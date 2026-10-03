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


# ── Ward-coverage behaviour ──────────────────────────────────────────────

def _square(lat, lon, half=0.05):
    return {"type": "Polygon", "coordinates": [[
        [lon - half, lat - half], [lon + half, lat - half],
        [lon + half, lat + half], [lon - half, lat + half], [lon - half, lat - half],
    ]]}


def _db(stations, boundaries):
    """Fake session that answers query(Station) and query(WardBoundary) differently."""
    from app.models.db_models import Station, WardBoundary
    db = MagicMock()
    rows = {Station: stations, WardBoundary: boundaries}
    db.query.side_effect = lambda model: MagicMock(all=MagicMock(return_value=rows[model]))
    return db


def _boundary(ward_id, lat, lon):
    b = MagicMock()
    b.ward_id, b.geometry = ward_id, _square(lat, lon)
    return b


def _gp(lat, lon, ward, pop, std):
    return GridPoint(lat=lat, lon=lon, ward_id=ward, ward_name=ward, population=pop, aqi=100.0, std=std, method="gnn")


def test_unmonitored_ward_is_recommended_even_with_lower_score(monkeypatch):
    import app.analytics.sensor_placement as sp
    # Ward M has a station and a very high-scoring point; ward U has no station
    # and a much lower-scoring point. With top_k=2 BOTH must appear.
    grid = [
        _gp(19.00, 72.80, "M", 2_000_000, 40.0),
        _gp(19.30, 72.80, "M", 2_000_000, 39.0),
        _gp(19.00, 73.00, "U", 50_000, 5.0),
    ]
    monkeypatch.setattr(sp, "scan_grid", lambda db, **k: grid)
    db = _db([_station("S1", 19.00, 72.80)], [_boundary("M", 19.00, 72.80), _boundary("U", 19.00, 73.00)])
    results = recommend_sensor_sites(db, top_k=2, exclusion_radius_km=1.0)
    wards = {r.ward_id: r for r in results}
    assert set(wards) == {"M", "U"}
    assert wards["U"].reason == "unmonitored_ward"
    assert wards["M"].reason == "coverage_gap"


def test_ward_already_covered_by_nearby_station_is_not_recommended(monkeypatch):
    import app.analytics.sensor_placement as sp
    # Ward U has no station inside it, but its only point is 0.3 km from one.
    grid = [_gp(19.00, 72.803, "U", 500_000, 20.0)]
    monkeypatch.setattr(sp, "scan_grid", lambda db, **k: grid)
    db = _db([_station("S1", 19.00, 72.80)], [_boundary("U", 19.00, 72.803)])
    assert recommend_sensor_sites(db, top_k=5, exclusion_radius_km=1.0) == []


def test_recommended_sites_keep_minimum_separation(monkeypatch):
    import app.analytics.sensor_placement as sp
    import app.ml.gnn_model as gm
    # Three neighbouring high-scoring points ~1.1 km apart in one big ward.
    grid = [_gp(19.00 + i * 0.01, 72.80, "W", 1_000_000, 30.0 - i) for i in range(3)]
    monkeypatch.setattr(sp, "scan_grid", lambda db, **k: grid)
    db = _db([], [_boundary("W", 19.01, 72.80)])
    results = recommend_sensor_sites(db, top_k=3, min_separation_km=2.0)
    assert len(results) == 2  # the middle point is < 2 km from the first
    for i, a in enumerate(results):
        for b in results[i + 1:]:
            assert gm.haversine_km(a.lat, a.lon, b.lat, b.lon) >= 2.0


def test_one_site_per_unmonitored_ward_before_second_site_in_same_ward(monkeypatch):
    import app.analytics.sensor_placement as sp
    grid = [
        _gp(19.00, 72.80, "BIG", 2_000_000, 40.0),
        _gp(19.10, 72.80, "BIG", 2_000_000, 39.0),   # 2nd-best point in the same ward
        _gp(19.30, 72.95, "SMALL", 60_000, 4.0),
    ]
    monkeypatch.setattr(sp, "scan_grid", lambda db, **k: grid)
    db = _db([], [_boundary("BIG", 19.05, 72.80), _boundary("SMALL", 19.30, 72.95)])
    results = recommend_sensor_sites(db, top_k=2)
    assert {r.ward_id for r in results} == {"BIG", "SMALL"}


def test_ward_boundary_failure_falls_back_to_score_ranking(monkeypatch):
    import app.analytics.sensor_placement as sp
    grid = [_gp(19.0, 72.8, "A", 100_000, 10.0), _gp(19.2, 72.9, "B", 100_000, 30.0)]
    monkeypatch.setattr(sp, "scan_grid", lambda db, **k: grid)
    db = MagicMock()
    db.query.return_value.all.return_value = []
    db.query.side_effect = [MagicMock(all=MagicMock(return_value=[])), RuntimeError("db down")]
    results = recommend_sensor_sites(db, top_k=2)
    assert [r.ward_id for r in results] == ["B", "A"]
    assert all(r.reason == "coverage_gap" for r in results)