"""
WO-15: SUE-only live pull of Sharadar SF1 ARQ eps.
Pre-registration: final/models/2026-09-26-sue-forward-ledger.md (section 4).

    python final/src/sue/sf1_eps_live_pull.py          # pull + atomic write
    python final/src/sue/sf1_eps_live_pull.py --dry    # pull, validate, write nothing

Why a separate file: data/sharadar/sf1_fundamentals.parquet ends 2026-09-08,
no Retrain step refreshes it, and it must NOT change (WO-14's overlap check
and the ext ledger's leverage read it). sharadar_pull_fundamentals.py must
never be run with SHARADAR_START/END: it overwrites that file with only those
years. This script writes ONLY data/sharadar/sf1_arq_eps_live.parquet.

- endpoint /v1.0/data/fundamentals (as sharadar_pull_fundamentals.py),
  dimension=ARQ, date.gte = today - 4 years (>= 12 quarters for the 8-D sd)
- ONE fresh pull = one consistent split basis. Never unioned with the 09-08
  file for SUE.
- columns ticker, dimension, date, reportperiod, eps, lastupdated + pulled_at
- hard cap MAX_CALLS = 15 API calls per pull; hitting it aborts, writes nothing
- atomic: temp file -> validate -> replace; a dated backup of the old file is
  kept when replacing
- SHARADAR_API_KEY from the environment only; never printed or written.
Exit 0 = written (or --dry ok); 1 = failed, nothing replaced; 2 = BLOCKED (no key).
"""
import argparse
import csv
import io
import json
import os
import sys
import time
from pathlib import Path

import pandas as pd
import requests

MAIN = Path("/Users/ggraham/pipe_dream/final")
LIVE = MAIN / "data" / "sharadar" / "sf1_arq_eps_live.parquet"
BASE_URL = "https://api.sharadar.com/v1.0/data/fundamentals"
PAGE = 10000
MAX_CALLS = 15
YEARS_BACK = 4
KEEP = ["ticker", "dimension", "date", "reportperiod", "eps", "lastupdated"]
DELAY = 0.2


def log(m):
    print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)


class CallCap(Exception):
    pass


def pull(api_key, date_gte):
    calls, rows = 0, []
    off = 0
    while True:
        if calls >= MAX_CALLS:
            raise CallCap(f"hard cap of {MAX_CALLS} API calls reached before paging finished")
        params = {"api_key": api_key, "format": "csv", "dimension": "ARQ",
                  "date.gte": date_gte, "limit": PAGE, "offset": off}
        last = None
        for attempt in range(3):
            try:
                r = requests.get(BASE_URL, params=params, timeout=180)
            except requests.RequestException as e:
                last = f"{type(e).__name__}"
                r = None
            calls += 1
            if r is not None and r.status_code == 200:
                break
            if r is not None:
                last = f"HTTP {r.status_code}"
            if calls >= MAX_CALLS:
                raise CallCap(f"hard cap of {MAX_CALLS} API calls reached (last error {last})")
            time.sleep(2 ** attempt)
        else:
            raise RuntimeError(f"page offset {off} failed after retries: {last}")
        chunk = list(csv.DictReader(io.StringIO(r.text))) if r.text.strip() else []
        if chunk and "lastupdated" not in chunk[0]:
            raise RuntimeError("endpoint returned no lastupdated column")
        rows += [{c: x.get(c) for c in KEEP} for x in chunk]
        log(f"  call {calls}: offset {off}, {len(chunk):,} rows (total {len(rows):,})")
        if len(chunk) < PAGE:
            break
        off += PAGE
        time.sleep(DELAY)
    return rows, calls


def validate(df, pull_day):
    probs = []
    if df.empty:
        probs.append("empty")
    if set(df["dimension"].unique()) != {"ARQ"}:
        probs.append(f"dimensions {set(df['dimension'].unique())}")
    if df[["ticker", "date", "reportperiod"]].isna().any().any():
        probs.append("null keys")
    if df["date"].max() < pull_day - pd.Timedelta(days=7):
        probs.append(f"max date {df['date'].max().date()} older than pull day - 7")
    if len(df) < 50000:
        probs.append(f"only {len(df)} rows")
    if df["lastupdated"].isna().any():
        probs.append("null lastupdated")
    return probs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args()
    key = os.environ.get("SHARADAR_API_KEY")
    if not key:
        print("BLOCKED: SHARADAR_API_KEY is not set. Run from a login shell that sources "
              "~/.config/pipe_dream/secrets.env, e.g.:\n  zsh -lc 'python "
              "final/src/sue/sf1_eps_live_pull.py'", file=sys.stderr)
        return 2
    now = pd.Timestamp.now()
    pull_day = now.normalize()
    date_gte = (pull_day - pd.DateOffset(years=YEARS_BACK)).date().isoformat()
    log(f"pulling SF1 ARQ eps, date >= {date_gte} (cap {MAX_CALLS} calls)")
    try:
        rows, calls = pull(key, date_gte)
    except (CallCap, RuntimeError) as e:
        print(f"SF1 LIVE PULL FAILED (nothing written): {e}", file=sys.stderr)
        return 1
    df = pd.DataFrame(rows, columns=KEEP)
    df["eps"] = pd.to_numeric(df["eps"], errors="coerce")
    for c in ("date", "reportperiod", "lastupdated"):
        df[c] = pd.to_datetime(df[c])
    df["ticker"] = df["ticker"].astype(str)
    n_raw = len(df)
    df = df.drop_duplicates().sort_values(["ticker", "date", "reportperiod"]).reset_index(drop=True)
    df["pulled_at"] = now.isoformat()
    probs = validate(df, pull_day)
    # re-stamping diagnostic: share of tickers whose rows all carry one lastupdated
    g = df.groupby("ticker")["lastupdated"]
    multi = g.size() > 1
    one_stamp = (g.nunique() == 1)[multi]
    info = {"pulled_at": now.isoformat(), "api_calls": calls, "date_gte": date_gte,
            "rows_raw": n_raw, "rows": int(len(df)), "tickers": int(df["ticker"].nunique()),
            "date_max": df["date"].max().date().isoformat(),
            "lastupdated_max": df["lastupdated"].max().date().isoformat(),
            "share_tickers_single_lastupdated (tickers with >1 row)": round(float(one_stamp.mean()), 4),
            "problems": probs}
    log(json.dumps(info))
    if probs:
        print(f"SF1 LIVE PULL FAILED validation (nothing written): {probs}", file=sys.stderr)
        return 1
    if a.dry:
        log("--dry: nothing written")
        return 0
    tmp = LIVE.with_suffix(".parquet.tmp")
    df.to_parquet(tmp, index=False)
    back = pd.read_parquet(tmp)
    assert len(back) == len(df) and list(back.columns) == list(df.columns)
    if LIVE.exists():
        old = pd.read_parquet(LIVE, columns=["pulled_at"])["pulled_at"].iloc[0]
        bk = LIVE.with_name(f"sf1_arq_eps_live_{pd.Timestamp(old).strftime('%Y-%m-%dT%H%M%S')}.parquet")
        LIVE.replace(bk)
        log(f"backup of previous pull -> {bk.name}")
    tmp.replace(LIVE)
    log(f"wrote {LIVE} ({len(df):,} rows, {calls} API calls)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
