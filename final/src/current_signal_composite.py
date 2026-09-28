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

WO-20 (2026-09-27, Gabe: "Seasonality looks very good so you should add it
to the model"): the model is now icw9_seas -- the 8 factors below PLUS
Heston-Sadka return seasonality `seas` (WO-18 definition), scored with the
frozen ic_weighted_composite.PRODUCTION_WEIGHTS_V9_SEAS (model_version
ic_weighted_seas_2026-09-27). `seas` is computed at SCORE TIME from the SEP
month files (final/src/seasonality/seas_live.py), so the panel is untouched.
The in-era backtest of icw9_seas uses IN-SAMPLE weights; there is NO
hold-out number for icw9_seas (the hold-out is spent). The hold-out lines in
BACKTEST_SUMMARY are the icw8 model's. Doc: final/models/2026-09-27-wo20-seas-live.md.
A missing SEP month file or seas coverage < SEAS_MIN_COVERAGE FAILS the run;
it never falls back to icw8 (that would publish icw8 picks labelled icw9).

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
    (--out-dir DIR writes both into DIR instead, for worktree testing)
"""
import argparse
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
sys.path.insert(0, str(RESET_SRC.parent / "seasonality"))
import seas_live as SL  # noqa: E402

PANEL = W.WORKING_PANEL
OUT_CSV = MAIN_ROOT / "out" / "current_signal_composite.csv"
OUT_META = MAIN_ROOT / "out" / "current_signal_composite_meta.json"

TIER = "cap150"

WEIGHTS = ICW.PRODUCTION_WEIGHTS_V9_SEAS
SIGNS = ICW.SIGNS_V9_SEAS
MODEL_VERSION = ICW.MODEL_VERSION_V9_SEAS
SEAS_MIN_COVERAGE = 0.60   # of the eligible cap150 cross-section; in-era 0.76-0.85

BACKTEST_SUMMARY = {
    "model_version": MODEL_VERSION,
    "factors": "9: the 8 icw8 factors + seas (Heston-Sadka return seasonality, WO-18), "
               "added 2026-09-27 by Gabe's decision",
    "in_era_backtest_2007_2019": {
        "harness": "WO-18 (v2 col c, cap150, decile_volq, 40 offsets, net 15bp, 2007-01-02..2019-12-31)",
        "icw9_seas": {"excess_cagr_vs_spy_pct": 3.49, "worst_offset_pct": 2.95, "loyo_min_pct": 2.46,
                      "post_2011_10_pct": 0.51, "offsets_positive": "40/40"},
        "icw8_previous_model": {"excess_cagr_vs_spy_pct": 2.85, "worst_offset_pct": 1.93, "loyo_min_pct": 1.71,
                                "post_2011_10_pct": 0.01, "offsets_positive": "40/40"},
        "in_sample_note": "IN-SAMPLE: the icw9_seas weights come from the same full-era t-stats "
                          "the backtest is read on (seas t +2.8356). Not an out-of-sample result.",
        "source": "final/src/seasonality/wo20_frozen_backtest.py -> final/out/seasonality/wo20_frozen_backtest.json",
    },
    "holdout_2020_2026": "icw9_seas: NONE -- the hold-out is spent; no look without Gabe. "
                         "The icw8_* lines below are the PREVIOUS 8-factor model's hold-out result.",
    "icw8_model_version": "ic_weighted_2026-09-22",
    "nominate_pooled_ic": "+0.03 to +0.05 (t=2.8-5.6, odd/even split-half OOS)",
    "icw8_holdout_excess_cagr_pct": 2.44,
    "icw8_holdout_offsets_positive": "40/40",
    "icw8_holdout_loyo_status": "FAILS -- dropping 2020 alone flips the mean to "
                            "-3.95%/yr. Same failure mode confirmed on three "
                            "separate model versions now (equal-weight, "
                            "asset_growth-dropped, IC-weighted). See the "
                            "full-specification and corrections docs before "
                            "trusting the headline number above.",
    "writeup": "final/models/2026-09-22-composite-model-full-specification.md",
    "wo20_doc": "final/models/2026-09-27-wo20-seas-live.md",
    "forward_record": "prediction_ledger_seas.csv (weekly; paired rho(icw9_seas) - rho(icw8), "
                      "read once at 6 counted dates)",
}


def overlap(p_a, p_b):
    a, b = dict(p_a), dict(p_b)
    shared = set(a) & set(b)
    return {"n_icw9_seas": len(a), "n_icw8": len(b), "shared": len(shared),
            "share_of_icw9_seas": round(len(shared) / max(len(a), 1), 4),
            "weight_overlap": round(float(sum(min(a[t], b[t]) for t in shared)), 4)}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", default=None,
                    help="write the CSV/meta here instead of the main checkout's final/out")
    args = ap.parse_args(argv)
    out_csv, out_meta = OUT_CSV, OUT_META
    if args.out_dir:
        od = Path(args.out_dir)
        od.mkdir(parents=True, exist_ok=True)
        out_csv, out_meta = od / OUT_CSV.name, od / OUT_META.name
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

    # WO-20: live seas for the WHOLE eligible cross-section before scoring
    # (rank_z runs over the full cross-section). Fails loudly, never falls back.
    sf, seas_info = SL.seas_asof(elig["ticker"], as_of)
    assert (sf["ticker"].to_numpy() == elig["ticker"].astype(str).to_numpy()).all()
    elig = elig.copy()
    elig["seas"] = sf["seas"].to_numpy(np.float64)
    if not seas_info["coverage"] >= SEAS_MIN_COVERAGE:
        raise SystemExit(f"seas coverage {seas_info['coverage']:.1%} on {as_of.date()} < "
                         f"{SEAS_MIN_COVERAGE:.0%} -- SEP month files look incomplete; refusing to write picks.")
    scored = ICW.compute_composite_ic_weighted(elig, weights=WEIGHTS)
    picks = C.pick_decile_volq(elig, scored)
    if not picks:
        raise SystemExit(f"pick_decile_volq returned no picks on {as_of.date()}.")
    # monitoring only: what the previous icw8 model would pick today
    picks8 = C.pick_decile_volq(elig, ICW.compute_composite_ic_weighted(elig, weights=ICW.PRODUCTION_WEIGHTS))
    pick_overlap = overlap(picks, picks8)

    tickers = [t for t, _ in picks]
    weights = {t: w for t, w in picks}
    out = elig[elig["ticker"].isin(tickers)][
        ["ticker", "sector", "close", "market_cap", "volatility_60"]
    ].copy()
    comp_lookup = dict(zip(scored["ticker"], scored["composite"]))
    out["composite_score"] = out["ticker"].map(comp_lookup)
    out["weight"] = out["ticker"].map(weights)
    out = out.sort_values("weight", ascending=False).reset_index(drop=True)
    out["seas"] = out["ticker"].map(dict(zip(elig["ticker"], elig["seas"])))
    out.to_csv(out_csv, index=False)

    meta = {
        "as_of_date": as_of.strftime("%Y-%m-%d"),
        "tier": TIER,
        "n_eligible_universe": int(len(elig)),
        "n_picks": int(len(out)),
        "model_version": MODEL_VERSION,
        "n_factors": len(WEIGHTS),
        "construction": "decile_volq: top decile by IC-weighted composite score "
                        "within each of 5 trailing-volatility quintiles, "
                        "inverse-vol weighted, 40-trading-day hold, no stop-loss",
        "factor_signs": {k: SIGNS[k] for k in WEIGHTS},
        "factor_weights": {k: round(v, 4) for k, v in WEIGHTS.items()},
        "seas": {"definition": "Heston-Sadka: mean same-calendar-month return over the prior 10 years "
                               "(target month = month of t+28 calendar days; >= 5 years; SEP closeadj)",
                 "coverage": round(seas_info["coverage"], 4), "target_month": seas_info["target_month"],
                 "months_used": seas_info["months_used"], "basis_flag": seas_info["basis_flag"],
                 "code": "final/src/seasonality/seas_live.py"},
        "picks_overlap_vs_icw8": pick_overlap,
        "backtest_summary": BACKTEST_SUMMARY,
        "writeup": "final/models/2026-09-22-composite-model-full-specification.md",
        "preregistration": "final/src/reset2026/PREREGISTRATION.md",
        "panel_source": W.WORKING_PANEL_SOURCE,
        "universe_rule": "v2 eligible_cap150, SPACs excluded unless in the old 4,011-ticker grid "
                         f"({uinfo.get('spac_rows_dropped_eligible_' + TIER, 0)} eligible SPAC rows dropped)",
        "role": "candidate",
        "note": "TRACKED, NOT ACTED ON AS A VALIDATED EDGE -- a theoretical, "
                "zero-fitted-parameter rank model (only the 9 factor SIGNS and "
                "the IC-weights' shrinkage formula are decisions; no return "
                "target was ever fit). seas was added 2026-09-27 (Gabe); its "
                "in-era backtest uses in-sample weights and it has no hold-out "
                "result. The previous 8-factor version fails leave-one-year-out "
                "on the 2020-2026 hold-out. See the write-ups.",
    }
    out_meta.write_text(json.dumps(meta, indent=2))
    print(f"as of {as_of.date()}: {len(out)} picks from {len(elig)} eligible names "
          f"({MODEL_VERSION}; seas coverage {seas_info['coverage']:.1%})")
    print(f"picks overlap vs icw8: {pick_overlap}")
    print(out.head(10).to_string(index=False))
    print(f"\n-> {out_csv}\n-> {out_meta}")


if __name__ == "__main__":
    sys.exit(main())
