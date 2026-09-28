"""
WO-21 (COO): what is the post-2011 random-book drag made of?
Descriptive, no trial counted. Pre-registration (committed before the run):
final/models/2026-09-27-construction-drag.md.

icw8 frozen PRODUCTION_WEIGHTS, v2 grid column c, cap150, h=40, decile_volq,
40 offsets, net 15 bp. Books on the same universe U:
  score    pick_decile_volq on the icw8 score
  random   same construction on the icw8 score shuffled within date
           (screen_insider_v2grid.shuffle_within_date, seeds 2000..2004 = COO decomp.py)
  noscore  no_exclusion_control.pick_full_universe_volq (WO-7 construction)
Split, pre (< 2011-10-01) and post (>= 2011-10-01), on sub-calendars exactly
as COO /tmp/coo_post2011/decomp.py:
  (a) universe      = noscore_net - SPY
  (b) construction  = random_net - noscore_net          (a)+(b) = random_net - SPY
  (c) costs         = random_net - random_gross         (overlapping measure)

Shared modules are imported, never edited. In-era only: every frame asserts
max(date) < 2020-01-01.

Usage:
  python drag_decomp.py --validate   reconcile gates only (no decomposition)
  python drag_decomp.py              reconcile gates + decomposition
Output: /Users/ggraham/pipe_dream/final/out/construction/drag_decomp.json
"""
import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

SRC = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SRC / "insider"))
sys.path.insert(0, str(SRC / "reset2026"))
import composite as C                    # noqa: E402
import run_backtest as RB                # noqa: E402
import downcap_v2_readout as DR          # noqa: E402
import ic_weighted_composite as ICW      # noqa: E402
import no_exclusion_control as NXC       # noqa: E402
import screen_insider as SI              # noqa: E402
import screen_insider_v2grid as V        # noqa: E402
import hedged_composite as HC            # noqa: E402

MAIN = Path("/Users/ggraham/pipe_dream/final")
OUT_DIR = MAIN / "out" / "construction"
OUT_JSON = OUT_DIR / "drag_decomp.json"
VAL_JSON = OUT_DIR / "drag_decomp_validate.json"
COO_DECOMP = Path("/tmp/coo_post2011/decomp.json")
WO7_JSON = DR.V2 / "noscore_control.json"
HOLDOUT = pd.Timestamp("2020-01-01")
CUT = pd.Timestamp("2011-10-01")
SEEDS = [2000 + k for k in range(5)]
REF_FULL = 0.0285416
TOL = 1e-6
ANN = 252.0 / RB.HORIZON
NW_LAGS = 39
log = V.log


def hold(ts, what):
    assert pd.Timestamp(ts) < HOLDOUT, f"HOLD-OUT BREACH ({what}): {ts}"


# ---------------------------------------------------------------- data
def load_universe():
    """screen_seas.load_universe (WO-18, as used by COO decomp.py) minus the
    seas-factor left merge (which changes neither rows nor order)."""
    p, spy = DR.load_column("c")
    all_dates = sorted(p["date"].unique())
    p = p[p["eligible_cap150"]].drop(columns=["eligible_cap500", "eligible_cap2000"])
    sec = pd.read_parquet(DR.R26 / "composite_panel_v2.parquet", columns=["ticker", "date", "sector"],
                          filters=[("date", ">=", "2007-01-02"), ("date", "<=", "2019-12-31")])
    sec["date"] = pd.to_datetime(sec["date"]); sec["ticker"] = sec["ticker"].astype(str)
    n = len(p)
    p = p.merge(sec, on=["ticker", "date"], how="left")
    assert len(p) == n, "merge changed row count"
    hold(p["date"].max(), "universe"); hold(spy.index.max(), "spy"); hold(max(all_dates), "calendar")
    U = p.sort_values(["date", "ticker"]).reset_index(drop=True)
    return U, all_dates, spy


def load_iwm_ret40():
    iwm = HC.load_iwm()
    hold(iwm["date"].max(), "iwm")
    return HC.ret40(iwm)


# ---------------------------------------------------------------- books
def noscore_picks(book):
    """WO-7 no-score construction on Book's per-date slices (same skip rule,
    same NaN-return drop + renormalise as Book.picks / noscore_control_v2.realise)."""
    out = {}
    for d, s, e in book.sl:
        if e - s < C.N_VOL_QUINTILES * 4:
            continue
        g = pd.DataFrame({"volatility_60": book.vol[s:e], "ticker": book.tick[s:e]})
        pk = NXC.pick_full_universe_volq(g)
        ret = dict(zip(book.tick[s:e], book.ret[s:e]))
        pk = [(t, w) for t, w in pk if pd.notna(ret.get(t))]
        if not pk:
            continue
        ws = sum(w for _, w in pk)
        gross = sum((w / ws) * (1.0 + ret[t]) for t, w in pk) - 1.0
        out[d] = (gross, {t for t, _ in pk})
    return out


def chains(pk, dates, bench, cost):
    """downcap_v2_readout.backtest arithmetic, returning per-offset records
    (date, net, excess, f_new). bench NaN masked after costing, as backtest."""
    res = []
    for off in range(40):
        prev, recs = set(), []
        for tp in dates[off::RB.HORIZON]:
            if tp not in pk:
                continue
            gross, cur = pk[tp]
            f_new = sum(1 for t in cur if t not in prev) / len(cur)
            prev = cur
            recs.append({"date": tp, "gross": gross, "f_new": f_new, "b": bench.get(tp, np.nan)})
        net = RB.turnover_net_return(recs, cost)
        b = np.array([r["b"] for r in recs], dtype=np.float64)
        dts = np.array([r["date"] for r in recs])
        fn = np.array([r["f_new"] for r in recs])
        ok = np.isfinite(b)
        res.append({"date": dts[ok], "net": net[ok], "exc": net[ok] - b[ok], "f_new": fn[ok]})
    return res


def per_offset(ch):
    return np.array([c["exc"].mean() * ANN for c in ch])


def loyo_vec(ch):
    """(40, Y) matrix: per offset, mean excess x ANN with year y dropped."""
    years = sorted({int(pd.Timestamp(d).year) for c in ch for d in c["date"]})
    m = np.full((len(ch), len(years)), np.nan)
    for i, c in enumerate(ch):
        yr = np.array([pd.Timestamp(d).year for d in c["date"]])
        for j, y in enumerate(years):
            m[i, j] = c["exc"][yr != y].mean() * ANN
    return years, m


def per_year(ch):
    """Per calendar year of rebalance date: mean over offsets of that offset's
    in-year mean excess x ANN."""
    acc = {}
    for c in ch:
        yr = np.array([pd.Timestamp(d).year for d in c["date"]])
        for y in np.unique(yr):
            acc.setdefault(int(y), []).append(float(c["exc"][yr == y].mean() * ANN))
    return {y: float(np.mean(v)) for y, v in sorted(acc.items())}


def window(pk, dates, lo=None, hi=None):
    ds = [d for d in dates if (lo is None or d >= lo) and (hi is None or d < hi)]
    return {d: v for d, v in pk.items() if d in set(ds)}, ds


# ---------------------------------------------------------------- stats
def ols_nw(y, x, lags=NW_LAGS):
    """OLS y = a + b x with Newey-West (Bartlett, `lags`) standard errors."""
    X = np.column_stack([np.ones(len(x)), x])
    XtX_inv = np.linalg.inv(X.T @ X)
    beta = XtX_inv @ X.T @ y
    u = y - X @ beta
    Z = X * u[:, None]
    S = Z.T @ Z
    for L in range(1, lags + 1):
        w = 1.0 - L / (lags + 1.0)
        G = Z[L:].T @ Z[:-L]
        S += w * (G + G.T)
    cov = XtX_inv @ S @ XtX_inv
    se = np.sqrt(np.diag(cov))
    r2 = 1.0 - (u @ u) / ((y - y.mean()) @ (y - y.mean()))
    return {"n": int(len(y)), "alpha_per40d": float(beta[0]), "alpha_ann": float(beta[0] * ANN),
            "alpha_t_nw": float(beta[0] / se[0]), "slope": float(beta[1]), "slope_t_nw": float(beta[1] / se[1]),
            "r2": float(r2)}


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--validate", action="store_true")
    args = ap.parse_args()
    T0 = time.time()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    coo = json.loads(COO_DECOMP.read_text())["icw8"]
    wo7 = json.loads(WO7_JSON.read_text())["tiers"]["cap150"]
    assert wo7["alignment"]["dates_removed_per_book"]["noscore"] == 0
    ref_ns = wo7["books"]["vs_spy_full"]["noscore"]["mean40"]

    U, all_dates, spy = load_universe()
    V.add_ranks(U, V.FC8)
    book = V.Book(U, all_dates, spy)
    score = SI.composite_score(U, ICW.PRODUCTION_WEIGHTS).to_numpy()
    log(f"universe {len(U):,} rows; dates {all_dates[0].date()}..{all_dates[-1].date()} ({time.time()-T0:.0f}s)")

    pk = {"score": book.picks(score), "noscore": noscore_picks(book)}
    for k, sd in enumerate(SEEDS):
        pk[f"rand{k}"] = book.picks(V.shuffle_within_date(U.assign(_s=score), "_s", sd))
    log(f"picks built ({time.time()-T0:.0f}s)")
    for b, v in pk.items():
        hold(max(v), f"picks {b}")

    W = {"full": (None, None), "pre": (None, CUT), "post": (CUT, None)}
    sub = {w: {b: window(v, all_dates, lo, hi) for b, v in pk.items()} for w, (lo, hi) in W.items()}

    def dr(b, w):
        p_, ds = sub[w][b]
        return DR.backtest(p_, ds, spy)["excess_cagr_vs_spy_mean40"]

    # ---- reconcile gates
    rec = {"score": {w: dr("score", w) for w in W},
           "rand": [{w: dr(f"rand{k}", w) for w in W} for k in range(len(SEEDS))],
           "noscore_full": dr("noscore", "full")}
    checks = {"icw8_full_vs_0.0285416": abs(rec["score"]["full"] - REF_FULL) < TOL}
    for w in W:
        checks[f"score_{w}_vs_coo"] = abs(rec["score"][w] - coo["score_book"][w]) < TOL
        for k in range(len(SEEDS)):
            checks[f"rand{k}_{w}_vs_coo"] = abs(rec["rand"][k][w] - coo["null_draws"][k][w]) < TOL
    checks["noscore_full_vs_wo7"] = abs(rec["noscore_full"] - ref_ns) < TOL
    rec["refs"] = {"icw8_full": REF_FULL, "coo_score_book": coo["score_book"], "coo_null_draws": coo["null_draws"],
                   "wo7_noscore_full": ref_ns, "tol": TOL}
    rec["checks"] = checks
    rec["all_pass"] = bool(all(checks.values()))
    for k_, v_ in checks.items():
        log(f"  reconcile {k_}: {'OK' if v_ else 'FAIL'}")
    log(f"score full {rec['score']['full']:+.7f} pre {rec['score']['pre']:+.7f} post {rec['score']['post']:+.7f}; "
        f"noscore full {rec['noscore_full']:+.9f} (WO-7 {ref_ns:+.9f})")
    if args.validate or not rec["all_pass"]:
        VAL_JSON.write_text(json.dumps({"reconcile": rec, "runtime_s": time.time() - T0}, indent=2, default=float))
        log(f"wrote {VAL_JSON}")
        assert rec["all_pass"], "RECONCILE FAIL: stop, no decomposition"
        return

    # ---- decomposition
    out = {"work_order": "WO-21", "prereg": "final/models/2026-09-27-construction-drag.md",
           "era": "2007-01-02..2019-12-31", "cut": str(CUT.date()), "cost_bps": DR.COST_BPS,
           "seeds": SEEDS, "reconcile": rec}
    R = [f"rand{k}" for k in range(len(SEEDS))]
    windows = {}
    for w in W:
        vec, fnew, ch_net = {}, {}, {}
        for b in pk:
            p_, ds = sub[w][b]
            for cost_name, cost in (("net", DR.COST_BPS), ("gross", 0.0)):
                ch = chains(p_, ds, spy, cost)
                vec[(b, cost_name)] = per_offset(ch)
                if cost_name == "net":
                    ch_net[b] = ch
                    fnew[b] = float(np.mean(np.concatenate([c["f_new"] for c in ch])))
        # oracle: chains == DR.backtest on every net book
        for b in pk:
            assert abs(vec[(b, "net")].mean() - dr(b, w)) < 1e-12, f"oracle fail {b} {w}"
        m = {k: float(v.mean()) for k, v in vec.items()}
        rnd_net = np.mean([m[(r, "net")] for r in R]); rnd_gross = np.mean([m[(r, "gross")] for r in R])
        ns_net, ns_gross = m[("noscore", "net")], m[("noscore", "gross")]
        sc_net, sc_gross = m[("score", "net")], m[("score", "gross")]
        per_draw = [{"net": m[(r, "net")], "gross": m[(r, "gross")],
                     "a": ns_net, "b": m[(r, "net")] - ns_net, "c": m[(r, "net")] - m[(r, "gross")]} for r in R]
        T = rnd_net
        comp = {"T_random_net_minus_spy": T, "a_universe_noscore_net_minus_spy": ns_net,
                "b_construction_random_net_minus_noscore_net": rnd_net - ns_net,
                "c_costs_random_net_minus_random_gross": rnd_net - rnd_gross}
        shares = {"a": comp["a_universe_noscore_net_minus_spy"] / T,
                  "b": comp["b_construction_random_net_minus_noscore_net"] / T,
                  "c": comp["c_costs_random_net_minus_random_gross"] / T}
        gross3 = {"a_g_noscore_gross_minus_spy": ns_gross, "b_g_random_gross_minus_noscore_gross": rnd_gross - ns_gross,
                  "c_random_net_minus_random_gross": rnd_net - rnd_gross}
        gross3["shares"] = {"a_g": ns_gross / T, "b_g": (rnd_gross - ns_gross) / T, "c": (rnd_net - rnd_gross) / T}
        assert abs(sum(v for k, v in gross3.items() if k != "shares") - T) < 1e-12
        score_split = {"T_score_net_minus_spy": sc_net, "a_universe": ns_net, "b_score_net_minus_noscore_net": sc_net - ns_net,
                       "c_score_net_minus_score_gross": sc_net - sc_gross,
                       "b_g_score_gross_minus_noscore_gross": sc_gross - ns_gross}
        sel = {"net": sc_net - rnd_net, "gross": sc_gross - rnd_gross}
        spread = {k: {"min": float(np.min([d[k] for d in per_draw])), "max": float(np.max([d[k] for d in per_draw])),
                      "sd": float(np.std([d[k] for d in per_draw]))} for k in ("net", "gross", "b", "c")}
        windows[w] = {"books": {"score_net": sc_net, "score_gross": sc_gross, "noscore_net": ns_net, "noscore_gross": ns_gross,
                                "random_net_mean": rnd_net, "random_gross_mean": rnd_gross},
                      "decomp_net_primary": comp, "shares_primary": shares, "decomp_gross_secondary": gross3,
                      "random_per_draw": per_draw, "random_draw_spread": spread,
                      "score_split": score_split, "selection_score_minus_random": sel,
                      "mean_f_new": {"score": fnew["score"], "noscore": fnew["noscore"],
                                     "random_mean": float(np.mean([fnew[r] for r in R]))}}
        # COO addendum: icw8 selection detail (per offset), on the post window (reported for all)
        sel_off = vec[("score", "net")] - np.mean([vec[(r, "net")] for r in R], axis=0)
        years, lm_s = loyo_vec(ch_net["score"])
        lm_r = np.mean([loyo_vec(ch_net[r])[1] for r in R], axis=0)
        gl = (lm_s - lm_r).mean(axis=0)
        windows[w]["selection_offsets"] = {"mean40": float(sel_off.mean()), "sd40": float(sel_off.std()),
                                           "offsets_positive": int((sel_off > 0).sum()),
                                           "loyo_min": float(gl.min()), "loyo_min_dropped_year": int(years[int(gl.argmin())]),
                                           "loyo_max": float(gl.max()), "loyo_max_dropped_year": int(years[int(gl.argmax())])}
        log(f"{w}: T {T:+.4f} a {comp['a_universe_noscore_net_minus_spy']:+.4f} "
            f"b {comp['b_construction_random_net_minus_noscore_net']:+.4f} c {comp['c_costs_random_net_minus_random_gross']:+.4f} "
            f"| score {sc_net:+.4f} sel {sel['net']:+.4f} ({time.time()-T0:.0f}s)")
    out["windows"] = windows

    # ---- decision map (post, primary net basis)
    sp = windows["post"]["shares_primary"]; sg = windows["post"]["decomp_gross_secondary"]["shares"]
    trig = {"a_ge_2/3": bool(sp["a"] >= 2 / 3), "b_ge_2/3": bool(sp["b"] >= 2 / 3), "c_ge_1/3": bool(sp["c"] >= 1 / 3)}
    trig_g = {"a_ge_2/3": bool(sg["a_g"] >= 2 / 3), "b_ge_2/3": bool(sg["b_g"] >= 2 / 3), "c_ge_1/3": bool(sg["c"] >= 1 / 3)}
    outcomes = [n for k, n in (("a_ge_2/3", "universe bet"), ("b_ge_2/3", "construction trial"),
                               ("c_ge_1/3", "turnover work order")) if trig[k]]
    out["decision_map"] = {"primary_net_triggers": trig, "secondary_gross_triggers": trig_g,
                           "disagreement": {k: trig[k] != trig_g[k] for k in trig},
                           "outcome": " + ".join(outcomes) if outcomes else "mixed (report only)"}
    log(f"decision map: {out['decision_map']}")

    # ---- per calendar year (full-calendar chains)
    ch_full = {}
    for b in pk:
        for cost_name, cost in (("net", DR.COST_BPS), ("gross", 0.0)):
            ch_full[(b, cost_name)] = chains(pk[b], all_dates, spy, cost)
    py = {k: per_year(v) for k, v in ch_full.items()}
    years = sorted(py[("score", "net")])
    tab = {}
    for y in years:
        rn = np.mean([py[(r, "net")][y] for r in R]); rg = np.mean([py[(r, "gross")][y] for r in R])
        nn, ng = py[("noscore", "net")][y], py[("noscore", "gross")][y]
        sn, sg_ = py[("score", "net")][y], py[("score", "gross")][y]
        tab[y] = {"T_random": rn, "a": nn, "b": rn - nn, "c": rn - rg, "a_g": ng, "b_g": rg - ng,
                  "score_net": sn, "score_b": sn - nn, "score_c": sn - sg_, "selection_net": sn - rn,
                  "random_net_draw_range": [float(min(py[(r, "net")][y] for r in R)),
                                            float(max(py[(r, "net")][y] for r in R))]}
    out["per_year"] = tab

    # ---- OLS: per-date random-book net excess on SPY and on IWM 40d returns
    iwm40 = load_iwm_ret40()
    def per_date(ch):
        s = {}
        for c in ch:
            for d, n in zip(c["date"], c["net"]):
                assert d not in s
                s[d] = n
        return pd.Series(s).sort_index()
    rnd_pd = pd.concat([per_date(ch_full[(r, "net")]) for r in R], axis=1).mean(axis=1)
    sc_pd = per_date(ch_full[("score", "net")])
    df = pd.DataFrame({"rnd": rnd_pd, "score": sc_pd})
    df["spy"] = spy.reindex(df.index).astype(np.float64)
    df["iwm"] = iwm40.reindex(df.index)
    hold(df.index.max(), "ols")
    df = df.dropna()
    ols = {}
    for w, (lo, hi) in W.items():
        mask = np.ones(len(df), dtype=bool)
        if lo is not None:
            mask &= np.asarray(df.index >= lo)
        if hi is not None:
            mask &= np.asarray(df.index < hi)
        g = df[mask]
        ex = (g["rnd"] - g["spy"]).to_numpy(); exs = (g["score"] - g["spy"]).to_numpy()
        ols[w] = {"random_excess_on_spy": ols_nw(ex, g["spy"].to_numpy()),
                  "random_excess_on_iwm": ols_nw(ex, g["iwm"].to_numpy()),
                  "random_excess_on_iwm_minus_spy": ols_nw(ex, (g["iwm"] - g["spy"]).to_numpy()),
                  "random_raw_on_spy": ols_nw(g["rnd"].to_numpy(), g["spy"].to_numpy()),
                  "random_raw_on_iwm": ols_nw(g["rnd"].to_numpy(), g["iwm"].to_numpy()),
                  "score_excess_on_spy": ols_nw(exs, g["spy"].to_numpy()),
                  "score_excess_on_iwm": ols_nw(exs, g["iwm"].to_numpy()),
                  "mean_random_excess_ann": float(ex.mean() * ANN),
                  "mean_iwm_minus_spy_ann": float((g["iwm"] - g["spy"]).mean() * ANN),
                  "first": str(g.index.min().date()), "last": str(g.index.max().date())}
        o = ols[w]
        log(f"OLS {w}: on SPY slope {o['random_excess_on_spy']['slope']:+.3f} (t {o['random_excess_on_spy']['slope_t_nw']:+.2f}) "
            f"alpha {o['random_excess_on_spy']['alpha_ann']:+.4f} (t {o['random_excess_on_spy']['alpha_t_nw']:+.2f}); "
            f"on IWM slope {o['random_excess_on_iwm']['slope']:+.3f} alpha {o['random_excess_on_iwm']['alpha_ann']:+.4f}")
    out["ols"] = ols
    out["ols_note"] = ("per-date net from full-calendar offset chains (each date in exactly one chain); random = 5-draw mean; "
                       "common sample where IWM ret40 is finite; NW(39) t; slope of excess-on-SPY = beta-1; alpha x252/40")
    out["runtime_s"] = time.time() - T0
    OUT_JSON.write_text(json.dumps(out, indent=2, default=float))
    log(f"wrote {OUT_JSON} ({out['runtime_s']:.0f}s)")


if __name__ == "__main__":
    main()
