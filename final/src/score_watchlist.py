"""
Score an arbitrary watchlist of tickers with both trained models (XGBoost +
LSTM), using the exact same training procedure as current_signal.py /
lstm_current_signal.py (train on all available labeled history through
today, score today's cross-section) -- just report a wider slice of the
output instead of only the top 10.

Usage: python3 score_watchlist.py TICKER1 TICKER2 ...
"""
import sys
import json

import numpy as np
import pandas as pd
import torch
from xgboost import XGBClassifier

from features import FEATURE_COLS, LABEL_COL, OUT_DIR, latest_complete_date
from lstm_backtest import SequenceIndex, train_lstm, CUTOFF_PERCENTILE, SEED

LSTM_TRAIN_CAP = 150000


def main():
    watchlist = [t.upper() for t in sys.argv[1:]]
    if not watchlist:
        print("Usage: python3 score_watchlist.py TICKER1 TICKER2 ...")
        return

    feat = pd.read_parquet(OUT_DIR / "features.parquet")
    feat = feat.sort_values(["ticker", "date"]).reset_index(drop=True)
    latest_date = latest_complete_date(feat)

    missing = [t for t in watchlist if t not in feat["ticker"].unique()]
    if missing:
        print(f"WARNING: no data for {missing} -- skipping these")

    # ---------- XGBoost ----------
    train = feat.dropna(subset=FEATURE_COLS + [LABEL_COL])
    cutoff_val_xgb = np.percentile(train[LABEL_COL], 75)
    y_train = (train[LABEL_COL] > cutoff_val_xgb).astype(int)
    X_train = train[FEATURE_COLS]

    xgb_model = XGBClassifier(n_estimators=100, max_depth=3, learning_rate=0.1,
                               eval_metric="logloss", verbosity=0)
    xgb_model.fit(X_train, y_train)

    today_rows = feat[feat["date"] == latest_date].dropna(subset=FEATURE_COLS).copy()
    today_rows["xgb_buy_proba"] = xgb_model.predict_proba(today_rows[FEATURE_COLS])[:, 1]
    today_rows["xgb_rank"] = today_rows["xgb_buy_proba"].rank(ascending=False, method="min").astype(int)
    xgb_universe_n = len(today_rows)

    # ---------- LSTM ----------
    torch.manual_seed(SEED)
    idx_store = SequenceIndex(feat)
    rng = np.random.default_rng(SEED)
    lstm_train_mask = ~np.isnan(idx_store.labels)
    lstm_pool = np.where(lstm_train_mask)[0]
    if len(lstm_pool) > LSTM_TRAIN_CAP:
        lstm_pool = rng.choice(lstm_pool, size=LSTM_TRAIN_CAP, replace=False)
    X_train_raw = idx_store.sequences_for(lstm_pool)
    y_train_raw = idx_store.labels[lstm_pool]
    cutoff_val_lstm = np.percentile(y_train_raw, CUTOFF_PERCENTILE)
    y_train_lstm = (y_train_raw > cutoff_val_lstm).astype(np.float32)
    mean = X_train_raw.reshape(-1, X_train_raw.shape[-1]).mean(axis=0)
    std = X_train_raw.reshape(-1, X_train_raw.shape[-1]).std(axis=0)
    std[std == 0] = 1.0
    X_train_lstm = (X_train_raw - mean) / std
    lstm_model, best_epoch, best_val = train_lstm(X_train_lstm, y_train_lstm, rng, X_train_lstm.shape[-1])

    today_mask = idx_store.dates == np.datetime64(latest_date)
    today_idx = np.where(today_mask)[0]
    X_today = (idx_store.sequences_for(today_idx) - mean) / std
    with torch.no_grad():
        lstm_probs = torch.sigmoid(lstm_model(torch.tensor(X_today, dtype=torch.float32))).numpy()
    lstm_tickers = idx_store.tickers_for(today_idx)
    lstm_df = pd.DataFrame({"ticker": lstm_tickers, "lstm_buy_proba": lstm_probs})
    lstm_df["lstm_rank"] = lstm_df["lstm_buy_proba"].rank(ascending=False, method="min").astype(int)
    lstm_universe_n = len(lstm_df)

    merged = today_rows.merge(lstm_df, on="ticker", how="left")

    out_rows = []
    for t in watchlist:
        row = merged[merged["ticker"] == t]
        if row.empty:
            out_rows.append({"ticker": t, "status": "no data"})
            continue
        r = row.iloc[0]
        out_rows.append({
            "ticker": t,
            "close": round(float(r["close"]), 2),
            "xgb_buy_proba": round(float(r["xgb_buy_proba"]), 4),
            "xgb_rank": f"{int(r['xgb_rank'])}/{xgb_universe_n}",
            "lstm_buy_proba": round(float(r["lstm_buy_proba"]), 4) if pd.notna(r["lstm_buy_proba"]) else None,
            "lstm_rank": f"{int(r['lstm_rank'])}/{lstm_universe_n}" if pd.notna(r["lstm_rank"]) else None,
            "momentum_20": round(float(r["momentum_20"]), 4),
            "momentum_60": round(float(r["momentum_60"]), 4),
            "momentum_120": round(float(r["momentum_120"]), 4),
            "pct_from_high_252": round(float(r["pct_from_high_252"]), 4),
            "pct_from_low_252": round(float(r["pct_from_low_252"]), 4),
            "volatility_20": round(float(r["volatility_20"]), 4),
        })

    result = {
        "as_of_date": str(pd.Timestamp(latest_date).date()),
        "xgb_universe_size": xgb_universe_n,
        "lstm_universe_size": lstm_universe_n,
        "xgb_buy_cutoff_used_for_top10": None,  # informational only, ranking is what matters here
        "watchlist": out_rows,
    }
    print(json.dumps(result, indent=2))
    with open(OUT_DIR / "watchlist_scores.json", "w") as f:
        json.dump(result, f, indent=2)


if __name__ == "__main__":
    main()
