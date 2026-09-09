"""
Offline audit: are the "gap ticker" price files actually the companies
they are named for?

No network. Runs entirely off files already in the repo.

THE TEST
--------
A gap ticker exists in the panel because it WAS an S&P 500 constituent at
some backtest timepoint and is missing from today's >$2B universe. So its
price history must overlap its index membership. If a file's price series
BEGINS AFTER the company's last day in the index, the file cannot be that
company -- the symbol was reissued and the by-ticker pull returned a
different issuer.

Inputs
    scripts/pit_universe/sp500_updated.csv    date,tickers  (daily membership)
    scripts/td_data_delisted/*.csv            date,open,high,low,close,volume
    scripts/td_data_delisted_repaired_causal/*.csv

Exit status is 1 if any contaminated file is found, so this can be wired
into the validation gates as a hard precondition.
"""
import argparse
import csv
import os
import sys
from collections import Counter
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
SP500 = SCRIPTS / "pit_universe" / "sp500_updated.csv"
PRICE_DIRS = ["td_data_delisted", "td_data_delisted_repaired_causal"]


def sp500_spans():
    """ticker -> (first_date_in_index, last_date_in_index)"""
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


def price_span(path):
    with open(path) as fh:
        rows = list(csv.reader(fh))[1:]
    if not rows:
        return 0, None, None
    return len(rows), rows[0][0], rows[-1][0]


def audit(pdir, span, verbose=True):
    d = SCRIPTS / pdir
    if not d.is_dir():
        return None
    bad, ok, unknown = [], 0, []
    for f in sorted(os.listdir(d)):
        if not f.endswith(".csv"):
            continue
        t = f[:-4]
        n, first, last = price_span(d / f)
        if n == 0:
            continue
        s = span.get(t)
        if s is None:
            unknown.append(t)
            continue
        if first > s[1]:
            bad.append((t, n, first, last, s[0], s[1]))
        else:
            ok += 1
    if verbose:
        print(f"\n{'=' * 78}\n{pdir}\n{'=' * 78}")
        print(f"  clean {ok}   contaminated {len(bad)}   "
              f"no-membership-record {len(unknown)}")
        if bad:
            print(f"\n  price series starts AFTER the company left the index -- "
                  f"wrong issuer:")
            print("  %-8s %-8s %-12s %-12s %-12s %-12s"
                  % ("ticker", "nrows", "px_first", "px_last",
                     "sp500_first", "sp500_last"))
            for r in sorted(bad, key=lambda x: x[2]):
                print("  %-8s %-8d %-12s %-12s %-12s %-12s" % r)
            yr = Counter()
            for t, *_ in bad:
                for row in list(csv.reader(open(d / f"{t}.csv")))[1:]:
                    yr[row[0][:4]] += 1
            print(f"\n  wrong-issuer bars in panel: {sum(yr.values()):,}")
            print(f"  by year: {sorted(yr.items())}")
        if unknown:
            print(f"\n  no membership record: {unknown}")
    return bad


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args()
    span = sp500_spans()
    print(f"S&P 500 members ever recorded: {len(span):,}")
    worst = 0
    for pdir in PRICE_DIRS:
        bad = audit(pdir, span, verbose=not a.quiet)
        if bad:
            worst = max(worst, len(bad))
    if worst:
        print(f"\nFAIL -- {worst} contaminated files. Re-pull by permaticker.")
        sys.exit(1)
    print("\nPASS -- every gap file overlaps its index membership.")


if __name__ == "__main__":
    main()
