from app.ingestion.cpcb_client import fetch_city_data
from collections import defaultdict
from datetime import datetime

from app.config import settings
from app.db import SessionLocal
from app.models.db_models import Station, RawReading, CleanedReading, StationAQI
from app.aqi.calculator import compute_aqi
from app.ingestion.cleaner import clean_reading
from app.utils import slugify

def _parse_timestamp(raw: str) -> datetime:
    return datetime.strptime(raw, "%d-%m-%Y %H:%M:%S")

def _group_by_station_and_time(records: list) -> dict:
    grouped = defaultdict(dict)
    for r in records:
        station_id = slugify(r["station"])
        timestamp = _parse_timestamp(r["last_update"])
        grouped[(station_id, timestamp, r["station"])][r["pollutant_id"]] = (
            r["min_value"], r["max_value"], r["avg_value"]
        )
    return grouped

def run_ingestion_cycle(db=None, records=None) -> dict:
    owns_session = db is None
    if db is None:
        db = SessionLocal()

    if records is None:
        records = fetch_city_data(
            settings.CPCB_BASE_URL, settings.CPCB_RESOURCE_ID,
            settings.CPCB_API_KEY, settings.TARGET_CITY,
        )

    grouped = _group_by_station_and_time(records)

    summary = {
        "stations_processed": 0,
        "stations_skipped_unknown": 0,
        "raw_readings_written": 0,
        "raw_readings_duplicate_skipped": 0,
        "aqi_ok": 0,
        "aqi_insufficient": 0,
    }

    for (station_id, timestamp, station_name), pollutants in grouped.items():
        station = db.query(Station).filter_by(station_id = station_id).first()
        if not station:
            print(f"  Skipping unknown station (not seeded): {station_name}")
            summary["stations_skipped_unknown"] += 1
            continue

        cleaned_for_aqi = {}
        for pollutant_id, (raw_min,raw_max,raw_avg) in pollutants.items():
            exists = db.query(RawReading).filter_by(
                station_id = station_id, pollutant_id=pollutant_id,timestamp = timestamp
            ).first()

            if exists:
                summary["raw_readings_duplicate_skipped"] += 1
                continue

            cleaned = clean_reading(raw_min,raw_max,raw_avg)

            db.add(RawReading(
                station_id=station_id, pollutant_id=pollutant_id,
                min_value=cleaned.min_value if not cleaned.is_corrected else None,
                max_value=cleaned.max_value if not cleaned.is_corrected else None,
                avg_value=cleaned.avg_value, timestamp=timestamp,
            ))

            db.add(CleanedReading(
                station_id=station_id, pollutant_id=pollutant_id,
                min_value=cleaned.min_value, max_value=cleaned.max_value,
                avg_value=cleaned.avg_value, timestamp=timestamp,
                is_corrected=cleaned.is_corrected,
                correction_reason=cleaned.correction_reason,
            ))

            summary["raw_readings_written"] += 1

            if cleaned.avg_value is not None:
                cleaned_for_aqi[pollutant_id] = cleaned.avg_value

        aqi_exists = db.query(StationAQI).filter_by(
            station_id=station_id, timestamp=timestamp
        ).first()
        if aqi_exists:
            continue

        result = compute_aqi(cleaned_for_aqi)
        db.add(StationAQI(
            station_id=station_id, timestamp=timestamp,
            aqi_value=result.aqi, status=result.status,
            category=result.category, dominant_pollutant=result.dominant_pollutant,
            sub_indices=result.sub_indices, reason=result.reason,
        ))

        summary["stations_processed"] += 1
        if result.status == "ok":
            summary["aqi_ok"] += 1
        else:
            summary["aqi_insufficient"] += 1

    db.commit()
    if owns_session:
        db.close()

    return summary