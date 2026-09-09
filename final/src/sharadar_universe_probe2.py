"""
Round 11b -- Sharadar probe, second pass.

WHY THIS REPLACES v1
--------------------
v1 asked what Sharadar's columns are. That question is now answered offline
from files already on disk:

  fundamentals (SF1) columns  -- confirmed from _sharadar_schema_probe/AAPL.csv
      ticker, dimension, calendardate, date, reportperiod, fiscalperiod,
      lastupdated, ... marketcap, price, sharesbas, shareswa, ev, pe, pb, ...
      `date`        = filing/publication date  (the PIT key -- correct)
      `calendardate`= period end               (using it would leak ~30 days)
      `dimension`   = ARQ/ARY as-reported (PIT) vs MRQ/MRY/MRT restated
  actions columns -- confirmed from sharadar_splits_raw.csv
      date, action, ticker, name, value, contraticker, contraname
  stocks columns  -- confirmed from td_data_delisted/*.csv
      date, open, high, low, close, volume

So this pass asks the three questions that are actually still open.

QUESTION 1 -- IS THERE A STABLE ID THAT SURVIVES SYMBOL REUSE?
An offline audit of the 264 pulled "gap ticker" files found 41 where the
price series BEGINS AFTER the company left the S&P 500. A file cannot be
the company it is named for if it starts after that company was gone. The
symbols were reissued to different companies and the by-ticker pull
silently returned the wrong entity -- 46,854 wrong-company bars, 68% of
them in the 2020-2026 hold-out window:

    FB    px from 2025-06-26, left index 2022-06-08
    EMC   px from 2023-05-15, left index 2016-09-06
    APC   px from 2026-02-12, left index 2019-08-08
    SGP   px from 2026-02-06, left index 2009-10-29
    ...37 more

Sharadar is documented to carry `permaticker`, a stable numeric ID that is
never recycled. If it is present, every by-ticker pull in this repo is
wrong by construction and must be redone by permaticker. That is the single
most important thing this script checks.

QUESTION 2 -- CAN THE UNIVERSE BE ENUMERATED AS OF A PAST DATE?
Gate B4 failed (IC +0.1262, ceiling 0.10) and the three-way ablation showed
the model is separating survivors from non-survivors rather than picking
stocks: gaps exempt IC +0.1350, gaps screened +0.1262, gaps removed -0.0013.
The candidate pool is "worth >$2B TODAY" plus a partial patch of S&P 500
leavers. Missing: everything that cleared $2B at the time, was never in the
S&P 500, and is now gone. Fixing that needs a query that returns ALL
tickers as of a past date, not one ticker at a time. This script tests
whether the API answers date-keyed queries with no ticker filter, and how
it pages.

QUESTION 3 -- ARE DEAD LARGE-CAPS PRICED AT ALL?
If Sharadar cannot price Lehman, Enron, Washington Mutual, the hole is not
fillable from this vendor and we need another.

    export SHARADAR_API_KEY="..."
    python3 sharadar_universe_probe2.py

Nothing is written except a JSON report under final/out/. No bulk pulling.
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
OUT = Path(__file__).resolve().parent.parent / "out" / "sharadar_universe_probe2.json"
DELAY = 0.3

# The 41 proven-contaminated gap tickers: price series starts after the
# company left the S&P 500, so the file is a different company.
CONTAMINATED = [
    "AT", "NSM", "MMI", "WB", "TSG", "FDC", "MI", "CCEP", "DTV", "STR",
    "SE", "ALTR", "ADT", "PLL", "EQ", "PD", "TE", "ADCT", "SII", "DNB",
    "MON", "HCP", "HMA", "EP", "STI", "DO", "EMC", "INFO", "KG", "FB",
    "PCL", "CAM", "POM", "SPLS", "SGP", "APC", "CA", "NFX", "BBBY",
    "EQR", "CSRA",
]

DEAD_LARGE_CAPS = [
    ("LEH", "Lehman Brothers, bankrupt 2008"),
    ("BSC", "Bear Stearns, acquired 2008"),
    ("WM", "Washington Mutual, failed 2008"),
    ("ENE", "Enron, bankrupt 2001"),
    ("SHLD", "Sears Holdings, bankrupt 2018"),
    ("BBBY", "Bed Bath & Beyond, bankrupt 2023"),
    ("FRC", "First Republic, failed 2023"),
    ("SIVB", "Silicon Valley Bank, failed 2023"),
]

PROBE_DATE = "2015-06-30"   # a past date to test enumeration against


def get(table, params=None, timeout=90):
    p = {"api_key": API_KEY, "format": "csv"}
    if params:
        p.update(params)
    try:
        r = requests.get(f"{BASE_URL}/{table}", params=p, timeout=timeout)
    except requests.RequestException as e:
        return None, f"request failed: {e}"
    if r.status_code != 200:
        return None, f"HTTP {r.status_code}: {r.text[:300].strip()}"
    if not r.text.strip():
        return [], "empty response"
    return list(csv.DictReader(io.StringIO(r.text))), None


def show(t):
    print("\n" + "=" * 76)
    print(t)
    print("=" * 76)


def pick(cols, *subs):
    """First column whose lowercased name contains any of subs."""
    for c in cols:
        lc = c.lower()
        if any(s in lc for s in subs):
            return c
    return None


def main():
    if not API_KEY:
        sys.exit('SHARADAR_API_KEY not set.  export SHARADAR_API_KEY="..."')
    rep = {}

    # ---------------------------------------------------------------- 1
    show("1. TICKERS MASTER -- stable ID, lifecycle dates, dead-company coverage")
    rows, err = get("tickers", {"limit": 50000})
    if err and not rows:
        print(f"  FAILED: {err}")
        rep["tickers"] = {"error": err}
        rows = []
    else:
        cols = list(rows[0].keys()) if rows else []
        print(f"  rows      : {len(rows):,}")
        print(f"  columns   : {cols}")
        rep["tickers"] = {"n": len(rows), "columns": cols}

        c_perma = pick(cols, "permaticker", "permid", "permanent")
        c_tick = pick(cols, "ticker")
        c_del = pick(cols, "isdelisted", "delisted")
        c_first = pick(cols, "firstpricedate", "firstdate")
        c_last = pick(cols, "lastpricedate", "lastdate")
        c_tbl = pick(cols, "table")
        c_cat = pick(cols, "category")
        c_exch = pick(cols, "exchange")

        print(f"\n  STABLE ID  -> {c_perma or 'NOT FOUND -- symbol reuse is unfixable here'}")
        print(f"  delisted   -> {c_del}")
        print(f"  firstprice -> {c_first}")
        print(f"  lastprice  -> {c_last}")
        rep["tickers"]["key_columns"] = {
            "permaticker": c_perma, "isdelisted": c_del,
            "firstpricedate": c_first, "lastpricedate": c_last,
        }

        if rows:
            print("\n  sample row:")
            for k, v in list(rows[0].items())[:20]:
                print(f"    {k:<20} {v}")

        for c in (c_del, c_tbl, c_cat, c_exch):
            if c:
                print(f"\n  {c} distribution: {Counter(r.get(c, '') for r in rows).most_common(10)}")

        if c_del:
            n_dead = sum(1 for r in rows if str(r.get(c_del, "")).upper().startswith(("Y", "T", "1")))
            print(f"\n  DEAD COMPANIES IN MASTER: {n_dead:,} of {len(rows):,}")
            print("  (a few thousand dead names = the survivorship hole IS fillable)")
            rep["tickers"]["n_delisted"] = n_dead

        # --- the contamination audit ---------------------------------
        show("1b. AUDIT -- what does Sharadar say the 41 bad files should be?")
        print("  If one symbol maps to MULTIPLE permatickers, the by-ticker pull")
        print("  merged two different companies and must be redone by permaticker.\n")
        bysym = {}
        for r in rows:
            bysym.setdefault(r.get(c_tick, ""), []).append(r)
        print("  %-7s %-6s %s" % ("ticker", "n_ids", "each: permaticker | first..last | delisted | name"))
        audit = {}
        for t in CONTAMINATED:
            ent = bysym.get(t, [])
            audit[t] = []
            if not ent:
                print(f"  {t:<7} {'0':<6} NOT IN MASTER")
                continue
            print(f"  {t:<7} {len(ent):<6}")
            for e in ent:
                nm = (e.get("name") or "")[:34]
                line = (f"      {e.get(c_perma,'?'):<10} "
                        f"{e.get(c_first,'?')}..{e.get(c_last,'?'):<12} "
                        f"{e.get(c_del,'?'):<4} {nm}")
                print(line)
                audit[t].append({k: e.get(k) for k in
                                 (c_perma, c_first, c_last, c_del, "name") if k})
        rep["contamination_audit"] = audit
        multi = [t for t, v in audit.items() if len(v) > 1]
        print(f"\n  symbols mapping to >1 permaticker: {len(multi)} -> {multi}")

    # ---------------------------------------------------------------- 2
    show("2. ENUMERATION -- can we ask 'everything as of a past date'?")
    print(f"  Testing date-keyed queries with NO ticker filter (date={PROBE_DATE}).")
    print("  If any of these work, the PIT universe is one bulk pull away.\n")
    trials = [
        ("stocks", {"date": PROBE_DATE, "limit": 5}),
        ("stocks", {"date.gte": PROBE_DATE, "date.lte": PROBE_DATE, "limit": 5}),
        ("stocks", {"date_gte": PROBE_DATE, "date_lte": PROBE_DATE, "limit": 5}),
        ("daily", {"date": PROBE_DATE, "limit": 5}),
        ("daily", {"ticker": "AAPL", "limit": 3}),
        ("fundamentals", {"date": PROBE_DATE, "limit": 5}),
        ("fundamentals", {"dimension": "ARQ", "calendardate": "2015-06-30", "limit": 5}),
        ("sf1", {"ticker": "AAPL", "limit": 2}),
        ("metrics", {"ticker": "AAPL", "limit": 2}),
    ]
    enum = {}
    for tbl, params in trials:
        time.sleep(DELAY)
        rows2, err = get(tbl, params)
        key = f"{tbl} {params}"
        if err and not rows2:
            print(f"  {tbl:<13} {str(params)[:46]:<48} -> {err[:60]}")
            enum[key] = {"error": err}
            continue
        cols = list(rows2[0].keys()) if rows2 else []
        mc = [c for c in cols if "marketcap" in c.lower() or "mktcap" in c.lower()]
        print(f"  {tbl:<13} {str(params)[:46]:<48} -> OK {len(rows2)} rows")
        if cols:
            print(f"                {'':48}    cols={cols[:12]}{' ...' if len(cols) > 12 else ''}")
        if mc:
            print(f"                {'':48}    MARKETCAP: {mc}")
        if rows2:
            tk = pick(cols, "ticker")
            print(f"                {'':48}    tickers seen: "
                  f"{sorted({r.get(tk,'') for r in rows2})[:6]}")
        enum[key] = {"n": len(rows2), "columns": cols, "marketcap_cols": mc}
    rep["enumeration"] = enum

    # ---------------------------------------------------------------- 3
    show("3. DEAD LARGE-CAP PRICE COVERAGE -- is the hole fillable?")
    cov = {}
    for tk, why in DEAD_LARGE_CAPS:
        time.sleep(DELAY)
        allrows, err = get("stocks", {"ticker": tk})
        if err and not allrows:
            print(f"  {tk:<6} {why:<34} -> {err[:50]}")
            cov[tk] = {"ok": False, "error": err}
            continue
        n = len(allrows)
        rng = ""
        if allrows:
            dc = pick(list(allrows[0].keys()), "date")
            ds = sorted(r[dc] for r in allrows if r.get(dc))
            rng = f"{ds[0]} .. {ds[-1]}" if ds else ""
        print(f"  {tk:<6} {why:<34} -> {n:>7,} rows   {rng}")
        cov[tk] = {"ok": n > 0, "rows": n, "range": rng}
    rep["dead_largecap_coverage"] = cov
    ok = sum(1 for v in cov.values() if v.get("ok"))
    print(f"\n  {ok}/{len(DEAD_LARGE_CAPS)} priced.")

    # ---------------------------------------------------------------- 4
    show("4. ACTIONS -- are delisting/merger events available?")
    rows3, err = get("actions", {"limit": 4000})
    if err and not rows3:
        print(f"  {err}")
        rep["actions"] = {"error": err}
    else:
        cols = list(rows3[0].keys()) if rows3 else []
        ac = pick(cols, "action")
        print(f"  columns: {cols}")
        if ac:
            print(f"  action values: {Counter(r.get(ac,'') for r in rows3).most_common(20)}")
        rep["actions"] = {"columns": cols,
                          "values": Counter(r.get(ac, "") for r in rows3).most_common(20) if ac else None}

    OUT.parent.mkdir(parents=True, exist_ok=True)
    json.dump(rep, open(OUT, "w"), indent=2, default=str)
    print(f"\nSaved -> {OUT}")
    print("\nPaste sections 1, 1b and 2 back -- those decide the rebuild.")


if __name__ == "__main__":
    main()
