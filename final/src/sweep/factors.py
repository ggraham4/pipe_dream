"""
Cross-sectional factor neutralization.

Round 13 (2026-09-11).

Why this is the decisive test
----------------------------
The per-feature IC screen found that the only columns carrying signal are
fundamentals, and that they all point the same way once you read their signs
together:

    pb_ratio          +    expensive beats cheap (the opposite of value)
    rnd_intensity     +    heavy R&D spenders beat the rest
    fcf_margin        -    cash-burning beats cash-generating
    operating_margin  -    low-margin beats high-margin

That is not four findings. It is one: buy expensive, cash-burning, R&D-heavy
companies -- the growth-over-value trade, measured across 2007-2019, which is
a single style regime from end to end. Splitting the era cannot separate them,
because both halves are the same regime; the periods that would discriminate
are before the panel starts or inside the sealed hold-out.

So neutralization is the only available discriminator. And it does double duty:

  1. INTERPRETATION. If the IC dies once sector, size and volatility are
     removed, the signal was a sector bet that an index gives away for free.
  2. POWER. If the IC survives, the residual has less common-factor variance,
     the per-window IC dispersion falls, and the t-statistic rises. Round 12
     measured an effective breadth of ~25 independent bets per window against a
     nominal 1,400; that gap is exactly the common-factor variance this removes.

One operation, both answers. That is why it runs before any model work.

What this is and is not
-----------------------
This residualizes the TARGET, which is the standard way to ask "does this
feature predict returns beyond what sector, size and volatility explain". The
factor returns are estimated from the realized cross-section at each date, so
this is a descriptive decomposition, not a tradable construction -- a tradable
version neutralizes the PORTFOLIO, not the label. The loadings themselves
(market cap, volatility, sector) are all known at the decision date, so nothing
here looks forward.

Declared limitation, carried from the pre-registration: `tickers_master.sector`
is the CURRENT classification, not point-in-time. A company's sector can change
(the 2018 Telecom -> Communication Services reclassification being the obvious
case), so using it for a 2008 decision is a mild look-ahead of the same class as
the defects this project has already been burned by, even though the magnitude
is far smaller. `sicsector` is assigned at filing time and is stickier; both are
exposed here and the comparison between them IS the sensitivity check.
"""

import csv
import functools

import numpy as np

from features import OUT_DIR

# Same anchor continuous_walkforward_pit.py uses for pit_universe.parquet --
# OUT_DIR.parent is `final/`, so this resolves to final/data/sharadar/.
# DATA_DIR.parent is `scripts/` and does NOT work here.
TICKERS_MASTER = OUT_DIR.parent / "data" / "sharadar" / "tickers_master.csv"

SCHEMES = ("sector", "sicsector", "famaindustry")

# Neutralization specs. The intercept is always present, and it IS the market
# factor -- removing a cross-sectional mean is exactly removing the equally
# weighted market return for that window.
SPECS = {
    "none": (),
    "market": (),                       # intercept only
    "size": ("size",),
    "vol": ("vol",),
    "size_vol": ("size", "vol"),
    "sector": ("sector",),
    "size_vol_sector": ("size", "vol", "sector"),
}


@functools.lru_cache(maxsize=8)
def load_sector_map(scheme="sector", path=None):
    """ticker -> sector label. Verified 100% join against the 4,011 panel
    tickers, with the label populated for 99.9% of delisted names -- which is
    the survivorship-critical set, and the reason this is usable at all."""
    if scheme not in SCHEMES:
        raise ValueError(f"scheme must be one of {SCHEMES}")
    out = {}
    with open(path or TICKERS_MASTER) as fh:
        for row in csv.DictReader(fh):
            v = (row.get(scheme) or "").strip()
            if v:
                out[row["ticker"]] = v
    return out


def _base_ticker(t):
    """Strip the segmentation suffix price_discontinuity.py adds. The two sides
    of a break are different securities for pricing, but they are the same
    company for a sector label."""
    s = str(t)
    return s.split("__post")[0] if "__post" in s else s


def _rank_centered(v):
    """Cross-sectional percentile rank, centered on zero. Rank rather than raw
    value so a single extreme market cap cannot dominate the regression."""
    v = np.asarray(v, dtype=np.float64)
    out = np.zeros(len(v))
    m = np.isfinite(v)
    k = int(m.sum())
    if k < 3:
        return out
    order = np.argsort(v[m], kind="stable")
    r = np.empty(k, dtype=np.float64)
    r[order] = np.arange(1, k + 1, dtype=np.float64)
    out[m] = r / (k + 1.0) - 0.5
    return out


def build_design(tickers, market_cap, vol, spec="size_vol_sector",
                 sector_map=None, min_per_sector=5):
    """Design matrix for one date's cross-section.

    Always includes an intercept (the market). Returns (X, column_names).
    Sector levels with fewer than `min_per_sector` names at this date are
    folded into the baseline rather than given their own dummy -- a two-name
    sector dummy fits those two names' returns exactly and would remove real
    residual variation.
    """
    parts = ["size", "vol", "sector"]
    want = SPECS.get(spec)
    if want is None:
        raise ValueError(f"spec must be one of {sorted(SPECS)}")
    n = len(tickers)
    cols, names = [np.ones(n)], ["intercept"]

    if "size" in want:
        with np.errstate(divide="ignore", invalid="ignore"):
            lm = np.log(np.where(np.asarray(market_cap, float) > 0,
                                 market_cap, np.nan))
        cols.append(_rank_centered(lm))
        names.append("size")
    if "vol" in want:
        cols.append(_rank_centered(vol))
        names.append("vol")
    if "sector" in want:
        smap = sector_map if sector_map is not None else load_sector_map()
        labs = np.array([smap.get(_base_ticker(t), "") for t in tickers])
        uniq, counts = np.unique(labs[labs != ""], return_counts=True)
        keep = [u for u, c in zip(uniq, counts) if c >= min_per_sector]
        # drop one level as the baseline; the intercept carries it
        for u in keep[1:]:
            cols.append((labs == u).astype(np.float64))
            names.append(f"sec::{u}")

    return np.column_stack(cols), names


def residualize(y, X):
    """Cross-sectional OLS residual, computed only over names with a finite y.

    Uses lstsq so a rank-deficient design (collinear sector dummies, a date
    where every name is one sector) degrades gracefully instead of raising.
    Names with a missing target come back NaN and stay excluded downstream --
    they are not silently imputed to zero, which would look like an average
    outcome for a name that usually stopped existing.
    """
    y = np.asarray(y, dtype=np.float64)
    out = np.full(len(y), np.nan)
    m = np.isfinite(y) & np.isfinite(X).all(axis=1)
    k = int(m.sum())
    if k < max(X.shape[1] + 5, 20):
        return out
    beta, *_ = np.linalg.lstsq(X[m], y[m], rcond=None)
    out[m] = y[m] - X[m] @ beta
    return out


def variance_removed(y, X):
    """Fraction of cross-sectional return variance the factors explain.

    Reported per date because it is the direct measure of how much of the
    cross-section was never the model's to predict. A high number is the
    quantitative form of "effective breadth is 25, not 1,400".
    """
    y = np.asarray(y, dtype=np.float64)
    m = np.isfinite(y) & np.isfinite(X).all(axis=1)
    if int(m.sum()) < max(X.shape[1] + 5, 20):
        return np.nan
    yv = y[m]
    ss_tot = float(((yv - yv.mean()) ** 2).sum())
    if ss_tot <= 0:
        return np.nan
    beta, *_ = np.linalg.lstsq(X[m], yv, rcond=None)
    resid = yv - X[m] @ beta
    return 1.0 - float(resid @ resid) / ss_tot
