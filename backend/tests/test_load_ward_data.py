from unittest.mock import patch

from scripts.load_ward_data import fetch_ward_boundaries, swap_lat_lon, WARD_POPULATION

SAMPLE_GEOJSON = {
    "type": "FeatureCollection",
    "features": [
        {
            "type": "Feature",
            "properties": {"Name": "\n    G/S\n   ", "NAME2": "G/S\n"},
            "geometry": {
                "type": "Polygon",
                "coordinates": [[[19.02, 72.83, 0.0], [19.03, 72.84, 0.0], [19.01, 72.85, 0.0], [19.02, 72.83, 0.0]]],
            },
        },
        {
            "type": "Feature",
            "properties": {"Name": "\n    F/N\n   ", "NAME2": "F/N\n"},
            "geometry": {
                "type": "Polygon",
                "coordinates": [[[19.10, 72.90, 0.0], [19.11, 72.91, 0.0], [19.09, 72.92, 0.0], [19.10, 72.90, 0.0]]],
            },
        },
    ],
}


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def test_swap_lat_lon_fixes_polygon_order_and_drops_elevation():
    geometry = {"type": "Polygon", "coordinates": [[[19.02, 72.83, 0.0], [19.03, 72.84, 0.0]]]}
    fixed = swap_lat_lon(geometry)
    assert fixed == {"type": "Polygon", "coordinates": [[[72.83, 19.02], [72.84, 19.03]]]}


def test_swap_lat_lon_handles_multipolygon():
    geometry = {
        "type": "MultiPolygon",
        "coordinates": [[[[19.0, 72.8, 0.0], [19.1, 72.9, 0.0]]]],
    }
    fixed = swap_lat_lon(geometry)
    assert fixed == {"type": "MultiPolygon", "coordinates": [[[[72.8, 19.0], [72.9, 19.1]]]]}


def test_swap_lat_lon_rejects_unknown_geometry_type():
    import pytest
    with pytest.raises(ValueError):
        swap_lat_lon({"type": "Point", "coordinates": [19.0, 72.8]})


def test_fetch_ward_boundaries_strips_whitespace_from_name():
    with patch("scripts.load_ward_data.requests.get", return_value=_FakeResponse(SAMPLE_GEOJSON)):
        boundaries = fetch_ward_boundaries()
    assert set(boundaries.keys()) == {"G/S", "F/N"}


def test_fetch_ward_boundaries_output_is_lon_lat_order():
    with patch("scripts.load_ward_data.requests.get", return_value=_FakeResponse(SAMPLE_GEOJSON)):
        boundaries = fetch_ward_boundaries()
    first_point = boundaries["G/S"]["coordinates"][0][0]
    assert first_point[0] > 70
    assert first_point[1] < 20


def test_all_24_population_wards_have_unique_codes():
    codes = [row[0] for row in WARD_POPULATION]
    assert len(codes) == 24
    assert len(set(codes)) == 24


def test_population_figures_are_all_positive():
    assert all(row[2] > 0 for row in WARD_POPULATION)