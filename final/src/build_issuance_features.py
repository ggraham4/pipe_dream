"""
Build the net-issuance feature panel.

Round 20 (2026-09-17). Adds `net_issuance_pct` (sweep/issuance.py) to the
augmented PIT panel, writes a new panel.

    python3 build_issuance_features.py

Output: out/features_with_issuance_sharadar_pit.parquet

ACCEPTANCE CHECKS
  1. SIGN PLAUSIBILITY. Net issuance should be near-zero-median (most
     company-years, no material share-count change) with a right skew
     (large dilutive raises are common; large buybacks are bounded at -100%
     but rarely approach it). A left-skewed or negative-median distribution
     means current/lookback are swapped.
  2. COVERAGE. Should be close to (not exceeding) the fundamentals panel's
     own coverage -- this feature needs a second, ~1-year-earlier filing to
     exist, so a few points below `market_cap` coverage is expected, not a
     bug.
  3. NO INFINITIES.
"""
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from features import OUT_DIR                              # noqa: E402
from sweep.issuance import build_issuance_features, NET_ISSUANCE_COL  # noqa: E402

SRC_PANEL = OUT_DIR / "features_with_fundamentals_sharadar_pit.parquet"
DST_PANEL = OUT_DIR / "features_with_issuance_sharadar_pit.parquet"


def main():
    t0 = time.time()
    print(f"Reading {SRC_PANEL.name} ...")
    panel = pd.read_parquet(SRC_PANEL)
    print(f"  {len(panel):,} rows, {panel['ticker'].nunique():,} tickers")

    print("computing net_issuance_pct (Sharadar SF1 sharesbas, filed-date keyed) ...")
    panel = build_issuance_features(panel)

    print("\n--- acceptance checks ---")
    ok = True
    v = panel[NET_ISSUANCE_COL].dropna()
    cov = panel[NET_ISSUANCE_COL].notna().mean()
    cov_mc = panel["market_cap"].notna().mean()
    med, mean = float(v.median()), float(v.mean())
    print(f"  coverage: {100*cov:.1f}% (market_cap coverage: {100*cov_mc:.1f}%)")
    if cov > cov_mc + 0.01:
        ok = False
        print("    FAIL -- issuance coverage exceeds market_cap's own coverage, "
              "impossible given it needs the same shares data plus a second filing")
    print(f"  median {med:+.4f}, mean {mean:+.4f} (expect median near 0, "
          f"mean pulled positive by dilutive raises)")
    if med < -0.02:
        ok = False
        print("    FAIL -- negative median suggests current/lookback shares are swapped")
    pctiles = v.quantile([0.01, 0.5, 0.99])
    print(f"  1st/50th/99th pctile: {pctiles.iloc[0]:+.3f} / {pctiles.iloc[1]:+.3f} / "
          f"{pctiles.iloc[2]:+.3f}")

    n_inf = int((~np.isfinite(panel[NET_ISSUANCE_COL].to_numpy(np.float64))
                & ~panel[NET_ISSUANCE_COL].isna()).sum())
    print(f"  finiteness: {n_inf} infinite values")
    if n_inf:
        ok = False
        print("    FAIL -- must be NaN, not inf")

    print(f"\n{'ALL CHECKS PASSED' if ok else 'CHECKS FAILED -- do not use this panel'}")
    if not ok:
        sys.exit(1)

    panel.to_parquet(DST_PANEL, index=False)
    print(f"\nwritten {DST_PANEL}  ({DST_PANEL.stat().st_size/1e6:.0f}MB, "
          f"{time.time()-t0:.0f}s)")


if __name__ == "__main__":
    main()
