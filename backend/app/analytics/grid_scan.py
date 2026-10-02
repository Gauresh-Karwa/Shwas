"""
Land-masked grid scan of Mumbai: for a uniform lattice of candidate
points (inside some ward, i.e. on land and within BMC limits — points
over the sea or outside the 24 wards are dropped), estimates current AQI
and, where a GNN checkpoint is loaded, an MC-dropout uncertainty (mean,
std) at each point.

This is the one shared, reusable "what does the air look like everywhere,
not just at stations" computation that both the sensor-placement
recommender and hotspot detection are built from — each applies its own
ranking to the same underlying grid rather than re-scanning separately.

Deliberately approximate, and documented as such: grid spacing is
converted from kilometres to degrees using a simple equirectangular
approximation (fine at Mumbai's ~50km scale and this grid's ~2km
resolution), not a proper geodesic grid. Point-in-polygon uses the ward
boundaries' EXTERIOR rings only (see app.analytics.geo), same
simplification already used by ward_exposure.py's centroid calculation.
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.analytics.geo import point_in_geometry
from app.aqi.calculator import CATEGORY_BANDS
from app.interpolation.idw import idw_interpolate
from app.interpolation.live import get_lagged_aqis, get_live_snapshot
from app.ml.model_registry import get_gnn_model
from app.models.db_models import WardBoundary, WardPopulation

KM_PER_DEG_LAT = 111.0
DEFAULT_MC_SAMPLES = 10
CACHE_TTL_SECONDS = 1800  # 30 min — current AQI doesn't swing fast enough
                          # to justify re-running an expensive MC-dropout
                          # scan on every request.

# Mumbai bounding box — matches app.ml.gnn_model's own LAT/LON normalisation
# range, so every grid point is guaranteed inside the GNN's trained domain.
LAT_MIN, LAT_MAX = 18.85, 19.30
LON_MIN, LON_MAX = 72.75, 73.00


def _category_for(aqi: float) -> str:
    for _, high, name in CATEGORY_BANDS:
        if aqi <= high:
            return name
    return "Severe"


@dataclass
class GridPoint:
    lat: float
    lon: float
    ward_id: str
    ward_name: str
    population: int
    aqi: float
    std: float | None  # None when this point fell back to IDW
    method: str  # "gnn" or "idw"


def _km_step_to_degrees(step_km: float, mean_lat_deg: float) -> tuple[float, float]:
    dlat = step_km / KM_PER_DEG_LAT
    dlon = step_km / (KM_PER_DEG_LAT * math.cos(math.radians(mean_lat_deg)))
    return dlat, dlon


def generate_land_masked_points(db: Session, step_km: float = 2.0) -> list[tuple[float, float, str]]:
    """Returns (lat, lon, ward_id) for every grid cell whose center falls
    inside some ward's boundary. A point matching more than one ward
    (shouldn't happen for non-overlapping wards, but defensively handled)
    keeps the first match found."""
    boundaries = db.query(WardBoundary).all()
    if not boundaries:
        return []

    dlat, dlon = _km_step_to_degrees(step_km, (LAT_MIN + LAT_MAX) / 2.0)
    points: list[tuple[float, float, str]] = []

    lat = LAT_MIN
    while lat <= LAT_MAX:
        lon = LON_MIN
        while lon <= LON_MAX:
            for boundary in boundaries:
                if point_in_geometry(lat, lon, boundary.geometry):
                    points.append((lat, lon, boundary.ward_id))
                    break
            lon += dlon
        lat += dlat
    return points


def _estimate_point(
    lat: float,
    lon: float,
    station_points: list[tuple[float, float, float]],
    station_lats: list[float],
    station_lons: list[float],
    station_aqis: list[float],
    lag1_aqis: list[Optional[float]],
    lag3_aqis: list[Optional[float]],
    model,
    now: datetime,
    mc_samples: int,
) -> tuple[float, float | None, str]:
    """GNN-first, IDW-fallback logic calling the MC-dropout variant so a std
    comes back alongside the point estimate. IDW has no equivalent uncertainty
    measure, so its std is None. Exogenous lag inputs are precomputed across
    all stations to avoid quadratic database queries."""
    if model is not None:
        try:
            from app.ml.gnn_model import gnn_interpolate_with_uncertainty

            mean, std = gnn_interpolate_with_uncertainty(
                model=model,
                query_lat=lat,
                query_lon=lon,
                station_lats=station_lats,
                station_lons=station_lons,
                station_aqis=station_aqis,
                hour=now.hour,
                weekday=now.weekday(),
                station_aqis_1h=lag1_aqis,
                station_aqis_3h=lag3_aqis,
                n_samples=mc_samples,
            )
            return mean, std, "gnn"
        except Exception:
            pass

    idw = idw_interpolate(
        target_lat=lat,
        target_lon=lon,
        station_points=station_points,
    )
    if idw is None:
        raise LookupError("Interpolation failed — no usable station data.")
    return idw.estimated_aqi, None, "idw"


_cache: dict[tuple[float, int], tuple[float, list[GridPoint]]] = {}


def scan_grid(db: Session, step_km: float = 2.0, mc_samples: int = DEFAULT_MC_SAMPLES, use_cache: bool = True) -> list[GridPoint]:
    """The full land-masked grid, each point's current AQI estimate, and
    (where the GNN ran) its MC-dropout uncertainty. Cached in-process for
    CACHE_TTL_SECONDS per (step_km, mc_samples) combination, since a full
    scan runs mc_samples forward passes per surviving point (~300 points
    at a 2km step over Mumbai) and isn't worth repeating every request."""
    cache_key = (step_km, mc_samples)
    if use_cache and cache_key in _cache:
        cached_at, cached_result = _cache[cache_key]
        if time.time() - cached_at < CACHE_TTL_SECONDS:
            return cached_result

    snapshot = get_live_snapshot(db)
    if not snapshot:
        raise LookupError("No live station AQI data available yet.")

    populations = {p.ward_id: p for p in db.query(WardPopulation).all()}
    boundaries = {b.ward_id: b for b in db.query(WardBoundary).all()}
    grid = generate_land_masked_points(db, step_km=step_km)
    model = get_gnn_model()
    now = datetime.now(tz=timezone.utc)

    # Precompute station lists and lag values ONCE for all grid points
    station_lats = [s["lat"] for s in snapshot]
    station_lons = [s["lon"] for s in snapshot]
    station_aqis = [s["aqi"] for s in snapshot]
    station_points = [(s["lat"], s["lon"], s["aqi"]) for s in snapshot]
    lag1_aqis = [get_lagged_aqis(db, s["station_id"], now, lag_hours=1) for s in snapshot]
    lag3_aqis = [get_lagged_aqis(db, s["station_id"], now, lag_hours=3) for s in snapshot]

    results: list[GridPoint] = []
    for lat, lon, ward_id in grid:
        pop_row = populations.get(ward_id)
        if pop_row is None:
            continue  # same "no fabricated population" rule as ward_exposure.py
        aqi, std, method = _estimate_point(
            lat=lat,
            lon=lon,
            station_points=station_points,
            station_lats=station_lats,
            station_lons=station_lons,
            station_aqis=station_aqis,
            lag1_aqis=lag1_aqis,
            lag3_aqis=lag3_aqis,
            model=model,
            now=now,
            mc_samples=mc_samples,
        )
        results.append(
            GridPoint(
                lat=lat,
                lon=lon,
                ward_id=ward_id,
                ward_name=boundaries[ward_id].ward_name,
                population=pop_row.population,
                aqi=round(aqi, 1),
                std=round(std, 2) if std is not None else None,
                method=method,
            )
        )

    if use_cache:
        _cache[cache_key] = (time.time(), results)
    return results


def clear_grid_cache() -> None:
    _cache.clear()
