"""
Build the sector-neutralized feature panel.

Round 20 (2026-09-17). Reads the augmented PIT panel, adds the 9 columns
from sweep/sector_neutral.py, writes a new panel.

    python3 build_sector_neutral_features.py

Output: out/features_with_sector_neutral_sharadar_pit.parquet

Does NOT overwrite the existing panel -- additive, so the deployed model and
every prior result stay reproducible from the panel they were built on.

ACCEPTANCE CHECKS
  1. DISPERSION -- each new column must vary within a date, or it carries no
     ranking information.
  2. COVERAGE -- new-column population should roughly match its source
     column's, modulo genuine sector-join misses. A material drop means the
     join broke, not that the feature is naturally sparse.
  3. DEMEANING WORKED -- each column's overall mean should sit near zero,
     since it is (by construction) a value minus its own group's median.
  4. NO INFINITIES -- XGBoost accepts NaN, rejects inf.

See sweep/sector_neutral.py's docstring for the point-in-time caveat this
family carries (current, not historically-tracked, sector classification).
"""
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from features import OUT_DIR                                    # noqa: E402
from sweep.sector_neutral import (                               # noqa: E402
    add_sector_neutral_columns, NEUTRALIZE_COLS, SECTOR_NEUTRAL_ALL)

SRC_PANEL = OUT_DIR / "features_with_fundamentals_sharadar_pit.parquet"
DST_PANEL = OUT_DIR / "features_with_sector_neutral_sharadar_pit.parquet"


def main():
    t0 = time.time()
    print(f"Reading {SRC_PANEL.name} ...")
    panel = pd.read_parquet(SRC_PANEL)
    print(f"  {len(panel):,} rows, {panel['ticker'].nunique():,} tickers, "
          f"{panel['date'].min().date()} .. {panel['date'].max().date()}")

    print("computing sector-neutralized columns (sicsector, filing-time-assigned) ...")
    panel = add_sector_neutral_columns(panel, scheme="sicsector")

    print("\n--- acceptance checks ---")
    ok = True

    print("  dispersion + coverage:")
    for base, c in zip(NEUTRALIZE_COLS, SECTOR_NEUTRAL_ALL):
        v = panel[c]
        cov_base = panel[base].notna().mean()
        cov_new = v.notna().mean()
        std = float(v.std())
        mean = float(v.mean())
        flag = ""
        if std <= 0 or not np.isfinite(std):
            ok, flag = False, "  FAIL -- zero/undefined variance"
        if cov_new < cov_base - 0.02:
            ok, flag = False, flag + "  FAIL -- coverage dropped vs source column"
        if abs(mean) > 0.5:
            ok, flag = False, flag + "  FAIL -- mean far from zero, demeaning broken"
        print(f"    {c:<28} {100*cov_new:>5.1f}% populated (source {100*cov_base:.1f}%)"
              f"  mean {mean:+.5f}  std {std:.5f}{flag}")

    n_inf = 0
    for c in SECTOR_NEUTRAL_ALL:
        v = panel[c].to_numpy(np.float64)
        n_inf += int((~np.isfinite(v) & ~np.isnan(v)).sum())
    print(f"\n  finiteness: {n_inf} infinite values across {len(SECTOR_NEUTRAL_ALL)} columns")
    if n_inf:
        ok = False
        print("    FAIL -- a ratio/diff with a degenerate group must be NaN, not inf.")

    print(f"\n{'ALL CHECKS PASSED' if ok else 'CHECKS FAILED -- do not use this panel'}")
    if not ok:
        sys.exit(1)

    panel.to_parquet(DST_PANEL, index=False)
    print(f"\nwritten {DST_PANEL}  ({DST_PANEL.stat().st_size/1e6:.0f}MB, "
          f"{time.time()-t0:.0f}s)")
    print(f"new columns: {SECTOR_NEUTRAL_ALL}")


if __name__ == "__main__":
    main()
