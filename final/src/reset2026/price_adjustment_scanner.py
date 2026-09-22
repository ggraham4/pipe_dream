"""
General-purpose safeguard, not tied to any one ticker: scans every ticker in
this pipeline's universe (`td_data_sharadar/*.csv`, the ~4,011-name set
composite_panel.parquet is built from) for `close` (split/dividend-adjusted)
vs. `closeunadj` (raw traded price) ratio jumps that do NOT match the
signature of a genuine stock split.

Two earlier discriminators were tried and both failed (kept in this
docstring, not the code, since the failures are as informative as the fix):

  1. Cross-reference against `sharadar_splits_raw.csv` (the options
     workstream's 660-ticker splits table). Flagged 710 "anomalies" --
     almost all real, ordinary splits (0.25->1.0, 0.3333->1.0, ...) simply
     absent from a table that was never meant to cover this universe.
  2. Cross-reference against `sf1_shares.csv` sharesbas. Flagged AAPL's own
     famous 2014 7-for-1 and 2020 4-for-1 splits as "unexplained" --
     `sharesbas` turns out to already be split-continuity-restated (AAPL's
     filed share count sits ~17.1-17.3B continuously straight through the
     2020 split, not showing the real ~4x jump), so it cannot discriminate
     a real split from a bug either way.

The discriminator that actually works, found and VALIDATED against a real
case while investigating LCID (2026-09-22): a genuine split is a real
event in the RAW, unadjusted trading price -- `closeunadj` must show a
same-day jump of the same magnitude as the ratio change, while `close`
(continuity-adjusted) stays smooth, because that continuity is the entire
purpose of adjusting. A bug shows the opposite shape, or no matching jump
in either series at all.

Checked against two known cases before trusting it:
  - AAPL, 2020-08-31 (real 4-for-1 split): closeunadj 499.23 -> 129.04
    (a real ~3.9x jump); close 124.808 -> 129.04 (ordinary). MATCHES the
    real-split signature.
  - LCID, 2025-08-29 -> 2025-09-02: closeunadj 1.98 -> 17.66 (~8.9x jump);
    close 19.80 -> 17.66 (ordinary). Initially treated as a bug (this
    project's own corrections doc, section 6c, since retracted) -- turned
    out to ALSO match the real-split signature, and a web search confirmed
    Lucid Group's real, SEC-filed 1-for-10 reverse split effective
    2025-09-02 (shares outstanding 3,072.6M -> 307.3M). The retraction is
    recorded in `models/2026-09-22-composite-model-corrections.md` section
    6d and `AGENTS.md`'s Known Gaps -- this scanner exists so the NEXT
    suspicious ratio gets checked systematically instead of by hand.

A jump is flagged only when close (the adjusted series) shows the large,
unexplained move and closeunadj does not -- the shape a bug actually has,
validated to not fire on either known-real case above.

Usage: python3 price_adjustment_scanner.py
Output: out/reset2026/price_adjustment_scan_report.json
"""
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

MAIN_ROOT = Path("/Users/ggraham/pipe_dream/final")
STOCKS_DIR = MAIN_ROOT / "data" / "sharadar" / "panel" / "stocks"
OHLC_DIR = MAIN_ROOT / "scripts" / "td_data_sharadar"
OUT_JSON = MAIN_ROOT / "out" / "reset2026" / "price_adjustment_scan_report.json"

RATIO_ROUND = 4
FLAG_MIN_ABS_LOG_RATIO = np.log(1.5)     # ignore sub-1.5x ratio wobbles (rounding noise)
ORDINARY_DAY_MOVE = 0.20                  # a "smooth" day is within +/-20%
RAW_JUMP_MATCH_TOLERANCE = 0.30           # closeunadj's jump should match the
                                          # ratio change within this relative tolerance


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def universe_tickers():
    return sorted(p.stem for p in OHLC_DIR.glob("*.csv"))


def load_close_pairs(tickers):
    tick_set = set(tickers)
    months = sorted(STOCKS_DIR.glob("*.parquet"))
    frames = []
    t0 = time.time()
    for i, f in enumerate(months, 1):
        d = pd.read_parquet(f, columns=["ticker", "date", "close", "closeunadj"])
        d = d[d["ticker"].isin(tick_set)]
        d = d[d["close"].notna() & d["closeunadj"].notna() & (d["closeunadj"] > 0) & (d["close"] > 0)]
        if not d.empty:
            frames.append(d)
        if i % 60 == 0 or i == len(months):
            log(f"  {i}/{len(months)} months loaded, {time.time()-t0:.0f}s")
    return pd.concat(frames, ignore_index=True)


def scan(df):
    df = df.sort_values(["ticker", "date"]).reset_index(drop=True)
    df["ratio"] = df["close"] / df["closeunadj"]

    flagged = []
    n_checked = 0
    for ticker, g in df.groupby("ticker"):
        g = g.reset_index(drop=True)
        r = g["ratio"].to_numpy()
        r_round = np.round(r, RATIO_ROUND)
        close = g["close"].to_numpy()
        closeunadj = g["closeunadj"].to_numpy()
        dates = g["date"].to_numpy()

        change_idx = np.flatnonzero(np.diff(r_round) != 0) + 1
        for ci in change_idx:
            before, after = r_round[ci - 1], r_round[ci]
            if before == 0 or after == 0:
                continue
            ratio_step = after / before
            if abs(np.log(ratio_step)) <= FLAG_MIN_ABS_LOG_RATIO:
                continue
            n_checked += 1

            close_step = close[ci] / close[ci - 1]
            raw_step = closeunadj[ci] / closeunadj[ci - 1]

            close_is_smooth = abs(np.log(close_step)) <= np.log(1.0 + ORDINARY_DAY_MOVE)
            # raw_step should be ~1/ratio_step (a forward split's ratio moves
            # TOWARD 1 while the raw price drops by the same factor, and vice
            # versa for a reverse split) -- i.e. raw_step * ratio_step ~= 1.
            raw_matches_ratio = abs(np.log(raw_step * ratio_step)) <= np.log(1.0 + RAW_JUMP_MATCH_TOLERANCE)

            if close_is_smooth and raw_matches_ratio:
                continue  # textbook real split: raw jumps to match the ratio, adjusted stays smooth

            flagged.append({
                "ticker": ticker,
                "date": str(pd.Timestamp(dates[ci]).date()),
                "ratio_before": float(before), "ratio_after": float(after),
                "ratio_step": float(ratio_step),
                "close_day_over_day_step": float(close_step),
                "closeunadj_day_over_day_step": float(raw_step),
                "close_is_smooth": bool(close_is_smooth),
                "raw_matches_ratio_change": bool(raw_matches_ratio),
            })
    log(f"checked {n_checked} ratio jumps >=1.5x across {df['ticker'].nunique()} tickers")
    return flagged


def main():
    t0 = time.time()
    tickers = universe_tickers()
    log(f"universe: {len(tickers):,} tickers")
    df = load_close_pairs(tickers)
    log(f"loaded {len(df):,} (ticker,date) close/closeunadj rows ({time.time()-t0:.0f}s)")

    flagged = scan(df)
    log(f"\n{len(flagged)} flagged jumps across {len(set(f['ticker'] for f in flagged))} tickers "
        f"that do NOT match the validated real-split signature")
    for it in flagged[:60]:
        print(" ", it)

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_JSON, "w") as f:
        json.dump({"n_tickers_scanned": len(tickers), "n_flagged": len(flagged),
                   "flagged": flagged}, f, indent=2, default=str)
    log(f"\nwrote {OUT_JSON} ({time.time()-t0:.0f}s total)")


if __name__ == "__main__":
    main()
