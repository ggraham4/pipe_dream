"""
Build the rate-sensitivity feature panel.

Round 14 (2026-09-11). Reads the augmented PIT panel, adds the four
rate-sensitivity columns from sweep/rates.py, writes a new panel.

    python3 build_rate_features.py

Output: out/features_with_rates_sharadar_pit.parquet

This does NOT overwrite the existing panel. The rates features are additive
and unproven; keeping them in a separate file means the deployed model and
every prior result stay reproducible from the panel they were built on.

Acceptance checks run automatically at the end. They are the ones that matter
for this specific feature family:

  1. NO LOOK-AHEAD. Each beta at date t must be computable from data strictly
     before t. Verified by recomputing a sample of betas from the raw inputs
     with an explicit backward-only window and comparing.
  2. COVERAGE. A beta needs a full trailing window, so early rows are NaN by
     construction. The check confirms the missing rows are the EARLY ones per
     ticker rather than a random subset -- a random pattern would mean the
     alignment is wrong.
  3. DISPERSION. The betas must actually vary cross-sectionally on a given
     date, or they carry no ranking information regardless of their values.
"""

import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from features import OUT_DIR, FEATURE_COLS            # noqa: E402
from sweep import rates as R                          # noqa: E402

SRC_PANEL = OUT_DIR / "features_with_fundamentals_sharadar_pit.parquet"
DST_PANEL = OUT_DIR / "features_with_rates_sharadar_pit.parquet"


def main():
    t0 = time.time()
    print(f"Reading {SRC_PANEL.name} ...")
    panel = pd.read_parquet(SRC_PANEL)
    print(f"  {len(panel):,} rows, {panel['ticker'].nunique():,} tickers, "
          f"{panel['date'].min().date()} .. {panel['date'].max().date()}")

    y = R.load_yields()
    panel = R.build_rate_features(panel, y)

    # ---------------- acceptance checks ----------------
    print("\n--- acceptance checks ---")
    ok = True

    # 2. coverage pattern: missing betas must be the EARLY rows per ticker
    g = panel[["ticker", "date", "rate_beta_120"]].copy()
    g["miss"] = ~np.isfinite(g["rate_beta_120"])
    per = g.groupby("ticker", observed=True).agg(
        n=("miss", "size"), n_miss=("miss", "sum"),
        first_ok=("miss", lambda s: int(np.argmin(s.to_numpy())) if (~s).any() else -1))
    # for a correctly-aligned rolling window, every missing row sits BEFORE
    # the first valid one, so n_miss == index of first valid
    clean = per[per.first_ok >= 0]
    leading_only = (clean.n_miss == clean.first_ok).mean()
    print(f"  coverage: {(~g['miss']).mean()*100:5.1f}% of rows have a beta; "
          f"{leading_only*100:.1f}% of tickers have ONLY leading NaNs")
    if leading_only < 0.98:
        ok = False
        print("    FAIL -- missing betas are not confined to the start of each "
              "series, which means the per-ticker alignment is wrong")

    # 3. cross-sectional dispersion on a sample of dates
    d = panel[np.isfinite(panel["rate_beta_120"])]
    samp = d.groupby("date")["rate_beta_120"].agg(["count", "std"])
    samp = samp[samp["count"] >= 100]
    print(f"  dispersion: median cross-sectional sd of rate_beta_120 = "
          f"{samp['std'].median():.4f} over {len(samp):,} dates")
    if not (samp["std"].median() > 1e-6):
        ok = False
        print("    FAIL -- betas are constant within a date, so they carry no "
              "ranking information")

    # 1. no look-ahead: recompute a few betas the slow, explicitly causal way
    rng = np.random.default_rng(0)
    pick = d.sample(min(200, len(d)), random_state=1)
    yv = y.reindex(pd.DatetimeIndex(panel["date"]))
    dy = yv["d_y10"].to_numpy()
    bad = 0
    checked = 0
    by_t = {k: v for k, v in panel.groupby("ticker", observed=True).indices.items()}
    for _, row in pick.iterrows():
        idx = by_t.get(row["ticker"])
        if idx is None or len(idx) < 130:
            continue
        pos = np.searchsorted(panel["date"].to_numpy()[idx], np.datetime64(row["date"]))
        if pos < 121 or pos >= len(idx):
            continue
        # window is the 120 observations ENDING AT pos-1 -- strictly before t
        w = idx[pos - 120:pos]
        r_, x_ = panel["daily_return"].to_numpy()[w], dy[w]
        m = np.isfinite(r_) & np.isfinite(x_)
        if m.sum() < 60:
            continue
        var = np.var(x_[m])
        if var <= 1e-12:
            continue
        ref = np.cov(r_[m], x_[m], bias=True)[0, 1] / var
        checked += 1
        if abs(ref - row["rate_beta_120"]) > 5e-3:
            bad += 1
    print(f"  causality: {checked} sampled betas recomputed with an explicitly "
          f"backward-only window, {bad} disagreed")
    if checked and bad > max(2, 0.05 * checked):
        ok = False
        print("    FAIL -- recomputed betas differ from the stored ones, so the "
              "rolling window is not the one documented")

    print(f"\n{'ALL CHECKS PASSED' if ok else 'CHECKS FAILED -- do not use this panel'}")
    if not ok:
        sys.exit(1)

    keep = (["ticker", "date", "close", "open", "market_cap"]
            + [c for c in panel.columns if c not in
               ("ticker", "date", "close", "open", "market_cap")])
    panel = panel[[c for c in keep if c in panel.columns]]
    panel.to_parquet(DST_PANEL, index=False)
    print(f"\nwritten {DST_PANEL}  ({DST_PANEL.stat().st_size/1e6:.0f}MB, "
          f"{time.time()-t0:.0f}s)")
    print(f"new columns: {R.RATE_FEATURE_COLS + ['d_y10_20']}")


if __name__ == "__main__":
    main()
