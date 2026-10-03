from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

import numpy as np
from sklearn.cluster import DBSCAN
from sqlalchemy.orm import Session

from app.aqi.calculator import CATEGORY_BANDS
from app.analytics.grid_scan import DEFAULT_MC_SAMPLES, scan_grid

DEFAULT_Z = 1.96

# Neighbouring grid cells are 2 km apart (2.83 km on the diagonal), so a
# 3 km radius joins adjacent hot cells into one hotspot.
CLUSTER_RADIUS_KM = 3.0
EARTH_RADIUS_KM = 6371.0


def _category_for(aqi: float) -> str:
    for _, high, name in CATEGORY_BANDS:
        if aqi <= high:
            return name
    return "Severe"


@dataclass
class HotspotCandidate:
    lat: float
    lon: float
    ward_id: str
    ward_name: str
    population: int
    estimated_aqi: float
    uncertainty_std: float | None
    lcb: float
    lcb_category: str
    method: str  # "gnn" (lcb is confidence-adjusted) or "idw" (lcb == aqi)
    cluster_size: int = 1  # grid cells merged into this hotspot


def cluster_hotspots(
    candidates: list[HotspotCandidate],
    radius_km: float = CLUSTER_RADIUS_KM,
) -> list[HotspotCandidate]:
    """Group neighbouring hot grid cells with DBSCAN (haversine metric) and
    keep the worst-LCB cell of each group as its representative.

    min_samples=1 on purpose: an isolated hot cell is still a hotspot, not
    noise, so nothing is discarded - adjacent cells are just merged so one
    polluted area is reported once, with `cluster_size` cells.
    radius_km <= 0 turns clustering off."""
    if radius_km <= 0 or len(candidates) < 2:
        return candidates

    coords = np.radians([[c.lat, c.lon] for c in candidates])
    labels = DBSCAN(
        eps=radius_km / EARTH_RADIUS_KM, min_samples=1, metric="haversine"
    ).fit_predict(coords)

    sizes = Counter(labels)
    best: dict[int, HotspotCandidate] = {}
    for cand, label in zip(candidates, labels):
        if label not in best or cand.lcb > best[label].lcb:
            best[label] = cand
    merged = []
    for label, cand in best.items():
        cand.cluster_size = sizes[label]
        merged.append(cand)
    return merged


def detect_hotspots(
    db: Session,
    threshold: float = 100.0,
    z: float = DEFAULT_Z,
    step_km: float = 2.0,
    mc_samples: int = DEFAULT_MC_SAMPLES,
    cluster_radius_km: float = CLUSTER_RADIUS_KM,
) -> list[HotspotCandidate]:
    grid = scan_grid(db, step_km=step_km, mc_samples=mc_samples)

    candidates = []
    for point in grid:
        if point.std is not None:
            lcb = max(0.0, point.aqi - z * point.std)
        else:
            lcb = point.aqi  # no uncertainty estimate to subtract

        if lcb < threshold:
            continue

        candidates.append(
            HotspotCandidate(
                lat=point.lat,
                lon=point.lon,
                ward_id=point.ward_id,
                ward_name=point.ward_name,
                population=point.population,
                estimated_aqi=point.aqi,
                uncertainty_std=point.std,
                lcb=round(lcb, 1),
                lcb_category=_category_for(lcb),
                method=point.method,
            )
        )

    candidates = cluster_hotspots(candidates, cluster_radius_km)
    candidates.sort(key=lambda c: c.lcb, reverse=True)
    return candidates