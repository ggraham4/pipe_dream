"""
Build the event / tail-shape feature panel.

Round 16 (2026-09-12). Reads the augmented PIT panel, adds the eight columns
from sweep/events.py, writes a new panel.

    python3 build_event_features.py

Output: out/features_with_events_sharadar_pit.parquet

Does NOT overwrite the existing panel. These features are additive and
unproven; keeping them separate means the deployed model and every prior result
stay reproducible from the panel they were built on.

ACCEPTANCE CHECKS -- the ones that matter for THIS feature family:

  1. NO LOOK-AHEAD, and it is the whole risk here. "Is there an earnings event
     in my holding window" is look-ahead as normally stated: the next filing
     date is in the future. The causal estimate uses each ticker's own past
     cadence. The check verifies the estimate is NOT the actual next filing
     date: an exact-hit rate near 100% would mean the future leaked in. Cadence
     alone gives ~14%.
  2. COVERAGE. Rolling features need a full trailing window, so early rows are
     NaN by construction. The check confirms the missing rows are the EARLY ones
     per ticker rather than a random subset -- a random pattern means the
     per-ticker alignment is wrong.
  3. DISPERSION. The columns must vary cross-sectionally on a given date, or
     they carry no ranking information whatever their values.
  4. NO CONSTANT-BY-DATE COLUMN. Round 14 shipped `d_y10_20`, a date constant
     with structurally zero cross-sectional IC, into a screen. Catch that here
     instead of in the results table.
"""

import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from features import OUT_DIR                            # noqa: E402
from sweep import events as E                           # noqa: E402

SRC_PANEL = OUT_DIR / "features_with_fundamentals_sharadar_pit.parquet"
DST_PANEL = OUT_DIR / "features_with_events_sharadar_pit.parquet"


def main():
    t0 = time.time()
    print(f"Reading {SRC_PANEL.name} ...")
    panel = pd.read_parquet(SRC_PANEL)
    print(f"  {len(panel):,} rows, {panel['ticker'].nunique():,} tickers, "
          f"{panel['date'].min().date()} .. {panel['date'].max().date()}")

    panel = E.build_event_features(panel, horizon=40)

    print("\n--- acceptance checks ---")
    ok = True

    # 1. LOOK-AHEAD -- the one that matters
    f = E.load_filings()
    f = f.sort_values(["ticker", "date"]).copy()
    f["actual_next"] = f.groupby("ticker", sort=False)["date"].shift(-1)
    v = f.dropna(subset=["actual_next"])
    err = (v["next_filing_est"] - v["actual_next"]).dt.days
    hit = float((err == 0).mean())
    print(f"  look-ahead: next-filing estimate matches the ACTUAL next filing "
          f"exactly {hit*100:.1f}% of the time (MAE {err.abs().median():.0f}d, "
          f"median bias {err.median():+.0f}d)")
    if hit > 0.50:
        ok = False
        print("    FAIL -- an exact-hit rate this high means the future filing "
              "date is leaking into the ESTIMATE rather than being predicted")
    # 1a. PLAUSIBILITY OF THE FIRE RATE -- the check that would have caught the
    # merge_asof misalignment bug. A 58-calendar-day window against a ~91-day
    # filing cadence must contain a filing roughly 58/91 = 64% of the time.
    # Coverage and dispersion checks BOTH passed while every merged column was
    # on the wrong row; only a check with an externally-known expected value
    # catches that. (Same lesson as Gate A7c: verify by naming what should be
    # there, not by counting.)
    span = 40 * 1.4523
    gaps = f.dropna(subset=["actual_next"])
    med_gap = float((gaps["actual_next"] - gaps["date"]).dt.days.median())
    expect = min(span / med_gap, 1.0)
    got = float(panel["earnings_in_window_actual"].mean())
    print(f"  fire rate: `earnings_in_window_actual` = {got*100:.1f}% of rows; "
          f"expected ~{expect*100:.0f}% ({span:.0f}d window / {med_gap:.0f}d cadence)")
    if not (0.5 * expect <= got <= 1.15 * expect):
        ok = False
        print("    FAIL -- the fire rate is not consistent with the filing "
              "cadence, which means rows are misaligned rather than the feature "
              "being rare")

    # 1b. the announcement-lead variant must be STRICTLY more conservative
    ka = panel["earnings_in_window_known"].mean()
    aa = panel["earnings_in_window_actual"].mean()
    print(f"  announcement lead ({E.ANNOUNCE_LEAD_DAYS}d): `_known` fires on "
          f"{ka*100:.1f}% of rows vs `_actual` {aa*100:.1f}%")
    leak = int(((panel["earnings_in_window_known"] > 0)
                & (panel["earnings_in_window_actual"] == 0)).sum())
    if leak:
        ok = False
        print(f"    FAIL -- {leak:,} rows where `_known` fires but `_actual` does "
              f"not. `_known` must be a strict subset; it is the SAME dates seen "
              f"through a {E.ANNOUNCE_LEAD_DAYS}d announcement window.")
    elif ka >= aa:
        ok = False
        print("    FAIL -- `_known` should fire strictly less often than `_actual`; "
              "if it does not, the lead is not being applied")
    print("  note: `days_to_next_filing_actual` / `earnings_in_window_actual` "
          "are the true next-filing date, carried DELIBERATELY.")
    print("        Earnings dates are scheduled and announced weeks ahead, so a "
          "real trader knows them; this dataset just cannot prove which ones "
          "were announced yet. The pair is screened side by side and the gap "
          "between them bounds what a real earnings calendar is worth.")

    # 2. coverage pattern on a rolling column
    g = panel[["ticker", "date", "realized_skew_120"]].copy()
    g["miss"] = ~np.isfinite(g["realized_skew_120"])
    per = g.groupby("ticker", observed=True).agg(
        n_miss=("miss", "sum"),
        first_ok=("miss", lambda s: int(np.argmin(s.to_numpy())) if (~s).any() else -1))
    clean = per[per.first_ok >= 0]
    leading = float((clean.n_miss == clean.first_ok).mean())
    print(f"  coverage: {(~g['miss']).mean()*100:5.1f}% of rows have skew; "
          f"{leading*100:.1f}% of tickers have ONLY leading NaNs")
    if leading < 0.95:
        ok = False
        print("    FAIL -- missing values are not confined to the start of each "
              "series, so the per-ticker alignment is wrong")

    # 3 & 4. dispersion, and no date-constant columns
    print(f"  {'column':<26} {'populated':>9} {'median x-sec sd':>16}")
    for c in E.EVENT_FEATURE_COLS:
        d = panel[np.isfinite(panel[c])]
        if not len(d):
            ok = False
            print(f"  {c:<26} {'0.0%':>9}   FAIL -- entirely empty")
            continue
        s = d.groupby("date")[c].agg(["count", "std"])
        s = s[s["count"] >= 100]
        med = float(s["std"].median()) if len(s) else np.nan
        flag = ""
        if not (med > 1e-9):
            ok = False
            flag = "   FAIL -- constant within a date: zero ranking information"
        print(f"  {c:<26} {np.isfinite(panel[c]).mean()*100:8.1f}% {med:>16.5f}{flag}")

    # 5. NO INFINITIES. Caught at TRAINING time in Round 17, three cells deep
    # into a sweep, instead of here. XGBoost accepts NaN and rejects inf.
    n_inf = 0
    for c in E.EVENT_FEATURE_COLS:
        v = panel[c].to_numpy(np.float64)
        n_inf += int((~np.isfinite(v) & ~np.isnan(v)).sum())
    print(f"  finiteness: {n_inf} infinite values across {len(E.EVENT_FEATURE_COLS)} columns")
    if n_inf:
        ok = False
        print("    FAIL -- XGBoost accepts NaN but rejects inf. A ratio with a "
              "zero denominator must be NaN, not inf.")

    print(f"\n{'ALL CHECKS PASSED' if ok else 'CHECKS FAILED -- do not use this panel'}")
    if not ok:
        sys.exit(1)

    panel.to_parquet(DST_PANEL, index=False)
    print(f"\nwritten {DST_PANEL}  ({DST_PANEL.stat().st_size/1e6:.0f}MB, "
          f"{time.time()-t0:.0f}s)")
    print(f"new columns: {E.EVENT_FEATURE_COLS}")


if __name__ == "__main__":
    main()
