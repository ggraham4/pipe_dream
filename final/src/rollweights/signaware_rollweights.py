"""
WO-39 (COO, 2026-10-01; "sign-aware rolling weights"; issued as "WO-35" and
renumbered by the COO because that number was already used by options
Phase 2): rule SA252, trial 3 of the "time-varying weights" family.
Pre-registration: final/models/2026-10-01-signaware-rolling-weights.md
(committed before any SA252-vs-control statistic is computed).

SA252 = WO-33's R252 in every respect (trailing 252 matured label dates, refit
every 21 trading days, embargo idx(d)+41 <= idx(refit), 9 factors, the live
rule w_k = s_k * max(0.1, |t_k|-1) / sum_j(...)) EXCEPT: a factor whose
trailing-window NW t is finite and does not have the pre-set sign s_k
(sign(t_k) != s_k, so t_k == 0 counts as opposed) gets the FLOOR raw weight
0.1 in its pre-set direction, exactly what the live rule gives an
un-estimable (NaN-t) factor. Never a flipped sign. Implementation: the opposed
t is set to NaN and screen_insider.fit_weights is called unchanged, so the
renormalization (sum of raw magnitudes over all 9) is the live one, taken over
the SA raw set.

The trailing t's are WO-33's own, read from its committed weight paths
(weight_paths.csv for Step 1, weight_paths_step2.csv for Step 2). No IC is
recomputed and no WO-33 output is rewritten. WO-33 / WO-34 modules are
imported read-only; none of their stage_* functions is called.

Stages:
  --stage build   SA252 paths, hard asserts, binding shares, weight stability,
                  R252-EXP reconcile in both eras. NO SA252-vs-control number.
  --stage score1  Step 1, 2010-01-04..2019-12-31 (RW.hold on this code path).
  --stage score2  Step 2, 2020-01-02..2026-07-30 (hold-out read #17, fit on 2020+).
  --stage swap    descriptive swap-one table, momentum_12_1 + net_issuance_pct.
"""
import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import rollweights as RW                    # noqa: E402  (WO-33 harness, read-only)

SI, DD, DR, V = RW.SI, RW.DD, RW.DR, RW.V
FT, SIGNS = RW.FT, RW.SIGNS
WC = [f"w_{c}" for c in FT]
TC = [f"t_{c}" for c in FT]
OUT = RW.OUT / "signaware"
SA1_CSV = OUT / "sa252_weight_path.csv"
SA2_CSV = OUT / "sa252_weight_path_step2.csv"
BUILD_JSON = OUT / "signaware_build.json"
EVAL1_JSON = OUT / "signaware_eval.json"
EVAL2_JSON = OUT / "signaware_eval_step2.json"
SWAP_JSON = OUT / "signaware_swap.json"
T_BAR = 2.39                                # k=3 Bonferroni (R252, R756 spent)
MIN_OFFSETS = 30
REF = {"A": {"diff": -0.01109435031575894, "offsets_positive": 0},
       "B": {"diff": 0.026025300395121343, "offsets_positive": 38}}
TOL = 1e-4                                  # 0.01 %/yr on the R252-EXP headline (as WO-34)
SWAP_FACTORS = ["momentum_12_1", "net_issuance_pct"]
HOLDOUT_READ = 17
log = RW.log


# ------------------------------------------------------------------ rule
def sa_weights(ts):
    """SA252 weights for one refit from the trailing t's. Returns (w, opposed)."""
    opposed = {c: bool(np.isfinite(ts[c]) and np.sign(ts[c]) != SIGNS[c]) for c in FT}
    ts_sa = {c: (float("nan") if opposed[c] else ts[c]) for c in FT}
    return SI.fit_weights(ts_sa, SIGNS), opposed


def sa_path(r252):
    """SA252 path from WO-33's R252 path rows (their t's). Hard asserts."""
    rows, n_assert, n_all9 = [], 0, 0
    for _, r in r252.iterrows():
        ts = {c: float(r[f"t_{c}"]) for c in FT}
        w_r = SI.fit_weights(ts, SIGNS)
        d = max(abs(w_r[c] - float(r[f"w_{c}"])) for c in FT)
        assert d <= 1e-12, f"R252 weights not reproduced from stored t's at {r['refit_date']}: {d}"
        w, opp = sa_weights(ts)
        if not any(opp.values()):
            n_assert += 1
            dd = max(abs(w[c] - w_r[c]) for c in FT)
            assert dd <= 1e-12, f"SA252 != R252 on an all-agree refit {r['refit_date']}: {dd}"
            n_all9 += int(all(np.isfinite(ts[c]) for c in FT))
        mn = min(abs(w[c]) for c in FT)
        for c in FT:
            assert np.sign(w[c]) == SIGNS[c], "flipped sign"
            if opp[c]:
                assert abs(abs(w[c]) - mn) <= 1e-15, "opposed factor not at the floor"
        assert abs(sum(abs(w[c]) for c in FT) - 1.0) <= 1e-12
        o = {k: r[k] for k in ("refit_date", "refit_idx", "first_used", "last_used", "n_min", "n_seas", "n_mom")}
        o.update({f"w_{c}": w[c] for c in FT}); o.update({f"t_{c}": ts[c] for c in FT})
        o.update({f"opp_{c}": int(opp[c]) for c in FT})
        o["max_abs_diff_vs_R252"] = max(abs(w[c] - w_r[c]) for c in FT)
        rows.append(o)
    p = pd.DataFrame(rows)
    p.insert(0, "arm", "SA252")
    return p, n_assert, n_all9


def binding(p):
    T = p[TC].to_numpy(np.float64)
    sg = np.array([SIGNS[c] for c in FT])
    fin = np.isfinite(T)
    opp = fin & (np.sign(T) != sg)
    eff = opp & (np.abs(T) > 1.0 + SI.FLOOR)    # raw magnitude differs from R252's
    n = len(p)
    return {"n_refits": int(n),
            "share_opposed_all_cells": float(opp.mean()),
            "share_opposed_finite_cells": float(opp.sum() / fin.sum()),
            "share_weight_changed_all_cells": float(eff.mean()),
            "share_refits_any_opposed": float(opp.any(axis=1).mean()),
            "share_refits_SA_differs_from_R252": float((p["max_abs_diff_vs_R252"] > 1e-12).mean()),
            "mean_n_opposed_per_refit": float(opp.sum(axis=1).mean()),
            "per_factor": {c: {"share_opposed": float(opp[:, j].mean()),
                               "share_weight_changed": float(eff[:, j].mean()),
                               "n_finite": int(fin[:, j].sum()),
                               "mean_w_SA252": float(p[f"w_{c}"].mean())}
                           for j, c in enumerate(FT)}}


def read_paths(csv, round_trip=False):
    kw = {"float_precision": "round_trip"} if round_trip else {}
    return pd.read_csv(csv, parse_dates=["refit_date", "first_used", "last_used"], **kw)


def arm(P, a):
    return P[P["arm"] == a].reset_index(drop=True)


# ------------------------------------------------------------------ books
def setup(era):
    if era == "A":
        U, cal, spy = RW.load_v2()
        V.add_ranks(U, FT)
        P = read_paths(RW.PATH_CSV); RW.hold(P["refit_date"].max(), "paths csv")
        S = read_paths(SA1_CSV); RW.hold(S["refit_date"].max(), "sa path csv")
        RW.hold(S["last_used"].dropna().max(), "sa fit window")
        lo = RW.EVAL_START
    else:
        U, cal, spy = RW.load_B()
        V.add_ranks(U, FT)
        P = read_paths(RW.PATH2_CSV); RW.hold2(P["refit_date"].max(), "paths2")
        S = read_paths(SA2_CSV); RW.hold2(S["refit_date"].max(), "sa path2")
        lo = None
    return U, cal, spy, P, S, lo


def run_score(era, book, cal, spy, s, lo, name):
    pk = book.picks(s)
    (RW.hold if era == "A" else RW.hold2)(max(pk), f"picks {name}")
    cal2 = cal
    if lo is not None:
        pk, cal2 = DD.window(pk, cal, lo=lo)
    return {cn: DD.chains(pk, cal2, spy, cost) for cn, cost in (("net", DR.COST_BPS), ("gross", 0.0))}


def run_path(era, book, U, cal, spy, path, lo, name):
    return run_score(era, book, cal, spy, RW.score_path(U, path).to_numpy(), lo, name)


def book_desc(ch):
    net = float(DD.per_offset(ch["net"]).mean()); gross = float(DD.per_offset(ch["gross"]).mean())
    return {"book_vs_spy_net_mean40": net, "book_vs_spy_gross_mean40": gross, "cost_drag_ann": gross - net,
            "mean_f_new": float(np.mean(np.concatenate([x["f_new"] for x in ch["net"]]))),
            "offsets_beating_spy": int((DD.per_offset(ch["net"]) > 0).sum()),
            "per_year_net": DD.per_year(ch["net"])}


def reconcile(era, ch):
    c = RW.compare(ch["R252"]["net"], ch["EXP"]["net"])
    ok = abs(c["mean_diff_ann_40offset"] - REF[era]["diff"]) < TOL and c["offsets_positive"] == REF[era]["offsets_positive"]
    log(f"[{era}] reconcile R252-EXP {c['mean_diff_ann_40offset']:+.6f} ({c['offsets_positive']}/40) "
        f"vs WO-33 {REF[era]['diff']:+.6f} ({REF[era]['offsets_positive']}/40) ok={ok}")
    return {"R252_minus_EXP": c["mean_diff_ann_40offset"], "offsets_positive": c["offsets_positive"],
            "nw39_t": c["nw39_t"], "wo33_ref": REF[era], "tol": TOL, "ok": bool(ok)}


def verdict1(c):
    if c["mean_diff_ann_40offset"] <= 0 or c["loyo_min"] <= 0:
        return "KILL"
    if c["nw39_t"] >= T_BAR and c["offsets_positive"] >= MIN_OFFSETS:
        return "SUCCESS"
    return "MIDDLE"


# ------------------------------------------------------------------ stages
def stage_build():
    T0 = time.time()
    (OUT / "logs").mkdir(parents=True, exist_ok=True)
    res = {"work_order": "WO-39 sign-aware rolling weights (issued as WO-35, renumbered)", "stage": "build",
           "rule": "SA252: R252, but finite t with sign(t) != pre-set sign -> floor raw weight in the pre-set direction",
           "signs": SIGNS, "floor": SI.FLOOR}
    P1 = read_paths(RW.PATH_CSV, round_trip=True)
    RW.hold(P1["refit_date"].max(), "paths csv"); RW.hold(P1["last_used"].dropna().max(), "fit window")
    sa1, na1, n91 = sa_path(arm(P1, "R252"))
    RW.hold(sa1["refit_date"].max(), "sa path"); RW.hold(sa1["last_used"].dropna().max(), "sa fit window")
    sa1.to_csv(SA1_CSV, index=False)
    P2 = read_paths(RW.PATH2_CSV, round_trip=True)
    RW.hold2(P2["refit_date"].max(), "paths2")
    sa2, na2, n92 = sa_path(arm(P2, "R252"))
    sa2.to_csv(SA2_CSV, index=False)
    pre = sa2[sa2["refit_date"] < RW.HOLDOUT].reset_index(drop=True)
    assert len(pre) == len(sa1) and (pre["refit_date"].to_numpy() == sa1["refit_date"].to_numpy()).all()
    d = float(np.abs(pre[WC].to_numpy() - sa1[WC].to_numpy()).max())
    assert d <= 1e-12, f"Step-2 SA path does not continue Step-1: {d}"
    eA = sa1[sa1["refit_date"] >= RW.EVAL_START].reset_index(drop=True)
    eB = sa2[sa2["refit_date"] >= RW.B_START].reset_index(drop=True)
    noopp = lambda p: int((p[[f"opp_{c}" for c in FT]].sum(axis=1) == 0).sum())      # noqa: E731
    all9 = lambda p: int(((p[[f"opp_{c}" for c in FT]].sum(axis=1) == 0)             # noqa: E731
                          & np.isfinite(p[TC].to_numpy(np.float64)).all(axis=1)).sum())
    res["asserts"] = {
        "R252_weights_reproduced_from_stored_t_1e-12": True,
        "SA252_equals_R252_when_no_finite_t_opposes_1e-12": True,
        "sign_never_flipped": True, "opposed_factor_at_floor": True,
        "step2_pre2020_SA_path_equals_step1_maxabs": d,
        "equality_assert_ran_on_refits": {"step1_path_all": na1, "step2_path_all": na2,
                                          "eval_2010_2019": noopp(eA), "eval_2020_2026": noopp(eB)},
        "of_which_all_9_t_finite_and_agree": {"step1_path_all": n91, "step2_path_all": n92,
                                              "eval_2010_2019": all9(eA), "eval_2020_2026": all9(eB)},
        "note": "short_interest_days_to_cover has NaN t before its 2020+ ICs mature (floor under both rules), "
                "so the literal all-9-finite case cannot occur in 2010-2019; the assert runs on every refit "
                "where no finite t opposes its pre-set sign"}
    res["binding"] = {"2010_2019": binding(eA), "2020_2026": binding(eB)}
    res["stability"] = {"2010_2019": {"SA252": RW.stability(sa1), "R252": RW.stability(arm(P1, "R252")),
                                      "EXP": RW.stability(arm(P1, "EXP"))},
                        "2020_2026": {"SA252": RW.stability(sa2, RW.B_START),
                                      "R252": RW.stability(arm(P2, "R252"), RW.B_START),
                                      "EXP": RW.stability(arm(P2, "EXP"), RW.B_START)}}
    BUILD_JSON.write_text(json.dumps(res, indent=1, default=str))
    for e in ("2010_2019", "2020_2026"):
        b = res["binding"][e]
        log(f"[{e}] refits {b['n_refits']}, opposed cells {b['share_opposed_all_cells']:.3f}, weight-changing "
            f"{b['share_weight_changed_all_cells']:.3f}, refits SA!=R252 {b['share_refits_SA_differs_from_R252']:.3f}; "
            f"L1/refit SA {res['stability'][e]['SA252']['mean_L1_change_per_refit']:.3f} "
            f"R252 {res['stability'][e]['R252']['mean_L1_change_per_refit']:.3f}")
    # ---- reconcile R252 - EXP (no SA252 book is built in this stage)
    res["reconcile"] = {}
    for era in ("A", "B"):
        U, cal, spy, P, _, lo = setup(era)
        book = V.Book(U, cal, spy)
        ch = {a: run_path(era, book, U, cal, spy, arm(P, a), lo, a) for a in ("EXP", "R252")}
        res["reconcile"][era] = reconcile(era, ch)
        if era == "B":
            live = float(DD.per_offset(run_score(era, book, cal, spy, SI.composite_score(U, RW.W_LIVE).to_numpy(),
                                                 lo, "LIVE")["net"]).mean())
            res["reconcile"]["B_live"] = {"mean40": live, "ref_wo23_B": RW.REF_B_LIVE,
                                          "ok": bool(abs(live - RW.REF_B_LIVE) < 1e-6)}
        BUILD_JSON.write_text(json.dumps(res, indent=1, default=str))
        del U, book, ch
    res["runtime_s"] = time.time() - T0
    BUILD_JSON.write_text(json.dumps(res, indent=1, default=str))
    assert res["reconcile"]["A"]["ok"] and res["reconcile"]["B"]["ok"] and res["reconcile"]["B_live"]["ok"], "RECONCILE FAIL"
    log(f"wrote {BUILD_JSON} ({res['runtime_s']:.0f}s)")


def stage_score(era):
    T0 = time.time()
    b = json.loads(BUILD_JSON.read_text())
    assert b["reconcile"]["A"]["ok"] and b["reconcile"]["B"]["ok"], "build not validated"
    U, cal, spy, P, S, lo = setup(era)
    book = V.Book(U, cal, spy)
    ch = {"EXP": run_path(era, book, U, cal, spy, arm(P, "EXP"), lo, "EXP"),
          "R252": run_path(era, book, U, cal, spy, arm(P, "R252"), lo, "R252"),
          "SA252": run_path(era, book, U, cal, spy, S, lo, "SA252"),
          "LIVE_REF": run_score(era, book, cal, spy, SI.composite_score(U, RW.W_LIVE).to_numpy(), lo, "LIVE")}
    out = {"work_order": "WO-39 sign-aware rolling weights (issued as WO-35, renumbered)", "step": 1 if era == "A" else 2,
           "prereg": "final/models/2026-10-01-signaware-rolling-weights.md",
           "window": (f"{RW.EVAL_START.date()}..{RW.END.date()}" if era == "A" else f"{RW.B_START.date()}..{RW.B_END.date()}"),
           "cost_bps": DR.COST_BPS, "control": "EXP", "t_bar": T_BAR, "min_offsets": MIN_OFFSETS,
           "family": "time-varying weights; trial 3 (R252, R756 spent)"}
    if era == "B":
        out["holdout_read"] = HOLDOUT_READ
    out["reconcile"] = reconcile(era, ch)
    assert out["reconcile"]["ok"], "RECONCILE FAIL"
    c = RW.compare(ch["SA252"]["net"], ch["EXP"]["net"])
    if era == "A":
        c["verdict"] = verdict1(c)
        log(f"[A] SA252 vs EXP: diff {c['mean_diff_ann_40offset']:+.4f}/yr t {c['nw39_t']:+.2f} "
            f"offsets+ {c['offsets_positive']}/40 LOYO min {c['loyo_min']:+.4f} -> {c['verdict']}")
    else:
        s1 = json.loads(EVAL1_JSON.read_text())["primary"]["SA252_vs_EXP"]["verdict"]
        c["ex2020"] = c["loyo_by_dropped_year"].get(2020)
        c["step2_pass"] = bool(c["mean_diff_ann_40offset"] > 0 and c["offsets_positive"] >= MIN_OFFSETS
                               and c["ex2020"] is not None and c["ex2020"] > 0)
        c["step1_verdict"] = s1
        c["promote_candidate"] = bool(s1 == "SUCCESS" and c["step2_pass"])
        log(f"[B] SA252 vs EXP: diff {c['mean_diff_ann_40offset']:+.4f}/yr t {c['nw39_t']:+.2f} "
            f"offsets+ {c['offsets_positive']}/40 LOYO min {c['loyo_min']:+.4f} ex2020 {c['ex2020']:+.4f} "
            f"-> step2_pass {c['step2_pass']} promote {c['promote_candidate']} (step 1 {s1})")
    out["primary"] = {"SA252_vs_EXP": c}
    out["reference_descriptive"] = {
        "SA252_vs_R252": RW.compare(ch["SA252"]["net"], ch["R252"]["net"]),
        "SA252_vs_LIVE": RW.compare(ch["SA252"]["net"], ch["LIVE_REF"]["net"]),
        "R252_vs_EXP": RW.compare(ch["R252"]["net"], ch["EXP"]["net"]),
        "LIVE_vs_EXP": RW.compare(ch["LIVE_REF"]["net"], ch["EXP"]["net"])}
    out["books"] = {k: book_desc(v) for k, v in ch.items()}
    if era == "B":
        out["books"]["live_ref_wo23_B"] = RW.REF_B_LIVE
        assert abs(out["books"]["LIVE_REF"]["book_vs_spy_net_mean40"] - RW.REF_B_LIVE) < 1e-6
    e = "2010_2019" if era == "A" else "2020_2026"
    out["binding"] = b["binding"][e]; out["stability"] = b["stability"][e]
    out["runtime_s"] = time.time() - T0
    fn = EVAL1_JSON if era == "A" else EVAL2_JSON
    fn.write_text(json.dumps(out, indent=1, default=float))
    for k in ("SA252_vs_R252", "SA252_vs_LIVE"):
        r = out["reference_descriptive"][k]
        log(f"[{era}] {k}: {r['mean_diff_ann_40offset']:+.4f}/yr t {r['nw39_t']:+.2f} {r['offsets_positive']}/40")
    for k in ("SA252", "R252", "EXP", "LIVE_REF"):
        d = out["books"][k]
        log(f"[{era}] {k:8s} vs SPY net {d['book_vs_spy_net_mean40']:+.4f} cost {d['cost_drag_ann']:.4f} f_new {d['mean_f_new']:.3f}")
    log(f"wrote {fn} ({out['runtime_s']:.0f}s)")


def renorm(p):
    p = p.copy()
    p[WC] = p[WC].div(p[WC].abs().sum(axis=1), axis=0)
    return p


def stage_swap():
    assert EVAL1_JSON.exists() and EVAL2_JSON.exists(), "run score1/score2 first"
    res = {"work_order": "WO-39 sign-aware rolling weights (issued as WO-35, renumbered)", "stage": "swap (descriptive, post hoc, no verdict)",
           "definitions": {"swapin": "EXP path with factor f's weight column replaced by SA252's, rows rescaled to sum|w|=1; minus EXP",
                           "swapout": "SA252 path with factor f's weight column replaced by EXP's, rescaled; minus EXP",
                           "swapout_loss": "(SA252 - EXP) - (swapout - EXP)"},
           "eras": {}}
    for era in ("A", "B"):
        T0 = time.time()
        U, cal, spy, P, S, lo = setup(era)
        book = V.Book(U, cal, spy)
        exp = arm(P, "EXP")
        assert (exp["refit_date"].to_numpy() == S["refit_date"].to_numpy()).all()
        ctl = run_path(era, book, U, cal, spy, exp, lo, "EXP")
        tot = RW.compare(run_path(era, book, U, cal, spy, S, lo, "SA252")["net"], ctl["net"])["mean_diff_ann_40offset"]
        er = {"SA252_minus_EXP": tot, "factors": {}}
        for f in SWAP_FACTORS:
            a = exp.copy(); a[f"w_{f}"] = S[f"w_{f}"].to_numpy()
            b = S.copy(); b[f"w_{f}"] = exp[f"w_{f}"].to_numpy()
            o = {}
            for nm, p in (("swapin", renorm(a)), ("swapout", renorm(b))):
                c = RW.compare(run_path(era, book, U, cal, spy, p, lo, f"{nm}_{f}")["net"], ctl["net"])
                o[nm] = {k: c[k] for k in ("mean_diff_ann_40offset", "offsets_positive", "nw39_t", "loyo_min")}
                log(f"[{era}] {nm}_{f}: {c['mean_diff_ann_40offset']:+.4f}/yr t {c['nw39_t']:+.2f} {c['offsets_positive']}/40")
            o["swapout_loss"] = tot - o["swapout"]["mean_diff_ann_40offset"]
            q = S if lo is None else S[S["refit_date"] >= lo]
            qe = exp if lo is None else exp[exp["refit_date"] >= lo]
            if lo is None:
                q = q[q["refit_date"] >= RW.B_START]; qe = qe[qe["refit_date"] >= RW.B_START]
            o["mean_w_SA252"] = float(q[f"w_{f}"].mean()); o["mean_w_EXP"] = float(qe[f"w_{f}"].mean())
            er["factors"][f] = o
            res["eras"][era] = er
            SWAP_JSON.write_text(json.dumps(res, indent=1, default=float))
        er["runtime_s"] = time.time() - T0
        SWAP_JSON.write_text(json.dumps(res, indent=1, default=float))
    log(f"wrote {SWAP_JSON}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", required=True, choices=["build", "score1", "score2", "swap"])
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    {"build": stage_build, "score1": lambda: stage_score("A"), "score2": lambda: stage_score("B"),
     "swap": stage_swap}[a.stage]()
