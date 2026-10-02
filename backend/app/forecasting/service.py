from __future__ import annotations
from datetime import datetime, date, timezone, timedelta
from sqlalchemy.orm import Session
from app.forecasting.sarima_model import (
    load_station_series,
    series_from_df,
    fit_sarima,
    fit_sarimax,
    sarima_forecast,
    sarima_forecast_with_ci,
    sarimax_forecast,
    align_exog_to_series,
)
from app.forecasting.baseline import seasonal_naive_forecast
from app.attribution.open_meteo_client import (
    get_historical_weather,
    get_forecast_weather,
    EXOG_COLUMNS,
)
from app.models.db_models import Station

MIN_ROWS_FOR_SARIMA = 7 * 24

_WEATHER_COLS = ["temp_c", "humidity_pct", "wind_speed_mps", "pressure_hpa", "precip_mm"]


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
    model_used = "seasonal_naive"
    values: list[float] = []

    if len(df) >= MIN_ROWS_FOR_SARIMA:

        station = (
            db.query(Station).filter(Station.station_id == station_id).first()
            if db is not None else None
        )
        lat = station.latitude if station else None
        lon = station.longitude if station else None

        series = series_from_df(df)
        sarimax_ok = False
        if lat is not None and lon is not None:
            try:
                train_start = series.index.min().date()
                train_end = series.index.max().date()
                hist_wx = get_historical_weather(lat, lon, train_start, train_end)
                exog_train = align_exog_to_series(series, hist_wx, _WEATHER_COLS)

                if exog_train is not None:
                    future_wx = get_forecast_weather(lat, lon, hours=steps)
                    if not future_wx.empty and len(future_wx) >= steps:
                        exog_future = future_wx[_WEATHER_COLS].iloc[:steps]
                        fit = fit_sarimax(series, exog_train)
                        values = sarimax_forecast(fit, exog_future, steps=steps)
                        model_used = "sarimax"
                        sarimax_ok = True
            except Exception:
                pass  # Fall through to plain SARIMA

        # Fall back to plain SARIMA
        if not sarimax_ok:
            try:
                fit_plain = fit_sarima(series)
                if uncertainty:
                    values, lower, upper = sarima_forecast_with_ci(fit_plain, steps=steps)
                else:
                    values = sarima_forecast(fit_plain, steps=steps)
                model_used = "sarima"
            except Exception:
                values = _naive_fallback(db, station_id, now, steps)
                model_used = "seasonal_naive"

        # If SARIMAX succeeded but uncertainty was requested, recompute with plain CI
        # (SARIMAX CI extraction is identical API — we wrap it here)
        if sarimax_ok and uncertainty:
            try:
                exog_train_u = align_exog_to_series(series, hist_wx, _WEATHER_COLS)  # type: ignore[possibly-undefined]
                fit_u = fit_sarimax(series, exog_train_u)
                from statsmodels.tsa.statespace.sarimax import SARIMAXResultsWrapper
                fc_obj = fit_u.get_forecast(steps=steps, exog=exog_future)  # type: ignore[possibly-undefined]
                ci = fc_obj.conf_int(alpha=0.05)
                lower = [float(max(0.0, min(500.0, v))) for v in ci.iloc[:, 0]]
                upper = [float(max(0.0, min(500.0, v))) for v in ci.iloc[:, 1]]
            except Exception:
                lower = [None] * steps  # type: ignore[assignment]
                upper = [None] * steps  # type: ignore[assignment]
    else:
        values = _naive_fallback(db, station_id, now, steps)

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