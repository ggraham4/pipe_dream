"""
Core, no-fit composite scoring + portfolio construction. See
PREREGISTRATION.md for the factor list, signs, and everything below is a
direct implementation of that spec -- read it first.

Deliberately imports `execution.py` from the MAIN checkout rather than
reimplementing position realization: that module is the project's single,
already-verified (`outcomes.py`'s 12,000-comparison gate) place a position is
turned into a return, entry lag / delisting exit floor / turnover-aware costs
included. Re-deriving that arithmetic here would risk quietly reintroducing
one of the bugs it was written to fix.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

MAIN_ROOT = Path("/Users/ggraham/pipe_dream/final")
MAIN_SRC = MAIN_ROOT / "src"
if str(MAIN_SRC) not in sys.path:
    sys.path.insert(0, str(MAIN_SRC))

from execution import (realize_position, realize_portfolio,  # noqa: E402
                        load_ohlc_panel, apply_turnover_costs,
                        DEFAULT_COST_BPS)

OHLC_DIR = MAIN_ROOT / "scripts" / "td_data_sharadar"
SPY_CSV = MAIN_ROOT / "scripts" / "td_data_local" / "SPY.csv"
USMV_CSV = MAIN_ROOT / "data" / "benchmarks" / "USMV.csv"

HORIZON = 40
ENTRY_LAG = 1
ENTRY_AT = "open"
STRESS_COST_BPS = 50.0

# ---------------------------------------------------------------------------
# Factors -- PREREGISTRATION.md section 2. Signs fixed here, once, before any
# score in this package is ever computed.
# ---------------------------------------------------------------------------
FACTOR_SIGNS = {
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
FACTOR_COLS = list(FACTOR_SIGNS)

TIERS = ("cap2000", "cap500", "cap150")
N_VOL_QUINTILES = 5


def rank_z(s: pd.Series) -> pd.Series:
    """Cross-sectional rank to [-0.5, +0.5]. NaN stays NaN. Constant/near-
    empty slices (n<2) return all-NaN rather than an arbitrary 0."""
    n = int(s.notna().sum())
    if n < 2:
        return pd.Series(np.nan, index=s.index)
    r = s.rank(method="average")
    return (r - 1.0) / (n - 1.0) - 0.5


def neutralize_on_sector(df: pd.DataFrame, factor_cols, sector_col="sector") -> pd.DataFrame:
    """OLS-residualize each factor cross-sectionally (this frame = one
    rebalance date's eligible universe) on sector dummies + intercept.

    See PREREGISTRATION.md's amendment: sector only, not size/vol -- vol is
    itself one of the factors, so residualizing it on itself is degenerate.
    """
    out = df.copy()
    sectors = pd.get_dummies(df[sector_col].fillna("Unknown"), prefix="sec", drop_first=True)
    X = np.column_stack([np.ones(len(df))] + [sectors[c].to_numpy(np.float64) for c in sectors.columns])
    for fc in factor_cols:
        y = df[fc].to_numpy(np.float64)
        mask = np.isfinite(y)
        resid = np.full(len(df), np.nan)
        if mask.sum() > X.shape[1] + 5:
            beta, *_ = np.linalg.lstsq(X[mask], y[mask], rcond=None)
            resid[mask] = y[mask] - X[mask] @ beta
        out[fc] = resid
    return out


def compute_composite(df_date: pd.DataFrame, neutral: bool) -> pd.DataFrame:
    """df_date: one rebalance date's eligible-universe rows, must carry
    `ticker`, `sector`, `volatility_60`, and all of FACTOR_COLS.

    Returns a frame indexed like df_date with columns `composite` (mean of
    available signed cross-sectional ranks; a name missing k of 9 factors is
    scored on the mean of what it has, not penalized structurally for
    missingness) and `coverage` (how many of the 9 factors were available).
    """
    work = neutralize_on_sector(df_date, FACTOR_COLS) if neutral else df_date
    scores = pd.DataFrame(index=df_date.index)
    for c in FACTOR_COLS:
        scores[c] = rank_z(work[c]) * FACTOR_SIGNS[c]
    out = pd.DataFrame(index=df_date.index)
    out["ticker"] = df_date["ticker"].values
    out["coverage"] = scores.notna().sum(axis=1).values
    out["composite"] = scores.mean(axis=1, skipna=True).values
    out.loc[out["coverage"] == 0, "composite"] = np.nan
    return out


def shuffle_composite(scored: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    """Matched null: permute `composite` across names WITHIN this date,
    same coverage pattern, cross-sectional pairing to factors destroyed.
    Same construction downstream (bucketing, weighting) as the real draw."""
    out = scored.copy()
    vals = out["composite"].to_numpy(copy=True)
    finite = np.isfinite(vals)
    perm = rng.permutation(np.flatnonzero(finite))
    shuffled = vals.copy()
    shuffled[finite] = vals[perm]
    out["composite"] = shuffled
    return out


def pick_decile_volq(df_date: pd.DataFrame, scored: pd.DataFrame, book_frac: float = 0.10):
    """Within each of N_VOL_QUINTILES trailing-volatility quintiles, take the
    top `book_frac` by composite score, inverse-vol weighted. Mirrors the
    deployed model's construction (decile within vol quintile) for direct
    comparability -- see RUNBOOK's `decile_volq_excess`.

    NaN volatility_60 is EXCLUDED from bucketing, never defaulted into
    bucket 0 -- the exact silent-failure mode Round 18 shipped and caught
    (`_bucket_idx`'s NaN-to-lowest-quintile behaviour).
    """
    vol = df_date["volatility_60"].to_numpy(np.float64)
    valid = np.isfinite(vol) & np.isfinite(scored["composite"].to_numpy(np.float64))
    if valid.sum() < N_VOL_QUINTILES * 4:
        return []
    idx = np.flatnonzero(valid)
    vol_v = vol[idx]
    q = pd.qcut(vol_v, N_VOL_QUINTILES, labels=False, duplicates="drop")
    comp_v = scored["composite"].to_numpy(np.float64)[idx]
    tick_v = scored["ticker"].to_numpy()[idx]
    picks = []
    for bucket in np.unique(q):
        bmask = q == bucket
        n_bucket = int(bmask.sum())
        k = max(1, int(round(n_bucket * book_frac)))
        b_idx = np.flatnonzero(bmask)
        order = b_idx[np.argsort(-comp_v[b_idx])][:k]
        for i in order:
            picks.append((tick_v[i], vol_v[i]))
    if not picks:
        return []
    inv_vol = np.array([1.0 / max(v, 1e-4) for _, v in picks])
    w = inv_vol / inv_vol.sum()
    return [(t, float(wi)) for (t, _), wi in zip(picks, w)]


def pick_topn_ew(df_date: pd.DataFrame, scored: pd.DataFrame, top_frac: float = 0.05):
    """Flat top `top_frac` of the eligible universe by composite score,
    equal-weighted. The check for whether decile_volq's result is variance-
    drag reduction rather than selection (PREREGISTRATION.md §4)."""
    comp = scored["composite"].to_numpy(np.float64)
    valid = np.isfinite(comp)
    n_valid = int(valid.sum())
    if n_valid < 5:
        return []
    k = max(1, int(round(n_valid * top_frac)))
    idx = np.flatnonzero(valid)
    order = idx[np.argsort(-comp[idx])][:k]
    tickers = scored["ticker"].to_numpy()[order]
    w = 1.0 / len(tickers)
    return [(t, w) for t in tickers]


def load_price_panels(tickers=None):
    """{ticker: DataFrame[date,open,high,low,close]} from the Sharadar
    per-ticker export -- the SAME corporate-action basis features were
    computed from. See PREREGISTRATION.md §5 amendment for why not
    td_data_local/td_data_delisted."""
    return load_ohlc_panel([OHLC_DIR], tickers=tickers)


def load_benchmark(path):
    df = pd.read_csv(path, usecols=["date", "open", "high", "low", "close"], parse_dates=["date"])
    return df.sort_values("date").reset_index(drop=True)


def realize_weighted_portfolio(picks_weighted, price_by_ticker, tp, horizon=HORIZON):
    """Like execution.realize_portfolio but with per-ticker WEIGHTS (inverse-
    vol for decile_volq, equal for topN_ew) rather than a flat equal weight.
    Re-derives the weighted sum from realize_position directly since
    realize_portfolio hardcodes equal weighting.

    Returns (portfolio_gross_return_or_None, {ticker: pos_dict}).
    """
    per_ticker = {}
    weights = {}
    for ticker, w in picks_weighted:
        g = price_by_ticker.get(ticker)
        if g is None or g.empty:
            continue
        pos = realize_position(g, tp, horizon, entry_lag=ENTRY_LAG, entry_at=ENTRY_AT,
                               stop_pct=None, cost_bps=0.0)
        if pos is not None:
            per_ticker[ticker] = pos
            weights[ticker] = w
    if not per_ticker:
        return None, per_ticker
    wsum = sum(weights.values())
    if wsum <= 0:
        return None, per_ticker
    gross = sum((weights[t] / wsum) * (1.0 + p["gross_return"]) for t, p in per_ticker.items()) - 1.0
    return float(gross), per_ticker


def make_results_record(tp, picks_weighted, per_ticker):
    tickers = list(per_ticker.keys())
    w = {t: wt for t, wt in picks_weighted}
    wsum = sum(w.get(t, 0.0) for t in tickers)
    gross = (sum((w.get(t, 0.0) / wsum) * (1.0 + p["gross_return"]) for t, p in per_ticker.items()) - 1.0
             if wsum > 0 else None)
    return {
        "timepoint": tp,
        "picks": tickers,
        "execution": {
            "per_ticker_gross": {t: p["gross_return"] for t, p in per_ticker.items()},
            "gross_return_pct": (gross * 100.0) if gross is not None else None,
        },
    }


def apply_costs(results, cost_bps):
    """Wrapper around execution.apply_turnover_costs that does not mutate
    the caller's list of dicts in place (that function does, and we want the
    same cached gross results scored at multiple cost levels)."""
    import copy
    seq = copy.deepcopy(results)
    return apply_turnover_costs(seq, cost_bps)
