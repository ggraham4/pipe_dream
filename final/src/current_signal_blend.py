"""
PRIMARY -- live picks for the composite+q75 blend, promoted to the app's
front-and-center signal 2026-09-19 per Gabe's explicit instruction.

Read final/models/2026-09-19-factor-composite-reset.md and
final/src/reset2026/PREREGISTRATION.md's "Future avenues" section before
trusting this beyond what it is. Gabe was told, in the moment, before this
promotion: the blend backtest is a SINGLE GRID result (q75's score cache
has only one cadence, not this project's usual 40-offset average), it
still loses to SPY in absolute terms on the 2020-2026 hold-out (-0.36%
excess, the least-bad of three losers, not a winner), and the construction
tested (both models forced through decile_volq) is not what either model
actually ran before this promotion. He asked to proceed anyway and to
retire the prior signals. This docstring exists so that context survives
the promotion, not to relitigate it.

FROZEN FACTOR SET, added 2026-09-22 -- read before touching this file's
composite scoring. reset2026/composite.py's FACTOR_SIGNS/compute_composite
were edited 2026-09-22 (asset_growth dropped, 9 -> 8 factors, per the
model-audit/corrections work -- see final/models/2026-09-22-composite-
model-full-specification.md) AFTER this blend was promoted and backtested
against the ORIGINAL 9-factor equal-weight composite. Importing
composite.FACTOR_SIGNS/compute_composite directly here would silently
change this already-promoted, already-backtested live signal's factor set
out from under the numbers in BACKTEST_SUMMARY below, the very first time
this script is rerun after that edit -- without anyone deciding that on
purpose. So this file uses its OWN frozen copy of the original 9-factor
equal-weight scoring (_ORIGINAL_FACTOR_SIGNS / _compute_composite_frozen,
below) instead of composite.py's current, evolving version. If the blend
is ever deliberately re-promoted onto the corrected 8-factor or IC-weighted
composite, that is a real decision needing its own re-backtest (see
final/app/lib/composite_model.py for that corrected version's OWN live
signal, shown separately in the app's Theoretical Model tab for exactly
this kind of side-by-side comparison) -- not something that should happen
as a side effect of an unrelated edit to composite.py.

WO-20 BLEND + SEAS (2026-09-27, Gabe: "Yes the blend should get the
seasonality"): the LIVE composite leg is now _BLEND_FACTOR_SIGNS_V10_SEAS /
_compute_composite_frozen_v10_seas -- the ORIGINAL frozen 9 factors above
(asset_growth kept, equal weights kept) PLUS `seas` (Heston-Sadka return
seasonality, WO-18 definition, sign +1) as a 10th equal-weight factor.
Minimal change by instruction: NOT switched to icw8/icw9 weights, asset_growth
NOT dropped; q75 leg, 50/50 rank_z blend, cap2000 and decile_volq unchanged.
q75 is NOT retrained (its 24 features have no seasonality). The original
_ORIGINAL_FACTOR_SIGNS / _compute_composite_frozen stay in place, unchanged,
so the pre-WO-20 numbers stay reproducible. `seas` is computed at score time
(final/src/seasonality/seas_live.py); a missing SEP month file or seas
coverage below SEAS_MIN_COVERAGE FAILS the run (never falls back to the
9-factor leg under the new label). Before/after backtest (pre-2020 only,
single grid): final/src/seasonality/wo20_blend_seas_backtest.py. Doc:
final/models/2026-09-27-wo20-seas-live.md.

CONSTRUCTION (matches blend_q75.py's tested configuration exactly)
    Universe: cap2000 tier (market cap >= $2B, closeunadj > $10,
        point-in-time) -- q75's own universe; the composite's strongest
        result (cap150) has no q75 counterpart to blend against.
    q75 score: the SAME cached model current_signal_pit.py trains
        (out/models/xgb_pit_augmented_model.json), scored fresh on today's
        eligible universe -- not retrained here.
    composite score: the ORIGINAL 9-factor rank-combination this blend was
        actually backtested against (frozen locally, see above -- NOT
        reset2026/composite.py's current, evolving version), zero fitted
        parameters, raw (not sector-neutralized).
    blend_score = mean(rank_z(composite), rank_z(q75_score)), per date.
    Portfolio: decile_volq (top decile by blend score within each of 5
        trailing-volatility quintiles, inverse-vol weighted).

OUTPUT (--out-dir DIR writes all three into DIR instead, for worktree testing)
    final/out/current_signal_blend.csv        the ~165 actual picks
    final/out/current_signal_blend_meta.json  construction + backtest caveats
    final/out/current_signal_blend_full.csv   EVERY name scanned today (not just
        picks), with a `status` column (PICK / ELIGIBLE_NOT_PICKED /
        ELIGIBLE_NOT_SCORED / INELIGIBLE_TODAY) plus, for anything eligible,
        its exact blend score, volatility quintile and rank within that
        quintile -- this is what makes "why isn't X a pick" an answerable
        query instead of a shrug.
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from xgboost import XGBClassifier

# Hardcoded absolute (not Path(__file__)-relative) so this always reads/
# writes the real live-app data in the main checkout even when invoked from
# an isolated git worktree. This file's own composite scoring is fully
# frozen locally (see above) and only borrows unchanged utility functions
# (rank_z, pick_decile_volq) from composite.py, so it doesn't matter whether
# that import resolves to the main checkout's copy or a worktree's.
MAIN_ROOT = Path("/Users/ggraham/pipe_dream/final")
SRC = MAIN_ROOT / "src"
RESET_SRC = SRC / "reset2026"
sys.path.insert(0, str(SRC))
sys.path.insert(0, str(RESET_SRC))

from current_signal_pit import AUGMENTED_FEATURE_COLS  # noqa: E402
from continuous_walkforward_pit import load_pit_universe  # noqa: E402
import composite as C  # noqa: E402  (only rank_z / pick_decile_volq used -- NOT FACTOR_SIGNS/compute_composite)
# working_panel (WO-11) is resolved next to THIS file, appended so every
# other import above keeps resolving to the main checkout exactly as before.
sys.path.append(str(Path(__file__).resolve().parent / "reset2026"))
import working_panel as W  # noqa: E402
sys.path.append(str(Path(__file__).resolve().parent / "seasonality"))
import seas_live as SL  # noqa: E402  (WO-20)

# Frozen copy of composite.py's ORIGINAL (2026-09-19) 9-factor equal-weight
# scoring -- see the module docstring above for why this can't just call
# composite.compute_composite() anymore.
_ORIGINAL_FACTOR_SIGNS = {
    "momentum_12_1": +1,
    "pct_from_high_252": +1,
    "volatility_60": -1,
    "gross_profitability": +1,
    "accruals": -1,
    "asset_growth": -1,
    "net_issuance_pct": -1,
    "days_to_next_filing_seasonal": -1,
    "short_interest_days_to_cover": -1,
}
_ORIGINAL_FACTOR_COLS = list(_ORIGINAL_FACTOR_SIGNS)


def _compute_composite_frozen(df_date: pd.DataFrame) -> pd.DataFrame:
    """Identical logic to composite.py's original compute_composite(df_date,
    neutral=False) -- equal-weight mean of signed cross-sectional ranks over
    _ORIGINAL_FACTOR_COLS. Reuses C.rank_z (an unchanged utility) but not
    C.FACTOR_SIGNS/C.compute_composite (which have since changed)."""
    scores = pd.DataFrame(index=df_date.index)
    for c in _ORIGINAL_FACTOR_COLS:
        scores[c] = C.rank_z(df_date[c]) * _ORIGINAL_FACTOR_SIGNS[c]
    out = pd.DataFrame(index=df_date.index)
    out["ticker"] = df_date["ticker"].values
    out["coverage"] = scores.notna().sum(axis=1).values
    out["composite"] = scores.mean(axis=1, skipna=True).values
    out.loc[out["coverage"] == 0, "composite"] = np.nan
    return out


# WO-20 (2026-09-27): the LIVE composite leg. The original 9 frozen factors
# (unchanged, incl. asset_growth) + seas as a 10th EQUAL-weight factor.
_BLEND_FACTOR_SIGNS_V10_SEAS = {**_ORIGINAL_FACTOR_SIGNS, "seas": +1}
_BLEND_FACTOR_COLS_V10_SEAS = list(_BLEND_FACTOR_SIGNS_V10_SEAS)
BLEND_MODEL_VERSION = "blend_q75_ew10seas_2026-09-27"
BLEND_MODEL_VERSION_PREVIOUS = "blend_q75_ew9_2026-09-19"
SEAS_MIN_COVERAGE = 0.60


def _compute_composite_frozen_v10_seas(df_date: pd.DataFrame) -> pd.DataFrame:
    """_compute_composite_frozen with seas added: equal-weight mean of signed
    cross-sectional ranks over _BLEND_FACTOR_COLS_V10_SEAS."""
    scores = pd.DataFrame(index=df_date.index)
    for c in _BLEND_FACTOR_COLS_V10_SEAS:
        scores[c] = C.rank_z(df_date[c]) * _BLEND_FACTOR_SIGNS_V10_SEAS[c]
    out = pd.DataFrame(index=df_date.index)
    out["ticker"] = df_date["ticker"].values
    out["coverage"] = scores.notna().sum(axis=1).values
    out["composite"] = scores.mean(axis=1, skipna=True).values
    out.loc[out["coverage"] == 0, "composite"] = np.nan
    return out


def _blend_picks(elig, comp_today, comp_scored):
    """The blend construction of main(), factored out for the pick-overlap check."""
    m = elig.merge(comp_today[["ticker", "sector"]], on="ticker", how="inner").merge(
        comp_scored[["ticker", "composite"]], on="ticker", how="inner")
    q, c = C.rank_z(m["q75_score"]), C.rank_z(m["composite"])
    b = pd.concat([q, c], axis=1).mean(axis=1, skipna=True)
    b[q.isna() & c.isna()] = np.nan
    return C.pick_decile_volq(m, pd.DataFrame({"ticker": m["ticker"].to_numpy(), "composite": b.to_numpy()}))


def _overlap(p_new, p_old):
    a, b = dict(p_new), dict(p_old)
    sh = set(a) & set(b)
    return {"n_new": len(a), "n_previous": len(b), "shared": len(sh),
            "share_of_new": round(len(sh) / max(len(a), 1), 4),
            "weight_overlap": round(float(sum(min(a[t], b[t]) for t in sh)), 4)}


BASE_PANEL = MAIN_ROOT / "out" / "features_with_fundamentals_sharadar_pit.parquet"
# WO-11 (2026-09-25, Gabe: "all models should use it"): the composite leg
# reads the WORKING panel (composite_panel_v2) with the v2 universe rule
# (old 4,011-ticker grid OR not a SPAC) applied before rank_z. The q75 leg
# and the cap2000 eligibility (load_pit_universe) are unchanged. v2 has NO
# refresh path yet (build_downcap_grid_v2.py never overwrites): once the base
# panel moves past v2's last date (2026-09-08) this script stops with the
# "no eligible rows" error below until a v2 refresh builder exists.
COMPOSITE_PANEL = W.WORKING_PANEL
Q75_MODEL = MAIN_ROOT / "out" / "models" / "xgb_pit_augmented_model.json"
OUT_CSV = MAIN_ROOT / "out" / "current_signal_blend.csv"
OUT_META = MAIN_ROOT / "out" / "current_signal_blend_meta.json"
OUT_FULL_CSV = MAIN_ROOT / "out" / "current_signal_blend_full.csv"
N_VOL_QUINTILES = 5
BOOK_FRAC = 0.10

TIER = "cap2000"

BACKTEST_SUMMARY = {
    "single_grid_only": True,
    "excess_cagr_vs_spy_pct": 1.54,
    "q75_alone_excess_cagr_vs_spy_pct": 0.35,
    "composite_alone_excess_cagr_vs_spy_pct": 0.54,
    "nominate_only_excess_cagr_pct": 2.52,
    "holdout_only_excess_cagr_pct": -0.36,
    "holdout_still_negative_in_absolute_terms": True,
    "null_percentile": 1.0,
    "loyo_drop_2020_still_positive": True,
    "source": "final/src/reset2026/blend_q75.py, final/out/reset2026/blend_q75_report.json",
    "writeup": "final/models/2026-09-19-factor-composite-reset.md",
    "note_wo20": "All numbers above are the PREVIOUS 9-factor blend (blend_q75_ew9_2026-09-19). "
                 "The live blend since WO-20 adds seas; its before/after is in wo20_seas_pre2020.",
    "wo20_seas_pre2020": {
        "harness": "blend_q75.py port, SINGLE GRID (q75 cadence), 82 windows 2007-01-03..2019-11-14, "
                   "v2 panel + column-c universe rule, net 15bp; no 2020+ window read",
        "blend_previous_9factor": {"excess_cagr_vs_spy_pct": 2.52, "loyo_min_pct": 2.07,
                                   "loyo_min_dropped_year": 2010, "post_2011_10_pct": 0.60},
        "blend_new_10factor_seas": {"excess_cagr_vs_spy_pct": 2.40, "loyo_min_pct": 1.87,
                                    "loyo_min_dropped_year": 2013, "post_2011_10_pct": 0.20},
        "composite_leg_alone": {"previous_9factor_pct": 1.18, "new_10factor_seas_pct": 1.67},
        "reading": "Adding seas raises the composite leg alone (+0.49pp/yr) but LOWERS the blend "
                   "(-0.12pp/yr, LOYO min -0.20pp, post-2011-10 -0.40pp) on this single grid. "
                   "Adopted by Gabe's decision (2026-09-27), not on this backtest.",
        "source": "final/src/seasonality/wo20_blend_seas_backtest.py -> final/out/seasonality/wo20_blend_seas_backtest.json",
    },
}


def blend_scores_at(d, label_col=None):
    """WO-20 forward record (seas_forward.py's blend_seas ledger): the same
    scoring main() does, for ONE date d, for EVERY name scored by both legs.
    Returns (frame [ticker, sector, volatility_60, q75_score, seas,
    composite_prev9, composite_seas10, blend_prev9_score, blend_seas10_score]
    (+ label_col from the working panel when given, for the blindness guard),
    seas_info). Writes nothing."""
    d = pd.Timestamp(d)
    needed = list(dict.fromkeys(["ticker", "date"] + AUGMENTED_FEATURE_COLS))
    base = pd.read_parquet(BASE_PANEL, columns=needed, filters=[("date", "==", d)])
    base["ticker"] = base["ticker"].astype(str)
    if base.empty:
        raise SystemExit(f"base panel has no rows on {d.date()} (q75 leg); run the base Retrain first")
    elig = base[base["ticker"].isin(set(load_pit_universe().get(str(d.date()), [])))].copy()
    model = XGBClassifier()
    model.load_model(str(Q75_MODEL))
    elig["q75_score"] = model.predict_proba(elig[AUGMENTED_FEATURE_COLS])[:, 1]
    cols = ["ticker", "date", "sector", "volatility_60", f"eligible_{TIER}"] + _ORIGINAL_FACTOR_COLS
    if label_col:
        cols.append(label_col)
    comp, _u = W.working_cross_section(list(dict.fromkeys(cols)), date=d, path=COMPOSITE_PANEL)
    comp = comp[comp[f"eligible_{TIER}"]].reset_index(drop=True)
    if comp.empty:
        raise SystemExit(f"no eligible_{TIER} rows in {COMPOSITE_PANEL.name} on {d.date()}")
    sf, seas_info = SL.seas_asof(comp["ticker"], d)
    comp["seas"] = sf["seas"].to_numpy(np.float64)
    if not seas_info["coverage"] >= SEAS_MIN_COVERAGE:
        raise SystemExit(f"seas coverage {seas_info['coverage']:.1%} on {d.date()} < {SEAS_MIN_COVERAGE:.0%}")
    comp["composite_prev9"] = _compute_composite_frozen(comp)["composite"].to_numpy()
    comp["composite_seas10"] = _compute_composite_frozen_v10_seas(comp)["composite"].to_numpy()
    m = elig[["ticker", "q75_score"]].merge(comp, on="ticker", how="inner")
    q = C.rank_z(m["q75_score"])
    for src, dst in (("composite_prev9", "blend_prev9_score"), ("composite_seas10", "blend_seas10_score")):
        c = C.rank_z(m[src])
        b = pd.concat([q, c], axis=1).mean(axis=1, skipna=True)
        b[q.isna() & c.isna()] = np.nan
        m[dst] = b.to_numpy()
    keep = ["ticker", "sector", "volatility_60", "q75_score", "seas", "composite_prev9", "composite_seas10",
            "blend_prev9_score", "blend_seas10_score"] + ([label_col] if label_col else [])
    return m[keep].reset_index(drop=True), seas_info


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", default=None, help="write the 3 outputs here instead of final/out")
    args = ap.parse_args(argv)
    out_csv, out_meta, out_full = OUT_CSV, OUT_META, OUT_FULL_CSV
    if args.out_dir:
        od = Path(args.out_dir)
        od.mkdir(parents=True, exist_ok=True)
        out_csv, out_meta, out_full = od / OUT_CSV.name, od / OUT_META.name, od / OUT_FULL_CSV.name
    print(f"loading base panel for q75 scoring ...")
    needed = list(dict.fromkeys(["ticker", "date", "close", "market_cap"] + AUGMENTED_FEATURE_COLS))
    base = pd.read_parquet(BASE_PANEL, columns=needed)
    base["date"] = pd.to_datetime(base["date"])
    base["ticker"] = base["ticker"].astype(str)
    as_of = base["date"].max()
    today = base[base["date"] == as_of].copy()
    print(f"  as of {as_of.date()}: {len(today):,} candidate rows")

    pit_universe = load_pit_universe()
    elig_today = set(pit_universe.get(str(as_of.date()), []))
    today["eligible_today"] = today["ticker"].isin(elig_today)
    elig = today[today["eligible_today"]].copy()
    print(f"  {len(elig):,} eligible at cap2000 tier today")

    print("scoring q75 (cached model, not retrained) ...")
    model = XGBClassifier()
    model.load_model(str(Q75_MODEL))
    elig["q75_score"] = model.predict_proba(elig[AUGMENTED_FEATURE_COLS])[:, 1]

    print("loading composite panel + scoring composite (frozen 9-factor original + seas, WO-20) ...")
    comp_needed = list(dict.fromkeys(
        ["ticker", "date", "sector", "volatility_60", f"eligible_{TIER}"] + _ORIGINAL_FACTOR_COLS))
    comp_panel, uinfo = W.working_cross_section(comp_needed, date=as_of, path=COMPOSITE_PANEL)
    comp_today = comp_panel[comp_panel[f"eligible_{TIER}"]].reset_index(drop=True)
    if comp_today.empty:
        raise SystemExit(f"no eligible_{TIER} rows in {COMPOSITE_PANEL.name} on {as_of.date()} -- "
                         f"the working panel (v2) has no refresh path yet; see WO-11.")
    # WO-20: live seas on the WHOLE eligible cap2000 cross-section before rank_z
    sf, seas_info = SL.seas_asof(comp_today["ticker"], as_of)
    assert (sf["ticker"].to_numpy() == comp_today["ticker"].astype(str).to_numpy()).all()
    comp_today = comp_today.copy()
    comp_today["seas"] = sf["seas"].to_numpy(np.float64)
    if not seas_info["coverage"] >= SEAS_MIN_COVERAGE:
        raise SystemExit(f"seas coverage {seas_info['coverage']:.1%} on {as_of.date()} < "
                         f"{SEAS_MIN_COVERAGE:.0%} -- SEP month files look incomplete; refusing to write picks.")
    comp_scored = _compute_composite_frozen_v10_seas(comp_today)
    # monitoring only: the previous 9-factor blend's picks today
    pick_overlap = _overlap(_blend_picks(elig, comp_today, comp_scored),
                            _blend_picks(elig, comp_today, _compute_composite_frozen(comp_today)))

    merged = elig.merge(
        comp_today[["ticker", "sector"]], on="ticker", how="inner"
    ).merge(
        comp_scored[["ticker", "composite"]], on="ticker", how="inner"
    )
    print(f"  {len(merged):,} names scored by both models")

    q75_rank = C.rank_z(merged["q75_score"])
    comp_rank = C.rank_z(merged["composite"])
    blend = pd.concat([q75_rank, comp_rank], axis=1).mean(axis=1, skipna=True)
    blend[q75_rank.isna() & comp_rank.isna()] = np.nan
    scored = pd.DataFrame({"ticker": merged["ticker"].to_numpy(), "composite": blend.to_numpy()})
    merged["blend_score"] = blend.to_numpy()

    elig_for_pick = merged.rename(columns={"volatility_60": "volatility_60"})
    picks = C.pick_decile_volq(elig_for_pick, scored)
    if not picks:
        raise SystemExit("pick_decile_volq returned no picks -- check inputs.")
    weights = {t: w for t, w in picks}

    # Bucket/rank EVERY scored name, not just the picks, so a query for a
    # non-pick can say WHY -- not eligible at all, vs eligible and scored but
    # ranked outside the top decile of its own volatility quintile. Mirrors
    # composite.pick_decile_volq's own bucketing exactly (same qcut call on
    # the same valid mask) rather than approximating it.
    vol = merged["volatility_60"].to_numpy(np.float64)
    valid = np.isfinite(vol) & np.isfinite(merged["blend_score"].to_numpy(np.float64))
    merged["vol_quintile"] = np.nan
    merged["rank_in_quintile"] = np.nan
    merged["n_in_quintile"] = np.nan
    merged["quintile_cutoff_rank"] = np.nan
    if valid.sum() >= N_VOL_QUINTILES * 4:
        idx = np.flatnonzero(valid)
        vol_v = vol[idx]
        q = pd.qcut(vol_v, N_VOL_QUINTILES, labels=False, duplicates="drop")
        comp_v = merged["blend_score"].to_numpy(np.float64)[idx]
        for bucket in np.unique(q):
            bmask = q == bucket
            n_bucket = int(bmask.sum())
            k = max(1, int(round(n_bucket * BOOK_FRAC)))
            b_idx = idx[bmask]
            order = np.argsort(-comp_v[bmask])
            ranks = np.empty(len(order), dtype=int)
            ranks[order] = np.arange(1, len(order) + 1)
            merged.loc[merged.index[b_idx], "vol_quintile"] = int(bucket)
            merged.loc[merged.index[b_idx], "rank_in_quintile"] = ranks
            merged.loc[merged.index[b_idx], "n_in_quintile"] = n_bucket
            merged.loc[merged.index[b_idx], "quintile_cutoff_rank"] = k

    merged["is_pick"] = merged["ticker"].isin(weights)
    merged["weight"] = merged["ticker"].map(weights)

    # Full scanned universe today, INCLUDING names that failed the cap2000
    # eligibility screen entirely -- a query needs to distinguish "not
    # eligible today" from "eligible but not picked", and only having the
    # eligible+scored subset can't do that.
    full = today[["ticker", "close", "market_cap", "eligible_today"]].merge(
        merged[["ticker", "sector", "volatility_60", "q75_score", "composite", "blend_score",
                "vol_quintile", "rank_in_quintile", "n_in_quintile", "quintile_cutoff_rank",
                "is_pick", "weight"]],
        on="ticker", how="left"
    ).rename(columns={"composite": "composite_score"})
    full["status"] = np.select(
        [full["is_pick"] == True, full["eligible_today"] & full["blend_score"].notna(),
         full["eligible_today"]],
        ["PICK", "ELIGIBLE_NOT_PICKED", "ELIGIBLE_NOT_SCORED"],
        default="INELIGIBLE_TODAY",
    )
    full.to_csv(out_full, index=False)
    print(f"  full universe: {len(full):,} names scanned, "
          f"{(full['status'] == 'PICK').sum()} picks, "
          f"{(full['status'] == 'ELIGIBLE_NOT_PICKED').sum()} eligible-not-picked, "
          f"{(full['status'] == 'INELIGIBLE_TODAY').sum()} ineligible today")

    out = merged[merged["ticker"].isin(weights)][
        ["ticker", "sector", "close", "market_cap", "volatility_60", "q75_score"]
    ].copy()
    out["composite_score"] = out["ticker"].map(dict(zip(merged["ticker"], merged["composite"])))
    out["blend_score"] = out["ticker"].map(dict(zip(merged["ticker"], merged["blend_score"])))
    out["weight"] = out["ticker"].map(weights)
    out = out.sort_values("weight", ascending=False).reset_index(drop=True)
    out.to_csv(out_csv, index=False)

    meta = {
        "as_of_date": as_of.strftime("%Y-%m-%d"),
        "tier": TIER,
        "n_eligible_universe": int(len(merged)),
        "n_picks": int(len(out)),
        "model_version": BLEND_MODEL_VERSION,
        "construction": "blend_score = mean(rank_z(composite_10factor_frozen_ew_seas), rank_z(q75_xgboost)), "
                        "decile_volq portfolio (top decile per trailing-vol quintile, inverse-vol "
                        "weighted), 40-trading-day hold, no stop-loss",
        "factors": {k: v for k, v in _BLEND_FACTOR_SIGNS_V10_SEAS.items()},
        "seas": {"definition": "Heston-Sadka: mean same-calendar-month return over the prior 10 years "
                               "(target month = month of t+28 calendar days; >= 5 years; SEP closeadj)",
                 "coverage": round(seas_info["coverage"], 4), "target_month": seas_info["target_month"],
                 "months_used": seas_info["months_used"], "basis_flag": seas_info["basis_flag"],
                 "code": "final/src/seasonality/seas_live.py"},
        "picks_overlap_vs_previous_9factor_blend": pick_overlap,
        "q75_weight": 0.5,
        "composite_weight": 0.5,
        "backtest_summary": BACKTEST_SUMMARY,
        "composite_panel_source": W.WORKING_PANEL_SOURCE,
        "universe_rule": "composite leg: v2 eligible_cap2000, SPACs excluded unless in the old "
                         f"4,011-ticker grid ({uinfo.get('spac_rows_dropped_eligible_' + TIER, 0)} "
                         "eligible SPAC rows dropped)",
        "role": "primary",
        "note": "Promoted to primary 2026-09-19 on a SINGLE-GRID backtest (not this "
                "project's usual 40-offset average) that still shows negative absolute "
                "excess vs SPY on the 2020-2026 hold-out (-0.36%, the least-bad of the "
                "three constructions tested, not a winner in absolute terms). See "
                "final/models/2026-09-19-factor-composite-reset.md. Composite factor set "
                "frozen 2026-09-22 to the exact version this backtest ran against -- see "
                "this file's module docstring; the corrected/IC-weighted version is shown "
                "separately in the app's Theoretical Model tab. WO-20 (2026-09-27, Gabe): "
                "seas added as a 10th equal-weight factor of the composite leg; q75 not retrained.",
    }
    out_meta.write_text(json.dumps(meta, indent=2))
    print(f"\nas of {as_of.date()}: {len(out)} picks from {len(merged)} scored names")
    print(out.head(10).to_string(index=False))
    print(f"seas coverage {seas_info['coverage']:.1%}; picks overlap vs previous 9-factor blend: {pick_overlap}")
    print(f"\n-> {out_csv}\n-> {out_meta}\n-> {out_full}")


if __name__ == "__main__":
    sys.exit(main())
