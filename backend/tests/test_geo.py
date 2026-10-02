import pytest

from app.analytics.geo import polygon_centroid


def test_square_centroid_is_its_middle():
    geometry = {
        "type": "Polygon",
        "coordinates": [[[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]],
    }
    lat, lon = polygon_centroid(geometry)
    assert lat == pytest.approx(5.0)
    assert lon == pytest.approx(5.0)


def test_rectangle_centroid():
    geometry = {
        "type": "Polygon",
        "coordinates": [[[0, 0], [20, 0], [20, 10], [0, 10], [0, 0]]],
    }
    lat, lon = polygon_centroid(geometry)
    assert lat == pytest.approx(5.0)
    assert lon == pytest.approx(10.0)


def test_right_triangle_centroid():
    geometry = {
        "type": "Polygon",
        "coordinates": [[[0, 0], [6, 0], [0, 6], [0, 0]]],
    }
    lat, lon = polygon_centroid(geometry)
    assert lat == pytest.approx(2.0)
    assert lon == pytest.approx(2.0)


def test_centroid_independent_of_winding_direction():
    geometry = {
        "type": "Polygon",
        "coordinates": [[[0, 0], [0, 10], [10, 10], [10, 0], [0, 0]]],
    }
    lat, lon = polygon_centroid(geometry)
    assert lat == pytest.approx(5.0)
    assert lon == pytest.approx(5.0)


def test_multipolygon_picks_the_larger_part():
    geometry = {
        "type": "MultiPolygon",
        "coordinates": [
            [[[100, 100], [101, 100], [101, 101], [100, 101], [100, 100]]],
            [[[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]],
        ],
    }
    lat, lon = polygon_centroid(geometry)
    assert lat == pytest.approx(5.0)
    assert lon == pytest.approx(5.0)


def test_unsupported_geometry_type_raises():
    with pytest.raises(ValueError):
        polygon_centroid({"type": "Point", "coordinates": [0, 0]})


def test_degenerate_ring_falls_back_to_vertex_average_not_nan():
    geometry = {"type": "Polygon", "coordinates": [[[0, 0], [5, 0], [10, 0], [0, 0]]]}
    lat, lon = polygon_centroid(geometry)
    assert lat == pytest.approx(0.0)
    assert lon == pytest.approx(5.0)


from app.analytics.geo import point_in_geometry


def test_point_clearly_inside_square():
    square = {"type": "Polygon", "coordinates": [[[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]]}
    assert point_in_geometry(5, 5, square) is True  # (lat=5, lon=5) -> center


def test_point_clearly_outside_square():
    square = {"type": "Polygon", "coordinates": [[[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]]}
    assert point_in_geometry(50, 50, square) is False


def test_point_outside_but_near_edge():
    square = {"type": "Polygon", "coordinates": [[[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]]}
    assert point_in_geometry(5, 10.5, square) is False


def test_point_inside_multipolygon_second_part():
    multi = {
        "type": "MultiPolygon",
        "coordinates": [
            [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]],
            [[[100, 100], [101, 100], [101, 101], [100, 101], [100, 100]]],
        ],
    }
    assert point_in_geometry(100.5, 100.5, multi) is True
    assert point_in_geometry(0.5, 0.5, multi) is True
    assert point_in_geometry(50, 50, multi) is False


def test_point_in_geometry_rejects_unknown_type():
    with pytest.raises(ValueError):
        point_in_geometry(0, 0, {"type": "Point", "coordinates": [0, 0]})


def test_adjacent_wards_share_no_double_counted_point():
    left = {"type": "Polygon", "coordinates": [[[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]]}
    right = {"type": "Polygon", "coordinates": [[[10, 0], [20, 0], [20, 10], [10, 10], [10, 0]]]}
    assert point_in_geometry(5, 5, left) is True
    assert point_in_geometry(5, 5, right) is False
    assert point_in_geometry(5, 15, left) is False
    assert point_in_geometry(5, 15, right) is True