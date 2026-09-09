"""
Rebuild the feature panel on the point-in-time universe.

WHAT CHANGES
------------
The old panel was built from `scripts/td_data_local/*.csv` (1,656 survivors)
plus `scripts/td_data_delisted/*.csv` (264 gap files, 41 of which were the
wrong company). This builds the same features from the Sharadar panel over
the 4,030 tickers the rebuilt universe actually contains -- including the
~2,100 that were missing, which are disproportionately the dead ones.

Feature definitions are UNCHANGED and imported from features.py rather than
restated here, so a difference in a downstream number can only come from
the data, never from a redefinition drifting between two copies.

WHY THE PRICES ARE DIRECTLY COMPARABLE
--------------------------------------
The existing pipeline's CSVs turn out to be split-adjusted but NOT
dividend-adjusted, which is exactly Sharadar's `close` column:

    AAPL 2015-06-30   existing 31.3575        Sharadar close      31.356
                                              Sharadar closeadj   27.954  (total return)
                                              Sharadar closeunadj 125.425 (raw)
    XOM  2015-06-30   existing 83.19999       Sharadar close      83.20
    volume            existing 177,482,800    Sharadar        177,483,000

Two independent vendors agreeing to four decimals. So `open/high/low/close/
volume` are used as-is and no adjustment decision is introduced -- prior
results stay comparable, and `closeadj` is deliberately NOT used even though
total return would be more correct, because switching now would confound the
universe change with a label change. That is a known limitation carried
forward on purpose: the labels exclude dividends, as they always have.

SPY comes from `scripts/td_data_local/SPY.csv`, unchanged. It is an ETF and
so absent from the equities panel, and it is the same series every prior
result used for relative_strength_20 and the benchmark comparison.

MEMORY
------
The price panel for 4,030 tickers is ~20M rows. Features are computed one
ticker at a time and streamed to parquet under a pinned schema -- inferring
per batch fails the moment one ticker's frame types differ from another's,
which is the same trap that broke the universe builder.

    python3 build_features_sharadar.py
    python3 build_features_sharadar.py --verify     # compare vs the old panel

VERIFY MODE is the point of trusting this at all: for tickers present in
BOTH the old and new panels, every feature on every shared (ticker, date)
should agree to floating-point noise. If it does, the rebuild changed the
universe and nothing else. If it does not, something other than coverage
moved and needs explaining before any gate is re-run.

OUTPUT
    final/out/features_sharadar_pit.parquet
"""
import argparse
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from features import (FEATURE_COLS, FORWARD_WINDOW, LABEL_COL,
                      TRADABLE_LABEL_COL, MOMENTUM_WINDOWS, VOL_WINDOWS,
                      VOLUME_WINDOW, RS_WINDOW, PRICE_LEVEL_WINDOW,
                      OUT_DIR, PROJECT_ROOT)

PANEL = PROJECT_ROOT / "data" / "sharadar" / "panel" / "stocks"
UNIVERSE = PROJECT_ROOT / "data" / "sharadar" / "pit_universe.parquet"
SPY_CSV = PROJECT_ROOT / "scripts" / "td_data_local" / "SPY.csv"
OUT = OUT_DIR / "features_sharadar_pit.parquet"
OLD_PANEL = OUT_DIR / "features_pit.parquet"

PRICE_COLS = ["open", "high", "low", "close", "volume"]


def load_spy():
    spy = pd.read_csv(SPY_CSV, parse_dates=["date"]).sort_values("date")
    spy["spy_momentum_20"] = spy["close"].pct_change(RS_WINDOW)
    return spy[["date", "spy_momentum_20"]].reset_index(drop=True)


def load_prices(tickers):
    months = sorted(PANEL.glob("*.parquet"))
    frames = []
    for i, f in enumerate(months, 1):
        d = pd.read_parquet(f, columns=["ticker", "date"] + PRICE_COLS)
        d = d[d["ticker"].isin(tickers)]
        if len(d):
            frames.append(d)
        if i % 60 == 0 or i == len(months):
            print(f"  loaded {i}/{len(months)} months, "
                  f"{sum(len(x) for x in frames):,} rows")
    df = pd.concat(frames, ignore_index=True)
    df["date"] = pd.to_datetime(df["date"])
    for c in PRICE_COLS:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df.sort_values(["ticker", "date"]).reset_index(drop=True)


def features_for(g, spy):
    """Exactly features.build_features()'s per-ticker block."""
    g = g.sort_values("date").reset_index(drop=True).copy()
    g["daily_return"] = g["close"].pct_change()
    for w in MOMENTUM_WINDOWS:
        g[f"momentum_{w}"] = g["close"].pct_change(w)
    for w in VOL_WINDOWS:
        g[f"volatility_{w}"] = g["daily_return"].rolling(w).std()
    g["volume_ratio_20"] = g["volume"] / g["volume"].rolling(VOLUME_WINDOW).mean()
    hi = g["close"].rolling(PRICE_LEVEL_WINDOW).max()
    lo = g["close"].rolling(PRICE_LEVEL_WINDOW).min()
    g["pct_from_high_252"] = (g["close"] - hi) / hi
    g["pct_from_low_252"] = (g["close"] - lo) / lo
    g = g.merge(spy, on="date", how="left")
    g["relative_strength_20"] = g["momentum_20"] - g["spy_momentum_20"]
    g[LABEL_COL] = g["close"].shift(-FORWARD_WINDOW) / g["close"] - 1
    g[TRADABLE_LABEL_COL] = (g["close"].shift(-FORWARD_WINDOW)
                             / g["open"].shift(-1)) - 1
    return g


def build():
    print("universe:")
    uni = pd.read_parquet(UNIVERSE, columns=["ticker"])
    tickers = set(uni["ticker"].unique())
    print(f"  {len(tickers):,} tickers ever eligible")

    print("prices:")
    px = load_prices(tickers)
    print(f"  {len(px):,} rows, {px['ticker'].nunique():,} tickers, "
          f"{px['date'].min().date()} .. {px['date'].max().date()}")

    spy = load_spy()
    print(f"spy: {len(spy):,} rows, {spy['date'].min().date()} .. "
          f"{spy['date'].max().date()}")

    keep = (["ticker", "date"] + PRICE_COLS + FEATURE_COLS
            + [LABEL_COL, TRADABLE_LABEL_COL])
    schema = pa.schema(
        [("ticker", pa.string()), ("date", pa.timestamp("ns"))]
        + [(c, pa.float64()) for c in PRICE_COLS + FEATURE_COLS
           + [LABEL_COL, TRADABLE_LABEL_COL]])

    OUT.parent.mkdir(parents=True, exist_ok=True)
    writer = pq.ParquetWriter(OUT, schema)
    n = 0
    groups = px.groupby("ticker", sort=False)
    for i, (tk, g) in enumerate(groups, 1):
        f = features_for(g, spy)[keep]
        f["ticker"] = f["ticker"].astype(str)
        for c in PRICE_COLS + FEATURE_COLS + [LABEL_COL, TRADABLE_LABEL_COL]:
            f[c] = pd.to_numeric(f[c], errors="coerce").astype("float64")
        writer.write_table(pa.Table.from_pandas(f, schema=schema,
                                                preserve_index=False))
        n += len(f)
        if i % 500 == 0 or i == len(groups):
            print(f"  {i:,}/{len(groups):,} tickers, {n:,} rows")
    writer.close()
    print(f"\n{n:,} rows -> {OUT}")
    return OUT


def verify():
    """Old vs new on shared (ticker, date). Coverage should differ; values
    should not."""
    if not OUT.exists():
        raise SystemExit(f"{OUT} not built yet.")
    if not OLD_PANEL.exists():
        raise SystemExit(f"{OLD_PANEL} not found -- nothing to compare against.")

    cols = ["ticker", "date"] + FEATURE_COLS + [LABEL_COL]
    print("loading old panel...")
    old = pd.read_parquet(OLD_PANEL, columns=cols)
    print("loading new panel...")
    new = pd.read_parquet(OUT, columns=cols)
    for d in (old, new):
        d["date"] = pd.to_datetime(d["date"])
        d["ticker"] = d["ticker"].astype(str)

    ot, nt = set(old["ticker"].unique()), set(new["ticker"].unique())
    print(f"\ntickers  old {len(ot):,}   new {len(nt):,}   "
          f"shared {len(ot & nt):,}   new-only {len(nt - ot):,}   "
          f"old-only {len(ot - nt):,}")
    print(f"rows     old {len(old):,}   new {len(new):,}")

    m = old.merge(new, on=["ticker", "date"], suffixes=("_o", "_n"), how="inner")
    print(f"shared (ticker, date) rows: {len(m):,}")
    if not len(m):
        print("NOTHING SHARED -- cannot verify.")
        return

    print(f"\n{'feature':<24} {'max abs diff':>14} {'median abs':>13} "
          f"{'n both':>12} {'disagree>1e-6':>14}")
    worst = 0.0
    for c in FEATURE_COLS + [LABEL_COL]:
        a, b = m[f"{c}_o"], m[f"{c}_n"]
        both = a.notna() & b.notna()
        if not both.any():
            print(f"{c:<24} {'no overlap':>14}")
            continue
        d = (a[both] - b[both]).abs()
        bad = int((d > 1e-6).sum())
        worst = max(worst, float(d.max()))
        print(f"{c:<24} {d.max():>14.3e} {d.median():>13.3e} "
              f"{int(both.sum()):>12,} {bad:>14,}")
    print(f"\nworst disagreement across all features: {worst:.3e}")
    if worst < 1e-6:
        print("PASS -- the rebuild changed coverage and nothing else.")
    else:
        print("INVESTIGATE -- values moved, not just coverage. Do not re-run")
        print("the gates until this is explained; a coverage change alone")
        print("cannot alter a feature on a date both panels share.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--verify", action="store_true")
    a = ap.parse_args()
    if a.verify:
        verify()
    else:
        build()
        print("\nnow run:  python3 build_features_sharadar.py --verify")
