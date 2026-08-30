"""
Query one or more tickers and get a clear BUY / NO BUY verdict from both
models, as of the most recent available trading day. This is the "should I
buy this" counterpart to query_day.py (which answers "what would the models
buy on date T") and score_watchlist.py (which reports raw scores/ranks for
a watchlist without a verdict) -- same training procedure as both, just
framed as an explicit recommendation per ticker.

How the verdict is decided: both models are trained (XGBoost fresh, LSTM
fresh) the same way current_signal.py / lstm_current_signal.py do -- on all
available labeled history through today, no lookahead -- then used to score
the ENTIRE current universe (not just the tickers you asked about), because
a probability only means something relative to the rest of the market that
day. Each queried ticker's rank within that full universe is converted to a
percentile; the label both models were trained on is itself defined as
"top 25% of forward returns" (see features.py / models/final-buy-no-buy-
model.md), so a ticker lands on a BUY verdict here if -- and only if -- it
falls in that same top quartile by the model's own prediction, mirroring
the exact definition the model was trained against rather than an arbitrary
probability cutoff like 0.5 (which would rarely trigger on a ~25%-positive-
rate classifier anyway).

Usage:
    python3 recommend.py AAPL
    python3 recommend.py AAPL MSFT NVDA TSLA

Output: a verdict table printed to the terminal, plus out/recommend_<date>.json
with the full detail (probabilities, ranks, percentiles, context features).
"""
import argparse
import json

import numpy as np
import pandas as pd
import torch
from xgboost import XGBClassifier

from features import FEATURE_COLS, LABEL_COL, OUT_DIR, latest_complete_date
from lstm_backtest import SequenceIndex, train_lstm, CUTOFF_PERCENTILE, SEED

XGB_CUTOFF_PERCENTILE = 75   # matches current_signal.py / the label's own definition
LSTM_TRAIN_CAP = 150000      # matches current_signal.py / lstm_current_signal.py

BUY_PERCENTILE_THRESHOLD = 0.25  # top quartile by rank -> BUY, same cut the label uses

CONTEXT_COLS = ["close", "momentum_20", "momentum_60", "momentum_120",
                "relative_strength_20", "pct_from_high_252", "pct_from_low_252", "volatility_20"]


def verdict_from_percentile(pct):
    if pct is None:
        return "N/A (no data)"
    return "BUY" if pct <= BUY_PERCENTILE_THRESHOLD else "NO BUY"


def combined_verdict(xgb_v, lstm_v):
    if xgb_v.startswith("N/A") or lstm_v.startswith("N/A"):
        return "N/A"
    if xgb_v == "BUY" and lstm_v == "BUY":
        return "BUY -- both models agree"
    if xgb_v == "NO BUY" and lstm_v == "NO BUY":
        return "PASS -- both models agree"
    return "MIXED -- models disagree"


def main():
    parser = argparse.ArgumentParser(description="Get both models' buy/no-buy verdict for one or more tickers.")
    parser.add_argument("tickers", nargs="+", help="One or more ticker symbols, e.g. AAPL MSFT NVDA")
    args = parser.parse_args()
    watchlist = [t.upper() for t in args.tickers]

    feat = pd.read_parquet(OUT_DIR / "features.parquet")
    feat = feat.sort_values(["ticker", "date"]).reset_index(drop=True)
    latest_date = latest_complete_date(feat)

    missing = [t for t in watchlist if t not in feat["ticker"].unique()]
    if missing:
        print(f"WARNING: no data for {missing} -- these will show as N/A below")

    print(f"Training both models on all available history through {latest_date.date()} "
          f"(no lookahead) -- this takes a bit for the LSTM...")

    # ---------- XGBoost ----------
    train = feat.dropna(subset=FEATURE_COLS + [LABEL_COL])
    cutoff_val_xgb = np.percentile(train[LABEL_COL], XGB_CUTOFF_PERCENTILE)
    y_train = (train[LABEL_COL] > cutoff_val_xgb).astype(int)
    xgb_model = XGBClassifier(n_estimators=100, max_depth=3, learning_rate=0.1,
                               eval_metric="logloss", verbosity=0)
    xgb_model.fit(train[FEATURE_COLS], y_train)

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

    print(f"\n=== Buy / No-Buy recommendation as of {latest_date.date()} ===")
    print(f"(Verdict = ticker ranks in the top {int(BUY_PERCENTILE_THRESHOLD*100)}% of the "
          f"{xgb_universe_n}-ticker universe by predicted probability -- the same top-quartile "
          f"cutoff both models were trained against.)\n")

    header = f"{'TICKER':<8}{'XGB proba':>10}{'XGB rank':>14}{'XGB verdict':>14}   " \
             f"{'LSTM proba':>10}{'LSTM rank':>14}{'LSTM verdict':>14}   {'COMBINED'}"
    print(header)
    print("-" * len(header))

    out_rows = []
    for t in watchlist:
        row = merged[merged["ticker"] == t]
        if row.empty:
            print(f"{t:<8}  no data available -- ticker missing from the universe or no current features")
            out_rows.append({"ticker": t, "status": "no data"})
            continue
        r = row.iloc[0]

        xgb_pct = r["xgb_rank"] / xgb_universe_n
        xgb_verdict = verdict_from_percentile(xgb_pct)

        if pd.notna(r["lstm_buy_proba"]):
            lstm_pct = r["lstm_rank"] / lstm_universe_n
            lstm_verdict = verdict_from_percentile(lstm_pct)
        else:
            lstm_pct, lstm_verdict = None, "N/A (no data)"

        combo = combined_verdict(xgb_verdict, lstm_verdict)

        xgb_rank_str = f"{int(r['xgb_rank'])}/{xgb_universe_n}"
        if pd.notna(r["lstm_buy_proba"]):
            lstm_proba_str = f"{r['lstm_buy_proba']:.4f}"
            lstm_rank_str = f"{int(r['lstm_rank'])}/{lstm_universe_n}"
        else:
            lstm_proba_str = "n/a"
            lstm_rank_str = "n/a"

        print(f"{t:<8}{r['xgb_buy_proba']:>10.4f}{xgb_rank_str:>14}{xgb_verdict:>14}   "
              f"{lstm_proba_str:>10}{lstm_rank_str:>14}{lstm_verdict:>14}   {combo}")

        out_rows.append({
            "ticker": t,
            "close": round(float(r["close"]), 2),
            "xgb_buy_proba": round(float(r["xgb_buy_proba"]), 4),
            "xgb_rank": f"{int(r['xgb_rank'])}/{xgb_universe_n}",
            "xgb_percentile": round(float(xgb_pct), 4),
            "xgb_verdict": xgb_verdict,
            "lstm_buy_proba": round(float(r["lstm_buy_proba"]), 4) if pd.notna(r["lstm_buy_proba"]) else None,
            "lstm_rank": f"{int(r['lstm_rank'])}/{lstm_universe_n}" if pd.notna(r["lstm_rank"]) else None,
            "lstm_percentile": round(float(lstm_pct), 4) if lstm_pct is not None else None,
            "lstm_verdict": lstm_verdict,
            "combined_verdict": combo,
            "momentum_20": round(float(r["momentum_20"]), 4),
            "momentum_60": round(float(r["momentum_60"]), 4),
            "momentum_120": round(float(r["momentum_120"]), 4),
            "pct_from_high_252": round(float(r["pct_from_high_252"]), 4),
            "pct_from_low_252": round(float(r["pct_from_low_252"]), 4),
            "volatility_20": round(float(r["volatility_20"]), 4),
        })

    result = {
        "as_of_date": str(pd.Timestamp(latest_date).date()),
        "buy_percentile_threshold": BUY_PERCENTILE_THRESHOLD,
        "xgb_universe_size": xgb_universe_n,
        "lstm_universe_size": lstm_universe_n,
        "xgb_label_cutoff_return": round(float(cutoff_val_xgb), 4),
        "lstm_label_cutoff_return": round(float(cutoff_val_lstm), 4),
        "recommendations": out_rows,
    }
    out_path = OUT_DIR / f"recommend_{latest_date.date()}.json"
    with open(out_path, "w") as f:
        json.dump(result, f, indent=2)
    print(f"\nSaved -> {out_path}")
    print("\nReminder: this is a relative call (top quartile of today's universe by predicted "
          "probability), not a probability of positive return in isolation -- same framing the "
          "rest of this project's 'top 10' lists use. Not investment advice.")


if __name__ == "__main__":
    main()
