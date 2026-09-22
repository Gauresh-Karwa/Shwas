import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.db import SessionLocal  
from app.models.db_models import Station, StationAQI  
from app.interpolation.idw import idw_interpolate 


def main():
    db = SessionLocal()
    stations = db.query(Station).all()

    station_data = []
    for s in stations:
        latest = db.query(StationAQI).filter_by(
            station_id=s.station_id, status="ok"
        ).order_by(StationAQI.timestamp.desc()).first()
        if latest:
            station_data.append((s.name, s.latitude, s.longitude, latest.aqi_value))

    db.close()

    print(f"Evaluating against {len(station_data)} stations with valid current AQI.\n")

    if len(station_data) < 3:
        print("Not enough stations with valid data to run a meaningful evaluation yet.")
        return

    errors = []
    print(f"{'Station':<45} {'Actual':>7} {'Predicted':>10} {'Error':>8} {'Confidence':>11}")
    print("-" * 90)

    for i, (name, lat, lon, actual_aqi) in enumerate(station_data):
        
        other_points = [(s_lat, s_lon, s_aqi) for j, (_, s_lat, s_lon, s_aqi) in enumerate(station_data) if j != i]

        result = idw_interpolate(lat, lon, other_points)
        if result is None:
            continue

        error = result.estimated_aqi - actual_aqi
        errors.append(error)
        print(f"{name:<45} {actual_aqi:>7} {result.estimated_aqi:>10} {error:>+8.1f} {result.confidence:>11}")

    if not errors:
        print("No evaluable predictions.")
        return

    mae = sum(abs(e) for e in errors) / len(errors)
    rmse = (sum(e ** 2 for e in errors) / len(errors)) ** 0.5

    print("-" * 90)
    print(f"\nMean Absolute Error (MAE):  {mae:.2f} AQI points")
    print(f"Root Mean Squared Error (RMSE): {rmse:.2f} AQI points")
    print(f"\nFor reference: CPCB's own AQI categories are ~50-100 points wide")
    print(f"(e.g. Good=0-50, Satisfactory=51-100), so an MAE well under that")
    print(f"range means the baseline is usually landing in the right category,")
    print(f"even when the exact number differs.")


if __name__ == "__main__":
    main()