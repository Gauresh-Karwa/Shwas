"""
Waste-burning detector.

Flags likely open burning of waste at known dumping grounds by combining
three pieces of evidence you already collect:

  1. NASA FIRMS satellite fire hits close to the dump site
  2. A PM2.5 spike at the nearest CPCB station(s) (last 3 h vs previous 24 h)
  3. A high fine-fraction (PM2.5/PM10 >= 0.65) = combustion signature

Each site gets a score 0-100 and a level: likely / possible / watch / none.
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_
from sqlalchemy.orm import Session

from app.analytics.source_apportionment import PM25_IDS, get_source_apportionment
from app.attribution.fire_client import get_nearby_fires
from app.config import settings
from app.interpolation.idw import haversine_km
from app.models.db_models import CleanedReading, Station

# Approximate coordinates - please verify on Google Maps before final demo.
DUMP_SITES = [
    {"site_id": "deonar",     "name": "Deonar Dumping Ground",     "lat": 19.0535, "lon": 72.9250},
    {"site_id": "mulund",     "name": "Mulund Dumping Ground",     "lat": 19.1730, "lon": 72.9680},
    {"site_id": "kanjurmarg", "name": "Kanjurmarg Dumping Ground", "lat": 19.1156, "lon": 72.9393},
    {"site_id": "gorai",      "name": "Gorai Dumping Ground",      "lat": 19.2270, "lon": 72.7870},
]

FIRE_RADIUS_KM = 3.0        # a fire this close to a dump counts as "at the dump"
STATION_RADIUS_KM = 10.0    # stations considered for PM evidence
MAX_STATIONS = 3
SPIKE_RATIO = 1.5           # recent PM2.5 / baseline PM2.5
RECENT_HOURS = 3
BASELINE_HOURS = 24
COMBUSTION_FRACTION = 0.65
CACHE_TTL_SECONDS = 600     # 10 minutes, protects NASA FIRMS from repeated calls

_cache: dict[bool, tuple[float, list[dict]]] = {}


def score_evidence(
    fire_count: int,
    max_frp_mw: float | None,
    spike_ratio: float | None,
    fine_fraction: float | None,
) -> tuple[int, str, list[str]]:
    """Pure function (no DB, no network): evidence in, score/level/reasons out."""
    score = 0
    reasons: list[str] = []

    if fire_count > 0:
        score += 50
        reasons.append(f"{fire_count} satellite fire detection(s) near the dump site")
        if max_frp_mw is not None and max_frp_mw >= 5:
            score += 10
            reasons.append(f"strong fire intensity ({max_frp_mw:.1f} MW)")

    if spike_ratio is not None and spike_ratio >= SPIKE_RATIO:
        score += 25
        reasons.append(f"PM2.5 is {spike_ratio:.1f}x above its 24 h normal at the nearest station")

    if fine_fraction is not None and fine_fraction >= COMBUSTION_FRACTION:
        score += 15
        reasons.append(f"fine-particle fraction {fine_fraction:.2f} points to combustion")

    if score >= 70:
        level = "likely"
    elif score >= 50:
        level = "possible"
    elif score >= 25:
        level = "watch"
    else:
        level = "none"

    if not reasons:
        reasons.append("no fire or pollution evidence right now")
    return score, level, reasons


def _mean_pm25(db: Session, station_id: str, start: datetime, end: datetime) -> float | None:
    rows = (
        db.query(CleanedReading.avg_value)
        .filter(
            and_(
                CleanedReading.station_id == station_id,
                CleanedReading.pollutant_id.in_(PM25_IDS),
                CleanedReading.avg_value.isnot(None),
                CleanedReading.avg_value > 0,
                CleanedReading.timestamp >= start,
                CleanedReading.timestamp < end,
            )
        )
        .all()
    )
    values = [r[0] for r in rows]
    return sum(values) / len(values) if values else None


def _nearby_stations(db: Session, lat: float, lon: float):
    found = []
    for s in db.query(Station).all():
        if s.latitude is None or s.longitude is None:
            continue
        d = haversine_km(lat, lon, s.latitude, s.longitude)
        if d <= STATION_RADIUS_KM:
            found.append((d, s))
    found.sort(key=lambda x: x[0])
    return found[:MAX_STATIONS]


def _fires_at_site(site: dict) -> list:
    if not settings.FIRMS_MAP_KEY:
        return []
    try:
        fires = get_nearby_fires(settings.FIRMS_MAP_KEY, site["lat"], site["lon"], radius_deg=0.1)
    except Exception:
        return []
    return [f for f in fires if f.distance_km <= FIRE_RADIUS_KM]


def _analyse_site(db: Session, site: dict, now: datetime) -> dict:
    fires = _fires_at_site(site)
    max_frp = max((f.frp_mw for f in fires), default=None)

    best = None  # station with the biggest PM2.5 spike
    for dist, st in _nearby_stations(db, site["lat"], site["lon"]):
        recent = _mean_pm25(db, st.station_id, now - timedelta(hours=RECENT_HOURS), now)
        baseline = _mean_pm25(
            db, st.station_id,
            now - timedelta(hours=BASELINE_HOURS + RECENT_HOURS),
            now - timedelta(hours=RECENT_HOURS),
        )
        if recent is None or baseline is None or baseline <= 0:
            continue
        ratio = recent / baseline
        if best is None or ratio > best["ratio"]:
            best = {"station": st, "dist": dist, "recent": recent, "baseline": baseline, "ratio": ratio}

    fine_fraction = None
    if best is not None:
        try:
            fine_fraction = get_source_apportionment(db, best["station"].station_id).get("fine_fraction")
        except Exception:
            fine_fraction = None

    score, level, reasons = score_evidence(
        len(fires), max_frp, best["ratio"] if best else None, fine_fraction
    )
    return {
        "site_id": site["site_id"],
        "name": site["name"],
        "lat": site["lat"],
        "lon": site["lon"],
        "level": level,
        "score": score,
        "reasons": reasons,
        "fire_count": len(fires),
        "max_frp_mw": round(max_frp, 1) if max_frp is not None else None,
        "nearest_station": best["station"].name if best else None,
        "station_distance_km": round(best["dist"], 1) if best else None,
        "pm25_recent": round(best["recent"], 1) if best else None,
        "pm25_baseline": round(best["baseline"], 1) if best else None,
        "spike_ratio": round(best["ratio"], 2) if best else None,
        "fine_fraction": fine_fraction,
        "simulated": False,
    }


def _simulate(site_result: dict) -> dict:
    """Demo helper: pretend Deonar is burning, clearly labelled as simulated."""
    score, level, reasons = score_evidence(2, 8.4, 2.1, 0.71)
    site_result.update(
        level=level, score=score, reasons=reasons, fire_count=2, max_frp_mw=8.4,
        spike_ratio=2.1, fine_fraction=0.71, simulated=True,
    )
    return site_result


def detect_waste_burning(db: Session, simulate: bool = False) -> list[dict]:
    cached = _cache.get(simulate)
    if cached and time.time() - cached[0] < CACHE_TTL_SECONDS:
        return cached[1]

    now = datetime.now(tz=timezone.utc).replace(tzinfo=None)  # DB stores naive UTC
    results = []
    for site in DUMP_SITES:
        try:
            res = _analyse_site(db, site, now)
        except Exception:
            res = {
                "site_id": site["site_id"], "name": site["name"],
                "lat": site["lat"], "lon": site["lon"], "level": "none", "score": 0,
                "reasons": ["data unavailable right now"], "fire_count": 0,
                "max_frp_mw": None, "nearest_station": None, "station_distance_km": None,
                "pm25_recent": None, "pm25_baseline": None, "spike_ratio": None,
                "fine_fraction": None, "simulated": False,
            }
        if simulate and site["site_id"] == "deonar":
            res = _simulate(res)
        results.append(res)

    results.sort(key=lambda r: r["score"], reverse=True)
    _cache[simulate] = (time.time(), results)
    return results