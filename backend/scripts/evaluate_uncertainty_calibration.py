from __future__ import annotations
import argparse
import random
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import torch

from app.db import SessionLocal
from app.models.db_models import Station
from app.forecasting.sarima_model import (
    fit_sarima,
    load_station_series,
    sarima_forecast_with_ci,
    series_from_df,
)
from app.ml.gnn_model import SpatialGNN, gnn_interpolate_with_uncertainty
from scripts.evaluate_gnn import load_full_context, load_test_data
from scripts.train_gnn import get_lag_aqi

MODELS_DIR = Path(__file__).resolve().parent.parent / "models"
BEST_MODEL = MODELS_DIR / "gnn_best.pt"
TARGET_COVERAGE = 0.95
ALPHA = 1.0 - TARGET_COVERAGE
CI_Z = 1.96  # matches app/forecasting/spatial.py's CI_Z
MIN_TRAIN_RECORDS = 500


def evaluate_sarima_coverage(test_days: int = 14, max_windows_per_station: int = 20):
    db = SessionLocal()
    stations = db.query(Station).all()
    hits, total, widths = 0, 0, []
    print(f"\nSARIMA confidence-interval coverage ({TARGET_COVERAGE:.0%} target)")
    print(f"  Walk-forward, retrain every 24h, last {test_days} days per station\n")
    for s in stations:
        df = load_station_series(db, s.station_id)
        if len(df) < MIN_TRAIN_RECORDS:
            continue
        test_start = df["ds"].max() - timedelta(days=test_days)
        if (df["ds"] > test_start).sum() < 24:
            continue

        current_origin = test_start
        windows_done = 0
        station_hits, station_total = 0, 0
        while current_origin + timedelta(hours=24) <= df["ds"].max() and windows_done < max_windows_per_station:
            window_end = current_origin + timedelta(hours=24)
            train_df = df[df["ds"] <= current_origin]
            test_window = df[(df["ds"] > current_origin) & (df["ds"] <= window_end)]
            if len(test_window) == 0 or len(train_df) < MIN_TRAIN_RECORDS:
                current_origin = window_end
                continue
            try:
                series = series_from_df(train_df, window_days=14)
                fit = fit_sarima(series)
                _, lower, upper = sarima_forecast_with_ci(fit, steps=len(test_window), alpha=ALPHA)
            except Exception:
                current_origin = window_end
                continue
            for (_, row), lo, hi in zip(test_window.iterrows(), lower, upper):
                actual = row["y"]
                station_total += 1
                widths.append(hi - lo)
                if lo <= actual <= hi:
                    station_hits += 1
            windows_done += 1
            current_origin = window_end

        if station_total:
            cov = station_hits / station_total
            print(f"  {s.name:<40} coverage={cov:6.1%}  n={station_total:4d}")
            hits += station_hits
            total += station_total
    db.close()

    if total == 0:
        print("  No station had enough history for a walk-forward SARIMA CI check.")
        return
    overall = hits / total
    avg_width = sum(widths) / len(widths)
    print(f"\n  Overall empirical coverage: {overall:.1%}  (target {TARGET_COVERAGE:.0%})")
    print(f"  Average interval width:     {avg_width:.1f} AQI pts")
    if overall < TARGET_COVERAGE - 0.05:
        print("  -> Intervals are TOO NARROW (overconfident): the true value falls")
        print("     outside more often than the stated 95% implies.")
    elif overall > TARGET_COVERAGE + 0.05:
        print("  -> Intervals are wider than necessary (underconfident) — safe, but")
        print("     could be tightened for a more useful band.")
    else:
        print("  -> Reasonably well calibrated.")


def evaluate_gnn_coverage(max_steps: int = 300, n_mc_samples: int = 20):
    print(f"\nGNN MC-dropout coverage (mean +/- {CI_Z}*std band, nominal ~95%)")
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    if not BEST_MODEL.exists():
        print(f"  No checkpoint at {BEST_MODEL} — skipping (needs a trained model).")
        return

    model = SpatialGNN().to(device)
    state = torch.load(BEST_MODEL, map_location=device)
    model.load_state_dict(state["model"] if isinstance(state, dict) and "model" in state else state)
    model.eval()

    test_data = load_test_data(use_val=False)
    if len(test_data) < 10:
        print("  Test split too small — falling back to the validation split.")
        test_data = load_test_data(use_val=True)
    full_context = load_full_context()

    timestamps = list(test_data.keys())
    if len(timestamps) > max_steps:
        timestamps = random.sample(timestamps, max_steps)

    hits, total, widths = 0, 0, []
    for ts in timestamps:
        entries = test_data[ts]
        ts_dt = ts if isinstance(ts, datetime) else datetime.fromisoformat(str(ts))
        for i, (sid, lat, lon, actual_aqi) in enumerate(entries):
            other = [e for j, e in enumerate(entries) if j != i]
            if len(other) < 3:
                continue
            s_lats = [e[1] for e in other]
            s_lons = [e[2] for e in other]
            s_aqis = [e[3] for e in other]
            sids = [e[0] for e in other]
            s_1h = [get_lag_aqi(sid_, ts_dt, full_context, 1) for sid_ in sids]
            s_3h = [get_lag_aqi(sid_, ts_dt, full_context, 3) for sid_ in sids]
            mean, std = gnn_interpolate_with_uncertainty(
                model, lat, lon, s_lats, s_lons, s_aqis, ts_dt.hour, ts_dt.weekday(),
                station_aqis_1h=s_1h, station_aqis_3h=s_3h, device=device, n_samples=n_mc_samples,
            )
            lo, hi = max(0.0, mean - CI_Z * std), min(500.0, mean + CI_Z * std)
            widths.append(hi - lo)
            total += 1
            if lo <= actual_aqi <= hi:
                hits += 1

    if total == 0:
        print("  No eligible held-out points found.")
        return
    coverage = hits / total
    avg_width = sum(widths) / len(widths)
    print(f"  Points evaluated:        {total}")
    print(f"  Empirical coverage:      {coverage:.1%}  (nominal ~95%)")
    print(f"  Average interval width:  {avg_width:.1f} AQI pts")
    print("  Note: MC-dropout is a relative confidence signal by construction, not a")
    print("  calibrated statistical interval — unlike SARIMA's CI, there's no reason")
    print("  to expect exactly 95% up front. This number tells you how far off it is,")
    print("  which is what you'd use to decide whether to scale CI_Z in spatial.py.")


def main():
    parser = argparse.ArgumentParser(description="Calibration check for SARIMA and GNN uncertainty estimates")
    parser.add_argument("--skip-sarima", action="store_true")
    parser.add_argument("--skip-gnn", action="store_true")
    parser.add_argument("--max-steps", type=int, default=300, help="Max GNN leave-one-out points to sample")
    args = parser.parse_args()
    if not args.skip_sarima:
        evaluate_sarima_coverage()
    if not args.skip_gnn:
        evaluate_gnn_coverage(max_steps=args.max_steps)


if __name__ == "__main__":
    main()