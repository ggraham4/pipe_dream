"""
Pull SF1 fundamentals for EVERY ticker, so the 14 fundamental features can
be computed on the new point-in-time universe.

WHY THIS IS NEEDED NOW
----------------------
The rebuilt universe has 4,030 distinct tickers over 2005-2026. The
existing fundamentals on disk (`fundamentals_raw/`, `fundamentals_raw_delisted/`)
cover roughly 1,900 -- the survivor list plus the gap patch. So the
augmented model's 14 fundamental features simply do not exist for the ~2,100
names the universe rebuild added, and those names are disproportionately
the dead ones the whole exercise was about recovering.

Gate B4 was measured on the augmented (25-column) model. Re-running it on
a price-only feature set would not be a like-for-like comparison, so this
has to exist before the gates mean anything.

WHAT IT PULLS
-------------
Dimensions ARQ and ARY only -- as-reported, never restated. MRQ/MRY/MRT
would leak later restatements into a supposedly point-in-time value, which
is the discipline the whole Sharadar migration exists to protect.

`date` is the FILING date, not the period end (`calendardate` lags it by
roughly 4-6 weeks). Everything downstream joins on filing date via
merge_asof, so using `calendardate` would introduce about a month of
look-ahead on every fundamental feature.

Columns, mapped to the concepts fundamentals_features_beta.py consumes:

    STOCK_CONCEPTS                       FLOW_CONCEPTS
      total_assets        -> assets        revenue            -> revenue
      total_liabilities   -> liabilities   net_income         -> netinc
      stockholders_equity -> equity        gross_profit       -> gp
      cash                -> cashneq       operating_income   -> opinc
      long_term_debt      -> debtnc        operating_cash_flow-> ncfo
      shares_outstanding  -> sharesbas     capex              -> capex
                                           rnd_expense        -> rnd

    plus eps / epsdil, and marketcap + price for cross-checking.

`shares_outstanding_dei` has no Sharadar equivalent; process_ticker()
already falls back to shares_outstanding when it is missing.

    export SHARADAR_API_KEY="..."
    python3 sharadar_pull_fundamentals.py

Expect roughly the same wall time as sharadar_pull_shares.py -- same row
count, more columns. Output is one tidy parquet, not 4,000 CSVs.

OUTPUT
    final/data/sharadar/sf1_fundamentals.parquet
"""
import csv
import io
import os
import sys
import time
from pathlib import Path

import pandas as pd
import requests

BASE_URL = "https://api.sharadar.com/v1.0/data"
API_KEY = os.environ.get("SHARADAR_API_KEY")
OUT = Path(os.environ.get("SHARADAR_OUT_DIR") or Path(__file__).resolve().parent.parent / "data" / "sharadar") / "sf1_fundamentals.parquet"
PAGE = 10000
DELAY = 0.2
START_YEAR = int(os.environ.get("SHARADAR_START", "2004")[:4])
END_YEAR = int(os.environ.get("SHARADAR_END", "2026")[:4])

KEEP = [
    "ticker", "dimension", "date", "calendardate", "reportperiod",
    # stock concepts
    "assets", "liabilities", "equity", "cashneq", "debtnc", "sharesbas",
    # flow concepts
    "revenue", "netinc", "gp", "opinc", "ncfo", "capex", "rnd",
    # per-share and cross-checks
    "eps", "epsdil", "marketcap", "price", "shareswa",
]
NUMERIC = [c for c in KEEP if c not in
           ("ticker", "dimension", "date", "calendardate", "reportperiod")]


def get(params, timeout=180, tries=4):
    last = None
    for attempt in range(tries):
        try:
            p = {"api_key": API_KEY, "format": "csv"}
            p.update(params)
            r = requests.get(f"{BASE_URL}/fundamentals", params=p, timeout=timeout)
            if r.status_code == 200:
                if not r.text.strip():
                    return []
                return list(csv.DictReader(io.StringIO(r.text)))
            last = f"HTTP {r.status_code}: {r.text[:150]}"
        except requests.RequestException as e:
            last = f"{type(e).__name__}: {e}"
        wait = 2 ** attempt
        print(f"      retry {attempt + 1}/{tries} in {wait}s -- {last}")
        time.sleep(wait)
    raise RuntimeError(f"failed after {tries} tries: {last}")


def main():
    if not API_KEY:
        sys.exit('SHARADAR_API_KEY not set.  export SHARADAR_API_KEY="..."')
    OUT.parent.mkdir(parents=True, exist_ok=True)

    seen, rows = set(), []
    t0 = time.time()
    for dim in ("ARQ", "ARY"):
        for year in range(START_YEAR, END_YEAR + 1):
            lo, hi = f"{year}-01-01", f"{year}-12-31"
            off, got = 0, 0
            while True:
                chunk = get({"dimension": dim, "date.gte": lo, "date.lte": hi,
                             "limit": PAGE, "offset": off})
                for r in chunk:
                    k = (r.get("ticker"), r.get("date"), dim)
                    if k in seen:
                        continue
                    seen.add(k)
                    rows.append({c: r.get(c) for c in KEEP})
                got += len(chunk)
                if len(chunk) < PAGE:
                    break
                off += PAGE
                time.sleep(DELAY)
            print(f"  {dim} {year}: {got:,} rows  "
                  f"(kept {len(rows):,}, {(time.time() - t0) / 60:.1f}m)")
            time.sleep(DELAY)

    df = pd.DataFrame(rows)
    for c in NUMERIC:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    df["ticker"] = df["ticker"].astype(str)
    df = df.sort_values(["ticker", "date", "dimension"]).reset_index(drop=True)
    df.to_parquet(OUT, index=False)

    print(f"\n{len(df):,} rows, {df['ticker'].nunique():,} tickers -> {OUT}")
    print(f"  dimensions: {df['dimension'].value_counts().to_dict()}")
    print(f"  filing dates {df['date'].min()} .. {df['date'].max()}")

    # does this actually cover the rebuilt universe?
    uni = OUT.parent / "pit_universe.parquet"
    if uni.exists():
        u = pd.read_parquet(uni, columns=["ticker"])
        need = set(u["ticker"].unique())
        have = set(df["ticker"].unique())
        miss = need - have
        print(f"\ncoverage of the rebuilt universe: "
              f"{len(need & have):,} of {len(need):,} tickers "
              f"({100 * len(need & have) / max(len(need), 1):.1f}%)")
        if miss:
            print(f"  {len(miss)} with no fundamentals: {sorted(miss)[:25]}")
    print("\nNext: rebuild the feature panel on the new universe.")


if __name__ == "__main__":
    main()
