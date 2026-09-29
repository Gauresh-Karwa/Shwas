from __future__ import annotations
from datetime import datetime, timezone, timedelta
from typing import Optional
from sqlalchemy.orm import Session
from app.forecasting.sarima_model import (
    load_station_series,
    series_from_df,
    fit_sarima,
    sarima_forecast,
    sarima_forecast_with_ci,
)
from app.forecasting.baseline import seasonal_naive_forecast

MIN_ROWS_FOR_SARIMA = 7 * 24


def run_forecast(
    db: Session,
    station_id: str,
    steps: int = 24,
    uncertainty: bool = False,
) -> dict:
    df = load_station_series(db, station_id)
    now = datetime.now(tz=timezone.utc)

    lower: list[float | None] | None = None
    upper: list[float | None] | None = None

    if len(df) >= MIN_ROWS_FOR_SARIMA:
        try:
            series = series_from_df(df)
            fit = fit_sarima(series)
            if uncertainty:
                values, lower, upper = sarima_forecast_with_ci(fit, steps=steps)
            else:
                values = sarima_forecast(fit, steps=steps)
            model_used = "sarima"
        except Exception:
            values = _naive_fallback(db, station_id, now, steps)
            model_used = "seasonal_naive"
    else:
        values = _naive_fallback(db, station_id, now, steps)
        model_used = "seasonal_naive"

    if uncertainty and lower is None:
        lower = [None] * steps
        upper = [None] * steps

    timestamps = [
        (now + timedelta(hours=h + 1)).isoformat()
        for h in range(steps)
    ]

    if uncertainty:
        points = [
            {
                "timestamp": ts,
                "aqi": round(v, 1),
                "aqi_lower": round(lo, 1) if lo is not None else None,
                "aqi_upper": round(hi, 1) if hi is not None else None,
            }
            for ts, v, lo, hi in zip(timestamps, values, lower, upper)
        ]
    else:
        points = [
            {"timestamp": ts, "aqi": round(v, 1)}
            for ts, v in zip(timestamps, values)
        ]

    return {
        "station_id": station_id,
        "model": model_used,
        "steps": steps,
        "forecast": points,
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