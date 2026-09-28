from __future__ import annotations
from datetime import datetime, timezone
from typing import Optional
from sqlalchemy.orm import Session
from app.models.db_models import Station, StationAQI


def get_live_snapshot(db: Session) -> list[dict]:
    stations = db.query(Station).all()
    result = []
    for station in stations:
        latest: Optional[StationAQI] = (
            db.query(StationAQI)
            .filter(
                StationAQI.station_id == station.station_id,
                StationAQI.status == "ok",
                StationAQI.aqi_value.isnot(None),
            )
            .order_by(StationAQI.timestamp.desc())
            .first()
        )
        if latest is None:
            continue
        result.append({
            "station_id": station.station_id,
            "name": station.name,
            "lat": station.latitude,
            "lon": station.longitude,
            "aqi": float(latest.aqi_value),
            "timestamp": latest.timestamp,
        })
    return result


def get_lagged_aqis(
    db: Session,
    station_id: str,
    reference_time: datetime,
    lag_hours: int,
) -> Optional[float]:
    from datetime import timedelta
    target_time = reference_time - timedelta(hours=lag_hours)
    record = (
        db.query(StationAQI)
        .filter(
            StationAQI.station_id == station_id,
            StationAQI.timestamp <= target_time,
            StationAQI.status == "ok",
            StationAQI.aqi_value.isnot(None),
        )
        .order_by(StationAQI.timestamp.desc())
        .first()
    )
    return float(record.aqi_value) if record else None
