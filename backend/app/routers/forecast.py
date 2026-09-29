from __future__ import annotations
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session
from app.db import get_db
from app.forecasting.service import run_forecast
from app.forecasting.spatial import run_coordinate_forecast, MAX_STEPS

router = APIRouter(prefix="/api", tags=["forecast"])
@router.get("/forecast/coordinate")
def forecast_coordinate(
    lat: float = Query(..., ge=-90, le=90, description="Query latitude"),
    lon: float = Query(..., ge=-180, le=180, description="Query longitude"),
    steps: int = Query(24, ge=1, le=MAX_STEPS, description="Number of hourly steps to forecast"),
    db: Session = Depends(get_db),
):
    try:
        return run_coordinate_forecast(db, lat, lon, steps=steps)
    except LookupError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/forecast/{station_id}")
def forecast(
    station_id: str,
    steps: int = Query(24, ge=1, le=168, description="Number of hourly steps to forecast"),
    db: Session = Depends(get_db),
):
    try:
        return run_forecast(db, station_id, steps=steps)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))