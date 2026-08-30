"""
Final LSTM step, mirroring current_signal.py: train on every sequence whose
own forward-return label has already resolved (no lookahead), then score
each ticker's most recent 20-day sequence to produce today's LSTM-based
top-10 buy list, directly comparable to the XGBoost current_top10.
"""
import json

import numpy as np
import pandas as pd
import torch
import torch.nn as nn

from features import FEATURE_COLS, FORWARD_WINDOW, OUT_DIR, MODELS_DIR, latest_complete_date
from lstm_backtest import (
    BuySignalLSTM, SequenceIndex, SEQ_LEN, train_lstm,
    CUTOFF_PERCENTILE, SEED,
)

TOP_N = 10
# Production run: single training pass, so we can afford a larger sample
# than the 8x-repeated walk-forward backtest.
TRAIN_CAP = 150000


def main():
    torch.manual_seed(SEED)
    feat = pd.read_parquet(OUT_DIR / "features.parquet")
    feat = feat.sort_values(["ticker", "date"]).reset_index(drop=True)

    latest_date = np.datetime64(latest_complete_date(feat))
    print(f"Latest available trading date (>=90% universe coverage): {pd.Timestamp(latest_date).date()}")

    print("Indexing sliding-window sequences for all tickers (memory-safe, on-demand slicing)...")
    idx_store = SequenceIndex(feat)

    rng = np.random.default_rng(SEED)
    train_mask = ~np.isnan(idx_store.labels)
    train_pool = np.where(train_mask)[0]
    if len(train_pool) > TRAIN_CAP:
        train_pool = rng.choice(train_pool, size=TRAIN_CAP, replace=False)

    X_train_raw = idx_store.sequences_for(train_pool)
    y_train_raw = idx_store.labels[train_pool]
    cutoff_val = np.percentile(y_train_raw, CUTOFF_PERCENTILE)
    y_train = (y_train_raw > cutoff_val).astype(np.float32)

    mean = X_train_raw.reshape(-1, X_train_raw.shape[-1]).mean(axis=0)
    std = X_train_raw.reshape(-1, X_train_raw.shape[-1]).std(axis=0)
    std[std == 0] = 1.0
    X_train = (X_train_raw - mean) / std

    print(f"Training on {len(train_pool)} sequences, label cutoff (75th pct {FORWARD_WINDOW}d fwd return) = {cutoff_val:.4f}")
    model, best_epoch, best_val = train_lstm(X_train, y_train, rng, X_train.shape[-1])
    print(f"Best epoch {best_epoch}, val_loss {best_val:.4f}")

    # score TODAY: one sequence per ticker, the one ending at latest_date
    today_mask = idx_store.dates == latest_date
    today_idx = np.where(today_mask)[0]
    X_today = (idx_store.sequences_for(today_idx) - mean) / std
    with torch.no_grad():
        probs = torch.sigmoid(model(torch.tensor(X_today, dtype=torch.float32))).numpy()
    today_tickers = idx_store.tickers_for(today_idx)

    order = np.argsort(-probs)[:TOP_N]
    top10 = pd.DataFrame({
        "ticker": today_tickers[order],
        "buy_proba": probs[order].round(4),
    })

    # attach current feature context (close, momentum, etc.) for readability,
    # matching the XGBoost current_top10.csv columns
    latest_feat = feat[feat["date"] == pd.Timestamp(latest_date)].set_index("ticker")
    context_cols = ["close", "momentum_20", "momentum_60", "momentum_120",
                     "relative_strength_20", "pct_from_high_252", "pct_from_low_252", "volatility_20"]
    for c in context_cols:
        top10[c] = top10["ticker"].map(latest_feat[c])

    print(f"\nTop {TOP_N} LSTM buy candidates as of {pd.Timestamp(latest_date).date()}:")
    print(top10.to_string(index=False))

    top10.to_csv(OUT_DIR / "lstm_current_top10.csv", index=False)
    with open(OUT_DIR / "lstm_current_signal_meta.json", "w") as f:
        json.dump({
            "as_of_date": str(pd.Timestamp(latest_date).date()),
            "train_sequences": int(len(train_pool)),
            "forward_window_trading_days": FORWARD_WINDOW,
            "label_cutoff_fwd_return": round(float(cutoff_val), 4),
            "universe_size": int(len(today_idx)),
            "best_epoch": best_epoch,
        }, f, indent=2)

    # Persist the trained model (+ normalization stats, required to score
    # anything new) so a future session doesn't have to retrain from
    # scratch. Same-day fallback/cache keyed to as_of_date, like the
    # XGBoost side -- retrain when the data actually moves forward.
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    torch.save(model.state_dict(), MODELS_DIR / "lstm_current_model.pt")
    np.savez(MODELS_DIR / "lstm_current_norm.npz", mean=mean, std=std)
    with open(MODELS_DIR / "lstm_current_model_meta.json", "w") as f:
        json.dump({
            "as_of_date": str(pd.Timestamp(latest_date).date()),
            "feature_cols": FEATURE_COLS,
            "seq_len": SEQ_LEN,
            "hidden_size": 32,
            "num_layers": 1,
            "forward_window_trading_days": FORWARD_WINDOW,
            "label_cutoff_fwd_return": round(float(cutoff_val), 4),
            "train_sequences": int(len(train_pool)),
            "best_epoch": best_epoch,
        }, f, indent=2)
    print(f"\nSaved model -> out/models/lstm_current_model.pt (as_of {pd.Timestamp(latest_date).date()})")


if __name__ == "__main__":
    main()
