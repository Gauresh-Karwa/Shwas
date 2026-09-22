import csv
import io
from dataclasses import dataclass
from datetime import datetime

import requests

from app.interpolation.idw import haversine_km

BASE_URL = "https://firms.modaps.eosdis.nasa.gov/api/area/csv"

MIN_FRP_MW = 1.0
ACCEPTED_CONFIDENCE = {"n", "h"} 


@dataclass
class FireDetection:
    latitude: float
    longitude: float
    distance_km: float
    acquired_at: datetime
    frp_mw: float
    confidence: str


def get_nearby_fires(
    map_key: str, center_lat: float, center_lon: float,
    radius_deg: float = 0.5, sensor: str = "VIIRS_SNPP_NRT", days: int = 1,
) -> list[FireDetection]:
    
    west = center_lon - radius_deg
    south = center_lat - radius_deg
    east = center_lon + radius_deg
    north = center_lat + radius_deg
    bbox = f"{west},{south},{east},{north}"

    url = f"{BASE_URL}/{map_key}/{sensor}/{bbox}/{days}"

    try:
        response = requests.get(url, timeout=20)
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        print(f"NASA FIRMS request failed: {type(e).__name__}: {e}")
        return []

    reader = csv.DictReader(io.StringIO(response.text))
    detections = []

    for row in reader:
        try:
            confidence = row["confidence"].strip().lower()
            frp = float(row["frp"])
        except (KeyError, ValueError):
            continue  

        if confidence not in ACCEPTED_CONFIDENCE:
            continue
        if frp < MIN_FRP_MW:
            continue

        lat, lon = float(row["latitude"]), float(row["longitude"])
        distance = haversine_km(center_lat, center_lon, lat, lon)

        acquired_at = datetime.strptime(
            f"{row['acq_date']} {row['acq_time']}", "%Y-%m-%d %H%M"
        )

        detections.append(FireDetection(
            latitude=lat, longitude=lon, distance_km=round(distance, 1),
            acquired_at=acquired_at, frp_mw=frp, confidence=confidence,
        ))

    detections.sort(key=lambda d: d.distance_km)
    return detections