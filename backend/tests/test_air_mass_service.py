from __future__ import annotations

from datetime import datetime
from unittest.mock import patch

import pandas as pd
import pytest

from app.attribution import attribution_service as svc

NOW = datetime(2026, 10, 6, 12, 40)     # 12:40 UTC -> latest wind hour is 12:00


def _frame(rows):
    return pd.DataFrame(rows, columns=["ds", "wind_speed_mps", "wind_dir_deg"])


@pytest.fixture(autouse=True)
def _clear_cache():
    svc._WIND_CACHE.clear()
    yield
    svc._WIND_CACHE.clear()


def test_hours_are_counted_back_from_the_latest_hour_and_future_rows_are_dropped():
    df = _frame([
        (datetime(2026, 10, 6, 9), 3.0, 250.0),
        (datetime(2026, 10, 6, 11), 4.0, 260.0),
        (datetime(2026, 10, 6, 12), 5.0, 270.0),
        (datetime(2026, 10, 6, 13), 9.0, 10.0),      # not happened yet
    ])
    with patch("app.attribution.attribution_service.get_recent_wind", return_value=df):
        winds = svc._wind_hours(19.05, 72.9, hours=6, now=NOW)
    assert [(w.hours_back, w.speed_mps, w.direction_deg) for w in winds] == [
        (0, 5.0, 270.0), (1, 4.0, 260.0), (3, 3.0, 250.0)]


def test_rows_older_than_the_window_are_dropped():
    df = _frame([(datetime(2026, 10, 6, 5), 3.0, 250.0), (datetime(2026, 10, 6, 12), 5.0, 270.0)])
    with patch("app.attribution.attribution_service.get_recent_wind", return_value=df):
        winds = svc._wind_hours(19.05, 72.9, hours=6, now=NOW)
    assert [w.hours_back for w in winds] == [0]


def test_missing_values_become_none():
    df = _frame([(datetime(2026, 10, 6, 12), float("nan"), 270.0), (datetime(2026, 10, 6, 11), 4.0, None)])
    with patch("app.attribution.attribution_service.get_recent_wind", return_value=df):
        winds = svc._wind_hours(19.05, 72.9, hours=6, now=NOW)
    assert winds[0].speed_mps is None and winds[1].direction_deg is None


def test_results_are_cached_per_cell_and_hour():
    df = _frame([(datetime(2026, 10, 6, 12), 5.0, 270.0)])
    with patch("app.attribution.attribution_service.get_recent_wind", return_value=df) as m:
        svc._wind_hours(19.051, 72.901, hours=6, now=NOW)
        svc._wind_hours(19.052, 72.902, hours=6, now=NOW)      # same ~1 km cell
        assert m.call_count == 1
        svc._wind_hours(19.30, 72.90, hours=6, now=NOW)        # different cell
        assert m.call_count == 2


def test_failed_fetches_are_not_cached():
    with patch("app.attribution.attribution_service.get_recent_wind", return_value=_frame([])) as m:
        assert svc._wind_hours(19.05, 72.9, hours=6, now=NOW) == []
        svc._wind_hours(19.05, 72.9, hours=6, now=NOW)
        assert m.call_count == 2


def test_get_air_mass_returns_none_without_wind_and_a_trajectory_with_it():
    with patch("app.attribution.attribution_service.get_recent_wind", return_value=_frame([])):
        assert svc.get_air_mass(None, 19.05, 72.9, [], now=NOW) is None
    df = _frame([(datetime(2026, 10, 6, 12 - i), 5.0, 270.0) for i in range(6)])
    with patch("app.attribution.attribution_service.get_recent_wind", return_value=df):
        t = svc.get_air_mass(None, 19.05, 72.9, [], now=NOW)
    assert t is not None and t.hours == 6 and t.origin_compass == "W"
