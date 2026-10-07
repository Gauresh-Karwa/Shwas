from __future__ import annotations

import json
import math
from types import SimpleNamespace

import pytest

from app.attribution import trajectory as tj
from app.attribution.trajectory import (
    TrajectoryPoint, WardShape, WindHour, back_trajectory, build_trajectory,
    classify_fires, destination_point, distance_to_path,
)
from app.interpolation.idw import bearing_deg, haversine_km

STATION = (19.05, 72.95)


def _winds(speed, direction, n):
    return [WindHour(hours_back=i, speed_mps=speed, direction_deg=direction) for i in range(n)]


def _fire(lat, lon, frp=20.0):
    return SimpleNamespace(latitude=lat, longitude=lon, frp_mw=frp)


# ── geometry ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("bearing", [0, 45, 90, 180, 270, 333])
def test_destination_point_matches_distance_and_bearing(bearing):
    lat, lon = destination_point(*STATION, bearing, 25.0)
    assert haversine_km(*STATION, lat, lon) == pytest.approx(25.0, abs=0.01)
    assert bearing_deg(*STATION, lat, lon) == pytest.approx(bearing, abs=0.2)


def test_wind_from_the_west_traces_the_air_back_to_the_west():
    pts = back_trajectory(*STATION, _winds(5.0, 270.0, 3))
    assert [p.hours_back for p in pts] == [0.0, 1.0, 2.0, 3.0]
    assert all(b.lon < a.lon for a, b in zip(pts, pts[1:]))          # keeps moving west
    assert pts[-1].lat == pytest.approx(STATION[0], abs=0.02)         # no north/south drift
    assert haversine_km(*STATION, pts[-1].lat, pts[-1].lon) == pytest.approx(5.0 * 3.6 * 3, abs=0.2)


def test_wind_from_north_east_traces_the_air_back_to_the_north_east():
    pts = back_trajectory(*STATION, _winds(4.0, 45.0, 2))
    assert pts[-1].lat > STATION[0] and pts[-1].lon > STATION[1]


def test_calm_or_missing_wind_does_not_move_the_air():
    pts = back_trajectory(*STATION, [WindHour(0, 0.2, 90.0), WindHour(1, 5.0, None), WindHour(2, None, 90.0)])
    assert all((p.lat, p.lon) == STATION for p in pts)


def test_each_hour_uses_its_own_wind():
    # latest hour: wind from the west, hour before: wind from the south
    pts = back_trajectory(*STATION, [WindHour(0, 5.0, 270.0), WindHour(1, 5.0, 180.0)])
    assert pts[1].lon < STATION[1] and pts[1].lat == pytest.approx(STATION[0], abs=0.01)
    assert pts[2].lat < pts[1].lat                                    # then back to the south


# ── distance to path ──────────────────────────────────────────────────────

def _line():
    return back_trajectory(*STATION, _winds(5.0, 270.0, 3))   # 18 km per hour, due west


def test_point_on_path_has_zero_distance_and_interpolated_hours():
    path = _line()
    mid = destination_point(*STATION, 270.0, 27.0)            # 1.5 h upwind
    d, hb = distance_to_path(mid[0], mid[1], path)
    assert d == pytest.approx(0.0, abs=0.05)
    assert hb == pytest.approx(1.5, abs=0.02)


def test_point_off_to_the_side_reports_the_perpendicular_distance():
    path = _line()
    on = destination_point(*STATION, 270.0, 27.0)
    off = destination_point(on[0], on[1], 0.0, 3.0)           # 3 km north of the path
    d, _ = distance_to_path(off[0], off[1], path)
    assert d == pytest.approx(3.0, abs=0.1)


def test_point_beyond_the_end_uses_the_end_point():
    path = _line()
    beyond = destination_point(path[-1].lat, path[-1].lon, 270.0, 10.0)
    d, hb = distance_to_path(beyond[0], beyond[1], path)
    assert d == pytest.approx(10.0, abs=0.1) and hb == pytest.approx(3.0)


# ── fire classification: the point of the whole exercise ──────────────────

def test_fire_upwind_on_the_path_is_flagged():
    path = _line()
    spot = destination_point(*STATION, 270.0, 36.0)           # 2 h upwind
    near = destination_point(spot[0], spot[1], 0.0, 2.0)
    on, off = classify_fires(path, [_fire(*near)])
    assert len(on) == 1 and off == 0
    assert on[0].hours_upwind == pytest.approx(2.0, abs=0.05)
    assert on[0].distance_to_path_km == pytest.approx(2.0, abs=0.1)


def test_fire_downwind_of_the_station_is_not_blamed():
    path = _line()                                            # air comes from the west
    east = destination_point(*STATION, 90.0, 4.0)             # 4 km EAST of the station (downwind)
    on, off = classify_fires(path, [_fire(*east)])
    assert on == [] and off == 1


def test_fire_far_from_the_path_is_not_blamed():
    path = _line()
    spot = destination_point(*STATION, 270.0, 27.0)
    far = destination_point(spot[0], spot[1], 0.0, 20.0)
    on, off = classify_fires(path, [_fire(*far)])
    assert on == [] and off == 1


def test_fire_at_the_station_itself_is_not_treated_as_upwind():
    on, off = classify_fires(_line(), [_fire(STATION[0] + 0.005, STATION[1])])
    assert on == [] and off == 1


def test_fires_on_path_are_sorted_by_distance_to_path():
    path = _line()
    a = destination_point(*destination_point(*STATION, 270.0, 20.0), 0.0, 4.0)
    b = destination_point(*destination_point(*STATION, 270.0, 40.0), 0.0, 1.0)
    on, _ = classify_fires(path, [_fire(*a), _fire(*b)])
    assert [round(f.distance_to_path_km) for f in on] == [1, 4]


# ── what the path crossed (synthetic wards) ───────────────────────────────

def _square(lat0, lat1, lon0, lon1):
    ring = [[lon0, lat0], [lon1, lat0], [lon1, lat1], [lon0, lat1], [lon0, lat0]]
    return {"type": "Polygon", "coordinates": [ring]}


WARD_B = WardShape("B", "West Ward", _square(19.03, 19.07, 72.80, 72.90))
WARD_A = WardShape("A", "East Ward", _square(19.03, 19.07, 72.90, 73.00))


def test_path_over_land_then_sea_reports_wards_oldest_first_and_sea_hours():
    t = build_trajectory(*STATION, _winds(4.0, 270.0, 3), wards=[WARD_A, WARD_B])
    assert [w["ward_id"] for w in t.wards_crossed] == ["B", "A"]          # B was earlier than A
    assert t.wards_crossed[0]["hours_back"] > t.wards_crossed[1]["hours_back"]
    assert t.marine_hours == pytest.approx(1.85, abs=0.25)                # west of 72.80 is sea
    assert t.over_sea is True
    assert "At least 1 h of that was over the sea" in t.summary()      # 1.85 h rounds DOWN, never up


def test_path_entirely_over_land_has_no_sea_hours():
    t = build_trajectory(*STATION, _winds(1.8, 270.0, 2), wards=[WARD_A, WARD_B])
    assert t.marine_hours == 0.0 and t.over_sea is False


def test_sea_hours_are_unknown_when_no_ward_data_is_available():
    t = build_trajectory(*STATION, _winds(4.0, 270.0, 3), wards=[])
    assert t.marine_hours is None and t.wards_crossed == [] and t.over_sea is False


def test_east_of_the_city_is_not_called_sea():
    t = build_trajectory(*STATION, _winds(5.0, 90.0, 3), wards=[WARD_A, WARD_B])   # air from the east
    assert not t.over_sea


# ── full analysis ─────────────────────────────────────────────────────────

def test_no_wind_data_gives_no_trajectory():
    assert build_trajectory(*STATION, []) is None
    assert build_trajectory(*STATION, [WindHour(0, None, None)]) is None


def test_stagnant_air_is_flagged_and_explained():
    t = build_trajectory(*STATION, _winds(0.8, 200.0, 6))
    assert t.stagnant and "Winds were light" in t.summary() and "0.8 m/s" in t.summary()


def test_origin_is_reported_with_distance_and_compass():
    t = build_trajectory(*STATION, _winds(5.0, 270.0, 3))
    assert t.origin_compass == "W"
    assert t.origin_distance_km == pytest.approx(54.0, abs=0.5)
    assert t.path_km == pytest.approx(54.0, abs=0.5)
    assert t.arrival_direction_deg == 270.0


def test_summary_mentions_upwind_fire_and_off_path_fires():
    spot = destination_point(*STATION, 270.0, 36.0)
    t = build_trajectory(*STATION, _winds(5.0, 270.0, 3), fires=[_fire(*spot)])
    assert "upwind" in t.summary() and "right on that path" in t.summary()
    east = destination_point(*STATION, 90.0, 5.0)
    t2 = build_trajectory(*STATION, _winds(5.0, 270.0, 3), fires=[_fire(*east)])
    assert "not on the air's path" in t2.summary()


def test_to_dict_is_json_serialisable_with_the_documented_keys():
    spot = destination_point(*STATION, 270.0, 36.0)
    t = build_trajectory(*STATION, _winds(4.0, 270.0, 3), fires=[_fire(*spot)], wards=[WARD_A, WARD_B])
    d = json.loads(json.dumps(t.to_dict()))
    assert set(d) == {"hours", "path_km", "mean_speed_mps", "stagnant", "arrival_from", "origin",
                      "points", "over", "fires_on_path", "fires_off_path", "summary"}
    assert len(d["points"]) == 4 and d["points"][0]["hours_back"] == 0.0
    assert d["arrival_from"]["compass"] == "W"
    assert set(d["over"]) == {"wards", "marine_hours", "sea"}