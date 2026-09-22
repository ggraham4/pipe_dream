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

CONSTRUCTION (matches blend_q75.py's tested configuration exactly)
    Universe: cap2000 tier (market cap >= $2B, closeunadj > $10,
        point-in-time) -- q75's own universe; the composite's strongest
        result (cap150) has no q75 counterpart to blend against.
    q75 score: the SAME cached model current_signal_pit.py trains
        (out/models/xgb_pit_augmented_model.json), scored fresh on today's
        eligible universe -- not retrained here.
    composite score: reset2026/composite.py's 9-factor rank-combination,
        zero fitted parameters, raw (not sector-neutralized).
    blend_score = mean(rank_z(composite), rank_z(q75_score)), per date.
    Portfolio: decile_volq (top decile by blend score within each of 5
        trailing-volatility quintiles, inverse-vol weighted).

OUTPUT
    final/out/current_signal_blend.csv        the ~165 actual picks
    final/out/current_signal_blend_meta.json  construction + backtest caveats
    final/out/current_signal_blend_full.csv   EVERY name scanned today (not just
        picks), with a `status` column (PICK / ELIGIBLE_NOT_PICKED /
        ELIGIBLE_NOT_SCORED / INELIGIBLE_TODAY) plus, for anything eligible,
        its exact blend score, volatility quintile and rank within that
        quintile -- this is what makes "why isn't X a pick" an answerable
        query instead of a shrug.
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from xgboost import XGBClassifier

MAIN_ROOT = Path(__file__).resolve().parent.parent
SRC = MAIN_ROOT / "src"
RESET_SRC = SRC / "reset2026"
sys.path.insert(0, str(SRC))
sys.path.insert(0, str(RESET_SRC))

from current_signal_pit import AUGMENTED_FEATURE_COLS  # noqa: E402
from continuous_walkforward_pit import load_pit_universe  # noqa: E402
import composite as C  # noqa: E402

BASE_PANEL = MAIN_ROOT / "out" / "features_with_fundamentals_sharadar_pit.parquet"
COMPOSITE_PANEL = MAIN_ROOT / "out" / "reset2026" / "composite_panel.parquet"
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
}


def main():
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

    print("loading composite panel + scoring composite ...")
    comp_needed = list(dict.fromkeys(
        ["ticker", "date", "sector", "volatility_60", f"eligible_{TIER}"] + C.FACTOR_COLS))
    comp_panel = pd.read_parquet(COMPOSITE_PANEL, columns=comp_needed)
    comp_panel["date"] = pd.to_datetime(comp_panel["date"])
    comp_panel["ticker"] = comp_panel["ticker"].astype(str)
    comp_today = comp_panel[(comp_panel["date"] == as_of) & (comp_panel[f"eligible_{TIER}"])].reset_index(drop=True)
    if comp_today.empty:
        raise SystemExit(f"no eligible_{TIER} rows in composite panel on {as_of.date()} -- "
                         f"rebuild reset2026/build_panel.py first.")
    comp_scored = C.compute_composite(comp_today, neutral=False)

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
    full.to_csv(OUT_FULL_CSV, index=False)
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
    out.to_csv(OUT_CSV, index=False)

    meta = {
        "as_of_date": as_of.strftime("%Y-%m-%d"),
        "tier": TIER,
        "n_eligible_universe": int(len(merged)),
        "n_picks": int(len(out)),
        "construction": "blend_score = mean(rank_z(composite_9factor), rank_z(q75_xgboost)), "
                        "decile_volq portfolio (top decile per trailing-vol quintile, inverse-vol "
                        "weighted), 40-trading-day hold, no stop-loss",
        "factors": {k: v for k, v in C.FACTOR_SIGNS.items()},
        "q75_weight": 0.5,
        "composite_weight": 0.5,
        "backtest_summary": BACKTEST_SUMMARY,
        "role": "primary",
        "note": "Promoted to primary 2026-09-19 on a SINGLE-GRID backtest (not this "
                "project's usual 40-offset average) that still shows negative absolute "
                "excess vs SPY on the 2020-2026 hold-out (-0.36%, the least-bad of the "
                "three constructions tested, not a winner in absolute terms). See "
                "final/models/2026-09-19-factor-composite-reset.md.",
    }
    OUT_META.write_text(json.dumps(meta, indent=2))
    print(f"\nas of {as_of.date()}: {len(out)} picks from {len(merged)} scored names")
    print(out.head(10).to_string(index=False))
    print(f"\n-> {OUT_CSV}\n-> {OUT_META}\n-> {OUT_FULL_CSV}")


if __name__ == "__main__":
    sys.exit(main())
