import pandas as pd
import numpy as np
from app.forecasting.sarima_model import series_from_df, fit_sarima, sarima_forecast

def test_series_from_df_resampling_and_fill():
    dates = pd.date_range('2024-01-01 00:00:00', periods=48, freq='2h')
    df = pd.DataFrame({'ds': dates, 'y': np.full(len(dates), 75.0)})
    series = series_from_df(df, window_days=2)
    assert len(series) == 2 * 24 + 1
    assert series.isna().sum() == 0
    assert series.iloc[0] == 75.0

def test_series_from_df_window_filtering():
    dates = pd.date_range('2024-01-01 00:00:00', periods=24 * 30, freq='1h')
    df = pd.DataFrame({'ds': dates, 'y': np.full(len(dates), 100.0)})
    series = series_from_df(df, window_days=7)
    assert len(series) == 24 * 7 + 1

def test_fit_sarima_and_forecast_shape():
    dates = pd.date_range('2024-01-01 00:00:00', periods=24 * 14, freq='1h')
    t = np.arange(len(dates))
    y = 100.0 + 20.0 * np.sin(2 * np.pi * t / 24)
    s = pd.Series(y, index=dates)
    fit_res = fit_sarima(s)
    preds = sarima_forecast(fit_res, steps=24)
    assert len(preds) == 24
    assert all(isinstance(p, float) for p in preds)
    assert all(0.0 <= p <= 500.0 for p in preds)

def test_sarima_forecast_clipping():
    class DummyFit:
        def forecast(self, steps=24):
            return [-50.0, 600.0, 150.0]
    preds = sarima_forecast(DummyFit(), steps=3)
    assert preds == [0.0, 500.0, 150.0]
