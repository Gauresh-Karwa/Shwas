"""
Ward Action Engine - data adapter.

Turns the live database and the existing analytics (ward exposure, waste-burning
detector, wind, fires, spatial forecast) into one WardContext per ward for
app.analytics.action_engine. All network and model calls go through the Providers
object so tests can replace them; a failed provider only blanks that ward's input
(the matching detector then reports "no data") and never fails the request.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Callable

from sqlalchemy.orm import Session

from app.analytics.action_engine import WardContext
from app.analytics.geo import point_in_geometry
from app.analytics.ward_exposure import compute_city_exposure
from app.analytics.waste_burning import detect_waste_burning
from app.config import settings
from app.interpolation.idw import haversine_km
from app.models.db_models import CleanedReading, Station, WardBoundary

IST_OFFSET = timedelta(hours=5, minutes=30)
DATA_MODES = ("legacy", "official_hourly")

MUMBAI_CENTER = (19.076, 72.8777)
FIRE_SEARCH_RADIUS_DEG = 0.5
BURNING_SITE_RADIUS_KM = 5.0      # a dump site this close to a ward centre (or inside it) is "near"
FORECAST_STEPS = 12
WIND_THREADS = 8

HISTORY_DAYS = 8
RECENT_HOURS = 3
BASELINE_HOURS = 24
FLAT_LOOKBACK_HOURS = 48
FLAT_MIN_READINGS = 6
FLAT_RELATIVE_RANGE = 0.02        # a channel whose whole range is within 2% of its mean is flat
BASELINE_MIN_READINGS = 3

PM25_IDS = ("PM2.5", "PM25")
PM10_IDS = ("PM10",)
NO2_IDS = ("NO2",)
CO_IDS = ("CO",)

def data_mode() -> str:
    mode = (getattr(settings, "ACTION_DATA_MODE", "legacy") or "legacy").strip().lower()
    return mode if mode in DATA_MODES else "legacy"


# ── providers (replaceable in tests) ──────────────────────────────────────

@dataclass
class Providers:
    winds: Callable[[float, float], list]                 # (lat, lon) -> [WindHour]
    fires: Callable[[], list]                             # () -> [FireDetection] for the whole city
    forecast: Callable[[Session, float, float], list]     # -> [(hours_ahead, aqi)]
    waste: Callable[[Session], list[dict]]          # (db) -> dump-site dicts


def _default_winds(lat: float, lon: float) -> list:
    from app.attribution.attribution_service import _wind_hours
    from app.attribution.trajectory import DEFAULT_HOURS
    return _wind_hours(lat, lon, DEFAULT_HOURS)


def _default_fires() -> list:
    if not settings.FIRMS_MAP_KEY:
        return []
    from app.attribution.fire_client import get_nearby_fires
    return get_nearby_fires(settings.FIRMS_MAP_KEY, MUMBAI_CENTER[0], MUMBAI_CENTER[1],
                            radius_deg=FIRE_SEARCH_RADIUS_DEG, days=1)


def _default_forecast(db: Session, lat: float, lon: float) -> list:
    from app.forecasting.spatial import run_coordinate_forecast
    result = run_coordinate_forecast(db, lat, lon, steps=FORECAST_STEPS)
    return [(i + 1, float(p["aqi"])) for i, p in enumerate(result["forecast"])]


def default_providers() -> Providers:
    return Providers(winds=_default_winds, fires=_default_fires,
                     forecast=_default_forecast, waste=lambda db: detect_waste_burning(db, False))


# ── station statistics ────────────────────────────────────────────────────

def local_hour(now_utc: datetime) -> int:
    return (now_utc + IST_OFFSET).hour


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _is_flat(values: list[float]) -> bool:
    mean = sum(values) / len(values)
    return (max(values) - min(values)) <= max(FLAT_RELATIVE_RANGE * abs(mean), 1e-6)


def _hour_distance(a: int, b: int) -> int:
    diff = abs(a - b) % 24
    return min(diff, 24 - diff)


def station_stats(db: Session, station_id: str, now: datetime) -> dict:
    """Numbers the detectors need from one station's recent cleaned readings (naive UTC)."""
    since = now - timedelta(days=HISTORY_DAYS)
    rows = (
        db.query(CleanedReading.pollutant_id, CleanedReading.timestamp, CleanedReading.avg_value)
        .filter(CleanedReading.station_id == station_id,
                CleanedReading.timestamp >= since,
                CleanedReading.timestamp <= now,
                CleanedReading.avg_value.isnot(None),
                CleanedReading.avg_value > 0)
        .all()
    )
    series: dict[str, list[tuple[datetime, float]]] = {"PM25": [], "PM10": [], "NO2": [], "CO": []}
    for pollutant, ts, value in rows:
        if pollutant in PM25_IDS:
            series["PM25"].append((ts, float(value)))
        elif pollutant in PM10_IDS:
            series["PM10"].append((ts, float(value)))
        elif pollutant in NO2_IDS:
            series["NO2"].append((ts, float(value)))
        elif pollutant in CO_IDS:
            series["CO"].append((ts, float(value)))

    def window(key: str, start_h: float, end_h: float) -> list[float]:
        lo, hi = now - timedelta(hours=start_h), now - timedelta(hours=end_h)
        return [v for ts, v in series[key] if lo <= ts <= hi]

    def recent(key: str) -> float | None:
        return _mean(window(key, RECENT_HOURS, 0))

    def same_hour_baseline(key: str) -> float | None:
        hour = local_hour(now)
        older = [v for ts, v in series[key]
                 if ts < now - timedelta(hours=BASELINE_HOURS)
                 and _hour_distance(local_hour(ts), hour) <= 1]
        return _mean(older) if len(older) >= BASELINE_MIN_READINGS else None

    pm25_24h = _mean(window("PM25", BASELINE_HOURS, 0))
    pm10_24h = _mean(window("PM10", BASELINE_HOURS, 0))
    fine = None
    if pm25_24h is not None and pm10_24h is not None and pm10_24h >= 1.0:
        fine = min(pm25_24h / pm10_24h, 1.0)

    gas_channels = []
    for key in ("NO2", "CO"):
        recent_values = window(key, FLAT_LOOKBACK_HOURS, 0)
        if len(recent_values) >= FLAT_MIN_READINGS:
            gas_channels.append(_is_flat(recent_values))
    gas_flat = None if not gas_channels else all(gas_channels)

    return {
        "fine_fraction": fine,
        "pm10_recent": recent("PM10"),
        "pm10_baseline": _mean(window("PM10", BASELINE_HOURS + RECENT_HOURS, RECENT_HOURS)),
        "no2_recent": recent("NO2"), "no2_baseline_same_hour": same_hour_baseline("NO2"),
        "co_recent": recent("CO"), "co_baseline_same_hour": same_hour_baseline("CO"),
        "gas_channels_flat": gas_flat,
    }


def nearest_station(stations: list[Station], lat: float, lon: float) -> tuple[Station | None, float | None]:
    best: tuple[Station | None, float | None] = (None, None)
    for st in stations:
        if st.latitude is None or st.longitude is None:
            continue
        d = haversine_km(lat, lon, st.latitude, st.longitude)
        if best[1] is None or d < best[1]:
            best = (st, d)
    return best


# ── wind, air mass, burning sites ─────────────────────────────────────────

def recent_speeds(winds: list, count: int = 3) -> list[float]:
    """Wind speeds for the latest hours, newest first; hours without a reading are skipped."""
    picked = sorted((w for w in winds if w.hours_back < count and w.speed_mps is not None),
                    key=lambda w: w.hours_back)
    return [w.speed_mps for w in picked]


def air_mass_summary(lat: float, lon: float, winds: list, fires: list, wards: list) -> dict | None:
    if not winds:
        return None
    from app.attribution.trajectory import DEFAULT_HOURS, build_trajectory
    trajectory = build_trajectory(lat, lon, winds, fires, wards)
    if trajectory is None:
        return None
    nearest_fire = (
        min(trajectory.fires_on_path, key=lambda x: x.distance_to_path_km)
        if trajectory.fires_on_path else None
    )
    return {
        "hours": DEFAULT_HOURS,
        "fires_on_path": len(trajectory.fires_on_path),
        "total_frp_mw": round(sum(f.frp_mw for f in trajectory.fires_on_path), 1),
        "marine_hours": trajectory.marine_hours,
        "mean_speed_mps": round(trajectory.mean_speed_mps, 1),
        "path_km": round(trajectory.path_km, 1),
        "origin_compass": trajectory.origin_compass,
        "origin_distance_km": round(trajectory.origin_distance_km, 1),
        "nearest_fire_hours_upwind": round(nearest_fire.hours_upwind, 1) if nearest_fire else None,
        "nearest_fire_dist_km": round(nearest_fire.distance_to_path_km, 1) if nearest_fire else None,
        "nearest_fire_frp_mw": round(nearest_fire.frp_mw, 1) if nearest_fire else None,
    }



def sites_near_ward(sites: list[dict], lat: float, lon: float, geometry: dict | None) -> list[dict]:
    near = []
    for site in sites:
        distance = haversine_km(lat, lon, site["lat"], site["lon"])
        inside = False
        if geometry:
            try:
                inside = point_in_geometry(site["lat"], site["lon"], geometry)
            except Exception:
                inside = False
        if inside or distance <= BURNING_SITE_RADIUS_KM:
            near.append({**site, "distance_km": round(distance, 1), "inside_ward": inside})
    return near


# ── main entry ────────────────────────────────────────────────────────────

@dataclass
class BuildMeta:
    stations_used: int = 0
    data_mode: str = "legacy"
    warnings: list[str] = field(default_factory=list)


def _safe(fn, *args, default=None, **kwargs):
    try:
        return fn(*args, **kwargs)
    except Exception:
        return default


def build_ward_contexts(db: Session, providers: Providers | None = None,
                        now: datetime | None = None) -> tuple[list[WardContext], BuildMeta]:
    """One WardContext per ward that has a boundary and a population. Raises LookupError
    when there is no live station data at all."""
    providers = providers or default_providers()
    now = now or datetime.now(tz=timezone.utc).replace(tzinfo=None)   # DB stores naive UTC
    mode = data_mode()
    official = mode == "official_hourly"

    summary = compute_city_exposure(db)
    meta = BuildMeta(stations_used=summary.stations_used, data_mode=mode)

    stations = db.query(Station).all()
    boundaries = {b.ward_id: b for b in db.query(WardBoundary).all()}
    from app.attribution.trajectory import WardShape
    shapes = [WardShape(b.ward_id, b.ward_name, b.geometry) for b in boundaries.values()]

    sites = _safe(providers.waste, db, default=[]) or []
    fires = _safe(providers.fires, default=[]) or []

    if providers.winds == _default_winds:
        from app.attribution.attribution_service import batch_wind_hours
        from app.attribution.trajectory import DEFAULT_HOURS
        ward_coords = [(w.lat, w.lon) for w in summary.wards]
        batch_map = _safe(batch_wind_hours, ward_coords, DEFAULT_HOURS, now=now, default={}) or {}
        wind_results = [batch_map.get((round(w.lat, 2), round(w.lon, 2)), []) for w in summary.wards]
    else:
        with ThreadPoolExecutor(max_workers=WIND_THREADS) as pool:
            wind_results = list(pool.map(lambda w: _safe(providers.winds, w.lat, w.lon, default=[]) or [],
                                         summary.wards))

    stats_cache: dict[str, dict] = {}
    contexts: list[WardContext] = []
    no_wind = no_forecast = 0
    for ward, winds in zip(summary.wards, wind_results):
        station, distance = nearest_station(stations, ward.lat, ward.lon)
        stats: dict = {}
        if station is not None:
            if station.station_id not in stats_cache:
                stats_cache[station.station_id] = _safe(station_stats, db, station.station_id, now, default={}) or {}
            stats = stats_cache[station.station_id]

        forecast = _safe(providers.forecast, db, ward.lat, ward.lon, default=None) or None
        if not winds:
            no_wind += 1
        if forecast is None:
            no_forecast += 1

        boundary = boundaries.get(ward.ward_id)
        contexts.append(WardContext(
            ward_id=ward.ward_id, ward_name=ward.ward_name, population=ward.population,
            lat=ward.lat, lon=ward.lon, aqi=ward.aqi, category=ward.category, aqi_method=ward.method,
            local_hour=local_hour(now),
            nearest_station_id=station.station_id if station else None,
            nearest_station_name=station.name if station else None,
            station_distance_km=distance,
            gas_channels_flat=stats.get("gas_channels_flat"),
            concentrations_valid=official, hourly_gas_valid=official,
            fine_fraction=stats.get("fine_fraction"),
            pm10_recent=stats.get("pm10_recent"), pm10_baseline=stats.get("pm10_baseline"),
            no2_recent=stats.get("no2_recent"), no2_baseline_same_hour=stats.get("no2_baseline_same_hour"),
            co_recent=stats.get("co_recent"), co_baseline_same_hour=stats.get("co_baseline_same_hour"),
            wind_speeds_recent=recent_speeds(winds),
            forecast=forecast,
            burning_sites=sites_near_ward(sites, ward.lat, ward.lon, boundary.geometry if boundary else None),
            air_mass=_safe(air_mass_summary, ward.lat, ward.lon, winds, fires, shapes, default=None),
        ))

    if no_wind:
        meta.warnings.append(f"Wind data was unavailable for {no_wind} ward(s).")
    if no_forecast:
        meta.warnings.append(f"Forecast was unavailable for {no_forecast} ward(s).")
    return contexts, meta