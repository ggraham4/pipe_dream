"""
Small numerical helpers, implemented on numpy + the standard library.

Round 12 (2026-09-09).

Deliberately dependency-free. The sweep runs unattended overnight on a machine
whose environment has already bitten this project once -- `query_day.py` failed
locally because pyarrow was missing from the `pipe_dream` conda env
(models/final-buy-no-buy-model.md). Everything needed here is a few dozen lines
of numpy, so scipy and scikit-learn are not worth the risk of a run dying at
3am on an import.

`statistics.NormalDist` (stdlib, 3.8+) supplies the normal CDF and its inverse.
"""

from statistics import NormalDist

import numpy as np

_ND = NormalDist()


def norm_cdf(x):
    return _ND.cdf(float(x))


def norm_ppf(p):
    p = min(max(float(p), 1e-15), 1 - 1e-15)
    return _ND.inv_cdf(p)


def rankdata(a):
    """Average ranks, 1-based, ties averaged. Matches scipy.stats.rankdata."""
    a = np.asarray(a, dtype=np.float64)
    n = len(a)
    if n == 0:
        return np.array([], dtype=np.float64)
    order = np.argsort(a, kind="stable")
    ranks = np.empty(n, dtype=np.float64)
    ranks[order] = np.arange(1, n + 1, dtype=np.float64)
    # average over tie groups
    s = a[order]
    i = 0
    while i < n:
        j = i + 1
        while j < n and s[j] == s[i]:
            j += 1
        if j - i > 1:
            ranks[order[i:j]] = (i + 1 + j) / 2.0
        i = j
    return ranks


def spearman(x, y):
    """Spearman rank correlation. NaN when undefined."""
    x = np.asarray(x, dtype=np.float64)
    y = np.asarray(y, dtype=np.float64)
    m = np.isfinite(x) & np.isfinite(y)
    if m.sum() < 3:
        return np.nan
    rx, ry = rankdata(x[m]), rankdata(y[m])
    sx, sy = rx.std(), ry.std()
    if sx <= 0 or sy <= 0:
        return np.nan
    return float(((rx - rx.mean()) * (ry - ry.mean())).mean() / (sx * sy))


def skew(a):
    a = np.asarray(a, dtype=np.float64)
    a = a[np.isfinite(a)]
    if len(a) < 3:
        return np.nan
    sd = a.std()
    if sd <= 0:
        return np.nan
    return float((((a - a.mean()) / sd) ** 3).mean())


def kurtosis(a):
    """Non-Fisher (normal == 3.0), matching scipy's fisher=False."""
    a = np.asarray(a, dtype=np.float64)
    a = a[np.isfinite(a)]
    if len(a) < 4:
        return np.nan
    sd = a.std()
    if sd <= 0:
        return np.nan
    return float((((a - a.mean()) / sd) ** 4).mean())


def ridge_fit_predict(X_tr, y_tr, X_te, alpha=1.0):
    """Standardize, ridge-solve the normal equations, predict.

    Columns with no variance are held out rather than blowing up the solve,
    and NaNs are imputed to the training mean (i.e. to 0 after standardizing),
    which is the closest linear analogue to XGBoost's native NaN handling.
    """
    X_tr = np.asarray(X_tr, dtype=np.float64)
    X_te = np.asarray(X_te, dtype=np.float64)
    y = np.asarray(y_tr, dtype=np.float64)

    mu = np.nanmean(X_tr, axis=0)
    mu = np.where(np.isfinite(mu), mu, 0.0)
    sd = np.nanstd(X_tr, axis=0)
    sd = np.where(np.isfinite(sd) & (sd > 1e-12), sd, 1.0)

    Z = np.nan_to_num((X_tr - mu) / sd, nan=0.0, posinf=0.0, neginf=0.0)
    Zt = np.nan_to_num((X_te - mu) / sd, nan=0.0, posinf=0.0, neginf=0.0)

    ybar = y.mean()
    yc = y - ybar
    k = Z.shape[1]
    A = Z.T @ Z + alpha * np.eye(k)
    try:
        w = np.linalg.solve(A, Z.T @ yc)
    except np.linalg.LinAlgError:
        w = np.linalg.lstsq(A, Z.T @ yc, rcond=None)[0]
    return (Zt @ w + ybar).astype(np.float32)
