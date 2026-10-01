from __future__ import annotations
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import requests

from app.db import SessionLocal
from app.models.db_models import WardBoundary, WardPopulation

WARDS_GEOJSON_URL = "https://bharatlas.com/api/dl/admin/wards-mumbai/wards_mumbai.geojson"
CENSUS_YEAR = 2011

WARD_POPULATION = [
    ("A", "Colaba", 185014, 12.5),
    ("B", "Sandhurst Road", 127290, 2.5),
    ("C", "Marine Lines", 166161, 1.8),
    ("D", "Grant Road", 346866, 6.6),
    ("E", "Byculla", 393286, 7.4),
    ("F/N", "Matunga", 529034, 13.0),
    ("F/S", "Parel", 360972, 14.0),
    ("G/N", "Dadar/Plaza", 377749, 9.1),
    ("G/S", "Elphinstone", 599039, 10.0),
    ("H/E", "Khar/Santacruz", 307581, 13.5),
    ("H/W", "Bandra", 557239, 11.6),
    ("K/E", "Andheri (East)", 823885, 24.8),
    ("K/W", "Andheri (West)", 748688, 23.4),
    ("L", "Kurla", 902225, 15.9),
    ("M/E", "Chembur", 807720, 32.5),
    ("M/W", "Chembur (West)", 411893, 19.5),
    ("N", "Ghatkopar", 622853, 26.0),
    ("P/N", "Malad", 941366, 19.1),
    ("P/S", "Goregaon", 463507, 24.4),
    ("R/C", "Borivali", 562162, 50.0),
    ("R/N", "Dahisar", 431368, 18.0),
    ("R/S", "Kandivali", 691229, 17.8),
    ("S", "Bhandup", 743783, 64.0),
    ("T", "Mulund", 341463, 45.4),
]


def swap_lat_lon(geometry: dict) -> dict:
    gtype = geometry["type"]

    def fix_ring(ring):
        return [[pt[1], pt[0]] for pt in ring]

    if gtype == "Polygon":
        return {"type": "Polygon", "coordinates": [fix_ring(r) for r in geometry["coordinates"]]}
    if gtype == "MultiPolygon":
        return {
            "type": "MultiPolygon",
            "coordinates": [[fix_ring(r) for r in polygon] for polygon in geometry["coordinates"]],
        }
    raise ValueError(f"Unexpected ward geometry type: {gtype!r}")


def fetch_ward_boundaries() -> dict[str, dict]:
    print(f"Downloading ward boundaries from {WARDS_GEOJSON_URL} ...")
    response = requests.get(WARDS_GEOJSON_URL, timeout=60)
    response.raise_for_status()
    data = response.json()

    boundaries: dict[str, dict] = {}
    for feature in data["features"]:
        raw_name = feature["properties"].get("Name") or feature["properties"].get("NAME2") or ""
        ward_id = raw_name.strip()
        if not ward_id:
            print(f"  Skipping a feature with no usable ward name: {feature['properties']}")
            continue
        boundaries[ward_id] = swap_lat_lon(feature["geometry"])
    print(f"  Parsed {len(boundaries)} ward boundaries: {sorted(boundaries)}")
    return boundaries


def main(force: bool = False) -> None:
    boundaries = fetch_ward_boundaries()
    population_by_ward = {row[0]: row for row in WARD_POPULATION}

    missing_population = sorted(set(boundaries) - set(population_by_ward))
    missing_boundary = sorted(set(population_by_ward) - set(boundaries))
    if missing_population:
        print(f"WARNING: no population figure for wards: {missing_population} — "
              f"these will get a boundary but no population row.")
    if missing_boundary:
        print(f"WARNING: no boundary found for wards with population data: {missing_boundary} — "
              f"these will be skipped entirely.")

    db = SessionLocal()
    boundaries_written = populations_written = skipped = 0

    for ward_id, geometry in boundaries.items():
        existing = db.query(WardBoundary).filter_by(ward_id=ward_id).first()
        pop_row = population_by_ward.get(ward_id)
        ward_name = pop_row[1] if pop_row else ward_id

        if existing and not force:
            skipped += 1
        else:
            if existing:
                existing.ward_name = ward_name
                existing.geometry = geometry
            else:
                db.add(WardBoundary(ward_id=ward_id, ward_name=ward_name, geometry=geometry))
            boundaries_written += 1

        if pop_row:
            _, _, population, _area_km2 = pop_row
            existing_pop = db.query(WardPopulation).filter_by(ward_id=ward_id).first()
            if existing_pop and not force:
                pass
            elif existing_pop:
                existing_pop.population = population
                existing_pop.census_year = CENSUS_YEAR
                populations_written += 1
            else:
                db.add(WardPopulation(ward_id=ward_id, population=population, census_year=CENSUS_YEAR))
                populations_written += 1

    db.commit()
    db.close()
    print(f"\nDone. Boundaries written/updated: {boundaries_written}, "
          f"skipped (already present, use --force to overwrite): {skipped}. "
          f"Populations written/updated: {populations_written}.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed Mumbai ward boundaries and Census 2011 population.")
    parser.add_argument("--force", action="store_true", help="Overwrite existing ward rows.")
    args = parser.parse_args()
    main(force=args.force)