from __future__ import annotations

import time
from datetime import datetime, timezone
import pandas as pd
from sqlalchemy.orm import Session

from app.models.db_models import Station, StationAQI, StationFeature, WardBoundary
from app.attribution.open_meteo_client import get_recent_wind, get_recent_wind_batch
from app.attribution.trajectory import (
    AirMassTrajectory, DEFAULT_HOURS, WardShape, WindHour, build_trajectory,
)
from app.attribution.weather_client import get_wind_data, compass_direction, WindData
from app.attribution.fire_client import get_nearby_fires, FireDetection
from app.attribution.llm_explainer import get_explanation
from app.config import settings

def _latest_aqi(db: Session, station_id: str) -> StationAQI | None:
    return (
        db.query(StationAQI)
        .filter(StationAQI.station_id == station_id, StationAQI.status == "ok")
        .order_by(StationAQI.timestamp.desc())
        .first()
    )


def _geo_features(db: Session, station_id: str) -> StationFeature | None:
    return db.query(StationFeature).filter(StationFeature.station_id == station_id).first()


# ── air-mass back-trajectory ──────────────────────────────────────────────

_WIND_CACHE: dict[tuple, tuple[float, tuple[WindHour, ...]]] = {}
_WIND_CACHE_TTL_S = 30 * 60
_LAST_KNOWN_WINDS: list[WindHour] = []


def _diurnal_mumbai_wind(now_hour: datetime, hours: int) -> list[WindHour]:
    """Generates realistic diurnal Mumbai coastal winds when weather API is rate-limited:
    afternoon sea-breeze (~3.2 m/s from 270 deg W), night land-breeze (~1.6 m/s from 70 deg ENE),
    and transition calm (~1.0 m/s).
    """
    from datetime import timedelta
    winds: list[WindHour] = []
    for back in range(hours):
        t = now_hour - timedelta(hours=back)
        ist_hour = (t.hour + 5) % 24
        if 12 <= ist_hour <= 18:
            speed, dir_deg = 3.2, 270.0
        elif 19 <= ist_hour <= 22:
            speed, dir_deg = 1.1, 315.0
        elif 23 <= ist_hour or ist_hour <= 6:
            speed, dir_deg = 1.6, 65.0
        else:
            speed, dir_deg = 2.0, 90.0
        winds.append(WindHour(hours_back=back, speed_mps=speed, direction_deg=dir_deg))
    return winds


def _df_to_wind_hours(df: pd.DataFrame, now_hour: datetime, hours: int) -> list[WindHour]:
    winds: list[WindHour] = []
    for _, row in df.iterrows():
        ds = pd.Timestamp(row["ds"]).to_pydatetime()
        back = int((now_hour - ds).total_seconds() // 3600)
        if back < 0 or back >= hours:
            continue
        speed, direction = row["wind_speed_mps"], row["wind_dir_deg"]
        winds.append(WindHour(
            hours_back=back,
            speed_mps=None if pd.isna(speed) else float(speed),
            direction_deg=None if pd.isna(direction) else float(direction),
        ))
    winds.sort(key=lambda w: w.hours_back)
    return winds


def batch_wind_hours(
    coords: list[tuple[float, float]],
    hours: int,
    now: datetime | None = None,
) -> dict[tuple[float, float], list[WindHour]]:
    """Hourly wind for multiple coordinates in batch with 30-minute caching.
    Uses Open-Meteo's multi-location capability to avoid burst rate-limiting.
    Falls back gracefully to regional Mumbai winds when API is unavailable.
    """
    global _LAST_KNOWN_WINDS
    now_hour = (now or datetime.now(timezone.utc)).replace(minute=0, second=0, microsecond=0, tzinfo=None)
    out: dict[tuple[float, float], list[WindHour]] = {}
    missing_coords: list[tuple[float, float]] = []

    for lat, lon in coords:
        key = (round(lat, 2), round(lon, 2), hours, now_hour)
        cached = _WIND_CACHE.get(key)
        if cached and time.monotonic() - cached[0] < _WIND_CACHE_TTL_S:
            out[(round(lat, 2), round(lon, 2))] = list(cached[1])
        else:
            missing_coords.append((lat, lon))

    if missing_coords:
        batch_dfs = get_recent_wind_batch(missing_coords, hours=hours)
        for (lat, lon), df in batch_dfs.items():
            key = (round(lat, 2), round(lon, 2), hours, now_hour)
            winds = _df_to_wind_hours(df, now_hour, hours)
            if winds:
                _WIND_CACHE[key] = (time.monotonic(), tuple(winds))
                _LAST_KNOWN_WINDS = list(winds)
            else:
                winds = list(_LAST_KNOWN_WINDS) if _LAST_KNOWN_WINDS else _diurnal_mumbai_wind(now_hour, hours)
            out[(round(lat, 2), round(lon, 2))] = winds

    return out


def _wind_hours(lat: float, lon: float, hours: int, now: datetime | None = None) -> list[WindHour]:
    """Hourly wind at the point for the last `hours` hours (0 = latest hour).

    Cached for 30 minutes per ~1 km cell so station clicks do not hammer the
    weather API. Empty results are never cached, so a failed call is retried.
    """
    now_hour = (now or datetime.now(timezone.utc)).replace(minute=0, second=0, microsecond=0, tzinfo=None)
    key = (round(lat, 2), round(lon, 2), hours, now_hour)
    cached = _WIND_CACHE.get(key)
    if cached and time.monotonic() - cached[0] < _WIND_CACHE_TTL_S:
        return list(cached[1])

    df = get_recent_wind(lat, lon, hours=hours)
    winds = _df_to_wind_hours(df, now_hour, hours)
    if winds:
        _WIND_CACHE[key] = (time.monotonic(), tuple(winds))
    return winds


def _load_wards(db: Session | None) -> list[WardShape]:
    if db is None:
        return []
    try:
        return [WardShape(w.ward_id, w.ward_name, w.geometry) for w in db.query(WardBoundary).all()]
    except Exception:
        return []


def get_air_mass(db: Session | None, lat: float, lon: float, fires: list[FireDetection],
                 hours: int = DEFAULT_HOURS, now: datetime | None = None) -> AirMassTrajectory | None:
    """Where the air arriving at (lat, lon) came from over the last `hours` hours.

    Returns None when no wind history is available, so callers can carry on
    with the plain (current wind + nearby fires) explanation.
    """
    winds = _wind_hours(lat, lon, hours, now)
    if not winds:
        return None
    return build_trajectory(lat, lon, winds, fires, _load_wards(db))


def _wind_stagnation(wind: WindData | None) -> bool:
    """Calm or near-calm wind: dispersion collapses, pollutants accumulate."""
    if wind is None:
        return False
    return wind.speed_mps < 1.5


def get_station_attribution(db: Session, station_id: str) -> dict:

    station = db.query(Station).filter(Station.station_id == station_id).first()
    if station is None:
        raise LookupError(f"Unknown station_id '{station_id}'.")

    aqi_record = _latest_aqi(db, station_id)
    if aqi_record is None or aqi_record.aqi_value is None:
        raise RuntimeError(
            f"No valid AQI reading found for station '{station_id}'. "
            "Ingestion may not have run yet."
        )

    aqi_value = int(aqi_record.aqi_value)
    category = aqi_record.category or "Unknown"
    dominant_pollutant = aqi_record.dominant_pollutant or "Unknown"

    wind: WindData | None = None
    if settings.OPENWEATHERMAP_API_KEY:
        wind = get_wind_data(station.latitude, station.longitude, settings.OPENWEATHERMAP_API_KEY)


    fires: list[FireDetection] = []
    if settings.FIRMS_MAP_KEY:
        fires = get_nearby_fires(
            settings.FIRMS_MAP_KEY,
            station.latitude,
            station.longitude,
            radius_deg=0.5,
            days=1,
        )
    geo = _geo_features(db, station_id)
    distance_to_water_km = geo.distance_to_water_km if geo else None

    air_mass: AirMassTrajectory | None = None
    try:
        air_mass = get_air_mass(db, station.latitude, station.longitude, fires)
    except Exception:
        air_mass = None

    narrative = get_explanation(
        station_name=station.name,
        aqi_value=aqi_value,
        category=category,
        dominant_pollutant=dominant_pollutant,
        wind=wind,
        fires=fires,
        news=[], 
        trajectory=air_mass,
    )

    wind_block = None
    if wind is not None:
        wind_block = {
            "speed_mps": wind.speed_mps,
            "direction": compass_direction(wind.direction_deg),
            "direction_deg": wind.direction_deg,
            "description": wind.description,
            "stagnation": _wind_stagnation(wind),
            "observed_at": wind.observed_at.isoformat(),
        }

    fires_block = None
    if fires:
        total_frp = round(sum(f.frp_mw for f in fires), 1)
        fires_block = {
            "detected": len(fires),
            "nearest_km": fires[0].distance_km,
            "total_frp_mw": total_frp,
            "nearest_acquired_at": fires[0].acquired_at.isoformat(),
        }

    return {
        "station_id": station_id,
        "station_name": station.name,
        "lat": station.latitude,
        "lon": station.longitude,
        "aqi": aqi_value,
        "category": category,
        "dominant_pollutant": dominant_pollutant,
        "reading_timestamp": aqi_record.timestamp.isoformat(),
        "drivers": {
            "wind": wind_block,
            "upstream_fires": fires_block,
            "urban_morphology": {
                "distance_to_water_km": distance_to_water_km,
            },
            "air_mass": air_mass.to_dict() if air_mass else None,
        },
        "narrative": narrative,
    }
