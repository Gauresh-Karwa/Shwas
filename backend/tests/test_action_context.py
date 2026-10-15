"""Tests for app.analytics.action_context (database and provider adapter)."""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.analytics import action_context as ac
from app.attribution.trajectory import WindHour
from app.db import Base
from app.models.db_models import CleanedReading, Station

# 04:00 UTC = 09:30 IST -> local hour 9
NOW = datetime(2026, 10, 9, 4, 0)


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    session.add(Station(station_id="S1", name="Chembur", agency="CPCB", latitude=19.05, longitude=72.9))
    session.commit()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def add(db, pollutant, ts, value, station="S1"):
    db.add(CleanedReading(station_id=station, pollutant_id=pollutant, avg_value=value, timestamp=ts))


def fill(db, pollutant, values, end=NOW, step_h=1):
    """Readings ending at `end`, oldest first, one every `step_h` hours."""
    for i, v in enumerate(reversed(values)):
        add(db, pollutant, end - timedelta(hours=i * step_h), v)
    db.commit()


# ── helpers ───────────────────────────────────────────────────────────────

def test_local_hour_is_ist():
    assert ac.local_hour(datetime(2026, 10, 9, 4, 0)) == 9
    assert ac.local_hour(datetime(2026, 10, 9, 20, 0)) == 1      # rolls past midnight


def test_hour_distance_wraps_midnight():
    assert ac._hour_distance(23, 0) == 1
    assert ac._hour_distance(9, 9) == 0
    assert ac._hour_distance(2, 22) == 4


def test_recent_speeds_newest_first_and_skips_gaps():
    winds = [WindHour(2, 1.0, 90), WindHour(0, 0.5, 80), WindHour(1, None, None), WindHour(4, 3.0, 10)]
    assert ac.recent_speeds(winds) == [0.5, 1.0]
    assert ac.recent_speeds([]) == []


def test_sites_near_ward_by_distance_and_by_containment():
    sites = [{"site_id": "near", "name": "N", "lat": 19.06, "lon": 72.92},
             {"site_id": "far", "name": "F", "lat": 19.40, "lon": 72.90},
             {"site_id": "inside", "name": "I", "lat": 19.30, "lon": 73.00}]
    polygon = {"type": "Polygon", "coordinates": [[[72.95, 19.25], [73.05, 19.25], [73.05, 19.35], [72.95, 19.35], [72.95, 19.25]]]}
    found = {s["site_id"]: s for s in ac.sites_near_ward(sites, 19.05, 72.91, polygon)}
    assert set(found) == {"near", "inside"}
    assert found["near"]["distance_km"] < ac.BURNING_SITE_RADIUS_KM
    assert found["inside"]["inside_ward"] is True and found["near"]["inside_ward"] is False
    assert "distance_km" not in sites[0]                       # inputs are not mutated


def test_nearest_station_picks_closest_and_handles_empty():
    near = Station(station_id="A", name="A", agency="x", latitude=19.0, longitude=72.8)
    far = Station(station_id="B", name="B", agency="x", latitude=19.3, longitude=73.0)
    station, d = ac.nearest_station([far, near], 19.01, 72.81)
    assert station.station_id == "A" and d < 3
    assert ac.nearest_station([], 19.0, 72.8) == (None, None)


@pytest.mark.parametrize("setting,expected", [("legacy", "legacy"), ("official_hourly", "official_hourly"),
                                               (" Official_Hourly ", "official_hourly"), ("nonsense", "legacy"), ("", "legacy")])
def test_data_mode_is_normalised(monkeypatch, setting, expected):
    monkeypatch.setattr(ac.settings, "ACTION_DATA_MODE", setting, raising=False)
    assert ac.data_mode() == expected
    # data_notice was removed from the public API; only data_mode() is tested now


# ── station_stats ─────────────────────────────────────────────────────────

def test_fine_fraction_from_24h_means(db):
    fill(db, "PM2.5", [30.0] * 10)
    fill(db, "PM10", [100.0] * 10)
    stats = ac.station_stats(db, "S1", NOW)
    assert stats["fine_fraction"] == pytest.approx(0.30)


def test_fine_fraction_is_none_without_pm10(db):
    fill(db, "PM2.5", [30.0] * 10)
    assert ac.station_stats(db, "S1", NOW)["fine_fraction"] is None


def test_fine_fraction_is_capped_at_one(db):
    fill(db, "PM2.5", [120.0] * 5)
    fill(db, "PM10", [100.0] * 5)
    assert ac.station_stats(db, "S1", NOW)["fine_fraction"] == 1.0


def test_gas_flat_detects_constant_channels(db):
    fill(db, "NO2", [10.0] * 10)
    fill(db, "CO", [0.5] * 10)
    assert ac.station_stats(db, "S1", NOW)["gas_channels_flat"] is True


def test_gas_not_flat_when_one_channel_moves(db):
    fill(db, "NO2", [10.0] * 10)
    fill(db, "CO", [0.5, 0.9, 0.4, 1.2, 0.7, 0.3, 1.0, 0.6, 0.8, 0.5])
    assert ac.station_stats(db, "S1", NOW)["gas_channels_flat"] is False


def test_gas_status_unknown_with_too_few_readings(db):
    fill(db, "NO2", [10.0, 12.0, 11.0])
    assert ac.station_stats(db, "S1", NOW)["gas_channels_flat"] is None


def test_same_hour_baseline_uses_earlier_days_only(db):
    fill(db, "NO2", [60.0] * 3, end=NOW - timedelta(hours=1))          # the last few hours: spike
    for day in range(2, 6):                                            # same local hour on earlier days
        add(db, "NO2", NOW - timedelta(days=day), 40.0)
    db.commit()
    stats = ac.station_stats(db, "S1", NOW)
    assert stats["no2_recent"] == pytest.approx(60.0)
    assert stats["no2_baseline_same_hour"] == pytest.approx(40.0)


def test_same_hour_baseline_needs_enough_history(db):
    fill(db, "NO2", [60.0] * 3, end=NOW - timedelta(hours=1))
    add(db, "NO2", NOW - timedelta(days=2), 40.0)
    db.commit()
    assert ac.station_stats(db, "S1", NOW)["no2_baseline_same_hour"] is None


def test_zero_and_null_readings_are_ignored(db):
    add(db, "PM10", NOW - timedelta(hours=1), 0.0)
    add(db, "PM10", NOW - timedelta(hours=2), None)
    db.commit()
    assert ac.station_stats(db, "S1", NOW)["pm10_recent"] is None


def test_other_stations_are_not_mixed_in(db):
    db.add(Station(station_id="S2", name="Other", agency="CPCB", latitude=19.2, longitude=72.9))
    add(db, "PM10", NOW - timedelta(hours=1), 500.0, station="S2")
    fill(db, "PM10", [100.0] * 3)
    assert ac.station_stats(db, "S1", NOW)["pm10_recent"] == pytest.approx(100.0)


# ── build_ward_contexts ───────────────────────────────────────────────────

class _Ward:
    def __init__(self, ward_id, lat, lon, aqi=150.0, population=100_000):
        self.ward_id, self.ward_name, self.lat, self.lon = ward_id, f"Ward {ward_id}", lat, lon
        self.aqi, self.population, self.category, self.method = aqi, population, "Moderate", "idw"


class _Summary:
    def __init__(self, wards):
        self.wards, self.stations_used = wards, 1


def fake_providers(winds=None, forecast=None, waste=None, fires=None, wind_error=False):
    def winds_fn(lat, lon):
        if wind_error:
            raise RuntimeError("weather api down")
        return winds if winds is not None else [WindHour(0, 0.5, 90), WindHour(1, 0.6, 90), WindHour(2, 0.4, 90)]
    return ac.Providers(
        winds=winds_fn,
        fires=lambda: fires or [],
        forecast=lambda db, lat, lon: forecast,
        waste=lambda db, simulate: waste or [],
    )


@pytest.fixture()
def one_ward(monkeypatch, db):
    monkeypatch.setattr(ac, "compute_city_exposure", lambda session: _Summary([_Ward("W1", 19.05, 72.91)]))
    return db


def test_context_gets_station_distance_wind_forecast_and_sites(one_ward):
    site = {"site_id": "deonar", "name": "Deonar", "lat": 19.06, "lon": 72.92, "level": "likely", "score": 90}
    providers = fake_providers(forecast=[(1, 160.0), (6, 190.0)], waste=[site])
    contexts, meta = ac.build_ward_contexts(one_ward, providers, now=NOW)
    ctx = contexts[0]
    assert ctx.ward_id == "W1" and ctx.nearest_station_id == "S1" and ctx.station_distance_km < 2
    assert ctx.wind_speeds_recent == [0.5, 0.6, 0.4]
    assert ctx.forecast == [(1, 160.0), (6, 190.0)]
    assert ctx.burning_sites[0]["site_id"] == "deonar" and "distance_km" in ctx.burning_sites[0]
    assert ctx.local_hour == 9
    assert meta.stations_used == 1 and meta.warnings == []


def test_legacy_mode_switches_dust_and_traffic_data_off(one_ward, monkeypatch):
    monkeypatch.setattr(ac.settings, "ACTION_DATA_MODE", "legacy", raising=False)
    ctx = ac.build_ward_contexts(one_ward, fake_providers(), now=NOW)[0][0]
    assert ctx.concentrations_valid is False and ctx.hourly_gas_valid is False


def test_official_mode_switches_them_on(one_ward, monkeypatch):
    monkeypatch.setattr(ac.settings, "ACTION_DATA_MODE", "official_hourly", raising=False)
    ctx = ac.build_ward_contexts(one_ward, fake_providers(), now=NOW)[0][0]
    assert ctx.concentrations_valid is True and ctx.hourly_gas_valid is True


def test_failing_providers_blank_inputs_and_add_warnings(one_ward):
    def boom(*a, **k):
        raise RuntimeError("down")
    providers = ac.Providers(winds=boom, fires=boom, forecast=boom, waste=boom)
    contexts, meta = ac.build_ward_contexts(one_ward, providers, now=NOW)
    ctx = contexts[0]
    assert ctx.wind_speeds_recent == [] and ctx.forecast is None
    assert ctx.burning_sites == [] and ctx.air_mass is None
    assert any("Wind" in w for w in meta.warnings) and any("Forecast" in w for w in meta.warnings)


def test_no_station_in_database_gives_unknown_distance(monkeypatch, db):
    db.query(Station).delete()
    db.commit()
    monkeypatch.setattr(ac, "compute_city_exposure", lambda session: _Summary([_Ward("W1", 19.05, 72.91)]))
    ctx = ac.build_ward_contexts(db, fake_providers(), now=NOW)[0][0]
    assert ctx.nearest_station_id is None and ctx.station_distance_km is None


def test_no_live_data_raises_lookup_error(monkeypatch, db):
    def none(session):
        raise LookupError("No live station AQI data available yet.")
    monkeypatch.setattr(ac, "compute_city_exposure", none)
    with pytest.raises(LookupError):
        ac.build_ward_contexts(db, fake_providers(), now=NOW)


def test_station_stats_are_computed_once_per_station(monkeypatch, db):
    monkeypatch.setattr(ac, "compute_city_exposure", lambda s: _Summary([_Ward("W1", 19.05, 72.91), _Ward("W2", 19.06, 72.92)]))
    calls = []
    real = ac.station_stats
    monkeypatch.setattr(ac, "station_stats", lambda *a, **k: calls.append(1) or real(*a, **k))
    ac.build_ward_contexts(db, fake_providers(), now=NOW)
    assert len(calls) == 1


def test_air_mass_counts_fires_on_the_path(one_ward):
    from app.attribution.fire_client import FireDetection
    winds = [WindHour(h, 3.0, 90.0) for h in range(6)]             # wind blowing from the east
    fire = FireDetection(latitude=19.05, longitude=72.97, distance_km=6.0,
                         acquired_at=datetime(2026, 10, 9), frp_mw=7.0, confidence="h")
    ctx = ac.build_ward_contexts(one_ward, fake_providers(winds=winds, fires=[fire]), now=NOW)[0][0]
    assert ctx.air_mass is not None and ctx.air_mass["fires_on_path"] == 1
    assert ctx.air_mass["total_frp_mw"] == 7.0