from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from app.models.db_models import StationAQI

def seasonal_naive_forecast(db: Session, station_id: str, target_timestamp: datetime) -> float | None:
    lookback_time = target_timestamp - timedelta(hours=24)
    record = db.query(StationAQI).filter(StationAQI.station_id == station_id, StationAQI.timestamp == lookback_time, StationAQI.status == 'ok').first()
    return float(record.aqi_value) if record and record.aqi_value is not None else None
