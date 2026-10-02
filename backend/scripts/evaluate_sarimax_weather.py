from __future__ import annotations
import argparse
import sys
import time
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.attribution.open_meteo_client import EXOG_COLUMNS, get_historical_weather
from app.db import SessionLocal
from app.forecasting.baseline import seasonal_naive_forecast
from app.forecasting.sarima_model import (
    align_exog_to_series,
    fit_sarima,
    fit_sarimax,
    load_station_series,
    sarima_forecast,
    sarimax_forecast,
    series_from_df,
)
from app.models.db_models import Station

TEST_WINDOW_DAYS = 14
FORECAST_HORIZON_H = 24
MIN_TRAIN_RECORDS = 500
WEATHER_FEATURES = ["temp_c", "humidity_pct", "wind_speed_mps", "pressure_hpa", "precip_mm"]


def _mae(errors: list[float]) -> float | None:
    return sum(errors) / len(errors) if errors else None


def evaluate_station(db, station, test_days: int = TEST_WINDOW_DAYS, min_records: int = MIN_TRAIN_RECORDS) -> dict | None:
    df = load_station_series(db, station.station_id)
    if not df.empty and df["ds"].max().year >= 2025 and ((df["ds"] < "2025-01-01").sum() >= min_records):
        df = df[df["ds"] < "2025-01-01"].copy()
    if len(df) < min_records:
        print(f"  {station.name}: only {len(df)} records - skipping (need >= {min_records})")
        return None

    test_start = df["ds"].max() - timedelta(days=test_days)
    n_test = (df["ds"] > test_start).sum()
    if n_test < FORECAST_HORIZON_H:
        print(f"  {station.name}: only {n_test} test points - skipping")
        return None

    print(f"\n  {station.name}")
    print(f"    train up to {test_start.date()}  |  test: last {test_days} days  ({n_test} pts)")

    print(f"    fetching historical weather ({df['ds'].min().date()} to {df['ds'].max().date()})...", end=" ", flush=True)
    weather = get_historical_weather(station.latitude, station.longitude, df["ds"].min().date(), df["ds"].max().date())
    print(f"{len(weather)} hourly rows" if not weather.empty else "FAILED (no weather — SARIMAX column will be empty for this station)")

    baseline_errs, sarima_errs, weather_errs = [], [], []
    current_origin = test_start
    step = 0
    while current_origin + timedelta(hours=FORECAST_HORIZON_H) <= df["ds"].max():
        window_end = current_origin + timedelta(hours=FORECAST_HORIZON_H)
        train_df = df[df["ds"] <= current_origin]
        test_window = df[(df["ds"] > current_origin) & (df["ds"] <= window_end)]
        if len(test_window) == 0 or len(train_df) < min_records:
            current_origin = window_end
            continue
        step += 1
        ts_list = list(test_window["ds"])

        t0 = time.perf_counter()
        try:
            s_series = series_from_df(train_df, window_days=14)
            sfit = fit_sarima(s_series)
            s_preds = sarima_forecast(sfit, steps=len(ts_list))
            s_map = dict(zip(ts_list, s_preds))
            s_ok = True
        except Exception as exc:
            print(f"    [step {step}] SARIMA error: {exc}")
            s_map, s_ok = {}, False
        sarima_fit_s = time.perf_counter() - t0

        w_map, w_ok = {}, False
        if s_ok and not weather.empty:
            try:
                exog_train = align_exog_to_series(s_series, weather, WEATHER_FEATURES)
                future_weather = weather[weather["ds"].isin(ts_list)].set_index("ds").reindex(ts_list)[WEATHER_FEATURES]
                if exog_train is not None and not future_weather.isna().any().any() and len(future_weather) == len(ts_list):
                    wfit = fit_sarimax(s_series, exog_train)
                    w_preds = sarimax_forecast(wfit, future_weather.reset_index(drop=True), steps=len(ts_list))
                    w_map = dict(zip(ts_list, w_preds))
                    w_ok = True
            except Exception as exc:
                print(f"    [step {step}] SARIMAX+weather error: {exc}")

        print(f"    step {step:2d}: {current_origin.date()} -> {window_end.date()} | {len(test_window):3d} pts | "
              f"SARIMA {sarima_fit_s:.2f}s | weather {'ok' if w_ok else 'skip'}")

        for _, row in test_window.iterrows():
            actual, ts = row["y"], row["ds"]
            b = seasonal_naive_forecast(db, station.station_id, ts)
            if b is not None:
                baseline_errs.append(abs(b - actual))
            if s_ok and (s := s_map.get(ts)) is not None:
                sarima_errs.append(abs(s - actual))
            if w_ok and (w := w_map.get(ts)) is not None:
                weather_errs.append(abs(w - actual))
        current_origin = window_end

    return {
        "station": station.name,
        "baseline_mae": _mae(baseline_errs),
        "sarima_mae": _mae(sarima_errs),
        "weather_mae": _mae(weather_errs),
        "n_sarima": len(sarima_errs),
        "n_weather": len(weather_errs),
    }


def main():
    parser = argparse.ArgumentParser(description="Walk-forward evaluation: Baseline vs SARIMA vs SARIMAX+weather")
    parser.add_argument("--days", type=int, default=TEST_WINDOW_DAYS)
    parser.add_argument("--station", type=str, default=None)
    parser.add_argument("--min-records", type=int, default=MIN_TRAIN_RECORDS)
    args = parser.parse_args()

    db = SessionLocal()
    stations = db.query(Station).all()
    if args.station:
        stations = [s for s in stations if s.station_id == args.station]
        if not stations:
            print(f"Station '{args.station}' not found in DB.")
            db.close()
            return

    print("\nWalk-forward forecast evaluation (Baseline vs SARIMA vs SARIMAX+weather)")
    print(f"  Test window : last {args.days} days per station")
    print(f"  Horizon     : {FORECAST_HORIZON_H} h (retrain every {FORECAST_HORIZON_H} h)")
    print(f"  Weather     : {', '.join(WEATHER_FEATURES)} (Open-Meteo ERA5, wind direction excluded — circular)")
    print(f"  Stations    : {len(stations)}\n")

    results = [r for s in stations if (r := evaluate_station(db, s, test_days=args.days, min_records=args.min_records))]
    db.close()

    if not results:
        print("\nNo stations had sufficient data to evaluate.")
        return

    hdr = f"\n{'Station':<40} {'Baseline':>10} {'SARIMA':>10} {'+Weather':>10} {'n(wx)':>7}"
    print(hdr)
    print("-" * 82)
    for r in results:
        b = f"{r['baseline_mae']:.2f}" if r["baseline_mae"] is not None else "N/A"
        s = f"{r['sarima_mae']:.2f}" if r["sarima_mae"] is not None else "N/A"
        w = f"{r['weather_mae']:.2f}" if r["weather_mae"] is not None else "N/A"
        print(f"{r['station']:<40} {b:>10} {s:>10} {w:>10} {r['n_weather']:>7}")

    def avg(key):
        vals = [r[key] for r in results if r[key] is not None]
        return sum(vals) / len(vals) if vals else None

    avg_b, avg_s, avg_w = avg("baseline_mae"), avg("sarima_mae"), avg("weather_mae")
    print("\n" + "=" * 60)
    print("Overall average MAE (AQI points, lower is better)")
    print("=" * 60)
    print(f"  Baseline (seasonal-naive): {avg_b:.2f}" if avg_b is not None else "  Baseline: N/A")
    print(f"  SARIMA (no weather):       {avg_s:.2f}" if avg_s is not None else "  SARIMA: N/A")
    print(f"  SARIMAX (+weather):        {avg_w:.2f}" if avg_w is not None else "  SARIMAX+weather: N/A (weather fetch may have failed for all stations)")
    if avg_s is not None and avg_w is not None:
        gain = avg_s - avg_w
        pct = gain / avg_s * 100 if avg_s else 0
        print(f"\n  Weather gain over plain SARIMA: {gain:+.2f} pts ({pct:+.1f}%)")
        if gain > 0:
            print("  -> Weather exog genuinely helps on this data — worth wiring into production.")
        else:
            print("  -> Weather exog does NOT help here — the added SARIMAX complexity isn't earning")
            print("     its keep; plain SARIMA remains the better choice for now.")
    print()


if __name__ == "__main__":
    main()
