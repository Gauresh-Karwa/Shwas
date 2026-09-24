import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.db import SessionLocal
from app.models.db_models import Station, StationFeature, StationAQI

def pearson_correlation(x: list[float], y: list[float]) -> float | None:
    n = len(x)
    if n < 3:
        return None
    mean_x, mean_y = (sum(x) / n, sum(y) / n)
    cov = sum(((xi - mean_x) * (yi - mean_y) for xi, yi in zip(x, y)))
    std_x = sum(((xi - mean_x) ** 2 for xi in x)) ** 0.5
    std_y = sum(((yi - mean_y) ** 2 for yi in y)) ** 0.5
    if std_x == 0 or std_y == 0:
        return None
    return cov / (std_x * std_y)

def main():
    db = SessionLocal()
    stations = db.query(Station).all()
    rows = []
    for s in stations:
        feature = db.query(StationFeature).filter_by(station_id=s.station_id).first()
        latest_aqi = db.query(StationAQI).filter_by(station_id=s.station_id, status='ok').order_by(StationAQI.timestamp.desc()).first()
        if feature and latest_aqi:
            rows.append((s.name, feature.distance_to_water_km, feature.distance_to_green_km, latest_aqi.aqi_value))
    db.close()
    print(f"{'Station':<45} {'Water(km)':>10} {'Green(km)':>10} {'AQI':>6}")
    print('-' * 75)
    for name, water, green, aqi in rows:
        water_str = f'{water:.2f}' if water is not None else 'none/>5km'
        green_str = f'{green:.2f}' if green is not None else 'none/>5km'
        print(f'{name:<45} {water_str:>10} {green_str:>10} {aqi:>6}')
    water_pairs = [(w, a) for _, w, g, a in rows if w is not None]
    green_pairs = [(g, a) for _, w, g, a in rows if g is not None]
    print(f'\nStations with a water distance AND valid AQI: {len(water_pairs)} of {len(rows)}')
    print(f'Stations with a green distance AND valid AQI: {len(green_pairs)} of {len(rows)}')
    if water_pairs:
        r_water = pearson_correlation([w for w, a in water_pairs], [a for w, a in water_pairs])
        print(f'\nCorrelation (distance to water vs. AQI): {r_water}')
        print('  (positive = farther from water tends to mean HIGHER AQI, i.e. water helps)')
    else:
        print('\nNot enough water-distance data to compute a correlation.')
    if green_pairs:
        r_green = pearson_correlation([g for g, a in green_pairs], [a for g, a in green_pairs])
        print(f'\nCorrelation (distance to green space vs. AQI): {r_green}')
        print('  (positive = farther from green space tends to mean HIGHER AQI, i.e. green space helps)')
    else:
        print('\nNot enough green-distance data to compute a correlation.')
    print("\nCAVEAT: small sample size, and some 'none/>5km' values may actually be")
    print("Overpass timeouts misread as 'not found' - treat this as a rough first")
    print('look, not a final verdict either way.')
if __name__ == '__main__':
    main()
