from unittest.mock import MagicMock

from app.analytics.grid_scan import GridPoint
from app.analytics.hotspots import detect_hotspots


def test_noisy_high_estimate_is_not_flagged(monkeypatch):
    # mean=180, std=45 -> LCB = 180 - 1.96*45 = 91.8 -> below threshold 100.
    grid = [GridPoint(lat=19.0, lon=72.8, ward_id="A", ward_name="A", population=10_000, aqi=180.0, std=45.0, method="gnn")]
    import app.analytics.hotspots as hs
    monkeypatch.setattr(hs, "scan_grid", lambda db, **k: grid)
    results = detect_hotspots(MagicMock(), threshold=100.0)
    assert results == []


def test_confident_moderately_high_estimate_is_flagged(monkeypatch):
    grid = [GridPoint(lat=19.0, lon=72.8, ward_id="A", ward_name="A", population=10_000, aqi=165.0, std=8.0, method="gnn")]
    import app.analytics.hotspots as hs
    monkeypatch.setattr(hs, "scan_grid", lambda db, **k: grid)
    results = detect_hotspots(MagicMock(), threshold=100.0)
    assert len(results) == 1
    assert abs(results[0].lcb - 149.3) < 0.2
    assert results[0].method == "gnn"


def test_idw_point_uses_raw_aqi_as_lcb_with_no_correction(monkeypatch):
    grid = [GridPoint(lat=19.0, lon=72.8, ward_id="A", ward_name="A", population=10_000, aqi=150.0, std=None, method="idw")]
    import app.analytics.hotspots as hs
    monkeypatch.setattr(hs, "scan_grid", lambda db, **k: grid)
    results = detect_hotspots(MagicMock(), threshold=100.0)
    assert len(results) == 1
    assert results[0].lcb == 150.0
    assert results[0].method == "idw"


def test_threshold_filters_out_low_lcb_points(monkeypatch):
    grid = [
        GridPoint(lat=19.0, lon=72.8, ward_id="LOW", ward_name="Low", population=1000, aqi=50.0, std=5.0, method="gnn"),
        GridPoint(lat=19.1, lon=72.9, ward_id="HIGH", ward_name="High", population=1000, aqi=200.0, std=5.0, method="gnn"),
    ]
    import app.analytics.hotspots as hs
    monkeypatch.setattr(hs, "scan_grid", lambda db, **k: grid)
    results = detect_hotspots(MagicMock(), threshold=100.0)
    assert {r.ward_id for r in results} == {"HIGH"}


def test_results_sorted_worst_lcb_first(monkeypatch):
    grid = [
        GridPoint(lat=19.0, lon=72.8, ward_id="A", ward_name="A", population=1000, aqi=160.0, std=2.0, method="gnn"),
        GridPoint(lat=19.1, lon=72.9, ward_id="B", ward_name="B", population=1000, aqi=250.0, std=2.0, method="gnn"),
    ]
    import app.analytics.hotspots as hs
    monkeypatch.setattr(hs, "scan_grid", lambda db, **k: grid)
    results = detect_hotspots(MagicMock(), threshold=100.0)
    assert [r.ward_id for r in results] == ["B", "A"]


def test_lcb_never_goes_negative(monkeypatch):
    grid = [GridPoint(lat=19.0, lon=72.8, ward_id="A", ward_name="A", population=1000, aqi=10.0, std=100.0, method="gnn")]
    import app.analytics.hotspots as hs
    monkeypatch.setattr(hs, "scan_grid", lambda db, **k: grid)
    results = detect_hotspots(MagicMock(), threshold=0.0)
    assert results[0].lcb == 0.0


def test_custom_z_changes_lcb(monkeypatch):
    grid = [GridPoint(lat=19.0, lon=72.8, ward_id="A", ward_name="A", population=1000, aqi=200.0, std=10.0, method="gnn")]
    import app.analytics.hotspots as hs
    monkeypatch.setattr(hs, "scan_grid", lambda db, **k: grid)
    results_strict = detect_hotspots(MagicMock(), threshold=0.0, z=1.96)
    results_loose = detect_hotspots(MagicMock(), threshold=0.0, z=0.5)
    assert results_loose[0].lcb > results_strict[0].lcb


# ── DBSCAN clustering of neighbouring hot cells ──────────────────────────

def _hot(lat, lon, ward, aqi, std=2.0):
    return GridPoint(lat=lat, lon=lon, ward_id=ward, ward_name=ward, population=1000, aqi=aqi, std=std, method="gnn")


def test_adjacent_hot_cells_merge_into_one_hotspot_with_worst_lcb(monkeypatch):
    # 0.018 deg ~ 2 km apart (grid step) -> one hotspot; 'mid' is the worst cell.
    grid = [_hot(19.000, 72.80, "a", 150.0), _hot(19.018, 72.80, "mid", 200.0), _hot(19.036, 72.80, "c", 160.0)]
    import app.analytics.hotspots as hs
    monkeypatch.setattr(hs, "scan_grid", lambda db, **k: grid)
    results = detect_hotspots(MagicMock(), threshold=100.0)
    assert len(results) == 1
    assert results[0].ward_id == "mid"
    assert results[0].cluster_size == 3


def test_diagonal_neighbour_on_the_grid_still_joins(monkeypatch):
    # diagonal of a 2 km grid is ~2.83 km, inside the default 3 km radius
    grid = [_hot(19.000, 72.800, "a", 150.0), _hot(19.018, 72.819, "b", 155.0)]
    import app.analytics.hotspots as hs
    monkeypatch.setattr(hs, "scan_grid", lambda db, **k: grid)
    assert len(detect_hotspots(MagicMock(), threshold=100.0)) == 1


def test_distant_hot_areas_stay_separate_hotspots(monkeypatch):
    grid = [_hot(19.00, 72.80, "a", 150.0), _hot(19.20, 72.90, "b", 150.0)]
    import app.analytics.hotspots as hs
    monkeypatch.setattr(hs, "scan_grid", lambda db, **k: grid)
    results = detect_hotspots(MagicMock(), threshold=100.0)
    assert len(results) == 2 and all(r.cluster_size == 1 for r in results)


def test_cluster_radius_zero_disables_clustering(monkeypatch):
    grid = [_hot(19.000, 72.80, "a", 150.0), _hot(19.018, 72.80, "b", 155.0)]
    import app.analytics.hotspots as hs
    monkeypatch.setattr(hs, "scan_grid", lambda db, **k: grid)
    assert len(detect_hotspots(MagicMock(), threshold=100.0, cluster_radius_km=0)) == 2