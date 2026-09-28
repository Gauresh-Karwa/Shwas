from __future__ import annotations
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session
from app.db import get_db
from app.forecasting.service import run_forecast

router = APIRouter(prefix="/api", tags=["forecast"])


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
