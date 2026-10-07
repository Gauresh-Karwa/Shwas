from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.attribution import llm_explainer as llm
from app.attribution.trajectory import WindHour, build_trajectory, destination_point
from app.attribution.weather_client import WindData

STATION = (19.05, 72.95)
WIND = WindData(speed_mps=4.0, direction_deg=270.0, description="few clouds", observed_at=datetime.now(timezone.utc))


def _trace(fires=()):
    winds = [WindHour(i, 5.0, 270.0) for i in range(3)]
    return build_trajectory(*STATION, winds, fires=list(fires))


def _fire(lat, lon):
    return SimpleNamespace(latitude=lat, longitude=lon, frp_mw=22.0, distance_km=9.0)


def test_prompt_without_a_trace_is_unchanged():
    f = _fire(19.1, 72.9)
    p = llm._build_user_prompt("Kurla", 101, "Moderate", "PM2.5", WIND, [f], [])
    assert "Nearby fire detections: 1, nearest 9.0 km away" in p
    assert "Air-mass trace" not in p


def test_prompt_with_a_trace_reports_where_the_air_came_from():
    p = llm._build_user_prompt("Kurla", 101, "Moderate", "PM2.5", WIND, [], [], _trace())
    assert "Air-mass trace (last 3 h, from hourly wind): the air arrived from the W, travelling about 54 km" in p


def test_fire_on_the_path_is_reported_as_upwind_and_replaces_the_old_fire_line():
    spot = destination_point(*STATION, 270.0, 36.0)
    f = _fire(*spot)
    p = llm._build_user_prompt("Kurla", 101, "Moderate", "PM2.5", WIND, [f], [], _trace([f]))
    assert "Fire detections along the air's path: 1" in p and "right on the path, about 2 h upwind" in p
    assert "Nearby fire detections" not in p


def test_fire_off_the_path_is_explicitly_marked_so_it_is_not_blamed():
    east = destination_point(*STATION, 90.0, 5.0)
    f = _fire(*east)
    p = llm._build_user_prompt("Kurla", 101, "Moderate", "PM2.5", WIND, [f], [], _trace([f]))
    assert "NOT on the air's path: 1" in p and "along the air's path" not in p


def test_light_winds_are_described_as_slow_dispersion():
    calm = build_trajectory(*STATION, [WindHour(i, 0.6, 200.0) for i in range(4)])
    p = llm._build_user_prompt("Sion", 160, "Moderate", "PM2.5", WIND, [], [], calm)
    assert "winds were light (about 0.6 m/s)" in p and "not being dispersed quickly" in p


def test_system_prompt_forbids_blaming_fires_that_are_not_on_the_path():
    assert "must not be blamed" in llm.SYSTEM_PROMPT
    assert "ONE sentence only" in llm.SYSTEM_PROMPT          # original rules are still there
    assert "Never invent a cause" in llm.SYSTEM_PROMPT


def test_fallback_without_a_trace_is_unchanged_and_with_one_adds_the_summary():
    assert llm._fallback_explanation(101, "Moderate", "PM2.5") == "Air quality is Moderate (AQI 101), primarily driven by PM2.5."
    t = _trace()
    text = llm._fallback_explanation(101, "Moderate", "PM2.5", t)
    assert text.startswith("Air quality is Moderate (AQI 101)") and t.summary() in text


def test_get_explanation_sends_the_trace_to_the_model_and_keeps_one_sentence():
    client = MagicMock()
    client.models.generate_content.return_value = SimpleNamespace(text="Likely carried in from the west. Extra.")
    with patch.object(llm.genai, "Client", return_value=client):
        out = llm.get_explanation("Kurla", 101, "Moderate", "PM2.5", WIND, [], [], trajectory=_trace())
    assert out == "Likely carried in from the west."
    kwargs = client.models.generate_content.call_args.kwargs
    assert "Air-mass trace" in kwargs["contents"]
    assert "must not be blamed" in kwargs["config"].system_instruction


def test_get_explanation_falls_back_to_the_rule_based_text_when_the_model_fails():
    t = _trace()
    with patch.object(llm.genai, "Client", side_effect=RuntimeError("no key")):
        out = llm.get_explanation("Kurla", 101, "Moderate", "PM2.5", WIND, [], [], trajectory=t)
    assert out == llm._fallback_explanation(101, "Moderate", "PM2.5", t)


def test_old_call_signature_still_works():
    with patch.object(llm.genai, "Client", side_effect=RuntimeError("no key")):
        out = llm.get_explanation("Kurla", 101, "Moderate", "PM2.5", WIND, [], [])
    assert out == "Air quality is Moderate (AQI 101), primarily driven by PM2.5."
