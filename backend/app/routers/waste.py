from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.analytics.waste_burning import detect_waste_burning
from app.db import get_db

router = APIRouter(prefix="/api", tags=["waste"])


@router.get("/waste/burning")
def waste_burning(
    simulate: bool = Query(False, description="Demo mode: pretend Deonar is burning"),
    db: Session = Depends(get_db),
):
    sites = detect_waste_burning(db, simulate=simulate)
    flagged = [s for s in sites if s["level"] in ("likely", "possible")]
    return {
        "checked_at": datetime.now(tz=timezone.utc).isoformat(),
        "simulated": simulate,
        "flagged_count": len(flagged),
        "sites": sites,
    }