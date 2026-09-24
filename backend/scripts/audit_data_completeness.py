import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.db import SessionLocal
from app.models.db_models import Station, StationAQI

def main():
    db = SessionLocal()
    stations = db.query(Station).order_by(Station.name).all()
    print(f"{'Station':<45} {'Records':>8} {'OK':>5} {'Insuf.':>7} {'First':>17} {'Last':>17}")
    print('-' * 105)
    total_records = 0
    stations_with_zero_data = []
    for station in stations:
        records = db.query(StationAQI).filter_by(station_id=station.station_id).order_by(StationAQI.timestamp).all()
        count = len(records)
        total_records += count
        if count == 0:
            stations_with_zero_data.append(station.name)
            print(f"{station.name:<45} {0:>8} {'-':>5} {'-':>7} {'-':>17} {'-':>17}")
            continue
        ok_count = sum((1 for r in records if r.status == 'ok'))
        insufficient_count = count - ok_count
        first_ts = records[0].timestamp.strftime('%Y-%m-%d %H:%M')
        last_ts = records[-1].timestamp.strftime('%Y-%m-%d %H:%M')
        print(f'{station.name:<45} {count:>8} {ok_count:>5} {insufficient_count:>7} {first_ts:>17} {last_ts:>17}')
    print('-' * 105)
    print(f'\nTotal AQI records across all stations: {total_records}')
    print(f'Stations with zero data yet: {len(stations_with_zero_data)} of {len(stations)}')
    if stations_with_zero_data:
        print("  (These have been seeded but ingestion hasn't run for them yet, or every")
        print('   record so far happened to be a duplicate/skip.)')
        for name in stations_with_zero_data:
            print(f'   - {name}')
    MIN_RECORDS_FOR_EVAL = 5
    eligible = [s for s in stations if db.query(StationAQI).filter_by(station_id=s.station_id).count() >= MIN_RECORDS_FOR_EVAL]
    print(f'\nStations with >= {MIN_RECORDS_FOR_EVAL} records (eligible for evaluation): {len(eligible)} of {len(stations)}')
    db.close()
if __name__ == '__main__':
    main()
