"""
Sector/industry-neutralized (cross-sectionally demeaned) features.

Round 20 (2026-09-17). Item #1 of the ranked data-sourcing report
(`models/2026-09-17-new-data-sourcing-research.md`), approved first by Gabe
because it's zero-cost (classification data already on disk) and answers the
single most important open question post-Round-11: is there any idiosyncratic
stock-picking signal left, or is the model's edge entirely sector/size/vol
loading, as Round 13 already found for the raw fundamentals?

WHAT THIS IS
------------
For each of the 9 relativizable price/volume columns, subtract the
cross-sectional median WITHIN the ticker's industry group on that date:

    momentum_20_ind_rel = momentum_20 - median(momentum_20 | sicsector, date)

This is the standard way factor research separates "which sector to be in"
(beta, buy the ETF) from "which stock within the sector" (the only thing
worth an ML model). `daily_return` and `volume_ratio_20` are excluded --
daily_return is too short-horizon for a sector-relative read to mean much at
a 40-day hold, and volume_ratio_20 is already a within-ticker ratio (of a
stock's own volume to its own trailing average), not a level that sector
membership would confound the way momentum/vol/relative-strength levels are.

POINT-IN-TIME CAVEAT -- READ BEFORE TRUSTING A RESULT FROM THIS FAMILY
------------------------------------------------------------------------
The report's verdict on this item calls sector/industry classification
"clean" for point-in-time use, and in principle that's right -- a company's
sector is knowable in real time, no restatement risk. But the ACTUAL source
this repo has for it, `tickers_master.csv` (via `factors.load_sector_map`,
also what `taxonomy.py` and the app's Sector Bets tab use), is the CURRENT
classification, not a historically-tracked one. `factors.py`'s own Round 13
docstring already flags this as "a mild look-ahead of the same class as the
defects this project has already been burned by, even though the magnitude
is far smaller" -- true there because that neutralization was descriptive
only (residualizing a backtest's target, never trained on). Here the
classification feeds a features that get TRAINED ON, which is a higher bar.

Mitigation, matching Round 13's own sensitivity check: use `sicsector` (SIC
code, assigned at FILING time) rather than the more mutable GICS-style
`sector` -- `factors.py` characterizes `sicsector` as "assigned at filing
time and stickier." This does not make the join fully point-in-time (a
ticker's CURRENT sicsector is still used for its entire 2007-2026 history),
but it bounds the exposure to genuine industry reclassifications, which are
rare, rather than the more frequent GICS-style re-sorting. If any candidate
here clears the shuffle-null gate, re-run it with `scheme="sector"` before
trusting the result -- if the two schemes disagree materially, the
look-ahead is not "far smaller" for that particular column and the result
should not be believed without a genuinely point-in-time classification
history (not currently on disk).
"""
import numpy as np
import pandas as pd

from sweep.factors import load_sector_map, _base_ticker

NEUTRALIZE_COLS = [
    "momentum_5", "momentum_20", "momentum_60", "momentum_120",
    "volatility_20", "volatility_60",
    "relative_strength_20",
    "pct_from_high_252", "pct_from_low_252",
]
SECTOR_NEUTRAL_ALL = [f"{c}_ind_rel" for c in NEUTRALIZE_COLS]


def add_sector_neutral_columns(df, scheme="sicsector"):
    """Returns a COPY of df with the `_ind_rel` columns added.

    Group key is (date, industry). A ticker with no classification gets NaN
    in every new column rather than being folded into an "unclassified"
    group, which would otherwise average together companies that have
    nothing in common except a missing label.
    """
    smap = load_sector_map(scheme=scheme)
    ind = df["ticker"].map(lambda t: smap.get(_base_ticker(t)))
    out = df.copy()
    gb = out.groupby([out["date"].values, ind.values])
    for c in NEUTRALIZE_COLS:
        med = gb[c].transform("median")
        out[f"{c}_ind_rel"] = out[c] - med
        out.loc[ind.isna(), f"{c}_ind_rel"] = np.nan
    return out
