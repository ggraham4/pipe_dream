"""
Amihud (2002) illiquidity measure -- candidate factor #3 (per Gabe's
"go ahead", 2026-09-22). ILLIQ_i,t = trailing-20-day mean of
|daily_return_i| / dollar_volume_i,t, using closeunadj*volume for dollar
volume (the SAME convention `downcap_universe.py` already uses for its
liquidity floor -- reusing an established window/basis, not inventing a
new one). Mechanism: price impact per dollar traded is a direct measure
of how hard a name is to trade; investors demand compensation for holding
illiquid assets (Amihud 2002's own well-cited result). Hypothesized sign:
+1 (higher illiquidity -> higher expected return, the illiquidity
premium) -- a candidate assigned sign, tested against the measurement
next, per this project's own IC-screen discipline (log_market_cap,
book_to_market were tested the same way).

Usage: python3 build_amihud_feature.py
Output: out/reset2026/amihud_feature.parquet (ticker, date, amihud_20)
"""
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

MAIN_ROOT = Path("/Users/ggraham/pipe_dream/final")
STOCKS_DIR = MAIN_ROOT / "data" / "sharadar" / "panel" / "stocks"
OHLC_DIR = MAIN_ROOT / "scripts" / "td_data_sharadar"
OUT = MAIN_ROOT / "out" / "reset2026" / "amihud_feature.parquet"

WINDOW = 20  # matches downcap_universe.py's DOLLAR_VOL_WINDOW convention


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def universe_tickers():
    return set(p.stem for p in OHLC_DIR.glob("*.csv"))


def main():
    t0 = time.time()
    tickers = universe_tickers()
    log(f"universe: {len(tickers):,} tickers")

    months = sorted(STOCKS_DIR.glob("*.parquet"))
    frames = []
    for i, f in enumerate(months, 1):
        d = pd.read_parquet(f, columns=["ticker", "date", "closeunadj", "volume"])
        d = d[d["ticker"].isin(tickers)]
        d = d[d["closeunadj"].notna() & (d["closeunadj"] > 0) & d["volume"].notna()]
        if not d.empty:
            frames.append(d)
        if i % 60 == 0 or i == len(months):
            log(f"  {i}/{len(months)} months loaded ({time.time()-t0:.0f}s)")
    panel = pd.concat(frames, ignore_index=True)
    panel["date"] = pd.to_datetime(panel["date"])
    panel = panel.sort_values(["ticker", "date"]).reset_index(drop=True)
    log(f"loaded {len(panel):,} rows ({time.time()-t0:.0f}s)")

    log("computing daily return, dollar volume, and Amihud ratio ...")
    panel["ret"] = panel.groupby("ticker")["closeunadj"].pct_change()
    panel["dollar_vol"] = panel["closeunadj"] * panel["volume"]
    panel["illiq_daily"] = np.where(panel["dollar_vol"] > 0,
                                     panel["ret"].abs() / panel["dollar_vol"], np.nan)

    log(f"rolling {WINDOW}-day mean (causal) ...")
    panel["amihud_20"] = (panel.groupby("ticker")["illiq_daily"]
                                .transform(lambda s: s.rolling(WINDOW, min_periods=WINDOW // 2).mean()))

    coverage = panel["amihud_20"].notna().mean()
    log(f"coverage: {coverage:.1%} ({time.time()-t0:.0f}s)")

    out = panel[["ticker", "date", "amihud_20"]].copy()
    out["amihud_20"] = out["amihud_20"].astype(np.float64)
    out["date"] = out["date"].dt.strftime("%Y-%m-%d")
    pq.write_table(pa.Table.from_pandas(out, preserve_index=False), OUT)
    log(f"\n-> {OUT} ({len(out):,} rows, {time.time()-t0:.0f}s total)")


if __name__ == "__main__":
    main()
