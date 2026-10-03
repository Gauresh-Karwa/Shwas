from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.attribution.attribution_service import get_station_attribution
from app.analytics.source_apportionment import get_source_apportionment, get_city_apportionment

router = APIRouter(prefix="/api/attribution", tags=["attribution"])


@router.get("/city/apportionment")
def city_apportionment(db: Session = Depends(get_db)):
    return get_city_apportionment(db)


@router.get("/{station_id:path}/apportionment")
def station_apportionment(station_id: str, db: Session = Depends(get_db)):
    return get_source_apportionment(db, station_id)


@router.get("/{station_id:path}")
def station_attribution(station_id: str, db: Session = Depends(get_db)):
    try:
        return get_station_attribution(db, station_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
