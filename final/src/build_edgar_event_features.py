"""
Build the SEC EDGAR 8-K event-flag panel.

Round 20 (2026-09-18). Adds EDGAR_EVENTS_ALL (sweep/edgar_events.py) to the
augmented PIT panel, writes a new panel.

    python3 build_edgar_event_features.py

Output: out/features_with_edgar_events_sharadar_pit.parquet

ACCEPTANCE CHECKS
  1. CIK COVERAGE -- report what fraction of tickers/rows got a CIK match at
     all (expected ~half the universe, see sweep/edgar_events.py's honest
     coverage caveat). Zero coverage would mean the CIK maps didn't load.
  2. FIRE RATE PLAUSIBILITY -- named expected values, not just "some rows
     are 1": Item 5.02 (exec departures) fires far more often than Item 4.02
     (restatements) in any real filing population; going concern should sit
     between them. A screen that shows item_502 rarer than item_402 means
     something is misaligned.
  3. NO INFINITIES.
"""
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from features import OUT_DIR                                       # noqa: E402
from sweep.edgar_events import build_edgar_event_features, EDGAR_EVENTS_ALL  # noqa: E402

SRC_PANEL = OUT_DIR / "features_with_fundamentals_sharadar_pit.parquet"
DST_PANEL = OUT_DIR / "features_with_edgar_events_sharadar_pit.parquet"


def main():
    t0 = time.time()
    print(f"Reading {SRC_PANEL.name} ...")
    panel = pd.read_parquet(SRC_PANEL)
    print(f"  {len(panel):,} rows, {panel['ticker'].nunique():,} tickers")

    print("computing EDGAR 8-K event columns ...")
    panel = build_edgar_event_features(panel)
    print(f"  done ({time.time()-t0:.0f}s)")

    print("\n--- acceptance checks ---")
    ok = True
    cik_cov = panel[EDGAR_EVENTS_ALL[0]].notna().mean()
    n_tickers_cov = panel.loc[panel[EDGAR_EVENTS_ALL[0]].notna(), "ticker"].nunique()
    print(f"  CIK coverage: {100*cik_cov:.1f}% of rows, "
          f"{n_tickers_cov:,}/{panel['ticker'].nunique():,} tickers")
    if cik_cov < 0.20:
        ok = False
        print("    FAIL -- coverage far below the expected ~half of the universe; "
              "the CIK maps likely didn't load")

    rates = {c: float(panel[c].mean()) for c in EDGAR_EVENTS_ALL}
    for c, r in rates.items():
        print(f"  {c:<28} fires on {100*r:.2f}% of covered rows")
    if not (rates["filed_item502_60d"] > rates["filed_going_concern_120d"]
            > rates["filed_item402_240d"]):
        ok = False
        print("    FAIL -- expected ordering item_502 > going_concern > item_402 "
              "(departures commonest, restatements rarest) did not hold")

    n_inf = 0
    for c in EDGAR_EVENTS_ALL:
        v = panel[c].to_numpy(np.float64)
        n_inf += int((~np.isfinite(v) & ~np.isnan(v)).sum())
    print(f"  finiteness: {n_inf} infinite values")
    if n_inf:
        ok = False

    print(f"\n{'ALL CHECKS PASSED' if ok else 'CHECKS FAILED -- inspect before using'}")
    if not ok:
        sys.exit(1)

    panel.to_parquet(DST_PANEL, index=False)
    print(f"\nwritten {DST_PANEL}  ({DST_PANEL.stat().st_size/1e6:.0f}MB, "
          f"{time.time()-t0:.0f}s)")


if __name__ == "__main__":
    main()
