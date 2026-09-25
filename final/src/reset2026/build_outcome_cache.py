"""
Vectorized, survivorship-correct realized outcome cache: for every (ticker,
date) in the Sharadar per-ticker OHLC export, the tradable 40-day-hold return
an execution.realize_position(entry_lag=1, entry_at="open", stop_pct=None,
cost_bps=0) call would produce -- computed WITHOUT calling that function
12M times, by exploiting that with no stop-loss the whole computation is a
per-ticker array shift, identical in spirit to `outcomes.py`'s "expensive
half once, reuse everywhere" split, just for a no-stop composite instead of
a per-cell XGBoost retrain.

WHY NOT THE PANEL'S OWN `forward_return_tradable_40`
-----------------------------------------------------
That column is `close.shift(-40) / open.shift(-1) - 1` (features.py), which
is NaN whenever a ticker's series ends within the next 40 trading days --
exactly the Round 9 bug ("the model literally could not pick a name on the
eve of its blow-up"), because a plain forward-looking shift has nothing to
fall back to at the end of a series. `execution.realize_position` fixes this
with the delisting exit floor: exit at the LAST available close, flagged
`truncated=True`, rather than dropped. This script reproduces that floor
vectorized instead of reimplementing the whole function:

    entry_idx  = i + 1                      (next bar's open; ENTRY_LAG=1)
    exit_idx   = min(i + HORIZON, n - 1)    (40 bars later, or the last bar)
    truncated  = (i + HORIZON) > (n - 1)

This is bit-for-bit what `realize_position` computes for entry_at="open",
entry_lag=1, stop_pct=None (window = future.iloc[0:HORIZON], entry price =
future.iloc[0]'s open, exit price = window's last close) -- verified against
that function's source, not assumed. `--verify-sample` below spot-checks N
random (ticker, date) pairs against the real function and aborts on any
mismatch, same discipline as `outcomes.py`'s reference gate.

OUTPUT
    <MAIN_ROOT>/out/reset2026/outcome_cache.parquet
        ticker, date, gross_return_40, truncated
    Plus one row per date for "SPY" and "USMV" (same construction, same cache).
"""
import argparse
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

MAIN_ROOT = Path("/Users/ggraham/pipe_dream/final")
MAIN_SRC = MAIN_ROOT / "src"
if str(MAIN_SRC) not in sys.path:
    sys.path.insert(0, str(MAIN_SRC))
from execution import realize_position  # noqa: E402

OHLC_DIR = MAIN_ROOT / "scripts" / "td_data_sharadar"
SPY_CSV = MAIN_ROOT / "scripts" / "td_data_local" / "SPY.csv"
USMV_CSV = MAIN_ROOT / "data" / "benchmarks" / "USMV.csv"
OUT_DIR = MAIN_ROOT / "out" / "reset2026"
OUT = OUT_DIR / "outcome_cache.parquet"

HORIZON = 40
ENTRY_LAG = 1


def vectorized_outcomes(g: pd.DataFrame):
    """g: one ticker's OHLC, sorted by date. Returns arrays (gross_return,
    truncated) aligned to g's rows."""
    n = len(g)
    open_ = g["open"].to_numpy(np.float64)
    close = g["close"].to_numpy(np.float64)
    idx = np.arange(n)
    entry_idx = idx + ENTRY_LAG
    exit_idx = np.minimum(idx + HORIZON, n - 1)
    valid = entry_idx <= n - 1
    entry_price = np.where(valid, open_[np.clip(entry_idx, 0, n - 1)], np.nan)
    exit_price = close[exit_idx]
    with np.errstate(divide="ignore", invalid="ignore"):
        gross = np.where(valid & (entry_price > 0) & np.isfinite(entry_price) & np.isfinite(exit_price),
                          exit_price / entry_price - 1.0, np.nan)
    truncated = (idx + HORIZON) > (n - 1)
    return gross.astype(np.float32), truncated


def verify_sample(price_by_ticker, cache_df, n_samples=500, seed=0):
    rng = np.random.default_rng(seed)
    cache_idx = cache_df.set_index(["ticker", "date"])
    tickers = cache_df["ticker"].unique()
    checked = 0
    mismatches = 0
    for _ in range(n_samples * 3):
        if checked >= n_samples:
            break
        t = rng.choice(tickers)
        g = price_by_ticker.get(t)
        if g is None or len(g) < 5:
            continue
        i = int(rng.integers(0, len(g)))
        tp = g["date"].iloc[i]
        pos = realize_position(g, tp, HORIZON, entry_lag=ENTRY_LAG, entry_at="open",
                               stop_pct=None, cost_bps=0.0)
        row = cache_idx.loc[(t, tp)] if (t, tp) in cache_idx.index else None
        checked += 1
        cached_gross = None if row is None else row["gross_return_40"]
        if pos is None:
            if cached_gross is not None and np.isfinite(cached_gross):
                mismatches += 1
                print(f"  MISMATCH {t} {tp.date()}: realize_position=None, cache={cached_gross}")
            continue
        if cached_gross is None or not np.isfinite(cached_gross):
            mismatches += 1
            print(f"  MISMATCH {t} {tp.date()}: realize_position={pos['gross_return']:.6f}, cache=NaN")
            continue
        if abs(pos["gross_return"] - cached_gross) > 1e-5:
            mismatches += 1
            print(f"  MISMATCH {t} {tp.date()}: realize_position={pos['gross_return']:.6f}, "
                  f"cache={cached_gross:.6f}")
    print(f"verify_sample: {checked} checked, {mismatches} mismatches")
    if mismatches:
        raise SystemExit(f"ABORT: outcome cache disagrees with execution.realize_position "
                          f"on {mismatches}/{checked} sampled (ticker, date) pairs")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--verify-samples", type=int, default=500)
    args = ap.parse_args()

    t0 = time.time()
    print(f"loading OHLC panel from {OHLC_DIR} ...", flush=True)
    from execution import load_ohlc_panel
    price_by_ticker = load_ohlc_panel([OHLC_DIR])
    print(f"  {len(price_by_ticker):,} tickers ({time.time()-t0:.0f}s)", flush=True)

    frames = []
    for i, (ticker, g) in enumerate(price_by_ticker.items(), 1):
        g = g.sort_values("date").reset_index(drop=True)
        gross, truncated = vectorized_outcomes(g)
        frames.append(pd.DataFrame({
            "ticker": ticker, "date": g["date"].to_numpy(),
            "gross_return_40": gross, "truncated": truncated,
        }))
        if i % 1000 == 0:
            print(f"  {i:,}/{len(price_by_ticker):,} tickers ({time.time()-t0:.0f}s)", flush=True)

    for name, path in (("SPY", SPY_CSV), ("USMV", USMV_CSV)):
        g = pd.read_csv(path, usecols=["date", "open", "high", "low", "close"], parse_dates=["date"])
        g = g.sort_values("date").reset_index(drop=True)
        gross, truncated = vectorized_outcomes(g)
        frames.append(pd.DataFrame({
            "ticker": name, "date": g["date"].to_numpy(),
            "gross_return_40": gross, "truncated": truncated,
        }))
        print(f"  benchmark {name}: {len(g):,} rows ({time.time()-t0:.0f}s)", flush=True)

    cache = pd.concat(frames, ignore_index=True)
    print(f"total rows: {len(cache):,}, coverage {cache['gross_return_40'].notna().mean():.1%} "
          f"({time.time()-t0:.0f}s)", flush=True)

    print(f"verifying {args.verify_samples} random samples against execution.realize_position "
          f"directly ...", flush=True)
    verify_sample(price_by_ticker, cache, n_samples=args.verify_samples)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pandas(cache, preserve_index=False), OUT)
    print(f"\n-> {OUT}  ({time.time()-t0:.0f}s total)", flush=True)


if __name__ == "__main__":
    sys.exit(main())
