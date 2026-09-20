import sys
from pathlib import Path
import pandas as pd 

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "historical"

def load_mumbai_subset() -> pd.DataFrame:
    stations_path = DATA_DIR / "stations.csv"
    hourly_path = DATA_DIR / "station_hour.csv"

    if not stations_path.exists() or not hourly_path.exists():
        print(f"Expected files not found in {DATA_DIR}")
        print("Download station_hour.csv and stations.csv from the Kaggle")
        sys.exit(1)

    stations = pd.read_csv(stations_path)
    hourly = pd.read_csv(hourly_path)

    mumbai_station_ids = stations.loc[
        stations["City"] == "Mumbai", "StationId"
    ].tolist()

    if not mumbai_station_ids:
        print("No Mumbai stations found in stations.csv, check the City")
        sys.exit(1)

    mumbai_hourly = hourly[hourly["StationId"].isin(mumbai_station_ids)].copy()
    mumbai_hourly["Datetime"] = pd.to_datetime(mumbai_hourly["Datetime"])

    return mumbai_hourly

def main():
    df = load_mumbai_subset()
    print(f"Loaded {len(df)} hourly records across {df['StationId'].nunique()} Mumbai stations")
    print(f"Date range: {df['Datetime'].min()} to {df['Datetime'].max()}")
    print(f"Columns: {list(df.columns)}")

    out_path = DATA_DIR / "mumbai_station_hour.csv"
    df.to_csv(out_path, index=False)
    print(f"Saved filtered subset to: {out_path}")

if __name__ == "__main__":
    main()