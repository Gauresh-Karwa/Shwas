import pytest
from app.interpolation.idw import (
    haversine_km,
    bearing_deg,
    _confidence_for_distance,
    idw_interpolate,
    InterpolationResult,
)

def test_haversine_same_point():
    assert haversine_km(19.0, 72.8, 19.0, 72.8) == 0.0

def test_haversine_known_mumbai_distance():
    dist = haversine_km(18.9220, 72.8347, 19.1176, 72.9060)
    assert 20.0 < dist < 30.0

def test_haversine_symmetric():
    d1 = haversine_km(19.0, 72.8, 19.2, 73.0)
    d2 = haversine_km(19.2, 73.0, 19.0, 72.8)
    assert pytest.approx(d1, rel=1e-5) == d2

def test_bearing_cardinal_directions():
    assert pytest.approx(bearing_deg(19.0, 72.8, 20.0, 72.8), abs=1.0) == 0.0
    assert pytest.approx(bearing_deg(19.0, 72.8, 18.0, 72.8), abs=1.0) == 180.0
    assert pytest.approx(bearing_deg(19.0, 72.8, 19.0, 73.8), abs=1.0) == 90.0
    assert pytest.approx(bearing_deg(19.0, 72.8, 19.0, 71.8), abs=1.0) == 270.0

def test_confidence_for_distance():
    assert _confidence_for_distance(1.5) == 'high'
    assert _confidence_for_distance(2.0) == 'high'
    assert _confidence_for_distance(3.5) == 'medium'
    assert _confidence_for_distance(5.0) == 'medium'
    assert _confidence_for_distance(7.5) == 'low'
    assert _confidence_for_distance(10.0) == 'low'
    assert _confidence_for_distance(15.0) == 'insufficient'

def test_idw_empty_stations():
    assert idw_interpolate(19.0, 72.8, []) is None

def test_idw_exact_station_match():
    stations = [(19.0, 72.8, 120.0), (19.2, 73.0, 80.0)]
    res = idw_interpolate(19.0, 72.8, stations)
    assert isinstance(res, InterpolationResult)
    assert res.estimated_aqi == 120.0
    assert res.confidence == 'high'
    assert res.stations_used == 1

def test_idw_midpoint_two_stations():
    stations = [(19.0, 72.8, 100.0), (19.2, 72.8, 200.0)]
    res = idw_interpolate(19.1, 72.8, stations)
    assert isinstance(res, InterpolationResult)
    assert pytest.approx(res.estimated_aqi, abs=1.0) == 150.0
    assert res.stations_used == 2

def test_idw_wind_correction_active():
    stations = [(19.0, 72.8, 100.0), (19.2, 72.8, 200.0)]
    res = idw_interpolate(19.1, 72.8, stations, wind_speed_mps=5.0, wind_from_deg=0.0)
    assert isinstance(res, InterpolationResult)
    assert res.wind_corrected is True
    assert res.estimated_aqi > 0
