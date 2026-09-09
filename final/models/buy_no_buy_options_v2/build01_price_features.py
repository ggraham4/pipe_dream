"""
Build an extended stock price-feature panel for the FULL expanded universe
(~1,653 tickers in scripts/td_data_local/), for the options/buy-no-buy
integration experiments. Reuses features.py's exact feature definitions
plus cumulative_return and volume_20 (raw rolling avg volume) which the
options model needs but the buy/no-buy FEATURE_COLS doesn't.
"""
import glob
import time
from pathlib import Path
import pandas as pd
import numpy as np

REPO_FINAL = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_FINAL / "scripts" / "td_data_local"
OUT_DIR = Path(__file__).resolve().parent

MOMENTUM_WINDOWS = [5, 20, 60, 120]
VOL_WINDOWS = [20, 60]
VOLUME_WINDOW = 20
RS_WINDOW = 20
PRICE_LEVEL_WINDOW = 252

t0 = time.time()
files = sorted(DATA_DIR.glob("*.csv"))
frames = []
for f in files:
    df = pd.read_csv(f, parse_dates=["date"])
    df["ticker"] = f.stem
    frames.append(df)
raw = pd.concat(frames, ignore_index=True)
raw = raw.sort_values(["ticker", "date"]).reset_index(drop=True)
print(f"Loaded {raw['ticker'].nunique()} tickers, {len(raw)} rows in {time.time()-t0:.1f}s, "
      f"{raw['date'].min().date()} to {raw['date'].max().date()}", flush=True)

spy = raw[raw["ticker"] == "SPY"].sort_values("date").copy()
spy["spy_momentum_20"] = spy["close"].pct_change(RS_WINDOW)
spy = spy[["date", "spy_momentum_20"]]

t1 = time.time()
pieces = []
for ticker, g in raw.groupby("ticker", sort=False):
    if ticker == "SPY":
        continue
    g = g.sort_values("date").reset_index(drop=True).copy()
    g["daily_return"] = g["close"].pct_change()
    g["cumulative_return"] = (1 + g["daily_return"].fillna(0)).cumprod() - 1
    for w in MOMENTUM_WINDOWS:
        g[f"momentum_{w}"] = g["close"].pct_change(w)
    for w in VOL_WINDOWS:
        g[f"volatility_{w}"] = g["daily_return"].rolling(w).std()
    g["volume_20"] = g["volume"].rolling(VOLUME_WINDOW).mean()
    g["volume_ratio_20"] = g["volume"] / g["volume_20"]

    rolling_high = g["close"].rolling(PRICE_LEVEL_WINDOW).max()
    rolling_low = g["close"].rolling(PRICE_LEVEL_WINDOW).min()
    g["pct_from_high_252"] = (g["close"] - rolling_high) / rolling_high
    g["pct_from_low_252"] = (g["close"] - rolling_low) / rolling_low

    g = g.merge(spy, on="date", how="left")
    g["relative_strength_20"] = g["momentum_20"] - g["spy_momentum_20"]
    g["forward_return_40"] = g["close"].shift(-40) / g["close"] - 1

    g = g.rename(columns={"ticker": "act_symbol"})
    pieces.append(g[["act_symbol", "date", "close", "volume", "daily_return",
                      "cumulative_return", "momentum_5", "momentum_20", "momentum_60",
                      "momentum_120", "volatility_20", "volatility_60", "volume_20",
                      "volume_ratio_20", "relative_strength_20", "pct_from_high_252",
                      "pct_from_low_252", "forward_return_40"]])

out = pd.concat(pieces, ignore_index=True)
print(f"Feature engineering done in {time.time()-t1:.1f}s, shape={out.shape}", flush=True)
out.to_parquet(OUT_DIR / "expanded_stock_features.parquet")
print(f"Wrote expanded_stock_features.parquet. Total time {time.time()-t0:.1f}s", flush=True)
