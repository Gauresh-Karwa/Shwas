from __future__ import annotations
from datetime import datetime, timezone, timedelta
from typing import Optional
from sqlalchemy.orm import Session
from app.forecasting.sarima_model import (
    load_station_series,
    series_from_df,
    fit_sarima,
    sarima_forecast,
)
from app.forecasting.baseline import seasonal_naive_forecast

MIN_ROWS_FOR_SARIMA = 7 * 24


def run_forecast(
    db: Session,
    station_id: str,
    steps: int = 24,
) -> dict:
    df = load_station_series(db, station_id)
    now = datetime.now(tz=timezone.utc)

    if len(df) >= MIN_ROWS_FOR_SARIMA:
        try:
            series = series_from_df(df)
            fit = fit_sarima(series)
            values = sarima_forecast(fit, steps=steps)
            model_used = "sarima"
        except Exception:
            values = _naive_fallback(db, station_id, now, steps)
            model_used = "seasonal_naive"
    else:
        values = _naive_fallback(db, station_id, now, steps)
        model_used = "seasonal_naive"

    timestamps = [
        (now + timedelta(hours=h + 1)).isoformat()
        for h in range(steps)
    ]
    return {
        "station_id": station_id,
        "model": model_used,
        "steps": steps,
        "forecast": [
            {"timestamp": ts, "aqi": round(v, 1)}
            for ts, v in zip(timestamps, values)
        ],
    }


def _naive_fallback(
    db: Session, station_id: str, now: datetime, steps: int
) -> list[float]:
    results = []
    for h in range(steps):
        target = now + timedelta(hours=h + 1)
        val = seasonal_naive_forecast(db, station_id, target)
        results.append(val if val is not None else 0.0)
    return results
