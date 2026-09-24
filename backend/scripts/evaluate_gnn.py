import sys
import argparse
import math
import random
from pathlib import Path
from datetime import datetime
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import torch
from app.db import SessionLocal
from app.models.db_models import Station, StationAQI
from app.interpolation.idw import idw_interpolate
from app.ml.gnn_model import SpatialGNN, AQI_MAX, normalise_lat, normalise_lon, temporal_encoding, gnn_interpolate
from scripts.train_gnn import get_lag_aqi, TRAIN_CUTOFF, VAL_CUTOFF
MODELS_DIR = Path(__file__).resolve().parent.parent / 'models'
BEST_MODEL = MODELS_DIR / 'gnn_best.pt'
TEST_CUTOFF = VAL_CUTOFF
VAL_START = TRAIN_CUTOFF
MAX_EVAL_STEPS = 1000

def load_test_data(use_val: bool=False) -> dict:
    db = SessionLocal()
    stations = {s.station_id: (s.latitude, s.longitude) for s in db.query(Station).all()}
    q = db.query(StationAQI).filter(StationAQI.status == 'ok')
    if use_val:
        q = q.filter(StationAQI.timestamp >= VAL_START, StationAQI.timestamp < TEST_CUTOFF)
    else:
        q = q.filter(StationAQI.timestamp >= TEST_CUTOFF)
    rows = q.all()
    db.close()
    by_ts: dict[datetime, list] = {}
    for row in rows:
        if row.aqi_value is None or row.station_id not in stations:
            continue
        lat, lon = stations[row.station_id]
        by_ts.setdefault(row.timestamp, []).append((row.station_id, lat, lon, float(row.aqi_value)))
    return {ts: entries for ts, entries in by_ts.items() if len(entries) >= 4}

def load_full_context() -> dict:
    db = SessionLocal()
    stations = {s.station_id: (s.latitude, s.longitude) for s in db.query(Station).all()}
    rows = db.query(StationAQI).filter(StationAQI.status == 'ok').all()
    db.close()
    by_ts: dict[datetime, list] = {}
    for row in rows:
        if row.aqi_value is None or row.station_id not in stations:
            continue
        lat, lon = stations[row.station_id]
        by_ts.setdefault(row.timestamp, []).append((row.station_id, lat, lon, float(row.aqi_value)))
    return by_ts

def evaluate(model: SpatialGNN | None, test_data: dict, full_context: dict, device: torch.device, max_steps: int=MAX_EVAL_STEPS):
    timestamps = list(test_data.keys())
    if len(timestamps) > max_steps:
        timestamps = random.sample(timestamps, max_steps)
    idw_errors, gnn_errors = ([], [])
    worst_gnn = []
    for ts in timestamps:
        entries = test_data[ts]
        ts_dt = ts if isinstance(ts, datetime) else datetime.fromisoformat(str(ts))
        hour, weekday = (ts_dt.hour, ts_dt.weekday())
        for i, (sid, lat, lon, actual_aqi) in enumerate(entries):
            other = [(e[1], e[2], e[3]) for j, e in enumerate(entries) if j != i]
            if len(other) < 3:
                continue
            idw_result = idw_interpolate(lat, lon, other)
            if idw_result:
                idw_errors.append(abs(idw_result.estimated_aqi - actual_aqi))
            if model is not None:
                s_lats = [e[1] for j, e in enumerate(entries) if j != i]
                s_lons = [e[2] for j, e in enumerate(entries) if j != i]
                s_aqis = [e[3] for j, e in enumerate(entries) if j != i]
                sids = [e[0] for j, e in enumerate(entries) if j != i]
                s_aqis_1h = [get_lag_aqi(sid_, ts_dt, full_context, 1) for sid_ in sids]
                s_aqis_3h = [get_lag_aqi(sid_, ts_dt, full_context, 3) for sid_ in sids]
                gnn_pred = gnn_interpolate(model, lat, lon, s_lats, s_lons, s_aqis, hour, weekday, station_aqis_1h=s_aqis_1h, station_aqis_3h=s_aqis_3h, device=device)
                err = abs(gnn_pred - actual_aqi)
                gnn_errors.append(err)
                worst_gnn.append((err, sid, actual_aqi, gnn_pred, ts))
    return (idw_errors, gnn_errors, sorted(worst_gnn, reverse=True)[:5])

def print_results(idw_errors, gnn_errors, worst_cases):

    def stats(errors):
        if not errors:
            return (float('nan'), float('nan'))
        mae = sum(errors) / len(errors)
        rmse = math.sqrt(sum((e ** 2 for e in errors)) / len(errors))
        return (mae, rmse)
    idw_mae, idw_rmse = stats(idw_errors)
    gnn_mae, gnn_rmse = stats(gnn_errors)
    print('\n' + '=' * 60)
    print('  Interpolation Model Comparison — Test Set')
    print('=' * 60)
    print(f"  {'Metric':<20}  {'IDW (baseline)':>16}  {'GNN':>10}")
    print(f"  {'-' * 20}  {'-' * 16}  {'-' * 10}")
    print(f"  {'MAE (AQI pts)':<20}  {idw_mae:>16.2f}  {gnn_mae:>10.2f}")
    print(f"  {'RMSE (AQI pts)':<20}  {idw_rmse:>16.2f}  {gnn_rmse:>10.2f}")
    print(f"  {'Samples':<20}  {len(idw_errors):>16,}  {len(gnn_errors):>10,}")
    print('=' * 60)
    if gnn_errors:
        delta_mae = idw_mae - gnn_mae
        delta_rmse = idw_rmse - gnn_rmse
        if delta_mae > 0:
            print(f'\n  GNN improves MAE by  {delta_mae:+.2f} AQI pts ({delta_mae / idw_mae * 100:.1f}%)')
            print(f'  GNN improves RMSE by {delta_rmse:+.2f} AQI pts ({delta_rmse / idw_rmse * 100:.1f}%)')
            print('  Recommendation: use GNN as primary interpolator.')
        else:
            print(f'\n  GNN does NOT beat IDW (delta MAE = {delta_mae:+.2f})')
            print('  Recommendation: keep IDW as primary interpolator.')
    if worst_cases:
        print('\n  Top-5 worst GNN errors:')
        print(f"  {'Station ID':<40}  {'Actual':>7}  {'GNN Pred':>9}  {'Error':>7}")
        print('  ' + '-' * 70)
        for err, sid, actual, pred, ts in worst_cases:
            print(f'  {sid:<40}  {actual:>7.1f}  {pred:>9.1f}  {err:>7.1f}')
    print()

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--ckpt', type=str, default=str(BEST_MODEL))
    parser.add_argument('--max-steps', type=int, default=MAX_EVAL_STEPS)
    parser.add_argument('--eval-val', action='store_true', help='Evaluate on the validation set (Jan–Jun 2020) instead of the test set. Use this when test set has < 50 timesteps.')
    args = parser.parse_args()
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    ckpt_path = Path(args.ckpt)
    model = None
    if ckpt_path.exists():
        print(f'Loading GNN from {ckpt_path} ...')
        model = SpatialGNN().to(device)
        state = torch.load(ckpt_path, map_location=device)
        if isinstance(state, dict) and 'model' in state:
            model.load_state_dict(state['model'])
        else:
            model.load_state_dict(state)
        model.eval()
    else:
        print(f'No GNN checkpoint found at {ckpt_path} — will evaluate IDW only.')
    split_label = 'validation (Jan–Jun 2020)' if args.eval_val else 'test (Jul 2020+)'
    print(f'Loading {split_label} data from DB...')
    test_data = load_test_data(use_val=args.eval_val)
    print(f'  {len(test_data):,} time steps (capped at {args.max_steps})')
    if len(test_data) < 10:
        print(f'\nOnly {len(test_data)} timesteps in test set — too few for reliable evaluation.\n   Run with --eval-val to evaluate on the larger validation set instead:\n   python scripts/evaluate_gnn.py --eval-val\n')
        if not test_data:
            return
    print('Loading full historical context for lag lookups...')
    full_context = load_full_context()
    print(f'  {len(full_context):,} total timesteps in lag context')
    print('Running leave-one-out evaluation...\n')
    idw_errors, gnn_errors, worst = evaluate(model, test_data, full_context, device, args.max_steps)
    print_results(idw_errors, gnn_errors, worst)
if __name__ == '__main__':
    main()
