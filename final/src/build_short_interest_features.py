"""
Build the short-interest feature panel.

Round 20 (2026-09-18). Adds SHORT_INTEREST_ALL (sweep/short_interest.py) to
the augmented PIT panel, writes a new panel.

    python3 build_short_interest_features.py

Output: out/features_with_short_interest_sharadar_pit.parquet

ACCEPTANCE CHECKS
  1. COVERAGE floor at 2020-04-15 (+8 business days lag) -- nothing before
     ~2020-04-27 should be populated; anything earlier means the lag or the
     raw pull's date floor broke.
  2. DAYS-TO-COVER PLAUSIBILITY -- FINRA caps effective values; the column
     should be non-negative with a sane median (single-digit days).
  3. NO INFINITIES.
"""
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from features import OUT_DIR                                       # noqa: E402
from sweep.short_interest import (                                  # noqa: E402
    build_short_interest_features, SHORT_INTEREST_ALL)

SRC_PANEL = OUT_DIR / "features_with_fundamentals_sharadar_pit.parquet"
DST_PANEL = OUT_DIR / "features_with_short_interest_sharadar_pit.parquet"


def main():
    t0 = time.time()
    print(f"Reading {SRC_PANEL.name} ...")
    panel = pd.read_parquet(SRC_PANEL)
    print(f"  {len(panel):,} rows, {panel['ticker'].nunique():,} tickers")

    print("computing short-interest columns (FINRA, +8 business day publish lag) ...")
    panel = build_short_interest_features(panel)

    print("\n--- acceptance checks ---")
    ok = True
    pre = panel[panel["date"] < "2020-04-27"]
    leak = pre[SHORT_INTEREST_ALL].notna().any(axis=1).sum()
    print(f"  rows before 2020-04-27 with any value populated: {leak}")
    if leak:
        ok = False
        print("    FAIL -- data appearing before the confirmed availability floor")

    dtc = panel["short_interest_days_to_cover"].dropna()
    print(f"  days_to_cover: {100*panel['short_interest_days_to_cover'].notna().mean():.1f}% "
          f"populated, median {dtc.median():.2f}, "
          f"{100*(dtc < 0).mean():.2f}% negative")
    if dtc.median() > 30 or (dtc < 0).mean() > 0.01:
        ok = False
        print("    FAIL -- implausible days-to-cover distribution")

    n_inf = 0
    for c in SHORT_INTEREST_ALL:
        v = panel[c].to_numpy(np.float64)
        n_inf += int((~np.isfinite(v) & ~np.isnan(v)).sum())
    print(f"  finiteness: {n_inf} infinite values")
    if n_inf:
        ok = False
        print("    FAIL")

    print(f"\n{'ALL CHECKS PASSED' if ok else 'CHECKS FAILED -- do not use this panel'}")
    if not ok:
        sys.exit(1)

    panel.to_parquet(DST_PANEL, index=False)
    print(f"\nwritten {DST_PANEL}  ({DST_PANEL.stat().st_size/1e6:.0f}MB, "
          f"{time.time()-t0:.0f}s)")


if __name__ == "__main__":
    main()
