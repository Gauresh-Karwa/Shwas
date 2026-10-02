from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.main import app
from app.models.db_models import Station, StationAQI


STATIONS = [
    ("STN_A", "Station A", 19.00, 72.80),
    ("STN_B", "Station B", 19.10, 72.90),
    ("STN_C", "Station C", 19.05, 72.82),  
]
QUERY_LAT, QUERY_LON = 19.05, 72.85


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


@pytest.fixture()
def client(db_session):

    def _override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def _seed_station(db_session, station_id, name, lat, lon, hours_of_history, end_time, base_aqi):

    db_session.add(Station(station_id=station_id, name=name, agency="CPCB", latitude=lat, longitude=lon))
    for h in range(hours_of_history, 0, -1):
        ts = end_time - timedelta(hours=h)
        wobble = 15.0 * ((ts.hour % 24) / 24.0)
        db_session.add(
            StationAQI(
                station_id=station_id,
                timestamp=ts,
                aqi_value=round(base_aqi + wobble),
                status="ok",
                category="Satisfactory",
                dominant_pollutant="PM2.5",
            )
        )
    db_session.commit()


@pytest.fixture()
def seeded_db(db_session):

    now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    _seed_station(db_session, "STN_A", "Station A", 19.00, 72.80, 24 * 14, now, base_aqi=80.0)
    _seed_station(db_session, "STN_B", "Station B", 19.10, 72.90, 24 * 14, now, base_aqi=120.0)
    _seed_station(db_session, "STN_C", "Station C", 19.05, 72.82, 48, now, base_aqi=95.0)
    return now


class TestPureIntegrationNoGnnCheckpoint:


    @pytest.fixture(autouse=True)
    def _no_checkpoint(self, monkeypatch):
        import app.routers.interpolate as interp_router
        import app.forecasting.spatial as spatial_module
        import app.forecasting.service as svc

        monkeypatch.setattr(interp_router, "get_gnn_model", lambda: None)
        monkeypatch.setattr(spatial_module, "get_gnn_model", lambda: None)
        monkeypatch.setattr(svc, "get_historical_weather", lambda *a, **k: __import__('pandas').DataFrame())
        monkeypatch.setattr(svc, "get_forecast_weather", lambda *a, **k: __import__('pandas').DataFrame())

    def test_forecast_station_uses_real_sarima(self, client, seeded_db):
        r = client.get("/api/forecast/STN_A", params={"steps": 6})
        assert r.status_code == 200
        body = r.json()
        assert body["station_id"] == "STN_A"
        assert body["model"] == "sarima"
        assert len(body["forecast"]) == 6
        assert all(0.0 <= p["aqi"] <= 500.0 for p in body["forecast"])

    def test_forecast_short_history_station_falls_back_to_naive(self, client, seeded_db):
        r = client.get("/api/forecast/STN_C", params={"steps": 4})
        assert r.status_code == 200
        body = r.json()
        assert body["model"] == "seasonal_naive"
        assert len(body["forecast"]) == 4

    def test_forecast_unknown_station_returns_404(self, client, seeded_db):
        r = client.get("/api/forecast/DOES_NOT_EXIST", params={"steps": 3})
        assert r.status_code == 404
        assert "DOES_NOT_EXIST" in r.json()["detail"]

    def test_interpolate_falls_back_to_idw_without_checkpoint(self, client, seeded_db):
        r = client.get("/api/interpolate", params={"lat": QUERY_LAT, "lon": QUERY_LON})
        assert r.status_code == 200
        body = r.json()
        assert body["model"] == "idw"
        assert 0.0 <= body["estimated_aqi"] <= 500.0
        assert body["stations_used"] == 3

    def test_coordinate_forecast_falls_back_to_idw_without_checkpoint(self, client, seeded_db):
        r = client.get(
            "/api/forecast/coordinate",
            params={"lat": QUERY_LAT, "lon": QUERY_LON, "steps": 5},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["model"] == "idw"
        assert len(body["forecast"]) == 5
        timestamps = [p["timestamp"] for p in body["forecast"]]
        assert timestamps == sorted(timestamps)

    def test_no_live_data_returns_503(self, client, db_session):
        # Stations exist with no AQI readings at all.
        db_session.add(Station(station_id="EMPTY", name="Empty", agency="CPCB", latitude=19.0, longitude=72.8))
        db_session.commit()
        r = client.get("/api/interpolate", params={"lat": 19.0, "lon": 72.8})
        assert r.status_code == 503


class TestIntegrationWithRealGnn:

    @pytest.fixture(autouse=True)
    def _inject_real_gnn(self, monkeypatch):
        import torch

        from app.ml.gnn_model import SpatialGNN

        torch.manual_seed(0)
        model = SpatialGNN(k_neighbours=3)
        model.eval()
        import app.routers.interpolate as interp_router
        import app.forecasting.spatial as spatial_module

        monkeypatch.setattr(interp_router, "get_gnn_model", lambda: model)
        monkeypatch.setattr(spatial_module, "get_gnn_model", lambda: model)

    def test_interpolate_runs_real_gnn_forward_pass(self, client, seeded_db):
        r = client.get("/api/interpolate", params={"lat": QUERY_LAT, "lon": QUERY_LON})
        assert r.status_code == 200
        body = r.json()
        assert body["model"] == "gnn"
        assert 0.0 <= body["estimated_aqi"] <= 500.0

    def test_coordinate_forecast_chains_real_sarima_into_real_gnn(self, client, seeded_db):
        r = client.get(
            "/api/forecast/coordinate",
            params={"lat": QUERY_LAT, "lon": QUERY_LON, "steps": 6},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["model"] == "gnn"
        assert body["stations_used"] == 3
        assert len(body["forecast"]) == 6
        for p in body["forecast"]:
            assert 0.0 <= p["aqi"] <= 500.0
            assert p["category"] in {
                "Good", "Satisfactory", "Moderate", "Poor", "Very Poor", "Severe"
            }

    def test_coordinate_forecast_uncertainty_end_to_end(self, client, seeded_db):
        r = client.get(
            "/api/forecast/coordinate",
            params={"lat": QUERY_LAT, "lon": QUERY_LON, "steps": 3, "uncertainty": "true"},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["model"] == "gnn"
        for p in body["forecast"]:
            assert p["uncertainty_std"] is not None
            assert p["aqi_lower"] <= p["aqi"] <= p["aqi_upper"]

    def test_station_forecast_uncertainty_end_to_end(self, client, seeded_db):
        r = client.get("/api/forecast/STN_A", params={"steps": 4, "uncertainty": "true"})
        assert r.status_code == 200
        body = r.json()
        assert body["model"] in ("sarima", "sarimax")
        for p in body["forecast"]:
            assert p["aqi_lower"] <= p["aqi"] <= p["aqi_upper"]


class TestRealCheckpointLoads:

    def test_real_checkpoint_loads_and_predicts(self, client, seeded_db):
        from app.ml.model_registry import get_gnn_model

        get_gnn_model.cache_clear()  # force a fresh load from disk
        model = get_gnn_model()
        assert model is not None, "models/gnn_best.pt did not load — check the checkpoint path/state_dict"

        r = client.get("/api/interpolate", params={"lat": QUERY_LAT, "lon": QUERY_LON})
        assert r.status_code == 200
        body = r.json()
        assert body["model"] == "gnn"
        assert 0.0 <= body["estimated_aqi"] <= 500.0