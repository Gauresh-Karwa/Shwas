from __future__ import annotations

import math
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.analytics.grid_scan import DEFAULT_MC_SAMPLES, scan_grid
from app.ml.gnn_model import haversine_km
from app.models.db_models import Station

EXCLUSION_RADIUS_KM = 2.5


@dataclass
class SensorSiteRecommendation:
    lat: float
    lon: float
    ward_id: str
    ward_name: str
    population: int
    estimated_aqi: float
    uncertainty_std: float
    nearest_station_distance_km: float
    score: float


def recommend_sensor_sites(
    db: Session,
    top_k: int = 5,
    exclusion_radius_km: float = EXCLUSION_RADIUS_KM,
    step_km: float = 2.0,
    mc_samples: int = DEFAULT_MC_SAMPLES,
) -> list[SensorSiteRecommendation]:
    grid = scan_grid(db, step_km=step_km, mc_samples=mc_samples)
    stations = [
        s for s in db.query(Station).all()
        if s.latitude is not None and s.longitude is not None
    ]

    candidates = []
    for point in grid:
        if point.std is None:
            continue  

        if stations:
            nearest_km = min(haversine_km(point.lat, point.lon, s.latitude, s.longitude) for s in stations)
        else:
            nearest_km = float("inf")

        if nearest_km < exclusion_radius_km:
            continue 

        score = point.std * math.log10(1 + point.population)
        candidates.append(
            SensorSiteRecommendation(
                lat=point.lat,
                lon=point.lon,
                ward_id=point.ward_id,
                ward_name=point.ward_name,
                population=point.population,
                estimated_aqi=point.aqi,
                uncertainty_std=point.std,
                nearest_station_distance_km=round(nearest_km, 2) if nearest_km != float("inf") else -1.0,
                score=round(score, 4),
            )
        )

    candidates.sort(key=lambda c: c.score, reverse=True)
    return candidates[:top_k]
