"""
Effective breadth: how many independent bets the portfolio actually makes.

Round 15 (2026-09-11). Pre-registered in
`claude/2026-09-11-round15-breadth-preregistration.md`; the gates below do not
move.

Why this module exists
----------------------
Rounds 12-14 attacked one term of

    IR  =  IC  x  sqrt(breadth)

exclusively, and returned well-powered negatives each time: the 24 existing
columns are a sector bet plus noise, and the rate family is one year (2019)
wearing a costume.

The other term has never been measured properly. The "~25 effective bets"
quoted since Round 12 was an informal estimate, not a definition, and no
decision should rest on a number nobody can reproduce.

**Read the multiplier honestly before using any of this.** Breadth is not an
independent source of edge: IC = 0 gives IR = 0 at any breadth, so nothing here
can make a signal-free model work. What breadth *is* worth is that it cuts both
ways at once -- more independent bets per unit time is more effective sample
size, so it tightens the standard error on IC at the same time as it raises the
IR that a given IC delivers:

    true IC 0.01, breadth  25  ->  IR 0.050   undetectable, untradeable
    true IC 0.01, breadth 625  ->  IR 0.250   detectable, and worth trading

The neutralized IC estimates are 0.001-0.014 against a minimum detectable IC of
0.0206. That is the signature of "too small to see at this sample size", which
is a different finding from "zero". Breadth is the only remaining lever that
addresses both halves of that sentence.

The definition, and the first version of it that was wrong
----------------------------------------------------------
The obvious formulation assumes every position has the SAME variance `s^2`:

    Var(A) = s^2 * [ 1/N_w + rho*(1 - 1/N_w) ],  N_w = 1/sum(w^2)
    =>  BR_eff = s^2 / Var(A),   with s^2 pooled over all held positions

**That is wrong for this portfolio and it was shipped once.** The deployed
config picks one name from each of five VOLATILITY QUINTILES and weights them
INVERSE to volatility -- so position variances differ by an order of magnitude
by construction, and the heavy weights sit on the calm names. Pooling then
overstates the typical position's risk while the portfolio's realized variance
reflects the calm names, and the ratio inflates. On five positions that are
independent BY CONSTRUCTION, with the deployed vol spread, it reported
**BR_eff 19.1 against a truth of 5.0**, and produced the impossible
`capture > 1` and negative `rho_bar` that gave it away.

The corrected definition standardizes each position by its own risk before
asking how much diversification the book achieves:

    s_i     = trailing 60d vol x sqrt(horizon)        (ex-ante, causal, already
                                                       the input invvol uses)
    k^2     = mean over all (i,t) of (a_i / s_i)^2    (one global calibration
                                                       constant, from the data)
    u_i     = a_i / (s_i * k)                          risk-standardized active
    v_i     = w_i * s_i / sum(w_j * s_j)               RISK weights, not cash

    =>  BR_eff = 1 / Var_t( sum_i v_i u_i )
        ceiling = 1 / sum_i v_i^2

`k` matters: BR_eff compares a realized portfolio variance against a predicted
single-name variance, so an uncalibrated vol forecast biases it directly. One
constant estimated from ~600 observations fixes the level without touching the
RELATIVE vols, which is what breadth actually depends on.

Note what this says about inverse-vol weighting: when the vol forecast is
right, `v_i` comes out uniform, so invvol is exactly the weighting that
maximises the ceiling. The ceiling is therefore ~N, and any shortfall of
BR_eff below it is correlation, not weighting.

`self_test()` checks all three anchors -- independent -> N, perfectly
correlated -> 1, rho=0.5 -> N/(1+(N-1)/2) -- under HETEROGENEOUS variances,
which is the case that caught the original.

The trap this module is built around
------------------------------------
Raising breadth reduces variance drag and improves compounded return **with
literally zero signal**. In this harness 27% of zero-signal configs already beat
the market. So a breadth improvement that is measured against SPY proves
nothing at all, and every gate that decides anything routes through
`stats.random_selection_null` instead. Beating SPY is not evidence here and is
not reported as if it were.
"""

import numpy as np
import pandas as pd

from sweep import factors as F
from sweep import portfolio as P

TRADING_DAYS = 252


# ==========================================================================
# Per-position detail -- the input every measurement below needs
# ==========================================================================
def position_rows(prep, spy_ret, horizon=40, top_n=5, weighting="equal",
                  bucket="none", step=None, untradable="drop"):
    """One row per (window, held position), with its weight and active return.

    Deliberately mirrors `portfolio.simulate`'s selection and weighting by
    CALLING `_pick_idx` and `_weights` rather than reimplementing them, so a
    breadth number can never be computed for a portfolio the simulator would
    not actually have held. (Same rule as `current_signal_pit.py` importing its
    selection from this package -- see DATA-PIPELINE-HANDOFF.md 6.4.)

    Costs are intentionally absent. Breadth is a property of the return
    covariance of the positions; charging turnover would change the level
    without changing the correlation, and would make the two gates below
    depend on a cost assumption they have no business depending on.
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
        for tp in tps[sl::n_sleeves * keep]:
            d = prep.g.get(np.datetime64(tp))
            if d is None or len(d["score"]) == 0:
                continue
            b = spy_ret.get(pd.Timestamp(tp), np.nan)
            if not np.isfinite(b):
                continue
            idx = P._pick_idx(d, top_n, bucket)
            if not len(idx):
                continue
            ok = d["tradable"][idx] & np.isfinite(d["ret"][idx])
            if untradable == "drop":
                idx = idx[ok]
                if not len(idx):
                    continue
            w = P._weights(d, idx, weighting)
            for j, k in enumerate(idx):
                rows.append({"sleeve": sl, "timepoint": pd.Timestamp(tp),
                             "ticker": d["ticker"][k], "w": w[j],
                             "ret": d["ret"][k], "bench": b,
                             "vol": d["vol"][k],
                             "active": d["ret"][k] - b})
    return pd.DataFrame(rows)


# ==========================================================================
# B1 -- the measurement
# ==========================================================================
def effective_breadth(rows, horizon=40, step=None):
    """Risk-standardized effective breadth, its ceiling, and implied rho.

    `rows` is the output of `position_rows`. Windows are grouped by
    (sleeve, timepoint) because overlapping sleeves are separate books; mixing
    them would count the same calendar period more than once and inflate
    breadth for free.

    See the module docstring for why this is NOT the pooled-variance ratio:
    with invvol weighting over vol-quintile picks, that version reported 19.1
    where the truth was 5.0.
    """
    if rows is None or not len(rows):
        return {"n_windows": 0}

    r = rows[np.isfinite(rows["active"]) & np.isfinite(rows["w"])].copy()
    # Ex-ante risk. A position with no vol estimate gets the cross-sectional
    # median rather than being dropped -- dropping it would silently change
    # the book whose breadth is being reported.
    sv = r["vol"].to_numpy(np.float64) * np.sqrt(float(horizon))
    med = np.nanmedian(sv[np.isfinite(sv) & (sv > 0)]) if np.isfinite(sv).any() else np.nan
    if not np.isfinite(med) or med <= 0:
        return {"n_windows": 0, "error": "no usable volatility estimates"}
    sv = np.where(np.isfinite(sv) & (sv > 1e-12), sv, med)
    r["s"] = sv

    a = r["active"].to_numpy(np.float64)
    k = float(np.sqrt(np.mean((a / sv) ** 2)))
    if not np.isfinite(k) or k <= 0:
        return {"n_windows": 0, "error": "calibration failed"}
    r["u"] = a / (sv * k)

    At, ceil, Nw, npos = [], [], [], []
    for _, d in r.groupby(["sleeve", "timepoint"], sort=True):
        w = d["w"].to_numpy(np.float64)
        tw = w.sum()
        if tw <= 0:
            continue
        w = w / tw
        v = w * d["s"].to_numpy(np.float64)
        tv = v.sum()
        if tv <= 0:
            continue
        v = v / tv
        At.append(float((v * d["u"].to_numpy(np.float64)).sum()))
        ceil.append(1.0 / float((v ** 2).sum()))
        Nw.append(1.0 / float((w ** 2).sum()))
        npos.append(len(w))

    At = np.asarray(At, dtype=np.float64)
    if len(At) < 8:
        return {"n_windows": len(At)}
    var_p = float(np.var(At, ddof=1))
    if var_p <= 0:
        return {"n_windows": len(At)}

    br = 1.0 / var_p
    nv = float(np.mean(ceil))
    # invert var = 1/nv + rho*(1 - 1/nv) on the risk-standardized book
    rho = (var_p - 1.0 / nv) / (1.0 - 1.0 / nv) if nv > 1.0001 else np.nan

    # Grinold's breadth is bets per YEAR; the per-window figure already prices
    # the sleeves' correlation, so this scales only by rebalance frequency.
    per_year = TRADING_DAYS / float(step or horizon)
    # Raw active series, for the IR line only (not used in the breadth math).
    raw = []
    for _, d in r.groupby(["sleeve", "timepoint"], sort=True):
        w = d["w"].to_numpy(np.float64)
        if w.sum() > 0:
            raw.append(float(((w / w.sum()) * d["active"].to_numpy(np.float64)).sum()))
    raw = np.asarray(raw, dtype=np.float64)

    return {
        "n_windows": len(At),
        "mean_positions": float(np.mean(npos)),
        "N_w": float(np.mean(Nw)),
        "ceiling": nv,
        "BR_eff": float(br),
        "BR_eff_annual": float(br * per_year),
        "rho_bar": float(rho),
        "capture": float(br / nv),
        "vol_calibration_k": k,
        "active_mean": float(raw.mean()) if len(raw) else np.nan,
        "active_sd": float(raw.std(ddof=1)) if len(raw) > 2 else np.nan,
        "IR_per_window": (float(raw.mean() / raw.std(ddof=1))
                          if len(raw) > 2 and raw.std(ddof=1) > 0 else np.nan),
    }


def breadth_ladder(prep, spy_ret, sector_map=None, **cfg):
    """BR_eff after removing progressively more of the factor structure.

    The ladder is the part that decides whether the shortfall is a CONSTRUCTION
    defect or an intrinsic property of equities. If breadth recovers as factors
    come out, the portfolio is re-loading a factor the feature screen already
    stripped, and that is fixable. If it does not move, the correlation is in
    the assets and no selection rule will buy breadth.
    """
    rows = position_rows(prep, spy_ret, **cfg)
    if not len(rows):
        return pd.DataFrame()
    out = [dict(stage="raw (vs SPY)",
                **effective_breadth(rows, cfg.get("horizon", 40), cfg.get("step")))]

    smap = sector_map if sector_map is not None else F.load_sector_map()
    for spec in ("size", "size_vol", "size_vol_sector"):
        r2 = _residualize_rows(rows, prep, spec, smap)
        out.append(dict(stage=f"resid: {spec}",
                        **effective_breadth(r2, cfg.get("horizon", 40),
                                            cfg.get("step"))))
    return pd.DataFrame(out)


def _residualize_rows(rows, prep, spec, smap):
    """Replace each held position's active return by its residual against the
    FULL cross-section's factor design for that date.

    The design is fitted on every name available that date, not just the five
    held. Fitting on the held names alone would be a regression with more
    parameters than observations and would residualize the positions to
    approximately zero by construction -- which would report spectacular
    breadth and mean nothing.
    """
    out = rows.reset_index(drop=True)
    res = np.full(len(out), np.nan)
    tick = out["ticker"].to_numpy(object)
    for tp, d in out.groupby("timepoint", sort=False):
        g = prep.g.get(np.datetime64(tp))
        if g is None:
            continue
        fin = np.isfinite(g["ret"])
        if fin.sum() < 40:
            continue
        X, _ = F.build_design(g["ticker"][fin], g["cap"][fin], g["vol"][fin],
                              spec=spec, sector_map=smap)
        r = F.residualize(g["ret"][fin], X)
        look = dict(zip(g["ticker"][fin], r))
        loc = d.index.to_numpy()            # positional, index was reset
        for i in loc:
            v = look.get(tick[i], np.nan)
            if np.isfinite(v):
                res[i] = v
    out["active"] = res
    return out[np.isfinite(out["active"])].reset_index(drop=True)


# ==========================================================================
# B2 -- is IC concentrated at the top of the ranking, or flat?
# ==========================================================================
def decile_active(prep, spy_ret, n_bins=10, era=None):
    """Mean active return by score decile, with a standard error.

    Settles whether breadth trades off against IC. If the top decile is not
    distinguishable from the second, the ranking is flat and extra breadth is
    free; if it is, breadth genuinely costs IC and the round has to optimise
    IC(k) * sqrt(BR(k)) rather than maximise either.

    Also settles the hold-out ordering (top-5 1.526x, top-20 0.909x, top-50
    0.813x), which under the established no-signal reading is noise rather
    than evidence that concentration works.
    """
    per_bin = {b: [] for b in range(n_bins)}
    for tp in prep.tps:
        d = prep.g.get(np.datetime64(tp))
        if d is None:
            continue
        b = spy_ret.get(pd.Timestamp(tp), np.nan)
        if not np.isfinite(b):
            continue
        if era is not None:
            t = pd.Timestamp(tp)
            if not (pd.Timestamp(era[0]) <= t < pd.Timestamp(era[1])):
                continue
        sc, r, ok = d["score"], d["ret"], d["tradable"]
        m = np.isfinite(sc) & np.isfinite(r) & ok
        if m.sum() < n_bins * 10:
            continue
        s, a = sc[m], r[m] - b
        # rank into bins; bin n_bins-1 is the HIGHEST score
        q = np.argsort(np.argsort(s)) * n_bins // len(s)
        for bi in range(n_bins):
            sel = a[q == bi]
            if len(sel):
                per_bin[bi].append(float(sel.mean()))

    rows = []
    for bi in range(n_bins):
        v = np.asarray(per_bin[bi], dtype=np.float64)
        v = v[np.isfinite(v)]
        if len(v) < 8:
            continue
        rows.append({"decile": bi + 1, "n_windows": len(v),
                     "mean_active": float(v.mean()),
                     "se": float(v.std(ddof=1) / np.sqrt(len(v))),
                     "t": float(v.mean() / (v.std(ddof=1) / np.sqrt(len(v))))})
    tab = pd.DataFrame(rows)
    if len(tab) >= 2:
        top, second = tab.iloc[-1], tab.iloc[-2]
        diff = top.mean_active - second.mean_active
        se = np.sqrt(top.se ** 2 + second.se ** 2)
        tab.attrs["top_vs_second"] = {
            "diff": float(diff), "se": float(se),
            "t": float(diff / se) if se > 0 else np.nan,
            # PRE-REGISTERED at 2 SE, before the number was seen
            "verdict": "CONCENTRATED" if se > 0 and abs(diff / se) >= 2.0 else "FLAT",
        }
    return tab


# ==========================================================================
# B3 -- neutralize at SELECTION, not only in the screen
# ==========================================================================
def residualized_prepared(prep, spec="size_vol_sector", sector_map=None):
    """A Prepared whose SCORES are residualized on the factor design.

    The current construction residualizes on sector inside the feature screen
    and then selects on raw scores, so the portfolio quietly re-loads the very
    factor the screen stripped out. This removes the factor at the point the
    decision is made.

    Named failure mode, pre-registered: if the underlying model has no signal,
    this ranks the RESIDUAL of noise -- breadth goes up and the matched-null
    percentile does not move. That is a FAIL, not a pass on breadth alone.
    """
    smap = sector_map if sector_map is not None else F.load_sector_map()
    q = P.Prepared.__new__(P.Prepared)
    q.tps, q.native_step = prep.tps, prep.native_step
    q.g = {}
    for k, d in prep.g.items():
        e = dict(d)
        sc = d["score"]
        fin = np.isfinite(sc)
        if fin.sum() >= 40:
            X, _ = F.build_design(d["ticker"][fin], d["cap"][fin], d["vol"][fin],
                                  spec=spec, sector_map=smap)
            r = F.residualize(sc[fin], X)
            new = np.full(len(sc), np.nan)
            new[np.flatnonzero(fin)] = r
            # A name whose residual is undefined must not be selectable. NaN
            # would sort to the TOP of an argpartition on -score, which is the
            # exact bug that manufactured IC on sparse fundamentals in Round 13.
            e["score"] = np.where(np.isfinite(new), new, -np.inf)
        q.g[k] = e
    return q


# ==========================================================================
# Self-test -- the two anchors the definition must reproduce
# ==========================================================================
def self_test(seed=0, verbose=True):
    """Three anchors, under HETEROGENEOUS position variances.

    The heterogeneity is the point. The first version of this module passed an
    equal-variance self-test and was still wrong by 3.8x on the actual deployed
    portfolio, because that portfolio picks across volatility quintiles and
    weights inverse to volatility. A self-test that does not reproduce the
    thing the real book does is not a test.

    Anchors: independent -> N, perfectly correlated -> 1, rho=0.5 ->
    N/(1+(N-1)*0.5).
    """
    rng = np.random.default_rng(seed)
    T, N = 6000, 5
    # five volatility quintiles, which is literally what bucket='volq' picks
    svec = np.array([0.05, 0.10, 0.15, 0.25, 0.40])
    w = 1.0 / svec
    w = w / w.sum()                       # invvol, as deployed
    ok = True

    def _rows(a):
        return pd.DataFrame({
            "sleeve": 0,
            "timepoint": np.repeat(
                pd.date_range("2000-01-01", periods=T, freq="D"), N),
            "ticker": "X",
            "w": np.tile(w, T),
            "ret": 0.0, "bench": 0.0,
            "vol": np.tile(svec, T),      # horizon=1 => s = vol
            "active": a.ravel()})

    ind = rng.normal(size=(T, N)) * svec
    com = (rng.normal(size=(T, 1)) @ np.ones((1, N))) * svec
    mix = ((rng.normal(size=(T, 1)) @ np.ones((1, N)))
           + rng.normal(size=(T, N))) / np.sqrt(2.0) * svec

    for label, a, exp, tol in (
            ("independent", ind, float(N), 0.10),
            ("perfectly correlated", com, 1.0, 0.10),
            ("rho=0.5 mixture", mix, N / (1 + (N - 1) * 0.5), 0.15)):
        r = effective_breadth(_rows(a), horizon=1, step=1)
        b = r.get("BR_eff", np.nan)
        good = np.isfinite(b) and abs(b - exp) / exp < tol
        ok &= bool(good)
        if verbose:
            print(f"  {label:22} BR_eff {b:6.2f}  ceiling {r.get('ceiling', float('nan')):5.2f}"
                  f"  (expect ~{exp:.2f})  {'OK' if good else 'FAIL'}")

    # the regression guard: capture must never exceed 1
    r = effective_breadth(_rows(ind), horizon=1, step=1)
    cap_ok = r.get("capture", 9) <= 1.05
    ok &= bool(cap_ok)
    if verbose:
        print(f"  capture <= 1 (the tell that caught v1): {r.get('capture', float('nan')):.3f}"
              f"  {'OK' if cap_ok else 'FAIL'}")
        print(f"  {'ALL ANCHORS PASSED' if ok else 'ANCHORS FAILED -- do not use these numbers'}")
    return ok


if __name__ == "__main__":
    self_test()
