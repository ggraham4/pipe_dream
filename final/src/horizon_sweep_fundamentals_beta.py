"""
BETA -- does adding fundamentals change which forward-return horizon is
best? Re-runs the baseline-vs-augmented comparison from backtest_
fundamentals_beta.py across horizons 10/20/40/60 trading days (same set
horizon_sweep.py tested for the price-only model), using the multi-horizon
label panel (features_with_fundamentals_beta_multihorizon.parquet, built
by adding forward_return_10/20/60 alongside the existing forward_return_40
LABEL_COL -- fundamentals features themselves don't depend on horizon, only
the label/embargo does, so the same panel covers all four).

Run ONE (horizon, mode) combination per process invocation -- same memory
lesson learned in backtest_fundamentals_beta.py (running multiple XGBoost
passes back-to-back in one long-lived process crept up to an OOM kill on
this sandbox's 8GB cap).

Usage:
    python3 horizon_sweep_fundamentals_beta.py --horizon 10 --mode baseline
    python3 horizon_sweep_fundamentals_beta.py --horizon 10 --mode augmented
    ... (repeat for 20, 40, 60)
    python3 horizon_sweep_fundamentals_beta.py --mode combine
"""
import argparse
import gc
import json

import numpy as np
import pandas as pd
from xgboost import XGBClassifier

from features import FEATURE_COLS, DATA_DIR, OUT_DIR
from fundamentals_features_beta import FUNDAMENTAL_FEATURE_COLS

TOP_N = 5
CUTOFF_PERCENTILE = 75
AUGMENTED_FEATURE_COLS = FEATURE_COLS + FUNDAMENTAL_FEATURE_COLS
HORIZONS = [10, 20, 40, 60]

TIMEPOINTS = [
    "2013-01-02", "2015-01-02", "2017-01-03", "2019-01-02",
    "2021-01-04", "2023-01-03", "2025-01-02", "2026-06-01",
]


def nearest_trading_date(target, available_dates):
    target = pd.Timestamp(target)
    candidates = available_dates[available_dates <= target]
    return candidates.max() if len(candidates) else None


def run_one(feat, all_dates, feature_cols, label_col, horizon, tag):
    spy = pd.read_csv(DATA_DIR / "SPY.csv", parse_dates=["date"]).sort_values("date").reset_index(drop=True)
    spy["spy_fwd_return"] = spy["close"].shift(-horizon) / spy["close"] - 1

    results = []
    for tp_str in TIMEPOINTS:
        tp = nearest_trading_date(tp_str, all_dates)
        if tp is None:
            continue
        idx = all_dates[all_dates == tp].index[0]
        if idx < horizon:
            print(f"[{tag} h={horizon}] skip {tp_str}: not enough history for embargo")
            continue
        train_cutoff_date = all_dates.iloc[idx - horizon]

        train = feat[feat["date"] <= train_cutoff_date]
        if len(train) < 300:
            print(f"[{tag} h={horizon}] skip {tp_str}: only {len(train)} training rows")
            continue

        cutoff_val = np.percentile(train[label_col], CUTOFF_PERCENTILE)
        y_train = (train[label_col] > cutoff_val).astype(int)
        model = XGBClassifier(n_estimators=100, max_depth=3, learning_rate=0.1,
                               eval_metric="logloss", verbosity=0)
        model.fit(train[feature_cols], y_train)

        test_rows = feat[feat["date"] == tp].copy()
        if test_rows.empty:
            continue
        test_rows["buy_proba"] = model.predict_proba(test_rows[feature_cols])[:, 1]

        top_picks = test_rows.sort_values("buy_proba", ascending=False).head(TOP_N)
        picks_realized = top_picks.dropna(subset=[label_col])
        if picks_realized.empty:
            print(f"[{tag} h={horizon}] skip {tp_str}: no picks with realized forward return yet")
            continue

        per_stock = 10000 / len(picks_realized)
        ending_value = (per_stock * (1 + picks_realized[label_col])).sum()
        portfolio_return = ending_value / 10000 - 1

        spy_row = spy[spy["date"] == tp]
        spy_return = float(spy_row["spy_fwd_return"].iloc[0]) if not spy_row.empty and spy_row["spy_fwd_return"].notna().any() else None

        results.append({
            "timepoint": str(tp.date()), "picks": picks_realized["ticker"].tolist(),
            "model_return_pct": round(float(portfolio_return) * 100, 2),
            "spy_return_pct": round(float(spy_return) * 100, 2) if spy_return is not None else None,
            "beat_spy": bool(spy_return is not None and portfolio_return > spy_return),
        })
    return results


def summarize(results):
    usable = [r for r in results if r.get("spy_return_pct") is not None]
    n = len(usable)
    if n == 0:
        return 0, 0.0, 0.0
    wins = sum(r["beat_spy"] for r in usable)
    avg_model = float(np.mean([r["model_return_pct"] for r in usable]))
    avg_spy = float(np.mean([r["spy_return_pct"] for r in usable]))
    return wins, avg_model, avg_spy


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--horizon", type=int, choices=HORIZONS)
    parser.add_argument("--mode", choices=["baseline", "augmented", "combine"], required=True)
    args = parser.parse_args()

    if args.mode == "combine":
        summary = {"horizons": {}}
        for h in HORIZONS:
            row = {}
            for mode in ["baseline", "augmented"]:
                path = OUT_DIR / f"horizon_sweep_fund_{mode}_{h}.json"
                if not path.exists():
                    print(f"MISSING: {path} -- run that (horizon, mode) combo first")
                    continue
                with open(path) as f:
                    results = json.load(f)["results"]
                wins, avg_model, avg_spy = summarize(results)
                row[mode] = {"win_rate": f"{wins}/{len(results)}", "avg_return_pct": round(avg_model, 2),
                             "avg_spy_pct": round(avg_spy, 2), "results": results}
            summary["horizons"][h] = row
        with open(OUT_DIR / "horizon_sweep_fundamentals_beta_summary.json", "w") as f:
            json.dump(summary, f, indent=2)

        print(f"\n{'horizon':<10}{'baseline win':>14}{'baseline avg%':>16}{'augmented win':>16}{'augmented avg%':>18}{'SPY avg%':>10}")
        for h in HORIZONS:
            row = summary["horizons"].get(h, {})
            b, a = row.get("baseline"), row.get("augmented")
            if b and a:
                print(f"{h:<10}{b['win_rate']:>14}{b['avg_return_pct']:>16.2f}{a['win_rate']:>16}{a['avg_return_pct']:>18.2f}{b['avg_spy_pct']:>10.2f}")
        print(f"\nSaved -> {OUT_DIR / 'horizon_sweep_fundamentals_beta_summary.json'}")
        return

    label_col = f"forward_return_{args.horizon}"
    print(f"Loading multi-horizon panel for horizon={args.horizon}, mode={args.mode}...")
    feat = pd.read_parquet(OUT_DIR / "features_with_fundamentals_beta_multihorizon.parquet")
    keep = ["ticker", "date", "close"] + FEATURE_COLS + FUNDAMENTAL_FEATURE_COLS + [label_col]
    feat = feat[keep].dropna(subset=FEATURE_COLS + [label_col]).reset_index(drop=True)
    for c in FEATURE_COLS + FUNDAMENTAL_FEATURE_COLS + [label_col]:
        feat[c] = feat[c].astype("float32")
    gc.collect()
    all_dates = feat["date"].drop_duplicates().sort_values().reset_index(drop=True)
    print(f"  {len(feat)} rows, {feat['ticker'].nunique()} tickers")

    feature_cols = FEATURE_COLS if args.mode == "baseline" else AUGMENTED_FEATURE_COLS
    results = run_one(feat, all_dates, feature_cols, label_col, args.horizon, args.mode)

    out_path = OUT_DIR / f"horizon_sweep_fund_{args.mode}_{args.horizon}.json"
    with open(out_path, "w") as f:
        json.dump({"horizon": args.horizon, "mode": args.mode, "results": results}, f, indent=2)
    wins, avg_model, avg_spy = summarize(results)
    print(f"h={args.horizon} {args.mode}: {wins}/{len(results)} beat SPY, avg {avg_model:.2f}% (SPY {avg_spy:.2f}%)")
    print(f"Saved -> {out_path}")


if __name__ == "__main__":
    main()
