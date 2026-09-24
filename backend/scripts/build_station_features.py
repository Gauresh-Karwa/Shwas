import sys
import time
import argparse
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.db import SessionLocal
from app.models.db_models import Station, StationFeature
from app.attribution.overpass_client import compute_station_geo_features

def main(force: bool=False) -> None:
    db = SessionLocal()
    stations = db.query(Station).all()
    mode = 'recomputing all' if force else 'skipping already-computed'
    print(f'Computing geo-features for {len(stations)} stations ({mode}).')
    print('Overpass is a free shared public service — queries are deliberately slow.\n')
    computed = skipped = 0
    for i, station in enumerate(stations, 1):
        existing = db.query(StationFeature).filter_by(station_id=station.station_id).first()
        if existing and (not force):
            print(f'[{i}/{len(stations)}] {station.name}: already computed, skipping.')
            skipped += 1
            continue
        print(f'[{i}/{len(stations)}] {station.name}: querying Overpass...')
        features = compute_station_geo_features(station.latitude, station.longitude)
        print(f'    → water: {features.distance_to_water_km} km')
        if existing:
            existing.distance_to_water_km = features.distance_to_water_km
        else:
            db.add(StationFeature(station_id=station.station_id, distance_to_water_km=features.distance_to_water_km))
        db.commit()
        computed += 1
        time.sleep(3)
    db.close()
    print(f'\nDone. Computed: {computed}, Skipped: {skipped}.')
if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Build station geo-features from OpenStreetMap.')
    parser.add_argument('--force', action='store_true', help='Recompute and overwrite rows even for stations that already have data.')
    args = parser.parse_args()
    main(force=args.force)
