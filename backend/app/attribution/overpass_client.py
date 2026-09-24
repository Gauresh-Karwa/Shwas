import time
from dataclasses import dataclass
import requests
OVERPASS_URL = 'https://overpass-api.de/api/interpreter'
HEADERS = {'User-Agent': 'Shwas-AQI-App/1.0 (github.com/Gauresh-Karwa/Shwas; educational project)'}
SEARCH_RADII_M = [250, 500, 1000, 2000, 3000, 5000]
WATER_TAGS = ['["natural"="water"]', '["waterway"="river"]']
QUERY_FAILED = -1
_RETRYABLE_STATUS = {429, 504}
_MAX_RETRIES = 3
_RETRY_BACKOFF = [10, 20, 40]

def _count_features_within(lat: float, lon: float, radius_m: int, tag_filters: list[str]) -> int:
    clauses = ''.join((f'nwr{tag}(around:{radius_m},{lat},{lon});' for tag in tag_filters))
    query = f'[out:json][timeout:25];({clauses});out count;'
    for attempt in range(_MAX_RETRIES):
        try:
            response = requests.post(OVERPASS_URL, data={'data': query}, headers=HEADERS, timeout=30)
            response.raise_for_status()
            data = response.json()
            elements = data.get('elements', [])
            if not elements:
                return 0
            total = elements[0].get('tags', {}).get('total', '0')
            return int(total)
        except requests.exceptions.HTTPError as e:
            status = e.response.status_code if e.response is not None else None
            if status in _RETRYABLE_STATUS and attempt < _MAX_RETRIES - 1:
                wait = _RETRY_BACKOFF[attempt]
                print(f'    Overpass {status} at r={radius_m}m (attempt {attempt + 1}/{_MAX_RETRIES}), retrying in {wait}s...')
                time.sleep(wait)
                continue
            print(f'    Overpass query failed ({type(e).__name__}: {e}) after {attempt + 1} attempt(s), marking radius as unreliable.')
            return QUERY_FAILED
        except (requests.exceptions.RequestException, ValueError, KeyError, IndexError) as e:
            print(f'    Overpass query failed ({type(e).__name__}: {e}) after {attempt + 1} attempt(s), marking radius as unreliable.')
            return QUERY_FAILED
    return QUERY_FAILED

def _nearest_feature_band_km(lat: float, lon: float, tag_filters: list[str]) -> float | None:
    for radius_m in SEARCH_RADII_M:
        count = _count_features_within(lat, lon, radius_m, tag_filters)
        if count == QUERY_FAILED:
            time.sleep(5)
            continue
        if count > 0:
            return radius_m / 1000
        time.sleep(2)
    return None

@dataclass
class StationGeoFeatures:
    distance_to_water_km: float | None

def compute_station_geo_features(lat: float, lon: float) -> StationGeoFeatures:
    water_band = _nearest_feature_band_km(lat, lon, WATER_TAGS)
    return StationGeoFeatures(distance_to_water_km=water_band)
