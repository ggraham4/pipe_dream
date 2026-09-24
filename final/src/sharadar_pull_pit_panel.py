"""
Pull the point-in-time panel: daily market caps + OHLCV, by date, for
every US equity Sharadar carries -- survivors and dead companies alike.

This is the pull that fixes Gate B4. The candidate pool stops being
"worth >$2B today, plus a partial patch of index leavers" and becomes
"worth >$2B on the day", which is the only version that is not
hindsight-determined.

SETTLED BEFORE WRITING THIS
---------------------------
  offset= pages; a short page means done.
  Equity master is 20,965 rows (table=stocks), 14,640 delisted.
  Date-keyed queries need no ticker filter.
  daily.marketcap is in MILLIONS THROUGHOUT -- confirmed across 2005-2026,
  not assumed. Medians stay within 0.43x-1.14x of 2015 (a unit break would
  show as ~1e6), and 21 of 21 AAPL/XOM/GE anchors against SF1's dollar
  figures land between 767,212 and 1,255,501 -- i.e. ~1e6 at every date,
  the spread being same-day price vs last-filing price.
      -> THE SCREEN IS  marketcap >= 2000.
  daily reaches back to 1998-12-01; ~6,000 rows per date.

  BUT THE COLUMN CONTAINS CORRUPT ROWS, IN TWO CLASSES:
      astronomical, trivially caught --
          DIGA Applied Digital Solutions  80,658,330,055 (2005)  = $80.6 QUADRILLION
          BNBX BNB Plus Corp               5,248,412 (2006)      = $5.2T in 2006
      plausible-magnitude and therefore dangerous --
          COR3 Cortex Pharmaceuticals   246,920 (2005), 320,418 (2006)
          RAMR RAM Holdings             342,340 (2006)
      COR3 is a micro-cap biotech listed at $247B, which would place it
      7th-largest company in America. No magnitude threshold can catch that;
      it sits squarely inside the real megacap range. Catching it needs an
      INDEPENDENT quantity -- marketcap/price implies a share count, and
      COR3's implied count is tens of billions of shares. That check lives
      in validate_marketcap_panel.py, deliberately NOT here.

  THIS PULLER THEREFORE DOES NOT CLEAN ANYTHING. It writes what the vendor
  sent, records outlier counts to the manifest, and leaves every judgement
  to the validation pass. Cleaning during ingestion destroys the evidence
  needed to audit the cleaning.

STRATEGY
--------
Month at a time, offset-paged, one parquet per table per month. Month
granularity keeps each request small enough to be reliable and makes the
job resumable to the month -- if it dies at 2014-07, rerunning skips
everything already written.

Rows are deduped on (ticker, date) at write time because offset paging
across a moving result set can repeat or drop rows. Every month's actual
row count, distinct dates and distinct tickers get logged so the panel can
be audited afterwards rather than trusted.

    export SHARADAR_API_KEY="..."
    python3 sharadar_pull_pit_panel.py                 # daily + stocks, 2005..now
    python3 sharadar_pull_pit_panel.py --table daily
    python3 sharadar_pull_pit_panel.py --start 2005-01 --end 2010-12
    python3 sharadar_pull_pit_panel.py --verify        # audit what's on disk

Roughly 3,000 requests per table. Expect 30-60 minutes per table. It is
safe to interrupt and rerun.

OUTPUT
    final/data/sharadar/panel/daily/YYYY-MM.parquet
    final/data/sharadar/panel/stocks/YYYY-MM.parquet
    final/data/sharadar/panel/_manifest.csv
"""
import argparse
import csv
import io
import os
import sys
import time
from datetime import date
from pathlib import Path

import pandas as pd
import requests

BASE_URL = "https://api.sharadar.com/v1.0/data"
API_KEY = os.environ.get("SHARADAR_API_KEY")
ROOT = Path(__file__).resolve().parent.parent
# SHARADAR_PANEL_DIR redirects output (used by the 1998-2004 backfill so it
# never lands in the live panel dir that build_pit_universe.py globs).
PANEL = Path(os.environ.get("SHARADAR_PANEL_DIR") or ROOT / "data" / "sharadar" / "panel")
MANIFEST = PANEL / "_manifest.csv"

PAGE = 10000
DELAY = 0.2
RETRIES = 4

# daily.marketcap is denominated in MILLIONS of USD, at every date from
# 2005 to 2026. Confirmed against SF1's dollar figures (21/21 anchors ~1e6)
# and against the per-date medians (no 1e6 break anywhere). Do not change
# without redoing that check -- a 1e6 error here is invisible in the output.
MARKETCAP_UNITS = "USD_MILLIONS"
UNIVERSE_MIN_MARKETCAP = 2000.0          # = $2B, in millions

# Scale guard. Asserted on p99.9, NOT max: max over ~120,000 rows is
# maximally sensitive to a single corrupt value and so cannot tell "one bad
# ticker" from "this month is in different units" -- which was exactly the
# failure of the first version of this file. Observed p99.9 runs 221,911
# (2005) to 2,476,904 (2026); a dollars-denominated month would put p99.9
# near 2e11. 1e9 sits ~400x above the real ceiling and ~200x below a unit
# break, so it separates the two cleanly.
SCALE_GUARD_P999 = 1e9
# Rows above this are recorded as outliers, never dropped. $20T is roughly
# 4x the largest company that has ever existed.
OUTLIER_ABOVE = 20_000_000.0

DEFAULT_START = "2005-01"
DEFAULT_END = date.today().strftime("%Y-%m")


def months(start, end):
    y, m = int(start[:4]), int(start[5:7])
    ey, em = int(end[:4]), int(end[5:7])
    while (y, m) <= (ey, em):
        yield f"{y:04d}-{m:02d}"
        m += 1
        if m == 13:
            y, m = y + 1, 1


def month_bounds(ym):
    y, m = int(ym[:4]), int(ym[5:7])
    last = date(y + (m == 12), 1 if m == 12 else m + 1, 1)
    return f"{ym}-01", (last - pd.Timedelta(days=1)).strftime("%Y-%m-%d")


def fetch(table, params):
    last = None
    for attempt in range(RETRIES):
        try:
            p = {"api_key": API_KEY, "format": "csv"}
            p.update(params)
            r = requests.get(f"{BASE_URL}/{table}", params=p, timeout=180)
            if r.status_code == 200:
                if not r.text.strip():
                    return []
                return list(csv.DictReader(io.StringIO(r.text)))
            last = f"HTTP {r.status_code}: {r.text[:150]}"
        except requests.RequestException as e:
            last = f"{type(e).__name__}: {e}"
        wait = 2 ** attempt
        print(f"      retry {attempt + 1}/{RETRIES} in {wait}s -- {last}")
        time.sleep(wait)
    raise RuntimeError(f"{table} failed after {RETRIES} tries: {last}")


def pull_month(table, ym):
    lo, hi = month_bounds(ym)
    rows, off = [], 0
    while True:
        chunk = fetch(table, {"date.gte": lo, "date.lte": hi,
                              "limit": PAGE, "offset": off})
        rows.extend(chunk)
        if len(chunk) < PAGE:
            break
        off += PAGE
        time.sleep(DELAY)
    return rows


NUMERIC = {
    "daily": ["ev", "evebit", "evebitda", "marketcap", "pb", "pe", "ps"],
    "stocks": ["open", "high", "low", "close", "volume",
               "closeadj", "closeunadj"],
}


def write_month(table, ym, rows):
    out = PANEL / table / f"{ym}.parquet"
    out.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        return {"month": ym, "table": table, "rows": 0, "dates": 0,
                "tickers": 0, "dupes": 0}
    df = pd.DataFrame(rows)
    n0 = len(df)
    df = df.drop_duplicates(subset=["ticker", "date"])
    for c in NUMERIC.get(table, []):
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    df["date"] = pd.to_datetime(df["date"]).dt.date.astype(str)
    df = df.sort_values(["date", "ticker"]).reset_index(drop=True)

    n_outlier, outlier_tickers = 0, ""
    if table == "daily" and "marketcap" in df.columns:
        mc = df["marketcap"].dropna()
        if len(mc):
            p999 = mc.quantile(0.999)
            if p999 > SCALE_GUARD_P999:
                raise SystemExit(
                    f"ABORT {ym}: marketcap p99.9 = {p999:,.0f}, above the "
                    f"{SCALE_GUARD_P999:,.0f} scale guard. That is a whole-month "
                    f"units problem, not a stray row. Re-run "
                    f"diagnose_marketcap_units.py before writing any more.")
            bad = df[df["marketcap"] > OUTLIER_ABOVE]
            n_outlier = len(bad)
            if n_outlier:
                # recorded, never dropped -- the validation pass decides
                outlier_tickers = "|".join(sorted(bad["ticker"].unique())[:12])
    df.to_parquet(out, index=False)
    return {"month": ym, "table": table, "rows": len(df),
            "dates": df["date"].nunique(), "tickers": df["ticker"].nunique(),
            "dupes": n0 - len(df), "outliers": n_outlier,
            "outlier_tickers": outlier_tickers}


def verify():
    print(f"marketcap units: {MARKETCAP_UNITS}   "
          f"universe screen: marketcap >= {UNIVERSE_MIN_MARKETCAP:,.0f}\n"
          f"NOTE: raw panel. Corrupt rows are recorded, not removed -- run "
          f"validate_marketcap_panel.py before using it as a universe.")
    for table in ("daily", "stocks"):
        d = PANEL / table
        if not d.is_dir():
            print(f"\n{table}: nothing on disk")
            continue
        files = sorted(d.glob("*.parquet"))
        tot = dates = 0
        first = last = None
        for f in files:
            df = pd.read_parquet(f, columns=["ticker", "date"])
            tot += len(df)
            dates += df["date"].nunique()
            lo, hi = df["date"].min(), df["date"].max()
            first = lo if first is None or lo < first else first
            last = hi if last is None or hi > last else last
        print(f"\n{table}: {len(files)} months, {tot:,} rows, "
              f"{dates:,} trading days, {first} .. {last}")
        gaps = []
        want = set(months(files[0].stem, files[-1].stem)) if files else set()
        have = {f.stem for f in files}
        gaps = sorted(want - have)
        if gaps:
            print(f"  MISSING MONTHS: {gaps}")
        else:
            print("  no missing months")

    du = PANEL / "daily"
    if du.is_dir():
        fs = sorted(du.glob("*.parquet"))
        if fs:
            print("\n  universe size at a few dates "
                  f"(marketcap >= {UNIVERSE_MIN_MARKETCAP:,.0f} = $2B):")
            for f in (fs[0], fs[len(fs) // 2], fs[-1]):
                df = pd.read_parquet(f, columns=["ticker", "date", "marketcap"])
                d0 = df["date"].max()
                day = df[df["date"] == d0]
                big = day[day["marketcap"] >= UNIVERSE_MIN_MARKETCAP]
                print(f"    {d0}  {len(day):,} listed   "
                      f"{len(big):,} over $2B")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--table", choices=["daily", "stocks"], action="append")
    ap.add_argument("--start", default=DEFAULT_START)
    ap.add_argument("--end", default=DEFAULT_END)
    ap.add_argument("--force", action="store_true",
                    help="re-pull months already on disk")
    ap.add_argument("--verify", action="store_true")
    a = ap.parse_args()

    if a.verify:
        verify()
        return
    if not API_KEY:
        sys.exit('SHARADAR_API_KEY not set.  export SHARADAR_API_KEY="..."')

    tables = a.table or ["daily", "stocks"]
    PANEL.mkdir(parents=True, exist_ok=True)
    log = []
    t0 = time.time()
    for table in tables:
        ms = list(months(a.start, a.end))
        print(f"\n=== {table}: {len(ms)} months {ms[0]} .. {ms[-1]}")
        for i, ym in enumerate(ms, 1):
            out = PANEL / table / f"{ym}.parquet"
            if out.exists() and not a.force:
                print(f"  [{i:>3}/{len(ms)}] {ym}  skip (on disk)")
                continue
            rows = pull_month(table, ym)
            st = write_month(table, ym, rows)
            log.append(st)
            el = time.time() - t0
            print(f"  [{i:>3}/{len(ms)}] {ym}  {st['rows']:>7,} rows  "
                  f"{st['dates']:>3} days  {st['tickers']:>6,} tickers"
                  + (f"  ({st['dupes']} dupes dropped)" if st["dupes"] else "")
                  + (f"  [{st['outliers']} outliers: {st['outlier_tickers']}]"
                     if st.get("outliers") else "")
                  + f"   [{el/60:.1f}m]")
            time.sleep(DELAY)

    if log:
        MANIFEST.parent.mkdir(parents=True, exist_ok=True)
        hdr = not MANIFEST.exists()
        with open(MANIFEST, "a", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(log[0].keys()))
            if hdr:
                w.writeheader()
            w.writerows(log)
    print(f"\ndone in {(time.time() - t0)/60:.1f} min")
    verify()


if __name__ == "__main__":
    main()
