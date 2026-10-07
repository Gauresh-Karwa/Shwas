from dataclasses import dataclass
from datetime import datetime, timedelta
import requests

BASE_URL = 'https://api.gdeltproject.org/api/v2/doc/doc'
AQ_RELEVANT_TERMS = (
    '("stubble burning" OR "farm fire" OR wildfire OR smog OR '
    '"air quality" OR pollution OR firecracker)'
)

# Simple in-process TTL cache: key → (results, expires_at)
_cache: dict[str, tuple[list, datetime]] = {}
_CACHE_TTL = timedelta(minutes=5)


_cooldown_until: datetime = datetime.min


@dataclass
class NewsResult:
    title: str
    url: str
    domain: str
    seen_date: str


def search_air_quality_news(
    area_name: str = 'Mumbai',
    timespan: str = '1d',
    max_records: int = 5,
) -> list[NewsResult]:
    global _cooldown_until
    cache_key = f"{area_name}:{timespan}:{max_records}"

    # Return cached results if still fresh
    if cache_key in _cache:
        cached_results, expires_at = _cache[cache_key]
        if datetime.utcnow() < expires_at:
            return cached_results

    # If currently in rate-limit cooldown, return stale cache or empty list
    if datetime.utcnow() < _cooldown_until:
        if cache_key in _cache:
            return _cache[cache_key][0]
        return []

    query = f'"{area_name}" {AQ_RELEVANT_TERMS} sourcecountry:IN'
    params = {
        'query': query,
        'mode': 'ArtList',
        'maxrecords': max_records,
        'format': 'json',
        'timespan': timespan,
        'sort': 'DateDesc',
    }

    try:
        response = requests.get(BASE_URL, params=params, timeout=15)
        if response.status_code == 429:
            _cooldown_until = datetime.utcnow() + timedelta(minutes=5)
            if cache_key in _cache:
                return _cache[cache_key][0]
            return []
        response.raise_for_status()
        data = response.json()
    except (requests.exceptions.RequestException, ValueError) as e:
        if hasattr(e, 'response') and getattr(e.response, 'status_code', None) == 429:
            _cooldown_until = datetime.utcnow() + timedelta(minutes=5)
        else:
            print(f'GDELT news search notice: {type(e).__name__}: {e}')
        # Return stale cache on failure rather than empty, if available
        if cache_key in _cache:
            return _cache[cache_key][0]
        return []

    articles = data.get('articles', [])
    results = [
        NewsResult(
            title=a.get('title', ''),
            url=a.get('url', ''),
            domain=a.get('domain', ''),
            seen_date=a.get('seendate', ''),
        )
        for a in articles
    ]

    # Store in cache
    _cache[cache_key] = (results, datetime.utcnow() + _CACHE_TTL)
    return results
