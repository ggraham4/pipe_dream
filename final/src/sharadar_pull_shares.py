"""
Pull filed share counts (SF1 `sharesbas`) so marketcap can be validated
against something independent.

WHY THIS IS NEEDED -- RAMR
--------------------------
validate_marketcap_panel.py check 1 flags rows whose implied share count
(marketcap x 1e6 / close) exceeds 30 billion. It caught DIGA, COR3, CHIO
and ICLD. It did NOT catch RAM Holdings:

    2006-06-30   mcap $342,341M   close $12.57   implied  27,234,757,359
    2008-06-30   mcap $ 27,251M   close $ 1.00   implied  27,251,400,000
    2009-03-31   mcap $  6,813M   close $ 0.25   implied  27,251,600,000

27.23 billion shares -- just under the 30bn line. RAM Holdings was a small
Bermuda financial guaranty reinsurer with roughly 28 MILLION shares. The
vendor's share count is wrong by a factor of about a thousand, and at
$27B on 2008-06-30 it sails into a >$2B universe screen.

That is the whole problem with check 1: 30bn is a number I picked. RAMR
sits just below it, CHIO at exactly 32bn sits just above. Nothing about
the data chose that line. A threshold on a derived quantity is still a
magnitude rule, and magnitude rules cannot separate a wrong value from a
large one.

`sharesbas` is the fix because it is INDEPENDENT: SF1 records what the
company filed. RAMR's filings say ~28M shares; implied/filed is then ~1000
and the row is unambiguously wrong, with no threshold to choose.

A NOTE ON WHETHER THE ERROR IS CONSTANT PER TICKER
--------------------------------------------------
It is not, and the difference matters for how features behave:

    RAMR  27,251,400,000 -> 27,251,600,000     effectively constant
    COR3  106,806,233,333 (2006)
          154,322,318,126 (2008)
          154,675,333,333 (2009)               changes mid-series

A constant error cancels out of any within-ticker transformation. A
mid-series change does not -- it manufactures a jump that looks like a
real event. Both are present in this data, so neither assumption is safe.

WHAT THIS PULLS
---------------
SF1 dimension ARQ and ARY (as-reported, never restated -- the same choice
sharadar_data_pull.py made and for the same reason), columns
ticker / date / sharesbas, where `date` is the FILING date, not the period
end. Filing date is what makes the later merge_asof point-in-time.

    export SHARADAR_API_KEY="..."
    python3 sharadar_pull_shares.py

OUTPUT
    final/data/sharadar/sf1_shares.csv    ticker, date, sharesbas, dimension
"""
import csv
import io
import os
import sys
import time
from pathlib import Path

import requests

BASE_URL = "https://api.sharadar.com/v1.0/data"
API_KEY = os.environ.get("SHARADAR_API_KEY")
OUT = Path(__file__).resolve().parent.parent / "data" / "sharadar" / "sf1_shares.csv"
PAGE = 10000
DELAY = 0.2
START, END = "2004-01-01", "2026-12-31"


def get(params, timeout=180):
    p = {"api_key": API_KEY, "format": "csv"}
    p.update(params)
    r = requests.get(f"{BASE_URL}/fundamentals", params=p, timeout=timeout)
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code}: {r.text[:200]}")
    if not r.text.strip():
        return []
    return list(csv.DictReader(io.StringIO(r.text)))


def main():
    if not API_KEY:
        sys.exit('SHARADAR_API_KEY not set.  export SHARADAR_API_KEY="..."')
    OUT.parent.mkdir(parents=True, exist_ok=True)

    seen, rows = set(), []
    for dim in ("ARQ", "ARY"):
        # year at a time -- keeps each offset walk short enough that a
        # moving result set cannot silently drop rows
        for year in range(int(START[:4]), int(END[:4]) + 1):
            lo, hi = f"{year}-01-01", f"{year}-12-31"
            off, got = 0, 0
            while True:
                chunk = get({"dimension": dim, "date.gte": lo, "date.lte": hi,
                             "limit": PAGE, "offset": off})
                for r in chunk:
                    sb = r.get("sharesbas")
                    if not sb:
                        continue
                    k = (r.get("ticker"), r.get("date"), dim)
                    if k in seen:
                        continue
                    seen.add(k)
                    rows.append({"ticker": r.get("ticker"), "date": r.get("date"),
                                 "sharesbas": sb, "dimension": dim})
                got += len(chunk)
                if len(chunk) < PAGE:
                    break
                off += PAGE
                time.sleep(DELAY)
            print(f"  {dim} {year}: {got:,} rows  (kept {len(rows):,} total)")
            time.sleep(DELAY)

    rows.sort(key=lambda r: (r["ticker"], r["date"]))
    with open(OUT, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["ticker", "date", "sharesbas", "dimension"])
        w.writeheader()
        w.writerows(rows)
    print(f"\n{len(rows):,} rows, {len({r['ticker'] for r in rows}):,} tickers -> {OUT}")

    for tk in ("RAMR", "COR3", "DIGA", "AAPL"):
        got = [r for r in rows if r["ticker"] == tk]
        if got:
            print(f"  {tk:<6} {len(got):>4} filings, "
                  f"latest sharesbas {float(got[-1]['sharesbas']):,.0f} "
                  f"({got[-1]['date']})")
        else:
            print(f"  {tk:<6} no filings on record")
    print("\nNow rerun:  python3 validate_marketcap_panel.py")


if __name__ == "__main__":
    main()
