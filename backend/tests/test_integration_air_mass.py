from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.attribution import attribution_service as svc
from app.attribution.fire_client import FireDetection
from app.attribution.trajectory import destination_point
from app.attribution.weather_client import WindData
from app.db import Base, get_db
from app.main import app
from app.models.db_models import WardBoundary

LAT, LON = 19.05, 72.95


@pytest.fixture()
def db_session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    ring = lambda lo0, lo1: [[[lo0, 19.03], [lo1, 19.03], [lo1, 19.07], [lo0, 19.07], [lo0, 19.03]]]
    session.add_all([
        WardBoundary(ward_id="B", ward_name="West Ward", geometry={"type": "Polygon", "coordinates": ring(72.80, 72.90)}),
        WardBoundary(ward_id="A", ward_name="East Ward", geometry={"type": "Polygon", "coordinates": ring(72.90, 73.00)}),
    ])
    session.commit()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture()
def client(db_session):
    def _db():
        yield db_session
    app.dependency_overrides[get_db] = _db
    svc._WIND_CACHE.clear()
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
    svc._WIND_CACHE.clear()


def _wind_frame(speed=4.0, direction=270.0, hours=6):
    now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0, tzinfo=None)
    rows = [(now - pd.Timedelta(hours=i), speed, direction) for i in range(hours)]
    return pd.DataFrame(rows, columns=["ds", "wind_speed_mps", "wind_dir_deg"])


def _fire(lat, lon):
    return FireDetection(latitude=lat, longitude=lon, distance_km=9.0, acquired_at=datetime(2026, 10, 6, 6, 0), frp_mw=25.0, confidence="h")


def _call(client, fires=(), wind_df=None, explain=None):
    wind = WindData(speed_mps=4.0, direction_deg=270.0, description="few clouds", observed_at=datetime.now(timezone.utc))
    frame = _wind_frame() if wind_df is None else wind_df
    explain = explain or (lambda **kw: "Likely carried in from the west.")
    with patch("app.main.get_wind_data", return_value=wind), \
         patch("app.main.get_nearby_fires", return_value=list(fires)), \
         patch("app.main.search_air_quality_news", return_value=[]), \
         patch("app.main.get_explanation", side_effect=explain) as ge, \
         patch("app.attribution.attribution_service.get_recent_wind", return_value=frame):
        r = client.get("/api/attribution", params={"lat": LAT, "lon": LON, "station_name": "Test", "aqi": 80,
                                                   "category": "Satisfactory", "dominant_pollutant": "PM2.5"})
    return r, ge


def test_endpoint_returns_the_air_mass_block(client):
    r, _ = _call(client)
    assert r.status_code == 200
    am = r.json()["air_mass"]
    assert am["hours"] == 6 and am["origin"]["compass"] == "W" and am["stagnant"] is False
    assert [w["ward_id"] for w in am["over"]["wards"]][-1] == "A"       # the station's own ward is the newest
    assert len(am["points"]) == 7
    assert r.json()["explanation"] == "Likely carried in from the west."


def test_trajectory_is_passed_to_the_llm_explainer(client):
    _, ge = _call(client)
    trace = ge.call_args.kwargs["trajectory"]
    assert trace is not None and trace.origin_compass == "W"


def test_fires_are_marked_upwind_or_not(client):
    upwind = destination_point(LAT, LON, 270.0, 36.0)
    downwind = destination_point(LAT, LON, 90.0, 5.0)
    r, ge = _call(client, fires=[_fire(*downwind), _fire(*upwind)])
    flags = {(f["lat"], f["lon"]): f["upwind"] for f in r.json()["fires"]}
    assert flags[(upwind[0], upwind[1])] is True and flags[(downwind[0], downwind[1])] is False
    trace = ge.call_args.kwargs["trajectory"]
    assert len(trace.fires_on_path) == 1 and trace.fires_off_path == 1


def test_without_wind_history_the_endpoint_still_works_without_a_trajectory(client):
    empty = pd.DataFrame(columns=["ds", "wind_speed_mps", "wind_dir_deg"])
    r, ge = _call(client, wind_df=empty)
    body = r.json()
    assert r.status_code == 200 and body["air_mass"] is None
    assert ge.call_args.kwargs["trajectory"] is None
    assert all(f["upwind"] is None for f in body["fires"])


def test_a_trajectory_failure_never_breaks_the_response(client):
    with patch("app.main.get_air_mass", side_effect=RuntimeError("boom")):
        r, _ = _call(client)
    assert r.status_code == 200 and r.json()["air_mass"] is None


def test_existing_response_keys_are_unchanged(client):
    r, _ = _call(client)
    assert {"wind", "fires", "news", "explanation"} <= set(r.json())
    assert set(r.json()["wind"]) == {"speed_mps", "direction_deg", "compass"}
