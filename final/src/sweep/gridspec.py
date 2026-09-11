"""
The frozen grid.

Round 12 (2026-09-09).

This file IS the pre-registration's machine-readable half. It is written before
any cell is run and it is not edited after a result is seen -- if the grid needs
to change, that happens in its own commit, before the next run, and prior
verdicts stand (validation-gates.md, standing process rule 5).

The trial count matters directly: the Deflated Sharpe Ratio's threshold rises
with the number of configs searched, so every cell added here raises the bar
that the eventual winner has to clear. That is the correct incentive. A grid is
not free, and "sweep everything" is not a strategy -- it is a way of
guaranteeing that the best cell looks good.

Structure
---------
PHASE A   one-factor-at-a-time around the production config, plus no-ML
          controls. 27 signal cells. Establishes which axes move anything at
          all, at a cost that fits one overnight run.

PHASE B   full cross of only the axes Phase A showed sensitivity on. Generated
          after A, from A's results, in its own commit.

PHASE C   tranching / finer rebalance for whatever survives B. Expensive
          (4x the fits) so it is spent only on finalists.

PORTFOLIO the construction grid applied to every signal cell. 48 configs.
          Free to run; not free statistically.
"""

import json
import sys
from pathlib import Path

# --------------------------------------------------------------------------
# The production config -- every Phase A cell is this with ONE field changed.
# Matches out/continuous_walkforward_pit_augmented_pit_realistic_tradable.json
# --------------------------------------------------------------------------
CENTER = {
    "features": "price_fund",
    "horizon": 40,
    "label": "q75",
    "label_basis": "tradable",
    "model": "xgb",
    "depth": 3,
    "eta": 0.1,
    "rounds": 100,
    "train": "expanding",
    "train_cap": 0,
    "universe": "pit",
    "cap_tier": "all",
    "step": 40,
    "seed": 0,
}


def _c(**over):
    d = dict(CENTER)
    d.update(over)
    if "horizon" in over and "step" not in over:
        d["step"] = over["horizon"]
    return d


# --------------------------------------------------------------------------
# PHASE A -- 27 cells, one axis moved at a time
# --------------------------------------------------------------------------
PHASE_A = [
    # 0. the production config itself, as the reference point
    _c(),

    # 1-3. FEATURE SET. 'novol' is the direct test of the B6 finding: if the
    # model is a volatility bet, deleting the two volatility columns collapses
    # it. 'volonly' is the same question from the other side.
    _c(features="price"),
    _c(features="novol"),
    _c(features="volonly"),

    # 4-6. HORIZON. The 40-day default was chosen on 8 timepoints in Aug 2026,
    # on data since found to be defective. It has never been re-tested.
    _c(horizon=10),
    _c(horizon=20),
    _c(horizon=60),

    # 7-11. LABEL DESIGN. 'xrank' strips the market component out of the
    # target entirely -- the model has only ever been trained on a target that
    # mixes "beat your peers" with "the market went up", and only the first is
    # something a cross-sectional selector can act on. 'volresid' targets
    # risk-adjusted outperformance instead of raw magnitude.
    _c(label="q60"),
    _c(label="q90"),
    _c(label="raw"),
    _c(label="xrank"),
    _c(label="volresid"),

    # 12. THE KNOWN-INFLATED CONTROL. close[t+H]/close[t] credits an overnight
    # move the strategy cannot capture, and Round 9 found it "carried the
    # entire published edge". It is in the grid as a positive control: if this
    # cell does NOT come out visibly better than the tradable one, something
    # is wrong with the harness, not with the market.
    _c(label_basis="as_published"),

    # 13-16. MODEL FAMILY AND CAPACITY.
    _c(model="xgb_reg", label="raw"),
    _c(model="ridge", label="xrank"),
    _c(depth=2),
    _c(depth=5),

    # 17-19. NO-ML CONTROLS. Rank on one column, no training at all, same
    # universe and same timepoints. If XGBoost cannot beat these, the ML is
    # contributing nothing and that is the finding.
    _c(model="feat:-volatility_60"),
    _c(model="feat:momentum_20"),
    _c(model="feat:pct_from_high_252"),

    # 20-23. TRAINING REGIME. The expanding window means a 2026 decision is
    # made by a model that spent most of its training on 2007-2015. Whether
    # that helps or hurts has never been tested here.
    _c(train="roll5"),
    _c(train="roll8"),
    _c(train_cap=1_500_000),
    _c(train_cap=500_000),

    # 24-26. UNIVERSE. cap tiers test whether any edge is concentrated where
    # the B6 ablation implied it would be.
    _c(universe="sp500"),
    _c(cap_tier="mega"),
    _c(cap_tier="mid"),
]

# --------------------------------------------------------------------------
# PORTFOLIO grid -- 48 configs, applied to every signal cell
# --------------------------------------------------------------------------
# Breadth is first because the baseline's problem is variance, not alpha:
# arithmetic excess -0.11%/window, compounded 0.998x vs SPY 5.229x. A 5-name
# book with zero skill lands near there on its own.
PORTFOLIO = [
    {"top_n": n, "weighting": w, "stop": s, "bucket": b, "vol_target": v,
     "cost_bps": 15.0, "cost_model": "turnover", "untradable": "drop"}
    for n in (5, 20, 50)
    for w in ("equal", "invvol")
    for s in (None, 0.15)
    for b in ("none", "volq")
    for v in (None, 0.20)
]

# Descriptive only -- run AFTER nomination, never used to pick a winner, so
# these do not enter the trial count.
SENSITIVITY = [
    {"top_n": 20, "weighting": "equal", "stop": None, "bucket": "none",
     "vol_target": None, "cost_bps": c, "cost_model": m, "untradable": u}
    for c in (15.0, 50.0, 100.0)
    for m in ("turnover", "per_window")
    for u in ("drop", "zero", "worst")
]


def main():
    what = sys.argv[1] if len(sys.argv) > 1 else "all"
    here = Path(__file__).resolve().parent
    wrote = []
    if what in ("all", "a"):
        p = here / "cells_phase_a.json"
        p.write_text(json.dumps(PHASE_A, indent=2))
        wrote.append((p, len(PHASE_A)))
    if what in ("all", "portfolio"):
        p = here / "grid_portfolio.json"
        p.write_text(json.dumps(PORTFOLIO, indent=2))
        wrote.append((p, len(PORTFOLIO)))
        p = here / "grid_sensitivity.json"
        p.write_text(json.dumps(SENSITIVITY, indent=2))
        wrote.append((p, len(SENSITIVITY)))
    for p, n in wrote:
        print(f"{n:>4} entries -> {p}")
    print(f"\nPhase A trial count: {len(PHASE_A)} signal x {len(PORTFOLIO)} "
          f"portfolio = {len(PHASE_A) * len(PORTFOLIO)} cells")
    print("That number is the deflation denominator. It is fixed now, before "
          "any result is seen.")


if __name__ == "__main__":
    main()
