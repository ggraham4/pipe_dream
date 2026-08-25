"""
Feature engineering matching the methodology in Gabe's pipe_dream repo
(src/data_loading.py) and the design decisions from the project chat history:

- Price/volume only, no fundamentals (explicit early decision, avoid paid data)
- Momentum at multiple windows (5, 20, 60, 120 trading days)
- Rolling volatility (std of daily returns) at 20/60 day windows
- Volume ratio (rolling average volume) at 20 days
- Relative strength vs SPY (momentum_stock - momentum_SPY) at 20 days
- Price level context: % from 252-day rolling high/low
- Every feature computed using only data strictly before the cutoff date
  (temporal wall / no lookahead, per the explicit rule established in
  the project's chat history)
- Forward return label horizon = 20 trading days, matching the
  most-used horizon across the repo's own XGBoost/LSTM experiments
"""
import pandas as pd
import numpy as np
from pathlib import Path

DATA_DIR = Path("/tmp/td_data")

MOMENTUM_WINDOWS = [5, 20, 60, 120]
VOL_WINDOWS = [20, 60]
VOLUME_WINDOW = 20
RS_WINDOW = 20
PRICE_LEVEL_WINDOW = 252
FORWARD_WINDOW = 20  # trading days ~ 1 month, matches repo's primary horizon

FEATURE_COLS = [
    "daily_return",
    "momentum_5", "momentum_20", "momentum_60", "momentum_120",
    "volatility_20", "volatility_60",
    "volume_ratio_20",
    "relative_strength_20",
    "pct_from_high_252", "pct_from_low_252",
]


def load_all_tickers():
    frames = []
    for f in sorted(DATA_DIR.glob("*.csv")):
        ticker = f.stem
        df = pd.read_csv(f, parse_dates=["date"])
        df["ticker"] = ticker
        frames.append(df)
    data = pd.concat(frames, ignore_index=True)
    data = data.sort_values(["ticker", "date"]).reset_index(drop=True)
    return data


def build_features(data: pd.DataFrame) -> pd.DataFrame:
    """
    data: long format, columns [date, open, high, low, close, volume, ticker]
    Returns same shape with feature columns added, computed per-ticker,
    using only trailing (rolling / shifted) data. SPY relative strength
    is joined in from the SPY sub-frame.
    """
    spy = data[data["ticker"] == "SPY"].sort_values("date").copy()
    spy["spy_momentum_20"] = spy["close"].pct_change(RS_WINDOW)
    spy = spy[["date", "spy_momentum_20"]]

    pieces = []
    for ticker, g in data.groupby("ticker", sort=False):
        if ticker == "SPY":
            continue
        g = g.sort_values("date").reset_index(drop=True).copy()

        g["daily_return"] = g["close"].pct_change()
        for w in MOMENTUM_WINDOWS:
            g[f"momentum_{w}"] = g["close"].pct_change(w)
        for w in VOL_WINDOWS:
            g[f"volatility_{w}"] = g["daily_return"].rolling(w).std()
        g["volume_ratio_20"] = g["volume"] / g["volume"].rolling(VOLUME_WINDOW).mean()

        rolling_high = g["close"].rolling(PRICE_LEVEL_WINDOW).max()
        rolling_low = g["close"].rolling(PRICE_LEVEL_WINDOW).min()
        g["pct_from_high_252"] = (g["close"] - rolling_high) / rolling_high
        g["pct_from_low_252"] = (g["close"] - rolling_low) / rolling_low

        g = g.merge(spy, on="date", how="left")
        g["relative_strength_20"] = g["momentum_20"] - g["spy_momentum_20"]

        # forward return label: close FORWARD_WINDOW trading days ahead vs today
        g["forward_return_20"] = g["close"].shift(-FORWARD_WINDOW) / g["close"] - 1

        pieces.append(g)

    out = pd.concat(pieces, ignore_index=True)
    return out


if __name__ == "__main__":
    raw = load_all_tickers()
    print(f"Loaded {raw['ticker'].nunique()} tickers, {len(raw)} rows, "
          f"{raw['date'].min().date()} to {raw['date'].max().date()}")
    feat = build_features(raw)
    feat.to_parquet("/root/pipe_dream_final/out/features.parquet")
    print(f"Feature panel: {feat.shape}, "
          f"non-null feature+label rows: {feat.dropna(subset=FEATURE_COLS + ['forward_return_20']).shape[0]}")
