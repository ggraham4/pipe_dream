"""
Why do 11% of shared (ticker, date) rows disagree between the old and new
feature panels?

WHAT THE VERIFY PASS SHOWED
---------------------------
    feature              max abs diff   median abs    n both   disagree>1e-6
    momentum_20             2.596e+00    2.857e-08 6,855,713         784,784
    volume_ratio_20         1.958e+01    2.574e-04 6,857,433       5,704,718

Two different problems wearing one number.

The MEDIAN price-feature difference is 2.9e-08 -- float32 rounding, i.e. the
two sources agree. But ~11% of rows disagree by up to 250%, which rounding
cannot produce. Something structural is different on a subset of rows.

`volume_ratio_20` is separate: it disagrees on 83% of rows but with a median
of 2.6e-04. That is the signature of a small systematic difference in the
volume input, not a different series -- Sharadar reports 177,483,000 where
the CSV has 177,482,800, i.e. rounded to the nearest hundred. A ~1e-6
relative difference in volume shows up amplified in a ratio of a value to
its own 20-day mean.

THE HYPOTHESIS FOR THE PRICE FEATURES
-------------------------------------
The old panel contains the 41 wrong-issuer gap files. On those tickers the
two panels share (ticker, date) rows while holding prices for DIFFERENT
COMPANIES, so every feature differs wildly. If that is the whole story, the
disagreement should be concentrated in a small number of tickers and should
collapse when they are excluded.

If it is NOT the whole story, the leftover tickers are a real discrepancy
between yfinance and Sharadar and have to be understood before any gate is
re-run -- a coverage change cannot alter a feature on a shared date.

    python3 diagnose_feature_mismatch.py
"""
import csv
from pathlib import Path

import numpy as np
import pandas as pd

from features import FEATURE_COLS, LABEL_COL, OUT_DIR, PROJECT_ROOT

OLD = OUT_DIR / "features_pit.parquet"
NEW = OUT_DIR / "features_sharadar_pit.parquet"
CONTAMINATED = set("""AT NSM MMI WB TSG FDC MI CCEP DTV STR SE ALTR ADT PLL EQ PD
TE ADCT SII DNB MON HCP HMA EP STI DO EMC INFO KG FB PCL CAM POM SPLS SGP APC CA
NFX BBBY EQR CSRA""".split())
PROBE = "momentum_20"


def main():
    cols = ["ticker", "date", PROBE, "close", "volume"]
    print("loading...")
    old = pd.read_parquet(OLD, columns=[c for c in cols])
    new = pd.read_parquet(NEW, columns=[c for c in cols])
    for d in (old, new):
        d["date"] = pd.to_datetime(d["date"])
        d["ticker"] = d["ticker"].astype(str)

    m = old.merge(new, on=["ticker", "date"], suffixes=("_o", "_n"))
    both = m[f"{PROBE}_o"].notna() & m[f"{PROBE}_n"].notna()
    m = m[both].copy()
    m["diff"] = (m[f"{PROBE}_o"] - m[f"{PROBE}_n"]).abs()
    m["bad"] = m["diff"] > 1e-6
    print(f"shared rows with {PROBE} on both sides: {len(m):,}")
    print(f"  disagreeing: {int(m['bad'].sum()):,} "
          f"({100 * m['bad'].mean():.1f}%)")

    g = (m.groupby("ticker")
           .agg(rows=("bad", "size"), bad=("bad", "sum"),
                worst=("diff", "max"))
           .assign(frac=lambda d: d["bad"] / d["rows"])
           .sort_values("bad", ascending=False))

    n_any = int((g["bad"] > 0).sum())
    print(f"  tickers with ANY disagreement: {n_any:,} of {len(g):,}")

    print("\n--- is it concentrated? ---")
    cum = g["bad"].cumsum() / g["bad"].sum()
    for k in (10, 25, 50, 100, 200):
        if k <= len(g):
            print(f"  top {k:>3} tickers account for {100 * cum.iloc[k - 1]:.1f}% "
                  f"of all disagreeing rows")

    print("\n--- the 41 known wrong-issuer tickers ---")
    inpanel = [t for t in CONTAMINATED if t in g.index]
    sub = g.loc[inpanel]
    print(f"  present in both panels: {len(inpanel)}")
    print(f"  their disagreeing rows: {int(sub['bad'].sum()):,} "
          f"({100 * sub['bad'].sum() / max(int(m['bad'].sum()), 1):.1f}% of the total)")

    rest = m[~m["ticker"].isin(CONTAMINATED)]
    print(f"\n--- EXCLUDING those 41 ---")
    print(f"  rows {len(rest):,}   disagreeing {int(rest['bad'].sum()):,} "
          f"({100 * rest['bad'].mean():.2f}%)")

    g2 = (rest.groupby("ticker")
              .agg(rows=("bad", "size"), bad=("bad", "sum"), worst=("diff", "max"))
              .assign(frac=lambda d: d["bad"] / d["rows"])
              .sort_values("bad", ascending=False))
    g2 = g2[g2["bad"] > 0]
    print(f"  tickers still disagreeing: {len(g2):,}")
    print(f"\n  worst 30 remaining:")
    print(f"  {'ticker':<9} {'rows':>7} {'bad':>7} {'frac':>7} {'worst diff':>12}")
    for t, r in g2.head(30).iterrows():
        print(f"  {t:<9} {int(r['rows']):>7,} {int(r['bad']):>7,} "
              f"{r['frac']:>7.2f} {r['worst']:>12.4f}")

    # look at one offender's raw prices side by side
    if len(g2):
        t = g2.index[0]
        print(f"\n--- raw close for {t}, first 8 disagreeing dates ---")
        s = m[(m["ticker"] == t) & m["bad"]].sort_values("date").head(8)
        print(f"  {'date':<12} {'old close':>12} {'new close':>12} "
              f"{'old vol':>14} {'new vol':>14}")
        for _, r in s.iterrows():
            print(f"  {r['date'].date()!s:<12} {r['close_o']:>12.4f} "
                  f"{r['close_n']:>12.4f} {r['volume_o']:>14,.0f} "
                  f"{r['volume_n']:>14,.0f}")

    # is the volume difference just rounding?
    print("\n--- volume: rounding or a different series? ---")
    v = m[m["volume_o"].notna() & m["volume_n"].notna()].copy()
    v["vdiff"] = (v["volume_o"] - v["volume_n"]).abs()
    v["vrel"] = v["vdiff"] / v["volume_o"].replace(0, np.nan)
    print(f"  rows {len(v):,}")
    print(f"  identical volume      : {int((v['vdiff'] == 0).sum()):,} "
          f"({100 * (v['vdiff'] == 0).mean():.1f}%)")
    print(f"  abs diff <= 100       : {int((v['vdiff'] <= 100).sum()):,} "
          f"({100 * (v['vdiff'] <= 100).mean():.1f}%)")
    print(f"  median relative diff  : {v['vrel'].median():.3e}")
    print(f"  p99 relative diff     : {v['vrel'].quantile(0.99):.3e}")
    print("\n  if nearly all differences are <= 100 shares, Sharadar is simply")
    print("  reporting volume rounded to the nearest hundred and volume_ratio_20")
    print("  is not evidence of a different series.")


if __name__ == "__main__":
    main()
