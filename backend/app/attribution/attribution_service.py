from __future__ import annotations

from datetime import datetime, timezone
from sqlalchemy.orm import Session

from app.models.db_models import Station, StationAQI, StationFeature
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

    narrative = get_explanation(
        station_name=station.name,
        aqi_value=aqi_value,
        category=category,
        dominant_pollutant=dominant_pollutant,
        wind=wind,
        fires=fires,
        news=[], 
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
        },
        "narrative": narrative,
    }
