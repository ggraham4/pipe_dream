"""
Horizon sweep: compares the current 20-trading-day forward-return label/hold
horizon against alternative horizons, using the exact same walk-forward
methodology, embargo discipline, timepoints, and $10k dollar-simulation
framing as backtest.py / lstm_backtest.py -- the only thing that changes
across horizons is H itself (forward_return_H replaces forward_return_20 as
both the training label AND the embargo gap, and SPY's own matched-window
benchmark return uses the same H).

Motivation (Gabe, 2026-08-27): the 20-day horizon was inherited from Gabe's
original repo convention ("most-used horizon in prior experiments"), never
actually swept against alternatives within this project's v1/v2/v3
backtests. Worth testing for real now that the universe/history is large
enough (~5.8M labeled rows, 2006-2026) to make the comparison meaningful.

LSTM's trailing INPUT sequence length (SEQ_LEN=20 trading days of feature
history per example) is held FIXED across all horizons here -- only the
forward-looking prediction target changes. Mixing both would confound "does
a longer prediction horizon help" with "does a longer lookback window help".

The H=20 column is not recomputed here -- it reuses the already-delivered
out/backtest_results.json / out/lstm_backtest_results.json numbers directly,
so this script only needs to freshly train the other candidate horizons.
"""
import gc
import json

import numpy as np
import pandas as pd
import torch

from features import FEATURE_COLS, DATA_DIR, OUT_DIR
from lstm_backtest import train_lstm, SEED, SEQ_LEN

CUTOFF_PERCENTILE = 75
TOP_N = 5
LSTM_TRAIN_CAP = 40000
NEW_HORIZONS = [10, 40, 60]  # 20 reused from existing backtest output

TIMEPOINTS = [
    "2013-01-02", "2015-01-02", "2017-01-03", "2019-01-02",
    "2021-01-04", "2023-01-03", "2025-01-02", "2026-06-01",
]


def nearest_trading_date(target, available_dates):
    target = pd.Timestamp(target)
    candidates = available_dates[available_dates <= target]
    return candidates.max() if len(candidates) else None


class HorizonSequenceIndex:
    """Same design as lstm_backtest.SequenceIndex, generalized to an
    arbitrary label column (forward_return_H) so it can be rebuilt per
    horizon without touching the SEQ_LEN trailing input window."""

    def __init__(self, feat, label_col):
        self.tickers = []
        self._vals_by_ticker = []
        tid_chunks, row_chunks, date_chunks, label_chunks = [], [], [], []
        for ticker, g in feat.groupby("ticker", sort=False):
            g = g.sort_values("date").dropna(subset=FEATURE_COLS)
            if len(g) < SEQ_LEN:
                continue
            tid = len(self.tickers)
            self.tickers.append(ticker)
            self._vals_by_ticker.append(g[FEATURE_COLS].to_numpy(dtype=np.float32))
            end_idx = np.arange(SEQ_LEN - 1, len(g), dtype=np.int32)
            tid_chunks.append(np.full(len(end_idx), tid, dtype=np.int32))
            row_chunks.append(end_idx)
            date_chunks.append(g["date"].to_numpy()[end_idx])
            label_chunks.append(g[label_col].to_numpy(dtype=np.float64)[end_idx])
        self.ticker_id = np.concatenate(tid_chunks)
        self.row_idx = np.concatenate(row_chunks)
        self.dates = np.concatenate(date_chunks)
        self.labels = np.concatenate(label_chunks)

    def __len__(self):
        return len(self.dates)

    def sequences_for(self, pool_idx):
        n_features = self._vals_by_ticker[0].shape[1]
        out = np.empty((len(pool_idx), SEQ_LEN, n_features), dtype=np.float32)
        tids = self.ticker_id[pool_idx]
        ridx = self.row_idx[pool_idx]
        for i in range(len(pool_idx)):
            vals = self._vals_by_ticker[tids[i]]
            r = ridx[i]
            out[i] = vals[r - SEQ_LEN + 1: r + 1]
        return out

    def tickers_for(self, pool_idx):
        tids = self.ticker_id[pool_idx]
        return np.array([self.tickers[t] for t in tids], dtype=object)


def spy_horizon_returns(spy, h, all_dates):
    spy = spy.sort_values("date").reset_index(drop=True)
    spy[f"fwd_{h}"] = spy["close"].shift(-h) / spy["close"] - 1
    out = {}
    for tp_str in TIMEPOINTS:
        tp = nearest_trading_date(tp_str, all_dates)
        if tp is None:
            continue
        row = spy[spy["date"] == tp]
        if row.empty or row[f"fwd_{h}"].isna().all():
            continue
        out[str(tp.date())] = round(float(row[f"fwd_{h}"].iloc[0]) * 100, 2)
    return out


def run_xgb_horizon(feat, label_col, h, all_dates, spy_returns):
    from xgboost import XGBClassifier
    results = []
    for tp_str in TIMEPOINTS:
        tp = nearest_trading_date(tp_str, all_dates)
        if tp is None:
            continue
        idx = all_dates[all_dates == tp].index[0]
        if idx < h:
            continue
        train_cutoff_date = all_dates.iloc[idx - h]
        train = feat[feat["date"] <= train_cutoff_date].dropna(subset=FEATURE_COLS + [label_col])
        if len(train) < 500:
            continue
        cutoff_val = np.percentile(train[label_col], CUTOFF_PERCENTILE)
        y_train = (train[label_col] > cutoff_val).astype(int)
        model = XGBClassifier(n_estimators=100, max_depth=3, learning_rate=0.1,
                               eval_metric="logloss", verbosity=0)
        model.fit(train[FEATURE_COLS], y_train)

        test_rows = feat[feat["date"] == tp].dropna(subset=FEATURE_COLS).copy()
        if test_rows.empty:
            continue
        test_rows["buy_proba"] = model.predict_proba(test_rows[FEATURE_COLS])[:, 1]
        top_picks = test_rows.sort_values("buy_proba", ascending=False).head(TOP_N)
        picks_realized = top_picks.dropna(subset=[label_col])
        if picks_realized.empty:
            continue
        per_stock = 10000 / len(picks_realized)
        ending_value = (per_stock * (1 + picks_realized[label_col])).sum()
        portfolio_return = round(float(ending_value / 10000 - 1) * 100, 2)
        tp_key = str(tp.date())
        spy_r = spy_returns.get(tp_key)
        results.append({
            "timepoint": tp_key,
            "model_return_pct": portfolio_return,
            "spy_return_pct": spy_r,
            "beat_spy": (spy_r is not None and portfolio_return > spy_r),
        })
    return results


def run_lstm_horizon(idx_store, h, all_dates, spy_returns, rng):
    results = []
    for tp_str in TIMEPOINTS:
        tp = nearest_trading_date(tp_str, all_dates)
        if tp is None:
            continue
        idx = all_dates[all_dates == tp].index[0]
        if idx < h:
            continue
        train_cutoff_date = all_dates.iloc[idx - h]

        train_mask = (idx_store.dates <= np.datetime64(train_cutoff_date)) & ~np.isnan(idx_store.labels)
        n_avail = train_mask.sum()
        if n_avail < 500:
            continue
        pool = np.where(train_mask)[0]
        if len(pool) > LSTM_TRAIN_CAP:
            pool = rng.choice(pool, size=LSTM_TRAIN_CAP, replace=False)

        X_train_raw = idx_store.sequences_for(pool)
        y_train_raw = idx_store.labels[pool]
        cutoff_val = np.percentile(y_train_raw, CUTOFF_PERCENTILE)
        y_train = (y_train_raw > cutoff_val).astype(np.float32)

        mean = X_train_raw.reshape(-1, X_train_raw.shape[-1]).mean(axis=0)
        std = X_train_raw.reshape(-1, X_train_raw.shape[-1]).std(axis=0)
        std[std == 0] = 1.0
        X_train = (X_train_raw - mean) / std

        model, best_epoch, best_val = train_lstm(X_train, y_train, rng, X_train.shape[-1])

        test_mask = idx_store.dates == np.datetime64(tp)
        test_idx = np.where(test_mask)[0]
        if len(test_idx) == 0:
            continue
        X_test = (idx_store.sequences_for(test_idx) - mean) / std
        y_test_label = idx_store.labels[test_idx]
        with torch.no_grad():
            test_probs = torch.sigmoid(model(torch.tensor(X_test, dtype=torch.float32))).numpy()

        order = np.argsort(-test_probs)
        realized_mask = ~np.isnan(y_test_label)
        top_idx = [i for i in order if realized_mask[i]][:TOP_N]
        if not top_idx:
            continue
        per_stock = 10000 / len(top_idx)
        picked_returns = y_test_label[top_idx]
        ending_value = float((per_stock * (1 + picked_returns)).sum())
        portfolio_return = round((ending_value / 10000 - 1) * 100, 2)
        tp_key = str(tp.date())
        spy_r = spy_returns.get(tp_key)
        results.append({
            "timepoint": tp_key,
            "model_return_pct": portfolio_return,
            "spy_return_pct": spy_r,
            "beat_spy": (spy_r is not None and portfolio_return > spy_r),
        })
    return results


def summarize(results):
    if not results:
        return {"n": 0, "wins": 0, "avg_model_pct": None, "avg_spy_pct": None}
    n = len(results)
    wins = sum(r["beat_spy"] for r in results)
    avg_model = round(float(np.mean([r["model_return_pct"] for r in results])), 2)
    spy_vals = [r["spy_return_pct"] for r in results if r["spy_return_pct"] is not None]
    avg_spy = round(float(np.mean(spy_vals)), 2) if spy_vals else None
    return {"n": n, "wins": wins, "avg_model_pct": avg_model, "avg_spy_pct": avg_spy}


def main():
    torch.manual_seed(SEED)
    feat = pd.read_parquet(OUT_DIR / "features.parquet")
    feat = feat.sort_values(["ticker", "date"]).reset_index(drop=True)
    all_dates = feat["date"].drop_duplicates().sort_values().reset_index(drop=True)
    spy = pd.read_csv(DATA_DIR / "SPY.csv", parse_dates=["date"])

    print("Computing forward-return labels for new horizons...")
    for h in NEW_HORIZONS:
        col = f"forward_return_{h}"
        feat[col] = feat.groupby("ticker")["close"].shift(-h) / feat["close"] - 1

    summary = {}

    # ---- horizon = 20, reused from existing backtest output ----
    with open(OUT_DIR / "backtest_results.json") as f:
        xgb20 = json.load(f)
    with open(OUT_DIR / "lstm_backtest_results.json") as f:
        lstm20 = json.load(f)
    summary[20] = {
        "xgboost": summarize([{"timepoint": r["timepoint"], "model_return_pct": r["model_return_pct"],
                                "spy_return_pct": r["spy_return_pct"], "beat_spy": r["beat_spy"]} for r in xgb20]),
        "lstm": summarize([{"timepoint": r["timepoint"], "model_return_pct": r["model_return_pct"],
                             "spy_return_pct": r["spy_return_pct"], "beat_spy": r["beat_spy"]} for r in lstm20]),
    }
    print(f"\nHorizon 20 (reused from existing backtest): "
          f"XGB {summary[20]['xgboost']['wins']}/{summary[20]['xgboost']['n']} wins, "
          f"avg {summary[20]['xgboost']['avg_model_pct']}% | "
          f"LSTM {summary[20]['lstm']['wins']}/{summary[20]['lstm']['n']} wins, "
          f"avg {summary[20]['lstm']['avg_model_pct']}%")

    all_xgb_results = {20: xgb20}
    all_lstm_results = {20: lstm20}

    for h in NEW_HORIZONS:
        print(f"\n=== Horizon = {h} trading days ===")
        label_col = f"forward_return_{h}"
        spy_returns = spy_horizon_returns(spy, h, all_dates)

        print("  XGBoost walk-forward...")
        xgb_results = run_xgb_horizon(feat, label_col, h, all_dates, spy_returns)
        all_xgb_results[h] = xgb_results
        gc.collect()

        print("  Indexing LSTM sequences for this horizon...")
        idx_store = HorizonSequenceIndex(feat, label_col)
        rng = np.random.default_rng(SEED)
        print("  LSTM walk-forward...")
        lstm_results = run_lstm_horizon(idx_store, h, all_dates, spy_returns, rng)
        all_lstm_results[h] = lstm_results

        # Free this horizon's ~2.6-3GB sequence index BEFORE the next
        # horizon's XGBoost step starts, not after -- otherwise it sits
        # alive (still bound to the `idx_store` name) through the next
        # loop iteration's XGBoost run, stacking on top of `feat` and
        # whatever XGBoost/pandas transients that step allocates. That
        # stacking is exactly what OOM-killed the first attempt at this
        # sweep (partway into horizon 40's XGBoost step, right after
        # horizon 10 finished) -- feat's own footprint plus a leftover
        # idx_store from the prior horizon was enough to blow past this
        # box's ~7.8GB cgroup limit.
        del idx_store
        gc.collect()

        summary[h] = {"xgboost": summarize(xgb_results), "lstm": summarize(lstm_results)}
        print(f"  XGB: {summary[h]['xgboost']['wins']}/{summary[h]['xgboost']['n']} wins, "
              f"avg model {summary[h]['xgboost']['avg_model_pct']}% vs SPY {summary[h]['xgboost']['avg_spy_pct']}%")
        print(f"  LSTM: {summary[h]['lstm']['wins']}/{summary[h]['lstm']['n']} wins, "
              f"avg model {summary[h]['lstm']['avg_model_pct']}% vs SPY {summary[h]['lstm']['avg_spy_pct']}%")

    with open(OUT_DIR / "horizon_sweep_summary.json", "w") as f:
        json.dump(summary, f, indent=2)
    with open(OUT_DIR / "horizon_sweep_xgb_detail.json", "w") as f:
        json.dump(all_xgb_results, f, indent=2)
    with open(OUT_DIR / "horizon_sweep_lstm_detail.json", "w") as f:
        json.dump(all_lstm_results, f, indent=2)

    print("\n\n=== SUMMARY ===")
    print(f"{'Horizon':>8} | {'XGB wins':>9} {'XGB avg%':>9} {'SPY avg%':>9} | {'LSTM wins':>10} {'LSTM avg%':>10} {'SPY avg%':>9}")
    for h in sorted(summary.keys()):
        x, l = summary[h]["xgboost"], summary[h]["lstm"]
        xgb_wins_str = f"{x['wins']}/{x['n']}"
        lstm_wins_str = f"{l['wins']}/{l['n']}"
        print(f"{h:>8} | {xgb_wins_str:>9} {x['avg_model_pct']!s:>9} {x['avg_spy_pct']!s:>9} | "
              f"{lstm_wins_str:>10} {l['avg_model_pct']!s:>10} {l['avg_spy_pct']!s:>9}")

    print("\nSaved -> out/horizon_sweep_summary.json, horizon_sweep_xgb_detail.json, horizon_sweep_lstm_detail.json")


if __name__ == "__main__":
    main()
