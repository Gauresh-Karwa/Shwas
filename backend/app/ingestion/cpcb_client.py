import time

import requests

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
    last_error = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = session.get(url, params=params, timeout=READ_TIMEOUT)
            response.raise_for_status()
            return response.json()
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
            last_error = e
            print(f"  Attempt {attempt}/{MAX_RETRIES} failed ({type(e).__name__}), "
                  f"retrying in {RETRY_BACKOFF_SECONDS}s")
            time.sleep(RETRY_BACKOFF_SECONDS)
    raise last_error


def fetch_city_data(base_url: str, resource_id: str, api_key: str, city: str) -> list:
    url = f"{base_url}/{resource_id}"
    all_records = []
    offset = 0

    while True:
        params = {
            "api-key": api_key,
            "format": "json",
            "limit": PAGE_SIZE,
            "offset": offset,
            "filters[city]": city,
        }
        payload = fetch_page(url, params)
        batch = payload.get("records", [])
        all_records.extend(batch)

        total = int(payload.get("total", 0))
        offset += PAGE_SIZE
        if offset >= total or not batch:
            break

    return all_records