from __future__ import annotations

import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone, timedelta

import pandas as pd
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from sqlalchemy.pool import StaticPool

from app.main import app
from app.db import Base, get_db
from app.models.db_models import Station, StationAQI, CleanedReading, StationFeature


@pytest.fixture()
def db_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine)
    session = TestingSession()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture(autouse=True)
def _no_wind_history():
    """The air-mass trace calls the weather API; keep these tests offline."""
    empty = pd.DataFrame(columns=["ds", "wind_speed_mps", "wind_dir_deg"])
    with patch("app.attribution.attribution_service.get_recent_wind", return_value=empty):
        yield


@pytest.fixture()
def client(db_session):
    def _override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _seed_station(db, station_id="chembur-mumbai-mpcb", lat=19.062, lon=72.899):
    s = Station(
        station_id=station_id,
        name="Chembur, Mumbai - MPCB",
        agency="MPCB",
        latitude=lat,
        longitude=lon,
    )
    db.add(s)
    db.commit()


def _seed_aqi(db, station_id="chembur-mumbai-mpcb", aqi=168, category="Moderate", pollutant="PM2.5"):
    db.add(StationAQI(
        station_id=station_id,
        timestamp=datetime.now(tz=timezone.utc).replace(tzinfo=None),
        aqi_value=aqi,
        status="ok",
        category=category,
        dominant_pollutant=pollutant,
    ))
    db.commit()


def _seed_readings(db, station_id, pm25, pm10):
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


def _seed_geo_feature(db, station_id, distance_to_water_km=2.5):
    db.add(StationFeature(
        station_id=station_id,
        distance_to_water_km=distance_to_water_km,
    ))
    db.commit()


class TestAttributionNoExternalCalls:

    def test_attribution_returns_200_with_correct_shape(self, client, db_session):
        _seed_station(db_session)
        _seed_aqi(db_session)
        _seed_geo_feature(db_session, "chembur-mumbai-mpcb")

        # Monkeypatch all external calls so no network is needed
        with (
            patch("app.attribution.attribution_service.get_wind_data", return_value=None),
            patch("app.attribution.attribution_service.get_nearby_fires", return_value=[]),
            patch("app.attribution.attribution_service.get_explanation", return_value="Air quality is Moderate."),
        ):
            resp = client.get("/api/attribution/chembur-mumbai-mpcb")

        assert resp.status_code == 200
        body = resp.json()
        assert body["station_id"] == "chembur-mumbai-mpcb"
        assert body["aqi"] == 168
        assert body["category"] == "Moderate"
        assert body["dominant_pollutant"] == "PM2.5"
        assert "drivers" in body
        assert "narrative" in body
        assert body["narrative"] == "Air quality is Moderate."

    def test_attribution_unknown_station_returns_404(self, client, db_session):
        resp = client.get("/api/attribution/nonexistent-station-id")
        assert resp.status_code == 404

    def test_attribution_no_aqi_reading_returns_503(self, client, db_session):
        _seed_station(db_session)
        # No AQI seeded
        with (
            patch("app.attribution.attribution_service.get_wind_data", return_value=None),
            patch("app.attribution.attribution_service.get_nearby_fires", return_value=[]),
            patch("app.attribution.attribution_service.get_explanation", return_value="Fallback."),
        ):
            resp = client.get("/api/attribution/chembur-mumbai-mpcb")
        assert resp.status_code == 503

    def test_attribution_includes_wind_block_when_available(self, client, db_session):
        from app.attribution.weather_client import WindData
        _seed_station(db_session)
        _seed_aqi(db_session)

        mock_wind = WindData(
            speed_mps=1.1,
            direction_deg=90.0,
            description="clear sky",
            observed_at=datetime.now(tz=timezone.utc),
        )
        with (
            patch("app.attribution.attribution_service.settings.OPENWEATHERMAP_API_KEY", "mock-key"),
            patch("app.attribution.attribution_service.get_wind_data", return_value=mock_wind),
            patch("app.attribution.attribution_service.get_nearby_fires", return_value=[]),
            patch("app.attribution.attribution_service.get_explanation", return_value="Stagnant air."),
        ):
            resp = client.get("/api/attribution/chembur-mumbai-mpcb")

        assert resp.status_code == 200
        wind = resp.json()["drivers"]["wind"]
        assert wind is not None
        assert wind["speed_mps"] == 1.1
        assert wind["direction"] == "E"
        assert wind["stagnation"] is True  # 1.1 < 1.5 threshold

    def test_attribution_includes_fire_block_when_fires_detected(self, client, db_session):
        from app.attribution.fire_client import FireDetection
        _seed_station(db_session)
        _seed_aqi(db_session)

        mock_fire = FireDetection(
            latitude=19.05, longitude=72.91,
            distance_km=8.2, acquired_at=datetime.now(),
            frp_mw=22.0, confidence="h",
        )
        with (
            patch("app.attribution.attribution_service.settings.FIRMS_MAP_KEY", "mock-key"),
            patch("app.attribution.attribution_service.get_wind_data", return_value=None),
            patch("app.attribution.attribution_service.get_nearby_fires", return_value=[mock_fire]),
            patch("app.attribution.attribution_service.get_explanation", return_value="Fire smoke."),
        ):
            resp = client.get("/api/attribution/chembur-mumbai-mpcb")

        assert resp.status_code == 200
        fires = resp.json()["drivers"]["upstream_fires"]
        assert fires is not None
        assert fires["detected"] == 1
        assert fires["nearest_km"] == 8.2
        assert fires["total_frp_mw"] == 22.0


    def test_station_apportionment_combustion(self, client, db_session):
        _seed_station(db_session)
        _seed_readings(db_session, "chembur-mumbai-mpcb", pm25=80, pm10=100)
        resp = client.get("/api/attribution/chembur-mumbai-mpcb/apportionment")
        assert resp.status_code == 200
        body = resp.json()
        assert body["source_type"] == "combustion_dominated"
        assert body["data_available"] is True

    def test_station_apportionment_no_data(self, client, db_session):
        _seed_station(db_session)
        resp = client.get("/api/attribution/chembur-mumbai-mpcb/apportionment")
        assert resp.status_code == 200
        assert resp.json()["source_type"] == "insufficient_data"

    def test_city_apportionment_returns_all_stations(self, client, db_session):
        for slug in ("s1", "s2"):
            _seed_station(db_session, station_id=slug, lat=19.05, lon=72.87)
        _seed_readings(db_session, "s1", pm25=75, pm10=100)
        _seed_readings(db_session, "s2", pm25=20, pm10=100)

        resp = client.get("/api/attribution/city/apportionment")
        assert resp.status_code == 200
        body = resp.json()
        assert body["stations_evaluated"] == 2
        assert body["city_summary"]["combustion_dominated"] == 1
        assert body["city_summary"]["dust_dominated"] == 1
