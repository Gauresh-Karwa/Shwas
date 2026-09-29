from __future__ import annotations
import argparse
import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import torch

from app.db import SessionLocal
from app.forecasting.sarima_model import fit_sarima, load_station_series, sarima_forecast, series_from_df
from app.interpolation.idw import idw_interpolate
from app.ml.gnn_model import SpatialGNN, gnn_interpolate
from app.models.db_models import Station

MODELS_DIR = Path(__file__).resolve().parent.parent / "models"
BEST_MODEL = MODELS_DIR / "gnn_best.pt"
HORIZONS = [1, 6, 12, 24]
MIN_TRAIN_RECORDS = 500
METHODS = ("persistence", "direct_sarima", "idw_chain", "gnn_chain")


def _load_model():
    if not BEST_MODEL.exists():
        return None, None
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = SpatialGNN().to(device)
    state = torch.load(BEST_MODEL, map_location=device)
    model.load_state_dict(state["model"] if isinstance(state, dict) and "model" in state else state)
    model.eval()
    return model, device


def backtest_station(db, held_out, all_stations, model, device, n_windows: int = 3):
    held_df = load_station_series(db, held_out.station_id)
    if len(held_df) < MIN_TRAIN_RECORDS:
        return None

    others = [s for s in all_stations if s.station_id != held_out.station_id]
    other_dfs = {s.station_id: load_station_series(db, s.station_id) for s in others}
    others = [s for s in others if len(other_dfs[s.station_id]) >= MIN_TRAIN_RECORDS]
    if len(others) < 3:
        return None

    max_h = max(HORIZONS)
    origins = []
    t = held_df["ds"].max() - timedelta(hours=max_h)
    for _ in range(n_windows):
        origins.append(t)
        t -= timedelta(hours=24)

    errors = {m: {h: [] for h in HORIZONS} for m in METHODS}

    for origin in origins:
        held_train = held_df[held_df["ds"] <= origin]
        if len(held_train) < MIN_TRAIN_RECORDS:
            continue
        eligible_others = [s for s in others if (other_dfs[s.station_id]["ds"] <= origin).sum() >= MIN_TRAIN_RECORDS]
        if len(eligible_others) < 3:
            continue

        try:
            held_series = series_from_df(held_train, window_days=14)
            direct_preds = sarima_forecast(fit_sarima(held_series), steps=max_h)
        except Exception:
            direct_preds = [None] * max_h

        last_row = held_train[held_train["ds"] == origin]
        last_val = float(last_row["y"].iloc[0]) if len(last_row) else None

        other_forecasts, other_now = {}, {}
        for s in eligible_others:
            train = other_dfs[s.station_id][other_dfs[s.station_id]["ds"] <= origin]
            now_row = train[train["ds"] == origin]
            other_now[s.station_id] = float(now_row["y"].iloc[0]) if len(now_row) else None
            try:
                other_forecasts[s.station_id] = sarima_forecast(fit_sarima(series_from_df(train, window_days=14)), steps=max_h)
            except Exception:
                other_forecasts[s.station_id] = None

        for h in HORIZONS:
            target_ts = origin + timedelta(hours=h)
            actual_row = held_df[held_df["ds"] == target_ts]
            if len(actual_row) == 0:
                continue
            actual = float(actual_row["y"].iloc[0])

            if last_val is not None:
                errors["persistence"][h].append(abs(last_val - actual))
            if direct_preds[h - 1] is not None:
                errors["direct_sarima"][h].append(abs(direct_preds[h - 1] - actual))

            aqis_h, lag1_h, lag3_h, valid = [], [], [], True
            for s in eligible_others:
                fc = other_forecasts[s.station_id]
                if fc is None:
                    valid = False
                    break
                val_h = fc[h - 1]
                val_1 = fc[h - 2] if h >= 2 else other_now[s.station_id]
                val_3 = fc[h - 4] if h >= 4 else None
                aqis_h.append(val_h)
                lag1_h.append(val_1 if val_1 is not None else val_h)
                lag3_h.append(val_3)
            if not valid:
                continue

            idw = idw_interpolate(
                held_out.latitude, held_out.longitude,
                [(s.latitude, s.longitude, v) for s, v in zip(eligible_others, aqis_h)],
            )
            if idw is not None:
                errors["idw_chain"][h].append(abs(idw.estimated_aqi - actual))

            if model is not None:
                try:
                    pred = gnn_interpolate(
                        model, held_out.latitude, held_out.longitude,
                        [s.latitude for s in eligible_others],
                        [s.longitude for s in eligible_others],
                        aqis_h, target_ts.hour, target_ts.weekday(),
                        station_aqis_1h=lag1_h, station_aqis_3h=lag3_h, device=device,
                    )
                    errors["gnn_chain"][h].append(abs(pred - actual))
                except Exception:
                    pass

    return errors


def _mae(vals):
    return sum(vals) / len(vals) if vals else None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--stations", type=int, default=None, help="Limit to first N stations, for a quick run")
    parser.add_argument("--windows", type=int, default=3, help="Backtest windows per station")
    args = parser.parse_args()

    model, device = _load_model()
    if model is None:
        print(f"No GNN checkpoint at {BEST_MODEL} — gnn_chain will be empty.")

    db = SessionLocal()
    all_stations = db.query(Station).all()
    # Filter to stations that have sufficient history (>= MIN_TRAIN_RECORDS)
    eligible = []
    for s in all_stations:
        df = load_station_series(db, s.station_id)
        if len(df) >= MIN_TRAIN_RECORDS:
            eligible.append((s, len(df)))
    eligible.sort(key=lambda x: x[1], reverse=True)
    all_eligible_stations = [x[0] for x in eligible]

    if not all_eligible_stations:
        print("No stations found with >= MIN_TRAIN_RECORDS in the database.")
        db.close()
        return

    eval_stations = all_eligible_stations[: args.stations] if args.stations else all_eligible_stations

    totals = {m: {h: [] for h in HORIZONS} for m in METHODS}
    print(f"\nLeave-one-station-out spatio-temporal backtest ({len(eval_stations)} stations evaluated, {args.windows} windows each)")

    for method in METHODS:
        print(f"\n-- {method} --  (MAE, AQI points)")
        print(f"{'Station':<30}" + "".join(f"{'h='+str(h):>10}" for h in HORIZONS))
        for s in eval_stations:
            errs = backtest_station(db, s, all_eligible_stations, model, device, n_windows=args.windows)
            if errs is None:
                continue
            row = f"{s.name:<30}"
            for h in HORIZONS:
                mae = _mae(errs[method][h])
                totals[method][h].extend(errs[method][h])
                row += f"{mae:>10.1f}" if mae is not None else f"{'N/A':>10}"
            print(row)
    db.close()

    print("\n" + "=" * 60)
    print("Overall MAE by horizon (AQI points, lower is better)")
    print("=" * 60)
    print(f"{'Method':<16}" + "".join(f"{'h='+str(h)+'h':>10}" for h in HORIZONS) + f"{'n(h=1)':>10}")
    for method in METHODS:
        row = f"{method:<16}"
        for h in HORIZONS:
            mae = _mae(totals[method][h])
            row += f"{mae:>10.1f}" if mae is not None else f"{'N/A':>10}"
        row += f"{len(totals[method][1]):>10}"
        print(row)

    print("\ngnn_chain vs idw_chain shows whether GNN spatial interpolation adds value")
    print("over plain IDW once you're forecasting forward in time (the real question")
    print("for /api/forecast/coordinate). direct_sarima is a cheating upper bound —")
    print("it uses the held-out station's own history, which a real no-sensor point")
    print("would never have. gnn_chain/idw_chain will always trail it; the honest")
    print("comparison is gnn_chain vs idw_chain vs persistence.\n")


if __name__ == "__main__":
    main()