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
- Forward return label horizon = 40 trading days (~2 months). Changed from
  20 to 40 on 2026-08-27 per Gabe's decision after the horizon sweep
  (out/horizon_sweep_summary.json / models/final-buy-no-buy-model.md):
  XGBoost's edge over SPY was largest at 40 days across the 8 walk-forward
  timepoints tested (10/20/40/60). This is now the permanent default for
  every script in the pipeline -- LABEL_COL below is the single source of
  truth other scripts import from, so changing FORWARD_WINDOW here is
  sufficient to retarget the whole pipeline at a new horizon.

All paths below are resolved relative to this file's location (PROJECT_ROOT
= the "final" folder, one level up from src/), NOT hardcoded to any one
machine. Fixed 2026-08-27 after these scripts were delivered with paths
hardcoded to the cloud sandbox they were built in (/root/pipe_dream_final/...,
/tmp/td_data_yf) -- which obviously don't exist on Gabe's Mac. Every other
script in this repo imports DATA_DIR/OUT_DIR/MODELS_DIR from here rather
than hardcoding its own, so this is the only place a path convention change
needs to happen. Expected layout (same on the cloud sandbox and on Gabe's
Mac, since pipe_dream/final/ is mirrored between them):
  final/
    src/            <- this file and every other script live here
    scripts/
      td_data_local/ <- one CSV per ticker, from local_data_pull.py
    out/
      models/        <- saved model checkpoints
"""
import json
import os
import tempfile

import pandas as pd
import numpy as np
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "scripts" / "td_data_local"
OUT_DIR = PROJECT_ROOT / "out"
MODELS_DIR = OUT_DIR / "models"


# --------------------------------------------------------------------------
# Atomic writes -- shared by every script in this repo that writes to out/,
# because the dashboard app polls and re-reads those exact files live while
# a background retrain job (app/lib/data_refresh.py's run_step_sequence) is
# still writing them. A plain df.to_parquet(path) / df.to_csv(path) opens
# and writes `path` directly, so for the whole write duration a concurrent
# reader can see a truncated file -- pyarrow reports that as "Parquet magic
# bytes not found in footer" (hit in practice on features_with_fundamentals_
# beta.parquet, ~6.3M rows, mid-write). Fix: write to a temp file in the
# same directory, then os.replace() into place -- that's atomic on both
# Linux and macOS, so any reader always sees either the complete old file or
# the complete new one, never a partial write.
# --------------------------------------------------------------------------

def _atomic_write(path, write_fn):
    path = Path(path)
    fd, tmp_path = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    os.close(fd)
    try:
        write_fn(tmp_path)
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        raise


def atomic_to_parquet(df, path):
    _atomic_write(path, lambda tmp_path: df.to_parquet(tmp_path))


def atomic_to_csv(df, path, **kwargs):
    _atomic_write(path, lambda tmp_path: df.to_csv(tmp_path, **kwargs))


def atomic_write_json(obj, path, **kwargs):
    def _write(tmp_path):
        with open(tmp_path, "w") as f:
            json.dump(obj, f, **kwargs)
    _atomic_write(path, _write)

MOMENTUM_WINDOWS = [5, 20, 60, 120]
VOL_WINDOWS = [20, 60]
VOLUME_WINDOW = 20
RS_WINDOW = 20
PRICE_LEVEL_WINDOW = 252
FORWARD_WINDOW = 40  # trading days ~ 2 months -- see docstring above
LABEL_COL = f"forward_return_{FORWARD_WINDOW}"
# Round 9 (2026-09-07) -- the TRADABLE label.
#
# LABEL_COL above measures close[t+H] / close[t], i.e. it credits the move
# from the closing print the signal was computed on. That return is not
# obtainable: you cannot rank the universe on close[t] and also have bought
# at close[t]. Training on it teaches the model to favour names that are
# about to gap overnight -- and the diagnostic bears that out, with the
# entire published edge sitting in the 30 of 123 windows whose picks gapped
# up between close[t] and open[t+1].
#
# TRADABLE_LABEL_COL measures close[t+H] / open[t+1]: buy at the first price
# actually available after the signal, hold to the same exit. Use this as
# the training target whenever the backtest is scored with realistic
# execution, so the model is optimizing the return it can actually capture.
TRADABLE_LABEL_COL = f"forward_return_tradable_{FORWARD_WINDOW}"

FEATURE_COLS = [
    "daily_return",
    "momentum_5", "momentum_20", "momentum_60", "momentum_120",
    "volatility_20", "volatility_60",
    "volume_ratio_20",
    "relative_strength_20",
    "pct_from_high_252", "pct_from_low_252",
]

# --------------------------------------------------------------------------
# CANDIDATE features -- computed, screened, and NOT in the model
# --------------------------------------------------------------------------
# These are built into every panel so the screens can see them, and are
# deliberately kept OUT of FEATURE_COLS. Nothing reaches the deployed model by
# being listed here; a candidate enters FEATURE_COLS only after clearing the
# feature_ic screen and then a pre-registered sweep cell. Keeping the two lists
# separate is what stops "we built the column" from quietly becoming "we trade
# the column".
#
# accel_20 (promoted 2026-09-16).
#   Second half of the trailing 20 days minus the first half, in log returns:
#
#       accel_20 = log(close[t] / close[t-10]) - log(close[t-10] / close[t-20])
#
#   momentum_20 is the SUM of 20 daily returns and is therefore invariant to
#   their ORDER -- an uptrend, a downtrend ending where it started, a V and an
#   inverted V all give the identical value. accel_20 is the cheapest statistic
#   that separates them, and it is the ONLY order-aware statistic that survived
#   the 2026-09-16 path-order screen
#   (models/2026-09-16-order-information-in-20-day-paths.md): paired against its
#   own matched shuffles it came back at -1.74 on IC and -1.97 at the traded
#   tail, one sign in 17 of 20 years, empirical p ~0.18 against an exact
#   permutation null. That is weak, not established -- which is exactly why it
#   is a candidate and not a feature.
#
#   The sign says DECELERATING names do better forward, holding the 20-day sum
#   fixed: short-term reversal inside the window.
#
#   Definition fidelity matters here. This must stay numerically identical to
#   screen_path_order.py's version, or the screen's evidence no longer applies
#   to the column being traded. build_accel_feature.py asserts the two agree.
CANDIDATE_FEATURE_COLS = ["accel_20"]
ACCEL_WINDOW = 20        # must equal screen_path_order.WIN


def accel_20(close: pd.Series, window: int = ACCEL_WINDOW) -> pd.Series:
    """Second half minus first half of the trailing `window` log returns.

    The telescoping form -- log(P_t/P_h) - log(P_h/P_0) with h the midpoint --
    is algebraically identical to summing the two halves of the daily log
    returns, and needs three prices instead of twenty-one.

    It is NOT identical when a price is missing inside the window: the
    telescoping form happily spans the gap, while summing daily returns yields
    NaN. The screen this feature came from treats a path with a missing day as
    not being a 20-day path, so that behaviour is reproduced explicitly via the
    validity count rather than inherited by accident.
    """
    h = window // 2
    lp = np.log(close.where(close > 0))
    a = (lp - lp.shift(h)) - (lp.shift(h) - lp.shift(window))
    # every one of the `window` daily log returns in the window must exist
    valid = lp.diff().notna().rolling(window).sum() == window
    return a.where(valid)


def latest_complete_date(feat: pd.DataFrame, min_coverage: float = 0.9) -> pd.Timestamp:
    """
    The most recent date is not always safe to use as "today" at this
    universe size: a local yfinance pull that takes hours across ~1,600
    tickers can straddle a market data update, so a handful of tickers
    pulled last end up with one extra trailing day that most of the
    universe (and, critically, SPY) doesn't have yet. Scoring "today" on
    a date SPY has no row for makes relative_strength_20 -- and therefore
    every row -- NaN, silently producing an empty top-N.

    Fix: pick the latest date where at least `min_coverage` of the full
    ticker universe has a row, instead of the bare .max().
    """
    counts = feat.groupby("date").size()
    total_tickers = feat["ticker"].nunique()
    complete_dates = counts[counts >= min_coverage * total_tickers].index
    return complete_dates.max()


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

        g["accel_20"] = accel_20(g["close"])

        rolling_high = g["close"].rolling(PRICE_LEVEL_WINDOW).max()
        rolling_low = g["close"].rolling(PRICE_LEVEL_WINDOW).min()
        g["pct_from_high_252"] = (g["close"] - rolling_high) / rolling_high
        g["pct_from_low_252"] = (g["close"] - rolling_low) / rolling_low

        g = g.merge(spy, on="date", how="left")
        g["relative_strength_20"] = g["momentum_20"] - g["spy_momentum_20"]

        # forward return label: close FORWARD_WINDOW trading days ahead vs today
        g[LABEL_COL] = g["close"].shift(-FORWARD_WINDOW) / g["close"] - 1
        # tradable variant: same exit, but entered at the next bar's open --
        # the first price obtainable after a signal computed on close[t].
        # See TRADABLE_LABEL_COL's note above.
        g[TRADABLE_LABEL_COL] = (g["close"].shift(-FORWARD_WINDOW)
                                  / g["open"].shift(-1)) - 1

        pieces.append(g)

    out = pd.concat(pieces, ignore_index=True)
    return out


if __name__ == "__main__":
    raw = load_all_tickers()
    print(f"Loaded {raw['ticker'].nunique()} tickers, {len(raw)} rows, "
          f"{raw['date'].min().date()} to {raw['date'].max().date()}")
    feat = build_features(raw)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    atomic_to_parquet(feat, OUT_DIR / "features.parquet")
    print(f"Feature panel: {feat.shape}, "
          f"non-null feature+label rows: {feat.dropna(subset=FEATURE_COLS + [LABEL_COL]).shape[0]}")
