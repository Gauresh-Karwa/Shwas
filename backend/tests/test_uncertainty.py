import numpy as np
import pandas as pd
import pytest
import torch

from app.forecasting import spatial
from app.forecasting.sarima_model import fit_sarima, sarima_forecast, sarima_forecast_with_ci
from app.ml.gnn_model import SpatialGNN, gnn_interpolate, gnn_interpolate_with_uncertainty

STATION_LATS = [19.0, 19.1, 19.2, 19.05, 19.15]
STATION_LONS = [72.8, 72.9, 72.85, 72.82, 72.88]
STATION_AQIS = [80.0, 120.0, 95.0, 110.0, 70.0]

def test_plain_interpolate_stays_deterministic():
    torch.manual_seed(0)
    model = SpatialGNN(k_neighbours=3, dropout=0.3)
    a = gnn_interpolate(model, 19.05, 72.85, STATION_LATS, STATION_LONS, STATION_AQIS, hour=10, weekday=2)
    b = gnn_interpolate(model, 19.05, 72.85, STATION_LATS, STATION_LONS, STATION_AQIS, hour=10, weekday=2)
    assert a == b


def test_uncertainty_produces_nonzero_spread_and_valid_bounds():
    torch.manual_seed(0)
    model = SpatialGNN(k_neighbours=3, dropout=0.3)
    mean, std = gnn_interpolate_with_uncertainty(
        model, 19.05, 72.85, STATION_LATS, STATION_LONS, STATION_AQIS,
        hour=10, weekday=2, n_samples=25,
    )
    assert 0.0 <= mean <= 500.0
    assert std > 0.0


def test_uncertainty_restores_eval_mode():
    model = SpatialGNN(k_neighbours=3, dropout=0.2)
    model.eval()
    gnn_interpolate_with_uncertainty(
        model, 19.05, 72.85, STATION_LATS, STATION_LONS, STATION_AQIS,
        hour=10, weekday=2, n_samples=5,
    )
    assert model.training is False


def test_uncertainty_single_sample_has_zero_std():
    model = SpatialGNN(k_neighbours=3, dropout=0.2)
    _, std = gnn_interpolate_with_uncertainty(
        model, 19.05, 72.85, STATION_LATS, STATION_LONS, STATION_AQIS,
        hour=10, weekday=2, n_samples=1,
    )
    assert std == 0.0

@pytest.fixture
def sarima_fit():
    dates = pd.date_range("2024-01-01", periods=24 * 14, freq="1h")
    t = np.arange(len(dates))
    y = 100.0 + 20.0 * np.sin(2 * np.pi * t / 24) + np.random.RandomState(0).normal(0, 3, len(dates))
    return fit_sarima(pd.Series(y, index=dates))


def test_ci_mean_matches_point_forecast(sarima_fit):
    point = sarima_forecast(sarima_fit, steps=6)
    mean, lower, upper = sarima_forecast_with_ci(sarima_fit, steps=6)
    assert mean == point
    assert all(lo <= m <= up for lo, m, up in zip(lower, mean, upper))


def test_ci_bounds_are_clipped_to_valid_range(sarima_fit):
    _, lower, upper = sarima_forecast_with_ci(sarima_fit, steps=6)
    assert all(0.0 <= v <= 500.0 for v in lower + upper)



def test_run_forecast_default_shape_unchanged(monkeypatch):
    from app.forecasting import service

    monkeypatch.setattr(service, "load_station_series", lambda db, sid: pd.DataFrame({"ds": [], "y": []}))
    monkeypatch.setattr(service, "seasonal_naive_forecast", lambda db, sid, ts: 42.0)
    out = service.run_forecast(db=None, station_id="X", steps=3)
    assert out["model"] == "seasonal_naive"
    assert set(out["forecast"][0].keys()) == {"timestamp", "aqi"}


def test_run_forecast_uncertainty_adds_ci_fields_for_sarima(monkeypatch):
    from app.forecasting import service

    dates = pd.date_range("2024-01-01", periods=24 * 14, freq="1h")
    df = pd.DataFrame({"ds": dates, "y": np.full(len(dates), 100.0)})
    monkeypatch.setattr(service, "load_station_series", lambda db, sid: df)
    out = service.run_forecast(db=None, station_id="X", steps=4, uncertainty=True)
    assert out["model"] == "sarima"
    for p in out["forecast"]:
        assert p["aqi_lower"] <= p["aqi"] <= p["aqi_upper"]


def test_run_forecast_uncertainty_naive_fallback_has_null_ci(monkeypatch):
    from app.forecasting import service

    monkeypatch.setattr(service, "load_station_series", lambda db, sid: pd.DataFrame({"ds": [], "y": []}))
    monkeypatch.setattr(service, "seasonal_naive_forecast", lambda db, sid, ts: 55.0)
    out = service.run_forecast(db=None, station_id="X", steps=2, uncertainty=True)
    assert out["model"] == "seasonal_naive"
    assert all(p["aqi_lower"] is None and p["aqi_upper"] is None for p in out["forecast"])



SNAPSHOT = [
    {"station_id": "A", "name": "A", "lat": 19.00, "lon": 72.80, "aqi": 100.0, "timestamp": None},
    {"station_id": "B", "name": "B", "lat": 19.10, "lon": 72.90, "aqi": 200.0, "timestamp": None},
]


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    spatial.clear_station_cache()
    monkeypatch.setattr(spatial, "get_live_snapshot", lambda db: SNAPSHOT)
    monkeypatch.setattr(
        spatial, "_station_forecast",
        lambda db, sid, steps: [110.0] * steps if sid == "A" else [210.0] * steps,
    )


def test_coordinate_forecast_default_shape_unchanged(monkeypatch):
    monkeypatch.setattr(spatial, "get_gnn_model", lambda: object())
    monkeypatch.setattr(spatial, "_gnn_step", lambda *a, **k: 150.0)
    out = spatial.run_coordinate_forecast(None, 19.05, 72.85, steps=2)
    assert set(out["forecast"][0].keys()) == {"timestamp", "aqi", "category"}


def test_coordinate_forecast_uncertainty_adds_band_for_gnn_hours(monkeypatch):
    monkeypatch.setattr(spatial, "get_gnn_model", lambda: object())
    monkeypatch.setattr(spatial, "_gnn_step_with_uncertainty", lambda *a, **k: (150.0, 10.0))
    out = spatial.run_coordinate_forecast(None, 19.05, 72.85, steps=2, uncertainty=True)
    for p in out["forecast"]:
        assert p["aqi_lower"] < p["aqi"] < p["aqi_upper"]
        assert p["uncertainty_std"] == 10.0


def test_coordinate_forecast_uncertainty_idw_fallback_has_null_band(monkeypatch):
    monkeypatch.setattr(spatial, "get_gnn_model", lambda: None)
    out = spatial.run_coordinate_forecast(None, 19.05, 72.85, steps=2, uncertainty=True)
    assert out["model"] == "idw"
    assert all(p["uncertainty_std"] is None for p in out["forecast"])