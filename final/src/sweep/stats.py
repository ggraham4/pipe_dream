"""
The statistics that decide whether a sweep result means anything.

Round 12 (2026-09-09).

The problem this file exists to solve
-------------------------------------
`validation-gates.md` already states it: "~40 backtest variants, 17 stop
levels, 4 horizons, 2 model families, 2 label designs, 14 universe screens, 3
gap modes. Under that search a nominal p < 0.05 is worthless."

This sweep is much larger than that. Run wide enough, the best cell in ANY
grid looks good -- that is what the maximum of a noise distribution does. So
the best cell's raw number is not evidence and is never reported alone. Three
things are reported with it:

  1. DEFLATED SHARPE RATIO -- Bailey & Lopez de Prado (2014). Discounts the
     selected Sharpe by the number of trials, the dispersion across trials,
     and the non-normality of the returns. Answers: given that we ran N
     configs, how surprising is the best one?

  2. REALITY CHECK -- White (2000), stationary-bootstrap form. Resamples the
     whole grid's excess-return series jointly and asks how often the best
     bootstrap cell beats the best observed cell. Preserves the cross-cell
     correlation that DSR's independence assumption ignores.

  3. MATCHED RANDOM-SELECTION NULL -- the project's own B2 tail test, applied
     per cell. Draws the same number of names, from the same eligible pool,
     under the SAME portfolio construction, and scores them the same way.

(3) is the one that stops the most likely false positive here. Tranching,
breadth and vol-targeting all improve compounded results with no signal at
all -- they cut variance drag. Without a construction-matched null, a config
that "beats the market" because it holds 50 names instead of 5 would be
credited to the model. The matched null strips that out: what is left is what
the SCORES contributed, over and above the construction.
"""

import numpy as np
import pandas as pd

from sweep import _num

EULER = 0.5772156649015329


# ==========================================================================
# Deflated Sharpe Ratio
# ==========================================================================
def expected_max_sharpe(n_trials, trial_sharpe_var):
    """E[max SR] across n independent trials whose SRs have the given variance.

    Bailey & Lopez de Prado (2014), eq. for the expected maximum of n draws
    from a standard normal, scaled by the observed dispersion of trial SRs.
    Both SR and the variance are PER-OBSERVATION, not annualized.
    """
    if n_trials < 2 or not np.isfinite(trial_sharpe_var) or trial_sharpe_var <= 0:
        return 0.0
    n = float(n_trials)
    a = _num.norm_ppf(1.0 - 1.0 / n)
    b = _num.norm_ppf(1.0 - 1.0 / (n * np.e))
    return float(np.sqrt(trial_sharpe_var) * ((1.0 - EULER) * a + EULER * b))


def deflated_sharpe(returns, n_trials, trial_sharpe_var, benchmark_sr=None):
    """Probability that the observed Sharpe exceeds what the search alone
    would produce.

    returns : the SELECTED strategy's per-period return series (excess over
              the benchmark, if the benchmark is what you are testing against).
    Returns a dict; 'dsr' is the probability. Below ~0.95 the result is not
    distinguishable from the best of N noise draws.
    """
    r = np.asarray(returns, dtype=np.float64)
    r = r[np.isfinite(r)]
    T = len(r)
    if T < 8:
        return {"dsr": np.nan, "sr": np.nan, "sr0": np.nan, "T": T}
    sd = r.std(ddof=1)
    if sd <= 0:
        return {"dsr": np.nan, "sr": np.nan, "sr0": np.nan, "T": T}

    sr = r.mean() / sd
    sr0 = benchmark_sr if benchmark_sr is not None else \
        expected_max_sharpe(n_trials, trial_sharpe_var)

    g3 = float(_num.skew(r))
    g4 = float(_num.kurtosis(r))
    denom = 1.0 - g3 * sr + ((g4 - 1.0) / 4.0) * sr ** 2
    if denom <= 0:
        return {"dsr": np.nan, "sr": sr, "sr0": sr0, "T": T}

    z = (sr - sr0) * np.sqrt(T - 1.0) / np.sqrt(denom)
    return {"dsr": float(_num.norm_cdf(z)), "sr": float(sr), "sr0": float(sr0),
            "T": T, "skew": g3, "kurt": g4, "z": float(z)}


# ==========================================================================
# White's Reality Check (stationary bootstrap)
# ==========================================================================
def reality_check(excess_matrix, n_boot=2000, block=4, seed=0):
    """White (2000) Reality Check over a grid of strategies.

    excess_matrix : (T, K) array -- each column one config's per-period excess
                    return over the benchmark, aligned on the same periods.

    Returns the bootstrap p-value for the null that NO config has positive
    expected excess return. Small p = the best cell is unlikely to be the best
    of K noise series.

    Uses a circular block bootstrap so serial dependence and, more importantly,
    the correlation ACROSS configs (they share the same windows and mostly the
    same names) is preserved -- that correlation is why a naive Bonferroni over
    K is far too conservative here and a raw p is far too liberal.
    """
    X = np.asarray(excess_matrix, dtype=np.float64)
    if X.ndim != 2 or X.shape[0] < 8 or X.shape[1] < 1:
        return {"p_value": np.nan, "V": np.nan, "K": 0}
    T, K = X.shape
    mu = X.mean(axis=0)
    V = float(np.sqrt(T) * mu.max())

    rng = np.random.default_rng(seed)
    n_blocks = int(np.ceil(T / block))
    stats = np.empty(n_boot)
    for i in range(n_boot):
        starts = rng.integers(0, T, size=n_blocks)
        idx = ((starts[:, None] + np.arange(block)[None, :]) % T).ravel()[:T]
        Xb = X[idx]
        stats[i] = np.sqrt(T) * (Xb.mean(axis=0) - mu).max()

    return {"p_value": float((stats >= V).mean()), "V": V, "K": K,
            "boot_mean": float(stats.mean()), "boot_p95": float(np.percentile(stats, 95))}


# ==========================================================================
# Matched random-selection null -- the construction-controlled test
# ==========================================================================
def random_selection_null(prep, sim_fn, score_fn, spy_ret, n_draws=200,
                          seed=0, **sim_kwargs):
    """Re-run the SAME portfolio construction with randomly chosen names.

    Everything is held fixed -- breadth, weighting, stop, cost, tranching,
    vol-target, and the eligible pool at each date -- and only the ranking is
    replaced by noise. The percentile of the real config within this
    distribution is the honest statement of what the SCORES bought, separately
    from what the CONSTRUCTION bought.

    Without this control a config that "beats the market" by holding 50 names
    instead of 5 gets credited to the model, when all it did was stop losing
    to variance drag.
    """
    rng = np.random.default_rng(seed)
    mults, excess = [], []
    for _ in range(n_draws):
        pw = sim_fn(prep.permuted(rng), **sim_kwargs)
        m = score_fn(pw, spy_ret)
        if m is None:
            continue
        mults.append(m["mult_ratio"])
        excess.append(m["excess_cagr"])
    if not mults:
        return {"n": 0, "_null_mults": np.array([])}
    a = np.asarray(mults, dtype=np.float64)
    e = np.asarray(excess, dtype=np.float64)
    return {
        "n": len(a),
        "null_mult_ratio_mean": float(np.nanmean(a)),
        "null_mult_ratio_p50": float(np.nanpercentile(a, 50)),
        "null_mult_ratio_p95": float(np.nanpercentile(a, 95)),
        "null_mult_ratio_p99": float(np.nanpercentile(a, 99)),
        "null_excess_cagr_p95": float(np.nanpercentile(e, 95)),
        "_null_mults": a,
    }


def percentile_of(value, null_array):
    a = np.asarray(null_array, dtype=np.float64)
    a = a[np.isfinite(a)]
    if not len(a) or not np.isfinite(value):
        return np.nan
    return float((a < value).mean())


# ==========================================================================
# Grid-level summary
# ==========================================================================
def summarize_grid(results, metric="mult_ratio", returns_key="_returns",
                   selection_trials=None):
    """Given every cell's metrics, produce the grid-level verdict.

    `results` : list of dicts, each with the metric and a per-period excess
                return series under `returns_key`.

    The distribution matters more than the maximum. If the best cell sits
    inside the bulk of the grid rather than out in its tail, the grid found
    nothing and the best cell is just the top of a noise distribution -- which
    is exactly the reading this file exists to force.
    """
    rows = [r for r in results if r and np.isfinite(r.get(metric, np.nan))]
    if not rows:
        return {"n_cells": 0}

    vals = np.array([r[metric] for r in rows], dtype=np.float64)
    best_i = int(np.argmax(vals))
    best = rows[best_i]

    # per-observation Sharpes across the grid, for the DSR variance term
    srs = []
    for r in rows:
        x = np.asarray(r.get(returns_key, []), dtype=np.float64)
        x = x[np.isfinite(x)]
        if len(x) > 2 and x.std(ddof=1) > 0:
            srs.append(x.mean() / x.std(ddof=1))
    sr_var = float(np.var(srs, ddof=1)) if len(srs) > 2 else np.nan

    # The deflation denominator must be the number of configurations the
    # winner was SELECTED from, which is not the number scored in THIS call.
    # Confirming one nominated config on the hold-out scores 1-4 cells but the
    # config came out of the full grid; deflating against 4 reports a pass it
    # has not earned. This bit the project once: a hold-out run printed
    # DSR 0.956 against 4 trials where the honest 1,152 gives 0.791.
    n_trials = int(selection_trials) if selection_trials else len(rows)
    best_ret = np.asarray(best.get(returns_key, []), dtype=np.float64)
    dsr = deflated_sharpe(best_ret, n_trials=n_trials, trial_sharpe_var=sr_var)
    dsr["n_trials_used"] = n_trials
    dsr["n_cells_scored"] = len(rows)
    if selection_trials and int(selection_trials) != len(rows):
        dsr["note"] = (f"deflated against {n_trials} SELECTION trials, not the "
                       f"{len(rows)} cells scored in this run")

    # ---- grid consistency against the construction-matched null ----------
    # Far higher-powered than any max-based test. Under the global null, the
    # fraction of cells sitting above the 95th percentile of their OWN matched
    # null is 5% by construction. If it comes back at 40%, something real is
    # present across the grid -- and that conclusion does not depend on which
    # single cell happened to top the table, which is the part of a max
    # statistic that cannot be trusted.
    pct = np.array([r.get("null_pctile", np.nan) for r in rows], dtype=np.float64)
    have_null = np.isfinite(pct)
    consistency = {}
    if have_null.any():
        k = int(have_null.sum())
        above95 = float((pct[have_null] > 0.95).mean())
        above50 = float((pct[have_null] > 0.50).mean())
        # binomial tail for the observed count of cells above p95, under 5%
        n_above = int((pct[have_null] > 0.95).sum())
        mu, sd = 0.05 * k, np.sqrt(0.05 * 0.95 * k)
        consistency = {
            "cells_with_null": k,
            "frac_above_null_p95": above95,
            "expected_under_null": 0.05,
            "n_above_p95": n_above,
            "z_vs_binomial": float((n_above - mu) / sd) if sd > 0 else np.nan,
            "frac_above_null_median": above50,
            "median_null_pctile": float(np.nanmedian(pct[have_null])),
        }

    return {
        "n_cells": len(rows),
        "metric": metric,
        "consistency": consistency,
        "best_value": float(vals[best_i]),
        "best_cell": best.get("cell_id"),
        "grid_mean": float(vals.mean()),
        "grid_median": float(np.median(vals)),
        "grid_p95": float(np.percentile(vals, 95)),
        "grid_max": float(vals.max()),
        "n_beating_1x": int((vals > 1.0).sum()),
        "frac_beating_1x": float((vals > 1.0).mean()),
        "trial_sharpe_var": sr_var,
        "deflated": dsr,
    }
