from dataclasses import dataclass
import requests
BASE_URL = 'https://api.gdeltproject.org/api/v2/doc/doc'
AQ_RELEVANT_TERMS = '("stubble burning" OR "farm fire" OR wildfire OR smog OR "air quality" OR pollution OR firecracker)'

@dataclass
class NewsResult:
    title: str
    url: str
    domain: str
    seen_date: str

def search_air_quality_news(area_name: str='Mumbai', timespan: str='1d', max_records: int=5) -> list[NewsResult]:
    query = f'"{area_name}" {AQ_RELEVANT_TERMS} sourcecountry:IN'
    params = {'query': query, 'mode': 'ArtList', 'maxrecords': max_records, 'format': 'json', 'timespan': timespan, 'sort': 'DateDesc'}
    try:
        response = requests.get(BASE_URL, params=params, timeout=15)
        response.raise_for_status()
        data = response.json()
    except (requests.exceptions.RequestException, ValueError) as e:
        print(f'GDELT news search failed: {type(e).__name__}: {e}')
        return []
    articles = data.get('articles', [])
    return [NewsResult(title=a.get('title', ''), url=a.get('url', ''), domain=a.get('domain', ''), seen_date=a.get('seendate', '')) for a in articles]
