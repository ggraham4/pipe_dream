"""
Resolve gap-ticker symbols to Sharadar permatickers. Offline.

Runs entirely off files already on disk -- no API key, no network:
    final/data/sharadar/tickers_master.csv      (20,965 equity rows)
    final/scripts/pit_universe/sp500_updated.csv
    final/scripts/td_data_delisted/*.csv        (the symbols to resolve)

WHY THIS REPLACES THE RESOLVER INSIDE sharadar_build_identity_map.py
--------------------------------------------------------------------
That version had two defects, both visible in its own output.

1. It treated a trailing 'O' as a bankruptcy-style suffix alongside 'Q'.
   Nothing justifies that, and it manufactured false candidates:
       AT  -> ATO  ATMOS ENERGY   (rel empty; matched ONLY on the 'O' rule)
       TE  -> TEO  TELECOM ARGENTINA
   The right answers, AT1 ALLTEL and TE1 TECO ENERGY, were present and lost
   to symbols that have nothing to do with them. Only 'Q' is a real
   convention here.

2. Its tie-break among date-overlapping candidates sorted by the END of the
   overlap, which is not a measure of fit at all. Where a related-but-wrong
   company is still listed today, it always won:
       BBBY  -> NXH   NEIGHBORHOOD INTELLIGENCE  (rel=BYON OSTK BBBY)
                      beating BBBYQ BED BATH & BEYOND
       INFO  -> TCX   TUCOWS      (rel=INFO)  beating INFO1 IHS MARKIT
       DTV   -> DTE   DTE ENERGY  (rel=..DTV..) beating DTV1 DIRECTV
   Each of those runners-up is the actual S&P 500 constituent.

THE RULE THIS USES
------------------
Applied strictly in this order:

  1. DATE FILTER. Discard any candidate whose [firstpricedate,
     lastpricedate] does not overlap the window in which the symbol was
     actually in the S&P 500. This is what separates Alltel from Atlantic
     Power under 'AT', and Motorola Mobility from Marcus & Millichap under
     'MMI'. It runs FIRST, before any preference ordering, because a
     company that was not trading when the symbol was in the index cannot
     be the constituent no matter how well it matches otherwise.

  2. SOURCE CLASS. Among survivors, prefer in this order:
         0  ticker == symbol                    (still the same company)
         1  ticker == symbol + digits           (SGP1, CA1, MON2)
         2  ticker == symbol + 'Q'              (BBBYQ, LEHMQ, WAMUQ)
         3  symbol appears in relatedtickers    (weakest -- a mention only)
     Class 3 is where every one of the bad picks above came from. A company
     listing another's symbol in relatedtickers is asserting a relationship,
     not an identity.

  3. OVERLAP LENGTH. Within a class, the candidate covering more of the
     membership window wins.

The suffix NUMBER is never consulted. It is assigned by recency, so it
carries no meaning: MON1 is the Money Store, MON2 is Monsanto.

OUTPUT
    final/data/sharadar/identity_map_v2.csv   one row per symbol, with the
        chosen permaticker, the runner-up, and a review flag
    stdout: every symbol where the choice was close enough to check by hand

    python3 resolve_identity_map.py
"""
import csv
import os
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MASTER = ROOT / "data" / "sharadar" / "tickers_master.csv"
SP500 = ROOT / "scripts" / "pit_universe" / "sp500_updated.csv"
GAPDIR = ROOT / "scripts" / "td_data_delisted"
OUT = ROOT / "data" / "sharadar" / "identity_map_v2.csv"

CLASS_NAME = {0: "exact", 1: "numeric-suffix", 2: "Q-suffix", 3: "related-only"}


def d(s):
    try:
        return date(int(s[:4]), int(s[5:7]), int(s[8:10]))
    except (ValueError, TypeError, IndexError):
        return None


def sp500_spans():
    span = {}
    with open(SP500) as fh:
        for row in csv.DictReader(fh):
            dt = row["date"]
            for t in row["tickers"].split(","):
                t = t.strip()
                if not t:
                    continue
                cur = span.get(t)
                if cur is None:
                    span[t] = [dt, dt]
                else:
                    if dt < cur[0]:
                        cur[0] = dt
                    if dt > cur[1]:
                        cur[1] = dt
    return span


def source_class(sym, row):
    t = row.get("ticker") or ""
    if t == sym:
        return 0
    tail = t[len(sym):]
    if t.startswith(sym) and tail.isdigit() and tail:
        return 1
    if t == sym + "Q":
        return 2
    if sym in (row.get("relatedtickers") or "").split():
        return 3
    return None


def overlap_days(a0, a1, b0, b1):
    lo, hi = max(a0, b0), min(a1, b1)
    return (hi - lo).days if hi >= lo else -1


def main():
    master = list(csv.DictReader(open(MASTER)))
    span = sp500_spans()
    syms = sorted(f[:-4] for f in os.listdir(GAPDIR) if f.endswith(".csv"))

    rows, review, unresolved = [], [], []
    for sym in syms:
        s = span.get(sym)
        s0, s1 = (d(s[0]), d(s[1])) if s else (None, None)

        scored = []
        for r in master:
            cls = source_class(sym, r)
            if cls is None:
                continue
            f, l = d(r.get("firstpricedate")), d(r.get("lastpricedate"))
            ov = overlap_days(s0, s1, f, l) if (s0 and f and l) else -1
            scored.append((ov, cls, r))

        # step 1: date filter, then 2: class, then 3: overlap
        viable = [x for x in scored if x[0] >= 0]
        viable.sort(key=lambda x: (x[1], -x[0]))

        best = viable[0] if viable else None
        second = viable[1] if len(viable) > 1 else None
        if not best:
            unresolved.append((sym, scored))

        # worth a human look when the runner-up is in the same class,
        # or when the only match is a bare relatedtickers mention
        flag = ""
        if best and second and best[1] == second[1]:
            flag = "same-class-runner-up"
        elif best and best[1] == 3:
            flag = "related-only"

        br = best[2] if best else {}
        sr = second[2] if second else {}
        if flag:
            review.append((sym, s, best, second))

        rows.append({
            "symbol": sym,
            "sp500_first": s[0] if s else "",
            "sp500_last": s[1] if s else "",
            "permaticker": br.get("permaticker", ""),
            "sharadar_ticker": br.get("ticker", ""),
            "name": br.get("name", ""),
            "isdelisted": br.get("isdelisted", ""),
            "firstpricedate": br.get("firstpricedate", ""),
            "lastpricedate": br.get("lastpricedate", ""),
            "match_class": CLASS_NAME.get(best[1], "") if best else "",
            "overlap_days": best[0] if best else "",
            "needs_review": flag,
            "runner_up": (f"{sr.get('ticker')}:{sr.get('permaticker')}:"
                          f"{sr.get('name','')[:30]}" if second else ""),
            "n_viable": len(viable),
        })

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    changed = [r for r in rows
               if r["sharadar_ticker"] and r["sharadar_ticker"] != r["symbol"]]
    print(f"symbols            : {len(rows)}")
    print(f"resolved           : {sum(1 for r in rows if r['permaticker'])}")
    print(f"unresolved         : {len(unresolved)} {[u[0] for u in unresolved]}")
    print(f"pulled under WRONG symbol: {len(changed)}")
    print(f"flagged for review : {len(review)}")
    print(f"\n-> {OUT}")

    print("\n" + "=" * 76)
    print("RESOLVED TO A DIFFERENT SYMBOL THAN WE PULLED")
    print("=" * 76)
    print("  %-8s %-9s %-9s %-15s %s" % ("symbol", "->", "perma", "class", "name"))
    for r in changed:
        print("  %-8s %-9s %-9s %-15s %s"
              % (r["symbol"], r["sharadar_ticker"], r["permaticker"],
                 r["match_class"], r["name"][:40]))

    if review:
        print("\n" + "=" * 76)
        print("NEEDS A HUMAN LOOK -- runner-up in the same class, or")
        print("the only evidence is a relatedtickers mention")
        print("=" * 76)
        for sym, s, best, second in review:
            print(f"\n  {sym}   in index {s[0]}..{s[1]}")
            for tag, x in (("chosen", best), ("runner", second)):
                if not x:
                    continue
                ov, cls, r = x
                print(f"    {tag:<7} {r.get('ticker'):<9} {r.get('permaticker'):<9} "
                      f"{CLASS_NAME[cls]:<15} ov={ov:>5}d  "
                      f"{r.get('firstpricedate')}..{r.get('lastpricedate')}  "
                      f"{r.get('name','')[:36]}")

    if unresolved:
        print("\n" + "=" * 76)
        print("UNRESOLVED -- no candidate overlaps the membership window")
        print("=" * 76)
        for sym, scored in unresolved:
            s = span.get(sym)
            print(f"\n  {sym}  in index {s[0] if s else '?'}..{s[1] if s else '?'}")
            for ov, cls, r in sorted(scored, key=lambda x: x[1])[:4]:
                print(f"    {r.get('ticker'):<9} {r.get('permaticker'):<9} "
                      f"{CLASS_NAME[cls]:<15} "
                      f"{r.get('firstpricedate')}..{r.get('lastpricedate')}  "
                      f"{r.get('name','')[:36]}")


if __name__ == "__main__":
    main()
