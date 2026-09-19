"""
Does implied volatility forecast realised volatility better than trailing
realised volatility does?

    python3 screen_iv_vol_forecast.py

--------------------------------------------------------------------------
WHY THIS IS THE RIGHT QUESTION TO ASK OF OPTION DATA
--------------------------------------------------------------------------
The 2026-09-16 screen asked nine option-implied features to predict the MEAN of
the forward return distribution and found nothing at proper power. That screen
was sound but it asked the wrong thing. Options price the SHAPE of a
distribution -- its width, its skew, its tails. Testing the width against the
mean is a category error, and the neutralisation made it worse by residualising
the target on volatility_60, which is the very channel an IV feature acts
through.

This asks what options are actually built to answer: how much will this name
move? And it matters here for a specific, non-speculative reason. Rounds 15/15b
found the largest single effect in the whole 1,152-cell sweep was not a model
change at all -- it was VOLATILITY-QUINTILE BUCKETING plus INVERSE-VOLATILITY
WEIGHTING, which lifted the grid mean from 0.606 to 0.905. That construction
runs on TRAILING REALISED vol. If implied vol ranks future volatility better,
it belongs in the construction, and no return-predictive power is required for
that to pay.

--------------------------------------------------------------------------
WHAT IS MEASURED
--------------------------------------------------------------------------
Target: realised volatility over the NEXT 40 trading days, annualised --
computed forward from daily returns, which is the quantity the construction
actually wants and cannot observe.

Predictors, all known at time t:
    opt_atm_iv       implied, ~56-day expiry, matched to the holding period
    volatility_20    trailing realised, 20d   (in the deployed feature set)
    volatility_60    trailing realised, 60d   (in the deployed feature set)

Two statistics:

 1. CROSS-SECTIONAL IC per day, Newey-West(40) corrected. Consecutive days
    share 39/40 of their forward window; the naive t is inflated ~sqrt(40).
    This is the ranking question, which is what bucketing and weighting need.

 2. INCREMENTAL REGRESSION. log(RV_fwd) on log(trailing) alone, then with
    log(IV) added. The question is not whether IV predicts -- of course it does
    -- but whether it predicts anything the model does not ALREADY have from
    volatility_60. A feature that merely restates an existing column is worth
    nothing however high its own t.

A POSITIVE CONTROL IS BUILT IN: trailing realised vol must itself forecast
forward realised vol strongly (volatility is the most persistent quantity in
finance). If it does not, the target is wrong and nothing else in the output
means anything.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parent))
from features import OUT_DIR                                   # noqa: E402
from sweep import _num                                         # noqa: E402

PANEL = OUT_DIR / "features_with_options_sharadar_pit.parquet"
ERA = ("2019-02-09", "2024-01-01")
H = 40
MIN_NAMES = 80
PREDICTORS = ["opt_atm_iv", "volatility_20", "volatility_60"]


def newey_west_t(x, lag):
    x = np.asarray(x, np.float64); x = x[np.isfinite(x)]
    n = len(x)
    if n < lag + 5:
        return np.nan, np.nan, n
    d = x - x.mean()
    var = float(d @ d) / n
    for k in range(1, lag + 1):
        var += 2.0 * (1.0 - k / (lag + 1.0)) * float(d[k:] @ d[:-k]) / n
    if var <= 0:
        return float(x.mean()), np.nan, n
    return float(x.mean()), float(x.mean() / np.sqrt(var / n)), n


def main():
    cols = ["ticker", "date", "daily_return"] + PREDICTORS
    present = set(pq.ParquetFile(PANEL).schema_arrow.names)
    print(f"loading {PANEL.name} ...", flush=True)
    p = pd.read_parquet(PANEL, columns=[c for c in cols if c in present])
    p = p.sort_values(["ticker", "date"]).reset_index(drop=True)

    # FORWARD realised vol: std of the NEXT H daily returns, annualised.
    # shift(-1) first so day t is excluded -- the position is entered at the
    # next open, so t's own return is already spent.
    g = p.groupby("ticker", observed=True)["daily_return"]
    fwd = (g.shift(-1).groupby(p["ticker"], observed=True)
           .rolling(H, min_periods=H).std().reset_index(level=0, drop=True))
    p["rv_fwd"] = fwd.to_numpy() * np.sqrt(252.0)

    p = p[(p["date"] >= ERA[0]) & (p["date"] < ERA[1])]
    p = p[p["opt_atm_iv"].notna() & np.isfinite(p["rv_fwd"])]
    print(f"  {len(p):,} name-dates with option data and a resolved forward RV")
    print(f"  forward RV: median {p['rv_fwd'].median():.3f}, "
          f"IV median {p['opt_atm_iv'].median():.3f}, "
          f"IV/RV ratio {p['opt_atm_iv'].median()/p['rv_fwd'].median():.3f}")
    print("  ^ ratio > 1 is the variance risk premium: options are priced above")
    print("    what subsequently happens. Expected, and a check on the target.\n")

    # ---- 1. cross-sectional ranking ------------------------------------
    daily = {c: [] for c in PREDICTORS}
    for d_, gg in p.groupby("date", observed=True, sort=True):
        y = gg["rv_fwd"].to_numpy(np.float64)
        if np.isfinite(y).sum() < MIN_NAMES:
            continue
        for c in PREDICTORS:
            x = gg[c].to_numpy(np.float64)
            m = np.isfinite(x) & np.isfinite(y)
            daily[c].append(_num.spearman(x[m], y[m])
                            if m.sum() >= MIN_NAMES else np.nan)
    print("=" * 84)
    print("RANKING FUTURE VOLATILITY -- cross-sectional IC vs realised vol over the")
    print("next 40 trading days, Newey-West(40)")
    print("=" * 84)
    print(f"{'predictor':<20}{'IC':>10}{'naive t':>11}{'NW t':>9}{'n days':>9}")
    ics = {}
    for c in PREDICTORS:
        v = np.asarray(daily[c], np.float64)
        m, tnw, n = newey_west_t(v, H)
        ok = np.isfinite(v)
        tn = float(v[ok].mean() / (v[ok].std(ddof=1) / np.sqrt(ok.sum())))
        ics[c] = m
        print(f"{c:<20}{m:>10.4f}{tn:>11.1f}{tnw:>9.1f}{n:>9}")
    if ics.get("volatility_60", 0) < 0.4:
        print("\n  WARNING: trailing realised vol should rank future realised vol")
        print("  very strongly (volatility is highly persistent). A weak number")
        print("  here means the target is wrong -- stop and fix it before reading")
        print("  anything else.")

    # ---- 2. does IV add anything to what the model already has? ---------
    print("\n" + "=" * 84)
    print("INCREMENTAL VALUE -- does IV tell us anything volatility_60 does not?")
    print("=" * 84)
    d = p[np.isfinite(p["volatility_60"]) & (p["volatility_60"] > 1e-6)
          & (p["opt_atm_iv"] > 1e-6) & (p["rv_fwd"] > 1e-6)]
    y = np.log(d["rv_fwd"].to_numpy(np.float64))
    x1 = np.log(d["volatility_60"].to_numpy(np.float64) * np.sqrt(252.0))
    x2 = np.log(d["opt_atm_iv"].to_numpy(np.float64))

    def r2(X, y):
        X = np.column_stack([np.ones(len(y))] + X)
        b, *_ = np.linalg.lstsq(X, y, rcond=None)
        e = y - X @ b
        return 1.0 - float(e @ e) / float(((y - y.mean()) ** 2).sum()), b

    r_hv, _ = r2([x1], y)
    r_iv, _ = r2([x2], y)
    r_both, b = r2([x1, x2], y)
    print(f"  log RV_fwd ~ log(trailing vol_60)      R2 = {r_hv:.4f}")
    print(f"  log RV_fwd ~ log(implied ATM vol)      R2 = {r_iv:.4f}")
    print(f"  log RV_fwd ~ both                      R2 = {r_both:.4f}")
    print(f"     coefficients: trailing {b[1]:+.3f}, implied {b[2]:+.3f}")
    print(f"  incremental R2 from adding IV to trailing: {r_both - r_hv:+.4f}")
    print(f"  incremental R2 from adding trailing to IV: {r_both - r_iv:+.4f}")
    print("\n  Whichever predictor the other cannot subsume is the one that belongs")
    print("  in the construction. Note these R2 are pooled across names and dates,")
    print("  so they are inflated by the cross-sectional spread in vol levels --")
    print("  read them against each other, never as absolute skill.")
    print("\n  IF IV RANKS BETTER: swap it into the volq bucketing and the invvol")
    print("  weights and re-run the construction. That is a change to the largest")
    print("  measured effect in the sweep, and it needs NO return predictability")
    print("  to pay -- which is exactly why it is worth testing before anything")
    print("  else option-derived.")


if __name__ == "__main__":
    main()
