import sys
from pathlib import Path
import pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.db import SessionLocal
from app.models.db_models import Station, RawReading, StationAQI
DATA_DIR = Path(__file__).resolve().parent.parent.parent / 'data' / 'historical'
KAGGLE_TO_LIVE_STATION_ID = {'MH006': 'borivali-east-mumbai-mpcb', 'MH007': 'chhatrapati-shivaji-intl-airport-t2-mumbai-mpcb', 'MH009': 'kurla-mumbai-mpcb', 'MH010': 'powai-mumbai-mpcb', 'MH011': 'sion-mumbai-mpcb', 'MH014': 'worli-mumbai-mpcb'}
POLLUTANT_COLUMN_MAP = {'PM2.5': 'PM2.5', 'PM10': 'PM10', 'NO2': 'NO2', 'NH3': 'NH3', 'CO': 'CO', 'SO2': 'SO2', 'O3': 'OZONE'}

def main():
    hourly_path = DATA_DIR / 'mumbai_station_hour.csv'
    if not hourly_path.exists():
        print(f'File not found: {hourly_path}')
        sys.exit(1)
    df = pd.read_csv(hourly_path)
    df['Datetime'] = pd.to_datetime(df['Datetime'])
    df = df[df['StationId'].isin(KAGGLE_TO_LIVE_STATION_ID.keys())]
    print(f'Rows to process (confirmed-mapping stations only): {len(df)}')
    db = SessionLocal()
    for kaggle_id, station_id in KAGGLE_TO_LIVE_STATION_ID.items():
        if not db.query(Station).filter_by(station_id=station_id).first():
            print(f"ERROR: station_id '{station_id}' (for {kaggle_id}) not found in stations table.")
            print('Add it via seed_stations.py first.')
            db.close()
            sys.exit(1)
    raw_written = 0
    raw_skipped = 0
    aqi_written = 0
    aqi_skipped = 0
    for _, row in df.iterrows():
        station_id = KAGGLE_TO_LIVE_STATION_ID[row['StationId']]
        timestamp = row['Datetime'].to_pydatetime()
        for kaggle_col, pollutant_id in POLLUTANT_COLUMN_MAP.items():
            value = row.get(kaggle_col)
            if pd.isna(value):
                continue
            exists = db.query(RawReading).filter_by(station_id=station_id, pollutant_id=pollutant_id, timestamp=timestamp).first()
            if exists:
                raw_skipped += 1
                continue
            db.add(RawReading(station_id=station_id, pollutant_id=pollutant_id, min_value=float(value), max_value=float(value), avg_value=float(value), timestamp=timestamp))
            raw_written += 1
        aqi_exists = db.query(StationAQI).filter_by(station_id=station_id, timestamp=timestamp).first()
        if aqi_exists:
            aqi_skipped += 1
            continue
        aqi_value = row.get('AQI')
        category = row.get('AQI_Bucket')
        if pd.isna(aqi_value):
            db.add(StationAQI(station_id=station_id, timestamp=timestamp, aqi_value=None, status='insufficient_data', reason='Kaggle historical row had no AQI value for this hour.'))
        else:
            db.add(StationAQI(station_id=station_id, timestamp=timestamp, aqi_value=int(aqi_value), status='ok', category=category if not pd.isna(category) else None, dominant_pollutant=None, reason=None))
        aqi_written += 1
    db.commit()
    db.close()
    print(f'\nRaw readings written: {raw_written}, skipped (duplicates): {raw_skipped}')
    print(f'AQI records written: {aqi_written}, skipped (duplicates): {aqi_skipped}')
if __name__ == '__main__':
    main()
