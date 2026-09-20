import pytest

try:
    from app.aqi.calculator import compute_sub_index, compute_aqi, normalize_raw_reading
except ImportError:
    from calculator import compute_sub_index, compute_aqi, normalize_raw_reading


def test_sub_index_pm25_known_value_323():
    assert round(compute_sub_index("PM2.5", 150)) == 323


def test_sub_index_pm25_known_value_75():
    assert round(compute_sub_index("PM2.5", 45)) == 75


def test_sub_index_exact_boundary():
    assert compute_sub_index("PM2.5", 30) == 50
    assert compute_sub_index("PM2.5", 31) == 51


def test_sub_index_unknown_pollutant_returns_none():
    assert compute_sub_index("RADON", 10) is None


def test_sub_index_negative_concentration_returns_none():
    assert compute_sub_index("PM2.5", -5) is None


def test_co_unit_normalization():
    assert normalize_raw_reading("CO", 20) == pytest.approx(0.20)
    assert normalize_raw_reading("PM2.5", 20) == 20  # only CO is scaled


def test_aqi_valid_reading_sion_station():
    readings = {"PM2.5": 9, "PM10": 13, "SO2": 5, "CO": 20}
    result = compute_aqi(readings)
    assert result.status == "ok"
    assert result.category == "Good"
    assert result.dominant_pollutant == "PM2.5"  # not CO, now that units are fixed


def test_aqi_insufficient_data_powai():
    readings = {"NO2": 6, "SO2": 13}
    result = compute_aqi(readings)
    assert result.status == "insufficient_data"
    assert result.aqi is None


def test_aqi_insufficient_data_bkc_iitm():
    
    readings = {"CO": 35, "OZONE": 15}
    result = compute_aqi(readings)
    assert result.status == "insufficient_data"


def test_aqi_fails_minimum_count_even_with_pm():
    readings = {"PM2.5": 45, "PM10": 60}
    result = compute_aqi(readings)
    assert result.status == "insufficient_data"


def test_aqi_dominant_pollutant_is_max_not_average():
    
    readings = {"PM2.5": 200, "PM10": 50, "SO2": 10, "CO": 1}
    result = compute_aqi(readings)
    assert result.status == "ok"
    assert result.dominant_pollutant == "PM2.5"


def test_aqi_severe_category():
    readings = {"PM2.5": 300, "PM10": 500, "SO2": 10, "CO": 5}
    result = compute_aqi(readings)
    assert result.category == "Severe"


def test_aqi_without_co_unit_fix_would_have_been_wrong():
  
    readings = {"PM2.5": 10, "PM10": 15, "SO2": 5, "CO": 42}  # realistic clean day
    result = compute_aqi(readings)
    assert result.category in ("Good", "Satisfactory")  # NOT Very Poor/Severe
