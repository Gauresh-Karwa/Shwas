from __future__ import annotations
from datetime import date

import pandas as pd
import requests

ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
REQUEST_TIMEOUT = 20

# One place to change if the exog feature set needs to grow or shrink —
# used identically for both endpoints so training and inference always
# see the same columns in the same order.
HOURLY_VARS = [
    "temperature_2m",
    "relative_humidity_2m",
    "wind_speed_10m",
    "wind_direction_10m",
    "surface_pressure",
    "precipitation",
]

COLUMN_RENAME = {
    "temperature_2m": "temp_c",
    "relative_humidity_2m": "humidity_pct",
    "wind_speed_10m": "wind_speed_mps",
    "wind_direction_10m": "wind_dir_deg",
    "surface_pressure": "pressure_hpa",
    "precipitation": "precip_mm",
}

EXOG_COLUMNS = list(COLUMN_RENAME.values())


def _empty_frame() -> pd.DataFrame:
    return pd.DataFrame(columns=["ds"] + EXOG_COLUMNS)


def _parse_hourly(payload: dict) -> pd.DataFrame:
    hourly = payload.get("hourly")
    if not hourly or "time" not in hourly:
        return _empty_frame()
    ds = pd.to_datetime(hourly["time"])
    if getattr(ds, "tz", None) is not None:
        ds = ds.tz_localize(None)
    df = pd.DataFrame({"ds": ds})
    for var in HOURLY_VARS:
        df[COLUMN_RENAME[var]] = hourly.get(var)
    return df


def get_historical_weather(lat: float, lon: float, start_date: date, end_date: date) -> pd.DataFrame:
    params = {
        "latitude": lat,
        "longitude": lon,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "hourly": ",".join(HOURLY_VARS),
        "wind_speed_unit": "ms",
        "timezone": "UTC",
    }
    try:
        response = requests.get(ARCHIVE_URL, params=params, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        return _parse_hourly(response.json())
    except requests.exceptions.RequestException as e:
        print(f"Open-Meteo archive request failed: {type(e).__name__}: {e}")
        return _empty_frame()


def get_forecast_weather(lat: float, lon: float, hours: int = 48) -> pd.DataFrame:
    forecast_days = max(1, min(16, -(-hours // 24)))  # ceil(hours / 24), capped at 16
    params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": ",".join(HOURLY_VARS),
        "wind_speed_unit": "ms",
        "timezone": "UTC",
        "forecast_days": forecast_days,
    }
    try:
        response = requests.get(FORECAST_URL, params=params, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        df = _parse_hourly(response.json())
    except requests.exceptions.RequestException as e:
        print(f"Open-Meteo forecast request failed: {type(e).__name__}: {e}")
        return _empty_frame()
    return df.head(hours).reset_index(drop=True)


def get_recent_wind(lat: float, lon: float, hours: int = 12) -> pd.DataFrame:
    """Hourly 10 m wind for the last `hours` hours up to the current hour (UTC).

    Uses the forecast endpoint's `past_hours` window, which covers the most
    recent hours that the ERA5 archive does not have yet. Columns: ds,
    wind_speed_mps, wind_dir_deg (meteorological: the direction wind blows FROM).
    """
    params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": "wind_speed_10m,wind_direction_10m",
        "past_hours": max(1, min(48, int(hours))),
        "forecast_hours": 1,
        "wind_speed_unit": "ms",
        "timezone": "UTC",
    }
    columns = ["ds", "wind_speed_mps", "wind_dir_deg"]
    try:
        response = requests.get(FORECAST_URL, params=params, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        hourly = response.json().get("hourly")
    except requests.exceptions.RequestException as e:
        print(f"Open-Meteo recent wind request failed: {type(e).__name__}: {e}")
        return pd.DataFrame(columns=columns)
    if not hourly or "time" not in hourly:
        return pd.DataFrame(columns=columns)
    ds = pd.to_datetime(hourly["time"])
    if getattr(ds, "tz", None) is not None:
        ds = ds.tz_localize(None)
    return pd.DataFrame({
        "ds": ds,
        "wind_speed_mps": hourly.get("wind_speed_10m"),
        "wind_dir_deg": hourly.get("wind_direction_10m"),
    })