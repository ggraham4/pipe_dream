"""
Export the Sharadar price panel to per-ticker CSVs, so realistic execution
works on the rebuilt universe.

WHY
---
`execution.py` realizes positions by reading one CSV per ticker out of
PRICE_DIRS (td_data_local, td_data_delisted...). Those directories hold
1,932 tickers. The rebuilt universe has 4,011, so most picks would have no
price series and `realize_portfolio` would report them untradable -- which
would look like a modest execution failure while actually being a silent
re-imposition of the old survivor universe at the execution layer.

Writing the panel out in the SAME schema execution.py already expects means
zero changes to any execution code path: no new loader class, no new
branch inside realize_position, and the price_discontinuity segmentation
machinery keeps working untouched. The only change needed elsewhere is
which directory PRICE_DIRS points at.

THE OLD DIRECTORIES MUST NOT BE MIXED IN
----------------------------------------
`load_ohlc_panel` resolves name collisions by "earliest directory wins", so
listing the Sharadar export first would appear to be enough. It is not, for
two reasons:

  1. td_data_delisted still contains the 41 wrong-issuer files. A ticker
     present there but absent from the export would silently supply another
     company's prices.
  2. The two sources are on different corporate-action bases for ~13% of
     tickers (see the price-basis note). Mixing them would make execution
     prices inconsistent with the features the pick was made on.

So when the walk-forward runs with --universe pit, PRICE_DIRS is this
directory ALONE.

SCHEMA
------
    date, open, high, low, close, volume

Same columns, same order, same split-adjusted basis as the existing CSVs --
which was verified to four decimals against them (AAPL 2015-06-30: existing
31.3575, Sharadar 31.356; volume 177,482,800 vs 177,483,000).

    python3 export_sharadar_ohlc.py
    python3 export_sharadar_ohlc.py --all      # every ticker, not just the universe

OUTPUT
    final/scripts/td_data_sharadar/{TICKER}.csv
"""
import argparse
from pathlib import Path

import pandas as pd

from features import PROJECT_ROOT

PANEL = PROJECT_ROOT / "data" / "sharadar" / "panel" / "stocks"
UNIVERSE = PROJECT_ROOT / "data" / "sharadar" / "pit_universe.parquet"
OUTDIR = PROJECT_ROOT / "scripts" / "td_data_sharadar"
COLS = ["date", "open", "high", "low", "close", "volume"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true",
                    help="export every ticker in the panel, not just universe members")
    a = ap.parse_args()

    if a.all:
        want = None
        print("exporting ALL tickers in the panel")
    else:
        u = pd.read_parquet(UNIVERSE, columns=["ticker"])
        want = set(u["ticker"].astype(str).unique())
        print(f"universe tickers: {len(want):,}")

    months = sorted(PANEL.glob("*.parquet"))
    frames = []
    for i, f in enumerate(months, 1):
        d = pd.read_parquet(f, columns=["ticker", "date", "open", "high",
                                        "low", "close", "volume"])
        if want is not None:
            d = d[d["ticker"].isin(want)]
        if len(d):
            frames.append(d)
        if i % 60 == 0 or i == len(months):
            print(f"  read {i}/{len(months)} months, "
                  f"{sum(len(x) for x in frames):,} rows")
    px = pd.concat(frames, ignore_index=True)
    del frames
    px["date"] = pd.to_datetime(px["date"]).dt.strftime("%Y-%m-%d")
    px = px.sort_values(["ticker", "date"])

    OUTDIR.mkdir(parents=True, exist_ok=True)
    n = 0
    for i, (tk, g) in enumerate(px.groupby("ticker", sort=False), 1):
        g[COLS].to_csv(OUTDIR / f"{tk}.csv", index=False)
        n += len(g)
        if i % 500 == 0:
            print(f"  wrote {i:,} tickers, {n:,} rows")
    print(f"\n{px['ticker'].nunique():,} tickers, {n:,} rows -> {OUTDIR}")

    if want is not None:
        missing = want - set(px["ticker"].unique())
        print(f"universe tickers with no price rows: {len(missing)}")
        if missing:
            print(f"  {sorted(missing)[:20]}")
    print("\nNow run the walk-forward with --universe pit; PRICE_DIRS points")
    print("at this directory alone, deliberately excluding the old CSVs.")


if __name__ == "__main__":
    main()
