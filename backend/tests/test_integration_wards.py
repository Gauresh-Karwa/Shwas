from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.main import app
from app.models.db_models import Station, StationAQI, WardBoundary, WardPopulation

WARD_A_GEOMETRY = {"type": "Polygon", "coordinates": [[[72.80, 19.00], [72.82, 19.00], [72.82, 19.02], [72.80, 19.02], [72.80, 19.00]]]}
WARD_B_GEOMETRY = {"type": "Polygon", "coordinates": [[[72.88, 19.08], [72.90, 19.08], [72.90, 19.10], [72.88, 19.10], [72.88, 19.10]]]}


@pytest.fixture()
def db_session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture()
def client(db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


@pytest.fixture()
def seeded_wards(db_session):
    db_session.add(Station(station_id="STN_A", name="Near Ward A", agency="CPCB", latitude=19.01, longitude=72.81))
    db_session.add(StationAQI(station_id="STN_A", timestamp=__import__("datetime").datetime(2026, 1, 1), aqi_value=250.0, status="ok", category="Poor", dominant_pollutant="PM2.5"))
    db_session.add(Station(station_id="STN_B", name="Near Ward B", agency="CPCB", latitude=19.09, longitude=72.89))
    db_session.add(StationAQI(station_id="STN_B", timestamp=__import__("datetime").datetime(2026, 1, 1), aqi_value=40.0, status="ok", category="Good", dominant_pollutant="PM2.5"))
    db_session.add(Station(station_id="STN_C", name="Third station", agency="CPCB", latitude=19.05, longitude=72.85))
    db_session.add(StationAQI(station_id="STN_C", timestamp=__import__("datetime").datetime(2026, 1, 1), aqi_value=100.0, status="ok", category="Moderate", dominant_pollutant="PM2.5"))

    db_session.add(WardBoundary(ward_id="WARD_A", ward_name="Ward A", geometry=WARD_A_GEOMETRY))
    db_session.add(WardPopulation(ward_id="WARD_A", population=100_000, census_year=2011))
    db_session.add(WardBoundary(ward_id="WARD_B", ward_name="Ward B", geometry=WARD_B_GEOMETRY))
    db_session.add(WardPopulation(ward_id="WARD_B", population=50_000, census_year=2011))
    db_session.commit()


class TestWardExposureNoGnnCheckpoint:

    @pytest.fixture(autouse=True)
    def _no_checkpoint(self, monkeypatch):
        import app.analytics.ward_exposure as we
        monkeypatch.setattr(we, "get_gnn_model", lambda: None)

    def test_wards_endpoint_returns_both_wards_with_idw(self, client, seeded_wards):
        r = client.get("/api/wards")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ok"
        assert body["stations_used"] == 3
        assert {w["ward_id"] for w in body["wards"]} == {"WARD_A", "WARD_B"}
        assert all(w["method"] == "idw" for w in body["wards"])

    def test_population_by_category_sums_to_total(self, client, seeded_wards):
        r = client.get("/api/wards")
        body = r.json()
        assert sum(body["population_by_category"].values()) == body["total_population"]
        assert body["total_population"] == 150_000

    def test_worst_ward_sorted_first(self, client, seeded_wards):
        r = client.get("/api/wards")
        wards = client.get("/api/wards").json()["wards"]
        assert wards[0]["ward_id"] == "WARD_A"
        assert wards[0]["aqi"] > wards[-1]["aqi"]

    def test_ward_missing_population_is_excluded(self, client, db_session, seeded_wards):
        db_session.add(WardBoundary(ward_id="WARD_C", ward_name="No Census Row", geometry=WARD_A_GEOMETRY))
        db_session.commit()
        r = client.get("/api/wards")
        ids = {w["ward_id"] for w in r.json()["wards"]}
        assert "WARD_C" not in ids

    def test_no_live_station_data_returns_503(self, client, db_session):
        db_session.add(WardBoundary(ward_id="WARD_A", ward_name="Ward A", geometry=WARD_A_GEOMETRY))
        db_session.add(WardPopulation(ward_id="WARD_A", population=1000, census_year=2011))
        db_session.commit()
        r = client.get("/api/wards")
        assert r.status_code == 503


class TestWardExposureWithRealGnn:

    @pytest.fixture(autouse=True)
    def _inject_real_gnn(self, monkeypatch):
        import torch
        from app.ml.gnn_model import SpatialGNN

        torch.manual_seed(0)
        model = SpatialGNN(k_neighbours=3)
        model.eval()

        import app.analytics.ward_exposure as we
        monkeypatch.setattr(we, "get_gnn_model", lambda: model)

    def test_wards_endpoint_uses_gnn(self, client, seeded_wards):
        r = client.get("/api/wards")
        assert r.status_code == 200
        body = r.json()
        assert all(w["method"] == "gnn" for w in body["wards"])
        for w in body["wards"]:
            assert 0.0 <= w["aqi"] <= 500.0