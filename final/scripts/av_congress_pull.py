"""
Pull every congressional stock-trade disclosure Alpha Vantage has, one call
per member (POLITICIAN_METADATA -> CONGRESS_TRADES?bioguide_id=...), into
final/data/alphavantage/congress/.

WHY (models/2026-09-23-insider-congress-results.md): the feed carries
transaction_date, notification_date AND filed_date, so a backtest can key on
when a trade became public. It cannot be tested on the nomination era (House
coverage starts mid-2018; 2014-2019 is almost Senate-only) and 2020-2026 is
spent, so this pull exists to (a) start a forward, pre-registered record and
(b) let a live-only overlay be built. Per member rather than per symbol:
symbol queries resolve to today's issuer.

The MCP connector's key is free tier (25 requests/day); ~1,150 members needs
the premium key used for av_options_pull.py.

RUN (on Gabe's machine; key from the environment, never in a file):
  cd /Users/ggraham/pipe_dream
  ALPHAVANTAGE_API_KEY=... python3 final/scripts/av_congress_pull.py
Resumable: members with a saved raw file are skipped. Then
  python3 final/scripts/av_congress_pull.py --combine-only
writes congress_trades.parquet from the raw files.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

import pandas as pd

AV_URL = "https://www.alphavantage.co/query"
OUT = Path("/Users/ggraham/pipe_dream/final/data/alphavantage/congress")
RATE_PER_MIN = 60


def get(params: dict, key: str) -> dict:
    q = urllib.parse.urlencode({**params, "apikey": key})
    for attempt in range(5):
        try:
            r = json.loads(urllib.request.urlopen(f"{AV_URL}?{q}", timeout=60).read())
        except Exception:  # network/JSON: back off and retry
            time.sleep(5 * (attempt + 1))
            continue
        msg = str(r.get("Information", "")) + str(r.get("Note", "")) + str(r.get("error", ""))
        if "rate" in msg.lower() or "frequency" in msg.lower():
            time.sleep(30)
            continue
        return r
    raise RuntimeError(f"failed after retries: {params}")


def combine() -> pd.DataFrame:
    rows = []
    for p in sorted((OUT / "raw").glob("*.json")):
        rows.extend(json.loads(p.read_text()).get("trades", []))
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    for c in ("transaction_date", "notification_date", "filed_date"):
        df[c] = pd.to_datetime(df[c], errors="coerce")
    for c in ("amount_min", "amount_max"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    n0 = len(df)
    df = df.drop_duplicates()
    bad = df["filed_date"] < df["transaction_date"]
    print(f"combined {n0:,} rows, {n0 - len(df):,} duplicates dropped, "
          f"{int(bad.sum()):,} with filed_date < transaction_date flagged (kept, column `filed_before_trade`)")
    df["filed_before_trade"] = bad
    df.to_parquet(OUT / "congress_trades.parquet", index=False)
    print(df.groupby([df["transaction_date"].dt.year, "chamber"]).size().unstack(fill_value=0).to_string())
    return df


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--combine-only", action="store_true")
    args = ap.parse_args()
    (OUT / "raw").mkdir(parents=True, exist_ok=True)
    if args.combine_only:
        combine(); return
    key = os.environ.get("ALPHAVANTAGE_API_KEY") or sys.exit("set ALPHAVANTAGE_API_KEY in the environment")
    meta_path = OUT / "politician_metadata.json"
    if not meta_path.exists():
        meta_path.write_text(json.dumps(get({"function": "POLITICIAN_METADATA"}, key)))
    members = json.loads(meta_path.read_text())["politicians"]
    gap = 60.0 / RATE_PER_MIN
    todo = [m["bioguide_id"] for m in members if not (OUT / "raw" / f"{m['bioguide_id']}.json").exists()]
    print(f"{len(members)} members, {len(todo)} to pull", flush=True)
    for i, bid in enumerate(todo):
        t = time.monotonic()
        r = get({"function": "CONGRESS_TRADES", "bioguide_id": bid}, key)
        if r.get("trades_truncated"):
            print(f"  WARNING {bid}: response truncated ({r.get('trades_total_count')} total)", flush=True)
        tmp = OUT / "raw" / f"{bid}.json.tmp"
        tmp.write_text(json.dumps(r)); tmp.rename(OUT / "raw" / f"{bid}.json")
        if i % 50 == 0:
            print(f"  {i+1}/{len(todo)} {bid}: {len(r.get('trades', []))} trades", flush=True)
        time.sleep(max(0.0, gap - (time.monotonic() - t)))
    combine()


if __name__ == "__main__":
    main()
