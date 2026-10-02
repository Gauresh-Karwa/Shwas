from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.analytics import grid_scan
from app.db import Base
from app.models.db_models import Station, StationAQI, WardBoundary, WardPopulation

BIG_WARD = {
    "type": "Polygon",
    "coordinates": [[[72.75, 18.85], [73.00, 18.85], [73.00, 19.30], [72.75, 19.30], [72.75, 18.85]]],
}


@pytest.fixture()
def db_session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    grid_scan.clear_grid_cache()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()
        grid_scan.clear_grid_cache()


def test_generate_land_masked_points_keeps_only_points_inside_wards(db_session):
    db_session.add(WardBoundary(ward_id="BIG", ward_name="Big Ward", geometry=BIG_WARD))
    db_session.commit()
    points = grid_scan.generate_land_masked_points(db_session, step_km=50.0)
    assert len(points) > 0
    assert all(ward_id == "BIG" for _, _, ward_id in points)
    assert all(grid_scan.LAT_MIN <= lat <= grid_scan.LAT_MAX for lat, _, _ in points)
    assert all(grid_scan.LON_MIN <= lon <= grid_scan.LON_MAX for _, lon, _ in points)


def test_generate_land_masked_points_empty_with_no_wards(db_session):
    assert grid_scan.generate_land_masked_points(db_session, step_km=50.0) == []


def test_generate_land_masked_points_drops_points_outside_any_ward(db_session):
    tiny_ward = {
        "type": "Polygon",
        "coordinates": [[[72.75, 18.85], [72.76, 18.85], [72.76, 18.86], [72.75, 18.86], [72.75, 18.85]]],
    }
    db_session.add(WardBoundary(ward_id="TINY", ward_name="Tiny Ward", geometry=tiny_ward))
    db_session.commit()
    points = grid_scan.generate_land_masked_points(db_session, step_km=50.0)
    assert len(points) <= 1


def test_scan_grid_raises_when_no_live_station_data(db_session):
    db_session.add(WardBoundary(ward_id="BIG", ward_name="Big Ward", geometry=BIG_WARD))
    db_session.add(WardPopulation(ward_id="BIG", population=10000, census_year=2011))
    db_session.commit()
    with pytest.raises(LookupError):
        grid_scan.scan_grid(db_session, step_km=50.0)


def test_scan_grid_skips_wards_with_no_population(db_session):
    db_session.add(Station(station_id="S1", name="S1", agency="CPCB", latitude=19.0, longitude=72.85))
    db_session.add(StationAQI(station_id="S1", timestamp=datetime(2026, 1, 1), aqi_value=100.0, status="ok", category="Moderate", dominant_pollutant="PM2.5"))
    db_session.add(WardBoundary(ward_id="BIG", ward_name="Big Ward", geometry=BIG_WARD))
    db_session.commit()
    results = grid_scan.scan_grid(db_session, step_km=50.0, use_cache=False)
    assert results == []


def test_scan_grid_idw_fallback_has_no_std(db_session, monkeypatch):
    monkeypatch.setattr(grid_scan, "get_gnn_model", lambda: None)
    db_session.add(Station(station_id="S1", name="S1", agency="CPCB", latitude=19.0, longitude=72.85))
    db_session.add(StationAQI(station_id="S1", timestamp=datetime(2026, 1, 1), aqi_value=120.0, status="ok", category="Moderate", dominant_pollutant="PM2.5"))
    db_session.add(WardBoundary(ward_id="BIG", ward_name="Big Ward", geometry=BIG_WARD))
    db_session.add(WardPopulation(ward_id="BIG", population=50000, census_year=2011))
    db_session.commit()
    results = grid_scan.scan_grid(db_session, step_km=50.0, use_cache=False)
    assert len(results) > 0
    assert all(p.method == "idw" and p.std is None for p in results)
    assert all(0.0 <= p.aqi <= 500.0 for p in results)


def test_scan_grid_with_real_gnn_produces_std(db_session, monkeypatch):
    import torch
    from app.ml.gnn_model import SpatialGNN

    torch.manual_seed(0)
    model = SpatialGNN(k_neighbours=3)
    model.eval()
    monkeypatch.setattr(grid_scan, "get_gnn_model", lambda: model)

    for i, (lat, lon) in enumerate([(19.0, 72.80), (19.1, 72.90), (19.05, 72.85)]):
        db_session.add(Station(station_id=f"S{i}", name=f"S{i}", agency="CPCB", latitude=lat, longitude=lon))
        db_session.add(StationAQI(station_id=f"S{i}", timestamp=datetime(2026, 1, 1), aqi_value=100.0 + i * 20, status="ok", category="Moderate", dominant_pollutant="PM2.5"))
    db_session.add(WardBoundary(ward_id="BIG", ward_name="Big Ward", geometry=BIG_WARD))
    db_session.add(WardPopulation(ward_id="BIG", population=50000, census_year=2011))
    db_session.commit()

    results = grid_scan.scan_grid(db_session, step_km=50.0, mc_samples=5, use_cache=False)
    assert len(results) > 0
    assert all(p.method == "gnn" for p in results)
    assert all(p.std is not None and p.std >= 0.0 for p in results)


def test_scan_grid_cache_returns_same_object_within_ttl(db_session, monkeypatch):
    monkeypatch.setattr(grid_scan, "get_gnn_model", lambda: None)
    db_session.add(Station(station_id="S1", name="S1", agency="CPCB", latitude=19.0, longitude=72.85))
    db_session.add(StationAQI(station_id="S1", timestamp=datetime(2026, 1, 1), aqi_value=100.0, status="ok", category="Moderate", dominant_pollutant="PM2.5"))
    db_session.add(WardBoundary(ward_id="BIG", ward_name="Big Ward", geometry=BIG_WARD))
    db_session.add(WardPopulation(ward_id="BIG", population=1000, census_year=2011))
    db_session.commit()

    first = grid_scan.scan_grid(db_session, step_km=50.0, use_cache=True)
    second = grid_scan.scan_grid(db_session, step_km=50.0, use_cache=True)
    assert first is second


def test_scan_grid_cache_bypass_recomputes(db_session, monkeypatch):
    monkeypatch.setattr(grid_scan, "get_gnn_model", lambda: None)
    db_session.add(Station(station_id="S1", name="S1", agency="CPCB", latitude=19.0, longitude=72.85))
    db_session.add(StationAQI(station_id="S1", timestamp=datetime(2026, 1, 1), aqi_value=100.0, status="ok", category="Moderate", dominant_pollutant="PM2.5"))
    db_session.add(WardBoundary(ward_id="BIG", ward_name="Big Ward", geometry=BIG_WARD))
    db_session.add(WardPopulation(ward_id="BIG", population=1000, census_year=2011))
    db_session.commit()

    first = grid_scan.scan_grid(db_session, step_km=50.0, use_cache=False)
    second = grid_scan.scan_grid(db_session, step_km=50.0, use_cache=False)
    assert first is not second
