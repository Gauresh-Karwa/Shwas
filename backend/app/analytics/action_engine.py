"""
Ward Action Engine - core (pure functions, no database, no network).

For every ward the engine:
  1. runs a set of small signal detectors on a WardContext (plain numbers in),
  2. matches fired signals to rules loaded from app/rules/action_rules.yaml,
  3. builds action cards (what / evidence / when / forecast if nothing is done),
  4. ranks wards by exposure: severity weight x population x (AQI / 100).

Nothing here guarantees an outcome. A card says "likely contributor" and shows the
numbers behind it; the forecast shown is the model's forecast WITHOUT any action.

Rules are data, not code: edit action_rules.yaml and the next request uses the new
version (get_ruleset re-reads the file when its modification time changes; a broken
edit is rejected and the last good rule set stays active).
"""
from __future__ import annotations

import math
import threading
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import yaml

from app.aqi.calculator import CATEGORY_BANDS
from app.utils import slugify
from app.analytics.action_reasoner import generate_action_reasoning

RULES_PATH = Path(__file__).resolve().parent.parent / "rules" / "action_rules.yaml"

SEVERITIES = ("low", "medium", "high")
SEVERITY_WEIGHT = {"low": 1.0, "medium": 2.0, "high": 3.0}
CONFIDENCE_LABELS = ("indicative", "possible", "likely", "high")

STATION_DISTANCE_SCALE_KM = 12.0   # ward confidence = signal confidence * exp(-d / 12)
ESTIMATED_DISTANCE_KM = 6.0        # beyond this the ward is tagged "estimated"
UNKNOWN_DISTANCE_FACTOR = 0.4      # no station at all near the ward
FORECAST_TREND_BAND_AQI = 5.0      # +/- band around "now" that counts as steady

CATEGORY_NAMES = [name for _, _, name in CATEGORY_BANDS]
SIMULATED_MARK = "SIMULATED"       # first word of the evidence line that flags demo data

IST_OFFSET = timedelta(hours=5, minutes=30)


def format_dynamic_checkpoint(checkpoint: str, now: datetime | None = None) -> str:
    """Enriches relative checkpoint SLAs with dynamic target timestamps in IST."""
    if not checkpoint:
        return ""
    now_utc = now or datetime.now(timezone.utc)
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=timezone.utc)
    now_ist = now_utc + IST_OFFSET

    t_60m = (now_ist + timedelta(minutes=60)).strftime("%H:%M")
    t_90m = (now_ist + timedelta(minutes=90)).strftime("%H:%M")
    t_2h = (now_ist + timedelta(hours=2)).strftime("%H:%M")
    t_3h = (now_ist + timedelta(hours=3)).strftime("%H:%M")
    t_4h = (now_ist + timedelta(hours=4)).strftime("%H:%M")

    res = checkpoint
    if "within 90 minutes" in res and "target" not in res:
        res = res.replace("within 90 minutes", f"within 90 minutes (target deadline: {t_90m} IST)")
    if "within 1 hour" in res and "target" not in res:
        res = res.replace("within 1 hour", f"within 1 hour (target: {t_60m} IST)")
    if "within 2 hours" in res and "target" not in res:
        res = res.replace("within 2 hours", f"within 2 hours (target: {t_2h} IST)")
    if "within 3 hours" in res and "target" not in res:
        res = res.replace("within 3 hours", f"within 3 hours (target: {t_3h} IST)")
    if "within 4 hours" in res and "target" not in res:
        res = res.replace("within 4 hours", f"within 4 hours (target: {t_4h} IST)")
    return res


# -- category helpers ------------------------------------------------------

def category_for_aqi(aqi: float) -> str:
    for _, high, name in CATEGORY_BANDS:
        if aqi <= high:
            return name
    return CATEGORY_NAMES[-1]


def category_index(name: str) -> int:
    return CATEGORY_NAMES.index(name)


def category_lower_bound(name: str) -> int:
    for low, _, band_name in CATEGORY_BANDS:
        if band_name == name:
            return low
    raise ValueError(f"Unknown category {name!r}")


def confidence_label(score: float) -> str:
    if score >= 0.75:
        return "high"
    if score >= 0.5:
        return "likely"
    if score >= 0.3:
        return "possible"
    return "indicative"


def confidence_rank(label: str) -> int:
    return CONFIDENCE_LABELS.index(label)


def _clip01(value: float) -> float:
    return max(0.0, min(1.0, value))


# -- inputs and outputs ----------------------------------------------------

@dataclass
class WardContext:
    """Everything the detectors may look at for one ward. Missing data is None."""
    ward_id: str
    ward_name: str
    population: int
    lat: float
    lon: float
    aqi: float
    category: str = ""
    aqi_method: str = ""
    local_hour: int = 0                        # Mumbai local time (IST), 0-23

    nearest_station_id: str | None = None
    nearest_station_name: str | None = None
    station_distance_km: float | None = None
    gas_channels_flat: bool | None = None      # None = unknown

    # data-scale switches (see ACTION_DATA_MODE in app/config.py)
    concentrations_valid: bool = False         # stored values are real concentrations
    hourly_gas_valid: bool = False             # gas values are hourly, not 24 h averages

    fine_fraction: float | None = None         # PM2.5 / PM10, 24 h
    pm10_recent: float | None = None
    pm10_baseline: float | None = None
    no2_recent: float | None = None
    no2_baseline_same_hour: float | None = None
    co_recent: float | None = None
    co_baseline_same_hour: float | None = None

    wind_speeds_recent: list[float] = field(default_factory=list)   # newest first, m/s
    precip_24h_mm: float | None = None
    humidity_pct: float | None = None

    forecast: list[tuple[int, float]] | None = None   # (hours ahead, AQI)
    burning_sites: list[dict] = field(default_factory=list)
    air_mass: dict | None = None

    def __post_init__(self):
        if not self.category:
            self.category = category_for_aqi(self.aqi)


@dataclass(frozen=True)
class Signal:
    name: str
    fired: bool
    strength: float = 0.0              # 0..1
    confidence: float = 0.0            # 0..1, before the station-distance adjustment
    evidence: tuple[str, ...] = ()
    station_dependent: bool = False    # confidence shrinks with distance to a station
    severity_hint: str | None = None   # a detector may raise, never lower, a rule's severity
    details: dict = field(default_factory=dict)


def _quiet(name: str, reason: str, station_dependent: bool = False) -> Signal:
    return Signal(name=name, fired=False, evidence=(reason,), station_dependent=station_dependent)


# -- detectors -------------------------------------------------------------

BURNING_LEVEL_CONFIDENCE = {"likely": 0.85, "possible": 0.60}

DEFAULT_PARAMS: dict[str, dict] = {
    "waste_burning": {"decay_km": 6.0, "high_within_km": 2.5},
    "inflow": {},
    "forecast_crossing": {"horizon_hours": 6, "margin_aqi": 5, "high_from_category": "Poor"},
    "stagnation": {"calm_speed_mps": 1.5, "calm_hours": 3, "horizon_hours": 12, "min_rise_aqi": 10},
    "traffic": {
        "morning_start": 8, "morning_end": 11,
        "evening_start": 17, "evening_end": 21,
        "spike_ratio": 1.3,
    },
    "dust": {
        "max_fine_fraction": 0.40, "max_humidity_pct": 70,
        "max_precip_mm": 0.1, "min_pm10_ratio": 1.2,
    },
}


def _site_distance_km(site: dict) -> float | None:
    """Distance used for the smoke decay: 0 when the dump site lies inside the ward."""
    if site.get("inside_ward"):
        return 0.0
    return site.get("distance_km")


def detect_waste_burning(ctx: WardContext, params: dict) -> Signal:
    """Confidence falls with the dump site's distance from the ward: smoke thins out as it
    travels, so a ward far from a burning site gets a weaker card than the ward holding it.
    Severity is raised to "high" only for a "likely" fire within high_within_km."""
    name = "waste_burning"
    candidates = [s for s in ctx.burning_sites if s.get("level") in BURNING_LEVEL_CONFIDENCE]
    if not candidates:
        if ctx.burning_sites:
            return _quiet(name, "A dump site is near this ward but shows no fire evidence right now.")
        return _quiet(name, "No monitored dump site is near this ward.")
    decay = float(params["decay_km"])

    def adjusted(site: dict) -> float:
        base = BURNING_LEVEL_CONFIDENCE[site["level"]]
        distance = _site_distance_km(site)
        return base if distance is None else base * math.exp(-max(0.0, distance) / decay)

    best = max(candidates, key=lambda s: (adjusted(s), s.get("score", 0)))
    distance = _site_distance_km(best)
    evidence = []
    if best.get("simulated"):
        evidence.append(f"{SIMULATED_MARK} demo data, not a real detection")
    if best.get("inside_ward"):
        evidence.append(f"{best['name']} lies inside this ward")
    elif distance is not None:
        evidence.append(f"{best['name']} is {distance:.1f} km from the ward centre")
    evidence.extend(best.get("reasons", []))
    close = distance is None or distance <= float(params["high_within_km"])
    return Signal(
        name=name, fired=True,
        strength=_clip01(best.get("score", 0) / 100.0),
        confidence=adjusted(best),
        evidence=tuple(evidence),
        severity_hint="high" if best["level"] == "likely" and close else None,
        details={"site_id": best.get("site_id"), "level": best["level"],
                 "simulated": bool(best.get("simulated")), "distance_km": distance},
    )


def detect_inflow(ctx: WardContext, params: dict) -> Signal:
    name = "inflow"
    mass = ctx.air_mass
    if not mass:
        return _quiet(name, "No back-trajectory is available for this ward.")
    count = int(mass.get("fires_on_path") or 0)
    if count <= 0:
        return _quiet(name, "No satellite fire detections lie along the incoming air path.")

    hours = mass.get("hours") or 6
    upwind_h = mass.get("nearest_fire_hours_upwind")
    dist_corridor = mass.get("nearest_fire_dist_km")
    compass = mass.get("origin_compass") or "upwind"
    speed = mass.get("mean_speed_mps")
    path_len = mass.get("path_km")
    total_frp = float(mass.get("total_frp_mw") or 0.0)

    evidence = []
    if upwind_h is not None and dist_corridor is not None:
        evidence.append(
            f"{count} satellite fire detection(s) (total {total_frp:.1f} MW) identified ~{upwind_h:.1f} h upwind along {compass} corridor ({dist_corridor:.1f} km from plume axis)"
        )
    else:
        evidence.append(f"{count} satellite fire detection(s) lie along incoming air path over the last {hours} h ({total_frp:.1f} MW)")

    if speed is not None and path_len is not None:
        evidence.append(
            f"Air parcel traversed {path_len:.0f} km from {compass} over past {hours} h at {speed:.1f} m/s average transport velocity"
        )
    elif total_frp > 0 and len(evidence) < 2:
        evidence.append(f"Combined thermal intensity {total_frp:.1f} MW along trajectory corridor")

    if upwind_h is not None and speed is not None:
        low_w = max(1, int(round(upwind_h)))
        high_w = max(low_w + 1, int(round(upwind_h + 2.5)))
        dynamic_window = f"Active plume transit window: next {low_w} to {high_w} hours ({speed:.1f} m/s from {compass})"
    else:
        dynamic_window = f"During active upwind smoke transit window ({compass} corridor)"

    return Signal(
        name=name, fired=True,
        strength=_clip01(count / 3.0), confidence=0.5,
        evidence=tuple(evidence),
        details={
            "fires_on_path": count,
            "dynamic_window": dynamic_window,
            "upwind_hours": upwind_h,
            "distance_to_path_km": dist_corridor,
            "origin_compass": compass,
        },
    )



def _forecast_points(ctx: WardContext, horizon: int) -> list[tuple[int, float]]:
    if not ctx.forecast:
        return []
    return [(h, a) for h, a in ctx.forecast if 1 <= h <= horizon]


def detect_forecast_crossing(ctx: WardContext, params: dict) -> Signal:
    name = "forecast_crossing"
    points = _forecast_points(ctx, int(params["horizon_hours"]))
    if not points:
        return _quiet(name, "No forecast is available for this ward.", station_dependent=True)
    now_idx = category_index(category_for_aqi(ctx.aqi))
    margin = float(params["margin_aqi"])
    crossing = None
    for hours, aqi in sorted(points):
        idx = category_index(category_for_aqi(aqi))
        if idx > now_idx and aqi >= category_lower_bound(CATEGORY_NAMES[idx]) + margin:
            crossing = (hours, aqi, idx)
            break
    if crossing is None:
        return _quiet(name, "The forecast stays in the current AQI category.", station_dependent=True)
    hours, aqi, idx = crossing
    steps_up = idx - now_idx
    confidence = 0.75 if hours <= 3 else 0.65 if hours <= 6 else 0.55
    high_from = params.get("high_from_category")
    hint = "high" if high_from in CATEGORY_NAMES and idx >= category_index(high_from) else None
    return Signal(
        name=name, fired=True,
        strength=_clip01(0.4 + 0.3 * steps_up), confidence=confidence,
        evidence=(f"Forecast reaches {CATEGORY_NAMES[idx]} (AQI {aqi:.0f}) in {hours} h; "
                  f"now {ctx.category} (AQI {ctx.aqi:.0f})",),
        station_dependent=True, severity_hint=hint,
        details={"hours": hours, "target_category": CATEGORY_NAMES[idx], "target_aqi": aqi},
    )


def detect_stagnation(ctx: WardContext, params: dict) -> Signal:
    name = "stagnation"
    need = int(params["calm_hours"])
    speeds = [s for s in ctx.wind_speeds_recent if s is not None][:need]
    if len(speeds) < need:
        return _quiet(name, "Recent wind data is not available for this ward.", station_dependent=True)
    calm = float(params["calm_speed_mps"])
    if any(s >= calm for s in speeds):
        return _quiet(name, f"Wind has not stayed below {calm:g} m/s for {need} h.", station_dependent=True)
    points = _forecast_points(ctx, int(params["horizon_hours"]))
    if not points:
        return _quiet(name, "Wind is calm, but no forecast is available to judge the trend.",
                      station_dependent=True)
    peak_h, peak = max(points, key=lambda p: p[1])
    rise = peak - ctx.aqi
    if rise < float(params["min_rise_aqi"]):
        return _quiet(name, "Wind is calm, but the forecast is not rising.", station_dependent=True)
    strength = _clip01(rise / 60.0)
    return Signal(
        name=name, fired=True, strength=strength, confidence=0.45 + 0.35 * strength,
        evidence=(f"Wind has stayed below {calm:g} m/s for {need} h (mean {sum(speeds) / len(speeds):.1f} m/s)",
                  f"Forecast rises by {rise:.0f} AQI points within {int(params['horizon_hours'])} h "
                  f"(peak {peak:.0f} at +{peak_h} h)"),
        station_dependent=True,
        details={"rise": rise, "peak_hours": peak_h},
    )


def _in_rush_window(hour: int, p: dict) -> bool:
    return (p["morning_start"] <= hour < p["morning_end"]
            or p["evening_start"] <= hour < p["evening_end"])


def detect_traffic(ctx: WardContext, params: dict) -> Signal:
    name = "traffic"
    if not ctx.hourly_gas_valid:
        return _quiet(name, "Needs hourly NO2/CO concentrations; the current data mode does not provide them.",
                      station_dependent=True)
    if ctx.gas_channels_flat is None:
        return _quiet(name, "NO2/CO data is not available at the nearest station.", station_dependent=True)
    if ctx.gas_channels_flat:
        return _quiet(name, "The nearest station's gas channels are flat, so traffic cannot be read from them.",
                      station_dependent=True)
    if not _in_rush_window(ctx.local_hour, params):
        return _quiet(name, "Outside the morning and evening rush windows.", station_dependent=True)
    spike = float(params["spike_ratio"])
    best = None
    for label, recent, base in (("NO2", ctx.no2_recent, ctx.no2_baseline_same_hour),
                                ("CO", ctx.co_recent, ctx.co_baseline_same_hour)):
        if recent is None or base is None or base <= 0:
            continue
        ratio = recent / base
        if ratio >= spike and (best is None or ratio > best[1]):
            best = (label, ratio)
    if best is None:
        return _quiet(name, "NO2 and CO are not above their usual level for this hour.", station_dependent=True)
    label, ratio = best
    strength = _clip01(ratio - 1.0)
    station = f" at {ctx.nearest_station_name}" if ctx.nearest_station_name else ""
    return Signal(
        name=name, fired=True, strength=strength,
        confidence=min(0.8, 0.5 + 0.3 * strength),
        evidence=(f"{label} is {ratio:.1f}x its usual level for this hour{station}",
                  f"Local time {ctx.local_hour:02d}:00 falls in a rush window"),
        station_dependent=True, details={"pollutant": label, "ratio": ratio},
    )


def detect_dust(ctx: WardContext, params: dict) -> Signal:
    name = "dust"
    if not ctx.concentrations_valid:
        return _quiet(name, "Needs real PM concentrations; the current data mode stores sub-indices.",
                      station_dependent=True)
    if ctx.fine_fraction is None:
        return _quiet(name, "PM2.5 and PM10 are not both available at the nearest station.", station_dependent=True)
    if ctx.precip_24h_mm is None or ctx.humidity_pct is None:
        return _quiet(name, "Rain and humidity data is not available.", station_dependent=True)
    max_fine = float(params["max_fine_fraction"])
    if ctx.fine_fraction > max_fine:
        return _quiet(name, f"Fine fraction {ctx.fine_fraction:.2f} is above {max_fine:.2f}; coarse dust does not dominate.",
                      station_dependent=True)
    if ctx.precip_24h_mm > float(params["max_precip_mm"]):
        return _quiet(name, "It has rained in the last 24 h, which suppresses dust.", station_dependent=True)
    if ctx.humidity_pct >= float(params["max_humidity_pct"]):
        return _quiet(name, "Humidity is too high for dust to lift.", station_dependent=True)
    evidence = [f"PM2.5/PM10 is {ctx.fine_fraction:.2f}, so coarse particles dominate",
                f"No rain in 24 h and humidity {ctx.humidity_pct:.0f}%"]
    ratio = None
    if ctx.pm10_recent is not None and ctx.pm10_baseline:
        ratio = ctx.pm10_recent / ctx.pm10_baseline
        if ratio < float(params["min_pm10_ratio"]):
            return _quiet(name, "PM10 is not above its own recent level.", station_dependent=True)
        evidence.append(f"PM10 is {ratio:.1f}x its recent level")
    strength = _clip01(1.0 - ctx.fine_fraction / max_fine) if max_fine > 0 else 0.5
    strength = max(strength, 0.2)
    return Signal(
        name=name, fired=True, strength=strength, confidence=0.45 + 0.35 * strength,
        evidence=tuple(evidence), station_dependent=True, details={"pm10_ratio": ratio},
    )


DETECTORS: dict[str, Callable[[WardContext, dict], Signal]] = {
    "waste_burning": detect_waste_burning,
    "inflow": detect_inflow,
    "forecast_crossing": detect_forecast_crossing,
    "stagnation": detect_stagnation,
    "traffic": detect_traffic,
    "dust": detect_dust,
}


# -- rules -----------------------------------------------------------------

class RuleError(ValueError):
    """The rules file is not valid; the previous rule set (if any) stays active."""


@dataclass(frozen=True)
class Rule:
    id: str
    signal: str
    enabled: bool
    severity: str
    min_confidence: str
    advisory: bool
    action_title: str
    time_window: str
    rationale: str
    source_reference: str | None
    source_verified: bool
    params: dict
    department: str = ""
    sop: str = ""
    compliance_checkpoint: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id, "signal": self.signal, "enabled": self.enabled,
            "severity": self.severity, "min_confidence": self.min_confidence,
            "advisory": self.advisory, "action_title": self.action_title,
            "time_window": self.time_window, "rationale": self.rationale,
            "source_reference": self.source_reference, "source_verified": self.source_verified,
            "params": dict(self.params),
            "department": self.department, "sop": self.sop,
            "compliance_checkpoint": self.compliance_checkpoint,
        }


@dataclass(frozen=True)
class RuleSet:
    version: str
    rules: tuple[Rule, ...]


_RULE_KEYS = {"id", "signal", "enabled", "severity", "min_confidence", "advisory", "action_title",
              "time_window", "rationale", "source_reference", "source_verified", "params",
              "department", "sop", "compliance_checkpoint"}
_REQUIRED_KEYS = {"id", "signal", "severity", "min_confidence", "action_title", "time_window", "rationale"}


def parse_rules(data) -> RuleSet:
    if not isinstance(data, dict) or "rules" not in data:
        raise RuleError("rules file must be a mapping with a 'rules' list")
    raw_rules = data["rules"]
    if not isinstance(raw_rules, list) or not raw_rules:
        raise RuleError("'rules' must be a non-empty list")
    rules: list[Rule] = []
    seen: set[str] = set()
    for i, raw in enumerate(raw_rules):
        where = f"rule #{i + 1}"
        if not isinstance(raw, dict):
            raise RuleError(f"{where}: must be a mapping")
        where = f"rule {raw.get('id', f'#{i + 1}')!r}"
        unknown = set(raw) - _RULE_KEYS
        if unknown:
            raise RuleError(f"{where}: unknown key(s) {sorted(unknown)}")
        missing = _REQUIRED_KEYS - set(raw)
        if missing:
            raise RuleError(f"{where}: missing key(s) {sorted(missing)}")
        if raw["id"] in seen:
            raise RuleError(f"{where}: duplicate id")
        seen.add(raw["id"])
        if raw["signal"] not in DETECTORS:
            raise RuleError(f"{where}: unknown signal {raw['signal']!r}; known: {sorted(DETECTORS)}")
        if raw["severity"] not in SEVERITIES:
            raise RuleError(f"{where}: severity must be one of {SEVERITIES}")
        if raw["min_confidence"] not in CONFIDENCE_LABELS:
            raise RuleError(f"{where}: min_confidence must be one of {CONFIDENCE_LABELS}")
        for key in ("action_title", "time_window", "rationale"):
            if not isinstance(raw[key], str) or not raw[key].strip():
                raise RuleError(f"{where}: {key} must be a non-empty string")
        for key in ("enabled", "advisory", "source_verified"):
            if key in raw and not isinstance(raw[key], bool):
                raise RuleError(f"{where}: {key} must be true or false")
        params = raw.get("params") or {}
        if not isinstance(params, dict):
            raise RuleError(f"{where}: params must be a mapping")
        bad = set(params) - set(DEFAULT_PARAMS[raw["signal"]])
        if bad:
            raise RuleError(f"{where}: unknown param(s) {sorted(bad)} for signal {raw['signal']!r}")
        source = raw.get("source_reference")
        if source is not None and not isinstance(source, str):
            raise RuleError(f"{where}: source_reference must be text or null")
        rules.append(Rule(
            id=raw["id"], signal=raw["signal"], enabled=raw.get("enabled", True),
            severity=raw["severity"], min_confidence=raw["min_confidence"],
            advisory=raw.get("advisory", False), action_title=raw["action_title"].strip(),
            time_window=raw["time_window"].strip(), rationale=raw["rationale"].strip(),
            source_reference=source, source_verified=raw.get("source_verified", False),
            params=dict(params),
            department=str(raw.get("department") or "").strip(),
            sop=str(raw.get("sop") or "").strip(),
            compliance_checkpoint=str(raw.get("compliance_checkpoint") or "").strip(),
        ))
    return RuleSet(version=str(data.get("version", "")), rules=tuple(rules))


def load_rules(path: Path | str = RULES_PATH) -> RuleSet:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle)
    except (OSError, yaml.YAMLError) as exc:
        raise RuleError(f"cannot read rules file {path}: {exc}") from exc
    return parse_rules(data)


_lock = threading.Lock()
_state: dict = {"path": None, "mtime": None, "ruleset": None, "error": None}


def get_ruleset(path: Path | str | None = None) -> RuleSet:
    """Current rule set, re-read from disk whenever the file changes.

    A file that fails validation is rejected: the last good rule set stays active and
    the error is kept in ruleset_status(). Only a first load with no good set raises.
    """
    target = Path(path) if path else RULES_PATH
    with _lock:
        try:
            mtime = target.stat().st_mtime_ns
        except OSError as exc:
            if _state["ruleset"] is not None and _state["path"] == str(target):
                _state["error"] = f"rules file unreadable: {exc}"
                return _state["ruleset"]
            raise RuleError(f"cannot read rules file {target}: {exc}") from exc
        if _state["path"] == str(target) and _state["mtime"] == mtime and _state["ruleset"] is not None:
            return _state["ruleset"]
        try:
            ruleset = load_rules(target)
        except RuleError as exc:
            if _state["ruleset"] is not None and _state["path"] == str(target):
                _state["mtime"] = mtime        # do not retry the same bad file on every request
                _state["error"] = str(exc)
                return _state["ruleset"]
            raise
        _state.update(path=str(target), mtime=mtime, ruleset=ruleset, error=None)
        return ruleset


def ruleset_status() -> dict:
    with _lock:
        ruleset = _state["ruleset"]
        return {
            "path": _state["path"],
            "version": ruleset.version if ruleset else None,
            "rule_count": len(ruleset.rules) if ruleset else 0,
            "last_error": _state["error"],
        }


def reset_ruleset_cache() -> None:
    with _lock:
        _state.update(path=None, mtime=None, ruleset=None, error=None)


# -- evaluation ------------------------------------------------------------

@dataclass
class ActionCard:
    card_id: str
    rule_id: str
    signal: str
    severity: str
    confidence: str
    confidence_score: float
    advisory: bool
    estimated: bool
    simulated: bool
    action_title: str
    time_window: str
    rationale: str
    evidence: list[str]
    forecast_without_action: dict | None
    source_reference: str | None
    source_verified: bool
    priority_score: float
    summary: str
    department: str = ""
    sop: str = ""
    compliance_checkpoint: str = ""
    baseline: bool = False     # True = standard mitigation, not a live signal card

    def to_dict(self) -> dict:
        return dict(self.__dict__)


@dataclass
class WardResult:
    ward_id: str
    ward_name: str
    population: int
    aqi: float
    category: str
    nearest_station: str | None
    distance_to_station_km: float | None
    is_estimated: bool
    priority_score: float
    cards: list[ActionCard] = field(default_factory=list)
    signals: list[dict] | None = None

    def to_dict(self) -> dict:
        out = {
            "ward_id": self.ward_id, "ward_name": self.ward_name, "population": self.population,
            "current_aqi": round(self.aqi, 1), "category": self.category,
            "nearest_station": self.nearest_station,
            "distance_to_station_km": self.distance_to_station_km,
            "is_estimated": self.is_estimated, "priority_score": round(self.priority_score, 1),
            "cards": [c.to_dict() for c in self.cards],
        }
        if self.signals is not None:
            out["signals"] = self.signals
        return out


def _distance_factor(distance_km: float | None) -> float:
    if distance_km is None:
        return UNKNOWN_DISTANCE_FACTOR
    return math.exp(-max(0.0, distance_km) / STATION_DISTANCE_SCALE_KM)


def forecast_without_action(ctx: WardContext, hours: int = 6) -> dict | None:
    """The model's forecast if nothing is done. Not a promise about any action."""
    points = [(h, a) for h, a in (ctx.forecast or []) if 1 <= h <= hours]
    if not points:
        return None
    h, aqi = max(points)
    delta = aqi - ctx.aqi
    trend = "rising" if delta > FORECAST_TREND_BAND_AQI else "falling" if delta < -FORECAST_TREND_BAND_AQI else "steady"
    return {"hours_ahead": h, "predicted_aqi": round(aqi, 1),
            "predicted_category": category_for_aqi(aqi), "trend": trend}


def render_summary(title: str, evidence: list[str], time_window: str, confidence: str,
                   simulated: bool = False) -> str:
    """Deterministic card text. An LLM may only rephrase this, never add facts.

    The reason shown is the first real piece of evidence; the "simulated" disclaimer is
    kept as a prefix instead, so a demo card never gives its disclaimer as the reason."""
    lead = next((e for e in evidence if not e.startswith(SIMULATED_MARK)), None) or "signal detected"
    return f"{title}. Why: {lead}. When: {time_window}. Confidence: {confidence}."


# -- Baseline operational mitigations --------------------------------------
# Mumbai has 24 wards. Even when no live signal fires, every ward should carry
# standard operational mitigation actions drawn from Mumbai's ward-specific risk
# profile (BMC 28-point C&D guidelines, SWM schedules, traffic management SOPs).
# These cards are marked baseline=True so the UI can style them distinctly.

@dataclass(frozen=True)
class BaselineMitigation:
    """A standard operational action that applies to every ward."""
    card_id_suffix: str
    action_title: str
    time_window: str
    rationale: str
    department: str
    sop: str
    compliance_checkpoint: str
    severity: str = "low"
    advisory: bool = False


# Four baseline mitigations that every Mumbai ward receives.
# Content is drawn from BMC Standard Operating Procedures and MCGM guidelines.
BASELINE_MITIGATIONS: list[BaselineMitigation] = [
    BaselineMitigation(
        card_id_suffix="dust_suppression",
        action_title="Hotspot Dust Suppression and C&D Site Enforcement",
        time_window="Daily during daylight hours (06:00 to 18:00)",
        rationale=(
            "Every ward in Mumbai has active construction or road-repair sites subject to BMC "
            "28-point Construction and Demolition guidelines. Routine water spraying and site "
            "compliance checks reduce fugitive PM10 emission by 30% to 60% on dry days."
        ),
        department="BMC Ward Works / Environment Dept (SWM and C&D Cell)",
        sop=(
            "Deploy 2 anti-smog guns or tanker sprinklers along identified C&D hotspots; "
            "inspect at least 3 sites for dust barriers, net covers, and wheel-wash compliance; "
            "issue Notice-to-Comply to non-conforming sites within 4 hours."
        ),
        compliance_checkpoint=(
            "Field officer submits photo-verified checklist within 4 hours of shift start; "
            "non-compliant sites reported to ward AEE by end of shift."
        ),
        severity="low",
    ),
    BaselineMitigation(
        card_id_suffix="traffic_corridor",
        action_title="Traffic Corridor Decongestion and Anti-Idling Patrol",
        time_window="Morning rush 08:00 to 10:30 and evening rush 17:00 to 20:00",
        rationale=(
            "Mumbai arterial corridors (LBS Marg, Eastern/Western Express Highways, "
            "SV Road) generate peak NO2 and CO during school and office rush hours. "
            "Targeted signal-timing optimisation and heavy-vehicle anti-idling enforcement "
            "reduce corridor pollutant concentrations by 10% to 20%."
        ),
        department="Traffic Police Branch and BMC Roads Dept",
        sop=(
            "Station traffic marshals at 2 or more identified congestion junctions; "
            "activate adaptive signal cycle if TMC system is available; "
            "issue penalties to heavy vehicles idling more than 3 minutes near schools or hospitals."
        ),
        compliance_checkpoint=(
            "Junction-level traffic flow log submitted to zone traffic DCP within 1 hour of rush-window conclusion; "
            "penalty tally reported to ward officer."
        ),
        severity="low",
    ),
    BaselineMitigation(
        card_id_suffix="swm_vigilance",
        action_title="Refuse and Biomass Burning Vigilance Squad",
        time_window="Evening patrol window 18:00 to 22:00 (post-market hours)",
        rationale=(
            "Open burning of municipal solid waste and biomass (dry leaves, packaging) "
            "is the single largest controllable source of fine-particle pollution in Mumbai "
            "wards during calm evening conditions when the sea-to-land breeze slows. "
            "MCGM SWM squad patrols and immediate suppression are the primary intervention."
        ),
        department="BMC SWM Flying Squad (Ward level) and MCGM Environment Cell",
        sop=(
            "Deploy at least 1 SWM squad vehicle per sub-zone; inspect all secondary collection "
            "points, nalla edges, and vacant plots; extinguish open fires immediately with "
            "dry sand or extinguisher; log GPS coordinates and initiate SWM complaint on MCGM "
            "1916 portal within 30 minutes."
        ),
        compliance_checkpoint=(
            "Squad patrol log with geo-tagged fire incidents submitted to ward AO within 1 hour of patrol conclusion; "
            "repeat-offender plots flagged for next morning follow-up."
        ),
        severity="low",
    ),
    BaselineMitigation(
        card_id_suffix="met_inversion_advisory",
        action_title="Evening Meteorological Inversion Advisory",
        time_window="Sea-to-land breeze transition window (16:00 to 21:00)",
        rationale=(
            "Mumbai experiences an evening transition from the sea breeze to the land breeze "
            "between approximately 16:00 and 20:00. During this switch, wind speeds drop and "
            "a shallow temperature inversion traps pollutants near the ground, typically "
            "raising AQI by 15 to 40 points in coastal and low-lying wards. A proactive "
            "advisory enables sensitive groups to plan activities."
        ),
        department="MCGM Public Health Dept and IMD / SAFAR Liaison Cell",
        sop=(
            "Issue health advisory via WhatsApp or SMS to registered ward contacts within 60 minutes of inversion alert; "
            "advise outdoor exercise restriction for AQI-sensitive groups (children, elderly, "
            "cardiac or asthma patients); coordinate with SAFAR for next 3-hour nowcast update."
        ),
        compliance_checkpoint=(
            "Advisory dissemination receipt log (target at least 80% of registered contacts) "
            "confirmed within 90 minutes of alert issuance; SAFAR nowcast AQI cross-checked against live station reading every 2 hours."
        ),
        severity="low",
        advisory=True,
    ),
]



def build_baseline_cards(
    ctx: WardContext, forecast: dict | None,
    existing_priority_count: int,
) -> list[ActionCard]:
    """Standard ward mitigation cards. Always generated; the UI can show or hide them
    depending on whether live signal cards already cover the domain."""
    ward_slug = slugify(ctx.ward_id)
    cards: list[ActionCard] = []
    for bm in BASELINE_MITIGATIONS:
        # Enrich evidence with live ward numbers so it is never completely generic
        evidence: list[str] = []
        if ctx.aqi:
            evidence.append(f"Current ward AQI: {ctx.aqi:.0f} ({ctx.category})")
        if ctx.population:
            evidence.append(f"{ctx.population:,} residents exposed to ambient air quality conditions")
        if not evidence:
            evidence.append("Standard ward risk profile: Mumbai BMC operational schedule")

        cards.append(ActionCard(
            card_id=f"act-{ward_slug}-baseline-{bm.card_id_suffix}",
            rule_id=f"BASELINE_{bm.card_id_suffix.upper()}",
            signal=bm.card_id_suffix,
            severity=bm.severity,
            confidence="high",
            confidence_score=1.0,
            advisory=bm.advisory,
            estimated=False,
            simulated=False,
            action_title=bm.action_title,
            time_window=bm.time_window,
            rationale=bm.rationale,
            evidence=evidence,
            forecast_without_action=forecast,
            source_reference=None,
            source_verified=False,
            priority_score=0.0,
            summary=f"{bm.action_title}. Standard operational mitigation. When: {bm.time_window}.",
            department=bm.department,
            sop=bm.sop,
            compliance_checkpoint=format_dynamic_checkpoint(bm.compliance_checkpoint),
            baseline=True,
        ))
    return cards


def _max_severity(a: str, b: str | None) -> str:
    if b is None:
        return a
    return a if SEVERITY_WEIGHT[a] >= SEVERITY_WEIGHT[b] else b


def evaluate_ward(ctx: WardContext, ruleset: RuleSet, include_signals: bool = False) -> WardResult:
    factor = _distance_factor(ctx.station_distance_km)
    is_estimated = ctx.station_distance_km is None or ctx.station_distance_km > ESTIMATED_DISTANCE_KM
    ward_slug = slugify(ctx.ward_id)
    forecast = forecast_without_action(ctx)

    cards: list[ActionCard] = []
    signal_log: list[dict] = []
    for rule in ruleset.rules:
        if not rule.enabled:
            continue
        params = {**DEFAULT_PARAMS[rule.signal], **rule.params}
        signal = DETECTORS[rule.signal](ctx, params)
        score = signal.confidence * (factor if signal.station_dependent else 1.0)
        label = confidence_label(score)
        card_made = signal.fired and confidence_rank(label) >= confidence_rank(rule.min_confidence)
        if include_signals:
            signal_log.append({
                "rule_id": rule.id, "signal": rule.signal, "fired": signal.fired,
                "card_created": card_made,
                "confidence": label if signal.fired else None,
                "evidence": list(signal.evidence),
            })
        if not card_made:
            continue
        severity = _max_severity(rule.severity, signal.severity_hint)
        evidence = list(signal.evidence)
        priority = 0.0 if rule.advisory else (
            SEVERITY_WEIGHT[severity] * ctx.population * (ctx.aqi / 100.0))
        detailed_rationale = generate_action_reasoning(
            ward_name=ctx.ward_name,
            ward_id=ctx.ward_id,
            population=ctx.population,
            aqi=ctx.aqi,
            category=ctx.category,
            signal=rule.signal,
            action_title=rule.action_title,
            evidence=evidence,
            time_window=rule.time_window,
            baseline_rationale=rule.rationale,
        )
        time_window = signal.details.get("dynamic_window") or rule.time_window
        checkpoint = format_dynamic_checkpoint(rule.compliance_checkpoint)
        cards.append(ActionCard(
            card_id=f"act-{ward_slug}-{rule.id.lower()}",
            rule_id=rule.id, signal=rule.signal, severity=severity,
            confidence=label, confidence_score=round(score, 3),
            advisory=rule.advisory,
            estimated=is_estimated and signal.station_dependent,
            simulated=bool(signal.details.get("simulated")),
            action_title=rule.action_title, time_window=time_window,
            rationale=detailed_rationale, evidence=evidence,
            forecast_without_action=forecast,
            source_reference=rule.source_reference if rule.source_verified else None,
            source_verified=rule.source_verified,
            priority_score=priority,
            summary=render_summary(rule.action_title, evidence, time_window, label,
                                   simulated=bool(signal.details.get("simulated"))),
            department=rule.department,
            sop=rule.sop,
            compliance_checkpoint=checkpoint,
            baseline=False,
        ))

    cards.sort(key=lambda c: (c.advisory, -SEVERITY_WEIGHT[c.severity], -c.confidence_score))
    # Append baseline mitigation cards (always; UI may collapse them when live cards dominate)
    baseline_cards = build_baseline_cards(ctx, forecast, existing_priority_count=len([c for c in cards if not c.advisory]))
    cards.extend(baseline_cards)
    ward_priority = max((c.priority_score for c in cards), default=0.0)
    return WardResult(
        ward_id=ctx.ward_id, ward_name=ctx.ward_name, population=ctx.population,
        aqi=ctx.aqi, category=ctx.category,
        nearest_station=ctx.nearest_station_name,
        distance_to_station_km=None if ctx.station_distance_km is None else round(ctx.station_distance_km, 1),
        is_estimated=is_estimated, priority_score=ward_priority, cards=cards,
        signals=signal_log if include_signals else None,
    )


def evaluate_all(contexts: list[WardContext], ruleset: RuleSet | None = None,
                 include_signals: bool = False) -> list[WardResult]:
    rules = ruleset if ruleset is not None else get_ruleset()
    results = [evaluate_ward(ctx, rules, include_signals) for ctx in contexts]
    exposure = {c.ward_id: c.population * c.aqi for c in contexts}
    results.sort(key=lambda r: (-r.priority_score, -exposure.get(r.ward_id, 0.0)))
    return results