from __future__ import annotations
import warnings
from datetime import datetime
import pandas as pd
from sqlalchemy.orm import Session
from statsmodels.tsa.statespace.sarimax import SARIMAX
from app.models.db_models import StationAQI

def load_station_series(db: Session, station_id: str) -> pd.DataFrame:
    records = db.query(StationAQI).filter(StationAQI.station_id == station_id, StationAQI.status == 'ok', StationAQI.aqi_value.isnot(None)).order_by(StationAQI.timestamp).all()
    return pd.DataFrame({'ds': [r.timestamp for r in records], 'y': [float(r.aqi_value) for r in records]})

def fit_sarima(series: pd.Series) -> object:
    with warnings.catch_warnings():
        warnings.simplefilter('ignore')
        model = SARIMAX(series, order=(1, 0, 1), seasonal_order=(1, 0, 0, 24), enforce_stationarity=False, enforce_invertibility=False)
        result = model.fit(disp=False, maxiter=50)
    return result

def sarima_forecast(fit_result, steps: int=24) -> list[float]:
    pred = fit_result.forecast(steps=steps)
    return [float(max(0.0, min(500.0, v))) for v in pred]

def sarima_forecast_with_ci(fit_result, steps: int=24, alpha: float=0.05) -> tuple[list[float], list[float], list[float]]:
    """Point forecast plus a (1 - alpha) confidence interval, straight from
    statsmodels' own get_forecast().conf_int() — no extra estimation needed,
    unlike the GNN's MC-dropout uncertainty. Returns (mean, lower, upper),
    each clipped to the valid [0, 500] AQI range like sarima_forecast()."""
    forecast_obj = fit_result.get_forecast(steps=steps)
    ci = forecast_obj.conf_int(alpha=alpha)
    mean = [float(max(0.0, min(500.0, v))) for v in forecast_obj.predicted_mean]
    lower = [float(max(0.0, min(500.0, v))) for v in ci.iloc[:, 0]]
    upper = [float(max(0.0, min(500.0, v))) for v in ci.iloc[:, 1]]
    return mean, lower, upper

def series_from_df(df: pd.DataFrame, window_days: int=14) -> pd.Series:
    s = df.set_index('ds')['y']
    s.index = pd.DatetimeIndex(s.index)
    if not s.empty and window_days:
        cutoff = s.index.max() - pd.Timedelta(days=window_days)
        s = s[s.index >= cutoff]
    full_idx = pd.date_range(s.index.min(), s.index.max(), freq='1h')
    s = s.reindex(full_idx).interpolate(method='time', limit=4).ffill()
    return s


def fit_sarimax(series: pd.Series, exog: pd.DataFrame) -> object:
    with warnings.catch_warnings():
        warnings.simplefilter('ignore')
        model = SARIMAX(series, exog=exog, order=(1, 0, 1), seasonal_order=(1, 0, 0, 24), enforce_stationarity=False, enforce_invertibility=False)
        result = model.fit(disp=False, maxiter=50)
    return result


def sarimax_forecast(fit_result, exog_future: pd.DataFrame, steps: int=24) -> list[float]:
    """Point forecast using exog_future as the (known-historical or
    forecast-API-provided) weather for each of the `steps` future hours.
    exog_future must have exactly `steps` rows and the same columns, in
    the same order, as the exog used to fit."""
    pred = fit_result.forecast(steps=steps, exog=exog_future)
    return [float(max(0.0, min(500.0, v))) for v in pred]


def align_exog_to_series(series: pd.Series, weather_df: pd.DataFrame, columns: list[str]) -> pd.DataFrame | None:
    if weather_df is None or weather_df.empty:
        return None
    w = weather_df.set_index('ds')[columns]
    w.index = pd.DatetimeIndex(w.index)
    w = w.reindex(series.index)
    missing_frac = w.isna().any(axis=1).mean()
    w = w.interpolate(method='time', limit=6).ffill().bfill()
    if missing_frac > 0.2 or w.isna().any().any():
        return None
    return w