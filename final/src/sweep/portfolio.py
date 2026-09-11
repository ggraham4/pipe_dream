"""
Portfolio sweep -- the cheap half. Hundreds of cells per minute.

Round 12 (2026-09-09).

Everything here is post-processing over a cached score cross-section
(`sweep/scorecache.py`) and a cached realized-outcomes table
(`sweep/outcomes.py`). No model is trained and no price file is re-read.

Why this half matters more than it looks
----------------------------------------
The current production config's arithmetic excess over SPY is -0.11% per
40-day window (t = -0.09) -- indistinguishable from zero. But its COMPOUNDED
result is 0.998x against SPY's 5.229x over the same span. That gap is not
alpha, it is variance: 17.3% per-window dispersion against SPY's 6.85%. A
5-name book with genuinely zero edge still ends up here.

So the parameters in this file -- breadth, weighting, vol-targeting,
tranching -- are not cosmetic tuning on top of a signal. On the evidence so
far they are the dominant term, and a sweep that only varied the signal would
be searching the wrong space.

Definitions used throughout
---------------------------
A "sleeve" holds a fixed set of names for `horizon` trading days, then
rebalances. When pick dates are spaced `step` < `horizon` apart, capital is
split across k = horizon/step sleeves offset from each other -- standard
tranching. Each sleeve compounds independently; portfolio equity is their
mean. This is the cheapest known way to cut timing luck without touching the
signal, which is exactly the problem the numbers above describe.
"""

import numpy as np
import pandas as pd
from sweep import outcomes as O
from sweep import _num

TRADING_DAYS = 252


# ==========================================================================
# Selection
# ==========================================================================
def _bucket_labels(df, scheme, n_buckets=5):
    """Bucket assignment for neutralized selection.

    'volq' and 'capq' rank within volatility / market-cap quantiles instead of
    across the whole cross-section. This tests the B6 ablation finding from
    the other side: the gates recorded that the edge lives only inside the top
    volatility decile. If ranking WITHIN volatility buckets preserves it, the
    signal is doing something beyond selecting volatile names. If it vanishes,
    that settles it.
    """
    if scheme == "none":
        return np.zeros(len(df), dtype=np.int16)
    col = {"volq": "volatility_60", "capq": "market_cap"}[scheme]
    v = df[col].to_numpy(np.float64)
    ok = np.isfinite(v)
    out = np.full(len(df), -1, dtype=np.int16)
    if ok.sum() < n_buckets * 4:
        return np.zeros(len(df), dtype=np.int16)
    edges = np.nanpercentile(v[ok], np.linspace(0, 100, n_buckets + 1)[1:-1])
    out[ok] = np.searchsorted(edges, v[ok], side="right").astype(np.int16)
    out[~ok] = 0
    return out


def select(df, top_n, bucket="none", n_buckets=5):
    """Pick top_n names by score, optionally per bucket.

    With bucketing, top_n is split as evenly as possible across buckets, so
    total breadth is held constant and the comparison against unbucketed
    selection is like-for-like.
    """
    if bucket == "none":
        return df.nlargest(top_n, "score")
    b = _bucket_labels(df, bucket, n_buckets)
    df = df.assign(_b=b)
    per = max(1, top_n // n_buckets)
    picks = (df.sort_values("score", ascending=False)
               .groupby("_b", observed=True).head(per))
    if len(picks) > top_n:
        picks = picks.nlargest(top_n, "score")
    return picks.drop(columns=["_b"])


def weights(df, scheme):
    """Position weights, normalized to sum to 1."""
    n = len(df)
    if n == 0:
        return np.array([])
    if scheme == "equal":
        w = np.ones(n)
    elif scheme == "invvol":
        v = df["volatility_60"].to_numpy(np.float64)
        v = np.where(np.isfinite(v) & (v > 1e-6), v, np.nan)
        if not np.isfinite(v).any():
            w = np.ones(n)
        else:
            v = np.where(np.isfinite(v), v, np.nanmedian(v))
            w = 1.0 / v
    elif scheme == "score":
        s = df["score"].to_numpy(np.float64)
        r = _num.rankdata(s)
        w = r / r.sum()
    elif scheme == "capw":
        m = df["market_cap"].to_numpy(np.float64)
        m = np.where(np.isfinite(m) & (m > 0), m, np.nan)
        w = np.where(np.isfinite(m), m, np.nanmedian(m)) if np.isfinite(m).any() else np.ones(n)
    else:
        raise ValueError(f"unknown weighting {scheme}")
    w = np.asarray(w, dtype=np.float64)
    tot = w.sum()
    return w / tot if tot > 0 else np.ones(n) / n


# ==========================================================================
# Prepared panel -- merge scores with outcomes ONCE
# ==========================================================================
class Prepared:
    """Scores joined to realized outcomes, pre-split by timepoint into numpy
    arrays.

    Built once per (score cache, horizon, stop) and reused across every
    portfolio config and every null draw. The matched random-selection null
    needs hundreds of re-simulations per cell, so the per-call cost here is
    what decides whether that control is affordable -- and it is the control
    that keeps the sweep honest, so it has to be.
    """

    __slots__ = ("tps", "g", "native_step")

    def __init__(self, scores, out_tab, horizon, stop):
        gcol, scol = O.col_gross(horizon, stop), O.col_stopped(horizon, stop)
        if gcol not in out_tab.columns:
            raise KeyError(f"{gcol} not in outcomes table -- rebuild the cache")

        s = scores.copy()
        s["ticker"] = s["ticker"].astype(str)
        o = out_tab[["timepoint", "ticker", gcol, scol, "tradable"]].copy()
        o["ticker"] = o["ticker"].astype(str)
        m = s.merge(o, on=["timepoint", "ticker"], how="left")

        self.tps = np.sort(m["timepoint"].unique())
        self.native_step = _infer_step(self.tps)
        self.g = {}
        for tp, d in m.groupby("timepoint", sort=True):
            self.g[np.datetime64(tp)] = {
                "ticker": d["ticker"].to_numpy(object),
                "score": d["score"].to_numpy(np.float64),
                "ret": d[gcol].to_numpy(np.float64),
                "stopped": d[scol].fillna(False).to_numpy(bool),
                "tradable": d["tradable"].fillna(False).to_numpy(bool),
                "vol": d["volatility_60"].to_numpy(np.float64)
                if "volatility_60" in d else np.full(len(d), np.nan),
                "cap": d["market_cap"].to_numpy(np.float64)
                if "market_cap" in d else np.full(len(d), np.nan),
            }

    def permuted(self, rng):
        """A copy with scores shuffled within each date. Pool, size and
        composition are untouched -- only the ranking is destroyed."""
        p = Prepared.__new__(Prepared)
        p.tps, p.native_step = self.tps, self.native_step
        p.g = {}
        for k, d in self.g.items():
            e = dict(d)
            e["score"] = rng.permutation(d["score"])
            p.g[k] = e
        return p


def _bucket_idx(v, n_buckets):
    ok = np.isfinite(v)
    out = np.zeros(len(v), dtype=np.int16)
    if ok.sum() < n_buckets * 4:
        return out
    edges = np.nanpercentile(v[ok], np.linspace(0, 100, n_buckets + 1)[1:-1])
    out[ok] = np.searchsorted(edges, v[ok], side="right").astype(np.int16)
    return out


def _pick_idx(d, top_n, bucket, n_buckets=5):
    """Indices of the selected names within one date's arrays."""
    sc = d["score"]
    n = len(sc)
    if n == 0:
        return np.array([], dtype=np.int64)
    if bucket == "none":
        k = min(top_n, n)
        idx = np.argpartition(-sc, k - 1)[:k]
        return idx[np.argsort(-sc[idx])]

    v = d["vol"] if bucket == "volq" else d["cap"]
    b = _bucket_idx(v, n_buckets)
    per = max(1, top_n // n_buckets)
    out = []
    for bi in range(n_buckets):
        m = np.flatnonzero(b == bi)
        if not len(m):
            continue
        k = min(per, len(m))
        loc = m[np.argpartition(-sc[m], k - 1)[:k]]
        out.append(loc)
    if not out:
        return np.array([], dtype=np.int64)
    idx = np.concatenate(out)
    return idx[np.argsort(-sc[idx])][:top_n]


def _weights(d, idx, scheme):
    n = len(idx)
    if n == 0:
        return np.array([])
    if scheme == "equal":
        w = np.ones(n)
    elif scheme == "invvol":
        v = d["vol"][idx]
        v = np.where(np.isfinite(v) & (v > 1e-6), v, np.nan)
        v = np.where(np.isfinite(v), v, np.nanmedian(v)) if np.isfinite(v).any() \
            else np.ones(n)
        w = 1.0 / v
    elif scheme == "score":
        w = _num.rankdata(d["score"][idx])
    elif scheme == "capw":
        m = d["cap"][idx]
        m = np.where(np.isfinite(m) & (m > 0), m, np.nan)
        w = np.where(np.isfinite(m), m, np.nanmedian(m)) if np.isfinite(m).any() \
            else np.ones(n)
    else:
        raise ValueError(f"unknown weighting {scheme}")
    w = np.asarray(w, dtype=np.float64)
    t = w.sum()
    return w / t if t > 0 else np.ones(n) / n


# ==========================================================================
# One portfolio config over one prepared panel
# ==========================================================================
def simulate(prep, horizon=40, top_n=5, weighting="equal", bucket="none",
             cost_bps=15.0, cost_model="turnover", step=None, vol_target=None,
             untradable="drop", stop=None, out_tab=None):
    """Run one portfolio config. Returns a per-window DataFrame.

    `prep` is a Prepared panel (stop/horizon are already baked into it).
    `stop`/`out_tab` are accepted and ignored so a portfolio-grid dict can
    carry them for bookkeeping.

    untradable : what to do with a selected name that was never tradable.
        'drop'  -- reweight across the rest (the production convention)
        'zero'  -- book a 0% return for that slice
        'worst' -- book -100%. Not realistic, but it bounds how much of any
                   result depends on quietly discarding names that stopped
                   existing, which is the exact failure mode this project
                   spent Round 11 digging out of.
    """
    tps = prep.tps
    native = prep.native_step
    keep = 1
    if step is not None:
        if step % native:
            raise ValueError(f"step {step} is not a multiple of the cached {native}")
        keep = step // native
    n_sleeves = max(1, horizon // native // keep)

    rows = []
    for sl in range(n_sleeves):
        prev = set()
        for tp in tps[sl::n_sleeves * keep]:
            d = prep.g.get(np.datetime64(tp))
            if d is None or len(d["score"]) == 0:
                continue
            idx = _pick_idx(d, top_n, bucket)
            if not len(idx):
                continue

            ok = d["tradable"][idx] & np.isfinite(d["ret"][idx])
            if untradable == "drop":
                idx = idx[ok]
                if not len(idx):
                    continue
                gv = d["ret"][idx]
            else:
                gv = np.where(ok, d["ret"][idx],
                              0.0 if untradable == "zero" else -1.0)

            w = _weights(d, idx, weighting)
            gross = float((w * gv).sum())

            exposure = 1.0
            if vol_target is not None:
                v = d["vol"][idx]
                v = v[np.isfinite(v)]
                if len(v):
                    ann = float(np.mean(v)) * np.sqrt(TRADING_DAYS)
                    ann /= max(np.sqrt(len(idx)) * 0.55, 1.0)
                    if ann > 1e-6:
                        exposure = min(1.0, vol_target / ann)
            gross *= exposure

            cur = set(d["ticker"][idx])
            if cost_model == "turnover":
                turn = 1.0 - (len(cur & prev) / max(len(cur), 1))
                charged = min(1.0, max(turn, float(d["stopped"][idx].mean())))
            elif cost_model == "per_window":
                charged = 1.0
            else:
                raise ValueError(cost_model)
            net = gross - charged * (cost_bps / 1e4) * exposure
            prev = cur

            rows.append({"sleeve": sl, "timepoint": pd.Timestamp(tp),
                         "n": len(idx), "gross": gross, "net": net,
                         "exposure": exposure, "turnover": charged})

    return pd.DataFrame(rows)


def _infer_step(tps):
    """Trading-day spacing of the cached pick grid, inferred from calendar
    gaps (median gap / ~1.45 calendar days per trading day)."""
    if len(tps) < 3:
        return 1
    d = np.diff(tps).astype("timedelta64[D]").astype(int)
    return max(1, int(round(np.median(d) / 1.4523)))


# ==========================================================================
# Scoring against SPY
# ==========================================================================
def spy_windows(spy_df, timepoints, horizon):
    """SPY's return over each holding window, matched to the same convention
    the positions use: enter at the next bar's open, exit at close[+horizon]."""
    s = spy_df.sort_values("date").reset_index(drop=True)
    dates = s["date"].to_numpy("datetime64[ns]")
    op = s["open"].to_numpy(np.float64)
    cl = s["close"].to_numpy(np.float64)
    out = {}
    for tp in timepoints:
        j = int(np.searchsorted(dates, np.datetime64(tp), "right"))
        if j >= len(dates):
            continue
        last = min(j + horizon, len(dates)) - 1
        if last < j or not np.isfinite(op[j]) or op[j] <= 0:
            continue
        out[pd.Timestamp(tp)] = cl[last] / op[j] - 1.0
    return pd.Series(out)


def score_run(per_window, spy_ret, horizon, era=None):
    """Collapse a simulate() result into the metric set the sweep is judged on.

    Primary metric (pre-registered): net compounded terminal value vs SPY over
    the same calendar span. Everything else is diagnostic.
    """
    if per_window.empty:
        return None
    df = per_window.copy()
    if era is not None:
        lo, hi = era
        df = df[(df["timepoint"] >= pd.Timestamp(lo)) &
                (df["timepoint"] < pd.Timestamp(hi))]
    if df.empty:
        return None

    df["spy"] = df["timepoint"].map(spy_ret)
    df = df.dropna(subset=["spy"])
    if df.empty:
        return None

    # Sleeve equity curves compound independently; the book is their mean.
    eq_m, eq_s, per_sleeve = [], [], []
    for sl, g in df.groupby("sleeve"):
        g = g.sort_values("timepoint")
        eq_m.append(float(np.prod(1.0 + g["net"].to_numpy(np.float64))))
        eq_s.append(float(np.prod(1.0 + g["spy"].to_numpy(np.float64))))
        per_sleeve.append(g)
    model_mult = float(np.mean(eq_m))
    spy_mult = float(np.mean(eq_s))

    # Book-level per-period series: average across sleeves at each date.
    book = (df.groupby("timepoint")[["net", "spy"]].mean().sort_index())
    r = book["net"].to_numpy(np.float64)
    b = book["spy"].to_numpy(np.float64)
    ex = r - b
    n = len(r)

    span_days = (book.index[-1] - book.index[0]).days + horizon * 1.4523
    years = max(span_days / 365.25, 1e-6)
    per_year = n / years

    def _ann(mult):
        return mult ** (1.0 / years) - 1.0 if mult > 0 else -1.0

    sd = float(np.std(r, ddof=1)) if n > 1 else np.nan
    ex_sd = float(np.std(ex, ddof=1)) if n > 1 else np.nan

    eq = np.cumprod(1.0 + r)
    dd = float(np.min(eq / np.maximum.accumulate(eq)) - 1.0) if n else np.nan

    return {
        "n_windows": n,
        "years": round(years, 2),
        "model_mult": model_mult,
        "spy_mult": spy_mult,
        "mult_ratio": model_mult / spy_mult if spy_mult > 0 else np.nan,
        "model_cagr": _ann(model_mult),
        "spy_cagr": _ann(spy_mult),
        "excess_cagr": _ann(model_mult) - _ann(spy_mult),
        "mean_excess": float(np.mean(ex)),
        "t_excess": float(np.mean(ex) / (ex_sd / np.sqrt(n))) if ex_sd and n > 1 else np.nan,
        "win_rate": float((ex > 0).mean()),
        "sharpe": float(np.mean(r) / sd * np.sqrt(per_year)) if sd else np.nan,
        "info_ratio": float(np.mean(ex) / ex_sd * np.sqrt(per_year)) if ex_sd else np.nan,
        "vol_ann": float(sd * np.sqrt(per_year)) if sd else np.nan,
        "max_dd": dd,
        "skew": _num.skew(r),
        "kurt": _num.kurtosis(r),
        "mean_exposure": float(df["exposure"].mean()),
        "mean_turnover": float(df["turnover"].mean()),
        "mean_n": float(df["n"].mean()),
        "_returns": r,
        "_timepoints": list(book.index),
    }


def mean_ic(prep, era=None, min_names=20):
    """Cross-sectional rank IC of score vs realized return -- the B4 measure.

    Reported alongside the portfolio metrics because it uses every name every
    window, and is therefore far higher-powered than any 5-name portfolio
    result. A config with a real signal but a bad portfolio shows up here; a
    config whose portfolio result is luck does not.
    """
    ics = []
    for tp, d in prep.g.items():
        if era is not None:
            t = pd.Timestamp(tp)
            if not (pd.Timestamp(era[0]) <= t < pd.Timestamp(era[1])):
                continue
        m = np.isfinite(d["ret"]) & np.isfinite(d["score"])
        if m.sum() < min_names:
            continue
        ic = _num.spearman(d["score"][m], d["ret"][m])
        if np.isfinite(ic):
            ics.append(ic)
    if len(ics) < 2:
        return {"mean_ic": np.nan, "t_ic": np.nan, "n_ic": len(ics)}
    a = np.asarray(ics)
    return {"mean_ic": float(a.mean()),
            "t_ic": float(a.mean() / (a.std(ddof=1) / np.sqrt(len(a)))),
            "n_ic": len(a)}
