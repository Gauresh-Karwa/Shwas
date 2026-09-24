import sys
import argparse
import random
import math
from pathlib import Path
from datetime import datetime
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import torch
import torch.nn as nn
import torch.optim as optim
from torch.optim.lr_scheduler import CosineAnnealingLR
from app.db import SessionLocal
from app.models.db_models import Station, StationAQI
from app.ml.gnn_model import SpatialGNN, AQI_MAX, normalise_lat, normalise_lon, temporal_encoding
MODELS_DIR = Path(__file__).resolve().parent.parent / 'models'
CHECKPOINT = MODELS_DIR / 'gnn_checkpoint.pt'
BEST_MODEL = MODELS_DIR / 'gnn_best.pt'
TRAIN_CUTOFF = datetime(2020, 1, 1)
VAL_CUTOFF = datetime(2020, 7, 1)
MIN_STATIONS_PER_STEP = 4

def load_dataset() -> dict[datetime, list[tuple[str, float, float, float]]]:
    db = SessionLocal()
    stations = {s.station_id: (s.latitude, s.longitude) for s in db.query(Station).all()}
    rows = db.query(StationAQI).filter(StationAQI.status == 'ok').all()
    db.close()
    by_ts: dict[datetime, list] = {}
    for row in rows:
        if row.aqi_value is None:
            continue
        if row.station_id not in stations:
            continue
        lat, lon = stations[row.station_id]
        by_ts.setdefault(row.timestamp, []).append((row.station_id, lat, lon, float(row.aqi_value)))
    return {ts: entries for ts, entries in by_ts.items() if len(entries) >= MIN_STATIONS_PER_STEP}

def split_dataset(data: dict):
    train, val, test = ({}, {}, {})
    for ts, entries in data.items():
        ts_dt = ts if isinstance(ts, datetime) else datetime.fromisoformat(str(ts))
        if ts_dt < TRAIN_CUTOFF:
            train[ts] = entries
        elif ts_dt < VAL_CUTOFF:
            val[ts] = entries
        else:
            test[ts] = entries
    return (train, val, test)

def get_lag_aqi(station_id: str, ts: datetime, all_data: dict, hours: int) -> float | None:
    from datetime import timedelta
    lag_ts = ts - timedelta(hours=hours)
    entries = all_data.get(lag_ts)
    if entries:
        for sid, _, _, aqi in entries:
            if sid == station_id:
                return aqi
    return None

def make_batch(entries: list[tuple[str, float, float, float]], mask_idx: int, ts: datetime, all_data: dict) -> tuple[torch.Tensor, list[float], list[float], float]:
    ts_dt = ts if isinstance(ts, datetime) else datetime.fromisoformat(str(ts))
    hs, hc, ws, wc = temporal_encoding(ts_dt.hour, ts_dt.weekday())
    lats, lons, feats = ([], [], [])
    target = 0.0
    for i, (sid, lat, lon, aqi) in enumerate(entries):
        is_masked = i == mask_idx
        aqi_norm = 0.0 if is_masked else aqi / AQI_MAX
        if is_masked:
            lag1_norm = 0.0
            lag3_norm = 0.0
        else:
            lag1 = get_lag_aqi(sid, ts_dt, all_data, hours=1)
            lag3 = get_lag_aqi(sid, ts_dt, all_data, hours=3)
            lag1_norm = lag1 / AQI_MAX if lag1 is not None else aqi_norm
            lag3_norm = lag3 / AQI_MAX if lag3 is not None else aqi_norm
        feats.append([normalise_lat(lat), normalise_lon(lon), aqi_norm, lag1_norm, lag3_norm, hs, hc, ws, wc])
        lats.append(lat)
        lons.append(lon)
        if is_masked:
            target = aqi / AQI_MAX
    return (torch.tensor(feats, dtype=torch.float32), lats, lons, target)

def run_epoch(model: SpatialGNN, data: dict, all_data: dict, criterion: nn.Module, optimiser: optim.Optimizer | None, device: torch.device, max_steps: int=2000) -> float:
    is_train = optimiser is not None
    model.train(is_train)
    timestamps = list(data.keys())
    if len(timestamps) > max_steps:
        timestamps = random.sample(timestamps, max_steps)
    total_loss = 0.0
    n = 0
    with torch.set_grad_enabled(is_train):
        for ts in timestamps:
            entries = data[ts]
            mask_idx = random.randint(0, len(entries) - 1)
            feats, lats, lons, target = make_batch(entries, mask_idx, ts, all_data)
            feats = feats.to(device)
            preds = model(feats, lats, lons)
            pred_target = preds[mask_idx, 0]
            loss = criterion(pred_target, torch.tensor(target, device=device))
            if is_train:
                optimiser.zero_grad()
                loss.backward()
                nn.utils.clip_grad_norm_(model.parameters(), max_norm=1.0)
                optimiser.step()
            total_loss += loss.item()
            n += 1
    return total_loss / n if n > 0 else float('inf')

def main():
    parser = argparse.ArgumentParser(description='Train Spatial GNN for AQI interpolation')
    parser.add_argument('--epochs', type=int, default=50)
    parser.add_argument('--lr', type=float, default=0.0003)
    parser.add_argument('--resume', action='store_true', help='Resume from checkpoint')
    parser.add_argument('--k', type=int, default=5, help='k-NN neighbours')
    parser.add_argument('--train-steps', type=int, default=2000, help='Time steps sampled per epoch')
    args = parser.parse_args()
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    print(f'Device: {device}')
    print('Loading dataset from DB...')
    all_data = load_dataset()
    train_data, val_data, test_data = split_dataset(all_data)
    print(f'  Train: {len(train_data):,} time steps  |  Val: {len(val_data):,}  |  Test (held-out): {len(test_data):,}')
    if len(train_data) == 0:
        print("ERROR: No training data found. Make sure station_aqi table has rows with status='ok'.")
        sys.exit(1)
    model = SpatialGNN(k_neighbours=args.k).to(device)
    criterion = nn.MSELoss()
    optimiser = optim.Adam(model.parameters(), lr=args.lr, weight_decay=1e-05)
    scheduler = CosineAnnealingLR(optimiser, T_max=args.epochs, eta_min=1e-06)
    start_epoch = 0
    best_val_loss = float('inf')
    if args.resume and CHECKPOINT.exists():
        ckpt = torch.load(CHECKPOINT, map_location=device)
        model.load_state_dict(ckpt['model'])
        optimiser.load_state_dict(ckpt['optimiser'])
        start_epoch = ckpt['epoch'] + 1
        best_val_loss = ckpt.get('best_val_loss', float('inf'))
        print(f"Resumed from epoch {ckpt['epoch']} (best val loss: {best_val_loss:.5f})")
    print(f'\nTraining for {args.epochs} epochs (sampling {args.train_steps} steps/epoch)...\n')
    print(f"{'Epoch':>6}  {'Train MSE':>10}  {'Train RMSE':>10}  {'Val MSE':>10}  {'Val RMSE':>10}  {'LR':>10}")
    print('-' * 65)
    for epoch in range(start_epoch, start_epoch + args.epochs):
        train_loss = run_epoch(model, train_data, all_data, criterion, optimiser, device, args.train_steps)
        val_loss = run_epoch(model, val_data, all_data, criterion, None, device, min(len(val_data), 500))
        scheduler.step()
        train_rmse = math.sqrt(train_loss) * AQI_MAX
        val_rmse = math.sqrt(val_loss) * AQI_MAX
        lr_now = optimiser.param_groups[0]['lr']
        print(f'{epoch + 1:>6}  {train_loss:>10.5f}  {train_rmse:>9.2f}  {val_loss:>10.5f}  {val_rmse:>9.2f}  {lr_now:>10.2e}')
        torch.save({'epoch': epoch, 'model': model.state_dict(), 'optimiser': optimiser.state_dict(), 'best_val_loss': best_val_loss, 'k': args.k}, CHECKPOINT)
        if val_loss < best_val_loss:
            best_val_loss = val_loss
            torch.save(model.state_dict(), BEST_MODEL)
            print(f'         ↳ New best val RMSE: {val_rmse:.2f} AQI — saved to {BEST_MODEL.name}')
    print(f'\nDone. Best val RMSE: {math.sqrt(best_val_loss) * AQI_MAX:.2f} AQI points.')
    print(f'Run  python scripts/evaluate_gnn.py  to compare against IDW baseline.')
if __name__ == '__main__':
    main()
