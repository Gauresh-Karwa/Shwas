import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.config import settings  # noqa: E402

PAGE_SIZE = 100
READ_TIMEOUT = 60
MAX_RETRIES = 3
RETRY_BACKOFF_SECONDS = 5

session = requests.Session()
session.headers.update({
    "User-Agent": "curl/8.21.0",
    "Accept": "*/*",
})


def fetch_page(url: str, params: dict) -> dict:
    """Fetch one page, retrying on timeout/connection errors with backoff."""
    last_error = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = session.get(url, params=params, timeout=READ_TIMEOUT)
            response.raise_for_status()
            return response.json()
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
            last_error = e
            print(f"  Attempt {attempt}/{MAX_RETRIES} failed ({type(e).__name__}), "
                  f"retrying in {RETRY_BACKOFF_SECONDS}s...")
            time.sleep(RETRY_BACKOFF_SECONDS)
    raise last_error


def fetch_city_data(city: str) -> dict:
    """Fetch all currently-reported records for a city, paginating in small pages."""
    url = f"{settings.CPCB_BASE_URL}/{settings.CPCB_RESOURCE_ID}"
    all_records = []
    offset = 0
    final_payload = None

    while True:
        params = {
            "api-key": settings.CPCB_API_KEY,
            "format": "json",
            "limit": PAGE_SIZE,
            "offset": offset,
            "filters[city]": city,
        }
        print(f"Fetching offset={offset} (page size {PAGE_SIZE})...")
        payload = fetch_page(url, params)
        final_payload = payload

        batch = payload.get("records", [])
        all_records.extend(batch)
        print(f"  Got {len(batch)} records (running total: {len(all_records)})")

        total = int(payload.get("total", 0))
        offset += PAGE_SIZE
        if offset >= total or not batch:
            break

    final_payload["records"] = all_records
    final_payload["count"] = len(all_records)
    return final_payload


def main():
    missing = settings.validate()
    if missing:
        print(f"Missing required settings: {missing}. Check your .env file.")
        sys.exit(1)

    city = settings.TARGET_CITY
    print(f"Fetching live CPCB data for {city}...")
    data = fetch_city_data(city)

    stations = sorted({r["station"] for r in data["records"]})
    print(f"\nTotal records: {data['count']}")
    print(f"Distinct stations reporting: {len(stations)}")
    for s in stations:
        print(f"  - {s}")

    out_dir = Path(__file__).resolve().parent.parent.parent / "data" / "raw"
    out_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = out_dir / f"cpcb_{city.lower()}_{timestamp}.json"
    out_path.write_text(json.dumps(data, indent=2))
    print(f"\nSaved raw sample to: {out_path}")


if __name__ == "__main__":
    main()