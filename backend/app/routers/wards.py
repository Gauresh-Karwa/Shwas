from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.analytics.ward_exposure import compute_city_exposure
from app.db import get_db

router = APIRouter(prefix="/api", tags=["wards"])


class WardExposureResponse(BaseModel):
    ward_id: str
    ward_name: str
    population: int
    census_year: int
    lat: float
    lon: float
    aqi: float
    category: str
    method: str


class CityExposureResponse(BaseModel):
    status: str
    stations_used: int
    wards: list[WardExposureResponse]
    population_by_category: dict[str, int]
    total_population: int


@router.get("/wards", response_model=CityExposureResponse)
def get_ward_exposure(db: Session = Depends(get_db)):
    try:
        summary = compute_city_exposure(db)
    except LookupError as exc:
        raise HTTPException(status_code=503, detail=str(exc))

    return CityExposureResponse(
        status="ok",
        stations_used=summary.stations_used,
        wards=[
            WardExposureResponse(
                ward_id=w.ward_id,
                ward_name=w.ward_name,
                population=w.population,
                census_year=w.census_year,
                lat=w.lat,
                lon=w.lon,
                aqi=w.aqi,
                category=w.category,
                method=w.method,
            )
            for w in summary.wards
        ],
        population_by_category=summary.population_by_category,
        total_population=sum(summary.population_by_category.values()),
    )