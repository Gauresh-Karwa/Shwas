from __future__ import annotations
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session
from app.db import get_db
from app.interpolation.live import get_live_snapshot, get_lagged_aqis
from app.interpolation.idw import idw_interpolate, InterpolationResult
from app.ml.model_registry import get_gnn_model

router = APIRouter(prefix="/api", tags=["interpolation"])


@router.get("/stations")
def get_stations(db: Session = Depends(get_db)):
    snapshot = get_live_snapshot(db)

    # Enrich each station with its latest individual pollutant readings
    # from the sub_indices JSON column of the latest StationAQI record.
    POLLUTANT_MAP = {"PM2.5": "pm25", "PM10": "pm10", "NO2": "no2", "SO2": "so2"}
    for entry in snapshot:
        from app.models.db_models import StationAQI
        latest_aqi = (
            db.query(StationAQI)
            .filter(
                StationAQI.station_id == entry["station_id"],
                StationAQI.status == "ok",
                StationAQI.aqi_value.isnot(None),
            )
            .order_by(StationAQI.timestamp.desc())
            .first()
        )
        sub = latest_aqi.sub_indices if latest_aqi and latest_aqi.sub_indices else {}
        for cpcb_key, field in POLLUTANT_MAP.items():
            val = sub.get(cpcb_key)
            entry[field] = round(float(val), 1) if val is not None else None

    return snapshot



@router.get("/interpolate")
def interpolate(
    lat: float = Query(..., ge=-90, le=90, description="Query latitude"),
    lon: float = Query(..., ge=-180, le=180, description="Query longitude"),
    db: Session = Depends(get_db),
):
    snapshot = get_live_snapshot(db)
    if not snapshot:
        raise HTTPException(status_code=503, detail="No live station data available")

    now = datetime.now(tz=timezone.utc)
    hour = now.hour
    weekday = now.weekday()

    station_lats = [s["lat"] for s in snapshot]
    station_lons = [s["lon"] for s in snapshot]
    station_aqis = [s["aqi"] for s in snapshot]

    model = get_gnn_model()
    if model is not None:
        try:
            from app.ml.gnn_model import gnn_interpolate
            lag1_aqis = [
                get_lagged_aqis(db, s["station_id"], now, lag_hours=1)
                for s in snapshot
            ]
            lag3_aqis = [
                get_lagged_aqis(db, s["station_id"], now, lag_hours=3)
                for s in snapshot
            ]
            aqi_est = gnn_interpolate(
                model=model,
                query_lat=lat,
                query_lon=lon,
                station_lats=station_lats,
                station_lons=station_lons,
                station_aqis=station_aqis,
                hour=hour,
                weekday=weekday,
                station_aqis_1h=lag1_aqis,
                station_aqis_3h=lag3_aqis,
            )
            return {
                "lat": lat,
                "lon": lon,
                "estimated_aqi": round(aqi_est, 1),
                "model": "gnn",
                "stations_used": len(snapshot),
            }
        except Exception:
            pass

    result: InterpolationResult | None = idw_interpolate(
        target_lat=lat,
        target_lon=lon,
        station_points=[(s["lat"], s["lon"], s["aqi"]) for s in snapshot],
    )
    if result is None:
        raise HTTPException(status_code=503, detail="Interpolation failed")

    return {
        "lat": lat,
        "lon": lon,
        "estimated_aqi": result.estimated_aqi,
        "model": "idw",
        "confidence": result.confidence,
        "nearest_station_distance_km": result.nearest_station_distance_km,
        "stations_used": result.stations_used,
    }
