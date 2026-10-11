"""Tests for app.analytics.action_engine (pure detectors, rules and ranking)."""
from __future__ import annotations

import math
import os
import time

import pytest
import yaml

from app.analytics import action_engine as ae
from app.analytics.action_engine import (
    DEFAULT_PARAMS, RuleError, WardContext, category_for_aqi, confidence_label,
    detect_dust, detect_forecast_crossing, detect_inflow, detect_stagnation,
    detect_traffic, detect_waste_burning, evaluate_all, evaluate_ward,
    forecast_without_action, get_ruleset, load_rules, parse_rules, reset_ruleset_cache,
)


def ctx(**overrides) -> WardContext:
    base = dict(ward_id="M/E", ward_name="Ward M East", population=100_000,
                lat=19.05, lon=72.92, aqi=150.0, local_hour=9,
                nearest_station_id="S1", nearest_station_name="Chembur", station_distance_km=2.0)
    base.update(overrides)
    return WardContext(**base)


def params(signal: str, **over) -> dict:
    return {**DEFAULT_PARAMS[signal], **over}


# ── category and confidence helpers ───────────────────────────────────────

@pytest.mark.parametrize("aqi,name", [(0, "Good"), (50, "Good"), (101, "Moderate"), (200, "Moderate"),
                                       (201, "Poor"), (350, "Very Poor"), (450, "Severe"), (999, "Severe")])
def test_category_for_aqi(aqi, name):
    assert category_for_aqi(aqi) == name


@pytest.mark.parametrize("score,label", [(0.9, "high"), (0.75, "high"), (0.6, "likely"),
                                          (0.5, "likely"), (0.35, "possible"), (0.1, "indicative")])
def test_confidence_label(score, label):
    assert confidence_label(score) == label


# ── waste burning ─────────────────────────────────────────────────────────

SITE = {"site_id": "deonar", "name": "Deonar Dumping Ground", "level": "likely", "score": 90,
        "reasons": ["2 satellite fire detection(s) near the dump site"], "distance_km": 2.4}


def test_burning_fires_on_likely_site_and_sets_high_hint():
    s = detect_waste_burning(ctx(burning_sites=[SITE]), params("waste_burning"))
    assert s.fired and s.severity_hint == "high"
    assert s.confidence == pytest.approx(0.85 * math.exp(-2.4 / 6.0))      # 2.4 km from the ward centre
    assert "Deonar Dumping Ground is 2.4 km from the ward centre" in s.evidence
    assert not s.station_dependent


def test_burning_possible_has_no_severity_hint():
    s = detect_waste_burning(ctx(burning_sites=[{**SITE, "level": "possible", "score": 55}]), params("waste_burning"))
    assert s.fired and s.severity_hint is None


def test_burning_watch_level_does_not_fire():
    s = detect_waste_burning(ctx(burning_sites=[{**SITE, "level": "watch", "score": 30}]), params("waste_burning"))
    assert not s.fired


def test_burning_no_nearby_site_does_not_fire():
    s = detect_waste_burning(ctx(burning_sites=[]), params("waste_burning"))
    assert not s.fired and "No monitored dump site" in s.evidence[0]


def test_burning_marks_simulated_data():
    s = detect_waste_burning(ctx(burning_sites=[{**SITE, "simulated": True}]), params("waste_burning"))
    assert s.details["simulated"] is True and s.evidence[0].startswith("SIMULATED")


def burn(distance, **over):
    return detect_waste_burning(ctx(burning_sites=[{**SITE, "distance_km": distance, **over}]), params("waste_burning"))


def test_burning_confidence_falls_with_distance():
    near, mid, far = burn(0.5), burn(3.9), burn(5.0)
    assert near.confidence > mid.confidence > far.confidence
    assert mid.confidence == pytest.approx(0.85 * math.exp(-3.9 / 6.0))


def test_burning_severity_is_high_only_close_to_the_site():
    assert burn(2.5).severity_hint == "high"
    assert burn(2.6).severity_hint is None and burn(3.9).severity_hint is None


def test_burning_site_inside_ward_ignores_centroid_distance():
    inside = burn(4.8, inside_ward=True)
    assert inside.confidence == pytest.approx(0.85) and inside.severity_hint == "high"
    assert "lies inside this ward" in inside.evidence[0]


def test_burning_unknown_distance_keeps_full_confidence():
    s = detect_waste_burning(ctx(burning_sites=[{k: v for k, v in SITE.items() if k != "distance_km"}]),
                             params("waste_burning"))
    assert s.confidence == pytest.approx(0.85) and s.severity_hint == "high"


def test_burning_picks_the_site_with_the_strongest_adjusted_confidence():
    close_weak = {**SITE, "site_id": "a", "name": "Close", "level": "possible", "score": 50, "distance_km": 0.5}
    far_strong = {**SITE, "site_id": "b", "name": "Far", "level": "likely", "score": 95, "distance_km": 5.0}
    s = detect_waste_burning(ctx(burning_sites=[far_strong, close_weak]), params("waste_burning"))
    assert s.details["site_id"] == "a"            # 0.60 * e^(-0.5/6) beats 0.85 * e^(-5/6)


def test_burning_decay_is_tunable_from_the_rules_file():
    c = ctx(burning_sites=[{**SITE, "distance_km": 3.9}])
    slow = detect_waste_burning(c, params("waste_burning", decay_km=60.0))
    fast = detect_waste_burning(c, params("waste_burning", decay_km=2.0))
    assert slow.confidence > fast.confidence


# ── inflow ────────────────────────────────────────────────────────────────

def test_inflow_fires_with_fires_on_path():
    s = detect_inflow(ctx(air_mass={"hours": 6, "fires_on_path": 2, "total_frp_mw": 9.5}), {})
    assert s.fired and "2 satellite fire" in s.evidence[0]


@pytest.mark.parametrize("mass", [None, {}, {"fires_on_path": 0}])
def test_inflow_quiet_without_fires(mass):
    assert not detect_inflow(ctx(air_mass=mass), {}).fired


# ── forecast crossing ─────────────────────────────────────────────────────

def test_crossing_fires_when_forecast_enters_worse_category():
    c = ctx(aqi=190, forecast=[(1, 192), (2, 200), (4, 225), (6, 230)])
    s = detect_forecast_crossing(c, params("forecast_crossing"))
    assert s.fired and s.details["hours"] == 4 and s.details["target_category"] == "Poor"
    assert s.severity_hint == "high"          # Poor reaches the high_from_category line
    assert s.confidence == pytest.approx(0.65)


def test_crossing_ignores_a_touch_of_the_next_band():
    # 203 is Poor but only 2 points over the band start; the 5 point margin blocks it
    s = detect_forecast_crossing(ctx(aqi=190, forecast=[(3, 203)]), params("forecast_crossing"))
    assert not s.fired


def test_crossing_ignores_points_beyond_horizon():
    s = detect_forecast_crossing(ctx(aqi=190, forecast=[(8, 260)]), params("forecast_crossing"))
    assert not s.fired


def test_crossing_moderate_target_is_not_high():
    s = detect_forecast_crossing(ctx(aqi=90, forecast=[(2, 120)]), params("forecast_crossing"))
    assert s.fired and s.severity_hint is None


def test_crossing_improving_forecast_does_not_fire():
    assert not detect_forecast_crossing(ctx(aqi=190, forecast=[(2, 150)]), params("forecast_crossing")).fired


def test_crossing_without_forecast():
    s = detect_forecast_crossing(ctx(forecast=None), params("forecast_crossing"))
    assert not s.fired and "No forecast" in s.evidence[0]


# ── stagnation ────────────────────────────────────────────────────────────

def test_stagnation_needs_calm_wind_and_rising_forecast():
    c = ctx(aqi=150, wind_speeds_recent=[0.8, 1.0, 0.6], forecast=[(3, 160), (9, 190)])
    s = detect_stagnation(c, params("stagnation"))
    assert s.fired and s.details["rise"] == pytest.approx(40) and s.details["peak_hours"] == 9


def test_stagnation_quiet_when_one_hour_is_windy():
    c = ctx(wind_speeds_recent=[0.8, 2.5, 0.6], forecast=[(9, 200)])
    assert not detect_stagnation(c, params("stagnation")).fired


def test_stagnation_quiet_when_forecast_flat():
    c = ctx(aqi=150, wind_speeds_recent=[0.5, 0.5, 0.5], forecast=[(6, 154)])
    assert not detect_stagnation(c, params("stagnation")).fired


def test_stagnation_quiet_with_too_little_wind_data():
    c = ctx(wind_speeds_recent=[0.5], forecast=[(6, 200)])
    assert not detect_stagnation(c, params("stagnation")).fired


def test_stagnation_quiet_without_forecast():
    assert not detect_stagnation(ctx(wind_speeds_recent=[0.5] * 3, forecast=None), params("stagnation")).fired


# ── traffic ───────────────────────────────────────────────────────────────

def traffic_ctx(**over):
    base = dict(hourly_gas_valid=True, gas_channels_flat=False, local_hour=9,
                no2_recent=60.0, no2_baseline_same_hour=40.0)
    base.update(over)
    return ctx(**base)


def test_traffic_fires_on_no2_spike_in_rush_hour():
    s = detect_traffic(traffic_ctx(), params("traffic"))
    assert s.fired and s.details["pollutant"] == "NO2" and s.details["ratio"] == pytest.approx(1.5)


def test_traffic_picks_the_larger_of_no2_and_co():
    s = detect_traffic(traffic_ctx(co_recent=3.0, co_baseline_same_hour=1.0), params("traffic"))
    assert s.details["pollutant"] == "CO"


def test_traffic_off_when_gas_channels_flat():
    s = detect_traffic(traffic_ctx(gas_channels_flat=True), params("traffic"))
    assert not s.fired and "flat" in s.evidence[0]


def test_traffic_off_when_gas_status_unknown():
    assert not detect_traffic(traffic_ctx(gas_channels_flat=None), params("traffic")).fired


def test_traffic_off_outside_rush_hours():
    assert not detect_traffic(traffic_ctx(local_hour=14), params("traffic")).fired


@pytest.mark.parametrize("hour,expected", [(7, False), (8, True), (10, True), (11, False),
                                            (16, False), (17, True), (20, True), (21, False)])
def test_traffic_rush_window_edges(hour, expected):
    assert detect_traffic(traffic_ctx(local_hour=hour), params("traffic")).fired is expected


def test_traffic_off_in_legacy_data_mode():
    s = detect_traffic(traffic_ctx(hourly_gas_valid=False), params("traffic"))
    assert not s.fired and "hourly" in s.evidence[0]


def test_traffic_below_spike_ratio_does_not_fire():
    assert not detect_traffic(traffic_ctx(no2_recent=44.0), params("traffic")).fired


# ── dust ──────────────────────────────────────────────────────────────────

def dust_ctx(**over):
    base = dict(concentrations_valid=True, fine_fraction=0.30, precip_24h_mm=0.0, humidity_pct=50.0,
                pm10_recent=180.0, pm10_baseline=120.0)
    base.update(over)
    return ctx(**base)


def test_dust_fires_when_coarse_dry_and_elevated():
    s = detect_dust(dust_ctx(), params("dust"))
    assert s.fired and s.station_dependent and len(s.evidence) == 3


def test_dust_gated_off_in_legacy_mode():
    s = detect_dust(dust_ctx(concentrations_valid=False), params("dust"))
    assert not s.fired and "sub-indices" in s.evidence[0]


@pytest.mark.parametrize("over", [dict(fine_fraction=0.55), dict(precip_24h_mm=2.0), dict(humidity_pct=85.0),
                                   dict(pm10_recent=100.0), dict(fine_fraction=None),
                                   dict(precip_24h_mm=None), dict(humidity_pct=None)])
def test_dust_quiet_when_any_condition_fails(over):
    assert not detect_dust(dust_ctx(**over), params("dust")).fired


# ── forecast_without_action ───────────────────────────────────────────────

def test_forecast_summary_rising_steady_falling():
    assert forecast_without_action(ctx(aqi=150, forecast=[(6, 190)]))["trend"] == "rising"
    assert forecast_without_action(ctx(aqi=150, forecast=[(6, 152)]))["trend"] == "steady"
    assert forecast_without_action(ctx(aqi=150, forecast=[(6, 100)]))["trend"] == "falling"
    assert forecast_without_action(ctx(forecast=None)) is None
    far = forecast_without_action(ctx(aqi=150, forecast=[(3, 160), (12, 400)]))
    assert far["hours_ahead"] == 3          # only the next 6 h are shown


# ── rules: validation ─────────────────────────────────────────────────────

def base_rule(**over):
    rule = dict(id="R1", signal="inflow", severity="low", min_confidence="possible",
                action_title="t", time_window="w", rationale="r")
    rule.update(over)
    return rule


def test_shipped_rules_file_is_valid():
    rules = load_rules()
    assert {r.signal for r in rules.rules} == set(ae.DETECTORS)
    assert len({r.id for r in rules.rules}) == len(rules.rules)


def test_shipped_rules_carry_no_unverified_citations():
    # a citation may only be shown once a person has verified it
    for rule in load_rules().rules:
        if not rule.source_verified:
            assert rule.source_reference is None


@pytest.mark.parametrize("bad,msg", [
    (base_rule(signal="nope"), "unknown signal"),
    (base_rule(severity="extreme"), "severity"),
    (base_rule(min_confidence="sure"), "min_confidence"),
    (base_rule(typo_key=1), "unknown key"),
    (base_rule(params={"bogus": 1}), "unknown param"),
    (base_rule(enabled="yes"), "enabled"),
    (base_rule(action_title="  "), "action_title"),
    (base_rule(params=[1]), "params"),
])
def test_invalid_rules_are_rejected(bad, msg):
    with pytest.raises(RuleError, match=msg):
        parse_rules({"version": "1", "rules": [bad]})


def test_missing_required_key_rejected():
    rule = base_rule()
    del rule["rationale"]
    with pytest.raises(RuleError, match="missing"):
        parse_rules({"rules": [rule]})


def test_duplicate_ids_and_empty_lists_rejected():
    with pytest.raises(RuleError, match="duplicate"):
        parse_rules({"rules": [base_rule(), base_rule()]})
    with pytest.raises(RuleError):
        parse_rules({"rules": []})
    with pytest.raises(RuleError):
        parse_rules(["not", "a", "mapping"])


# ── rules: hot reload ─────────────────────────────────────────────────────

@pytest.fixture()
def rules_file(tmp_path):
    reset_ruleset_cache()
    path = tmp_path / "rules.yaml"
    path.write_text(yaml.safe_dump({"version": "1", "rules": [base_rule()]}))
    yield path
    reset_ruleset_cache()


def _rewrite(path, data):
    path.write_text(yaml.safe_dump(data))
    stamp = time.time() + 5 * _rewrite.calls
    _rewrite.calls += 1
    os.utime(path, (stamp, stamp))      # make the change visible even on coarse clocks


_rewrite.calls = 1


def test_rule_edits_are_picked_up_without_restart(rules_file):
    assert get_ruleset(rules_file).version == "1"
    _rewrite(rules_file, {"version": "2", "rules": [base_rule(severity="high")]})
    updated = get_ruleset(rules_file)
    assert updated.version == "2" and updated.rules[0].severity == "high"


def test_broken_edit_keeps_last_good_rules(rules_file):
    good = get_ruleset(rules_file)
    _rewrite(rules_file, {"version": "3", "rules": [base_rule(severity="extreme")]})
    assert get_ruleset(rules_file) is good
    assert "severity" in ae.ruleset_status()["last_error"]
    _rewrite(rules_file, {"version": "4", "rules": [base_rule()]})
    assert get_ruleset(rules_file).version == "4"
    assert ae.ruleset_status()["last_error"] is None


def test_first_load_with_broken_file_raises(rules_file):
    _rewrite(rules_file, {"rules": [base_rule(severity="extreme")]})
    with pytest.raises(RuleError):
        get_ruleset(rules_file)


# ── evaluation ────────────────────────────────────────────────────────────

def ruleset(*rules):
    return parse_rules({"version": "t", "rules": list(rules)})


BURN_RULE = base_rule(id="BURN", signal="waste_burning", severity="medium", action_title="Inspect dump")
CROSS_RULE = base_rule(id="CROSS", signal="forecast_crossing", severity="medium", action_title="Advise ward")
INFLOW_RULE = base_rule(id="INFLOW", signal="inflow", severity="low", advisory=True, action_title="Notify")


def test_card_carries_evidence_window_and_forecast():
    c = ctx(aqi=190, burning_sites=[SITE], forecast=[(6, 230)])
    result = evaluate_ward(c, ruleset(BURN_RULE))
    card = result.cards[0]
    assert card.rule_id == "BURN" and card.severity == "high"      # "likely" raises medium to high
    assert card.evidence[0].startswith("Deonar")
    assert card.forecast_without_action["predicted_category"] == "Poor"
    assert "Inspect dump" in card.summary and card.time_window in card.summary
    assert card.card_id == "act-m-e-burn"


def test_detector_can_raise_but_never_lower_severity():
    rule = base_rule(id="B", signal="waste_burning", severity="high")
    weak = {**SITE, "level": "possible", "score": 55}
    assert evaluate_ward(ctx(burning_sites=[weak]), ruleset(rule)).cards[0].severity == "high"


def test_priority_formula_is_severity_times_population_times_aqi():
    c = ctx(aqi=200.0, population=100_000, burning_sites=[SITE])
    result = evaluate_ward(c, ruleset(BURN_RULE))
    assert result.priority_score == pytest.approx(3.0 * 100_000 * 2.0)


def test_advisory_cards_do_not_raise_priority():
    c = ctx(air_mass={"hours": 6, "fires_on_path": 3})
    result = evaluate_ward(c, ruleset(INFLOW_RULE))
    live_cards = [c for c in result.cards if not c.baseline]
    assert len(live_cards) == 1 and live_cards[0].advisory and result.priority_score == 0.0


def test_advisory_cards_sort_after_action_cards():
    c = ctx(aqi=190, burning_sites=[SITE], air_mass={"fires_on_path": 3})
    result = evaluate_ward(c, ruleset(INFLOW_RULE, BURN_RULE))
    non_baseline = [card.rule_id for card in result.cards if not card.baseline]
    assert non_baseline == ["BURN", "INFLOW"]


def test_distance_to_station_lowers_confidence_of_station_signals_only():
    near = ctx(aqi=190, station_distance_km=1.0, forecast=[(2, 230)], burning_sites=[SITE])
    far = ctx(aqi=190, station_distance_km=10.0, forecast=[(2, 230)], burning_sites=[SITE])
    rs = ruleset(CROSS_RULE, BURN_RULE)
    near_cards = {c.rule_id: c for c in evaluate_ward(near, rs).cards}
    far_cards = {c.rule_id: c for c in evaluate_ward(far, rs).cards}
    assert far_cards["CROSS"].confidence_score < near_cards["CROSS"].confidence_score
    assert far_cards["BURN"].confidence_score == near_cards["BURN"].confidence_score   # satellite-based
    assert far_cards["CROSS"].estimated is True and far_cards["BURN"].estimated is False
    assert evaluate_ward(far, rs).is_estimated and not evaluate_ward(near, rs).is_estimated


def test_min_confidence_filters_weak_cards():
    far = ctx(aqi=190, station_distance_km=40.0, forecast=[(6, 230)])     # 0.55 * exp(-40/12) is tiny
    strict = base_rule(id="C", signal="forecast_crossing", min_confidence="likely")
    assert [c for c in evaluate_ward(far, ruleset(strict)).cards if not c.baseline] == []


def test_no_station_at_all_still_evaluates_and_is_estimated():
    c = ctx(station_distance_km=None, nearest_station_name=None, aqi=190, forecast=[(2, 230)])
    result = evaluate_ward(c, ruleset(CROSS_RULE))
    assert result.is_estimated and result.distance_to_station_km is None and result.cards


def test_disabled_rule_produces_nothing():
    off = {**BURN_RULE, "enabled": False}
    assert [c for c in evaluate_ward(ctx(burning_sites=[SITE]), ruleset(off)).cards if not c.baseline] == []


def test_unverified_citation_is_not_exposed_on_cards():
    rule = {**BURN_RULE, "source_reference": "Some Plan 2023", "source_verified": False}
    card = evaluate_ward(ctx(burning_sites=[SITE]), ruleset(rule)).cards[0]
    assert card.source_reference is None and card.source_verified is False
    verified = {**BURN_RULE, "source_reference": "Some Plan 2023", "source_verified": True}
    assert evaluate_ward(ctx(burning_sites=[SITE]), ruleset(verified)).cards[0].source_reference == "Some Plan 2023"


def test_simulated_burning_marks_card():
    card = evaluate_ward(ctx(burning_sites=[{**SITE, "simulated": True}]), ruleset(BURN_RULE)).cards[0]
    assert card.simulated is True


def test_simulated_summary_gives_real_reason_no_prefix():
    card = evaluate_ward(ctx(burning_sites=[{**SITE, "simulated": True}]), ruleset(BURN_RULE)).cards[0]
    # [SIMULATED DEMO] prefix was removed from render_summary; simulated flag is still on the card
    assert card.simulated is True
    assert "Why: Deonar Dumping Ground is 2.4 km from the ward centre." in card.summary
    assert "Why: SIMULATED" not in card.summary


def test_real_summary_has_no_simulated_prefix():
    card = evaluate_ward(ctx(burning_sites=[SITE]), ruleset(BURN_RULE)).cards[0]
    assert not card.summary.startswith("[SIMULATED")


def test_rule_params_override_detector_defaults():
    c = ctx(aqi=190, forecast=[(10, 260)])
    short = base_rule(id="S", signal="forecast_crossing")
    long = base_rule(id="L", signal="forecast_crossing", params={"horizon_hours": 12})
    assert [c for c in evaluate_ward(c, ruleset(short)).cards if not c.baseline] == []
    assert len([c for c in evaluate_ward(c, ruleset(long)).cards if not c.baseline]) == 1


def test_include_signals_explains_quiet_rules():
    result = evaluate_ward(ctx(), ruleset(BURN_RULE, CROSS_RULE), include_signals=True)
    assert [s["rule_id"] for s in result.signals] == ["BURN", "CROSS"]
    assert all(not s["fired"] and s["evidence"] for s in result.signals)
    assert evaluate_ward(ctx(), ruleset(BURN_RULE)).signals is None


# ── ranking across wards ──────────────────────────────────────────────────

def test_all_wards_are_returned_and_ranked_by_exposure():
    big = ctx(ward_id="BIG", ward_name="Big", population=800_000, aqi=180, burning_sites=[SITE])
    small = ctx(ward_id="SMALL", ward_name="Small", population=50_000, aqi=180, burning_sites=[SITE])
    quiet_dense = ctx(ward_id="QD", ward_name="Quiet dense", population=900_000, aqi=120)
    quiet_light = ctx(ward_id="QL", ward_name="Quiet light", population=10_000, aqi=60)
    results = evaluate_all([quiet_light, small, quiet_dense, big], ruleset(BURN_RULE))
    assert [r.ward_id for r in results] == ["BIG", "SMALL", "QD", "QL"]
    assert len(results) == 4
    live_qd = [c for c in results[2].cards if not c.baseline]
    assert live_qd == [] and results[2].priority_score == 0.0


def test_evaluate_all_uses_current_rule_file_by_default(rules_file, monkeypatch):
    monkeypatch.setattr(ae, "RULES_PATH", rules_file)
    reset_ruleset_cache()
    out = evaluate_all([ctx(air_mass={"fires_on_path": 2})])
    assert out[0].cards[0].rule_id == "R1"