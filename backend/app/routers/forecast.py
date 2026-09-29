from __future__ import annotations
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session
from app.db import get_db
from app.forecasting.service import run_forecast
from app.forecasting.spatial import run_coordinate_forecast, MAX_STEPS
from app.models.db_models import Station

router = APIRouter(prefix="/api", tags=["forecast"])

UNCERTAINTY_DESC = (
    "Include a confidence interval: SARIMA's own get_forecast().conf_int() "
    "for station forecasts, or MC-dropout mean/std for coordinate forecasts "
    "on hours the GNN handles. Adds a few extra fields per point; leave off "
    "(default) for the original lean response."
)

@router.get("/forecast/coordinate")
def forecast_coordinate(
    lat: float = Query(..., ge=-90, le=90, description="Query latitude"),
    lon: float = Query(..., ge=-180, le=180, description="Query longitude"),
    steps: int = Query(24, ge=1, le=MAX_STEPS, description="Number of hourly steps to forecast"),
    uncertainty: bool = Query(False, description=UNCERTAINTY_DESC),
    db: Session = Depends(get_db),
):
    try:
        return run_coordinate_forecast(db, lat, lon, steps=steps, uncertainty=uncertainty)
    except LookupError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/forecast/{station_id}")
def forecast(
    station_id: str,
    steps: int = Query(24, ge=1, le=168, description="Number of hourly steps to forecast"),
    uncertainty: bool = Query(False, description=UNCERTAINTY_DESC),
    db: Session = Depends(get_db),
):
    exists = db.query(Station.station_id).filter(Station.station_id == station_id).first()
    if exists is None:
        raise HTTPException(status_code=404, detail=f"Unknown station_id '{station_id}'.")
    try:
        return run_forecast(db, station_id, steps=steps, uncertainty=uncertainty)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))