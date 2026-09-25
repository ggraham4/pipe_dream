"""
Per-feature information coefficient -- the floor the sweep is missing.

Round 12 (2026-09-09).

Why this belongs in the sweep and not in a side script
------------------------------------------------------
Nothing in this project has ever measured what each individual feature column
is worth on its own. `factor_probe.py` tests features as PORTFOLIOS (top 5 by
volatility_60, top 5 by momentum_20), which conflates the signal with a 5-name
book's variance. `gates_b4_b6.py` measures the IC of the MODEL SCORE. The
simplest question -- what is each of the 24 columns' own rank-IC against
forward return -- has no answer on record.

That gap makes the sweep hard to read. If the best of 1,296 cells comes back
at IC 0.015, there is currently no way to tell whether the model found
something or whether one raw column was already at 0.015 and the model is just
transmitting it. This supplies that floor.

It also answers the horizon question independently of XGBoost. The 40-day
default was chosen because XGBoost preferred it (models/final-buy-no-buy-
model.md); measuring each feature's IC at 10/20/40/60 says what horizon the
DATA prefers, with no model in the loop at all.

What this is NOT
----------------
**Not a trial.** These are properties of the data, not candidate strategies,
so they do not enter the Deflated Sharpe denominator -- adding them there would
raise the bar the eventual winner must clear for no reason. The three `feat:`
cells that ARE pre-registered strategies stay in the Phase A grid and stay
counted.

The bookkeeping only changes if a feature gets PROMOTED to a strategy on the
strength of this screen. Selecting the best of 24 columns is a search over 24
alternatives and must be counted as such. `promotion_trial_count` in the output
records the number to use if that happens.

Multiple testing within the screen itself
-----------------------------------------
24 features x 4 horizons is 96 tests. At |t| > 2 roughly five of them come back
"significant" with nothing there.

The screen reports Benjamini-Hochberg q-values **within each horizon** (m = 24)
as `q_value_bh`. Correcting across all four horizons as one family (m = 96) is
stricter, and the CLI reports that too -- but it is over-conservative, because
the same feature at 10 and 20 days is not an independent test. The honest read
is that the truth lies between the two, and that the per-horizon permutation
null is the better-calibrated statistic than either.

That null shuffles the return ranks within each date, destroying the
cross-sectional pairing while preserving the pool, the date structure, the
feature values and the return distribution exactly.
"""

import numpy as np
import pandas as pd

import continuous_walkforward_pit as W
from features import FEATURE_COLS
from fundamentals_features_beta import FUNDAMENTAL_FEATURE_COLS

_NO_STALE = [c for c in FUNDAMENTAL_FEATURE_COLS if c != "fundamentals_age_days"]
ALL_FEATURES = list(FEATURE_COLS) + list(_NO_STALE)

MIN_NAMES = 20


# --------------------------------------------------------------------------
# Ranked-correlation machinery
# --------------------------------------------------------------------------
def _avg_ranks(a):
    """Average ranks (ties averaged) of a 1-D array, ignoring nothing.

    NaN handling is the caller's job -- see _ranked_matrix. Getting that wrong
    is not cosmetic: np.argsort sorts NaN LAST, so a naive rank would put every
    missing value at the TOP of the ordering. A fundamental column that is NaN
    for 4% of names would then look like a strong signal on exactly those
    names. That is a manufactured IC, and it is the kind of error this project
    has already paid for twice.
    """
    a = np.asarray(a, dtype=np.float64)
    n = len(a)
    order = np.argsort(a, kind="stable")
    r = np.empty(n, dtype=np.float64)
    r[order] = np.arange(1, n + 1, dtype=np.float64)
    s = a[order]
    i = 0
    while i < n:
        j = i + 1
        while j < n and s[j] == s[i]:
            j += 1
        if j - i > 1:
            r[order[i:j]] = (i + 1 + j) / 2.0
        i = j
    return r


def _center_norm(r):
    r = r - r.mean()
    nrm = np.sqrt((r ** 2).sum())
    return r / nrm if nrm > 1e-12 else np.zeros_like(r)


def _ranked_matrix(X):
    """Column-wise centered/normalized ranks with NaN neutralized to zero.

    A NaN entry contributes exactly 0 to any dot product, so it neither helps
    nor hurts -- rather than being silently ranked best or worst. Returns the
    matrix and the per-column count of finite entries.
    """
    n, F = X.shape
    out = np.zeros((n, F), dtype=np.float64)
    counts = np.zeros(F, dtype=np.int64)
    for c in range(F):
        col = X[:, c]
        m = np.isfinite(col)
        k = int(m.sum())
        counts[c] = k
        if k < MIN_NAMES:
            continue
        out[m, c] = _center_norm(_avg_ranks(col[m]))
    return out, counts


def _pairwise_ic(X, y):
    """Exact pairwise-complete Spearman of every column of X against y.

    For a column with no missing values this is a dot product against the
    shared y-ranks. For a column with missing values BOTH sides are re-ranked
    on the intersection, because ranking y over the full cross-section and the
    feature over a subset compares two different orderings.
    """
    n, F = X.shape
    ok_y = np.isfinite(y)
    yr_full = np.zeros(n)
    yr_full[ok_y] = _center_norm(_avg_ranks(y[ok_y]))

    ic = np.full(F, np.nan)
    counts = np.zeros(F, dtype=np.int64)
    for c in range(F):
        m = np.isfinite(X[:, c]) & ok_y
        k = int(m.sum())
        counts[c] = k
        if k < MIN_NAMES:
            continue
        if k == int(ok_y.sum()):
            xr = np.zeros(n)
            xr[m] = _center_norm(_avg_ranks(X[m, c]))
            ic[c] = float(xr @ yr_full)
        else:
            xr = _center_norm(_avg_ranks(X[m, c]))
            yr = _center_norm(_avg_ranks(y[m]))
            ic[c] = float(xr @ yr)
    return ic, counts


def _bh_qvalues(p):
    """Benjamini-Hochberg FDR q-values."""
    p = np.asarray(p, dtype=np.float64)
    ok = np.isfinite(p)
    q = np.full_like(p, np.nan)
    if not ok.any():
        return q
    pv = p[ok]
    m = len(pv)
    order = np.argsort(pv)
    ranked = pv[order] * m / np.arange(1, m + 1)
    ranked = np.minimum.accumulate(ranked[::-1])[::-1]
    out = np.empty(m)
    out[order] = np.minimum(ranked, 1.0)
    q[ok] = out
    return q


def _two_sided_p(t):
    from sweep import _num
    if not np.isfinite(t):
        return np.nan
    return float(2.0 * (1.0 - _num.norm_cdf(abs(t))))


# --------------------------------------------------------------------------
# The screen
# --------------------------------------------------------------------------
def screen(ctx, features=None, start="2007-01-02", step=None, era=None,
           n_perm=200, seed=0, verbose=True, neutralize="none",
           sector_scheme="sector"):
    """Per-feature IC over the walk-forward timepoint grid.

    Uses the SAME point-in-time eligibility screen as every sweep cell
    (W.allowed_universe_at), so the pool a feature is measured on is the pool
    the model actually chooses from. Measuring IC over the full panel instead
    would include names no strategy could ever have bought.

    Returns (table, diagnostics).
    """
    _asked = list(features or ALL_FEATURES)
    feats = [c for c in _asked if c in ctx.feat.columns]
    if not feats:
        # Silent-failure guard. The filter above quietly drops any column the
        # panel context did not load, so a missing entry in PanelContext.want
        # yields an empty screen with no error -- which reads as "no signal"
        # rather than "nothing was measured". Name the columns instead.
        raise KeyError(
            f"none of the {len(_asked)} requested features are in the loaded "
            f"panel: {_asked[:6]}{' ...' if len(_asked) > 6 else ''}. "
            f"Add them to PanelContext's `want` list in scorecache.py.")
    if len(feats) < len(_asked) and verbose:
        print(f"    WARNING: {len(_asked) - len(feats)} requested feature(s) "
              f"absent from the panel: {sorted(set(_asked) - set(feats))}")
    horizon = int(ctx.horizon)
    step = int(step or horizon)
    f = ctx.feat
    dates_arr = f["date"].values
    step_dates = W.build_step_dates(ctx.all_dates, start, step)

    label = ctx.label_trd if ctx.label_trd in f.columns else ctx.label_pub
    Xall = f[feats].to_numpy(np.float32)
    yall = f[label].to_numpy(np.float32)

    # Factor neutralization of the TARGET. See sweep/factors.py for why this is
    # the discriminator between stock selection and a style bet, and why it
    # simultaneously buys statistical power.
    _neut = neutralize not in (None, "none")
    if _neut:
        from sweep import factors as FA
        smap = FA.load_sector_map(sector_scheme)
        capall = (f["market_cap"].to_numpy(np.float64)
                  if "market_cap" in f.columns else np.full(len(f), np.nan))
        volall = (f["volatility_60"].to_numpy(np.float64)
                  if "volatility_60" in f.columns else np.full(len(f), np.nan))
        tickall = f["ticker"].astype(str).to_numpy()
        var_removed = []

    rng = np.random.default_rng(seed)
    ic_rows, icb_rows, perm_rows, meta_rows = [], [], [], []
    cnt_sum = np.zeros(len(feats)); cnt_n = 0

    for n, tp in enumerate(step_dates, 1):
        if era is not None:
            t = pd.Timestamp(tp)
            if not (pd.Timestamp(era[0]) <= t < pd.Timestamp(era[1])):
                continue
        lo = int(np.searchsorted(dates_arr, np.datetime64(tp), "left"))
        hi = int(np.searchsorted(dates_arr, np.datetime64(tp), "right"))
        if hi <= lo:
            continue
        rows = f.iloc[lo:hi]
        allowed = W.allowed_universe_at(tp, ctx.current_universe,
                                        ctx.gap_earliest, ctx.universe,
                                        ctx.pit_map)
        sel = rows["ticker"].isin(allowed).to_numpy()
        pos = np.arange(lo, hi)[sel]
        if len(pos) < MIN_NAMES:
            continue

        X = Xall[pos].astype(np.float64)
        y = yall[pos].astype(np.float64)

        if _neut:
            D, _dn = FA.build_design(tickall[pos], capall[pos], volall[pos],
                                     spec=neutralize, sector_map=smap)
            vr = FA.variance_removed(y, D)
            if np.isfinite(vr):
                var_removed.append(vr)
            y = FA.residualize(y, D)

        resolved = np.isfinite(y)
        nr = int(resolved.sum())
        n_all = len(pos)
        if nr < MIN_NAMES:
            continue

        # PRIMARY -- pairwise-complete rank IC on names whose label resolved.
        ic, counts = _pairwise_ic(X, y)

        # WORST-CASE BOUND -- unresolved labels booked at the bottom of the
        # return ranking. An unresolved label overwhelmingly means the series
        # ended inside the holding window, i.e. the name was delisted or blew
        # up. Dropping those is the standard convention and is also the exact
        # shape of the survivorship hole Round 11 dug out, so the bound is
        # carried alongside every point estimate rather than trusted away.
        ybound = np.where(resolved, y, float(np.min(y[resolved])) - 1.0)
        icb, _ = _pairwise_ic(X, ybound)

        ic_rows.append(ic)
        icb_rows.append(icb)
        cnt_sum += counts; cnt_n += 1
        meta_rows.append({"timepoint": pd.Timestamp(tp), "n_all": n_all,
                          "n_resolved": nr,
                          "frac_unresolved": 1.0 - nr / n_all})

        # PERMUTATION NULL -- shuffle the return ranks within the date, which
        # is equivalent to shuffling each feature within the date. Pool, size,
        # feature values and return distribution all survive; only the pairing
        # dies. Calibrates the scale of the MAXIMUM |t| across features, which
        # is the number the eye goes to.
        if n_perm:
            Xr, _ = _ranked_matrix(X)
            yr = np.zeros(n_all)
            yr[resolved] = _center_norm(_avg_ranks(y[resolved]))
            base = yr[resolved]
            Yp = np.zeros((n_all, n_perm))
            for r in range(n_perm):
                Yp[resolved, r] = base[rng.permutation(nr)]
            perm_rows.append(Xr.T @ Yp)          # (F, n_perm)

        if verbose and (n % 20 == 0 or n == 1):
            print(f"    feature-IC {n}/{len(step_dates)} "
                  f"{pd.Timestamp(tp).date()} ({nr}/{n_all} resolved)",
                  flush=True)

    if not ic_rows:
        return pd.DataFrame(), {"error": "no windows"}

    IC = np.vstack(ic_rows)                       # (W, F)
    ICB = np.vstack(icb_rows)
    W_ = IC.shape[0]
    with np.errstate(divide="ignore", invalid="ignore"):
        mu = np.nanmean(IC, axis=0)
        sd = np.nanstd(IC, axis=0, ddof=1)
        t = np.where(sd > 0, mu / (sd / np.sqrt(W_)), np.nan)
    p = np.array([_two_sided_p(x) for x in t])

    tab = pd.DataFrame({
        "feature": feats,
        "mean_ic": mu,
        "t_stat": t,
        "p_value": p,
        "q_value_bh": _bh_qvalues(p),
        "ic_sd": sd,
        "frac_windows_positive": np.nanmean(IC > 0, axis=0),
        "mean_n_names": cnt_sum / max(cnt_n, 1),
        "mean_ic_worstcase": np.nanmean(ICB, axis=0),
        "n_windows": W_,
        "horizon": horizon,
    })

    diag = {
        "_ic_matrix": IC,
        "_timepoints": [m["timepoint"] for m in meta_rows],
        "_features": feats,
        "horizon": horizon,
        "step": step,
        "n_windows": W_,
        "n_features": len(feats),
        "era": era,
        "mean_frac_unresolved": float(np.mean([m["frac_unresolved"]
                                               for m in meta_rows])),
        "promotion_trial_count": len(feats),
        "neutralize": neutralize,
        "sector_scheme": sector_scheme if _neut else None,
        "mean_variance_removed": (float(np.mean(var_removed))
                                  if _neut and var_removed else None),
    }

    if perm_rows:
        # Null distribution of the MAXIMUM |t| across features -- the relevant
        # comparison, because the temptation is to read the top of the table.
        PERM = np.stack(perm_rows)                # (W, F, n_perm)
        with np.errstate(divide="ignore", invalid="ignore"):
            pm = PERM.mean(axis=0)                # (F, n_perm)
            ps = PERM.std(axis=0, ddof=1)
            pt = np.where(ps > 0, pm / (ps / np.sqrt(W_)), np.nan)
        if pt.size == 0 or not np.isfinite(pt).any():
            # every feature degenerate under permutation (all-NaN or constant
            # within every date) -- report it rather than crashing on an empty
            # reduction, which says nothing about what went wrong.
            print("    permutation null skipped: no finite t-statistics "
                  "(all screened features are constant or empty within dates)")
            return tab.sort_values("t_stat", key=np.abs, ascending=False), diag
        maxabs = np.nanmax(np.abs(pt), axis=0)   # max across features, per draw
        obs_max = float(np.nanmax(np.abs(t)))
        diag["permutation"] = {
            "n_perm": int(PERM.shape[2]),
            "observed_max_abs_t": obs_max,
            "null_max_abs_t_p50": float(np.nanpercentile(maxabs, 50)),
            "null_max_abs_t_p95": float(np.nanpercentile(maxabs, 95)),
            "p_value_of_max": float(np.nanmean(maxabs >= obs_max)),
        }

    # How many INDEPENDENT bets are in these columns? If every feature's IC
    # time series moves together, 24 features is one factor wearing 24 hats,
    # and no amount of model capacity or feature filtering changes that.
    # Constant / degenerate columns carry no IC series and would poison the
    # correlation structure with NaN; drop them from this diagnostic only.
    live = np.flatnonzero(np.isfinite(sd) & (sd > 0))
    with np.errstate(divide="ignore", invalid="ignore"):
        C = np.corrcoef(np.nan_to_num(IC[:, live], nan=0.0).T)
    C = np.atleast_2d(np.nan_to_num(C, nan=0.0))
    off = C[~np.eye(len(live), dtype=bool)] if len(live) > 1 else np.array([0.0])
    ev = np.linalg.eigvalsh(C)[::-1]
    ev = ev[ev > 0]
    diag["ic_correlation"] = {
        "n_live_features": int(len(live)),
        "mean_abs_offdiag": float(np.nanmean(np.abs(off))),
        "max_abs_offdiag": float(np.nanmax(np.abs(off))),
        "pc1_share": float(ev[0] / ev.sum()) if len(ev) else np.nan,
        "n_pcs_for_90pct": int(np.searchsorted(np.cumsum(ev) / ev.sum(), 0.90) + 1)
        if len(ev) else 0,
    }
    # If pc1_share is high and n_pcs_for_90pct is small, this feature set is a
    # handful of factors wearing many hats -- and no amount of model capacity,
    # feature filtering or extra columns changes that. It is the single most
    # useful number here for deciding whether the ceiling is the data.

    return tab.sort_values("t_stat", key=np.abs, ascending=False), diag
