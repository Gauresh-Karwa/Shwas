"""End to end: seeded database -> ward exposure -> context builder -> engine -> /api/actions."""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.analytics.action_context as ac
import app.analytics.ward_exposure as we
import app.routers.actions as actions_router
from app.analytics.action_engine import RuleError, reset_ruleset_cache
from app.attribution.trajectory import WindHour
from app.db import Base, get_db
from app.main import app
from app.models.db_models import (
    CleanedReading, Station, StationAQI, WardBoundary, WardPopulation,
)

NOW = datetime(2026, 10, 9, 4, 0)       # 09:30 IST: inside the morning rush window

WARD_A = {"type": "Polygon", "coordinates": [[[72.90, 19.03], [72.94, 19.03], [72.94, 19.07], [72.90, 19.07], [72.90, 19.03]]]}
WARD_B = {"type": "Polygon", "coordinates": [[[72.80, 19.15], [72.84, 19.15], [72.84, 19.19], [72.80, 19.19], [72.80, 19.15]]]}
DEONAR = {"site_id": "deonar", "name": "Deonar Dumping Ground", "lat": 19.0535, "lon": 72.9250,
          "level": "likely", "score": 90, "reasons": ["2 satellite fire detection(s) near the dump site"]}


@pytest.fixture()
def db_session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture()
def client(db_session, monkeypatch):
    reset_ruleset_cache()
    actions_router.clear_cache()
    monkeypatch.setattr(we, "get_gnn_model", lambda: None)                  # IDW only: no torch needed
    monkeypatch.setattr(ac.settings, "ACTION_DATA_MODE", "legacy", raising=False)
    app.dependency_overrides[get_db] = lambda: db_session
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()
        actions_router.clear_cache()
        reset_ruleset_cache()


def providers(waste=None, forecast=None, winds=None):
    calm = [WindHour(0, 0.5, 90.0), WindHour(1, 0.6, 90.0), WindHour(2, 0.4, 90.0)]
    return ac.Providers(
        winds=lambda lat, lon: calm if winds is None else winds,
        fires=lambda: [],
        forecast=lambda db, lat, lon: forecast,
        waste=lambda db: waste or [],
    )


@pytest.fixture()
def seeded(db_session):
    s = db_session
    s.add(Station(station_id="S_A", name="Chembur", agency="CPCB", latitude=19.05, longitude=72.91))
    s.add(Station(station_id="S_B", name="Borivali", agency="CPCB", latitude=19.17, longitude=72.82))
    s.add(StationAQI(station_id="S_A", timestamp=NOW, aqi_value=190.0, status="ok", category="Moderate", dominant_pollutant="PM2.5"))
    s.add(StationAQI(station_id="S_B", timestamp=NOW, aqi_value=80.0, status="ok", category="Satisfactory", dominant_pollutant="PM2.5"))
    s.add(WardBoundary(ward_id="M/E", ward_name="Ward M East", geometry=WARD_A))
    s.add(WardPopulation(ward_id="M/E", population=800_000, census_year=2011))
    s.add(WardBoundary(ward_id="R/C", ward_name="Ward R Central", geometry=WARD_B))
    s.add(WardPopulation(ward_id="R/C", population=500_000, census_year=2011))
    s.commit()


def use(monkeypatch, prov):
    monkeypatch.setattr(ac, "default_providers", lambda: prov)


def by_id(payload):
    return {w["ward_id"]: w for w in payload["wards"]}


def test_returns_every_ward_with_legacy_notice(client, seeded, monkeypatch):
    use(monkeypatch, providers())
    body = client.get("/api/actions").json()
    assert body["total_wards_evaluated"] == 2 and len(body["wards"]) == 2
    assert body["data_mode"] == "legacy"
    assert body["rules"]["active"] == 6


def test_stagnation_and_crossing_cards_use_forecast_and_wind(client, seeded, monkeypatch):
    use(monkeypatch, providers(forecast=[(3, 200.0), (6, 235.0), (9, 250.0)]))
    ward = by_id(client.get("/api/actions").json())["M/E"]
    rules = {c["rule_id"] for c in ward["cards"]}
    assert {"RULE_FORECAST_CROSSING", "RULE_STAGNATION"} <= rules
    crossing = next(c for c in ward["cards"] if c["rule_id"] == "RULE_FORECAST_CROSSING")
    assert crossing["severity"] == "high"
    assert crossing["forecast_without_action"]["trend"] == "rising"
    assert crossing["source_reference"] is not None and "SAFAR" in crossing["source_reference"]


def test_dust_and_traffic_are_off_in_legacy_mode(client, seeded, monkeypatch):
    use(monkeypatch, providers(forecast=[(6, 235.0)]))
    ward = by_id(client.get("/api/actions?include_signals=true").json())["M/E"]
    signals = {s["rule_id"]: s for s in ward["signals"]}
    assert not signals["RULE_DUST"]["fired"] and "sub-indices" in signals["RULE_DUST"]["evidence"][0]
    assert not signals["RULE_TRAFFIC_PEAK"]["fired"] and "hourly" in signals["RULE_TRAFFIC_PEAK"]["evidence"][0]


def test_burning_detection_ranks_the_ward_first(client, seeded, monkeypatch):
    site = {**DEONAR}
    use(monkeypatch, providers(waste=[site]))
    body = client.get("/api/actions").json()
    first = body["wards"][0]
    assert first["ward_id"] == "M/E"
    burn = next(c for c in first["cards"] if c["rule_id"] == "RULE_WASTE_BURNING")
    assert burn["simulated"] is False and burn["severity"] == "high"
    assert first["priority_score"] == pytest.approx(3.0 * 800_000 * first["current_aqi"] / 100.0, rel=1e-3)
    live_rc = [c for c in by_id(body)["R/C"]["cards"] if not c.get("baseline")]
    assert live_rc == []


def test_ward_without_station_nearby_is_tagged_estimated(client, seeded, db_session, monkeypatch):
    use(monkeypatch, providers(forecast=[(6, 235.0)]))
    db_session.query(Station).filter(Station.station_id == "S_A").update({"latitude": 19.55, "longitude": 73.4})
    db_session.commit()
    ward = by_id(client.get("/api/actions").json())["M/E"]
    assert ward["is_estimated"] is True and ward["distance_to_station_km"] > 6


def test_single_ward_filter_and_404(client, seeded, monkeypatch):
    use(monkeypatch, providers())
    one = client.get("/api/actions", params={"ward_id": "R/C"}).json()
    assert [w["ward_id"] for w in one["wards"]] == ["R/C"] and one["total_wards_evaluated"] == 1
    assert client.get("/api/actions", params={"ward_id": "Z/Z"}).status_code == 404


def test_no_live_station_data_returns_503(client, monkeypatch):
    use(monkeypatch, providers())
    assert client.get("/api/actions").status_code == 503


def test_unusable_rules_return_503(client, seeded, monkeypatch):
    use(monkeypatch, providers())
    def broken():
        raise RuleError("bad file")
    monkeypatch.setattr(actions_router, "get_ruleset", broken)
    response = client.get("/api/actions")
    assert response.status_code == 503 and "bad file" in response.json()["detail"]


def test_rules_endpoint_is_not_exposed(client):
    """The internal rules endpoint must not be publicly accessible."""
    response = client.get("/api/actions/rules")
    assert response.status_code == 404


def test_response_is_cached_between_calls(client, seeded, monkeypatch):
    calls = []
    use(monkeypatch, providers())
    real = actions_router.build_ward_contexts
    monkeypatch.setattr(actions_router, "build_ward_contexts", lambda *a, **k: calls.append(1) or real(*a, **k))
    client.get("/api/actions")
    client.get("/api/actions")
    client.get("/api/actions?include_signals=true")
    assert len(calls) == 2                      # second plain call was served from the cache


def test_official_mode_enables_traffic_and_dust(client, seeded, db_session, monkeypatch):
    monkeypatch.setattr(ac.settings, "ACTION_DATA_MODE", "official_hourly", raising=False)
    s = db_session
    for i in range(10):                         # moving gas channel + recent NO2 spike at the nearest station
        s.add(CleanedReading(station_id="S_A", pollutant_id="CO", avg_value=0.4 + 0.05 * (i % 4),
                             timestamp=NOW - timedelta(hours=i)))
    for i in range(3):
        s.add(CleanedReading(station_id="S_A", pollutant_id="NO2", avg_value=60.0, timestamp=NOW - timedelta(hours=i + 1)))
    for i in range(7):
        s.add(CleanedReading(station_id="S_A", pollutant_id="NO2", avg_value=40.0, timestamp=NOW - timedelta(days=2 + i)))
    for i in range(6):                          # coarse-dominated PM so dust reaches its weather check
        s.add(CleanedReading(station_id="S_A", pollutant_id="PM2.5", avg_value=30.0, timestamp=NOW - timedelta(hours=i)))
        s.add(CleanedReading(station_id="S_A", pollutant_id="PM10", avg_value=120.0, timestamp=NOW - timedelta(hours=i)))
    s.commit()
    real = ac.build_ward_contexts
    monkeypatch.setattr(actions_router, "build_ward_contexts", lambda db, **k: real(db, now=NOW, **k))
    use(monkeypatch, providers())
    body = client.get("/api/actions?include_signals=true").json()
    ward = by_id(body)["M/E"]
    assert body["data_mode"] == "official_hourly"
    dust = next(s for s in ward["signals"] if s["rule_id"] == "RULE_DUST")
    assert not dust["fired"] and "Rain and humidity" in dust["evidence"][0]     # weather feed not wired yet


def test_normalize_priority_score():
    from app.routers.actions import normalize_priority_score
    # 0 raw -> 0.0
    assert normalize_priority_score(0.0) == 0.0
    assert normalize_priority_score(-5.0) == 0.0
    # At max severity 3, max aqi 500: capacity is 15 * pop -> 100.0
    pop = 800_000
    max_raw = 3.0 * pop * 5.0
    assert normalize_priority_score(max_raw, pop) == 100.0
    # Over capacity clamped to 100.0
    assert normalize_priority_score(max_raw * 1.5, pop) == 100.0
    # Half capacity -> 50.0
    assert normalize_priority_score(max_raw * 0.5, pop) == 50.0


def test_simulate_ward_normalizes_priority_score(client, seeded, monkeypatch):
    use(monkeypatch, providers())
    resp = client.post("/api/actions/simulate", json={"ward_id": "M/E", "scenario": "landfill_fire"})
    assert resp.status_code == 200
    data = resp.json()
    sim = data["simulation"]
    # Scores must be bounded within 0.0 - 100.0
    assert 0.0 <= sim["baseline_priority_score"] <= 100.0
    assert 0.0 <= sim["simulated_priority_score"] <= 100.0
    # Crisis simulation increases the priority score
    assert sim["simulated_priority_score"] >= sim["baseline_priority_score"]
    # All simulated action cards also have normalized priority scores
    for card in data["cards"]:
        assert 0.0 <= card["priority_score"] <= 100.0