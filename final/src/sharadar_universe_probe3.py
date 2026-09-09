"""
Round 11c -- Sharadar probe, third pass. Sizing the rebuild.

WHAT PROBE 2 SETTLED
--------------------
  permaticker EXISTS  (tickers master: table, permaticker, ticker, name,
                       exchange, isdelisted, category, ..., firstpricedate,
                       lastpricedate, firstquarter, lastquarter)
  13,039 isdelisted='Y' rows -> dead companies ARE carried
  DATE-KEYED QUERIES WORK with no ticker filter:
       stocks?date=2015-06-30   -> ticker,date,open,high,low,close,volume,
                                   closeadj,closeunadj,lastupdated
       daily?date=2015-06-30    -> ticker,date,lastupdated,ev,evebit,
                                   evebitda,MARKETCAP,pb,pe,ps
  `daily` is the table that solves the PIT universe outright: market cap
  per ticker per day. Screen it at >$2B as of date D and the candidate pool
  is what was actually large on D, dead companies included.
  actions carries delisted / regulatorydelisting / voluntarydelisting /
  acquisitionby / tickerchangeto / tickerchangefrom.

TWO RESULTS FROM PROBE 2 THAT WERE WRONG, AND WHY
-------------------------------------------------
1. "41 of 41 NOT IN MASTER" was a FALSE NEGATIVE. The tickers call returned
   exactly 50,000 rows -- the limit, i.e. truncated -- and what came back was
   dominated by non-equities (13,247 holdings_investor, 8,650 insiders,
   8,347 funds; only 11,052 rows with table='stocks'). The audit never saw
   the equity rows. It proves nothing. Redone here against a properly
   filtered, fully paged master.

2. "WM -> 7,215 rows, 1997-12-31..2026-09-08" is NOT Washington Mutual.
   That is Waste Management, still trading. So dead-large-cap coverage by
   symbol is 0/8, not 1/8 -- and that failure is itself another instance of
   the same symbol-reuse bug the audit found.

THE CLUE THAT MATTERS
---------------------
The §2 output leaked Sharadar's disambiguation convention. A date-keyed
stocks query returned tickers 'CA1' and 'SEMI1'. Sharadar appears to append
a numeric suffix to the OLDER holder of a reused symbol -- so Computer
Associates is likely 'CA1' while 'CA' is whoever holds it now. If that is
right, every dead company in this repo is reachable, just not under the
symbol it traded as.

QUESTIONS THIS PASS ANSWERS
---------------------------
A. Paging -- how do we walk past 50,000 rows? (offset / cursor / page /
   format=json envelope). Without this nothing bulk can be pulled.
B. The real equity master -- how many table='stocks' rows, how many dead.
C. The suffix convention -- resolve LEH/BSC/ENE/SHLD/FRC/SIVB/BBBY/WM and
   all 41 contaminated symbols to permatickers and real names.
D. Sizing -- rows per date in stocks and daily, and how far back `daily`
   reaches. Decides whether the PIT universe pull is hours or days.

    export SHARADAR_API_KEY="..."
    python3 sharadar_universe_probe3.py

Read-only. Writes one JSON report under final/out/.
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
OUT = Path(__file__).resolve().parent.parent / "out" / "sharadar_universe_probe3.json"
DELAY = 0.25

CONTAMINATED = [
    "AT", "NSM", "MMI", "WB", "TSG", "FDC", "MI", "CCEP", "DTV", "STR",
    "SE", "ALTR", "ADT", "PLL", "EQ", "PD", "TE", "ADCT", "SII", "DNB",
    "MON", "HCP", "HMA", "EP", "STI", "DO", "EMC", "INFO", "KG", "FB",
    "PCL", "CAM", "POM", "SPLS", "SGP", "APC", "CA", "NFX", "BBBY",
    "EQR", "CSRA",
]

DEAD = {
    "LEH": "Lehman Brothers", "BSC": "Bear Stearns",
    "WM": "Washington Mutual", "ENE": "Enron",
    "SHLD": "Sears Holdings", "BBBY": "Bed Bath & Beyond",
    "FRC": "First Republic", "SIVB": "Silicon Valley Bank",
}

SIZE_DATES = ["2008-06-30", "2015-06-30", "2022-06-30"]


def raw(table, params=None, timeout=120, fmt="csv"):
    p = {"api_key": API_KEY, "format": fmt}
    if params:
        p.update(params)
    try:
        r = requests.get(f"{BASE_URL}/{table}", params=p, timeout=timeout)
    except requests.RequestException as e:
        return None, f"request failed: {e}"
    if r.status_code != 200:
        return None, f"HTTP {r.status_code}: {r.text[:200].strip()}"
    return r, None


def get(table, params=None, timeout=120):
    r, err = raw(table, params, timeout)
    if err:
        return None, err
    if not r.text.strip():
        return [], None
    return list(csv.DictReader(io.StringIO(r.text))), None


def show(t):
    print("\n" + "=" * 76)
    print(t)
    print("=" * 76)


def main():
    if not API_KEY:
        sys.exit('SHARADAR_API_KEY not set.  export SHARADAR_API_KEY="..."')
    rep = {}

    # ------------------------------------------------------------- A
    show("A. PAGING -- how do we get past 50,000 rows?")
    print("  Each trial asks for 3 rows starting at offset 10 and prints the")
    print("  first ticker. If a mechanism works, that ticker DIFFERS from the")
    print("  no-offset baseline.\n")
    base, err = get("tickers", {"table": "stocks", "limit": 3})
    base_first = base[0].get("ticker") if base else None
    print(f"  baseline (no offset)          first ticker = {base_first}")
    if err:
        print(f"  baseline failed: {err}")
    page = {}
    for name, params in [
        ("offset",  {"table": "stocks", "limit": 3, "offset": 10}),
        ("skip",    {"table": "stocks", "limit": 3, "skip": 10}),
        ("page",    {"table": "stocks", "limit": 3, "page": 2}),
        ("start",   {"table": "stocks", "limit": 3, "start": 10}),
        ("cursor?", {"table": "stocks", "limit": 3, "cursor": ""}),
    ]:
        time.sleep(DELAY)
        rows, e = get("tickers", params)
        if e:
            print(f"  {name:<12} -> {e[:60]}")
            page[name] = {"error": e}
            continue
        f = rows[0].get("ticker") if rows else None
        works = (f is not None and f != base_first)
        print(f"  {name:<12} -> {len(rows)} rows, first={f}   "
              f"{'WORKS' if works else 'no effect'}")
        page[name] = {"first": f, "works": works}

    # does format=json carry a pagination envelope?
    time.sleep(DELAY)
    r, e = raw("tickers", {"table": "stocks", "limit": 2}, fmt="json")
    if e:
        print(f"\n  format=json -> {e[:70]}")
    else:
        txt = r.text[:600]
        print(f"\n  format=json envelope (first 600 chars):\n    {txt}")
        page["json_envelope"] = txt
    rep["paging"] = page

    # ------------------------------------------------------------- B
    show("B. THE REAL EQUITY MASTER -- table='stocks' only")
    rows, err = get("tickers", {"table": "stocks", "limit": 50000}, timeout=300)
    if err:
        print(f"  FAILED: {err}")
        rep["master"] = {"error": err}
        rows = []
    else:
        print(f"  rows returned: {len(rows):,}"
              f"{'   <-- AT LIMIT, still truncated' if len(rows) >= 50000 else ''}")
        tabs = Counter(r.get("table", "") for r in rows)
        print(f"  table values : {tabs.most_common(6)}")
        dead_n = sum(1 for r in rows if r.get("isdelisted") == "Y")
        print(f"  isdelisted=Y : {dead_n:,} of {len(rows):,}")
        print(f"  category     : {Counter(r.get('category','') for r in rows).most_common(8)}")
        fp = sorted(r.get("firstpricedate", "") for r in rows if r.get("firstpricedate"))
        lp = sorted(r.get("lastpricedate", "") for r in rows if r.get("lastpricedate"))
        if fp:
            print(f"  firstpricedate spans {fp[0]} .. {fp[-1]}")
        if lp:
            print(f"  lastpricedate  spans {lp[0]} .. {lp[-1]}")
        rep["master"] = {"n": len(rows), "n_delisted": dead_n,
                         "truncated": len(rows) >= 50000}

    bysym = {}
    byname = []
    for r in rows:
        bysym.setdefault(r.get("ticker", ""), []).append(r)
        byname.append((r.get("name", "").upper(), r))

    def dump(sym):
        ent = bysym.get(sym, [])
        if not ent:
            return None
        out = []
        for e in ent:
            out.append({
                "permaticker": e.get("permaticker"), "name": e.get("name"),
                "isdelisted": e.get("isdelisted"),
                "first": e.get("firstpricedate"), "last": e.get("lastpricedate"),
                "related": e.get("relatedtickers"), "exchange": e.get("exchange"),
            })
            print(f"      {e.get('permaticker','?'):<9} "
                  f"{sym:<7} {str(e.get('isdelisted')):<2} "
                  f"{str(e.get('firstpricedate')):<11}..{str(e.get('lastpricedate')):<11} "
                  f"{(e.get('name') or '')[:36]:<36} rel={e.get('relatedtickers','')}")
        return out

    # ------------------------------------------------------------- C
    show("C. SUFFIX CONVENTION -- is the dead company at TICKER + digit?")
    print("  Sharadar returned 'CA1' and 'SEMI1' from a 2015 date query, which")
    print("  suggests the older holder of a reused symbol gets a numeric suffix.\n")
    sfx = {}
    for sym, who in DEAD.items():
        print(f"  {sym}  ({who})")
        got = {}
        for cand in (sym, sym + "1", sym + "2"):
            d = dump(cand)
            if d:
                got[cand] = d
        if not got:
            print("      -- nothing in master under this symbol or its suffixes")
        sfx[sym] = got
    rep["dead_resolution"] = sfx

    # name search as the backstop
    print("\n  name search backstop (substring match on the master's name field):")
    for frag in ["LEHMAN", "BEAR STEARNS", "WASHINGTON MUTUAL", "ENRON",
                 "SEARS", "BED BATH", "FIRST REPUBLIC", "SVB", "SILICON VALLEY"]:
        hits = [(n, r) for n, r in byname if frag in n][:3]
        if hits:
            for n, r in hits:
                print(f"    {frag:<18} -> {r.get('ticker'):<8} "
                      f"perma={r.get('permaticker'):<9} del={r.get('isdelisted')} "
                      f"{r.get('firstpricedate')}..{r.get('lastpricedate')}  {n[:34]}")
        else:
            print(f"    {frag:<18} -> no match")

    # ------------------------------------------------------------- C2
    show("C2. THE 41 CONTAMINATED SYMBOLS -- resolved against the real master")
    audit = {}
    multi = []
    for t in CONTAMINATED:
        ent = bysym.get(t, [])
        alts = [c for c in (t + "1", t + "2") if c in bysym]
        print(f"  {t:<7} {len(ent)} under symbol"
              + (f", suffixed variants present: {alts}" if alts else ""))
        audit[t] = {"direct": dump(t) or [], "suffixed": {}}
        for a in alts:
            audit[t]["suffixed"][a] = dump(a)
        if len(ent) + len(alts) > 1:
            multi.append(t)
    print(f"\n  symbols resolving to more than one company: {len(multi)}")
    print(f"  {multi}")
    rep["contamination_resolution"] = audit

    # ------------------------------------------------------------- D
    show("D. SIZING -- rows per date, and how far back `daily` reaches")
    size = {}
    for d in SIZE_DATES:
        for tbl in ("stocks", "daily"):
            time.sleep(DELAY)
            rows2, e = get(tbl, {"date": d, "limit": 50000}, timeout=300)
            if e:
                print(f"  {tbl:<7} {d} -> {e[:60]}")
                size[f"{tbl}:{d}"] = {"error": e}
                continue
            n = len(rows2)
            note = "  <-- AT LIMIT, truncated" if n >= 50000 else ""
            extra = ""
            if tbl == "daily" and rows2:
                big = 0
                for r2 in rows2:
                    try:
                        if float(r2.get("marketcap") or 0) >= 2e9:
                            big += 1
                    except ValueError:
                        pass
                extra = f"   >=$2B: {big:,}"
            print(f"  {tbl:<7} {d} -> {n:,} rows{extra}{note}")
            size[f"{tbl}:{d}"] = {"n": n}
            if tbl == "daily" and rows2:
                size[f"{tbl}:{d}"]["n_over_2b"] = big

    time.sleep(DELAY)
    rows3, e = get("daily", {"ticker": "AAPL"}, timeout=300)
    if e:
        print(f"\n  daily history depth (AAPL) -> {e[:60]}")
    else:
        ds = sorted(r.get("date", "") for r in rows3 if r.get("date"))
        print(f"\n  daily history depth (AAPL): {len(rows3):,} rows  "
              f"{ds[0] if ds else '?'} .. {ds[-1] if ds else '?'}")
        size["daily_depth_AAPL"] = {"n": len(rows3),
                                    "first": ds[0] if ds else None,
                                    "last": ds[-1] if ds else None}
    rep["sizing"] = size

    OUT.parent.mkdir(parents=True, exist_ok=True)
    json.dump(rep, open(OUT, "w"), indent=2, default=str)
    print(f"\nSaved -> {OUT}")
    print("\nSections A, C and D decide the pull plan. Paste them back.")


if __name__ == "__main__":
    main()
