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

def series_from_df(df: pd.DataFrame, window_days: int=14) -> pd.Series:
    s = df.set_index('ds')['y']
    s.index = pd.DatetimeIndex(s.index)
    if not s.empty and window_days:
        cutoff = s.index.max() - pd.Timedelta(days=window_days)
        s = s[s.index >= cutoff]
    full_idx = pd.date_range(s.index.min(), s.index.max(), freq='1h')
    s = s.reindex(full_idx).interpolate(method='time', limit=4).ffill()
    return s
