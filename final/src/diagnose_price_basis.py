"""
The feature mismatch is not the wrong-issuer files. What is it?

WHAT THE LAST DIAGNOSTIC RULED OUT
----------------------------------
The 41 wrong-issuer tickers account for 1.0% of disagreeing rows. The
disagreement is spread across 1,783 of 1,837 shared tickers, ~95% of each
one's rows. That is not contamination; that is a systematic difference in
the price series themselves.

THE CLUE
--------
    AIV 2006-02-01   old close 0.8850   new close 54.6480   volume IDENTICAL

Same company, same day, same volume, prices differing by ~61.75x. Volume
matching exactly rules out a different issuer -- this is the same series on
a different ADJUSTMENT BASIS. yfinance auto-adjusts for dividends and
spinoffs; AIV spun off AIR in 2020, and compounding that with a REIT's
distributions scales the whole pre-2020 history down by ~62x.

WHY THAT SHOULD NOT HAVE MATTERED, AND WHY IT DOES
--------------------------------------------------
A constant scale factor cancels out of `pct_change`, so a dividend-adjusted
series and a raw one should give IDENTICAL momentum. Two things break that:

  1. The factor is not constant -- it steps at every ex-dividend date, so
     returns differ on those days specifically.
  2. PRECISION. Scaled down 62x, AIV's 2006 prices land at ~$0.88 and are
     stored to 4 decimals. That leaves ~3 significant figures, and returns
     computed from them are badly quantized: old shows 0.8850 -> 0.8850,
     a return of exactly 0, where the real move was +0.024%.

So the question is not "which is right" in the abstract. It is: how large
are the resulting feature differences, and are they large enough to matter?

WHAT THIS MEASURES
------------------
1. The DISTRIBUTION of |momentum_20 difference| among disagreeing rows.
   The verify pass reported only a count above 1e-6 and a max. 1e-6 is far
   tighter than anything that could affect a model, so that count says
   nothing about materiality. If the typical disagreement is 1e-4 this is
   noise; if it is 1e-2 it is not.
2. Per ticker, whether old/new close is a CONSTANT ratio. Constant means a
   pure adjustment convention. Varying means ex-dividend steps.
3. Precision loss: how many old closes sit below $5, where 4-decimal
   storage starts destroying return precision.
4. Raw closes side by side for a heavily adjusted name and a typical one.

    python3 diagnose_price_basis.py
"""
import numpy as np
import pandas as pd

from features import OUT_DIR

OLD = OUT_DIR / "features_pit.parquet"
NEW = OUT_DIR / "features_sharadar_pit.parquet"


def main():
    cols = ["ticker", "date", "momentum_20", "close", "volume"]
    print("loading...")
    old = pd.read_parquet(OLD, columns=cols)
    new = pd.read_parquet(NEW, columns=cols)
    for d in (old, new):
        d["date"] = pd.to_datetime(d["date"])
        d["ticker"] = d["ticker"].astype(str)
    m = old.merge(new, on=["ticker", "date"], suffixes=("_o", "_n"))
    m = m[m["momentum_20_o"].notna() & m["momentum_20_n"].notna()].copy()
    m["diff"] = (m["momentum_20_o"] - m["momentum_20_n"]).abs()
    print(f"shared rows: {len(m):,}")

    print("\n=== 1. HOW BIG are the disagreements, really? ===")
    d = m["diff"]
    print(f"  all shared rows:")
    for q in (0.5, 0.75, 0.9, 0.95, 0.99, 0.999, 1.0):
        print(f"    p{q * 100:<7g} {d.quantile(q):>12.3e}")
    dis = d[d > 1e-6]
    print(f"\n  among the {len(dis):,} rows disagreeing by >1e-6:")
    for q in (0.5, 0.75, 0.9, 0.95, 0.99, 1.0):
        print(f"    p{q * 100:<7g} {dis.quantile(q):>12.3e}")
    for thr in (1e-4, 1e-3, 1e-2, 1e-1):
        print(f"  rows differing by more than {thr:>7g}: "
              f"{int((d > thr).sum()):>10,} ({100 * (d > thr).mean():.3f}%)")

    print("\n=== 2. is old/new close a CONSTANT ratio per ticker? ===")
    m["ratio"] = m["close_o"] / m["close_n"].replace(0, np.nan)
    g = m.groupby("ticker")["ratio"].agg(["median", "min", "max", "size"])
    g["spread"] = (g["max"] - g["min"]) / g["median"]
    print(f"  tickers: {len(g):,}")
    print(f"  ratio median == 1 (within 1e-6): "
          f"{int(((g['median'] - 1).abs() < 1e-6).sum()):,}")
    print(f"  ratio constant within 0.1% (a pure scale): "
          f"{int((g['spread'] < 1e-3).sum()):,}")
    print(f"  ratio varies by >10% across the series: "
          f"{int((g['spread'] > 0.1).sum()):,}")
    print("\n  most heavily rescaled tickers (median old/new):")
    print(f"  {'ticker':<9} {'median':>10} {'spread':>10} {'rows':>8}")
    for t, r in g.sort_values("median").head(12).iterrows():
        print(f"  {t:<9} {r['median']:>10.4f} {r['spread']:>10.4f} "
              f"{int(r['size']):>8,}")

    print("\n=== 3. precision loss in the OLD series ===")
    for thr in (1.0, 5.0, 10.0):
        n = int((m["close_o"] < thr).sum())
        print(f"  old closes below ${thr:>5.2f}: {n:>10,} "
              f"({100 * n / len(m):.2f}%)   new: "
              f"{int((m['close_n'] < thr).sum()):>10,}")
    lowo = m[m["close_o"] < 5]
    if len(lowo):
        print(f"\n  median |momentum_20 diff| where old close < $5 : "
              f"{lowo['diff'].median():.3e}")
        print(f"  median |momentum_20 diff| where old close >= $5: "
              f"{m[m['close_o'] >= 5]['diff'].median():.3e}")

    print("\n=== 4. side by side ===")
    for t in ("AIV", "SNEX", "AAPL", "XOM"):
        s = m[m["ticker"] == t].sort_values("date")
        if not len(s):
            continue
        s = s[s["date"] >= "2015-06-25"].head(4)
        if not len(s):
            s = m[m["ticker"] == t].sort_values("date").head(4)
        print(f"\n  {t}")
        print(f"    {'date':<12} {'old close':>12} {'new close':>12} "
              f"{'ratio':>10} {'mom20 old':>12} {'mom20 new':>12}")
        for _, r in s.iterrows():
            print(f"    {r['date'].date()!s:<12} {r['close_o']:>12.4f} "
                  f"{r['close_n']:>12.4f} {r['close_o'] / r['close_n']:>10.4f} "
                  f"{r['momentum_20_o']:>12.6f} {r['momentum_20_n']:>12.6f}")


if __name__ == "__main__":
    main()
