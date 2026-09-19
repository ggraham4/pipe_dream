"""
Factor attribution -- is the winning cell skill, or is it beta?

Round 12 (2026-09-09), written after the first nomination-era sweep returned a
2.94x compounded ratio from a cell whose mean IC is 0.0020 (t = 0.09).

The problem this exists to solve
--------------------------------
The construction-matched null (S4) re-runs a config with the rankings shuffled
within each date. That controls for breadth, weighting, stops, bucketing and
tranching -- everything about HOW the book is built. It does not control for
WHAT the book is tilted toward.

A shuffled ranking picks names with average beta and average volatility. The
real ranking picks whatever the model systematically prefers -- and
`factor_probe.py` already established that this model approximates "top 5 by
volatility_60", a book with beta 1.79 on the vol_high factor. Over 2009-2019,
a high-beta tilt earns a large excess return with no selection skill
whatsoever, and S4 will score it at the 100th percentile of its own null.

So S4 answers "did the scores beat a coin flip under this construction?" when
the question that decides the round is "did the scores beat a coin flip that
carried the same factor exposure?" This module asks the second one.

Factors
-------
All built from the SAME eligible pool, the SAME dates and the SAME realized
outcomes as the portfolio being tested, so a regression against them is
apples-to-apples rather than against an external index with its own universe.

  spy        SPY over the matched holding window
  univ       equal-weight ALL eligible names -- the pool's own return. The
             gates already record that this underperforms SPY, so separating
             it from SPY separates "the pool" from "the picks".
  volhi      equal-weight top volatility_60 quintile of the eligible pool
  vollo      equal-weight bottom volatility_60 quintile
  volspread  volhi - vollo, the tradable long-volatility factor

An alpha that survives regression on these is selection. One that does not is
a factor bet that could have been had for free, without a model.
"""

import numpy as np
import pandas as pd

from sweep import portfolio as P


# --------------------------------------------------------------------------
# Factor construction
# --------------------------------------------------------------------------
def factor_returns(prep, era=None, q=0.2):
    """Per-window returns of the reference factors, on the prepared panel."""
    rows = []
    for tp, d in prep.g.items():
        t = pd.Timestamp(tp)
        if era is not None and not (pd.Timestamp(era[0]) <= t < pd.Timestamp(era[1])):
            continue
        ok = d["tradable"] & np.isfinite(d["ret"])
        if ok.sum() < 40:
            continue
        r, v = d["ret"][ok], d["vol"][ok]
        rec = {"timepoint": t, "univ": float(r.mean()), "n": int(ok.sum())}
        fv = np.isfinite(v)
        if fv.sum() >= 40:
            hi = np.nanquantile(v[fv], 1.0 - q)
            lo = np.nanquantile(v[fv], q)
            mh, ml = fv & (v >= hi), fv & (v <= lo)
            rec["volhi"] = float(r[mh].mean()) if mh.any() else np.nan
            rec["vollo"] = float(r[ml].mean()) if ml.any() else np.nan
            rec["volspread"] = rec["volhi"] - rec["vollo"]
        rows.append(rec)
    return pd.DataFrame(rows).set_index("timepoint").sort_index()


# --------------------------------------------------------------------------
# Regression
# --------------------------------------------------------------------------
def _ols(y, X, names):
    """OLS with an intercept. Returns coefficients, t-stats, R^2."""
    n = len(y)
    A = np.column_stack([np.ones(n)] + [X[:, i] for i in range(X.shape[1])])
    beta, *_ = np.linalg.lstsq(A, y, rcond=None)
    resid = y - A @ beta
    dof = max(n - A.shape[1], 1)
    s2 = float(resid @ resid) / dof
    try:
        cov = s2 * np.linalg.inv(A.T @ A)
        se = np.sqrt(np.diag(cov))
    except np.linalg.LinAlgError:
        se = np.full(len(beta), np.nan)
    with np.errstate(divide="ignore", invalid="ignore"):
        t = beta / se
    ss_tot = float(((y - y.mean()) ** 2).sum())
    r2 = 1.0 - float(resid @ resid) / ss_tot if ss_tot > 0 else np.nan
    return (dict(zip(["alpha"] + names, beta)),
            dict(zip(["alpha"] + names, t)), r2, n)


def attribute(port_returns, timepoints, spy_ret, factors, era=None):
    """Regress a portfolio's per-window returns on the reference factors.

    Runs a ladder of nested models so it is visible which factor kills the
    alpha, rather than only reporting the final one.
    """
    idx = pd.Index([pd.Timestamp(t) for t in timepoints], name="timepoint")
    y = pd.Series(np.asarray(port_returns, dtype=np.float64), index=idx)
    df = pd.DataFrame({"y": y})
    df["spy"] = [spy_ret.get(t, np.nan) for t in idx]
    for c in ("univ", "volhi", "vollo", "volspread"):
        if c in factors.columns:
            df[c] = factors[c].reindex(idx).to_numpy()
    if era is not None:
        df = df[(df.index >= pd.Timestamp(era[0])) & (df.index < pd.Timestamp(era[1]))]
    df = df.dropna()
    if len(df) < 12:
        return {"error": f"only {len(df)} usable windows"}

    yv = df["y"].to_numpy()
    out = {"n_windows": len(df), "mean_return": float(yv.mean()),
           "models": {}}
    ladder = [("raw", []), ("vs SPY", ["spy"]), ("vs universe", ["univ"]),
              ("vs SPY+univ", ["spy", "univ"]),
              ("vs SPY+volspread", ["spy", "volspread"]),
              ("vs SPY+univ+volspread", ["spy", "univ", "volspread"])]
    for label, cols in ladder:
        cols = [c for c in cols if c in df.columns]
        if cols:
            b, t, r2, n = _ols(yv, df[cols].to_numpy(), cols)
        else:
            se = yv.std(ddof=1) / np.sqrt(len(yv))
            b = {"alpha": float(yv.mean())}
            t = {"alpha": float(yv.mean() / se) if se > 0 else np.nan}
            r2, n = 0.0, len(yv)
        out["models"][label] = {"coef": {k: float(v) for k, v in b.items()},
                                "t": {k: float(v) for k, v in t.items()},
                                "r2": float(r2)}
    return out


# --------------------------------------------------------------------------
# What is the book actually holding?
# --------------------------------------------------------------------------
def exposure_profile(prep, era=None, **pick_kwargs):
    """Where the selected names sit in the pool's volatility and size
    distribution. A characteristic tilt shows up here directly, without any
    regression to argue about."""
    top_n = pick_kwargs.get("top_n", 5)
    bucket = pick_kwargs.get("bucket", "none")
    vp, cp, n = [], [], 0
    for tp, d in prep.g.items():
        t = pd.Timestamp(tp)
        if era is not None and not (pd.Timestamp(era[0]) <= t < pd.Timestamp(era[1])):
            continue
        idx = P._pick_idx(d, top_n, bucket)
        if not len(idx):
            continue
        for src, acc in (("vol", vp), ("cap", cp)):
            v = d[src]
            fv = np.isfinite(v)
            if fv.sum() < 20:
                continue
            ranks = np.searchsorted(np.sort(v[fv]), v[idx]) / max(fv.sum(), 1)
            ranks = ranks[np.isfinite(v[idx])]
            if len(ranks):
                acc.append(float(ranks.mean()))
        n += 1
    return {
        "n_windows": n,
        "mean_vol_percentile": float(np.mean(vp)) if vp else np.nan,
        "mean_cap_percentile": float(np.mean(cp)) if cp else np.nan,
    }


# --------------------------------------------------------------------------
# Cluster-robust version of the grid consistency statistic
# --------------------------------------------------------------------------
def clustered_consistency(results_df, cell_col="cell_id",
                          pct_col="null_pctile", thresh=0.95, null_rate=0.05):
    """Recompute the grid consistency test treating each SIGNAL cell as one
    independent unit.

    `stats.summarize_grid` computes a binomial z over every cell in the grid.
    That assumes 1,152 independent trials. They are not: 48 portfolio configs
    share one score vector, so their results are near-perfectly correlated, and
    the binomial z is inflated by roughly the square root of the cluster size.

    Clustering on the signal cell is the honest unit of replication. A
    pre-registered threshold that passes only under the inflated version has
    not been met.
    """
    if pct_col not in results_df.columns:
        return {"error": f"no '{pct_col}' column -- this results file was "
                         "written by a run with --null-draws 0, which computes "
                         "no matched null. Re-run `portfolio` with "
                         "--null-draws 100 to regenerate it."}
    d = results_df.dropna(subset=[pct_col])
    if d.empty:
        return {"error": "no null percentiles"}
    per = d.groupby(cell_col)[pct_col].apply(lambda s: float((s > thresh).mean()))
    k = len(per)
    p_hat = float(d[pct_col].gt(thresh).mean())
    naive_n = len(d)
    naive_z = ((p_hat - null_rate) /
               np.sqrt(null_rate * (1 - null_rate) / naive_n))
    se_cluster = per.std(ddof=1) / np.sqrt(k) if k > 1 else np.nan
    z_cluster = (per.mean() - null_rate) / se_cluster if se_cluster and se_cluster > 0 else np.nan
    return {
        "n_rows": naive_n,
        "n_clusters": k,
        "frac_above_p95": p_hat,
        "naive_z": float(naive_z),
        "cluster_mean_frac": float(per.mean()),
        "cluster_sd": float(per.std(ddof=1)) if k > 1 else np.nan,
        "z_clustered": float(z_cluster) if np.isfinite(z_cluster) else np.nan,
        "inflation_factor": float(naive_z / z_cluster) if z_cluster and np.isfinite(z_cluster) and z_cluster != 0 else np.nan,
        "cells_with_zero": int((per == 0).sum()),
        "cells_above_half": int((per > 0.5).sum()),
    }


# --------------------------------------------------------------------------
# The decisive test: what does t(alpha) look like when the ranking is noise?
# --------------------------------------------------------------------------
def null_attribution(prep, spy_ret, factors, horizon, era=None, n_draws=200,
                     seed=23, model="vs SPY+univ+volspread", **cfg):
    """Distribution of alpha and t(alpha) under shuffled rankings.

    This is the test the first pass was missing. A regression alpha of
    t = 3.29 sounds decisive until you remember it is the t-stat of the single
    best of 1,152 searched configurations, computed on 82 windows. The
    selection is not in the t-stat.

    So: hold the construction, the universe, the dates and the factor
    regression exactly fixed, replace the ranking with noise, and read off the
    null distribution of t(alpha) directly. No asymptotic argument, no
    independence assumption -- the same permutation the S4 null uses, carried
    all the way through the factor regression instead of stopping at the
    compounded ratio.

    If shuffled rankings routinely produce t(alpha) near 3, the observed 3.29
    is the maximum of a noise distribution and means nothing.
    """
    rng = np.random.default_rng(seed)
    alphas, tstats, ratios = [], [], []
    for _ in range(n_draws):
        pw = P.simulate(prep.permuted(rng), horizon=horizon, **cfg)
        if pw.empty:
            continue
        book = pw.groupby("timepoint")[["net"]].mean().sort_index()
        if era is not None:
            book = book[(book.index >= pd.Timestamp(era[0])) &
                        (book.index < pd.Timestamp(era[1]))]
        if len(book) < 12:
            continue
        att = attribute(book["net"].to_numpy(), book.index, spy_ret, factors,
                        era=era)
        if "error" in att or model not in att["models"]:
            continue
        mm = att["models"][model]
        alphas.append(mm["coef"]["alpha"])
        tstats.append(mm["t"]["alpha"])
    if not tstats:
        return {"n": 0}
    a, t = np.asarray(alphas), np.asarray(tstats)
    return {
        "n": len(t), "model": model,
        "t_alpha_p50": float(np.percentile(t, 50)),
        "t_alpha_p90": float(np.percentile(t, 90)),
        "t_alpha_p95": float(np.percentile(t, 95)),
        "t_alpha_p99": float(np.percentile(t, 99)),
        "t_alpha_max": float(t.max()),
        "alpha_p95_pct_per_window": float(np.percentile(a, 95) * 100),
        "_t": t,
    }


def window_concentration(returns, timepoints, spy_ret, factors, era=None,
                         model="vs SPY+univ+volspread", drop=(1, 3, 5)):
    """How much of the alpha rests on a handful of windows.

    82 observations is not many, and this project's own history is a study in
    results carried by a few extreme outcomes ("terminal value is decided by a
    handful of extreme outcomes" -- validation-gates.md, process rule 4). If
    t(alpha) collapses when the best three windows are removed, the alpha is
    those three windows.
    """
    r = np.asarray(returns, dtype=np.float64)
    idx = pd.Index([pd.Timestamp(t) for t in timepoints])
    base = attribute(r, idx, spy_ret, factors, era=era)
    out = {"full": {"t_alpha": base["models"][model]["t"]["alpha"],
                    "alpha": base["models"][model]["coef"]["alpha"],
                    "n": base["n_windows"]}}
    order = np.argsort(-r)
    for k in drop:
        keep = np.ones(len(r), dtype=bool)
        keep[order[:k]] = False
        a = attribute(r[keep], idx[keep], spy_ret, factors, era=era)
        if "error" in a:
            continue
        out[f"drop_best_{k}"] = {"t_alpha": a["models"][model]["t"]["alpha"],
                                 "alpha": a["models"][model]["coef"]["alpha"],
                                 "n": a["n_windows"]}
    top = np.sort(r)[::-1]
    tot = float(np.sum(r))
    out["share_of_total_return"] = {
        "best_1": float(top[0] / tot) if tot else np.nan,
        "best_3": float(top[:3].sum() / tot) if tot else np.nan,
        "best_5": float(top[:5].sum() / tot) if tot else np.nan,
    }
    out["skew"] = float(pd.Series(r).skew())
    return out
