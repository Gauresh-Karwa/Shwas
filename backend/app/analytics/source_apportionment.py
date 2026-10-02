from __future__ import annotations

from datetime import datetime, timedelta, timezone
from sqlalchemy.orm import Session
from sqlalchemy import and_

from app.models.db_models import CleanedReading, Station

COMBUSTION_THRESHOLD = 0.65
DUST_THRESHOLD = 0.40

LOOKBACK_HOURS = 24

PM25_IDS = {"PM2.5", "PM25", "pm2.5", "pm25"}
PM10_IDS = {"PM10", "pm10"}


def _mean_pollutant(
    db: Session,
    station_id: str,
    pollutant_ids: set[str],
    since: datetime,
) -> float | None:

    rows = (
        db.query(CleanedReading.avg_value)
        .filter(
            and_(
                CleanedReading.station_id == station_id,
                CleanedReading.pollutant_id.in_(pollutant_ids),
                CleanedReading.avg_value.isnot(None),
                CleanedReading.avg_value > 0,
                CleanedReading.timestamp >= since,
            )
        )
        .all()
    )
    if not rows:
        return None
    values = [r[0] for r in rows]
    return sum(values) / len(values)


def _classify(ratio: float) -> str:
    if ratio >= COMBUSTION_THRESHOLD:
        return "combustion_dominated"
    if ratio <= DUST_THRESHOLD:
        return "dust_dominated"
    return "mixed"


def get_source_apportionment(db: Session, station_id: str) -> dict:
    since = datetime.now(tz=timezone.utc).replace(tzinfo=None) - timedelta(hours=LOOKBACK_HOURS)

    pm25 = _mean_pollutant(db, station_id, PM25_IDS, since)
    pm10 = _mean_pollutant(db, station_id, PM10_IDS, since)

    if pm25 is None or pm10 is None or pm10 < 1.0:
        return {
            "station_id": station_id,
            "pm25_mean_ug_m3": pm25,
            "pm10_mean_ug_m3": pm10,
            "fine_fraction": None,
            "source_type": "insufficient_data",
            "interpretation": "Insufficient PM2.5 and PM10 readings in the last 24 hours.",
            "window_hours": LOOKBACK_HOURS,
            "data_available": False,
        }

    ratio = min(pm25 / pm10, 1.0)
    source = _classify(ratio)

    interpretations = {
        "combustion_dominated": (
            "Fine particulate fraction is high (>= 65%). "
            "Dominant source is likely high-temperature combustion: "
            "vehicle exhaust, refinery flue gas, biomass burning, or secondary sulfate/nitrate aerosols."
        ),
        "mixed": (
            "Fine fraction is moderate (40 to 65%). "
            "Mixed urban background: combination of traffic emissions and mechanical dust resuspension."
        ),
        "dust_dominated": (
            "Coarse fraction dominates (PM2.5/PM10 <= 40%). "
            "Primary source is likely mechanical dispersion: road dust, construction debris, or sea spray."
        ),
    }

    return {
        "station_id": station_id,
        "pm25_mean_ug_m3": round(pm25, 2),
        "pm10_mean_ug_m3": round(pm10, 2),
        "fine_fraction": round(ratio, 3),
        "source_type": source,
        "interpretation": interpretations[source],
        "window_hours": LOOKBACK_HOURS,
        "data_available": True,
    }


def get_city_apportionment(db: Session) -> dict:

    stations = db.query(Station).all()
    results = []
    combustion_count = 0
    mixed_count = 0
    dust_count = 0
    insufficient_count = 0

    for s in stations:
        r = get_source_apportionment(db, s.station_id)
        r["station_name"] = s.name
        results.append(r)
        if r["source_type"] == "combustion_dominated":
            combustion_count += 1
        elif r["source_type"] == "mixed":
            mixed_count += 1
        elif r["source_type"] == "dust_dominated":
            dust_count += 1
        else:
            insufficient_count += 1

    return {
        "window_hours": LOOKBACK_HOURS,
        "stations_evaluated": len(stations),
        "city_summary": {
            "combustion_dominated": combustion_count,
            "mixed": mixed_count,
            "dust_dominated": dust_count,
            "insufficient_data": insufficient_count,
        },
        "stations": results,
    }
