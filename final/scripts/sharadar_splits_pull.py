"""
Run this ON YOUR OWN MACHINE (not through Claude) -- same reason
sharadar_data_pull.py and every other local_*.py script in this folder
exists: api.sharadar.com isn't reachable from Claude's cloud sandbox OR
the device-bridge shell (confirmed directly, both get a 403 from the
proxy on CONNECT).

WHAT THIS DOES AND WHY

Fixes a real data bug found 2026-09-04: the options model's expanded
universe join uses scripts/td_data_local/*.csv (split-adjusted for
continuity -- a 2024 NVDA row shows NVDA's PRICE already divided by 10 to
match today's post-split scale, even for dates before the actual
2024-06-10 split) next to DoltHub's option chain strikes, which are NOT
retroactively adjusted for later splits (a 2024-01-17 NVDA $400 strike is
a real pre-split nominal strike, not rescaled). Any ticker that split
during the window has this mismatch for all its pre-split rows -- it
corrupted moneyness, strike selection, AND the payoff/return target used
to train every options model in this project. The current workaround
(final/models/buy_no_buy_options_v2/fix_split_adjustment.py) just drops
rows with implausible moneyness -- a same-day patch, not a real fix.

This script pulls Sharadar's "actions" table (corporate actions --
confirmed to exist from Sharadar's own docs, per sharadar_data_pull.py's
module docstring) for the full expanded options universe, filters to
split-type actions, and saves them so a real per-ticker, per-date
cumulative split-adjustment factor can be computed and used to properly
RESCALE pre-split strikes (multiply by the right ratio) instead of just
deleting the affected rows.

UNCERTAIN, BY DESIGN -- READ THIS IF IT DOESN'T WORK FIRST TRY: the exact
column names and the "action" value used for splits (e.g. "split" vs
"splitfactor" vs something else), and which direction "value" encodes
(shares-after per share-before, or the reverse) were NOT confirmed against
real data before writing this (same situation sharadar_data_pull.py was
in for the fundamentals table, solved there with fuzzy column-matching +
a probe mode -- same approach here). Run with --probe-only first: it
pulls 5 tickers with well-known, well-documented splits (NVDA 10-for-1 on
2024-06-10, TSLA 3-for-1 on 2022-08-25, GOOGL/GOOG 20-for-1 on
2022-07-15, CMG 50-for-1 on 2024-06-26, SMCI 10-for-1 on 2024-09-30) and
prints every column Sharadar actually returns, plus the raw rows -- so the
parsing can be checked against dates/ratios we already know are correct
before trusting it for all 1,266 tickers. If the printed rows don't
obviously show those known splits, paste the output back to Claude before
running the full pull -- the column-matching logic below needs a one-line
fix, not a rewrite, same as every other script in this pattern.

SETUP (same key you already have, per credentials-and-env-reference.md
in the Claude Project):
    export SHARADAR_API_KEY="your-key-here"
    pip install requests

Usage:
    python3 sharadar_splits_pull.py --probe-only     # 5 known-split tickers,
                                                        prints raw columns/rows
                                                        -- run this FIRST
    python3 sharadar_splits_pull.py                  # full 1,266-ticker
                                                        expanded universe
    python3 sharadar_splits_pull.py --tickers NVDA,TSLA   # just these

Output: writes final/models/buy_no_buy_options_v2/sharadar_splits_raw.csv
(one row per detected split action: ticker, date, raw Sharadar columns
kept as-is for traceability) plus a per-run report of which tickers had
zero split rows found (expected/fine for most tickers -- most stocks
never split in this window) vs which requests actually failed.
"""
import argparse
import csv
import io
import os
import sys
import time
from pathlib import Path

import requests

SCRIPT_DIR = Path(__file__).parent
UNIVERSE_FILE = SCRIPT_DIR.parent / "models" / "buy_no_buy_options_v2" / "expanded_universe_tickers.txt"
OUT_PATH = SCRIPT_DIR.parent / "models" / "buy_no_buy_options_v2" / "sharadar_splits_raw.csv"

BASE_URL = "https://api.sharadar.com/v1.0/data"
REQUEST_DELAY_SECONDS = 0.3
API_KEY = os.environ.get("SHARADAR_API_KEY")

# well-documented splits, for --probe-only sanity checking against known truth
PROBE_TICKERS = ["NVDA", "TSLA", "GOOGL", "CMG", "SMCI"]
KNOWN_SPLITS = {
    "NVDA": "10-for-1 on 2024-06-10",
    "TSLA": "3-for-1 on 2022-08-25",
    "GOOGL": "20-for-1 on 2022-07-15",
    "CMG": "50-for-1 on 2024-06-26",
    "SMCI": "10-for-1 on 2024-09-30",
}


def fetch_table(table: str, ticker: str, extra_params: dict = None):
    params = {"api_key": API_KEY, "ticker": ticker, "format": "csv"}
    if extra_params:
        params.update(extra_params)
    try:
        resp = requests.get(f"{BASE_URL}/{table}", params=params, timeout=30)
    except requests.RequestException as e:
        print(f"    ERROR: request failed: {e}")
        return None, None
    if resp.status_code != 200:
        print(f"    ERROR: HTTP {resp.status_code}: {resp.text[:300]}")
        return None, None
    text = resp.text
    if not text.strip():
        return [], []
    reader = csv.DictReader(io.StringIO(text))
    rows = list(reader)
    return rows, reader.fieldnames or []


def probe():
    print("Probing Sharadar 'actions' table for 5 well-known splits...\n")
    for t in PROBE_TICKERS:
        print(f"--- {t} (known: {KNOWN_SPLITS[t]}) ---")
        rows, fieldnames = fetch_table("actions", t)
        time.sleep(REQUEST_DELAY_SECONDS)
        if rows is None:
            continue
        if not rows:
            print("  (empty response -- no actions at all for this ticker? unexpected for a name this size)")
            continue
        print(f"  columns: {fieldnames}")
        # print every row that looks split-related, plus first 3 rows regardless
        # so we can see the full shape of the data even if "split" isn't the
        # literal string used
        split_like = [r for r in rows if any("split" in str(v).lower() for v in r.values())]
        print(f"  {len(rows)} total action rows, {len(split_like)} contain 'split' somewhere")
        for r in (split_like or rows[:3]):
            print(f"    {r}")
        print()
    print("Check the rows above against the KNOWN_SPLITS dates/ratios in this script.\n"
          "If they don't line up (or 'split' never appears), paste this whole output\n"
          "back to Claude before running the full pull -- the parsing logic in\n"
          "pull_splits_for_ticker() below needs a one-line adjustment.")


def pull_splits_for_ticker(ticker: str):
    """Returns list of raw dict rows (whatever columns Sharadar sent back,
    kept verbatim) that look like split actions, or None on request failure."""
    rows, fieldnames = fetch_table("actions", ticker)
    if rows is None:
        return None
    if not rows:
        return []
    out = []
    for r in rows:
        action_val = ""
        for k, v in r.items():
            if k and k.lower() in ("action", "actiontype", "type"):
                action_val = str(v).lower()
                break
        # fuzzy: treat as a split if the action field says so, OR if nothing
        # matched an action-like column but some value contains "split"
        is_split = "split" in action_val
        if not action_val:
            is_split = any("split" in str(v).lower() for v in r.values())
        if is_split:
            row = dict(r)
            row["_ticker"] = ticker
            out.append(row)
    return out


def main():
    if not API_KEY:
        print('ERROR: SHARADAR_API_KEY environment variable not set.\n'
              'Run:  export SHARADAR_API_KEY="your-key-here"\nthen re-run this script.')
        sys.exit(1)

    parser = argparse.ArgumentParser()
    parser.add_argument("--probe-only", action="store_true")
    parser.add_argument("--tickers", type=str, default=None)
    args = parser.parse_args()

    if args.probe_only:
        probe()
        return

    if args.tickers:
        tickers = [t.strip().upper() for t in args.tickers.split(",")]
    else:
        if not UNIVERSE_FILE.exists():
            print(f"ERROR: {UNIVERSE_FILE} not found. Either run with --tickers, "
                  f"or make sure expanded_universe_tickers.txt is present "
                  f"(already saved there by Claude alongside the other v2 build scripts).")
            sys.exit(1)
        tickers = [t.strip() for t in UNIVERSE_FILE.read_text().splitlines() if t.strip()]

    print(f"Pulling 'actions' (splits) for {len(tickers)} tickers from Sharadar...")
    all_rows = []
    failed = []
    n_with_splits = 0
    for i, t in enumerate(tickers, 1):
        rows = pull_splits_for_ticker(t)
        if rows is None:
            failed.append(t)
        elif rows:
            n_with_splits += 1
            all_rows.extend(rows)
        if i % 50 == 0 or i == len(tickers):
            print(f"  [{i}/{len(tickers)}] ... {n_with_splits} tickers with a split found so far, "
                  f"{len(failed)} failed requests", flush=True)
        time.sleep(REQUEST_DELAY_SECONDS)

    print(f"\nDone. {n_with_splits}/{len(tickers)} tickers had at least one split action. "
          f"{len(all_rows)} total split rows. {len(failed)} tickers failed the request entirely.")
    if failed:
        print(f"Failed (network/auth error, not just 'no splits'): {failed[:30]}"
              f"{' ...' if len(failed) > 30 else ''}")

    if all_rows:
        all_fieldnames = []
        for r in all_rows:
            for k in r.keys():
                if k not in all_fieldnames:
                    all_fieldnames.append(k)
        OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(OUT_PATH, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=all_fieldnames)
            writer.writeheader()
            writer.writerows(all_rows)
        print(f"\nSaved {OUT_PATH}")
        print("Send Claude a message once this is done -- it'll pick this file up "
              "directly (it's already in the connected folder) and build the proper "
              "strike-rescale table from it.")
    else:
        print("\nNo split rows collected at all -- something is likely wrong with the "
              "column-matching logic (see the module docstring). Run --probe-only and "
              "paste the output back to Claude before trying the full pull again.")


if __name__ == "__main__":
    main()
