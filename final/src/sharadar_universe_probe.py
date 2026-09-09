"""
Round 11 — can Sharadar give us a genuinely point-in-time universe?

The problem this is trying to solve
-----------------------------------
Gate B4 failed at IC +0.1262 (t 8.10) and the three-way ablation showed why:

    gaps waved through the floor : IC +0.1350
    gaps facing the same floor   : IC +0.1262   <- barely moved
    gaps removed entirely        : IC -0.0013   <- collapses

It is not the screen. It is the pool. The candidate universe at any past date
is built from tickers worth >$2B TODAY (survivors by construction) plus a
PARTIAL patch of losers (S&P 500 leavers we could recover data for). Group
membership is only knowable with hindsight, so the model learns to separate
survivors from non-survivors instead of learning to pick stocks.

Missing entirely: companies that cleared $2B at the time, were never in the
S&P 500, and are now gone. Nobody patched those in.

The fix requires answering one question: **can we enumerate, as of an
arbitrary past date, every US stock that met the criteria then — including the
ones that no longer exist?**

This script does NOT pull anything. It probes what Sharadar can answer, and
quantifies how big the survivorship hole actually is.

What it checks
--------------
1. `tickers` — the securities master. Does it list DELISTED companies? Does it
   carry first/last price dates and an is-delisted flag? How many US common
   stocks are there in total, and how many are dead?
2. A daily market-cap source. Sharadar's Nasdaq-Data-Link DAILY table carries
   marketcap per ticker per day, which would solve the universe problem in one
   bulk pull. The api.sharadar.com surface may expose it under a different
   name, so several candidates are tried and whatever responds is reported.
3. `stocks` price coverage for companies that were large and are now dead
   (Lehman, Bear Stearns, Enron, Sears, Bed Bath & Beyond, First Republic,
   SVB, Chesapeake, Peabody, Washington Mutual). If Sharadar has these, the
   hole is fillable. If it does not, we need a different vendor.
4. `sp500` — historical index membership, to cross-check the existing gap set.

Column names were never confirmed for this API (the docs render behind a
login), so everything here reports the ACTUAL header row rather than assuming.
Paste the output back and the loader gets written against what is really there.

    export SHARADAR_API_KEY="..."
    python3 sharadar_universe_probe.py
"""
import csv
import io
import json
import os
import sys
import time
from collections import Counter
from pathlib import Path

import requests

BASE_URL = "https://api.sharadar.com/v1.0/data"
API_KEY = os.environ.get("SHARADAR_API_KEY")
OUT = Path(__file__).resolve().parent.parent / "out" / "sharadar_universe_probe.json"
DELAY = 0.3

# Large companies that no longer exist. If Sharadar cannot price these, it
# cannot fix the survivorship hole and we need another source.
DEAD_LARGE_CAPS = [
    ("LEH", "Lehman Brothers, bankrupt 2008"),
    ("BSC", "Bear Stearns, acquired 2008"),
    ("WM", "Washington Mutual, failed 2008"),
    ("ENE", "Enron, bankrupt 2001"),
    ("SHLD", "Sears Holdings, bankrupt 2018"),
    ("BBBY", "Bed Bath & Beyond, bankrupt 2023"),
    ("FRC", "First Republic, failed 2023"),
    ("SIVB", "Silicon Valley Bank, failed 2023"),
    ("CHK", "Chesapeake Energy, ch.11 2020"),
    ("BTU", "Peabody Energy, ch.11 2016"),
]

MARKETCAP_TABLE_CANDIDATES = ["daily", "metrics", "dailymetrics", "indicators",
                              "sf1", "fundamentals"]


def get(table, params=None, timeout=60):
    p = {"api_key": API_KEY, "format": "csv"}
    if params:
        p.update(params)
    try:
        r = requests.get(f"{BASE_URL}/{table}", params=p, timeout=timeout)
    except requests.RequestException as e:
        return None, f"request failed: {e}"
    if r.status_code != 200:
        return None, f"HTTP {r.status_code}: {r.text[:200].strip()}"
    if not r.text.strip():
        return [], "empty response"
    rows = list(csv.DictReader(io.StringIO(r.text)))
    return rows, None


def show(title):
    print("\n" + "=" * 74)
    print(title)
    print("=" * 74)


def main():
    if not API_KEY:
        sys.exit("SHARADAR_API_KEY not set.  export SHARADAR_API_KEY=\"...\"")
    report = {}

    # ---- 1. securities master ------------------------------------------
    show("1. TICKERS — does the securities master include DEAD companies?")
    rows, err = get("tickers", {"limit": 20000})
    if err and not rows:
        print(f"  FAILED: {err}")
        print("  Try the same call in a browser to see the real error.")
        report["tickers"] = {"error": err}
    else:
        cols = list(rows[0].keys()) if rows else []
        print(f"  rows returned : {len(rows):,}")
        print(f"  columns       : {cols}")
        report["tickers"] = {"n": len(rows), "columns": cols}
        if rows:
            print("\n  sample row:")
            for k, v in list(rows[0].items())[:18]:
                print(f"    {k:<22} {v}")
            # what identifies a dead company?
            flagcols = [c for c in cols if any(s in c.lower() for s in
                        ("delist", "islive", "active", "lastprice", "firstprice"))]
            print(f"\n  life-cycle columns found: {flagcols or 'NONE — this is a problem'}")
            for c in flagcols:
                vals = Counter(r.get(c, "")[:10] for r in rows)
                top = vals.most_common(6)
                print(f"    {c:<22} {len(vals)} distinct; most common {top}")
            for c in cols:
                if c.lower() in ("exchange", "category", "currency", "table",
                                 "scalemarketcap", "isdelisted"):
                    print(f"    {c:<22} {Counter(r.get(c,'') for r in rows).most_common(8)}")
            report["tickers"]["lifecycle_columns"] = flagcols

    # ---- 2. a daily market-cap source ----------------------------------
    show("2. DAILY MARKET CAP — is there a table with marketcap per ticker/day?")
    print("  This is the table that would solve the universe problem outright.")
    found = {}
    for tbl in MARKETCAP_TABLE_CANDIDATES:
        time.sleep(DELAY)
        rows, err = get(tbl, {"ticker": "AAPL", "limit": 3})
        if err and not rows:
            print(f"  {tbl:<14} -> {err}")
            continue
        cols = list(rows[0].keys()) if rows else []
        mc = [c for c in cols if any(s in c.lower() for s in
              ("marketcap", "mktcap", "market_cap", "sharesbas", "shareswa"))]
        print(f"  {tbl:<14} -> OK, {len(rows)} rows, {len(cols)} cols; "
              f"marketcap-ish: {mc or 'none'}")
        if cols:
            print(f"                    columns: {cols[:14]}"
                  f"{' ...' if len(cols) > 14 else ''}")
        found[tbl] = {"columns": cols, "marketcap_cols": mc}
    report["marketcap_tables"] = found

    # ---- 3. can we price dead large caps? -------------------------------
    show("3. PRICE COVERAGE FOR DEAD LARGE-CAPS — the decisive test")
    cov = {}
    for tk, why in DEAD_LARGE_CAPS:
        time.sleep(DELAY)
        rows, err = get("stocks", {"ticker": tk, "limit": 5})
        if err and not rows:
            print(f"  {tk:<6} {why:<34} -> {err}")
            cov[tk] = {"ok": False, "error": err}
            continue
        if not rows:
            print(f"  {tk:<6} {why:<34} -> NO ROWS")
            cov[tk] = {"ok": False, "error": "no rows"}
            continue
        cols = list(rows[0].keys())
        dcol = next((c for c in cols if "date" in c.lower()), None)
        # full range needs a second call without limit; ask for oldest first
        time.sleep(DELAY)
        allrows, _ = get("stocks", {"ticker": tk})
        n = len(allrows) if allrows else 0
        rng = ""
        if allrows and dcol:
            ds = sorted(r[dcol] for r in allrows if r.get(dcol))
            rng = f"{ds[0]} .. {ds[-1]}" if ds else ""
        print(f"  {tk:<6} {why:<34} -> {n:>6,} rows   {rng}")
        cov[tk] = {"ok": n > 0, "rows": n, "range": rng, "columns": cols}
    report["dead_largecap_coverage"] = cov
    ok = sum(1 for v in cov.values() if v.get("ok"))
    print(f"\n  {ok}/{len(DEAD_LARGE_CAPS)} dead large-caps have price history.")
    if ok >= 7:
        print("  -> Sharadar CAN fill the survivorship hole. Proceed to the pull.")
    else:
        print("  -> Sharadar CANNOT fill it on its own. We need another source")
        print("     (CRSP, or Nasdaq Data Link's SHARADAR/SEP with delisted).")

    # ---- 4. historical index membership --------------------------------
    show("4. SP500 — historical membership, to cross-check the gap set")
    rows, err = get("sp500", {"limit": 20})
    if err and not rows:
        print(f"  {err}")
        report["sp500"] = {"error": err}
    else:
        cols = list(rows[0].keys()) if rows else []
        print(f"  rows {len(rows)}, columns {cols}")
        for r in rows[:5]:
            print(f"    {r}")
        report["sp500"] = {"columns": cols, "n": len(rows)}

    OUT.parent.mkdir(parents=True, exist_ok=True)
    json.dump(report, open(OUT, "w"), indent=2, default=str)
    print(f"\nSaved -> {OUT}")
    print("\nPaste the output above back. The loader gets written against the")
    print("real column names rather than guessed ones.")


if __name__ == "__main__":
    main()
