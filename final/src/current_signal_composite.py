"""
Live picks for the factor-composite reset -- TRACKED CANDIDATE, NOT the
deployed signal. See final/models/2026-09-19-factor-composite-reset.md for
the full write-up and final/src/reset2026/PREREGISTRATION.md for the spec.

WHY THIS IS A CANDIDATE, NOT PRIMARY (same honesty convention as the
existing xrank candidate in current_signal_pit.py):

    Nomination era (2007-2019): +3.75%/yr excess vs SPY, 40/40 grid offsets
    positive, survives sector-neutralization (Round-13-style test), survives
    leave-one-year-out.

    Hold-out (2020-2026), confirmed once: +1.85%/yr excess vs SPY, 39/40
    offsets positive -- BUT FAILS leave-one-year-out. Only 2 of 7 years
    (2020, 2022) are positive; the other 5 are all negative; dropping 2020
    alone flips the 7-year mean to -2.05%/yr. This is the same failure mode
    that already killed a different finding in this project (Round 14's
    rate_beta_x_move). Shown here so its picks can be tracked and compared
    in real time -- not because it is confirmed to work.

CONSTRUCTION (matches PREREGISTRATION.md's named selection exactly):
    Universe: cap150 tier (market cap >= $150M, trailing 20-day median
        dollar volume >= $250k, domestic common stock, point-in-time).
    9 factors, rank-transformed and sign-combined with ZERO fitted
        parameters (see reset2026/composite.py:FACTOR_SIGNS).
    Portfolio: top decile by composite score within each of 5 trailing-
        volatility quintiles, inverse-vol weighted (decile_volq).
    40-trading-day hold, no stop-loss, ~200 positions.

This script does NOT retrain anything (there is nothing to train -- the
composite has no fitted parameters). It scores the MOST RECENT complete
date in reset2026/composite_panel.parquet. Refreshing this signal means
refreshing that panel: re-run, in order,
    downcap_universe.py -> quality_factors.py -> build_panel.py
(final/src/reset2026/), which themselves depend on the base
features_with_fundamentals_sharadar_pit.parquet being current (the app's
existing "Retrain ALL models" pipeline).

OUTPUT
    final/out/current_signal_composite.csv
    final/out/current_signal_composite_meta.json
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

MAIN_ROOT = Path(__file__).resolve().parent.parent
RESET_SRC = MAIN_ROOT / "src" / "reset2026"
sys.path.insert(0, str(RESET_SRC))
import composite as C  # noqa: E402

PANEL = MAIN_ROOT / "out" / "reset2026" / "composite_panel.parquet"
OUT_CSV = MAIN_ROOT / "out" / "current_signal_composite.csv"
OUT_META = MAIN_ROOT / "out" / "current_signal_composite_meta.json"

TIER = "cap150"
NEUTRAL = False

BACKTEST_SUMMARY = {
    "nominate_excess_cagr_pct": 3.75,
    "nominate_offsets_positive": "40/40",
    "holdout_excess_cagr_pct": 1.85,
    "holdout_offsets_positive": "39/40",
    "holdout_loyo_status": "FAILS -- only 2 of 7 hold-out years (2020, 2022) "
                            "are positive; dropping 2020 alone flips the mean "
                            "to -2.05%/yr. See the write-up before trusting "
                            "the headline number above.",
}


def main():
    if not PANEL.exists():
        raise SystemExit(f"{PANEL} not found -- run downcap_universe.py, "
                         f"quality_factors.py, then build_panel.py first "
                         f"(final/src/reset2026/).")

    needed = list(dict.fromkeys(
        ["ticker", "date", "sector", "close", "market_cap", "volatility_60",
         f"eligible_{TIER}"] + C.FACTOR_COLS))
    panel = pd.read_parquet(PANEL, columns=needed)
    panel["date"] = pd.to_datetime(panel["date"])
    panel["ticker"] = panel["ticker"].astype(str)

    as_of = panel["date"].max()
    df_date = panel[panel["date"] == as_of]
    elig = df_date[df_date[f"eligible_{TIER}"]].reset_index(drop=True)
    if len(elig) < 20:
        raise SystemExit(f"only {len(elig)} eligible names on {as_of.date()} -- "
                         f"panel looks stale or broken, refusing to write picks.")

    scored = C.compute_composite(elig, neutral=NEUTRAL)
    picks = C.pick_decile_volq(elig, scored)
    if not picks:
        raise SystemExit(f"pick_decile_volq returned no picks on {as_of.date()}.")

    tickers = [t for t, _ in picks]
    weights = {t: w for t, w in picks}
    out = elig[elig["ticker"].isin(tickers)][
        ["ticker", "sector", "close", "market_cap", "volatility_60"]
    ].copy()
    comp_lookup = dict(zip(scored["ticker"], scored["composite"]))
    out["composite_score"] = out["ticker"].map(comp_lookup)
    out["weight"] = out["ticker"].map(weights)
    out = out.sort_values("weight", ascending=False).reset_index(drop=True)
    out.to_csv(OUT_CSV, index=False)

    meta = {
        "as_of_date": as_of.strftime("%Y-%m-%d"),
        "tier": TIER,
        "neutral": NEUTRAL,
        "n_eligible_universe": int(len(elig)),
        "n_picks": int(len(out)),
        "construction": "decile_volq: top decile by composite score within "
                        "each of 5 trailing-volatility quintiles, inverse-vol "
                        "weighted, 40-trading-day hold, no stop-loss",
        "factors": {k: v for k, v in C.FACTOR_SIGNS.items()},
        "backtest_summary": BACKTEST_SUMMARY,
        "writeup": "final/models/2026-09-19-factor-composite-reset.md",
        "preregistration": "final/src/reset2026/PREREGISTRATION.md",
        "role": "candidate",
        "note": "TRACKED, NOT ACTED ON AS A VALIDATED EDGE. Passes nomination-"
                "era leave-one-year-out; FAILS it on the 2020-2026 hold-out "
                "(2 of 7 years carry the whole result). See the write-up.",
    }
    OUT_META.write_text(json.dumps(meta, indent=2))
    print(f"as of {as_of.date()}: {len(out)} picks from {len(elig)} eligible names")
    print(out.head(10).to_string(index=False))
    print(f"\n-> {OUT_CSV}\n-> {OUT_META}")


if __name__ == "__main__":
    sys.exit(main())
