"""
Live picks for the "theoretical model" -- the factor composite treated as a
physics-style theory (formalized, audited, corrected 2026-09-22) -- TRACKED
CANDIDATE, NOT the deployed signal. See final/models/2026-09-22-composite-
model-full-specification.md for the current spec (the authoritative "what to
actually run" doc) and final/src/reset2026/PREREGISTRATION.md for the
decision-by-decision record.

UPDATED 2026-09-22 to the model's CURRENT state (was last regenerated against
the original 2026-09-19 9-factor equal-weight version -- see git history of
this file for that version's numbers):
    - `asset_growth` dropped (measured wrong-signed against its own citation,
      stable across both halves of the nomination era) -- 8 factors now.
    - Scoring is IC-shrinkage weighted (ic_weighted_composite.py's
      PRODUCTION_WEIGHTS, frozen, fit once on the nomination era, never
      re-fit), not equal-weighted.

WHY THIS IS A CANDIDATE, NOT PRIMARY (same honesty convention as the
existing xrank candidate in current_signal_pit.py):

    Nomination era (2007-2019, genuinely out-of-sample odd/even split-half
    for the weights themselves): pooled Spearman IC +0.03 to +0.05,
    t-stats 2.8-5.6.

    Hold-out (2020-2026), now confirmed a THIRD time across three different
    model versions (equal-weight baseline, asset_growth-dropped, and this
    IC-weighted version): the IC-weighted version's decile_volq portfolio
    shows +2.44%/yr excess vs SPY, 40/40 offsets positive -- but FAILS
    leave-one-year-out (dropping 2020 alone flips the mean to -3.95%/yr).
    Every version tested shows this identical failure mode: a strong
    aggregate that depends almost entirely on one year. Shown here so its
    picks can be tracked and compared in real time -- not because it is
    confirmed to work. See final/models/2026-09-22-composite-model-
    corrections.md sections 12 and 16 for the full numbers.

CONSTRUCTION (matches the full-specification doc's section 2 exactly):
    Universe: cap150 tier (market cap >= $150M, trailing 20-day median
        dollar volume >= $250k, domestic common stock, point-in-time).
    8 factors, rank-transformed, IC-shrinkage weighted (frozen weights,
        never re-fit) -- see reset2026/ic_weighted_composite.py.
    Portfolio: top decile by composite score within each of 5 trailing-
        volatility quintiles, inverse-vol weighted (decile_volq). A buffered
        variant (hold unless outside top-20%) was tested and cuts turnover
        ~3x with no return penalty, but is NOT yet the adopted default here
        -- see corrections doc section 15 -- because it is stateful
        (depends on what was already held) and this script is a stateless
        daily scorer with no persisted book.
    40-trading-day hold, no stop-loss, ~200 positions.

This script does NOT retrain anything (there is nothing to train -- the
composite has no fitted parameters; the IC weights are a frozen constant,
not fit here). It scores the MOST RECENT date in the WORKING panel,
reset2026/working_panel.WORKING_PANEL (composite_panel_v2.parquet since
2026-09-25, WO-11, per Gabe: "all models should use it"), with the v2
universe rule (old 4,011-ticker grid OR not a SPAC) applied BEFORE scoring
-- see working_panel.py's docstring for why that order matters.

KNOWN GAP (WO-11): composite_panel_v2 has NO refresh path yet.
build_downcap_grid_v2.py refuses to overwrite, and the app's Retrain chain
(downcap_universe.py -> quality_factors.py -> build_panel.py) rebuilds the v1
panel only. Until a v2 refresh builder exists, this signal stays at the v2
panel's last date (2026-09-08).

OUTPUT
    final/out/current_signal_composite.csv
    final/out/current_signal_composite_meta.json
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

# DATA (panel, output CSV/meta) always lives in the main checkout's out/,
# hardcoded absolute like every other reset2026 script -- so this script
# reads/writes the real live-app data even when invoked from inside an
# isolated git worktree (where a relative path would resolve to the
# worktree's own, data-less final/ instead).
MAIN_ROOT = Path("/Users/ggraham/pipe_dream/final")
# CODE (composite.py / ic_weighted_composite.py) is resolved relative to
# wherever THIS file itself lives, not hardcoded to the main checkout --
# so a worktree session testing an in-progress model change picks up that
# worktree's own reset2026/, not a stale main-checkout copy.
RESET_SRC = Path(__file__).resolve().parent / "reset2026"
sys.path.insert(0, str(RESET_SRC))
import composite as C  # noqa: E402
import ic_weighted_composite as ICW  # noqa: E402
import working_panel as W  # noqa: E402

PANEL = W.WORKING_PANEL
OUT_CSV = MAIN_ROOT / "out" / "current_signal_composite.csv"
OUT_META = MAIN_ROOT / "out" / "current_signal_composite_meta.json"

TIER = "cap150"

BACKTEST_SUMMARY = {
    "model_version": "ic_weighted_2026-09-22",
    "nominate_pooled_ic": "+0.03 to +0.05 (t=2.8-5.6, odd/even split-half OOS)",
    "holdout_excess_cagr_pct": 2.44,
    "holdout_offsets_positive": "40/40",
    "holdout_loyo_status": "FAILS -- dropping 2020 alone flips the mean to "
                            "-3.95%/yr. Same failure mode confirmed on three "
                            "separate model versions now (equal-weight, "
                            "asset_growth-dropped, IC-weighted). See the "
                            "full-specification and corrections docs before "
                            "trusting the headline number above.",
    "writeup": "final/models/2026-09-22-composite-model-full-specification.md",
}


def main():
    if not PANEL.exists():
        raise SystemExit(f"{PANEL} not found -- it is built by "
                         f"reset2026/build_downcap_grid_v2.py (WO-6).")

    needed = list(dict.fromkeys(
        ["ticker", "date", "sector", "close", "market_cap", "volatility_60",
         f"eligible_{TIER}"] + C.FACTOR_COLS))
    # latest date only, universe rule applied before scoring (working_panel.py)
    df_date, uinfo = W.working_cross_section(needed, path=PANEL)
    as_of = df_date["date"].max()
    elig = df_date[df_date[f"eligible_{TIER}"]].reset_index(drop=True)
    if len(elig) < 20:
        raise SystemExit(f"only {len(elig)} eligible names on {as_of.date()} -- "
                         f"panel looks stale or broken, refusing to write picks.")

    scored = ICW.compute_composite_ic_weighted(elig)
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
        "n_eligible_universe": int(len(elig)),
        "n_picks": int(len(out)),
        "construction": "decile_volq: top decile by IC-weighted composite score "
                        "within each of 5 trailing-volatility quintiles, "
                        "inverse-vol weighted, 40-trading-day hold, no stop-loss",
        "factor_signs": {k: v for k, v in C.FACTOR_SIGNS.items()},
        "factor_weights": {k: round(v, 4) for k, v in ICW.PRODUCTION_WEIGHTS.items()},
        "backtest_summary": BACKTEST_SUMMARY,
        "writeup": "final/models/2026-09-22-composite-model-full-specification.md",
        "preregistration": "final/src/reset2026/PREREGISTRATION.md",
        "panel_source": W.WORKING_PANEL_SOURCE,
        "universe_rule": "v2 eligible_cap150, SPACs excluded unless in the old 4,011-ticker grid "
                         f"({uinfo.get('spac_rows_dropped_eligible_' + TIER, 0)} eligible SPAC rows dropped)",
        "role": "candidate",
        "note": "TRACKED, NOT ACTED ON AS A VALIDATED EDGE -- a theoretical, "
                "zero-fitted-parameter rank model (only the 8 factor SIGNS and "
                "the IC-weights' shrinkage formula are decisions; no return "
                "target was ever fit). Fails leave-one-year-out on the "
                "2020-2026 hold-out across all three tested versions. See the "
                "write-up.",
    }
    OUT_META.write_text(json.dumps(meta, indent=2))
    print(f"as of {as_of.date()}: {len(out)} picks from {len(elig)} eligible names")
    print(out.head(10).to_string(index=False))
    print(f"\n-> {OUT_CSV}\n-> {OUT_META}")


if __name__ == "__main__":
    sys.exit(main())
