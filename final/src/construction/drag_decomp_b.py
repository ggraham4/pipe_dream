"""
WO-24 (COO): WO-21's universe / construction / cost / selection decomposition
on period B = 2020-01-02 .. 2026-07-30 (last matured 40d label, = WO-23).
Descriptive, no trial. Hold-out read #6 (Gabe's standing OK 2026-09-27 for
unfitted 2020-2026 reads): frozen live weights only, nothing fit on 2020+.
Pre-registration: final/models/2026-09-28-construction-drag-2020s.md.

Models: icw8 (ICW.PRODUCTION_WEIGHTS) and icw9_seas (ICW.PRODUCTION_WEIGHTS_V9_SEAS),
cap150, v2 col c, decile_volq, 40 offsets, net 15 bp.

Stages (separate processes: importing model_audit_wo23 imports screen_seas,
which sets V.COL / V.SIGNS9 globally; WO-21 never imported it):
  --stage A   rerun WO-21 drag_decomp.main() unmodified (outputs -> /tmp) and
              compare every numeric leaf with the committed drag_decomp.json (1e-9)
  --stage B   reconcile icw8 / icw9_seas B to WO-23 (1e-6), then decompose
Output: final/out/construction/drag_decomp_b.json (A result stored under
"period_A_reproduce"; stage B requires it to have passed).
"""
import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
SRC = HERE.parent
FINAL = HERE.parents[1]
OUT_DIR = FINAL / "out" / "construction"
OUT_JSON = OUT_DIR / "drag_decomp_b.json"
WO21_JSON = OUT_DIR / "drag_decomp.json"
WO23_JSON = FINAL / "out" / "audit" / "model_audit_wo23.json"
TMP = Path("/tmp/wo24_drag_decomp_b")
B_LO, B_HI = pd.Timestamp("2020-01-02"), pd.Timestamp("2026-07-30")
SEEDS = [2000 + k for k in range(5)]
TOL_B = 1e-6
TOL_A = 1e-9


def _load_out():
    return json.loads(OUT_JSON.read_text()) if OUT_JSON.exists() else {}


def _save_out(d):
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(d, indent=2, default=float))


# ------------------------------------------------------------------ stage A
def _leaves(x, path=""):
    if isinstance(x, dict):
        for k, v in x.items():
            yield from _leaves(v, f"{path}/{k}")
    elif isinstance(x, list):
        for i, v in enumerate(x):
            yield from _leaves(v, f"{path}[{i}]")
    else:
        yield path, x


def stage_a():
    sys.path.insert(0, str(HERE))
    import drag_decomp as DD
    TMP.mkdir(parents=True, exist_ok=True)
    DD.OUT_DIR = TMP
    DD.OUT_JSON = TMP / "drag_decomp.json"
    DD.VAL_JSON = TMP / "drag_decomp_validate.json"
    argv = sys.argv
    sys.argv = [argv[0]]
    t0 = time.time()
    try:
        DD.main()
    finally:
        sys.argv = argv
    got = json.loads(DD.OUT_JSON.read_text())
    ref = json.loads(WO21_JSON.read_text())
    gl, rl = dict(_leaves(got)), dict(_leaves(ref))
    skip = {"/runtime_s"}
    keys = sorted((set(gl) | set(rl)) - skip)
    missing = [k for k in keys if k not in gl or k not in rl]
    bad, maxdiff, n_num = [], 0.0, 0
    for k in keys:
        if k in missing:
            continue
        a, b = gl[k], rl[k]
        if isinstance(a, (int, float)) and not isinstance(a, bool) and isinstance(b, (int, float)) and not isinstance(b, bool):
            n_num += 1
            if not (np.isnan(a) and np.isnan(b)):
                d = abs(a - b); maxdiff = max(maxdiff, d)
                if d > TOL_A:
                    bad.append((k, a, b))
        elif a != b:
            bad.append((k, a, b))
    res = {"reference": str(WO21_JSON.relative_to(FINAL.parent)), "numeric_leaves": n_num,
           "max_abs_diff": maxdiff, "tol": TOL_A, "missing_keys": missing, "mismatches": bad[:20],
           "n_mismatch": len(bad), "wo21_reconcile_all_pass": bool(got["reconcile"]["all_pass"]),
           "pass": bool(not bad and not missing and got["reconcile"]["all_pass"]),
           "runtime_s": time.time() - t0}
    out = _load_out(); out["period_A_reproduce"] = res; _save_out(out)
    print(json.dumps({k: v for k, v in res.items() if k != "mismatches"}, indent=1), flush=True)
    assert res["pass"], "PERIOD-A REPRODUCE FAIL"


# ------------------------------------------------------------------ stage B
def stage_b():
    sys.path.insert(0, str(SRC / "audit"))
    sys.path.insert(0, str(HERE))
    import model_audit_wo23 as MA          # imports screen_seas (V.COL/SIGNS9), as WO-23
    import drag_decomp as DD               # chains / per_offset / loyo_vec / per_year / ols_nw / noscore_picks
    V, SI, DR = MA.V, MA.SI, MA.DR
    log = V.log
    ANN = DD.ANN
    T0 = time.time()
    out = _load_out()
    assert out.get("period_A_reproduce", {}).get("pass"), "run --stage A first (must pass)"

    wo23 = json.loads(WO23_JSON.read_text())["B"]["theoretical"]
    ref = {"icw8": wo23["icw8"]["excess_cagr_vs_spy_mean40"], "icw9_seas": wo23["icw9_seas"]["excess_cagr_vs_spy_mean40"]}
    W = {"icw8": dict(MA.W8), "icw9_seas": dict(MA.W9)}
    # frozen constants only (hold-out read #6: nothing fit on 2020+)
    assert W["icw8"] == dict(MA.ICW.PRODUCTION_WEIGHTS) and W["icw9_seas"] == dict(MA.ICW.PRODUCTION_WEIGHTS_V9_SEAS)

    U, all_dates, spy = MA.load_theo("B", "cap150")
    dts = pd.DatetimeIndex(all_dates)
    assert dts.min() >= B_LO and dts.max() <= B_HI and U["date"].min() >= B_LO and U["date"].max() <= B_HI
    assert spy.index.min() >= B_LO and spy.index.max() <= B_HI
    V.add_ranks(U, MA.FT)
    book = V.Book(U, all_dates, spy)
    score = {m: SI.composite_score(U, w).to_numpy() for m, w in W.items()}

    # ---- reconcile gate (same score arrays the decomposition uses), before any random draw
    pk = {("score", m): book.picks(score[m]) for m in W}
    rec = {}
    for m in W:
        got = DR.backtest(pk[("score", m)], all_dates, spy)["excess_cagr_vs_spy_mean40"]
        rec[m] = {"got": got, "wo23": ref[m], "diff": got - ref[m], "ok": bool(abs(got - ref[m]) < TOL_B)}
        log(f"reconcile B {m}: {got:+.9f} vs WO-23 {ref[m]:+.9f} diff {got - ref[m]:+.2e} {'OK' if rec[m]['ok'] else 'FAIL'}")
    out["period_B_reconcile"] = {"reference": str(WO23_JSON.relative_to(FINAL.parent)), "tol": TOL_B, "models": rec,
                                 "all_pass": bool(all(r["ok"] for r in rec.values()))}
    _save_out(out)
    assert out["period_B_reconcile"]["all_pass"], "PERIOD-B RECONCILE FAIL: stop, no decomposition"

    # ---- books
    pk[("noscore", None)] = DD.noscore_picks(book)
    for m in W:
        for k, sd in enumerate(SEEDS):
            pk[(f"rand{k}", m)] = book.picks(V.shuffle_within_date(U.assign(_s=score[m]), "_s", sd))
    log(f"books built ({time.time()-T0:.0f}s)")
    R = [f"rand{k}" for k in range(len(SEEDS))]

    ch, vec, fnew = {}, {}, {}
    for key, p_ in pk.items():
        for cn, cost in (("net", DR.COST_BPS), ("gross", 0.0)):
            c = DD.chains(p_, all_dates, spy, cost)
            ch[key + (cn,)] = c
            vec[key + (cn,)] = DD.per_offset(c)
        fnew[key] = float(np.mean(np.concatenate([c["f_new"] for c in ch[key + ("net",)]])))
        assert abs(vec[key + ("net",)].mean() - DR.backtest(p_, all_dates, spy)["excess_cagr_vs_spy_mean40"]) < 1e-12, f"oracle {key}"

    ns_net, ns_gross = float(vec[("noscore", None, "net")].mean()), float(vec[("noscore", None, "gross")].mean())
    years_all = None
    models = {}
    for m in W:
        mr = {r: float(vec[(r, m, "net")].mean()) for r in R}
        mg = {r: float(vec[(r, m, "gross")].mean()) for r in R}
        rnd_net, rnd_gross = float(np.mean(list(mr.values()))), float(np.mean(list(mg.values())))
        sc_net, sc_gross = float(vec[("score", m, "net")].mean()), float(vec[("score", m, "gross")].mean())
        T = rnd_net
        comp = {"T_random_net_minus_spy": T, "a_universe_noscore_net_minus_spy": ns_net,
                "b_construction_random_net_minus_noscore_net": rnd_net - ns_net,
                "c_costs_random_net_minus_random_gross": rnd_net - rnd_gross}
        shares = {"a": ns_net / T, "b": (rnd_net - ns_net) / T, "c": (rnd_net - rnd_gross) / T}
        gross3 = {"a_g_noscore_gross_minus_spy": ns_gross, "b_g_random_gross_minus_noscore_gross": rnd_gross - ns_gross,
                  "c_random_net_minus_random_gross": rnd_net - rnd_gross}
        gross3["shares"] = {"a_g": ns_gross / T, "b_g": (rnd_gross - ns_gross) / T, "c": (rnd_net - rnd_gross) / T}
        assert abs(sum(v for k, v in gross3.items() if k != "shares") - T) < 1e-12
        per_draw = [{"seed": SEEDS[i], "net": mr[r], "gross": mg[r], "b": mr[r] - ns_net, "c": mr[r] - mg[r],
                     "share_a": ns_net / mr[r], "share_b": (mr[r] - ns_net) / mr[r], "share_c": (mr[r] - mg[r]) / mr[r]}
                    for i, r in enumerate(R)]
        spread = {k: {"min": float(np.min([d[k] for d in per_draw])), "max": float(np.max([d[k] for d in per_draw])),
                      "sd": float(np.std([d[k] for d in per_draw]))} for k in ("net", "gross", "b", "c", "share_a", "share_b", "share_c")}
        score_split = {"T_score_net_minus_spy": sc_net, "a_universe": ns_net, "score_net_minus_noscore_net": sc_net - ns_net,
                       "score_costs_net_minus_gross": sc_net - sc_gross,
                       "score_gross_minus_noscore_gross": sc_gross - ns_gross}
        # selection detail: vs random (5-draw mean per offset) and vs noscore
        rnd_off = {cn: np.mean([vec[(r, m, cn)] for r in R], axis=0) for cn in ("net", "gross")}
        years, lm_s = DD.loyo_vec(ch[("score", m, "net")])
        _, lm_n = DD.loyo_vec(ch[("noscore", None, "net")])
        lm_r = np.mean([DD.loyo_vec(ch[(r, m, "net")])[1] for r in R], axis=0)
        years_all = years

        def sel_stats(off, lm):
            gl = lm.mean(axis=0)
            return {"mean40": float(off.mean()), "sd40": float(off.std()), "offsets_positive": int((off > 0).sum()),
                    "loyo_min": float(gl.min()), "loyo_min_dropped_year": int(years[int(gl.argmin())]),
                    "loyo_max": float(gl.max()), "loyo_max_dropped_year": int(years[int(gl.argmax())]),
                    "loyo_by_dropped_year": {int(y): float(v) for y, v in zip(years, gl)}}
        sel = {"vs_random_net": sel_stats(vec[("score", m, "net")] - rnd_off["net"], lm_s - lm_r),
               "vs_random_gross_mean40": float((vec[("score", m, "gross")] - rnd_off["gross"]).mean()),
               "vs_noscore_net": sel_stats(vec[("score", m, "net")] - vec[("noscore", None, "net")], lm_s - lm_n),
               "vs_noscore_gross_mean40": float((vec[("score", m, "gross")] - vec[("noscore", None, "gross")]).mean())}
        sc_off = vec[("score", m, "net")]
        trig = {"a_ge_2/3": bool(shares["a"] >= 2 / 3), "b_ge_2/3": bool(shares["b"] >= 2 / 3), "c_ge_1/3": bool(shares["c"] >= 1 / 3)}
        sg = gross3["shares"]
        trig_g = {"a_ge_2/3": bool(sg["a_g"] >= 2 / 3), "b_ge_2/3": bool(sg["b_g"] >= 2 / 3), "c_ge_1/3": bool(sg["c"] >= 1 / 3)}
        if T >= 0:
            outcome = "no drag, report only"
        else:
            o = [n for k, n in (("a_ge_2/3", "universe bet"), ("b_ge_2/3", "construction trial"),
                                ("c_ge_1/3", "turnover work order")) if trig[k]]
            outcome = " + ".join(o) if o else "mixed (report only)"
        per_draw_outcomes = []
        for d in per_draw:
            o = [n for ok, n in ((d["share_a"] >= 2 / 3, "universe bet"), (d["share_b"] >= 2 / 3, "construction trial"),
                                 (d["share_c"] >= 1 / 3, "turnover work order")) if ok]
            per_draw_outcomes.append(" + ".join(o) if o else "mixed")
        models[m] = {"books": {"score_net": sc_net, "score_gross": sc_gross, "noscore_net": ns_net, "noscore_gross": ns_gross,
                               "random_net_mean": rnd_net, "random_gross_mean": rnd_gross,
                               "score_sd40": float(sc_off.std()), "score_offsets_positive": int((sc_off > 0).sum())},
                     "decomp_net_primary": comp, "shares_primary": shares, "decomp_gross_secondary": gross3,
                     "random_per_draw": per_draw, "random_draw_spread": spread, "score_split": score_split,
                     "selection": sel,
                     "mean_f_new": {"score": fnew[("score", m)], "noscore": fnew[("noscore", None)],
                                    "random_mean": float(np.mean([fnew[(r, m)] for r in R]))},
                     "decision_map": {"primary_net_triggers": trig, "secondary_gross_triggers": trig_g,
                                      "disagreement_basis": {k: trig[k] != trig_g[k] for k in trig},
                                      "outcome": outcome, "per_draw_outcomes": per_draw_outcomes}}
        log(f"{m}: T {T:+.4f} a {ns_net:+.4f} b {rnd_net-ns_net:+.4f} c {rnd_net-rnd_gross:+.4f} | score {sc_net:+.4f} "
            f"sel/rand {sel['vs_random_net']['mean40']:+.4f} sel/ns {sel['vs_noscore_net']['mean40']:+.4f} -> {outcome}")

    dm = {"trigger_model": "icw8", "outcome": models["icw8"]["decision_map"]["outcome"],
          "icw9_seas_outcome": models["icw9_seas"]["decision_map"]["outcome"],
          "model_disagreement": models["icw8"]["decision_map"]["primary_net_triggers"] != models["icw9_seas"]["decision_map"]["primary_net_triggers"]}

    # ---- per calendar year (B calendar = full-calendar chains here)
    py = {k: DD.per_year(v) for k, v in ch.items()}
    tab = {}
    for m in W:
        tm = {}
        for y in sorted(py[("score", m, "net")]):
            rn = np.mean([py[(r, m, "net")][y] for r in R]); rg = np.mean([py[(r, m, "gross")][y] for r in R])
            nn, ng = py[("noscore", None, "net")][y], py[("noscore", None, "gross")][y]
            sn, sg_ = py[("score", m, "net")][y], py[("score", m, "gross")][y]
            tm[y] = {"T_random": rn, "a": nn, "b": rn - nn, "c": rn - rg, "a_g": ng, "b_g": rg - ng,
                     "score_net": sn, "score_minus_noscore": sn - nn, "score_c": sn - sg_, "selection_net": sn - rn,
                     "random_net_draw_range": [float(min(py[(r, m, "net")][y] for r in R)),
                                               float(max(py[(r, m, "net")][y] for r in R))]}
        tab[m] = tm

    # ---- OLS on SPY (IWM does not cover B: IWM.csv ends 2019-12-31; not in outcome_cache_v2)
    def per_date(c_):
        s = {}
        for c in c_:
            for d, n in zip(c["date"], c["net"]):
                assert d not in s
                s[d] = n
        return pd.Series(s).sort_index()
    df = pd.DataFrame({"noscore": per_date(ch[("noscore", None, "net")])})
    for m in W:
        df[f"rnd_{m}"] = pd.concat([per_date(ch[(r, m, "net")]) for r in R], axis=1).mean(axis=1)
        df[f"score_{m}"] = per_date(ch[("score", m, "net")])
    df["spy"] = spy.reindex(df.index).astype(np.float64)
    df = df.dropna()
    x = df["spy"].to_numpy()
    ols = {"n": int(len(df)), "first": str(df.index.min().date()), "last": str(df.index.max().date()),
           "noscore_excess_on_spy": DD.ols_nw((df["noscore"] - df["spy"]).to_numpy(), x),
           "noscore_raw_on_spy": DD.ols_nw(df["noscore"].to_numpy(), x),
           "mean_noscore_excess_ann": float((df["noscore"] - df["spy"]).mean() * ANN)}
    for m in W:
        ols[f"random_{m}_excess_on_spy"] = DD.ols_nw((df[f"rnd_{m}"] - df["spy"]).to_numpy(), x)
        ols[f"score_{m}_excess_on_spy"] = DD.ols_nw((df[f"score_{m}"] - df["spy"]).to_numpy(), x)
    # fix 1/1: the data dir is gitignored and lives in the main checkout (= hedged_composite.IWM_CSV)
    import hedged_composite as HC
    iwm = pd.read_csv(HC.IWM_CSV, usecols=["date"], parse_dates=["date"])
    iwm_note = {"iwm_csv_last": str(iwm["date"].max().date()), "covers_B": bool(iwm["date"].max() >= B_HI),
                "note": "IWM.csv ends 2019-12-31 and IWM is not in outcome_cache_v2 (SPY, USMV only); the Sharadar panel is "
                        "stocks only. No IWM OLS for B; no data pulled under WO-24."}
    assert not iwm_note["covers_B"]

    out.update({"work_order": "WO-24", "holdout_read": 6, "prereg": "final/models/2026-09-28-construction-drag-2020s.md",
                "period_B": [str(B_LO.date()), str(B_HI.date())], "calendar_dates": len(all_dates),
                "universe_rows": int(len(U)), "cost_bps": DR.COST_BPS, "seeds": SEEDS,
                "weights": W, "models": models, "decision_map": dm, "loyo_years": [int(y) for y in years_all],
                "per_year": tab, "ols_spy": ols, "ols_iwm": iwm_note,
                "ols_note": "per-date net from full-calendar offset chains; random = 5-draw mean; NW(39) t; slope of excess-on-SPY = beta-1; alpha x252/40",
                "runtime_s_B": time.time() - T0})
    _save_out(out)
    log(f"decision map: {dm}")
    log(f"wrote {OUT_JSON} ({time.time()-T0:.0f}s)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", required=True, choices=["A", "B"])
    a = ap.parse_args()
    stage_a() if a.stage == "A" else stage_b()


if __name__ == "__main__":
    main()
