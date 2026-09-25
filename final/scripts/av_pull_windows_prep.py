"""
Rebuild, on a fresh machine (the Windows pull host), the two gitignored inputs
the Alpha Vantage options pull needs -- straight from Sharadar, no file copy:

    final/data/sharadar/tickers_master.csv          (1 paged API table)
    final/data/sharadar/downcap_universe_v2.parquet (built locally from the
        Sharadar DAILY + SEP monthly panel 2007-10..now and SF1 share counts)

    python final/scripts/av_pull_windows_prep.py            # all steps, resumable
    python final/scripts/av_pull_windows_prep.py --verify   # checks only

Needs SHARADAR_API_KEY in the environment (never in a file inside the repo).
Every step skips work already on disk, so re-running after an interruption
is safe. Expect ~1-2 h, dominated by the monthly panel pull (~230 months x 2
tables). ~2 GB of disk.

The last step checks the rebuilt universe against the Mac's copy by NAMED
counts (Gate A7c: name what must be there). A mismatch beyond 1% means the
two machines would pull different name sets -- stop and report it.
"""
from __future__ import annotations

import argparse
import csv
import os
import subprocess
import sys
from pathlib import Path

FINAL = Path(__file__).resolve().parents[1]
SRC = FINAL / "src"
SHARADAR = FINAL / "data" / "sharadar"
PANEL_START = "2007-10"   # pull starts 2008-01-02; 20d dollar-volume window needs the lead-in

# (date, cap2000, cap500, cap150) from the Mac's downcap_universe_v2 report,
# 2026-09-22. Tolerance 1%: Sharadar revises a handful of rows over time.
EXPECTED = [
    ("2008-06-30", 947, 1993, 2953),
    ("2014-06-30", 1382, 2449, 3213),
    ("2020-06-30", 1299, 2259, 3005),
]


def env():
    e = dict(os.environ)
    e["PYTHONUTF8"] = "1"                 # Windows cp1252 chokes on company names
    e["PIPE_DREAM_FINAL"] = str(FINAL)
    return e


def run(args, **extra):
    e = env(); e.update(extra)
    print(">>", " ".join(str(a) for a in args), flush=True)
    subprocess.run([sys.executable, *map(str, args)], check=True, env=e)


def step_tickers():
    out = SHARADAR / "tickers_master.csv"
    if out.exists():
        print(f"skip: {out} exists"); return
    sys.path.insert(0, str(SRC))
    import sharadar_build_identity_map as M   # reuses its paged Sharadar client
    rows = M.get_all("tickers", {"table": "stocks"})
    SHARADAR.mkdir(parents=True, exist_ok=True)
    with open(out, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader(); w.writerows(rows)
    print(f"-> {out} ({len(rows):,} rows)")


def step_shares():
    out = SHARADAR / "sf1_shares.csv"
    if out.exists():
        print(f"skip: {out} exists"); return
    run([SRC / "sharadar_pull_shares.py"])


def step_panel():
    # the panel script itself skips months already on disk
    run([SRC / "sharadar_pull_pit_panel.py", "--start", PANEL_START])


def step_universe():
    out = SHARADAR / "downcap_universe_v2.parquet"
    if out.exists():
        print(f"skip: {out} exists"); return
    run([SRC / "reset2026" / "downcap_universe.py"], DOWNCAP_OUT_NAME="downcap_universe_v2")


def verify() -> bool:
    import pandas as pd
    ok = True
    tm = pd.read_csv(SHARADAR / "tickers_master.csv", dtype=str, usecols=["ticker", "relatedtickers"])
    for t in ["AAPL", "WB1", "LEHMQ", "BSC1", "SIVBQ"]:
        hit = t in set(tm.ticker)
        print(f"{'PASS' if hit else 'FAIL'}  tickers_master has {t}")
        ok &= hit
    u = pd.read_parquet(SHARADAR / "downcap_universe_v2.parquet",
                        columns=["date", "ticker", "eligible_cap2000", "eligible_cap500", "eligible_cap150"])
    u["date"] = pd.to_datetime(u["date"]).dt.strftime("%Y-%m-%d")
    for d, c2, c5, c1 in EXPECTED:
        g = u[u.date == d]
        got = (int(g.eligible_cap2000.sum()), int(g.eligible_cap500.sum()), int(g.eligible_cap150.sum()))
        good = all(abs(a - b) <= 0.01 * b for a, b in zip(got, (c2, c5, c1)))
        print(f"{'PASS' if good else 'FAIL'}  {d} cap2000/500/150 = {got}, Mac had {(c2, c5, c1)}")
        ok &= good
    a = u[(u.ticker == "AAPL") & (u.date == "2008-01-02")]
    good = len(a) == 1 and bool(a.eligible_cap2000.iloc[0])
    print(f"{'PASS' if good else 'FAIL'}  AAPL cap2000-eligible on 2008-01-02")
    ok &= good
    print("ALL CHECKS PASS" if ok else "CHECKS FAILED -- do not start the pull; report the FAIL lines")
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--verify", action="store_true")
    a = ap.parse_args()
    if not a.verify:
        if not os.environ.get("SHARADAR_API_KEY"):
            sys.exit("SHARADAR_API_KEY is not set in the environment")
        step_tickers(); step_shares(); step_panel(); step_universe()
    sys.exit(0 if verify() else 1)


if __name__ == "__main__":
    main()
