import numpy as np
import pandas as pd
import pytest
from app.forecasting.sarima_model import align_exog_to_series, fit_sarimax, sarimax_forecast


def _make_dummy_series_and_weather(hours: int = 72):
    idx = pd.date_range("2026-09-01 00:00", periods=hours, freq="1h")
    y = pd.Series(50.0 + 10.0 * np.sin(np.linspace(0, 4 * np.pi, hours)), index=idx)
    weather_df = pd.DataFrame({
        "ds": idx,
        "temp_c": 28.0 + 4.0 * np.cos(np.linspace(0, 4 * np.pi, hours)),
        "humidity_pct": 70.0 + 10.0 * np.sin(np.linspace(0, 4 * np.pi, hours)),
    })
    return y, weather_df


def test_align_exog_to_series_valid():
    y, weather_df = _make_dummy_series_and_weather(72)
    aligned = align_exog_to_series(y, weather_df, ["temp_c", "humidity_pct"])
    assert aligned is not None
    assert len(aligned) == len(y)
    assert list(aligned.columns) == ["temp_c", "humidity_pct"]
    assert aligned.index.equals(y.index)


def test_align_exog_to_series_empty_or_none():
    y, _ = _make_dummy_series_and_weather(24)
    assert align_exog_to_series(y, None, ["temp_c"]) is None
    assert align_exog_to_series(y, pd.DataFrame(), ["temp_c"]) is None


def test_align_exog_to_series_excessive_missing_returns_none():
    y, weather_df = _make_dummy_series_and_weather(100)
    # Truncate weather to only first 50 hours (50% missing for y)
    truncated_weather = weather_df.iloc[:50]
    aligned = align_exog_to_series(y, truncated_weather, ["temp_c"])
    assert aligned is None


def test_fit_sarimax_and_forecast_shape():
    y, weather_df = _make_dummy_series_and_weather(72)
    exog = align_exog_to_series(y, weather_df, ["temp_c", "humidity_pct"])
    res = fit_sarimax(y, exog)
    assert res is not None

    future_idx = pd.date_range("2026-09-04 00:00", periods=6, freq="1h")
    exog_future = pd.DataFrame({
        "temp_c": [30.0] * 6,
        "humidity_pct": [65.0] * 6,
    }, index=future_idx)

    forecast = sarimax_forecast(res, exog_future, steps=6)
    assert len(forecast) == 6
    assert all(isinstance(v, float) for v in forecast)
    assert all(0.0 <= v <= 500.0 for v in forecast)


def test_sarimax_forecast_clipping():
    class DummyResult:
        def forecast(self, steps=2, exog=None):
            return [-15.0, 650.0]

    dummy_exog = pd.DataFrame({"temp_c": [25.0, 26.0]})
    clipped = sarimax_forecast(DummyResult(), dummy_exog, steps=2)
    assert clipped == [0.0, 500.0]
