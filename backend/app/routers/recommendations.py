from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.analytics.hotspots import DEFAULT_Z, detect_hotspots
from app.analytics.sensor_placement import EXCLUSION_RADIUS_KM, recommend_sensor_sites
from app.db import get_db

router = APIRouter(prefix="/api", tags=["recommendations"])


class SensorSiteResponse(BaseModel):
    lat: float
    lon: float
    ward_id: str
    ward_name: str
    population: int
    estimated_aqi: float
    uncertainty_std: float
    nearest_station_distance_km: float
    score: float


class HotspotResponse(BaseModel):
    lat: float
    lon: float
    ward_id: str
    ward_name: str
    population: int
    estimated_aqi: float
    uncertainty_std: float | None
    lcb: float
    lcb_category: str
    method: str


@router.get("/recommendations/sensor-placement", response_model=list[SensorSiteResponse])
def sensor_placement(
    top_k: int = Query(5, ge=1, le=50),
    exclusion_radius_km: float = Query(EXCLUSION_RADIUS_KM, ge=0),
    db: Session = Depends(get_db),
):
    try:
        sites = recommend_sensor_sites(db, top_k=top_k, exclusion_radius_km=exclusion_radius_km)
    except LookupError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    return [SensorSiteResponse(**vars(s)) for s in sites]


@router.get("/analytics/hotspots", response_model=list[HotspotResponse])
def hotspots(
    threshold: float = Query(100.0, ge=0, le=500),
    z: float = Query(DEFAULT_Z, ge=0),
    db: Session = Depends(get_db),
):
    try:
        found = detect_hotspots(db, threshold=threshold, z=z)
    except LookupError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    return [HotspotResponse(**vars(h)) for h in found]
