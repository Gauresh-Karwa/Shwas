"""
Sensor-site recommendation.

Two goals, in this order:

1. COVERAGE — every ward that has no monitoring station should get a
   candidate site (its best-scoring location), as long as that location is
   at least `exclusion_radius_km` from every existing station. A ward whose
   every point is already within that radius of a station is genuinely
   covered and is not recommended.
2. UNCERTAINTY x EXPOSURE — remaining slots go to the highest-scoring
   locations anywhere, where
       score = GNN MC-dropout std * log10(1 + ward population)

Every recommendation is kept at least `min_separation_km` from the others,
so picks spread across the city instead of clustering in one big ward.

Each result carries a `reason`:
    "unmonitored_ward" - chosen because its ward has no station
    "coverage_gap"     - chosen on score alone (ward already has a station)
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.analytics.geo import point_in_geometry
from app.analytics.grid_scan import DEFAULT_MC_SAMPLES, scan_grid
from app.ml.gnn_model import haversine_km
from app.models.db_models import Station, WardBoundary

# Minimum distance from an EXISTING station for a site to be worth adding.
EXCLUSION_RADIUS_KM = 1.0
# Minimum spacing between two RECOMMENDED sites.
MIN_SEPARATION_KM = 2.0
# Placement scans a finer grid than hotspots so small wards get candidates.
PLACEMENT_STEP_KM = 1.0

REASON_UNMONITORED = "unmonitored_ward"
REASON_GAP = "coverage_gap"


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
    reason: str = REASON_GAP


def _monitored_wards(db: Session, stations) -> set[str] | None:
    """Ward ids that contain at least one station, or None if the ward
    boundaries can't be evaluated (then no ward is treated as unmonitored)."""
    try:
        boundaries = db.query(WardBoundary).all()
        monitored: set[str] = set()
        for b in boundaries:
            if any(point_in_geometry(s.latitude, s.longitude, b.geometry) for s in stations):
                monitored.add(b.ward_id)
        return monitored
    except Exception:
        return None


def select_sites(
    candidates: list[SensorSiteRecommendation],
    monitored_wards: set[str] | None,
    top_k: int,
    min_separation_km: float,
) -> list[SensorSiteRecommendation]:
    """Pure selection step (no DB): ward coverage first, then best score,
    keeping every pick `min_separation_km` away from the others."""
    chosen: list[SensorSiteRecommendation] = []

    def far_enough(c: SensorSiteRecommendation) -> bool:
        return all(
            haversine_km(c.lat, c.lon, o.lat, o.lon) >= min_separation_km for o in chosen
        )

    ranked = sorted(candidates, key=lambda c: c.score, reverse=True)

    # Pass 1 - one site per unmonitored ward (highest-scoring wards first).
    if monitored_wards is not None:
        by_ward: dict[str, list[SensorSiteRecommendation]] = {}
        for c in ranked:
            if c.ward_id not in monitored_wards:
                by_ward.setdefault(c.ward_id, []).append(c)  # already score-desc
        for ward_candidates in sorted(by_ward.values(), key=lambda cs: cs[0].score, reverse=True):
            if len(chosen) >= top_k:
                break
            for c in ward_candidates:
                if far_enough(c):
                    c.reason = REASON_UNMONITORED
                    chosen.append(c)
                    break

    # Pass 2 - fill remaining slots with the best-scoring spread-out sites.
    for c in ranked:
        if len(chosen) >= top_k:
            break
        if c in chosen or not far_enough(c):
            continue
        c.reason = REASON_GAP
        chosen.append(c)

    chosen.sort(key=lambda c: c.score, reverse=True)
    return chosen


def recommend_sensor_sites(
    db: Session,
    top_k: int = 5,
    exclusion_radius_km: float = EXCLUSION_RADIUS_KM,
    step_km: float = PLACEMENT_STEP_KM,
    mc_samples: int = DEFAULT_MC_SAMPLES,
    min_separation_km: float = MIN_SEPARATION_KM,
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

    monitored = _monitored_wards(db, stations)
    return select_sites(candidates, monitored, top_k, min_separation_km)