from unittest.mock import MagicMock

import pytest

from app.analytics.grid_scan import GridPoint
from app.analytics.sensor_placement import recommend_sensor_sites


def _station(station_id, lat, lon):
    s = MagicMock()
    s.station_id, s.latitude, s.longitude = station_id, lat, lon
    return s


def test_points_near_existing_station_are_hard_excluded(monkeypatch):
    grid = [GridPoint(lat=19.00, lon=72.80, ward_id="A", ward_name="A", population=1_000_000, aqi=200.0, std=50.0, method="gnn")]
    import app.analytics.sensor_placement as sp
    monkeypatch.setattr(sp, "scan_grid", lambda db, **k: grid)

    db = MagicMock()
    db.query.return_value.all.return_value = [_station("S1", 19.00, 72.80)]
    results = recommend_sensor_sites(db, top_k=5)
    assert results == []


def test_idw_fallback_points_are_never_ranked(monkeypatch):
    grid = [GridPoint(lat=19.20, lon=72.90, ward_id="B", ward_name="B", population=1_000_000, aqi=300.0, std=None, method="idw")]
    import app.analytics.sensor_placement as sp
    monkeypatch.setattr(sp, "scan_grid", lambda db, **k: grid)

    db = MagicMock()
    db.query.return_value.all.return_value = []
    results = recommend_sensor_sites(db, top_k=5)
    assert results == []


def test_higher_std_outranks_lower_std_at_equal_population(monkeypatch):
    grid = [
        GridPoint(lat=19.0, lon=72.8, ward_id="A", ward_name="A", population=100_000, aqi=150.0, std=10.0, method="gnn"),
        GridPoint(lat=19.1, lon=72.9, ward_id="B", ward_name="B", population=100_000, aqi=150.0, std=30.0, method="gnn"),
    ]
    import app.analytics.sensor_placement as sp
    monkeypatch.setattr(sp, "scan_grid", lambda db, **k: grid)
    db = MagicMock()
    db.query.return_value.all.return_value = []
    results = recommend_sensor_sites(db, top_k=5)
    assert results[0].ward_id == "B"  # higher std wins
    assert results[0].score > results[1].score


def test_higher_population_outranks_lower_population_at_equal_std(monkeypatch):
    grid = [
        GridPoint(lat=19.0, lon=72.8, ward_id="LOW_POP", ward_name="Low", population=1_000, aqi=150.0, std=20.0, method="gnn"),
        GridPoint(lat=19.1, lon=72.9, ward_id="HIGH_POP", ward_name="High", population=2_000_000, aqi=150.0, std=20.0, method="gnn"),
    ]
    import app.analytics.sensor_placement as sp
    monkeypatch.setattr(sp, "scan_grid", lambda db, **k: grid)
    db = MagicMock()
    db.query.return_value.all.return_value = []
    results = recommend_sensor_sites(db, top_k=5)
    assert results[0].ward_id == "HIGH_POP"


def test_top_k_truncates(monkeypatch):
    grid = [
        GridPoint(lat=19.0 + i * 0.01, lon=72.8, ward_id=f"W{i}", ward_name=f"W{i}", population=1000 * (i + 1), aqi=150.0, std=10.0 + i, method="gnn")
        for i in range(10)
    ]
    import app.analytics.sensor_placement as sp
    monkeypatch.setattr(sp, "scan_grid", lambda db, **k: grid)
    db = MagicMock()
    db.query.return_value.all.return_value = []
    results = recommend_sensor_sites(db, top_k=3)
    assert len(results) == 3


def test_no_existing_stations_means_no_exclusion(monkeypatch):
    grid = [GridPoint(lat=19.0, lon=72.8, ward_id="A", ward_name="A", population=10_000, aqi=150.0, std=15.0, method="gnn")]
    import app.analytics.sensor_placement as sp
    monkeypatch.setattr(sp, "scan_grid", lambda db, **k: grid)
    db = MagicMock()
    db.query.return_value.all.return_value = []
    results = recommend_sensor_sites(db, top_k=5)
    assert len(results) == 1
    assert results[0].nearest_station_distance_km == -1.0


def test_exclusion_radius_is_configurable(monkeypatch):
    import app.ml.gnn_model as gm
    distance = gm.haversine_km(19.00, 72.80, 19.027, 72.80)  # ~3km north
    grid = [GridPoint(lat=19.00, lon=72.80, ward_id="A", ward_name="A", population=10_000, aqi=150.0, std=15.0, method="gnn")]
    import app.analytics.sensor_placement as sp
    monkeypatch.setattr(sp, "scan_grid", lambda db, **k: grid)
    db = MagicMock()
    db.query.return_value.all.return_value = [_station("S1", 19.027, 72.80)]

    assert recommend_sensor_sites(db, top_k=5, exclusion_radius_km=5.0) == []
    assert len(recommend_sensor_sites(db, top_k=5, exclusion_radius_km=1.0)) == 1
