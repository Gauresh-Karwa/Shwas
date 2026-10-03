from __future__ import annotations

from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.analytics import grid_scan
from app.db import Base, get_db
from app.main import app
from app.models.db_models import Station, StationAQI, WardBoundary, WardPopulation
from app.analytics.sensor_placement import EXCLUSION_RADIUS_KM

BIG_WARD = {
    "type": "Polygon",
    "coordinates": [[[72.75, 18.85], [73.00, 18.85], [73.00, 19.30], [72.75, 19.30], [72.75, 18.85]]],
}


@pytest.fixture()
def db_session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    grid_scan.clear_grid_cache()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()
        grid_scan.clear_grid_cache()


@pytest.fixture()
def client(db_session):
    def _override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture()
def seeded(db_session):
    db_session.add(Station(station_id="S1", name="S1", agency="CPCB", latitude=19.00, longitude=72.80))
    db_session.add(StationAQI(station_id="S1", timestamp=datetime(2026, 1, 1), aqi_value=90.0, status="ok", category="Satisfactory", dominant_pollutant="PM2.5"))
    db_session.add(Station(station_id="S2", name="S2", agency="CPCB", latitude=19.20, longitude=72.95))
    db_session.add(StationAQI(station_id="S2", timestamp=datetime(2026, 1, 1), aqi_value=180.0, status="ok", category="Moderate", dominant_pollutant="PM2.5"))
    db_session.add(WardBoundary(ward_id="BIG", ward_name="Big Ward", geometry=BIG_WARD))
    db_session.add(WardPopulation(ward_id="BIG", population=500_000, census_year=2011))
    db_session.commit()


@pytest.fixture(autouse=True)
def _inject_real_gnn(monkeypatch):
    import torch
    from app.ml.gnn_model import SpatialGNN

    torch.manual_seed(0)
    model = SpatialGNN(k_neighbours=3)
    model.eval()
    monkeypatch.setattr(grid_scan, "get_gnn_model", lambda: model)


class TestSensorPlacementEndpoint:
    def test_returns_recommendations_with_real_gnn(self, client, seeded):
        r = client.get("/api/recommendations/sensor-placement", params={"top_k": 3})
        assert r.status_code == 200
        body = r.json()
        assert isinstance(body, list)
        for site in body:
            assert site["nearest_station_distance_km"] == -1.0 or site["nearest_station_distance_km"] >= EXCLUSION_RADIUS_KM
            assert site["reason"] in ("unmonitored_ward", "coverage_gap")
            assert 0.0 <= site["estimated_aqi"] <= 500.0
            assert site["uncertainty_std"] >= 0.0

    def test_no_live_data_returns_503(self, client, db_session):
        db_session.add(WardBoundary(ward_id="BIG", ward_name="Big Ward", geometry=BIG_WARD))
        db_session.add(WardPopulation(ward_id="BIG", population=1000, census_year=2011))
        db_session.commit()
        r = client.get("/api/recommendations/sensor-placement")
        assert r.status_code == 503

    def test_exclusion_radius_query_param_is_applied(self, client, seeded):
        wide = client.get("/api/recommendations/sensor-placement", params={"exclusion_radius_km": 100.0}).json()
        narrow = client.get("/api/recommendations/sensor-placement", params={"exclusion_radius_km": 0.0}).json()
        assert len(wide) <= len(narrow)


class TestHotspotsEndpoint:
    def test_returns_hotspots_with_real_gnn(self, client, seeded):
        r = client.get("/api/analytics/hotspots", params={"threshold": 0.0})
        assert r.status_code == 200
        body = r.json()
        assert isinstance(body, list)
        for h in body:
            assert h["lcb"] <= h["estimated_aqi"] or h["method"] == "idw"
            assert h["lcb"] >= 0.0

    def test_high_threshold_can_return_empty_list(self, client, seeded):
        r = client.get("/api/analytics/hotspots", params={"threshold": 499.9})
        assert r.status_code == 200
        assert r.json() == []

    def test_no_live_data_returns_503(self, client, db_session):
        db_session.add(WardBoundary(ward_id="BIG", ward_name="Big Ward", geometry=BIG_WARD))
        db_session.add(WardPopulation(ward_id="BIG", population=1000, census_year=2011))
        db_session.commit()
        r = client.get("/api/analytics/hotspots")
        assert r.status_code == 503