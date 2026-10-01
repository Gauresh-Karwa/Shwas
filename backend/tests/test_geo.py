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