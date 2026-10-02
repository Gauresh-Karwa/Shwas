"""
FastAPI router for the attribution and source apportionment endpoints.

Routes
------
GET /api/attribution/{station_id}
    Multi-modal causal attribution: wind, fires, urban morphology, Gemini narrative.

GET /api/attribution/{station_id}/apportionment
    PM2.5/PM10 fine-fraction source classification for a single station.

GET /api/attribution/city/apportionment
    City-wide PM2.5/PM10 classification summary across all active stations.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.attribution.attribution_service import get_station_attribution
from app.analytics.source_apportionment import get_source_apportionment, get_city_apportionment

router = APIRouter(prefix="/api/attribution", tags=["attribution"])


@router.get("/city/apportionment")
def city_apportionment(db: Session = Depends(get_db)):
    """
    City-wide PM2.5/PM10 combustion-vs-dust source classification.

    Returns a summary of how many Mumbai stations fall into each source
    category over the last 24 hours, plus per-station breakdowns.

    Source types:
    - `combustion_dominated` — PM2.5/PM10 ratio >= 0.65 (vehicle exhaust, refinery flue gas, biomass)
    - `mixed`                — ratio 0.40 to 0.65 (urban background)
    - `dust_dominated`       — ratio <= 0.40 (road dust, construction, sea spray)
    - `insufficient_data`    — fewer than one PM2.5+PM10 pair in the last 24 hours
    """
    return get_city_apportionment(db)


@router.get("/{station_id}/apportionment")
def station_apportionment(station_id: str, db: Session = Depends(get_db)):
    """
    PM2.5/PM10 fine-fraction source apportionment for a single station.

    Returns the rolling 24-hour fine fraction, combustion-vs-dust
    classification, and a plain-English interpretation of the dominant
    pollution source.
    """
    return get_source_apportionment(db, station_id)


@router.get("/{station_id}")
def station_attribution(station_id: str, db: Session = Depends(get_db)):
    """
    Multi-modal causal attribution for a station.

    Assembles current wind conditions (OpenWeatherMap), nearby active fires
    (NASA FIRMS VIIRS), pre-computed urban morphology distance (OSM), and
    generates a single-sentence Gemini citizen narrative explaining why
    air quality is at its current level.

    All external data sources are best-effort: if a provider is offline,
    the corresponding `drivers` field is `null` and the remaining fields
    are unaffected.

    Returns 404 if the station_id is not in the database.
    Returns 503 if no AQI reading exists yet for the station.
    """
    try:
        return get_station_attribution(db, station_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
