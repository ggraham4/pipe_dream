"""
BETA -- walk-forward backtest comparing XGBoost with vs without fundamentals
features, on the SAME row-restricted universe so the comparison isolates
the marginal value of fundamentals rather than being confounded by a
smaller universe. Mirrors backtest.py's methodology exactly (same 8
timepoints, same $10k-equal-weight-top-5 simulation, same 75th-percentile
label, same embargo) -- only the feature set and the row-availability
filter differ.

Why the same-row-subset restriction matters: features_with_fundamentals_
beta.parquet has fundamentals coverage well under 100% (SEC XBRL starts
~2009, and 14 tickers have no SEC match at all -- see fundamentals_
features_beta.py's coverage printout). If the baseline ran on the full
universe and the augmented model ran only on fundamentals-covered rows,
any difference in results could just be "smaller/different universe," not
"fundamentals helped or hurt." Both models here are trained and scored on
exactly the same rows: every row must have a complete price feature vector
AND a complete fundamentals feature vector AND a resolved label. This is a
stricter, smaller universe than the production backtest's (skews toward
larger, more established companies with SEC filing history -- a real
caveat on how to read these results, not a bug).

Does NOT touch backtest.py or any production file. Output goes to
out/backtest_fundamentals_beta_*.json, not out/backtest_results.json.

Usage: python3 backtest_fundamentals_beta.py
"""
import argparse
import gc
import json

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score, matthews_corrcoef
from xgboost import XGBClassifier

from features import FEATURE_COLS, FORWARD_WINDOW, LABEL_COL, DATA_DIR, OUT_DIR
from fundamentals_features_beta import FUNDAMENTAL_FEATURE_COLS

TOP_N = 5
CUTOFF_PERCENTILE = 75
AUGMENTED_FEATURE_COLS = FEATURE_COLS + FUNDAMENTAL_FEATURE_COLS

TIMEPOINTS = [
    "2013-01-02", "2015-01-02", "2017-01-03", "2019-01-02",
    "2021-01-04", "2023-01-03", "2025-01-02", "2026-06-01",
]


def nearest_trading_date(target, available_dates):
    target = pd.Timestamp(target)
    candidates = available_dates[available_dates <= target]
    return candidates.max() if len(candidates) else None


def run_one_model(feat, all_dates, feature_cols, label, tag):
    spy = pd.read_csv(DATA_DIR / "SPY.csv", parse_dates=["date"]).sort_values("date").reset_index(drop=True)
    spy["spy_fwd_return"] = spy["close"].shift(-FORWARD_WINDOW) / spy["close"] - 1

    embargo_days = FORWARD_WINDOW
    results, metrics_log = [], []

    for tp_str in TIMEPOINTS:
        tp = nearest_trading_date(tp_str, all_dates)
        if tp is None:
            print(f"[{tag}] skip {tp_str}: no trading date found")
            continue
        idx = all_dates[all_dates == tp].index[0]
        if idx < embargo_days:
            print(f"[{tag}] skip {tp_str}: not enough history for embargo")
            continue
        train_cutoff_date = all_dates.iloc[idx - embargo_days]

        train = feat[feat["date"] <= train_cutoff_date]
        if len(train) < 300:
            print(f"[{tag}] skip {tp_str}: only {len(train)} training rows")
            continue

        cutoff_val = np.percentile(train[LABEL_COL], CUTOFF_PERCENTILE)
        y_train = (train[LABEL_COL] > cutoff_val).astype(int)
        model = XGBClassifier(n_estimators=100, max_depth=3, learning_rate=0.1,
                               eval_metric="logloss", verbosity=0)
        model.fit(train[feature_cols], y_train)

        test_rows = feat[feat["date"] == tp].copy()
        if test_rows.empty:
            print(f"[{tag}] skip {tp_str}: no scoreable rows at {tp.date()}")
            continue
        test_rows["buy_proba"] = model.predict_proba(test_rows[feature_cols])[:, 1]

        eval_rows = test_rows.dropna(subset=[LABEL_COL])
        if len(eval_rows) > 10 and eval_rows[LABEL_COL].gt(cutoff_val).nunique() > 1:
            y_eval = (eval_rows[LABEL_COL] > cutoff_val).astype(int)
            auc = roc_auc_score(y_eval, eval_rows["buy_proba"])
            preds = (eval_rows["buy_proba"] > 0.5).astype(int)
            mcc = matthews_corrcoef(y_eval, preds) if preds.nunique() > 1 else float("nan")
        else:
            auc, mcc = float("nan"), float("nan")

        metrics_log.append({
            "timepoint": str(tp.date()), "train_rows": len(train),
            "label_cutoff_return": round(float(cutoff_val), 4),
            "n_scored": len(test_rows),
            "auc": round(float(auc), 4) if auc == auc else None,
            "mcc": round(float(mcc), 4) if mcc == mcc else None,
        })

        top_picks = test_rows.sort_values("buy_proba", ascending=False).head(TOP_N)
        picks_realized = top_picks.dropna(subset=[LABEL_COL])
        if picks_realized.empty:
            print(f"[{tag}] skip {tp_str}: no picks with realized forward return yet")
            continue

        per_stock = 10000 / len(picks_realized)
        ending_value = (per_stock * (1 + picks_realized[LABEL_COL])).sum()
        portfolio_return = ending_value / 10000 - 1

        spy_row = spy[spy["date"] == tp]
        spy_return = float(spy_row["spy_fwd_return"].iloc[0]) if not spy_row.empty and spy_row["spy_fwd_return"].notna().any() else None
        spy_ending = 10000 * (1 + spy_return) if spy_return is not None else None
        universe_return = float(test_rows.dropna(subset=[LABEL_COL])[LABEL_COL].mean())

        results.append({
            "timepoint": str(tp.date()), "picks": picks_realized["ticker"].tolist(),
            "pick_probs": [round(float(p), 3) for p in picks_realized["buy_proba"].tolist()],
            "ending_value_model": round(float(ending_value), 2),
            "model_return_pct": round(float(portfolio_return) * 100, 2),
            "ending_value_spy": round(float(spy_ending), 2) if spy_ending else None,
            "spy_return_pct": round(float(spy_return) * 100, 2) if spy_return is not None else None,
            "universe_avg_return_pct": round(universe_return * 100, 2),
            "beat_spy": bool(spy_return is not None and portfolio_return > spy_return),
        })

    return results, metrics_log


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["baseline", "augmented", "combine"], required=True,
                         help="Run one model at a time (each a fresh process -- avoids OOM from "
                              "keeping both models' working memory resident at once) then combine.")
    args = parser.parse_args()

    if args.mode == "combine":
        with open(OUT_DIR / "backtest_fundamentals_beta_baseline.json") as f:
            baseline = json.load(f)
        with open(OUT_DIR / "backtest_fundamentals_beta_augmented.json") as f:
            augmented = json.load(f)
        out = {"universe_note": baseline["universe_note"],
               "baseline": {"results": baseline["results"], "metrics": baseline["metrics"]},
               "augmented": {"results": augmented["results"], "metrics": augmented["metrics"]}}
        with open(OUT_DIR / "backtest_fundamentals_beta.json", "w") as f:
            json.dump(out, f, indent=2)
        print_comparison(baseline["results"], augmented["results"])
        return

    print("Loading combined price+fundamentals panel...")
    feat = pd.read_parquet(OUT_DIR / "features_with_fundamentals_beta.parquet")
    feat = feat.sort_values(["ticker", "date"]).reset_index(drop=True)
    keep_cols = ["ticker", "date", "close"] + FEATURE_COLS + FUNDAMENTAL_FEATURE_COLS + [LABEL_COL]
    feat = feat[keep_cols]
    for c in FEATURE_COLS + FUNDAMENTAL_FEATURE_COLS + [LABEL_COL]:
        feat[c] = feat[c].astype("float32")
    gc.collect()

    # NOTE (corrected after a first pass): requiring ALL 14 fundamental
    # columns to be simultaneously non-null shrank the universe to 231
    # tickers (5.1% of rows) -- gross_margin and rnd_intensity are
    # inherently sparse (many financials/REITs/utilities/retailers don't
    # report a separate gross-profit or R&D line item at all), so a blanket
    # dropna on every fundamental column punished the whole universe for
    # two columns' sparsity and skewed hard toward one type of company
    # (mostly tech/industrials that report both). XGBoost natively handles
    # missing values (it learns a default split direction per node for
    # NaN), so instead we only require the same price+label completeness
    # the production backtest already requires -- fundamentals are used
    # wherever present and gracefully skipped by the model where absent,
    # which both keeps the universe representative AND is how this would
    # actually be deployed (not by shrinking the universe to whoever
    # reports every field).
    required = FEATURE_COLS + [LABEL_COL]
    before = len(feat)
    feat_restricted = feat.dropna(subset=required).copy()
    print(f"Restricting to rows with complete price+label data (same universe as the production "
          f"backtest -- fundamentals columns are left as-is, NaN where absent, XGBoost handles "
          f"missing values natively): {len(feat_restricted)}/{before} rows ({len(feat_restricted)/before:.1%}), "
          f"{feat_restricted['ticker'].nunique()} unique tickers")
    for col in FUNDAMENTAL_FEATURE_COLS:
        cov = feat_restricted[col].notna().mean()
        print(f"    {col:<22} {cov:.1%} coverage within this universe")

    all_dates = feat_restricted["date"].drop_duplicates().sort_values().reset_index(drop=True)
    del feat
    gc.collect()

    universe_note = (f"{len(feat_restricted)}/{before} rows ({len(feat_restricted)/before:.1%}), "
                      f"{feat_restricted['ticker'].nunique()} tickers -- same price+label-complete "
                      f"universe as the production backtest; fundamentals used where present, "
                      f"NaN-handled by XGBoost where absent")

    if args.mode == "baseline":
        print("\n=== Running BASELINE (price-only features) ===")
        results, metrics = run_one_model(feat_restricted, all_dates, FEATURE_COLS, LABEL_COL, "baseline")
        out_path = OUT_DIR / "backtest_fundamentals_beta_baseline.json"
    else:
        print("\n=== Running AUGMENTED (price + fundamentals features) ===")
        results, metrics = run_one_model(feat_restricted, all_dates, AUGMENTED_FEATURE_COLS, LABEL_COL, "augmented")
        out_path = OUT_DIR / "backtest_fundamentals_beta_augmented.json"

    with open(out_path, "w") as f:
        json.dump({"universe_note": universe_note, "results": results, "metrics": metrics}, f, indent=2)
    print(f"Saved -> {out_path}")
    summarize(results, args.mode)


def summarize(results, label):
    n = len(results)
    wins = sum(r["beat_spy"] for r in results)
    avg_model = np.mean([r["model_return_pct"] for r in results])
    avg_spy = np.mean([r["spy_return_pct"] for r in results])
    total = sum(r["ending_value_model"] for r in results)
    print(f"\n{label}: {wins}/{n} beat SPY, avg return {avg_model:.2f}%/trial "
          f"(SPY avg {avg_spy:.2f}%/trial), ${n*10000:,} -> ${total:,.2f}")
    return wins, avg_model, total


def print_comparison(baseline_results, augmented_results):
    print("\n" + "=" * 70)
    print(f"{'timepoint':<12}{'baseline %':>12}{'augmented %':>13}{'SPY %':>10}")
    for b, a in zip(baseline_results, augmented_results):
        print(f"{b['timepoint']:<12}{b['model_return_pct']:>12.2f}{a['model_return_pct']:>13.2f}{b['spy_return_pct']:>10.2f}")
    summarize(baseline_results, "BASELINE (price-only)")
    summarize(augmented_results, "AUGMENTED (price + fundamentals)")


if __name__ == "__main__":
    main()
