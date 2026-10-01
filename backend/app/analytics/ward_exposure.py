from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.aqi.calculator import CATEGORY_BANDS
from app.analytics.geo import polygon_centroid
from app.interpolation.idw import idw_interpolate
from app.interpolation.live import get_lagged_aqis, get_live_snapshot
from app.ml.model_registry import get_gnn_model
from app.models.db_models import WardBoundary, WardPopulation


def _category_for(aqi: float) -> str:
    for _, high, name in CATEGORY_BANDS:
        if aqi <= high:
            return name
    return "Severe"


@dataclass
class WardExposure:
    ward_id: str
    ward_name: str
    population: int
    census_year: int
    lat: float
    lon: float
    aqi: float
    category: str
    method: str  


@dataclass
class CityExposureSummary:
    wards: list[WardExposure] = field(default_factory=list)
    population_by_category: dict[str, int] = field(default_factory=dict)
    stations_used: int = 0


def _estimate_aqi_at(db: Session, lat: float, lon: float, snapshot: list[dict], model, now: datetime) -> tuple[float, str]:
    if model is not None:
        try:
            from app.ml.gnn_model import gnn_interpolate

            lag1_aqis = [get_lagged_aqis(db, s["station_id"], now, lag_hours=1) for s in snapshot]
            lag3_aqis = [get_lagged_aqis(db, s["station_id"], now, lag_hours=3) for s in snapshot]
            estimate = gnn_interpolate(
                model=model,
                query_lat=lat,
                query_lon=lon,
                station_lats=[s["lat"] for s in snapshot],
                station_lons=[s["lon"] for s in snapshot],
                station_aqis=[s["aqi"] for s in snapshot],
                hour=now.hour,
                weekday=now.weekday(),
                station_aqis_1h=lag1_aqis,
                station_aqis_3h=lag3_aqis,
            )
            return estimate, "gnn"
        except Exception:
            pass

    idw = idw_interpolate(
        target_lat=lat,
        target_lon=lon,
        station_points=[(s["lat"], s["lon"], s["aqi"]) for s in snapshot],
    )
    if idw is None:
        raise LookupError("Interpolation failed — no usable station data.")
    return idw.estimated_aqi, "idw"


def compute_city_exposure(db: Session) -> CityExposureSummary:
    snapshot = get_live_snapshot(db)
    if not snapshot:
        raise LookupError("No live station AQI data available yet.")

    boundaries = {b.ward_id: b for b in db.query(WardBoundary).all()}
    populations = {p.ward_id: p for p in db.query(WardPopulation).all()}
    ward_ids = sorted(set(boundaries) & set(populations))

    model = get_gnn_model()
    now = datetime.now(tz=timezone.utc)

    summary = CityExposureSummary(stations_used=len(snapshot))
    for ward_id in ward_ids:
        boundary = boundaries[ward_id]
        pop = populations[ward_id]
        lat, lon = polygon_centroid(boundary.geometry)
        aqi, method = _estimate_aqi_at(db, lat, lon, snapshot, model, now)
        category = _category_for(aqi)

        summary.wards.append(
            WardExposure(
                ward_id=ward_id,
                ward_name=boundary.ward_name,
                population=pop.population,
                census_year=pop.census_year,
                lat=lat,
                lon=lon,
                aqi=round(aqi, 1),
                category=category,
                method=method,
            )
        )
        summary.population_by_category[category] = (
            summary.population_by_category.get(category, 0) + pop.population
        )

    summary.wards.sort(key=lambda w: w.aqi, reverse=True)
    return summary