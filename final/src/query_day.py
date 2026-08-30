"""
Query both models' buy picks for an arbitrary date -- historical or the most
recent available trading day. Generalizes current_signal.py / lstm_current_
signal.py (which only ever score "today") and the point-in-time embargo
training in backtest.py / lstm_backtest.py (which only ever score one of the
8 fixed walk-forward timepoints) into a single script that takes any date.

Point-in-time correctness: for a query date T, both models train ONLY on
rows/sequences whose OWN forward-return label (horizon = FORWARD_WINDOW
trading days, imported from features.py -- currently 40, changed from 20 on
2026-08-27) had already resolved by T (row date <= T - FORWARD_WINDOW
trading days, by trading-day position, not calendar days) -- the same
embargo rule used everywhere else in this project. This means querying a
historical date reproduces exactly what the model would have said on that
day, with no lookahead into data that didn't exist yet as of T. Each query
retrains both models from scratch at T -- this is intentionally the same
"real" training procedure as every other script in this repo, not a
cached/precomputed lookup, so a query is only as fast as one walk-forward
retrain (XGBoost: seconds; LSTM: ~10-30s depending on pool size).

If T is old enough that its own forward return has resolved (i.e. there's a
trading date at least FORWARD_WINDOW trading days after T in the dataset),
each pick's REALIZED forward return is also reported, so a historical query
doubles as a single-timepoint backtest. If T is within the trailing
~FORWARD_WINDOW-trading-day window of the data (including the most recent
available date), realized return isn't shown -- it hasn't happened yet --
this is a live buy signal, not a backtested outcome.

Usage:
    python3 query_day.py                    # most recent available date
    python3 query_day.py 2024-06-15         # nearest trading date <= this
    python3 query_day.py 2024-06-15 --top 5

Output: printed tables for both models + a JSON file at
out/query_<date>.json with the full picks, metadata, and overlap.
"""
import argparse
import json

import numpy as np
import pandas as pd
import torch
from xgboost import XGBClassifier

from features import FEATURE_COLS, FORWARD_WINDOW, LABEL_COL, OUT_DIR, latest_complete_date
from lstm_backtest import SequenceIndex, train_lstm, CUTOFF_PERCENTILE as LSTM_CUTOFF_PCT, SEED

XGB_CUTOFF_PERCENTILE = 75
LSTM_TRAIN_CAP = 150000  # matches the one-off production LSTM scripts, not the 8x-repeated backtest's 40k cap

CONTEXT_COLS = ["close", "momentum_20", "momentum_60", "momentum_120",
                "relative_strength_20", "pct_from_high_252", "pct_from_low_252", "volatility_20"]


def nearest_trading_date(target, available_dates):
    target = pd.Timestamp(target)
    candidates = available_dates[available_dates <= target]
    return candidates.max() if len(candidates) else None


def embargo_cutoff(tp, all_dates, embargo_days=FORWARD_WINDOW):
    idx = all_dates[all_dates == tp].index[0]
    if idx < embargo_days:
        return None
    return all_dates.iloc[idx - embargo_days]


def run_xgb(feat, tp, train_cutoff_date, top_n):
    train = feat[feat["date"] <= train_cutoff_date].dropna(subset=FEATURE_COLS + [LABEL_COL])
    if len(train) < 500:
        return None, {"error": f"only {len(train)} training rows available before {train_cutoff_date.date()}"}

    cutoff_val = np.percentile(train[LABEL_COL], XGB_CUTOFF_PERCENTILE)
    y_train = (train[LABEL_COL] > cutoff_val).astype(int)
    model = XGBClassifier(n_estimators=100, max_depth=3, learning_rate=0.1,
                           eval_metric="logloss", verbosity=0)
    model.fit(train[FEATURE_COLS], y_train)

    test_rows = feat[feat["date"] == tp].dropna(subset=FEATURE_COLS).copy()
    if test_rows.empty:
        return None, {"error": f"no scoreable rows at {tp.date()}"}
    test_rows["buy_proba"] = model.predict_proba(test_rows[FEATURE_COLS])[:, 1]
    top = test_rows.sort_values("buy_proba", ascending=False).head(top_n)

    out = top[["ticker", "buy_proba"] + CONTEXT_COLS + [LABEL_COL]].copy()
    out = out.rename(columns={LABEL_COL: "realized_fwd_return"})
    out["buy_proba"] = out["buy_proba"].round(4)
    meta = {"train_rows": int(len(train)), "label_cutoff_return": round(float(cutoff_val), 4),
            "universe_scored": int(len(test_rows))}
    return out, meta


def run_lstm(idx_store, feat, tp, train_cutoff_date, top_n, rng):
    train_mask = (idx_store.dates <= np.datetime64(train_cutoff_date)) & ~np.isnan(idx_store.labels)
    n_avail = int(train_mask.sum())
    if n_avail < 500:
        return None, {"error": f"only {n_avail} training sequences available before {train_cutoff_date.date()}"}

    pool = np.where(train_mask)[0]
    if len(pool) > LSTM_TRAIN_CAP:
        pool = rng.choice(pool, size=LSTM_TRAIN_CAP, replace=False)

    X_train_raw = idx_store.sequences_for(pool)
    y_train_raw = idx_store.labels[pool]
    cutoff_val = np.percentile(y_train_raw, LSTM_CUTOFF_PCT)
    y_train = (y_train_raw > cutoff_val).astype(np.float32)

    mean = X_train_raw.reshape(-1, X_train_raw.shape[-1]).mean(axis=0)
    std = X_train_raw.reshape(-1, X_train_raw.shape[-1]).std(axis=0)
    std[std == 0] = 1.0
    X_train = (X_train_raw - mean) / std

    model, best_epoch, best_val = train_lstm(X_train, y_train, rng, X_train.shape[-1])

    test_mask = idx_store.dates == np.datetime64(tp)
    test_idx = np.where(test_mask)[0]
    if len(test_idx) == 0:
        return None, {"error": f"no scoreable sequences at {tp.date()}"}

    X_test = (idx_store.sequences_for(test_idx) - mean) / std
    with torch.no_grad():
        probs = torch.sigmoid(model(torch.tensor(X_test, dtype=torch.float32))).numpy()
    tickers = idx_store.tickers_for(test_idx)
    labels = idx_store.labels[test_idx]

    order = np.argsort(-probs)[:top_n]
    latest_feat = feat[feat["date"] == tp].set_index("ticker")
    rows = []
    for i in order:
        t = str(tickers[i])
        row = {"ticker": t, "buy_proba": round(float(probs[i]), 4)}
        for c in CONTEXT_COLS:
            row[c] = float(latest_feat.loc[t, c]) if t in latest_feat.index else None
        lab = labels[i]
        row["realized_fwd_return"] = float(lab) if not np.isnan(lab) else None
        rows.append(row)
    out = pd.DataFrame(rows)
    meta = {"train_sequences": int(len(pool)), "label_cutoff_return": round(float(cutoff_val), 4),
            "best_epoch": best_epoch, "universe_scored": int(len(test_idx))}
    return out, meta


def main():
    parser = argparse.ArgumentParser(description="Query both models' buy picks for a given date.")
    parser.add_argument("date", nargs="?", default=None,
                         help="YYYY-MM-DD. Defaults to the most recent available trading date.")
    parser.add_argument("--top", type=int, default=10, help="Number of picks to show per model (default 10).")
    args = parser.parse_args()

    feat = pd.read_parquet(OUT_DIR / "features.parquet")
    feat = feat.sort_values(["ticker", "date"]).reset_index(drop=True)
    all_dates = feat["date"].drop_duplicates().sort_values().reset_index(drop=True)

    if args.date is None:
        tp = latest_complete_date(feat)
    else:
        tp = nearest_trading_date(args.date, all_dates)
        if tp is None:
            print(f"No trading date on or before {args.date} in the dataset "
                  f"(earliest available: {all_dates.min().date()}).")
            return
        if tp.date() != pd.Timestamp(args.date).date():
            print(f"Note: {args.date} isn't a trading date on file -- using the "
                  f"nearest prior trading date, {tp.date()}.")

    train_cutoff_date = embargo_cutoff(tp, all_dates)
    if train_cutoff_date is None:
        print(f"Not enough history before {tp.date()} to apply the {FORWARD_WINDOW}-trading-day "
              f"embargo -- try a date at least ~{FORWARD_WINDOW} trading days after "
              f"{all_dates.min().date()}.")
        return

    idx_tp = all_dates[all_dates == tp].index[0]
    is_realized = idx_tp <= (len(all_dates) - 1 - FORWARD_WINDOW)

    print(f"Querying {tp.date()} (point-in-time: trained only on data through "
          f"{train_cutoff_date.date()}, {FORWARD_WINDOW}-trading-day embargo applied)")
    if is_realized:
        print(f"This date's own {FORWARD_WINDOW}-trading-day forward return has resolved -- "
              "showing it for each pick (this doubles as a single-timepoint backtest).")
    else:
        print(f"This date is within the trailing ~{FORWARD_WINDOW} trading days of available data -- "
              "forward return hasn't resolved yet. Live buy signal only, no realized return.")

    rng = np.random.default_rng(SEED)
    torch.manual_seed(SEED)

    print("\nTraining XGBoost (point-in-time, no lookahead)...")
    xgb_out, xgb_meta = run_xgb(feat, tp, train_cutoff_date, args.top)

    print("Indexing LSTM sequences and training (point-in-time, no lookahead)...")
    idx_store = SequenceIndex(feat)
    lstm_out, lstm_meta = run_lstm(idx_store, feat, tp, train_cutoff_date, args.top, rng)

    print(f"\n=== XGBoost top {args.top} as of {tp.date()} ===")
    if xgb_out is None:
        print(f"  (unavailable: {xgb_meta['error']})")
    else:
        print(xgb_out.to_string(index=False))

    print(f"\n=== LSTM top {args.top} as of {tp.date()} ===")
    if lstm_out is None:
        print(f"  (unavailable: {lstm_meta['error']})")
    else:
        print(lstm_out.to_string(index=False))

    if xgb_out is not None and lstm_out is not None:
        overlap = sorted(set(xgb_out["ticker"]) & set(lstm_out["ticker"]))
        print(f"\nOverlap ({len(overlap)}/{args.top}): {overlap if overlap else 'none'}")

    result = {
        "query_date_requested": args.date or "latest",
        "resolved_trading_date": str(tp.date()),
        "train_cutoff_date": str(train_cutoff_date.date()),
        "forward_return_realized": bool(is_realized),
        "top_n": args.top,
        "xgboost": {"meta": xgb_meta, "picks": [] if xgb_out is None else xgb_out.to_dict(orient="records")},
        "lstm": {"meta": lstm_meta, "picks": [] if lstm_out is None else lstm_out.to_dict(orient="records")},
    }
    out_path = OUT_DIR / f"query_{tp.date()}.json"
    with open(out_path, "w") as f:
        json.dump(result, f, indent=2, default=str)
    print(f"\nSaved -> {out_path}")


if __name__ == "__main__":
    main()
