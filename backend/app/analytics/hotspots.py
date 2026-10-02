"""
Confidence-gated hotspot detection: ranks land-masked grid points by a
lower confidence bound (LCB) on AQI, not the raw point estimate, so a
high AQI number that's really just MC-dropout noise doesn't get flagged
alongside a reading the model is actually confident about.

    LCB(p) = mean_aqi(p) - z * std(p)

IMPORTANT CALIBRATION CAVEAT, stated plainly rather than implied away:
treating z=1.96 as "the 95% bound" assumes the GNN's MC-dropout std is a
calibrated Gaussian uncertainty. That has NOT been confirmed against real
data — scripts/evaluate_uncertainty_calibration.py exists specifically to
check this empirical coverage, and it has not yet been run against this
project's live Postgres data as of this code being written. Until that
script reports a real coverage number close to 95%, treat "lcb" as a
confidence-ADJUSTED estimate, not a statistically verified bound — the
field is named accordingly (lcb, not confirmed_floor or similar) and
callers should surface it the same way.

Points that fell back to IDW (no std available) are still reported, but
flagged method="idw" with lcb == aqi (no correction applied, since there
is no uncertainty estimate to subtract) rather than silently dropped —
an IDW-only hotspot is still worth knowing about, just without the same
confidence framing as a GNN-confirmed one.
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.aqi.calculator import CATEGORY_BANDS
from app.analytics.grid_scan import DEFAULT_MC_SAMPLES, scan_grid

DEFAULT_Z = 1.96


def _category_for(aqi: float) -> str:
    for _, high, name in CATEGORY_BANDS:
        if aqi <= high:
            return name
    return "Severe"


@dataclass
class HotspotCandidate:
    lat: float
    lon: float
    ward_id: str
    ward_name: str
    population: int
    estimated_aqi: float
    uncertainty_std: float | None
    lcb: float
    lcb_category: str
    method: str  # "gnn" (lcb is confidence-adjusted) or "idw" (lcb == aqi)


def detect_hotspots(
    db: Session,
    threshold: float = 100.0,
    z: float = DEFAULT_Z,
    step_km: float = 2.0,
    mc_samples: int = DEFAULT_MC_SAMPLES,
) -> list[HotspotCandidate]:
    grid = scan_grid(db, step_km=step_km, mc_samples=mc_samples)

    candidates = []
    for point in grid:
        if point.std is not None:
            lcb = max(0.0, point.aqi - z * point.std)
        else:
            lcb = point.aqi  # no uncertainty estimate to subtract

        if lcb < threshold:
            continue

        candidates.append(
            HotspotCandidate(
                lat=point.lat,
                lon=point.lon,
                ward_id=point.ward_id,
                ward_name=point.ward_name,
                population=point.population,
                estimated_aqi=point.aqi,
                uncertainty_std=point.std,
                lcb=round(lcb, 1),
                lcb_category=_category_for(lcb),
                method=point.method,
            )
        )

    candidates.sort(key=lambda c: c.lcb, reverse=True)
    return candidates
