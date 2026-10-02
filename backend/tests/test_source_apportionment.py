from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.analytics.source_apportionment import (
    get_source_apportionment,
    get_city_apportionment,
    COMBUSTION_THRESHOLD,
    DUST_THRESHOLD,
)
from app.models.db_models import Station, CleanedReading

@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()
    engine.dispose()


def _add_station(db, station_id="kurla-mumbai-mpcb", lat=19.07, lon=72.88):
    s = Station(
        station_id=station_id,
        name="Kurla, Mumbai - MPCB",
        agency="MPCB",
        latitude=lat,
        longitude=lon,
    )
    db.add(s)
    db.commit()
    return s


def _add_readings(db, station_id, pm25, pm10):
    """Insert a single recent hour of PM2.5 and PM10 readings."""
    from datetime import datetime, timedelta, timezone
    now = datetime.now(tz=timezone.utc).replace(tzinfo=None)
    for pollutant, value in [("PM2.5", pm25), ("PM10", pm10)]:
        db.add(CleanedReading(
            station_id=station_id,
            pollutant_id=pollutant,
            avg_value=value,
            min_value=value * 0.9,
            max_value=value * 1.1,
            timestamp=now - timedelta(minutes=30),
        ))
    db.commit()


def test_combustion_dominated_classification(db):
    _add_station(db)
    _add_readings(db, "kurla-mumbai-mpcb", pm25=80.0, pm10=100.0)
    result = get_source_apportionment(db, "kurla-mumbai-mpcb")
    assert result["data_available"] is True
    assert result["source_type"] == "combustion_dominated"
    assert result["fine_fraction"] >= COMBUSTION_THRESHOLD


def test_dust_dominated_classification(db):
    _add_station(db)
    _add_readings(db, "kurla-mumbai-mpcb", pm25=20.0, pm10=100.0)
    result = get_source_apportionment(db, "kurla-mumbai-mpcb")
    assert result["data_available"] is True
    assert result["source_type"] == "dust_dominated"
    assert result["fine_fraction"] <= DUST_THRESHOLD


def test_mixed_classification(db):
    _add_station(db)
    _add_readings(db, "kurla-mumbai-mpcb", pm25=50.0, pm10=100.0)
    result = get_source_apportionment(db, "kurla-mumbai-mpcb")
    assert result["data_available"] is True
    assert result["source_type"] == "mixed"
    assert DUST_THRESHOLD < result["fine_fraction"] < COMBUSTION_THRESHOLD


def test_insufficient_data_when_no_readings(db):
    _add_station(db)
    result = get_source_apportionment(db, "kurla-mumbai-mpcb")
    assert result["data_available"] is False
    assert result["source_type"] == "insufficient_data"
    assert result["fine_fraction"] is None


def test_fine_fraction_clamped_to_one(db):

    _add_station(db)
    _add_readings(db, "kurla-mumbai-mpcb", pm25=120.0, pm10=100.0)
    result = get_source_apportionment(db, "kurla-mumbai-mpcb")
    assert result["data_available"] is True
    assert result["fine_fraction"] <= 1.0, "fine_fraction must be clamped to 1.0 on bad sensor data"


def test_city_apportionment_aggregates_multiple_stations(db):
    for slug, pm25, pm10 in [
        ("s1", 80, 100),   # combustion
        ("s2", 20, 100),   # dust
        ("s3", 50, 100),   # mixed
    ]:
        _add_station(db, station_id=slug, lat=19.0 + 0.01 * len(slug), lon=72.85)
        _add_readings(db, slug, pm25, pm10)

    result = get_city_apportionment(db)
    assert result["stations_evaluated"] == 3
    summary = result["city_summary"]
    assert summary["combustion_dominated"] == 1
    assert summary["dust_dominated"] == 1
    assert summary["mixed"] == 1
    assert len(result["stations"]) == 3
    for entry in result["stations"]:
        assert "station_name" in entry
