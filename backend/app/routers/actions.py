from __future__ import annotations

import threading
import time
from datetime import datetime, timezone, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.analytics.action_context import build_ward_contexts, data_mode
from app.analytics.action_engine import (
    RuleError, WardContext, evaluate_all, evaluate_ward, get_ruleset,
    ruleset_status, category_for_aqi, forecast_without_action,
)
from app.db import get_db

router = APIRouter(prefix="/api", tags=["actions"])

IST_OFFSET = timedelta(hours=5, minutes=30)

# ---------------------------------------------------------------------------
# Scenario definitions — each preset maps to exact WardContext overrides.
# The overrides are chosen so the relevant detector threshold is definitively
# crossed, without hard-coding any output text.
# ---------------------------------------------------------------------------

SCENARIO_DEFS: dict[str, dict] = {
    "landfill_fire": {
        "label": "Deonar Landfill Firestorm",
        "preferred_ward": "M/E",
        # Inject an active high-confidence burning site inside the ward
        "burning_site": {
            "name": "Deonar Dumping Ground (active fire)",
            "level": "likely",
            "score": 85,
            "simulated": True,
            "reasons": [
                "NASA VIIRS thermal anomaly detected at Deonar landfill perimeter",
                "Subsurface methane ignition and open MSW combustion confirmed",
            ],
        },
        "aqi_delta": 185,     # added on top of the ward's live AQI
    },
    "winter_stagnation": {
        "label": "Winter Coastal Inversion and Stagnation Trap",
        "preferred_ward": "H/E",
        # Drive stagnation detector: calm winds for 3 h + rising forecast
        "wind_speeds_recent": [0.8, 0.9, 0.7],     # all < 1.5 m/s (calm threshold)
        "forecast_delta": 38,    # AQI rise over 6 h  (> min_rise_aqi 10)
        "aqi_delta": 140,
    },
    "cd_dust": {
        "label": "Kurla C&D Road Dust Resuspension Surge",
        "preferred_ward": "L",
        # Drive dust detector: low fine fraction + dry + PM10 elevated
        "fine_fraction": 0.28,
        "humidity_pct": 42.0,
        "precip_24h_mm": 0.0,
        "pm10_ratio": 1.85,     # pm10_recent / pm10_baseline ratio
        "concentrations_valid": True,
        "aqi_delta": 120,
    },
}


class SimulateRequest(BaseModel):
    ward_id: str = Field(..., description="Target BMC ward ID (e.g. 'H/E', 'M/E', 'L')")
    scenario: str = Field(..., description="One of: landfill_fire | winter_stagnation | cd_dust")
    lang: str = Field("en", description="Language for LLM rationale output: 'en' | 'hi' | 'mr'")


def _synthesize_context(base: WardContext, scenario_key: str) -> WardContext:
    """
    Clone a live WardContext and apply physical overrides for the chosen scenario
    so that the target detectors fire definitively. Nothing is hardcoded in the
    output — the action engine evaluates the synthetic context exactly as it
    would evaluate live data.
    """
    defn = SCENARIO_DEFS[scenario_key]
    now_ist = datetime.now(tz=timezone.utc) + IST_OFFSET

    # --- common: elevate AQI ------------------------------------------------
    sim_aqi = min(500.0, base.aqi + defn.get("aqi_delta", 0))
    sim_category = category_for_aqi(sim_aqi)

    # --- build overrides per scenario ---------------------------------------
    overrides: dict = {}

    if scenario_key == "landfill_fire":
        site = {
            **defn["burning_site"],
            "lat": base.lat,
            "lon": base.lon,
            "inside_ward": True,
            "distance_km": 0.0,
        }
        overrides = {
            "aqi": sim_aqi,
            "category": sim_category,
            "burning_sites": [site],
        }

    elif scenario_key == "winter_stagnation":
        # Forecast: build a list of (hours_ahead, aqi) pairs that rise
        forecast_base = sim_aqi
        delta = defn["forecast_delta"]
        sim_forecast = [
            (1, forecast_base + delta * 0.3),
            (2, forecast_base + delta * 0.5),
            (3, forecast_base + delta * 0.75),
            (6, forecast_base + delta),
            (12, forecast_base + delta * 0.9),
        ]
        overrides = {
            "aqi": sim_aqi,
            "category": sim_category,
            "wind_speeds_recent": defn["wind_speeds_recent"],
            "forecast": sim_forecast,
        }

    elif scenario_key == "cd_dust":
        pm10_baseline = 60.0   # typical urban baseline in ug/m3
        overrides = {
            "aqi": sim_aqi,
            "category": sim_category,
            "fine_fraction": defn["fine_fraction"],
            "humidity_pct": defn["humidity_pct"],
            "precip_24h_mm": defn["precip_24h_mm"],
            "pm10_recent": pm10_baseline * defn["pm10_ratio"],
            "pm10_baseline": pm10_baseline,
            "concentrations_valid": defn["concentrations_valid"],
        }

    # Merge: start from live context fields, apply overrides
    import dataclasses
    live_fields = {f.name: getattr(base, f.name) for f in dataclasses.fields(base)}
    live_fields.update(overrides)
    live_fields["category"] = category_for_aqi(live_fields["aqi"])
    return WardContext(**live_fields)

CACHE_TTL_SECONDS = 300
_cache: dict[tuple, tuple[float, dict]] = {}
_cache_lock = threading.Lock()


def clear_cache() -> None:
    with _cache_lock:
        _cache.clear()


def _rules_or_503():
    try:
        return get_ruleset()
    except RuleError as exc:
        raise HTTPException(status_code=503, detail=f"Action rules are not usable: {exc}")


@router.get("/actions")
def ward_actions(
    include_signals: bool = Query(False, description="Also return, per ward, why each rule did or did not fire"),
    ward_id: str | None = Query(None, description="Return only this ward"),
    lang: str = Query("en", description="Language for LLM rationale: 'en' | 'hi' | 'mr'"),
    db: Session = Depends(get_db),
):
    safe_lang = lang if lang in ("en", "hi", "mr") else "en"
    ruleset = _rules_or_503()
    # Only cache English — non-English requests are generated on-the-fly
    use_cache = safe_lang == "en"
    key = (include_signals, ruleset.version, ruleset_status()["rule_count"], id(ruleset))
    if use_cache:
        with _cache_lock:
            hit = _cache.get(key)
            fresh = hit is not None and time.time() - hit[0] < CACHE_TTL_SECONDS
        if fresh:
            payload = hit[1]
            if ward_id is None:
                return payload
            wards = [w for w in payload["wards"] if w["ward_id"] == ward_id]
            if not wards:
                raise HTTPException(status_code=404, detail=f"Unknown ward_id '{ward_id}'.")
            return {**payload, "wards": wards, "total_wards_evaluated": 1,
                    "wards_with_cards": sum(1 for w in wards if w["cards"])}

    try:
        contexts, meta = build_ward_contexts(db)
    except LookupError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    results = evaluate_all(contexts, ruleset, include_signals=include_signals, lang=safe_lang)
    payload = {
        "generated_at": datetime.now(tz=timezone.utc).isoformat(),
        "data_mode": meta.data_mode,
        "stations_used": meta.stations_used,
        "total_wards_evaluated": len(results),
        "wards_with_cards": sum(1 for r in results if r.cards),
        "rules": {"version": ruleset.version, "active": sum(1 for r in ruleset.rules if r.enabled)},
        "warnings": meta.warnings,
        "wards": [r.to_dict() for r in results],
    }
    if use_cache:
        with _cache_lock:
            _cache[key] = (time.time(), payload)

    if ward_id is None:
        return payload
    wards = [w for w in payload["wards"] if w["ward_id"] == ward_id]
    if not wards:
        raise HTTPException(status_code=404, detail=f"Unknown ward_id '{ward_id}'.")
    return {**payload, "wards": wards, "total_wards_evaluated": 1,
            "wards_with_cards": sum(1 for w in wards if w["cards"])}


def normalize_priority_score(raw: float, population: int | None = None) -> float:
    """
    Normalize raw exposure-severity priority score to a clean 0-100 scale.
    Raw priority = severity_weight (1..3) * population * (aqi / 100).
    Max theoretical exposure for a ward is severity 3.0 * population * (500 AQI / 100) = 15.0 * population.
    If population is unavailable, falls back to city-average ward population (600,000 -> 9,000,000 ceiling).
    """
    if raw <= 0:
        return 0.0
    if population and population > 0:
        capacity = 15.0 * population
        norm = (raw / capacity) * 100.0
    else:
        norm = (raw / 9_000_000.0) * 100.0
    return round(min(100.0, max(0.0, norm)), 1)


@router.post("/actions/simulate")
def simulate_ward(
    body: SimulateRequest,
    db: Session = Depends(get_db),
):
    """
    Synthesize a crisis scenario for a chosen ward and run the action engine
    against it. Returns the same schema as /api/actions for one ward, plus
    a 'simulation' block with the before/after delta.
    """
    if body.scenario not in SCENARIO_DEFS:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown scenario '{body.scenario}'. Valid: {sorted(SCENARIO_DEFS)}",
        )

    ruleset = _rules_or_503()

    # Build live contexts for all wards — we need the base WardContext for the target
    try:
        contexts, meta = build_ward_contexts(db)
    except LookupError as exc:
        raise HTTPException(status_code=503, detail=str(exc))

    base_ctx = next((c for c in contexts if c.ward_id == body.ward_id), None)
    if base_ctx is None:
        raise HTTPException(
            status_code=404,
            detail=f"Ward '{body.ward_id}' not found. Available: {sorted(c.ward_id for c in contexts)}",
        )

    safe_lang = body.lang if body.lang in ("en", "hi", "mr") else "en"

    # Evaluate baseline (what the engine currently says for that ward)
    baseline_result = evaluate_ward(base_ctx, ruleset, include_signals=True, lang=safe_lang)

    # Synthesize the simulated context
    try:
        sim_ctx = _synthesize_context(base_ctx, body.scenario)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Context synthesis failed: {exc}")

    # Evaluate the simulated context
    sim_result = evaluate_ward(sim_ctx, ruleset, include_signals=True, lang=safe_lang)

    # Mark all cards as simulated and normalize their priority scores to 0-100
    for card in sim_result.cards:
        card.simulated = True
        card.priority_score = normalize_priority_score(card.priority_score, sim_ctx.population)

    defn = SCENARIO_DEFS[body.scenario]
    generated_at = datetime.now(tz=timezone.utc).isoformat()

    return {
        "generated_at": generated_at,
        "scenario": body.scenario,
        "scenario_label": defn["label"],
        "ward_id": body.ward_id,
        "ward_name": sim_ctx.ward_name,
        "simulation": {
            "baseline_aqi": round(base_ctx.aqi, 1),
            "baseline_category": base_ctx.category,
            "simulated_aqi": round(sim_ctx.aqi, 1),
            "simulated_category": sim_ctx.category,
            "aqi_delta": round(sim_ctx.aqi - base_ctx.aqi, 1),
            "population": sim_ctx.population,
            "baseline_card_count": len([c for c in baseline_result.cards if not c.baseline]),
            "simulated_card_count": len([c for c in sim_result.cards if not c.baseline]),
            "baseline_priority_score": normalize_priority_score(baseline_result.priority_score, base_ctx.population),
            "simulated_priority_score": normalize_priority_score(sim_result.priority_score, sim_ctx.population),
        },
        "signals": sim_result.signals,
        "cards": [c.to_dict() for c in sim_result.cards],
    }