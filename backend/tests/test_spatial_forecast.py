import pytest
from fastapi.testclient import TestClient

from app.forecasting import spatial
from app.main import app

SNAPSHOT = [
    {"station_id": "A", "name": "A", "lat": 19.00, "lon": 72.80, "aqi": 100.0, "timestamp": None},
    {"station_id": "B", "name": "B", "lat": 19.10, "lon": 72.90, "aqi": 200.0, "timestamp": None},
    {"station_id": "C", "name": "C", "lat": 19.05, "lon": 72.85, "aqi": 150.0, "timestamp": None},
]


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    spatial.clear_station_cache()
    monkeypatch.setattr(spatial, "get_live_snapshot", lambda db: SNAPSHOT)


def _fake_forecast(values_by_station):
    def fake(db, station_id, steps):
        return values_by_station[station_id][:steps]
    return fake


def test_idw_fallback_when_no_model(monkeypatch):
    monkeypatch.setattr(spatial, "get_gnn_model", lambda: None)
    monkeypatch.setattr(spatial, "_station_forecast", _fake_forecast({
        "A": [100.0] * 6, "B": [200.0] * 6, "C": [150.0] * 6}))
    out = spatial.run_coordinate_forecast(None, 19.05, 72.85, steps=6)
    assert out["model"] == "idw"
    assert len(out["forecast"]) == 6
    assert all(60 <= p["aqi"] <= 240 for p in out["forecast"])
    assert out["forecast"][0]["category"] in {"Satisfactory", "Moderate", "Poor"}


def test_gnn_used_and_lags_built_from_forecast(monkeypatch):
    calls = []

    def fake_gnn(model, lat, lon, snapshot, aqis, lag1, lag3, target):
        calls.append((list(aqis), list(lag1), list(lag3), target))
        return 111.0

    monkeypatch.setattr(spatial, "get_gnn_model", lambda: object())
    monkeypatch.setattr(spatial, "_gnn_step", fake_gnn)
    monkeypatch.setattr(spatial, "_station_forecast", _fake_forecast({
        "A": [101.0, 102.0, 103.0, 104.0],
        "B": [201.0, 202.0, 203.0, 204.0],
        "C": [151.0, 152.0, 153.0, 154.0]}))
    out = spatial.run_coordinate_forecast(None, 19.05, 72.85, steps=4)
    assert out["model"] == "gnn"
    assert all(p["aqi"] == 111.0 for p in out["forecast"])
    assert calls[0][0] == [101.0, 201.0, 151.0]
    assert calls[0][1] == [100.0, 200.0, 150.0]
    assert calls[0][2] == [None, None, None]
    assert calls[3][1] == [103.0, 203.0, 153.0]
    assert calls[3][2] == [101.0, 201.0, 151.0]


def test_zero_forecast_values_replaced_by_persistence(monkeypatch):
    seen = []
    monkeypatch.setattr(spatial, "get_gnn_model", lambda: object())
    monkeypatch.setattr(spatial, "_gnn_step",
                        lambda m, la, lo, sn, aqis, l1, l3, t: seen.append(list(aqis)) or 90.0)
    monkeypatch.setattr(spatial, "_station_forecast", _fake_forecast({
        "A": [0.0, 0.0], "B": [210.0, 0.0], "C": [0.0, 160.0]}))
    spatial.run_coordinate_forecast(None, 19.05, 72.85, steps=2)
    assert seen[0] == [100.0, 210.0, 150.0]
    assert seen[1] == [100.0, 210.0, 160.0]


def test_gnn_failure_falls_back_to_idw_per_hour(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("bad")
    monkeypatch.setattr(spatial, "get_gnn_model", lambda: object())
    monkeypatch.setattr(spatial, "_gnn_step", boom)
    monkeypatch.setattr(spatial, "_station_forecast", _fake_forecast({
        "A": [100.0] * 3, "B": [200.0] * 3, "C": [150.0] * 3}))
    out = spatial.run_coordinate_forecast(None, 19.05, 72.85, steps=3)
    assert out["model"] == "idw"


def test_no_stations_raises_lookup_error(monkeypatch):
    monkeypatch.setattr(spatial, "get_live_snapshot", lambda db: [])
    with pytest.raises(LookupError):
        spatial.run_coordinate_forecast(None, 19.0, 72.8)


def test_endpoint_route_not_shadowed_by_station_route(monkeypatch):
    import app.routers.forecast as fr
    monkeypatch.setattr(fr, "run_coordinate_forecast",
                        lambda db, lat, lon, steps, uncertainty=False: {"lat": lat, "lon": lon, "steps": steps, "forecast": []})
    from app.db import get_db
    app.dependency_overrides[get_db] = lambda: None
    try:
        r = TestClient(app).get("/api/forecast/coordinate?lat=19.07&lon=72.87&steps=5")
    finally:
        app.dependency_overrides.clear()
    assert r.status_code == 200
    assert r.json()["steps"] == 5