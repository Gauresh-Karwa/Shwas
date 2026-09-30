from datetime import date
from unittest.mock import patch

import pandas as pd
import pytest
import requests

from app.attribution import open_meteo_client as omc
SAMPLE_RESPONSE = {
    "latitude": 19.05,
    "longitude": 72.87,
    "hourly": {
        "time": ["2020-01-01T00:00", "2020-01-01T01:00", "2020-01-01T02:00"],
        "temperature_2m": [24.1, 23.8, 23.5],
        "relative_humidity_2m": [70, 72, 75],
        "wind_speed_10m": [3.2, 2.9, 2.5],
        "wind_direction_10m": [270, 265, 260],
        "surface_pressure": [1010.1, 1010.3, 1010.5],
        "precipitation": [0.0, 0.0, 0.1],
    },
}


class _FakeResponse:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.exceptions.HTTPError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


def test_historical_weather_parses_documented_schema():
    with patch("app.attribution.open_meteo_client.requests.get", return_value=_FakeResponse(SAMPLE_RESPONSE)):
        df = omc.get_historical_weather(19.05, 72.87, date(2020, 1, 1), date(2020, 1, 1))
    assert list(df.columns) == ["ds"] + omc.EXOG_COLUMNS
    assert len(df) == 3
    assert df["temp_c"].tolist() == [24.1, 23.8, 23.5]
    assert df["humidity_pct"].tolist() == [70, 72, 75]
    assert df["wind_speed_mps"].tolist() == [3.2, 2.9, 2.5]
    assert pd.api.types.is_datetime64_any_dtype(df["ds"])


def test_historical_weather_sends_correct_params():
    captured = {}

    def fake_get(url, params=None, timeout=None):
        captured["url"] = url
        captured["params"] = params
        return _FakeResponse(SAMPLE_RESPONSE)

    with patch("app.attribution.open_meteo_client.requests.get", side_effect=fake_get):
        omc.get_historical_weather(19.05, 72.87, date(2020, 1, 1), date(2020, 1, 31))
    assert captured["url"] == omc.ARCHIVE_URL
    assert captured["params"]["start_date"] == "2020-01-01"
    assert captured["params"]["end_date"] == "2020-01-31"
    assert captured["params"]["wind_speed_unit"] == "ms"
    assert set(captured["params"]["hourly"].split(",")) == set(omc.HOURLY_VARS)


def test_historical_weather_returns_empty_frame_on_request_failure():
    with patch("app.attribution.open_meteo_client.requests.get", side_effect=requests.exceptions.ConnectionError):
        df = omc.get_historical_weather(19.05, 72.87, date(2020, 1, 1), date(2020, 1, 1))
    assert df.empty
    assert list(df.columns) == ["ds"] + omc.EXOG_COLUMNS


def test_historical_weather_returns_empty_frame_on_http_error():
    with patch("app.attribution.open_meteo_client.requests.get", return_value=_FakeResponse({}, status=400)):
        df = omc.get_historical_weather(19.05, 72.87, date(2020, 1, 1), date(2020, 1, 1))
    assert df.empty


def test_forecast_weather_truncates_to_requested_hours():
    # 3 days worth (72 hourly points), but only 30 hours requested.
    hours = 72
    times = pd.date_range("2026-01-01", periods=hours, freq="1h").strftime("%Y-%m-%dT%H:%M").tolist()
    payload = {"hourly": {"time": times, **{v: [1.0] * hours for v in omc.HOURLY_VARS}}}
    with patch("app.attribution.open_meteo_client.requests.get", return_value=_FakeResponse(payload)):
        df = omc.get_forecast_weather(19.05, 72.87, hours=30)
    assert len(df) == 30


@pytest.mark.parametrize("hours,expected_forecast_days", [(1, 1), (24, 1), (25, 2), (48, 2), (49, 3), (400, 16)])
def test_forecast_weather_requests_correct_forecast_days(hours, expected_forecast_days):
    captured = {}

    def fake_get(url, params=None, timeout=None):
        captured["forecast_days"] = params["forecast_days"]
        n = params["forecast_days"] * 24
        times = pd.date_range("2026-01-01", periods=n, freq="1h").strftime("%Y-%m-%dT%H:%M").tolist()
        return _FakeResponse({"hourly": {"time": times, **{v: [1.0] * n for v in omc.HOURLY_VARS}}})

    with patch("app.attribution.open_meteo_client.requests.get", side_effect=fake_get):
        omc.get_forecast_weather(19.05, 72.87, hours=hours)
    assert captured["forecast_days"] == expected_forecast_days


def test_missing_hourly_key_returns_empty_frame():
    with patch("app.attribution.open_meteo_client.requests.get", return_value=_FakeResponse({"latitude": 1})):
        df = omc.get_historical_weather(19.05, 72.87, date(2020, 1, 1), date(2020, 1, 1))
    assert df.empty


def test_timezone_aware_input_is_normalized_to_naive():
    tz_aware_payload = {
        "hourly": {
            "time": ["2020-01-01T00:00+00:00", "2020-01-01T01:00+00:00"],
            "temperature_2m": [24.0, 23.5],
            "relative_humidity_2m": [70, 71],
            "wind_speed_10m": [3.0, 3.1],
            "wind_direction_10m": [270, 271],
            "surface_pressure": [1010.0, 1010.1],
            "precipitation": [0.0, 0.0],
        }
    }
    with patch("app.attribution.open_meteo_client.requests.get", return_value=_FakeResponse(tz_aware_payload)):
        df = omc.get_historical_weather(19.05, 72.87, date(2020, 1, 1), date(2020, 1, 1))
    assert df["ds"].dt.tz is None
    naive_index = pd.DatetimeIndex(["2020-01-01T00:00:00", "2020-01-01T01:00:00"])
    matched = df.set_index("ds").reindex(naive_index)
    assert not matched["temp_c"].isna().any()