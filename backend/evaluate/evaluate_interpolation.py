import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.db import SessionLocal
from app.models.db_models import Station, StationAQI
from app.interpolation.idw import idw_interpolate
from app.attribution.weather_client import get_wind_data, compass_direction
from app.config import settings

def main():
    db = SessionLocal()
    stations = db.query(Station).all()
    station_data = []
    for s in stations:
        latest = db.query(StationAQI).filter_by(station_id=s.station_id, status='ok').order_by(StationAQI.timestamp.desc()).first()
        if latest:
            station_data.append((s.name, s.latitude, s.longitude, latest.aqi_value))
    db.close()
    print(f'\nEvaluating against {len(station_data)} stations with valid current AQI.')
    if len(station_data) < 3:
        print('Not enough stations with valid data to evaluate yet.')
        return
    CITY_CENTRE = (19.047, 72.874)
    wind = None
    if settings.OPENWEATHERMAP_API_KEY:
        print('Fetching current wind data (city centre)...', end=' ', flush=True)
        wind = get_wind_data(*CITY_CENTRE, settings.OPENWEATHERMAP_API_KEY)
        if wind:
            print(f'{wind.speed_mps:.1f} m/s from {compass_direction(wind.direction_deg)} ({wind.direction_deg}°)')
        else:
            print('failed — will use plain IDW only.')
    else:
        print('OWM_API_KEY not set — will use plain IDW only.')
    wind_speed = wind.speed_mps if wind else None
    wind_deg = wind.direction_deg if wind else None
    idw_errors = []
    widw_errors = []
    col_w = 47
    print(f"\n{'Station':<{col_w}} {'Actual':>7} {'IDW':>6} {'W-IDW':>7} {'ΔIDW':>6} {'ΔW-IDW':>7}")
    print('─' * (col_w + 40))
    for i, (name, lat, lon, actual_aqi) in enumerate(station_data):
        other = [(s_lat, s_lon, s_aqi) for j, (_, s_lat, s_lon, s_aqi) in enumerate(station_data) if j != i]
        plain = idw_interpolate(lat, lon, other)
        wwind = idw_interpolate(lat, lon, other, wind_speed_mps=wind_speed, wind_from_deg=wind_deg)
        if plain is None:
            continue
        err_idw = plain.estimated_aqi - actual_aqi
        err_widw = wwind.estimated_aqi - actual_aqi if wwind else float('nan')
        idw_errors.append(err_idw)
        if wwind:
            widw_errors.append(err_widw)
        widw_str = f'{wwind.estimated_aqi:>7.1f}' if wwind else '     N/A'
        werr_str = f'{err_widw:>+7.1f}' if wwind else '     N/A'
        print(f'{name:<{col_w}} {actual_aqi:>7} {plain.estimated_aqi:>6.1f} {widw_str} {err_idw:>+6.1f} {werr_str}')

    def mae_rmse(errors):
        if not errors:
            return (float('nan'), float('nan'))
        mae = sum((abs(e) for e in errors)) / len(errors)
        rmse = (sum((e ** 2 for e in errors)) / len(errors)) ** 0.5
        return (mae, rmse)
    idw_mae, idw_rmse = mae_rmse(idw_errors)
    widw_mae, widw_rmse = mae_rmse(widw_errors)
    print('─' * (col_w + 40))
    print(f"\n{'Metric':<25}  {'Plain IDW':>12}  {'Wind-IDW':>10}  {'Improvement':>12}")
    print(f"{'MAE (AQI pts)':<25}  {idw_mae:>12.2f}  {widw_mae:>10.2f}  {idw_mae - widw_mae:>+12.2f}")
    print(f"{'RMSE (AQI pts)':<25}  {idw_rmse:>12.2f}  {widw_rmse:>10.2f}  {idw_rmse - widw_rmse:>+12.2f}")
    print(f'\nNote: CPCB AQI categories are ~50 points wide — an MAE well below')
    print(f'that means the model usually lands in the correct category.')
    if wind:
        print(f'\nWind correction active: {wind.speed_mps:.1f} m/s from {compass_direction(wind.direction_deg)} — alpha=0.6')
    else:
        print('\nWind correction inactive (no API key or fetch failed).')
if __name__ == '__main__':
    main()
