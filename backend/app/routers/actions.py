from __future__ import annotations

import threading
import time
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.analytics.action_context import build_ward_contexts, data_mode
from app.analytics.action_engine import RuleError, evaluate_all, get_ruleset, ruleset_status
from app.db import get_db

router = APIRouter(prefix="/api", tags=["actions"])

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


@router.get("/actions/rules")
def action_rules():
    """The rules the engine is using right now, so officials can audit them."""
    ruleset = _rules_or_503()
    return {
        "status": ruleset_status(),
        "rules": [r.to_dict() for r in ruleset.rules],
    }


@router.get("/actions")
def ward_actions(
    simulate_burning: bool = Query(False, description="Demo mode: pretend Deonar is burning (cards are marked simulated)"),
    include_signals: bool = Query(False, description="Also return, per ward, why each rule did or did not fire"),
    ward_id: str | None = Query(None, description="Return only this ward"),
    db: Session = Depends(get_db),
):
    ruleset = _rules_or_503()
    key = (simulate_burning, include_signals, ruleset.version, ruleset_status()["rule_count"], id(ruleset))
    with _cache_lock:
        hit = _cache.get(key)
        fresh = hit is not None and time.time() - hit[0] < CACHE_TTL_SECONDS
    if fresh:
        payload = hit[1]
    else:
        try:
            contexts, meta = build_ward_contexts(db, simulate_burning=simulate_burning)
        except LookupError as exc:
            raise HTTPException(status_code=503, detail=str(exc))
        results = evaluate_all(contexts, ruleset, include_signals=include_signals)
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
        with _cache_lock:
            _cache[key] = (time.time(), payload)

    if ward_id is None:
        return payload
    wards = [w for w in payload["wards"] if w["ward_id"] == ward_id]
    if not wards:
        raise HTTPException(status_code=404, detail=f"Unknown ward_id '{ward_id}'.")
    return {**payload, "wards": wards, "total_wards_evaluated": 1,
            "wards_with_cards": sum(1 for w in wards if w["cards"])}