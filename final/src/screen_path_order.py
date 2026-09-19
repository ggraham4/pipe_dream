"""
Is there ORDER information in a 20-day price path, beyond its net level change?

    python3 screen_path_order.py

Pre-registered 2026-09-16 (claude/2026-09-16-order-information-preregistration.md)
BEFORE any result was computed. The gates in that doc do not move.

THE QUESTION
------------
Gabe, 2026-09-12: "when I look at some of the tickers it suggests they are on a
downward slope which to XGBoost would look the same as an upward slope."

momentum_20 is (up to compounding) the SUM of 20 daily returns, and a sum is
invariant to permutation. All 20! orderings of the same 20 days -- a clean
uptrend, a clean downtrend ending where it started, a V, an inverted V --
produce the identical feature value. If forward returns depend on which path
occurred, nothing in the model can see it, and that is the entire standing
motivation for the LSTM / TSFM / behavioural-syllable branch.

WHY NOT JUST BUILD THE LSTM
---------------------------
Building one answers "can THIS ARCHITECTURE find order information", and a null
result confounds "no information" with "wrong architecture" -- precisely the
ambiguity the fly-reservoir work ended in. Comparing an order-blind statistic
with an order-aware one computed on IDENTICAL inputs answers "is there order
information at all", which is the question that should be settled first and is
three orders of magnitude cheaper.

THE PRIMARY STATISTIC IS CONDITIONAL, NOT MARGINAL
--------------------------------------------------
A 20-day slope is correlated with a 20-day sum by construction, so a marginal IC
near momentum_20's would show only that. momentum_20 therefore goes INTO the
design matrix beside size/vol/sector, and both the feature and the label are
residualised on it. What survives is the part of the path's shape that the net
level change does not already contain. Marginal IC is reported beside it for
comparability with earlier screens and is not the gate.

THE CONTROL IS THE POINT
------------------------
slope_20_shuf recomputes the slope on the SAME 20 daily returns permuted within
each (ticker, date): identical marginal distribution, identical sum, order
destroyed. An order-aware feature must beat its own shuffle, not merely beat
zero. volatility_60 is the positive control -- without it, a null result here
would be inconclusive rather than negative.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parent))
from features import FEATURE_COLS, TRADABLE_LABEL_COL, OUT_DIR   # noqa: E402
from sweep import factors as F                                   # noqa: E402
from sweep import portfolio as P                                 # noqa: E402
from sweep import _num                                           # noqa: E402

PANEL = OUT_DIR / "features_with_fundamentals_sharadar_pit.parquet"
DAILY_DIR = OUT_DIR / "sweep"
WIN = 20                     # trailing days, matching momentum_20
HORIZON = 40
MIN_NAMES = 80
SEED = 0

# effratio_20 was registered as order-aware and is NOT: it is
# (P20 - P0) / sum|dP|, and both the numerator and the denominator are
# permutation-invariant, so every ordering of the same 20 returns gives the
# identical value. Its own matched shuffle is therefore numerically identical to
# it and its paired statistic is exactly zero by construction -- the self-test
# asserts this rather than leaving it as a claim. It stays in the table so the
# mistake is visible, and it is EXCLUDED from the gate: a feature that cannot
# possibly carry order information would otherwise make the FAIL gate easier to
# satisfy by contributing a guaranteed null. Excluding it makes the gate
# strictly harder.
ORDER_AWARE = ["slope_20", "accel_20", "effratio_20"]
GATED = ["slope_20", "accel_20"]
N_SHUF = 5                   # Amendment A: 5 matched shuffles per candidate
SHUF = [f"{c}__s{k}" for c in ORDER_AWARE for k in range(N_SHUF)]
CONTROL = SHUF
REFERENCE = ["momentum_20", "volatility_60"]
NEW = ORDER_AWARE + CONTROL


def decile_volq_excess(score, y, vol, n_buckets=5, frac=0.10,
                       min_per_bucket=10) -> float:
    """Top `frac` by `score` WITHIN each volatility quintile, mean y minus the
    cross-section's mean y.

    Amendment B. The definition is lifted verbatim from fly/marginal_fly.py and
    screen_sector_hierarchy.py rather than rewritten, because the bucketing is
    the whole point: the deployed construction takes one name per volatility
    quintile, so a raw top-decile is selection-mismatched against it. That
    mismatch is the error this metric was created to fix, and reproducing it
    here under the same name would reintroduce it.

    Signed, like IC -- a feature whose information runs negative produces a
    negative excess and the sign is read, not folded away.
    """
    b = P._bucket_idx(vol, n_buckets)
    sel = []
    for bi in range(n_buckets):
        m = np.flatnonzero(b == bi)
        if len(m) < min_per_bucket:
            continue
        k = max(1, int(frac * len(m)))
        sel.append(m[np.argpartition(-score[m], k - 1)[:k]])
    if not sel:
        return np.nan
    idx = np.concatenate(sel)
    return float(y[idx].mean()) - float(y.mean())


def _pit_universe() -> dict:
    """date -> set of eligible tickers, read from the parquet directly.

    continuous_walkforward_pit.load_pit_universe() is the canonical loader but
    that module imports xgboost at import time, so a screen that needs no model
    at all cannot run without it. The parquet's contract here is two columns and
    a date slice.
    """
    path = OUT_DIR.parent / "data" / "sharadar" / "pit_universe.parquet"
    if not path.exists():
        raise SystemExit(f"{path} not found -- run build_pit_universe.py first.")
    u = pd.read_parquet(path, columns=["date", "ticker"])
    u["date"] = u["date"].astype(str).str.slice(0, 10)
    u["ticker"] = u["ticker"].astype(str)
    m = {d: frozenset(g) for d, g in u.groupby("date")["ticker"]}
    print(f"  PIT universe: {len(m):,} trading days")
    return m


def newey_west_t(x, lag):
    """t for the mean of an autocorrelated series, Bartlett kernel."""
    x = np.asarray(x, np.float64)
    x = x[np.isfinite(x)]
    n = len(x)
    if n < lag + 5:
        return np.nan, np.nan, n
    d = x - x.mean()
    g0 = float(d @ d) / n
    var = g0
    for k in range(1, lag + 1):
        gk = float(d[k:] @ d[:-k]) / n
        var += 2.0 * (1.0 - k / (lag + 1.0)) * gk
    if var <= 0:
        return float(x.mean()), np.nan, n
    return float(x.mean()), float(x.mean() / np.sqrt(var / n)), n


def _path_features(lr: np.ndarray, rng) -> dict:
    """Path statistics from a (T,) log-return series for ONE ticker.

    lr[i] is the log return INTO day i, so the 20 returns ending at day i are
    lr[i-19 : i+1] -- the same window momentum_20 uses. Everything is computed
    by cumulative sums so the whole ticker is one vectorised pass.

    Amendment A: every order-aware feature also gets N_SHUF matched shuffles --
    the SAME 20 returns permuted within each window. Same sum, same marginal
    distribution, order destroyed. The candidate is read as candidate minus the
    mean of its own shuffles, so each one needs its own control rather than
    borrowing slope's.
    """
    T = len(lr)
    out = {c: np.full(T, np.nan) for c in NEW}
    if T < WIN:
        return out
    x = np.arange(WIN, dtype=np.float64)
    xc = x - x.mean()
    sxx = float(xc @ xc)

    V = np.lib.stride_tricks.sliding_window_view(lr, WIN)      # (T-WIN+1, WIN)
    end = np.arange(WIN - 1, T)

    def _stats(W):
        """The three order-aware statistics for one (n, WIN) block of returns."""
        P = np.cumsum(W, axis=1)
        tot = P[:, -1]
        denom = np.abs(W).sum(1)
        with np.errstate(invalid="ignore", divide="ignore"):
            eff = np.where(denom > 0, tot / denom, np.nan)
        return {
            "slope_20": (P - P.mean(axis=1, keepdims=True)) @ xc / sxx * WIN,
            "accel_20": W[:, WIN // 2:].sum(1) - W[:, :WIN // 2].sum(1),
            "effratio_20": eff,
        }

    real = _stats(V)
    for c in ORDER_AWARE:
        out[c][end] = real[c]
    for k in range(N_SHUF):
        idx = np.argsort(rng.random(V.shape), axis=1)
        sh = _stats(np.take_along_axis(V, idx, axis=1))
        for c in ORDER_AWARE:
            out[f"{c}__s{k}"][end] = sh[c]
    return out


def build_path_features(panel: pd.DataFrame) -> pd.DataFrame:
    """Adds NEW columns to a panel carrying ticker/date/close, sorted by date."""
    rng = np.random.default_rng(SEED)
    panel = panel.sort_values(["ticker", "date"], kind="mergesort")
    close = panel["close"].to_numpy(np.float64)
    with np.errstate(invalid="ignore", divide="ignore"):
        logp = np.log(np.where(close > 0, close, np.nan))
    tick = panel["ticker"].to_numpy()
    # boundaries of each ticker's block
    cut = np.flatnonzero(tick[1:] != tick[:-1]) + 1
    starts = np.concatenate([[0], cut])
    ends = np.concatenate([cut, [len(tick)]])

    cols = {c: np.full(len(tick), np.nan) for c in NEW}
    for a, b in zip(starts, ends):
        lp = logp[a:b]
        if len(lp) < WIN + 1:
            continue
        lr = np.diff(lp, prepend=np.nan)     # lr[i] = return INTO day i
        lr[0] = np.nan
        # a NaN anywhere in a window poisons that window; that is correct --
        # a path with a missing day is not a 20-day path.
        res = _path_features(lr, rng)
        for c in NEW:
            cols[c][a:b] = res[c]
    for c in NEW:
        panel[c] = cols[c]
    return panel


def main(start=None, end=None, tag=""):
    need = ["ticker", "date", "close", TRADABLE_LABEL_COL,
            "market_cap", "volatility_60", "momentum_20"]
    present = set(pq.ParquetFile(PANEL).schema_arrow.names)
    missing = [c for c in need if c not in present]
    if missing:
        raise SystemExit(f"{PANEL.name} lacks {missing}")
    print(f"loading {PANEL.name} ...", flush=True)
    # A date filter must be pushed down to the reader (the full panel is
    # ~12.3M rows and will not fit in a small machine's memory) AND must keep
    # WIN+1 days of run-up, or every ticker loses its first 20 rows to the
    # filter boundary rather than to genuinely missing history.
    filt = []
    if start:
        filt.append(("date", ">=", pd.Timestamp(start)
                     - pd.Timedelta(days=int(WIN * 2.2))))
    if end:
        filt.append(("date", "<", pd.Timestamp(end)))
    panel = pd.read_parquet(PANEL, columns=need, filters=filt or None)
    print(f"  {len(panel):,} rows", flush=True)

    print("building path features ...", flush=True)
    panel = build_path_features(panel)

    # SANITY: the permutation control must preserve the sum exactly, and
    # slope_20 must recover a straight line. Both are cheap and both would have
    # caught a silent indexing error.
    _selftest()

    corr = panel[["momentum_20"] + NEW].corr(method="spearman")["momentum_20"]
    print("\nrank correlation with momentum_20 (the order-blind incumbent):")
    for c in NEW:
        print(f"  {c:<16}{corr[c]:>+7.3f}")
    print("  slope_20 is highly correlated with the sum BY CONSTRUCTION, which")
    print("  is why the gate is on the CONDITIONAL statistic, not this one.")

    if start:
        panel = panel[panel["date"] >= pd.Timestamp(start)]

    pit = _pit_universe()
    smap = F.load_sector_map()

    feats = NEW + REFERENCE
    daily_marg = {c: [] for c in feats}
    daily_cond = {c: [] for c in feats}
    dec_marg = {c: [] for c in feats}
    dec_cond = {c: [] for c in feats}
    days = []
    panel = panel.dropna(subset=["momentum_20", "volatility_60", "market_cap"])
    print(f"\nscreening {panel['date'].nunique():,} dates ...", flush=True)
    for d_, g in panel.groupby("date", observed=True, sort=True):
        day = pit.get(str(pd.Timestamp(d_).date()))
        if day:
            g = g[g["ticker"].isin(day)]
        y = g[TRADABLE_LABEL_COL].to_numpy(np.float64)
        m0 = np.isfinite(y)
        if m0.sum() < MIN_NAMES:
            continue
        g = g[m0]; y = y[m0]
        D, _ = F.build_design(g["ticker"].to_numpy(),
                              g["market_cap"].to_numpy(np.float64),
                              g["volatility_60"].to_numpy(np.float64),
                              spec="size_vol_sector", sector_map=smap)
        # CONDITIONAL design: momentum_20 joins the controls, standardised so
        # it does not dominate the normal equations numerically.
        mom = g["momentum_20"].to_numpy(np.float64)
        mm = np.isfinite(mom)
        z = np.zeros(len(mom))
        if mm.sum() > 2 and np.nanstd(mom[mm]) > 0:
            z[mm] = (mom[mm] - mom[mm].mean()) / mom[mm].std()
        Dc = np.column_stack([D, z])

        y_m = F.residualize(y, D)
        y_c = F.residualize(y, Dc)
        ok_m, ok_c = np.isfinite(y_m), np.isfinite(y_c)
        if ok_c.sum() < MIN_NAMES:
            continue
        days.append(pd.Timestamp(d_))
        vol = g["volatility_60"].to_numpy(np.float64)
        for c in feats:
            x = g[c].to_numpy(np.float64)
            mk = ok_m & np.isfinite(x)
            if mk.sum() >= MIN_NAMES:
                daily_marg[c].append(_num.spearman(x[mk], y_m[mk]))
                dec_marg[c].append(decile_volq_excess(x[mk], y_m[mk], vol[mk]))
            else:
                daily_marg[c].append(np.nan); dec_marg[c].append(np.nan)
            # both sides residualised -> partial rank correlation given controls
            xf = np.isfinite(x)
            if xf.sum() < MIN_NAMES:
                daily_cond[c].append(np.nan); dec_cond[c].append(np.nan)
                continue
            xr = np.full(len(x), np.nan)
            xr[xf] = F.residualize(x[xf], Dc[xf])
            mk = ok_c & np.isfinite(xr)
            if mk.sum() >= MIN_NAMES:
                daily_cond[c].append(_num.spearman(xr[mk], y_c[mk]))
                dec_cond[c].append(decile_volq_excess(xr[mk], y_c[mk], vol[mk]))
            else:
                daily_cond[c].append(np.nan); dec_cond[c].append(np.nan)
    days = pd.DatetimeIndex(days)
    print(f"  {len(days):,} daily cross-sections, "
          f"{days.min().date()} .. {days.max().date()}")

    # The daily IC series is the sufficient statistic: nothing downstream needs
    # the panel again. Saving it lets the full 2007-2026 era be run as slices
    # on a machine that cannot hold 12.3M rows at once, and pooled afterwards
    # -- which is arithmetically identical to one run, because Newey-West is
    # computed on the concatenated series either way.
    np.savez(DAILY_DIR / f"path_order_daily{tag or '_full'}.npz",
             days=days.values.astype("datetime64[D]"),
             **{f"marg__{c}": np.asarray(daily_marg[c], np.float64) for c in feats},
             **{f"cond__{c}": np.asarray(daily_cond[c], np.float64) for c in feats},
             **{f"decm__{c}": np.asarray(dec_marg[c], np.float64) for c in feats},
             **{f"decc__{c}": np.asarray(dec_cond[c], np.float64) for c in feats})

    _report(days, daily_marg, daily_cond, feats, tag, dec_marg, dec_cond)


def _report(days, daily_marg, daily_cond, feats, tag="",
            dec_marg=None, dec_cond=None):
    yrs = sorted(set(days.year))
    rows = []
    for c in feats:
        r = {"feature": c,
             "kind": ("order-aware" if c in ORDER_AWARE else
                      "SHUFFLE CONTROL" if c in CONTROL else "reference")}
        for stat, dd in (("marg", daily_marg), ("cond", daily_cond)):
            v = np.asarray(dd[c], np.float64)
            m, tnw, n = newey_west_t(v, HORIZON)
            ok = np.isfinite(v)
            tn = (float(v[ok].mean() / (v[ok].std(ddof=1) / np.sqrt(ok.sum())))
                  if ok.sum() > 2 else np.nan)
            r[f"ic_{stat}"] = m; r[f"t_naive_{stat}"] = tn; r[f"t_nw_{stat}"] = tnw
            r[f"n_days_{stat}"] = n
            per = []
            for y in yrs:
                s = v[np.asarray(days.year == y) & ok]
                per.append(float(s.mean()) if len(s) > 20 else np.nan)
            r[f"sign_consistency_{stat}"] = (
                float(np.nanmean(np.sign(per) == np.sign(m))) if m == m else np.nan)
            if stat == "cond":
                r.update({f"ic_{y}": p for y, p in zip(yrs, per)})
        rows.append(r)
    res = pd.DataFrame(rows)

    print("\n" + "=" * 104)
    print("ORDER INFORMATION IN A 20-DAY PATH  --  Newey-West(40), daily cross-sections")
    print("=" * 104)
    print(f"{'feature':<17}{'kind':<17}{'marg IC':>9}{'marg NW t':>11}"
          f"{'COND IC':>10}{'COND NW t':>11}{'sign cons':>11}")
    for _, r in res.iterrows():
        print(f"{r['feature']:<17}{r['kind']:<17}{r['ic_marg']:>+9.4f}"
              f"{r['t_nw_marg']:>+11.2f}{r['ic_cond']:>+10.4f}"
              f"{r['t_nw_cond']:>+11.2f}{r['sign_consistency_cond']:>10.0%}")
    print("\nper-year CONDITIONAL IC")
    print(f"{'feature':<17}" + "".join(f"{y:>9}" for y in yrs))
    for _, r in res.iterrows():
        line = "".join(f"{r[f'ic_{y}']:>+9.4f}" if r[f"ic_{y}"] == r[f"ic_{y}"]
                       else f"{'--':>9}" for y in yrs)
        print(f"{r['feature']:<17}{line}")

    # ---- the pre-registered gates, evaluated mechanically ----
    g = res.set_index("feature")
    shuf = max(abs(g.loc[f"{c}__s0", "t_nw_cond"]) for c in GATED)
    paired = {r["feature"]: r for r in
              _report_paired(days, daily_cond, yrs,
                             "AMENDMENT A: conditional IC", "IC")}
    pdec = None
    if dec_cond is not None:
        pdec = {r["feature"]: r for r in
                _report_paired(days, dec_cond, yrs,
                               "AMENDMENT B: conditional decile_volq_excess "
                               "(40-day return units)", "dec")}
    # Amendment B, when available, is the registered primary. Its PASS clause
    # additionally requires the sign to AGREE with Amendment A's, so a PASS
    # cannot be manufactured by reading the same weak effect through a
    # differently-signed lens.
    # The positive control must be read on the SAME statistic as the primary,
    # or a decile gate would be licensed by an IC control.
    #
    # AND FOR THE DECILE STATISTIC THAT CONTROL IS STRUCTURALLY INVALID.
    # decile_volq_excess selects the top 10% WITHIN each volatility quintile,
    # so ranking by volatility_60 inside a volatility bucket is very nearly a
    # constant -- the metric is built to be blind to exactly the feature
    # Amendment B nominated as its positive control. Its marginal decile t
    # comes back at ~1.7 against a 3.0 bar for that reason and not because the
    # estimator lacks power. Reported and flagged rather than swapped for a
    # control that would pass, which would be choosing a control after seeing
    # the result.
    pos = abs(g.loc["volatility_60", "t_nw_marg"])
    pos_invalid = False
    if pdec is not None and dec_marg is not None:
        _, pos_t, _ = newey_west_t(
            np.asarray(dec_marg["volatility_60"], np.float64), HORIZON)
        pos = abs(pos_t)
        pos_invalid = True

    prim, pname = (pdec, "B (decile)") if pdec else (paired, "A (IC)")
    hits = [c for c in GATED
            if abs(prim[c]["t_nw"]) >= 2.0
            and prim[c]["sign_consistency"] >= 0.70
            and (pdec is None or
                 np.sign(prim[c]["diff"]) == np.sign(paired[c]["diff"]))]
    allnull = all(abs(prim[c]["t_nw"]) < 1.4 for c in GATED)
    print("\n" + "=" * 104)
    print("PRE-REGISTERED GATES")
    print("=" * 104)
    print(f"  positive control volatility_60 |t| = {pos:.2f}  MARGINAL  "
          f"(FAIL gate needs >= 3.0)")
    print(f"    read marginal, not conditional: volatility_60 is IN the design "
          f"matrix, so\n    its conditional column is a feature partialled on "
          f"itself and measures nothing.")
    if pos_invalid:
        print("    ^ STRUCTURALLY INVALID as a control for the decile "
              "statistic: decile_volq_excess\n      buckets ON volatility, so "
              "it is built to be blind to volatility_60. The FAIL\n      gate "
              "therefore cannot be reached under Amendment B.")
    print(f"  worst single shuffle's own |t| = {shuf:.2f}  (why the original "
          f"absolute-level gate could not resolve)")
    # How wide is the null actually? The 15 shuffle series carry no order
    # information by construction, so the spread of THEIR t-statistics is the
    # empirical null for an unpaired read -- and it is much wider at the decile
    # than at IC, which is why only the paired number may be read.
    for stat, dd in (("IC", daily_cond), ("decile", dec_cond)):
        if dd is None:
            continue
        ts = [abs(newey_west_t(np.asarray(dd[f"{c}__s{k}"], np.float64),
                               HORIZON)[1])
              for c in ORDER_AWARE for k in range(N_SHUF)]
        print(f"  empirical null, {stat:<7}: {N_SHUF * len(ORDER_AWARE)} "
              f"order-free shuffle series reach median |t| "
              f"{np.median(ts):.2f}, max {max(ts):.2f}")
    print(f"  primary statistic: AMENDMENT {pname}")
    for c in GATED:
        extra = ("" if pdec is None else
                 f"   [A: {paired[c]['t_nw']:+.2f}]")
        print(f"    {c:<14} DIFF t {prim[c]['t_nw']:>+6.2f}   "
              f"sign cons {prim[c]['sign_consistency']:>4.0%}{extra}")
    print(f"  candidates clearing |DIFF t| >= 2.0 with >=70% sign consistency "
          f"(and matching A's sign): {hits or 'none'}")
    if hits:
        verdict = f"PASS -- order information exists ({', '.join(hits)})"
    elif allnull and pos >= 3.0:
        verdict = ("FAIL -- no order information in a 20-day path; "
                   "close the sequence-model branch for this input")
    else:
        verdict = "INCONCLUSIVE"
    print(f"\n  VERDICT: {verdict}")

    out = OUT_DIR / "sweep" / f"path_order_screen{tag}.csv"
    res.to_csv(out, index=False)
    print(f"\nwritten {out}")


def _selftest():
    """The two errors that would silently invalidate this whole screen."""
    rng = np.random.default_rng(1)
    # a straight line must give slope == total, and zero acceleration
    lr = np.concatenate([[np.nan], np.full(60, 0.01)])
    f = _path_features(lr, rng)
    i = 40
    assert abs(f["slope_20"][i] - 0.20) < 1e-9, f["slope_20"][i]
    assert abs(f["accel_20"][i]) < 1e-12, f["accel_20"][i]
    assert abs(f["effratio_20"][i] - 1.0) < 1e-12, f["effratio_20"][i]
    # a V: same 20-day sum as its reverse, opposite acceleration
    r = np.concatenate([np.full(10, -0.01), np.full(10, 0.01)])
    a = _path_features(np.concatenate([[np.nan], r]), rng)
    b = _path_features(np.concatenate([[np.nan], r[::-1]]), rng)
    # lr[0] is NaN, so the first COMPLETE window ends at index WIN, not WIN-1.
    j = WIN
    assert abs(a["accel_20"][j] - 0.20) < 1e-12
    assert abs(b["accel_20"][j] + 0.20) < 1e-12
    assert abs(a["slope_20"][j] + b["slope_20"][j]) < 1e-9, "V/inverted-V must mirror"
    # the shuffle control must preserve the SUM exactly
    lr2 = np.concatenate([[np.nan], rng.normal(0, .02, 200)])
    V = np.lib.stride_tricks.sliding_window_view(lr2[1:], WIN)
    tot = V.sum(1)
    sh = _path_features(lr2, np.random.default_rng(7))
    # sum is invariant under permutation, so a shuffled slope is bounded by the
    # same total; verify the marginal set is untouched via the effratio, which
    # depends only on |r| and the sum -- both permutation-invariant.
    er = _path_features(lr2, np.random.default_rng(99))["effratio_20"]
    assert np.allclose(er[WIN:], sh["effratio_20"][WIN:], equal_nan=True), \
        "permutation must not change any order-blind statistic"
    for k in range(N_SHUF):
        assert not np.allclose(sh[f"slope_20__s{k}"][WIN:], sh["slope_20"][WIN:],
                               equal_nan=True), f"shuffle {k} did not reorder"
        # effratio depends only on the SUM and on sum|r|, both permutation-
        # invariant, so its "shuffle" must be numerically identical. That makes
        # effratio_20 order-blind after all -- recorded here rather than quietly
        # dropped, because the paired statistic for it is then exactly zero.
        assert np.allclose(sh[f"effratio_20__s{k}"][WIN:], sh["effratio_20"][WIN:],
                           equal_nan=True), "effratio must be permutation-invariant"
    # the shuffles must differ from EACH OTHER, or they are one control repeated
    assert not np.allclose(sh["slope_20__s0"][WIN:], sh["slope_20__s1"][WIN:],
                           equal_nan=True), "shuffles are not independent"
    print("  self-test: straight line, V/inverted-V mirror, "
          "shuffle preserves order-blind statistics -- ok")


def _report_paired(days, cond, yrs, title="conditional IC", unit="IC"):
    """AMENDMENT A's primary statistic: candidate minus its own matched shuffles.

    The conditional statistic's null is not centred at zero -- residualising a
    path statistic on momentum_20 leaves a component the real and the shuffled
    version share, and that component is order-blind by construction because the
    shuffle has no order at all. So the candidate is read against the shuffle's
    level, not against zero. Pairing by DAY also removes the market-wide common
    term, which is the dominant source of variance in a daily IC series.
    """
    print("\n" + "=" * 104)
    print(f"candidate MINUS the mean of its own {N_SHUF} matched shuffles, "
          f"paired by day  --  {title}")
    print("=" * 104)
    print(f"{'feature':<17}{'cand ' + unit:>12}{'shuf ' + unit:>12}{'DIFF':>11}"
          f"{'NW t':>9}{'sign cons':>11}{'days>0':>9}")
    rows = []
    for c in ORDER_AWARE:
        a = np.asarray(cond[c], np.float64)
        S = np.vstack([np.asarray(cond[f"{c}__s{k}"], np.float64)
                       for k in range(N_SHUF)])
        b = np.nanmean(S, axis=0)
        d = a - b
        m, t, n = newey_west_t(d, HORIZON)
        ok = np.isfinite(d)
        per = []
        for y in yrs:
            sl = d[np.asarray(days.year == y) & ok]
            per.append(float(sl.mean()) if len(sl) > 20 else np.nan)
        sc = float(np.nanmean(np.sign(per) == np.sign(m))) if m == m else np.nan
        flag = "" if c in GATED else "  (order-BLIND, not gated)"
        print(f"{c:<17}{np.nanmean(a):>+12.5f}{np.nanmean(b):>+12.5f}"
              f"{m:>+11.5f}{t:>+9.2f}{sc:>10.0%}{np.mean(d[ok] > 0):>9.0%}{flag}")
        rows.append({"feature": c, "diff": m, "t_nw": t, "sign_consistency": sc,
                     **{f"diff_{y}": p for y, p in zip(yrs, per)}})
    print(f"{'':<17}" + "".join(f"{y:>9}" for y in yrs))
    for r in rows:
        print(f"{r['feature']:<17}" +
              "".join(f"{r[f'diff_{y}']:>+9.4f}" if r[f"diff_{y}"] == r[f"diff_{y}"]
                      else f"{'--':>9}" for y in yrs))
    return rows


def pool(pattern="path_order_daily_*.npz"):
    """Combine sliced runs into one full-era result.

    Concatenating the daily IC series and running Newey-West once over the
    result is exactly what a single unsliced run does. Slices must not overlap;
    this checks that rather than assuming it.
    """
    import glob
    files = sorted(glob.glob(str(DAILY_DIR / pattern)))
    if not files:
        raise SystemExit(f"no slices matching {DAILY_DIR / pattern}")
    days, feats = [], None
    marg, cond, decm, decc = {}, {}, {}, {}
    for f in files:
        z = np.load(f, allow_pickle=False)
        ks = [k[6:] for k in z.files if k.startswith("marg__")]
        if feats is None:
            feats = ks
        elif set(feats) != set(ks):
            raise SystemExit(f"{f} has different features: {sorted(set(ks) ^ set(feats))}")
        if "decm__slope_20" not in z.files:
            raise SystemExit(
                f"{Path(f).name} predates Amendment B (no decile series). "
                f"Rerun that slice -- pooling a mix would silently drop the "
                f"decile statistic for part of the era.")
        days.append(pd.DatetimeIndex(z["days"]))
        for c in feats:
            marg.setdefault(c, []).append(z[f"marg__{c}"])
            cond.setdefault(c, []).append(z[f"cond__{c}"])
            decm.setdefault(c, []).append(z[f"decm__{c}"])
            decc.setdefault(c, []).append(z[f"decc__{c}"])
        print(f"  {Path(f).name}: {len(z['days']):,} days "
              f"{pd.Timestamp(z['days'][0]).date()} .. {pd.Timestamp(z['days'][-1]).date()}")
    allday = pd.DatetimeIndex(np.concatenate([d.values for d in days]))
    if allday.duplicated().any():
        raise SystemExit(f"{int(allday.duplicated().sum())} duplicated dates -- "
                         f"the slices overlap; rerun with disjoint ranges.")
    order = np.argsort(allday.values)
    allday = allday[order]
    M = {c: np.concatenate(marg[c])[order] for c in feats}
    C = {c: np.concatenate(cond[c])[order] for c in feats}
    DM = {c: np.concatenate(decm[c])[order] for c in feats}
    DC = {c: np.concatenate(decc[c])[order] for c in feats}
    print(f"\npooled {len(files)} slices -> {len(allday):,} daily cross-sections, "
          f"{allday.min().date()} .. {allday.max().date()}")
    _report(allday, M, C, feats, "_pooled", DM, DC)


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--start", default=None, help="first screened date (YYYY-MM-DD)")
    ap.add_argument("--end", default=None, help="exclusive last date")
    ap.add_argument("--tag", default="", help="suffix for the output csv")
    ap.add_argument("--pool", action="store_true",
                    help="combine previously saved slices instead of screening")
    a = ap.parse_args()
    if a.pool:
        pool()
    else:
        main(a.start, a.end, a.tag)
