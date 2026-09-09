"""
Build the ticker -> permaticker identity map, and settle the marketcap units.

WHAT PROBE 3 ESTABLISHED
------------------------
  offset= (and skip=) page the API.  format=json returns {"count":N,"data":[...]}
  The equity master is 20,965 rows (table='stocks'), NOT truncated,
     14,640 of them isdelisted='Y', firstpricedate back to 1986-01-01.
  The disambiguation convention is real, and has TWO forms:
     numeric suffix on the older holder of a reused symbol
         BSC1 Bear Stearns   CA1 CA Inc   EMC1 EMC Corp   SPLS1 Staples
         APC1 Anadarko       SGP1 Schering-Plough         NFX1 Newfield
     bankruptcy 'Q' symbol, the standard OTC convention
         LEHMQ Lehman   WAMUQ Washington Mutual   ENRNQ Enron
         SHLDQ Sears    BBBYQ Bed Bath   SIVBQ SVB   FRCB First Republic
  28 of the 41 contaminated symbols resolve to more than one company.
  `relatedtickers` cross-links them: AT1 -> rel=AT, CA1 -> rel=CA.

WHY "APPEND 1" IS NOT THE RULE
------------------------------
The suffix is assigned by recency, not by which company we want:
    MMI1 = Motorola Mobility (2010-2012),  MMI2 = MMI Companies (1993-2000)
    WB1  = Wachovia (..2008-12-31),        WB2  = Wachovia (..2001-08-31)
    MON1 = Money Store (1991-1998),        MON2 = Monsanto (2000-2018)
So MON1 is NOT Monsanto. Resolving by suffix would pick the wrong company
again, in a way that looks plausible. The only correct rule is DATE
CONTAINMENT: the right company is the one whose [firstpricedate,
lastpricedate] span covers the dates we need it for -- cross-checked
against when the symbol was actually in the S&P 500.

THE UNITS PROBLEM -- THIS BLOCKS THE WHOLE UNIVERSE REBUILD
-----------------------------------------------------------
Probe 3 counted companies with daily.marketcap >= 2e9:

    daily 2008-06-30   5,880 rows   >=$2B: 1
    daily 2015-06-30   5,333 rows   >=$2B: 0
    daily 2022-06-30   6,234 rows   >=$2B: 0

Zero companies over $2B in 2015 is impossible, so `daily.marketcap` is
almost certainly denominated in MILLIONS, not dollars -- while SF1's
marketcap is in dollars (AAPL 2026-06-30 read 4508288143800). If that is
right, the >$2B screen is `marketcap >= 2000`, and getting it wrong by
1e6 would silently build a universe of the wrong ~5,000 companies.
Step 2 settles it by direct comparison rather than assumption.

OUTPUTS (final/data/sharadar/)
    tickers_master.csv     the full 20,965-row equity master
    actions.csv            corporate actions, fully paged
    identity_map.csv       symbol -> permaticker per gap ticker, with the
                           evidence and an explicit ambiguity flag
    units_report.txt

    export SHARADAR_API_KEY="..."
    python3 sharadar_build_identity_map.py
"""
import csv
import io
import json
import os
import statistics
import sys
import time
from pathlib import Path

import requests

BASE_URL = "https://api.sharadar.com/v1.0/data"
API_KEY = os.environ.get("SHARADAR_API_KEY")
ROOT = Path(__file__).resolve().parent.parent
OUTDIR = ROOT / "data" / "sharadar"
SP500 = ROOT / "scripts" / "pit_universe" / "sp500_updated.csv"
DELAY = 0.25
PAGE = 10000


def get(table, params=None, timeout=180):
    p = {"api_key": API_KEY, "format": "csv"}
    if params:
        p.update(params)
    r = requests.get(f"{BASE_URL}/{table}", params=p, timeout=timeout)
    if r.status_code != 200:
        raise RuntimeError(f"{table} HTTP {r.status_code}: {r.text[:200]}")
    if not r.text.strip():
        return []
    return list(csv.DictReader(io.StringIO(r.text)))


def get_all(table, params=None, cap=2_000_000):
    """Page with offset= until a short page comes back."""
    out, off = [], 0
    while len(out) < cap:
        p = dict(params or {})
        p.update({"limit": PAGE, "offset": off})
        chunk = get(table, p)
        out.extend(chunk)
        print(f"    {table} +{len(chunk):,} (total {len(out):,})")
        if len(chunk) < PAGE:
            break
        off += PAGE
        time.sleep(DELAY)
    return out


def write_csv(path, rows):
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"    -> {path}  ({len(rows):,} rows)")


def show(t):
    print("\n" + "=" * 76)
    print(t)
    print("=" * 76)


# ---------------------------------------------------------------- step 2
def units(report):
    show("2. MARKETCAP UNITS -- dollars or millions?")
    d = get("daily", {"ticker": "AAPL", "date.gte": "2026-06-01", "limit": 3})
    f = get("fundamentals", {"ticker": "AAPL", "dimension": "ARQ", "limit": 3})
    dv = [float(r["marketcap"]) for r in d if r.get("marketcap")]
    fv = [float(r["marketcap"]) for r in f if r.get("marketcap")]
    print(f"  daily.marketcap        (AAPL) : {dv[:3]}")
    print(f"  fundamentals.marketcap (AAPL) : {fv[:3]}")
    ratio = None
    if dv and fv:
        ratio = fv[0] / dv[0]
        print(f"  ratio fundamentals/daily      : {ratio:,.1f}")

    probe = get_all("daily", {"date": "2015-06-30"})
    vals = []
    for r in probe:
        try:
            v = float(r.get("marketcap") or 0)
        except ValueError:
            continue
        if v > 0:
            vals.append(v)
    vals.sort()
    if vals:
        print(f"\n  daily 2015-06-30: {len(vals):,} non-zero marketcaps")
        print(f"    min {vals[0]:,.2f}   median {statistics.median(vals):,.2f}"
              f"   max {vals[-1]:,.2f}")
        print(f"    count >= 2,000        (if MILLIONS, = $2B): "
              f"{sum(1 for v in vals if v >= 2_000):,}")
        print(f"    count >= 2,000,000,000 (if DOLLARS, = $2B): "
              f"{sum(1 for v in vals if v >= 2e9):,}")

    # AAPL's real market cap on 2015-06-30 was ~$725B. Whichever scale puts
    # the max near that is the right one.
    scale = None
    if vals:
        if 1e5 <= vals[-1] <= 1e7:
            scale = "MILLIONS"
        elif vals[-1] >= 1e11:
            scale = "DOLLARS"
    print(f"\n  VERDICT: daily.marketcap is in {scale or 'UNCLEAR -- inspect above'}")
    if scale == "MILLIONS":
        print("  -> the >$2B screen is  marketcap >= 2000")
    elif scale == "DOLLARS":
        print("  -> the >$2B screen is  marketcap >= 2e9")
    report["units"] = {"daily_aapl": dv[:3], "sf1_aapl": fv[:3],
                       "ratio": ratio, "scale": scale,
                       "n_2015": len(vals),
                       "max_2015": vals[-1] if vals else None}
    (OUTDIR / "units_report.txt").parent.mkdir(parents=True, exist_ok=True)
    (OUTDIR / "units_report.txt").write_text(json.dumps(report["units"], indent=2))
    return scale


# ---------------------------------------------------------------- step 3
def sp500_spans():
    span = {}
    with open(SP500) as fh:
        for row in csv.DictReader(fh):
            d = row["date"]
            for t in row["tickers"].split(","):
                t = t.strip()
                if not t:
                    continue
                cur = span.get(t)
                if cur is None:
                    span[t] = [d, d]
                else:
                    if d < cur[0]:
                        cur[0] = d
                    if d > cur[1]:
                        cur[1] = d
    return span


def candidates(sym, master, by_ticker):
    """Every master row that could plausibly BE this symbol's company."""
    out = list(by_ticker.get(sym, []))
    seen = {id(r) for r in out}
    for r in master:
        t = r.get("ticker") or ""
        rel = (r.get("relatedtickers") or "").split()
        hit = False
        # numeric suffix: SYM + digits
        if t.startswith(sym) and t[len(sym):].isdigit() and t != sym:
            hit = True
        # bankruptcy Q, and other single-letter tails
        elif len(t) == len(sym) + 1 and t.startswith(sym) and t[-1] in "QO":
            hit = True
        # cross-linked
        elif sym in rel:
            hit = True
        if hit and id(r) not in seen:
            out.append(r)
            seen.add(id(r))
    return out


def overlaps(a0, a1, b0, b1):
    if not (a0 and a1 and b0 and b1):
        return False
    return a0 <= b1 and b0 <= a1


def build_map(master, report):
    show("3. IDENTITY MAP -- which permaticker was the S&P constituent?")
    print("  Rule: the company whose [firstpricedate, lastpricedate] OVERLAPS")
    print("  the window in which the symbol was actually in the index.")
    print("  Suffix numbering is recency-ordered, NOT semantic -- MON1 is the")
    print("  Money Store, MON2 is Monsanto -- so suffix is never used to pick.\n")

    span = sp500_spans()
    by_ticker = {}
    for r in master:
        by_ticker.setdefault(r.get("ticker", ""), []).append(r)

    gapdir = ROOT / "scripts" / "td_data_delisted"
    syms = sorted(f[:-4] for f in os.listdir(gapdir) if f.endswith(".csv"))
    rows, ambiguous, unresolved = [], [], []

    for sym in syms:
        s = span.get(sym)
        cands = candidates(sym, master, by_ticker)
        matched = []
        if s:
            for c in cands:
                if overlaps(s[0], s[1], c.get("firstpricedate"), c.get("lastpricedate")):
                    matched.append(c)
        pick = matched[0] if len(matched) == 1 else None
        if len(matched) > 1:
            # prefer the one covering the MOST of the membership window
            def cover(c):
                lo = max(s[0], c.get("firstpricedate") or "9999")
                hi = min(s[1], c.get("lastpricedate") or "0000")
                return hi > lo, hi
            matched.sort(key=cover, reverse=True)
            pick = matched[0]
            ambiguous.append(sym)
        if not matched:
            unresolved.append(sym)
        rows.append({
            "symbol": sym,
            "sp500_first": s[0] if s else "",
            "sp500_last": s[1] if s else "",
            "n_candidates": len(cands),
            "n_date_matched": len(matched),
            "permaticker": pick.get("permaticker") if pick else "",
            "sharadar_ticker": pick.get("ticker") if pick else "",
            "name": pick.get("name") if pick else "",
            "isdelisted": pick.get("isdelisted") if pick else "",
            "firstpricedate": pick.get("firstpricedate") if pick else "",
            "lastpricedate": pick.get("lastpricedate") if pick else "",
            "ambiguous": "Y" if len(matched) > 1 else "",
            "all_candidates": "|".join(
                f"{c.get('ticker')}:{c.get('permaticker')}:"
                f"{c.get('firstpricedate')}..{c.get('lastpricedate')}"
                for c in cands),
        })

    write_csv(OUTDIR / "identity_map.csv", rows)
    resolved = [r for r in rows if r["permaticker"]]
    print(f"\n  gap symbols            : {len(rows)}")
    print(f"  resolved to a permaticker: {len(resolved)}")
    print(f"  ambiguous (>1 date match): {len(ambiguous)} {ambiguous[:20]}")
    print(f"  UNRESOLVED               : {len(unresolved)}")
    for u in unresolved:
        r = next(x for x in rows if x["symbol"] == u)
        print(f"    {u:<8} sp500 {r['sp500_first']}..{r['sp500_last']}  "
              f"cands={r['all_candidates'][:90]}")

    # did the symbol we pulled differ from the company we needed?
    print("\n  symbols where the CORRECT company trades under a DIFFERENT")
    print("  Sharadar ticker than the one we pulled by:")
    n = 0
    for r in rows:
        if r["sharadar_ticker"] and r["sharadar_ticker"] != r["symbol"]:
            print(f"    {r['symbol']:<8} -> {r['sharadar_ticker']:<9} "
                  f"perma {r['permaticker']:<9} {r['name'][:38]}")
            n += 1
    print(f"\n  {n} of {len(rows)} gap files were pulled under the wrong symbol.")
    report["identity"] = {"n": len(rows), "resolved": len(resolved),
                          "ambiguous": ambiguous, "unresolved": unresolved,
                          "n_wrong_symbol": n}


def main():
    if not API_KEY:
        sys.exit('SHARADAR_API_KEY not set.  export SHARADAR_API_KEY="..."')
    OUTDIR.mkdir(parents=True, exist_ok=True)
    report = {}

    show("1. MASTER + ACTIONS")
    print("  tickers (table=stocks):")
    master = get_all("tickers", {"table": "stocks"})
    write_csv(OUTDIR / "tickers_master.csv", master)
    print("  actions:")
    acts = get_all("actions")
    write_csv(OUTDIR / "actions.csv", acts)
    report["master_rows"] = len(master)
    report["action_rows"] = len(acts)

    units(report)
    build_map(master, report)

    json.dump(report, open(OUTDIR / "build_report.json", "w"), indent=2, default=str)
    print(f"\nSaved -> {OUTDIR}")
    print("\nSend back section 2's VERDICT line and section 3's summary.")
    print("tickers_master.csv and identity_map.csv are the two files to keep.")


if __name__ == "__main__":
    main()
