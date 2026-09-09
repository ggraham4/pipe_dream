"""
Why did 2005-01 report a max marketcap of 120,902,938,553?

WHAT HAPPENED
-------------
The panel puller asserts that no month's maximum `daily.marketcap` exceeds
1e9, which cannot happen if the column is denominated in millions. It fired
on the very first month:

    ABORT 2005-01: max marketcap 120,902,938,553

Neither reading of that number works:

    as MILLIONS -> $1.2e17.  Absurd.
    as DOLLARS  -> $120.9B.  Also wrong -- if January 2005 were denominated
                   in dollars the MAXIMUM would be General Electric at
                   roughly $380B, not $121B. A max of $121B is not the top
                   of that distribution.

So the number is probably a single corrupt row rather than an era-wide unit
change -- but "probably" is not good enough for the constant that decides
which ~5,000 companies enter the universe. The flaw in the assertion is
that `max` over ~120,000 rows is maximally sensitive to exactly one bad
value, so it cannot distinguish "one broken ticker" from "the whole month
is in different units". This tells them apart.

DO NOT RELAX THE ASSERTION UNTIL THIS RUNS. Loosening a check because it
failed is how a 1e6 error gets into the universe silently.

WHAT IT CHECKS
--------------
1. Distribution shape per date: n, median, p99, p99.9, max. If a month is
   in different units the MEDIAN moves by ~1e6. If one row is corrupt the
   median is unchanged and only the tail is absurd. These look nothing
   alike, and the median is the statistic that settles it.

2. The top 10 names by marketcap, joined to the master. In a healthy 2005
   the leaders are GE / XOM / MSFT / C / WMT. If the leader is an unknown
   micro-cap, the row is corrupt.

3. A self-contained anchor that relies on no outside knowledge: for AAPL,
   XOM and GE, compare `daily.marketcap` against the `fundamentals.marketcap`
   of the most recent filing at that date. SF1 is in dollars. If daily is
   in millions the ratio is ~1e6 at EVERY date; if some era is in dollars
   the ratio there is ~1.

    export SHARADAR_API_KEY="..."
    python3 diagnose_marketcap_units.py
"""
import csv
import io
import os
import statistics
import sys
import time
from pathlib import Path

import requests

BASE_URL = "https://api.sharadar.com/v1.0/data"
API_KEY = os.environ.get("SHARADAR_API_KEY")
MASTER = Path(__file__).resolve().parent.parent / "data" / "sharadar" / "tickers_master.csv"
DELAY = 0.25

DATES = ["2005-01-31", "2006-06-30", "2008-06-30", "2012-06-29",
         "2015-06-30", "2020-06-30", "2026-06-30"]
ANCHORS = ["AAPL", "XOM", "GE"]


def get(table, params, timeout=180):
    p = {"api_key": API_KEY, "format": "csv"}
    p.update(params)
    r = requests.get(f"{BASE_URL}/{table}", params=p, timeout=timeout)
    if r.status_code != 200:
        raise RuntimeError(f"{table} HTTP {r.status_code}: {r.text[:150]}")
    if not r.text.strip():
        return []
    return list(csv.DictReader(io.StringIO(r.text)))


def get_all(table, params, page=10000):
    out, off = [], 0
    while True:
        p = dict(params)
        p.update({"limit": page, "offset": off})
        c = get(table, p)
        out.extend(c)
        if len(c) < page:
            return out
        off += page
        time.sleep(DELAY)


def q(vals, p):
    if not vals:
        return float("nan")
    i = min(int(len(vals) * p), len(vals) - 1)
    return vals[i]


def main():
    if not API_KEY:
        sys.exit('SHARADAR_API_KEY not set.  export SHARADAR_API_KEY="..."')

    names = {}
    if MASTER.exists():
        for r in csv.DictReader(open(MASTER)):
            names.setdefault(r["ticker"], r["name"])

    print("=" * 78)
    print("1. DISTRIBUTION SHAPE  -- a unit change moves the MEDIAN;")
    print("   one corrupt row moves only the MAX")
    print("=" * 78)
    print(f"{'date':<12} {'n':>7} {'median':>12} {'p99':>14} "
          f"{'p99.9':>16} {'max':>20}")
    per_date = {}
    for dt in DATES:
        try:
            rows = get_all("daily", {"date": dt})
        except RuntimeError as e:
            print(f"{dt}  ERROR {e}")
            continue
        vals = []
        for r in rows:
            try:
                v = float(r.get("marketcap") or 0)
            except ValueError:
                continue
            if v > 0:
                vals.append(v)
        vals.sort()
        per_date[dt] = (rows, vals)
        if not vals:
            print(f"{dt:<12} {len(rows):>7,}   no non-zero marketcaps")
            continue
        print(f"{dt:<12} {len(vals):>7,} {statistics.median(vals):>12,.1f} "
              f"{q(vals, 0.99):>14,.1f} {q(vals, 0.999):>16,.1f} "
              f"{vals[-1]:>20,.1f}")
        time.sleep(DELAY)

    med2015 = None
    if "2015-06-30" in per_date and per_date["2015-06-30"][1]:
        med2015 = statistics.median(per_date["2015-06-30"][1])
    if med2015:
        print("\n  median relative to 2015-06-30 (a unit break shows as ~1e6):")
        for dt, (_, vals) in per_date.items():
            if vals:
                print(f"    {dt}  x{statistics.median(vals)/med2015:,.3f}")

    print("\n" + "=" * 78)
    print("2. TOP 10 BY MARKETCAP -- are the leaders the real megacaps?")
    print("=" * 78)
    for dt, (rows, _) in per_date.items():
        good = []
        for r in rows:
            try:
                good.append((float(r.get("marketcap") or 0), r.get("ticker")))
            except ValueError:
                pass
        good.sort(reverse=True)
        print(f"\n  {dt}")
        for v, t in good[:10]:
            print(f"    {t:<10} {v:>22,.1f}   {names.get(t,'?')[:44]}")

    print("\n" + "=" * 78)
    print("3. ANCHOR -- daily.marketcap vs fundamentals.marketcap (dollars).")
    print("   Ratio ~1e6 everywhere = daily is millions everywhere.")
    print("   Ratio ~1 at some dates = that era is in dollars.")
    print("=" * 78)
    print(f"{'ticker':<8} {'date':<12} {'daily':>18} "
          f"{'sf1 (dollars)':>22} {'ratio':>12}")
    for tk in ANCHORS:
        try:
            sf1 = get("fundamentals", {"ticker": tk, "dimension": "ARQ",
                                       "limit": 400})
        except RuntimeError as e:
            print(f"  {tk}: sf1 error {e}")
            continue
        sf1 = sorted([r for r in sf1 if r.get("marketcap")],
                     key=lambda r: r.get("date", ""))
        for dt in DATES:
            try:
                d = get("daily", {"ticker": tk, "date": dt})
            except RuntimeError:
                continue
            if not d or not d[0].get("marketcap"):
                print(f"  {tk:<8} {dt:<12} {'no daily row':>18}")
                continue
            dv = float(d[0]["marketcap"])
            prior = [r for r in sf1 if r["date"] <= dt]
            if not prior:
                print(f"  {tk:<8} {dt:<12} {dv:>18,.1f} {'no sf1 filing yet':>22}")
                continue
            fv = float(prior[-1]["marketcap"])
            print(f"  {tk:<8} {dt:<12} {dv:>18,.1f} {fv:>22,.1f} "
                  f"{(fv / dv if dv else float('nan')):>12,.0f}")
            time.sleep(DELAY)

    print("\n" + "=" * 78)
    print("READING THIS")
    print("=" * 78)
    print("  medians all within a few x of each other, ratios all ~1e6")
    print("      -> units are millions throughout; the 2005 max is ONE bad")
    print("         row. Fix: assert on p99.9, quarantine outliers to a file.")
    print("  2005 median ~1e6 x the 2015 median, or 2005 ratios ~1")
    print("      -> the early era really is in dollars. Fix: a per-era scale,")
    print("         derived from the data, never a hardcoded guess.")


if __name__ == "__main__":
    main()
