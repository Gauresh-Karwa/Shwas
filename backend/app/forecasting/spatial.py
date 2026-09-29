from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.aqi.calculator import CATEGORY_BANDS
from app.forecasting.service import run_forecast
from app.interpolation.idw import idw_interpolate
from app.interpolation.live import get_live_snapshot
from app.ml.model_registry import get_gnn_model

CACHE_TTL_SECONDS = 3600
MAX_STEPS = 48

_station_cache: dict[str, tuple[float, list[float]]] = {}


def _category_for(aqi: float) -> str:
    for _, high, name in CATEGORY_BANDS:
        if aqi <= high:
            return name
    return "Severe"


def _station_forecast(db: Session, station_id: str, steps: int) -> list[float]:
    hit = _station_cache.get(station_id)
    if hit and time.time() - hit[0] < CACHE_TTL_SECONDS and len(hit[1]) >= steps:
        return hit[1][:steps]
    result = run_forecast(db, station_id, steps=steps)
    values = [float(p["aqi"]) for p in result["forecast"]]
    _station_cache[station_id] = (time.time(), values)
    return values


def clear_station_cache() -> None:
    _station_cache.clear()


def _gnn_step(model, lat, lon, snapshot, aqis, lag1, lag3, target: datetime) -> float:
    from app.ml.gnn_model import gnn_interpolate

    return gnn_interpolate(
        model=model,
        query_lat=lat,
        query_lon=lon,
        station_lats=[s["lat"] for s in snapshot],
        station_lons=[s["lon"] for s in snapshot],
        station_aqis=aqis,
        hour=target.hour,
        weekday=target.weekday(),
        station_aqis_1h=lag1,
        station_aqis_3h=lag3,
    )


def _build_station_series(db: Session, snapshot: list[dict], steps: int) -> dict[str, list[float]]:
    series: dict[str, list[float]] = {}
    for s in snapshot:
        raw = _station_forecast(db, s["station_id"], steps)
        filled: list[float] = []
        prev = s["aqi"]
        for v in raw:
            if v is None or v <= 0:
                v = prev
            filled.append(v)
            prev = v
        while len(filled) < steps:
            filled.append(prev)
        series[s["station_id"]] = [s["aqi"]] + filled
    return series


def run_coordinate_forecast(db: Session, lat: float, lon: float, steps: int = 24) -> dict:
    steps = max(1, min(steps, MAX_STEPS))
    snapshot = get_live_snapshot(db)
    if not snapshot:
        raise LookupError("No live station data available")

    now = datetime.now(tz=timezone.utc)
    series = _build_station_series(db, snapshot, steps)
    model = get_gnn_model()

    points = []
    gnn_hours = 0
    for h in range(1, steps + 1):
        target = now + timedelta(hours=h)
        ids = [s["station_id"] for s in snapshot]
        aqis = [series[i][h] for i in ids]
        lag1 = [series[i][h - 1] for i in ids]
        lag3 = [series[i][h - 3] if h >= 3 else None for i in ids]

        estimate = None
        if model is not None:
            try:
                estimate = _gnn_step(model, lat, lon, snapshot, aqis, lag1, lag3, target)
                gnn_hours += 1
            except Exception:
                estimate = None
        if estimate is None:
            idw = idw_interpolate(
                target_lat=lat,
                target_lon=lon,
                station_points=[(s["lat"], s["lon"], a) for s, a in zip(snapshot, aqis)],
            )
            if idw is None:
                raise LookupError("Interpolation failed")
            estimate = idw.estimated_aqi

        points.append({
            "timestamp": target.isoformat(),
            "aqi": round(estimate, 1),
            "category": _category_for(estimate),
        })

    if gnn_hours == steps:
        method = "gnn"
    elif gnn_hours == 0:
        method = "idw"
    else:
        method = "gnn+idw"

    return {
        "lat": lat,
        "lon": lon,
        "model": method,
        "steps": steps,
        "stations_used": len(snapshot),
        "forecast": points,
    }