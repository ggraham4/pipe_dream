"""
WO-6: targeted Sharadar top-up for the survivorship-safe down-cap grid.

WHAT IT PULLS
-------------
The Phase 1 inventory (final/src/reset2026/downcap_grid_inventory.py) found
that SEP prices and SF1 ARQ/ARY for the cap500/cap150 names missing from
the old 4,011-ticker grid are ALREADY on disk for all but a handful. The bulk
SF1 pull (src/sharadar_pull_fundamentals.py) fetched every ticker by date
range. The pull list it writes, out/reset2026/downcap_v2/pull_list.csv, is
(ticker, table) rows. As of 2026-09-24 it is 14 tickers x SF1 and 0 x SEP.

For each row this script requests, per ticker:
    SF1  -> /v1.0/data/fundamentals?ticker=T&dimension=ARQ  (and ARY)
    SEP  -> /v1.0/data/sep?ticker=T&date.gte=2005-01-01
and writes one CSV per (table, dimension, ticker) under
    final/data/sharadar/downcap_pull/{sf1_ARQ,sf1_ARY,sep}/T.csv

It never touches sf1_fundamentals.parquet or panel/. Folding any rows it
finds into the grid is a separate, reviewed step, and the bulk pull already
returned nothing for these names, so an empty result is the expected one.

SAFETY
------
- The key comes ONLY from the SHARADAR_API_KEY environment variable. It is
  never written anywhere, and it is redacted from every error message.
- Resumable: a (table, ticker) whose output CSV exists, or which is recorded
  as empty in _done.txt, is skipped.
- Atomic: each response is written to <file>.tmp and then os.replace()d.
- Retries with exponential backoff (1, 2, 4, 8, 16s) on network errors,
  HTTP 429 and HTTP 5xx.
- --dry-run prints the request plan and the call count and needs no key.

USAGE (run on Gabe's machine; the sandbox has no network to Sharadar)
    python3 final/scripts/sharadar_downcap_pull.py --dry-run
    SHARADAR_API_KEY=... python3 final/scripts/sharadar_downcap_pull.py
    # other list:  --pull-list path/to/list.csv   (columns: ticker, table)
"""
import argparse
import csv
import io
import os
import sys
import time
from pathlib import Path

MAIN = Path(__file__).resolve().parent.parent          # .../final
DEFAULT_LIST = Path("/Users/ggraham/pipe_dream/final/out/reset2026/downcap_v2/pull_list.csv")
OUT_ROOT = Path("/Users/ggraham/pipe_dream/final/data/sharadar/downcap_pull")
BASE_URL = "https://api.sharadar.com/v1.0/data"
DELAY = 0.25
TRIES = 5
SEP_START = "2005-01-01"


def plan(pull_list):
    rows = list(csv.DictReader(open(pull_list)))
    reqs = []
    for r in rows:
        t, table = r["ticker"].strip(), r["table"].strip().upper()
        if table == "SF1":
            for dim in ("ARQ", "ARY"):
                reqs.append(("fundamentals", {"ticker": t, "dimension": dim},
                             OUT_ROOT / f"sf1_{dim}" / f"{t}.csv", f"sf1_{dim}:{t}"))
        elif table == "SEP":
            reqs.append(("sep", {"ticker": t, "date.gte": SEP_START},
                         OUT_ROOT / "sep" / f"{t}.csv", f"sep:{t}"))
        else:
            raise SystemExit(f"unknown table {table!r} for {t}")
    return reqs


def load_done():
    f = OUT_ROOT / "_done.txt"
    return set(f.read_text().split()) if f.exists() else set()


def mark_done(key):
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    with open(OUT_ROOT / "_done.txt", "a") as fh:
        fh.write(key + "\n")


def fetch(endpoint, params, key):
    import requests
    last = None
    for attempt in range(TRIES):
        try:
            p = {"api_key": key, "format": "csv"}
            p.update(params)
            r = requests.get(f"{BASE_URL}/{endpoint}", params=p, timeout=120)
            if r.status_code == 200:
                return r.text
            last = f"HTTP {r.status_code}: {r.text[:150]}"
            if r.status_code not in (429,) and r.status_code < 500:
                break  # 4xx other than 429: retrying will not help
        except Exception as e:  # network errors
            last = f"{type(e).__name__}: {e}"
        last = last.replace(key, "<redacted>")
        wait = 2 ** attempt
        print(f"    retry {attempt + 1}/{TRIES} in {wait}s -- {last}", flush=True)
        time.sleep(wait)
    raise RuntimeError(f"{endpoint} {params.get('ticker')}: {str(last).replace(key, '<redacted>')}")


def write_atomic(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text)
    os.replace(tmp, path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pull-list", type=Path, default=DEFAULT_LIST)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    reqs = plan(a.pull_list)
    done = load_done()
    todo = [r for r in reqs if not r[2].exists() and r[3] not in done]
    print(f"pull list: {a.pull_list}")
    print(f"requests: {len(reqs)} total, {len(reqs) - len(todo)} already done, "
          f"{len(todo)} to go")
    est = len(todo) * (DELAY + 0.8)
    print(f"estimated runtime: ~{est/60:.1f} min at ~{DELAY + 0.8:.2f}s/call")
    if a.dry_run:
        for endpoint, params, out, k in todo:
            shown = "&".join(f"{kk}={vv}" for kk, vv in params.items())
            print(f"  GET {BASE_URL}/{endpoint}?{shown}&format=csv&api_key=$SHARADAR_API_KEY -> {out}")
        return 0

    key = os.environ.get("SHARADAR_API_KEY")
    if not key:
        print("ERROR: SHARADAR_API_KEY is not set in the environment.", file=sys.stderr)
        return 2

    n_rows = n_empty = n_fail = 0
    for i, (endpoint, params, out, k) in enumerate(todo, 1):
        try:
            text = fetch(endpoint, params, key)
        except RuntimeError as e:
            n_fail += 1
            print(f"  [{i}/{len(todo)}] FAIL {k}: {e}", flush=True)
            continue
        rows = list(csv.DictReader(io.StringIO(text))) if text.strip() else []
        if rows:
            write_atomic(out, text)
            n_rows += len(rows)
        else:
            n_empty += 1
        mark_done(k)
        print(f"  [{i}/{len(todo)}] {k}: {len(rows)} rows", flush=True)
        time.sleep(DELAY)
    print(f"\ndone: {n_rows} rows written, {n_empty} empty, {n_fail} failed "
          f"(re-run to retry failures; completed requests are skipped)")
    return 1 if n_fail else 0


if __name__ == "__main__":
    sys.exit(main())
