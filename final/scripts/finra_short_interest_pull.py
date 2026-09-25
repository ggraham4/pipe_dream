"""
Pull FINRA's consolidated equity short interest history.

Round 20 (2026-09-18). Data-sourcing report item #7. Free, public, no API
key, no rate limit observed. Endpoint documented at
https://www.finra.org/sites/default/files/Equity_Short_Interest_Data_File_Download_API.pdf
(that PDF's own "EquityShortInterest" dataset is OTC-only, despite the doc's
title -- the one that actually covers NYSE/Nasdaq-listed names, confirmed by
direct query, is "consolidatedShortInterest" under the same group).

    python3 finra_short_interest_pull.py

Output: final/data/finra/short_interest_raw.csv

WHAT WAS VERIFIED BEFORE WRITING THIS (2026-09-18, live queries)
------------------------------------------------------------------
1. No API key / auth needed -- plain unauthenticated POST.
2. Coverage includes NYSE/Nasdaq-listed names (AAPL, OPCH confirmed), not
   just OTC, despite the dataset's home page describing OTC reporting --
   `marketClassCode` reads "NYSE"/"NNM" on real queries.
3. EARLIEST AVAILABLE DATE IS 2020-04-15, confirmed by bracketing (queries
   for anything before that, back to 2010, all return empty). This is a hard
   wall, not a rate limit or a paging artifact -- same era constraint as the
   options-implied features (chain starts 2019-02-09). Nominate/confirm era
   split needed, matching build_options_shuffle_null.py's pattern, NOT the
   standard 2007-2020 nomination era.
4. Bulk pull by DATE RANGE works (not per-ticker) -- one query for a date
   range returns every reporting name at once (~16-21k rows per settlement
   date), paginated via `limit`/`offset` (max limit 5000, `record-total`
   response header gives the count to page against). Full history is ~540
   paginated requests, a few minutes, not per-ticker as the AV sources were.

POINT-IN-TIME CAVEAT -- READ BEFORE BUILDING A FEATURE ON THIS
------------------------------------------------------------------
The API returns `settlementDate` only -- no publish/availability timestamp
field, unlike the legacy OTC-only "EquityShortInterest" dataset, which does
carry `updateDatetime`. FINRA's own published reporting rule (Rule 4560) is
that short interest is made public a FIXED ~8 business days after each
settlement date -- use `settlementDate + 8 business days` as the
availability timestamp when building a feature from this, never the raw
settlementDate itself (that would be look-ahead of exactly the class this
project has been burned by before). This script pulls the raw data only;
the lag is applied at feature-build time, not here, so the raw file stays
a faithful record of what FINRA actually published.
"""
import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from features import PROJECT_ROOT                                # noqa: E402

OUT = PROJECT_ROOT / "data" / "finra" / "short_interest_raw.csv"
URL = "https://api.finra.org/data/group/otcMarket/name/consolidatedShortInterest"
EARLIEST = "2020-04-01"          # one day before the confirmed hard wall
PAGE = 5000                      # API's own max limit


def _fetch_range(lo, hi):
    """One (lo, hi) settlement-date window, fully paginated."""
    rows, offset = [], 0
    while True:
        payload = {
            "compareFilters": [
                {"compareType": "GREATER", "fieldName": "settlementDate", "fieldValue": lo},
                {"compareType": "LESSER", "fieldName": "settlementDate", "fieldValue": hi},
            ],
            "limit": PAGE, "offset": offset,
        }
        r = requests.post(URL, json=payload,
                          headers={"Accept": "application/json"}, timeout=60)
        r.raise_for_status()
        if r.status_code == 204 or not r.text.strip():
            break
        batch = r.json()
        if not batch:
            break
        rows.extend(batch)
        total = int(r.headers.get("record-total", len(batch)))
        offset += len(batch)
        if offset >= total or len(batch) < PAGE:
            break
    return rows


def main():
    import pandas as pd
    import datetime as dt

    OUT.parent.mkdir(parents=True, exist_ok=True)
    today = dt.date.today()
    lo = dt.date.fromisoformat(EARLIEST)
    all_rows = []
    t0 = time.time()
    while lo < today:
        hi = min(lo + dt.timedelta(days=31), today + dt.timedelta(days=1))
        print(f"  {lo} .. {hi} ...", flush=True)
        batch = _fetch_range(lo.isoformat(), hi.isoformat())
        print(f"    {len(batch):,} rows ({time.time()-t0:.0f}s elapsed)", flush=True)
        all_rows.extend(batch)
        lo = hi

    df = pd.DataFrame(all_rows)
    print(f"\n{len(df):,} total rows, {df['symbolCode'].nunique():,} symbols, "
          f"{df['settlementDate'].min()} .. {df['settlementDate'].max()}")

    print("\n--- acceptance checks ---")
    ok = True
    if df["settlementDate"].min() < "2020-04-15":
        ok = False
        print("    FAIL -- data before the confirmed 2020-04-15 wall; something changed upstream")
    known = {"AAPL", "MSFT", "NVDA"}
    have = set(df["symbolCode"]) & known
    print(f"  known large-caps present: {have}")
    if have != known:
        ok = False
        print("    FAIL -- expected large-cap names missing")
    print(f"\n{'ALL CHECKS PASSED' if ok else 'CHECKS FAILED -- inspect before using'}")

    df.to_csv(OUT, index=False)
    print(f"\nwritten {OUT} ({OUT.stat().st_size/1e6:.0f}MB, {time.time()-t0:.0f}s total)")


if __name__ == "__main__":
    main()
