"""
Manual CPCB data injector — use when api.data.gov.in is unreachable.

Usage:
  1. Open this URL on your phone / browser on a different network:
     https://api.data.gov.in/resource/3b01bcb8-0b14-4abf-b6f2-c1bfd384ba69?api-key=579b464db66ec23bdd0000019498ed5a56b9458471fbd9db14d89cb1&format=json&limit=500&filters[city]=Mumbai

  2. Save the JSON response to a file (e.g. cpcb_latest.json)

  3. Run:
     python scripts/inject_cpcb_json.py path/to/cpcb_latest.json
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.ingestion.pipeline import run_ingestion_cycle


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    path = Path(sys.argv[1])
    if not path.exists():
        print(f"ERROR: file not found: {path}")
        sys.exit(1)

    data = json.loads(path.read_text(encoding="utf-8"))
    records = data.get("records", data)  # handle both {records: [...]} and bare list
    if not isinstance(records, list):
        print("ERROR: expected a JSON object with a 'records' key, or a bare JSON array.")
        sys.exit(1)

    print(f"Injecting {len(records)} records from {path.name} ...")
    summary = run_ingestion_cycle(records=records)
    print("\nSummary:")
    for k, v in summary.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
