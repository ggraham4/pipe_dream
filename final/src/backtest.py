"""
Walk-forward buy/no-buy backtest + $10k dollar simulation.

Methodology (matches the design rules established in the project's own
chat history and repo code):
  - XGBoostClassifier(n_estimators=100, max_depth=3, learning_rate=0.1),
    same hyperparameters used throughout the repo's own XGBoost experiments.
  - Binary label: forward_return_20 > cutoff, where cutoff = 75th
    percentile of the TRAINING set's forward returns only (matches the
    final LSTM run's CUTOFF_PERCENTILE=75, avoiding the 95th-percentile
    "too rare to learn" problem flagged early in the project, and the
    70th used in one XGBoost sweep).
  - Strict walk-forward: for a decision made at time T, the model is
    trained ONLY on rows whose OWN forward-return label resolves at or
    before T (i.e. row date <= T - 20 trading days). This embargo/purge
    gap is exactly the fix the project's own chat history identified was
    missing from the LSTM's interleaved test split ("a training matrix
    from March 2015 and a test matrix from June 2015 sit right next to
    each other... not yet a genuine holdout of the future").
  - At T, every ticker with a complete (non-NaN) feature row is scored;
    the top N by predicted buy-probability are the "buy" list.
  - $10,000 equal-weighted across the buy list, held exactly 20 trading
    days, compared against $10,000 in SPY over the identical window.
"""
import pandas as pd
import numpy as np
from xgboost import XGBClassifier
from sklearn.metrics import roc_auc_score, matthews_corrcoef, precision_score
import json

from features import FEATURE_COLS, FORWARD_WINDOW

TOP_N = 5
CUTOFF_PERCENTILE = 75
LABEL_COL = "forward_return_20"

TIMEPOINTS = [
    "2013-01-02", "2015-01-02", "2017-01-03", "2019-01-02",
    "2021-01-04", "2023-01-03", "2025-01-02", "2026-06-01",
]


def nearest_trading_date(target, available_dates):
    target = pd.Timestamp(target)
    candidates = available_dates[available_dates <= target]
    return candidates.max() if len(candidates) else None


def run_backtest():
    feat = pd.read_parquet("/root/pipe_dream_final/out/features.parquet")
    feat = feat.sort_values(["ticker", "date"]).reset_index(drop=True)

    spy = pd.read_csv("/tmp/td_data/SPY.csv", parse_dates=["date"]).sort_values("date").reset_index(drop=True)
    spy["spy_fwd_return_20"] = spy["close"].shift(-FORWARD_WINDOW) / spy["close"] - 1

    all_dates = feat["date"].drop_duplicates().sort_values().reset_index(drop=True)

    embargo_days = FORWARD_WINDOW  # trading days

    results = []
    picks_log = []
    metrics_log = []

    for tp_str in TIMEPOINTS:
        tp = nearest_trading_date(tp_str, all_dates)
        if tp is None:
            print(f"skip {tp_str}: no trading date found")
            continue

        # training cutoff: embargo_days trading days before tp (by position in
        # the master trading calendar, not calendar days)
        idx = all_dates[all_dates == tp].index[0]
        if idx < embargo_days:
            print(f"skip {tp_str}: not enough history for embargo")
            continue
        train_cutoff_date = all_dates.iloc[idx - embargo_days]

        train = feat[(feat["date"] <= train_cutoff_date)].dropna(subset=FEATURE_COLS + [LABEL_COL])
        if len(train) < 500:
            print(f"skip {tp_str}: only {len(train)} training rows")
            continue

        cutoff_val = np.percentile(train[LABEL_COL], CUTOFF_PERCENTILE)
        y_train = (train[LABEL_COL] > cutoff_val).astype(int)
        X_train = train[FEATURE_COLS]

        model = XGBClassifier(n_estimators=100, max_depth=3, learning_rate=0.1,
                               eval_metric="logloss", verbosity=0)
        model.fit(X_train, y_train)

        # score cross-section AT tp
        test_rows = feat[(feat["date"] == tp)].dropna(subset=FEATURE_COLS).copy()
        if test_rows.empty:
            print(f"skip {tp_str}: no scoreable rows at {tp.date()}")
            continue
        test_rows["buy_proba"] = model.predict_proba(test_rows[FEATURE_COLS])[:, 1]

        # classification quality at this timepoint (needs realized label too)
        eval_rows = test_rows.dropna(subset=[LABEL_COL]).copy()
        if len(eval_rows) > 10 and eval_rows[LABEL_COL].gt(cutoff_val).nunique() > 1:
            y_eval = (eval_rows[LABEL_COL] > cutoff_val).astype(int)
            auc = roc_auc_score(y_eval, eval_rows["buy_proba"])
            preds = (eval_rows["buy_proba"] > 0.5).astype(int)
            mcc = matthews_corrcoef(y_eval, preds) if preds.nunique() > 1 else float("nan")
        else:
            auc, mcc = float("nan"), float("nan")

        metrics_log.append({
            "timepoint": str(tp.date()),
            "train_rows": len(train),
            "train_cutoff_date": str(train_cutoff_date.date()),
            "label_cutoff_return": round(float(cutoff_val), 4),
            "n_scored": len(test_rows),
            "auc": round(float(auc), 4) if auc == auc else None,
            "mcc": round(float(mcc), 4) if mcc == mcc else None,
        })

        top_picks = test_rows.sort_values("buy_proba", ascending=False).head(TOP_N)

        # simulate $10k equal weight, using REALIZED forward_return_20 for
        # each picked ticker (already computed with strict no-lookahead
        # construction: close[t+20] / close[t] - 1)
        picks_with_realized = top_picks.dropna(subset=[LABEL_COL])
        n_realized = len(picks_with_realized)
        if n_realized == 0:
            print(f"skip {tp_str}: no picks with realized forward return yet")
            continue

        per_stock = 10000 / n_realized
        ending_value = (per_stock * (1 + picks_with_realized[LABEL_COL])).sum()
        # add back any un-realized picks at $0 return contribution removed
        # (all picks should have realized returns except right at the data edge)
        portfolio_return = ending_value / 10000 - 1

        spy_row = spy[spy["date"] == tp]
        if spy_row.empty or spy_row["spy_fwd_return_20"].isna().all():
            spy_return = None
            spy_ending = None
        else:
            spy_return = float(spy_row["spy_fwd_return_20"].iloc[0])
            spy_ending = 10000 * (1 + spy_return)

        # naive "buy everything scored" universe benchmark
        universe_return = float(test_rows.dropna(subset=[LABEL_COL])[LABEL_COL].mean())

        results.append({
            "timepoint": str(tp.date()),
            "exit_date_approx_trading_days": FORWARD_WINDOW,
            "picks": picks_with_realized["ticker"].tolist(),
            "pick_probs": [round(float(p), 3) for p in picks_with_realized["buy_proba"].tolist()],
            "starting_value": 10000,
            "ending_value_model": round(float(ending_value), 2),
            "model_return_pct": round(float(portfolio_return) * 100, 2),
            "ending_value_spy": round(float(spy_ending), 2) if spy_ending else None,
            "spy_return_pct": round(float(spy_return) * 100, 2) if spy_return is not None else None,
            "universe_avg_return_pct": round(universe_return * 100, 2),
            "beat_spy": bool(spy_return is not None and portfolio_return > spy_return),
        })

        for t, p, r in zip(picks_with_realized["ticker"], picks_with_realized["buy_proba"], picks_with_realized[LABEL_COL]):
            picks_log.append({"timepoint": str(tp.date()), "ticker": t, "buy_proba": round(float(p), 3),
                               "realized_20d_return_pct": round(float(r) * 100, 2)})

    return results, metrics_log, picks_log


if __name__ == "__main__":
    results, metrics_log, picks_log = run_backtest()

    with open("/root/pipe_dream_final/out/backtest_results.json", "w") as f:
        json.dump(results, f, indent=2)
    with open("/root/pipe_dream_final/out/backtest_metrics.json", "w") as f:
        json.dump(metrics_log, f, indent=2)
    pd.DataFrame(picks_log).to_csv("/root/pipe_dream_final/out/backtest_picks.csv", index=False)

    print(f"\n{'timepoint':<12}{'model %':>10}{'SPY %':>10}{'univ avg %':>12}{'beat SPY':>10}")
    for r in results:
        print(f"{r['timepoint']:<12}{r['model_return_pct']:>10.2f}{r['spy_return_pct']:>10.2f}"
              f"{r['universe_avg_return_pct']:>12.2f}{str(r['beat_spy']):>10}")

    n = len(results)
    wins = sum(r["beat_spy"] for r in results)
    avg_model = np.mean([r["model_return_pct"] for r in results])
    avg_spy = np.mean([r["spy_return_pct"] for r in results])
    print(f"\nWin rate vs SPY: {wins}/{n}")
    print(f"Avg model return per trial: {avg_model:.2f}%")
    print(f"Avg SPY return per trial:   {avg_spy:.2f}%")

    print("\nClassification metrics per timepoint:")
    for m in metrics_log:
        print(m)
