from __future__ import annotations
import argparse
import sys
import time
from datetime import timedelta
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.db import SessionLocal
from app.models.db_models import Station
from app.forecasting.baseline import seasonal_naive_forecast
from app.forecasting.sarima_model import fit_sarima, load_station_series, sarima_forecast, series_from_df
TEST_WINDOW_DAYS = 14
FORECAST_HORIZON_H = 24
MIN_TRAIN_RECORDS = 500

def _mae(errors: list[float]) -> float | None:
    return sum(errors) / len(errors) if errors else None

def evaluate_station(db, station_id: str, station_name: str, test_days: int=TEST_WINDOW_DAYS, min_records: int=MIN_TRAIN_RECORDS) -> dict | None:
    df = load_station_series(db, station_id)
    if not df.empty and df['ds'].max().year >= 2025 and ((df['ds'] < '2025-01-01').sum() >= min_records):
        df = df[df['ds'] < '2025-01-01'].copy()
    if len(df) < min_records:
        print(f'  {station_name}: only {len(df)} records - skipping (need >= {min_records})')
        return None
    test_start = df['ds'].max() - timedelta(days=test_days)
    n_test = (df['ds'] > test_start).sum()
    if n_test < FORECAST_HORIZON_H:
        print(f'  {station_name}: only {n_test} test points - skipping')
        return None
    print(f'\n  {station_name}')
    print(f'    train up to {test_start.date()}  |  test: last {test_days} days  ({n_test} pts)')
    baseline_errs, sarima_errs = ([], [])
    current_origin = test_start
    step = 0
    while current_origin + timedelta(hours=FORECAST_HORIZON_H) <= df['ds'].max():
        window_end = current_origin + timedelta(hours=FORECAST_HORIZON_H)
        train_df = df[df['ds'] <= current_origin]
        test_window = df[(df['ds'] > current_origin) & (df['ds'] <= window_end)]
        if len(test_window) == 0 or len(train_df) < MIN_TRAIN_RECORDS:
            current_origin = window_end
            continue
        step += 1
        ts_list = list(test_window['ds'])
        t0 = time.perf_counter()
        try:
            s_series = series_from_df(train_df, window_days=14)
            sfit = fit_sarima(s_series)
            s_preds = sarima_forecast(sfit, steps=len(ts_list))
            s_map = dict(zip(ts_list, s_preds))
            s_ok = True
        except Exception as exc:
            print(f'    [step {step}] SARIMA error: {exc}')
            s_map, s_ok = ({}, False)
        sarima_fit_s = time.perf_counter() - t0
        print(f'    step {step:2d}: {current_origin.date()} -> {window_end.date()} | {len(test_window):3d} pts | SARIMA {sarima_fit_s:.2f}s')
        for _, row in test_window.iterrows():
            actual, ts = (row['y'], row['ds'])
            b = seasonal_naive_forecast(db, station_id, ts)
            if b is not None:
                baseline_errs.append(abs(b - actual))
            if s_ok:
                s = s_map.get(ts)
                if s is not None:
                    sarima_errs.append(abs(s - actual))
        current_origin = window_end
    b_mae = _mae(baseline_errs)
    s_mae = _mae(sarima_errs)
    return {'station': station_name, 'baseline_mae': b_mae, 'sarima_mae': s_mae, 'gain': b_mae - s_mae if b_mae is not None and s_mae is not None else None, 'n': len(sarima_errs)}

def _winner(r: dict) -> str:
    b = r['baseline_mae']
    s = r['sarima_mae']
    if b is None or s is None:
        return 'N/A'
    return 'SARIMA' if s <= b else 'Baseline'

def main():
    parser = argparse.ArgumentParser(description='Walk-forward forecasting evaluation: Baseline vs SARIMA')
    parser.add_argument('--days', type=int, default=TEST_WINDOW_DAYS, help='Test window in days (default 14, use 7 for faster run)')
    parser.add_argument('--station', type=str, default=None, help='Evaluate only this station_id')
    parser.add_argument('--min-records', type=int, default=MIN_TRAIN_RECORDS, help='Minimum training records required (default 500)')
    args = parser.parse_args()
    test_days = args.days
    min_records = args.min_records
    db = SessionLocal()
    stations = db.query(Station).all()
    if args.station:
        stations = [s for s in stations if s.station_id == args.station]
        if not stations:
            print(f"Station '{args.station}' not found in DB.")
            db.close()
            return
    print('\nWalk-forward forecast evaluation (Baseline vs SARIMA)')
    print(f'  Test window : last {test_days} days per station')
    print(f'  Horizon     : {FORECAST_HORIZON_H} h (retrain every {FORECAST_HORIZON_H} h)')
    print(f'  Stations    : {len(stations)}\n')
    results = []
    for s in stations:
        r = evaluate_station(db, s.station_id, s.name, test_days=test_days, min_records=min_records)
        if r:
            results.append(r)
    db.close()
    if not results:
        print('\nNo stations had sufficient data to evaluate.')
        return
    hdr = f"\n{'Station':<45} {'Baseline MAE':>13} {'SARIMA MAE':>13} {'Gain':>8} {'N':>5} {'Winner':>10}"
    print(hdr)
    print('-' * 100)
    for r in results:
        w = _winner(r)
        b = f"{r['baseline_mae']:.2f}" if r['baseline_mae'] is not None else 'N/A'
        sa = f"{r['sarima_mae']:.2f}" if r['sarima_mae'] is not None else 'N/A'
        gain = f"{r['gain']:+.2f}" if r['gain'] is not None else 'N/A'
        row = f"{r['station']:<45} {b:>13} {sa:>13} {gain:>8} {r['n']:>5} {w:>10}"
        print(row)
    print()
    wins = {'Baseline': 0, 'SARIMA': 0}
    for r in results:
        wins[_winner(r)] += 1
    print(f"  Wins - Baseline: {wins['Baseline']}  |  SARIMA: {wins['SARIMA']}")
    all_b = [r['baseline_mae'] for r in results if r['baseline_mae']]
    all_s = [r['sarima_mae'] for r in results if r['sarima_mae']]
    if all_b and all_s:
        avg_b = sum(all_b) / len(all_b)
        avg_s = sum(all_s) / len(all_s)
        avg_gain = avg_b - avg_s
        print(f'  Avg MAE - Baseline: {avg_b:.2f}  |  SARIMA: {avg_s:.2f}  |  Avg Gain: {avg_gain:+.2f} pts')
    print()
if __name__ == '__main__':
    main()
