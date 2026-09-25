"""
Merge an Alpha Vantage pull root produced on another machine (the Windows
host) into this machine's root. Safe to run repeatedly.

    python final/scripts/av_merge_pull_roots.py --src <copied windows alphavantage dir> \
        [--dst final/data/alphavantage]

- pull_log.sqlite: rows from --src are added; where both roots logged the same
  (pass, date, ticker), a finished status (ok/no_data) wins over `error`,
  otherwise the destination row is kept.
- options/<pass>/date=*.parquet: copied if absent; if both roots have a date,
  the two are concatenated and de-duplicated on (sharadar_ticker, contractID).
  Written atomically.
Afterwards run build_option_chain_unified.py and build_av_options_features.py
(both incremental).
"""
from __future__ import annotations

import argparse
import os
import shutil
import sqlite3
from pathlib import Path

import pandas as pd

FINAL = Path(__file__).resolve().parents[1]


def merge_logs(src: Path, dst: Path):
    con = sqlite3.connect(dst / "pull_log.sqlite")
    con.execute(f"ATTACH DATABASE '{src / 'pull_log.sqlite'}' AS s")
    before = con.execute("SELECT COUNT(*) FROM calls").fetchone()[0]
    con.execute("""INSERT OR IGNORE INTO calls SELECT * FROM s.calls""")
    con.execute("""INSERT OR REPLACE INTO calls
                   SELECT sc.* FROM s.calls sc JOIN calls c
                     ON c.pass = sc.pass AND c.date = sc.date AND c.ticker = sc.ticker
                   WHERE c.status = 'error' AND sc.status IN ('ok', 'no_data')""")
    con.execute("INSERT OR IGNORE INTO symcache SELECT * FROM s.symcache")
    con.commit()
    after = con.execute("SELECT COUNT(*) FROM calls").fetchone()[0]
    con.execute("DETACH DATABASE s")
    print(f"log: {before:,} -> {after:,} rows")


def merge_parts(src: Path, dst: Path):
    n_copy = n_merge = 0
    for f in sorted((src / "options").glob("*/date=*.parquet")):
        out = dst / "options" / f.parent.name / f.name
        out.parent.mkdir(parents=True, exist_ok=True)
        if not out.exists():
            shutil.copy2(f, out); n_copy += 1; continue
        both = pd.concat([pd.read_parquet(out), pd.read_parquet(f)], ignore_index=True)
        both = both.drop_duplicates(["sharadar_ticker", "contractID"], keep="first")
        tmp = out.with_suffix(".tmp"); both.to_parquet(tmp, index=False); os.replace(tmp, out)
        n_merge += 1
    print(f"partitions: {n_copy} copied, {n_merge} merged")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", type=Path, required=True)
    ap.add_argument("--dst", type=Path, default=FINAL / "data" / "alphavantage")
    a = ap.parse_args()
    if a.src.resolve() == a.dst.resolve():
        raise SystemExit("--src and --dst are the same directory")
    merge_logs(a.src, a.dst)
    merge_parts(a.src, a.dst)


if __name__ == "__main__":
    main()
