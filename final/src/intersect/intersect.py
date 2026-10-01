"""
WO-44 (COO): does the intersection of the live icw9_seas picks (L) and the
R252 rolling-weights picks (R) beat the live book?
Pre-registration: final/models/2026-10-01-intersection-book.md (committed
before any INT-vs-L number is computed).

Research backtest only. Reads panels, writes JSON. No broker, no orders.

Harness = WO-33's (final/src/rollweights/rollweights.py, imported read-only):
v2 col c cap150, decile_volq, 40 offsets, h=40, net 15 bp.
  era A  2010-01-04..2019-12-31  (Step-1 universe + weight_paths.csv)
  era B  2020-01-02..2026-07-30  (Step-2 universe + weight_paths_step2.csv)
         hold-out read #20, unfitted (nothing new is fitted here).

Stages:
  --stage build   reconcile gates (hard asserts) + weighted pick sets cached
                  to /tmp. No INT-vs-L statistic.
  --stage score   primary + descriptive + size-matched null (run ONLY after
                  the pre-reg commit).
"""
import argparse
import json
import pickle
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "rollweights"))
import rollweights as RW                 # noqa: E402  (read-only import)

V, SI, DD, DR, C = RW.V, RW.SI, RW.DD, RW.DR, RW.C
OUT = HERE.parents[1] / "out" / "intersect"
BUILD_JSON = OUT / "intersect_build.json"
EVAL_JSON = OUT / "intersect_eval.json"
CACHE = Path("/tmp/wo44_intersect_picks.pkl")     # regenerable, never committed
MIN_INT = 10
N_NULL = 100
NULL_SEED0 = 4400
ANN = RW.ANN
REF_R252_EXP_A_PCT = -1.109
REF_R252_EXP_B_PCT = 2.603
log = V.log


# ------------------------------------------------------------------ picks
def wpicks(book, score):
    """Book.picks, but keeping per-name inverse-vol weights and returns.
    {date: (tickers, inv_vol, ret)} for names with a finite 40d return."""
    score = np.asarray(score, dtype=np.float64)
    out = {}
    for d, s, e in book.sl:
        if e - s < C.N_VOL_QUINTILES * 4:
            continue
        g = pd.DataFrame({"volatility_60": book.vol[s:e]})
        sc = pd.DataFrame({"ticker": book.tick[s:e], "composite": score[s:e]})
        pk = C.pick_decile_volq(g, sc)
        if not pk:
            continue
        pos = {t: i for i, t in enumerate(book.tick[s:e])}
        ii = np.array([pos[t] for t, _ in pk])
        ret = book.ret[s:e][ii]
        vol = book.vol[s:e][ii]
        ok = np.isfinite(ret)
        if not ok.any():
            continue
        iv = 1.0 / np.maximum(vol[ok], 1e-4)
        out[d] = (np.array([t for t, _ in pk], dtype=object)[ok], iv, ret[ok])
    return out


def realise(t, iv, ret, mask=None):
    if mask is not None:
        t, iv, ret = t[mask], iv[mask], ret[mask]
    w = iv / iv.sum()
    return float((w * (1.0 + ret)).sum() - 1.0), set(t)


def assert_same(wp, ref, what):
    assert set(wp) == set(ref), f"{what}: date sets differ"
    for d, (g, names) in ref.items():
        g2, n2 = realise(*wp[d])
        assert n2 == names, f"{what}: names differ {d}"
        assert abs(g2 - g) < 1e-12, f"{what}: gross differs {d} {g2} {g}"


# ------------------------------------------------------------------ build
def era_build(tag, U, cal, spy, P, lo):
    V.add_ranks(U, RW.FT)
    book = V.Book(U, cal, spy)
    sc = {"L": SI.composite_score(U, RW.W_LIVE).to_numpy()}
    for arm in ("R252", "EXP"):
        sc[arm] = RW.score_path(U, P[P["arm"] == arm].reset_index(drop=True)).to_numpy()
    ref = {k: book.picks(v) for k, v in sc.items()}
    wp = {k: wpicks(book, sc[k]) for k in ("L", "R252")}
    for k in wp:
        assert_same(wp[k], ref[k], f"{tag} {k}")
    if lo is not None:
        sub = {k: DD.window(v, cal, lo=lo) for k, v in ref.items()}
        dates = sub["L"][1]
        ch = {k: DD.chains(sub[k][0], dates, spy, DR.COST_BPS) for k in ref}
    else:
        dates = cal
        ch = {k: DD.chains(ref[k], dates, spy, DR.COST_BPS) for k in ref}
    c = RW.compare(ch["R252"], ch["EXP"])
    dset = set(dates)
    nL = np.array([len(v[0]) for d, v in wp["L"].items() if d in dset])
    nR = np.array([len(v[0]) for d, v in wp["R252"].items() if d in dset])
    res = {"L_vs_spy_mean40": float(DD.per_offset(ch["L"]).mean()),
           "R252_vs_spy_mean40": float(DD.per_offset(ch["R252"]).mean()),
           "R252_minus_EXP": c["mean_diff_ann_40offset"], "R252_minus_EXP_offsets_positive": c["offsets_positive"],
           "weighted_picks_equal_Book_picks": True,
           "n_dates": int(len(nL)),
           "L_names": {"mean": float(nL.mean()), "min": int(nL.min()), "max": int(nL.max())},
           "R_names": {"mean": float(nR.mean()), "min": int(nR.min()), "max": int(nR.max())}}
    wp = {k: {d: v for d, v in x.items() if d in dset} for k, x in wp.items()}
    return res, {"wp": wp, "dates": dates, "spy": spy}


def stage_build():
    T0 = time.time()
    OUT.mkdir(parents=True, exist_ok=True)
    res = {"work_order": "WO-44", "stage": "build", "holdout_read": 20}
    cache = {}
    # ---- era A
    U, cal, spy = RW.load_v2()
    P = pd.read_csv(RW.PATH_CSV, parse_dates=["refit_date"])
    rA, cache["A"] = era_build("A", U, cal, spy, P, RW.EVAL_START)
    refA = json.loads(RW.EVAL_JSON.read_text())["primary"]["R252"]
    rA["ref_R252_minus_EXP"] = refA["mean_diff_ann_40offset"]
    rA["ok"] = bool(abs(rA["R252_minus_EXP"] - refA["mean_diff_ann_40offset"]) < 1e-9
                    and round(rA["R252_minus_EXP"] * 100, 3) == REF_R252_EXP_A_PCT
                    and rA["R252_minus_EXP_offsets_positive"] == 0)
    res["A"] = rA
    log(f"[A] R252-EXP {rA['R252_minus_EXP']*100:+.4f}%/yr (ref {REF_R252_EXP_A_PCT}); |L| mean {rA['L_names']['mean']:.1f} "
        f"min {rA['L_names']['min']} ({time.time()-T0:.0f}s)")
    BUILD_JSON.write_text(json.dumps(res, indent=2, default=float))
    assert rA["ok"], "RECONCILE FAIL (A)"
    del U
    # ---- era B
    U, cal, spy = RW.load_B()
    P = pd.read_csv(RW.PATH2_CSV, parse_dates=["refit_date"])
    rB, cache["B"] = era_build("B", U, cal, spy, P, None)
    refB = json.loads(RW.EVAL2_JSON.read_text())["primary"]["R252"]
    rB["ref_R252_minus_EXP"] = refB["mean_diff_ann_40offset"]; rB["ref_L_vs_spy"] = RW.REF_B_LIVE
    rB["ok"] = bool(abs(rB["L_vs_spy_mean40"] - RW.REF_B_LIVE) < 1e-6
                    and round(rB["L_vs_spy_mean40"] * 100, 3) == -2.016
                    and abs(rB["R252_minus_EXP"] - refB["mean_diff_ann_40offset"]) < 1e-9
                    and round(rB["R252_minus_EXP"] * 100, 3) == REF_R252_EXP_B_PCT
                    and rB["R252_minus_EXP_offsets_positive"] == 38)
    res["B"] = rB
    log(f"[B] L vs SPY {rB['L_vs_spy_mean40']*100:+.4f} (ref -2.016); R252-EXP {rB['R252_minus_EXP']*100:+.4f} "
        f"(ref {REF_R252_EXP_B_PCT}); |L| mean {rB['L_names']['mean']:.1f} min {rB['L_names']['min']} ({time.time()-T0:.0f}s)")
    res["runtime_s"] = time.time() - T0
    BUILD_JSON.write_text(json.dumps(res, indent=2, default=float))
    assert rB["ok"], "RECONCILE FAIL (B)"
    with open(CACHE, "wb") as f:
        pickle.dump(cache, f)
    log(f"wrote {BUILD_JSON}; cache {CACHE}")


# ------------------------------------------------------------------ score
def build_books(wp):
    L, R = wp["L"], wp["R252"]
    assert set(L) == set(R), "L and R date sets differ"
    bk = {k: {} for k in ("L", "R", "INT", "L_only", "R_only", "UNION")}
    rows = []
    for d in sorted(L):
        lt, liv, lr = L[d]; rt, riv, rr = R[d]
        inR = np.isin(lt, rt); inL = np.isin(rt, lt)
        n = int(inR.sum())
        fb = n < MIN_INT
        bk["L"][d] = realise(lt, liv, lr); bk["R"][d] = realise(rt, riv, rr)
        bk["INT"][d] = bk["L"][d] if fb else realise(lt, liv, lr, inR)
        if (~inR).any():
            bk["L_only"][d] = realise(lt, liv, lr, ~inR)
        if (~inL).any():
            bk["R_only"][d] = realise(rt, riv, rr, ~inL)
        bk["UNION"][d] = realise(np.r_[lt, rt[~inL]], np.r_[liv, riv[~inL]], np.r_[lr, rr[~inL]])
        rows.append((d, len(lt), len(rt), n, fb))
    cnt = pd.DataFrame(rows, columns=["date", "nL", "nR", "nINT", "fallback"])
    return bk, cnt


def null_book(wp, cnt, seed):
    rng = np.random.default_rng(seed)
    L = wp["L"]
    out = {}
    for d, n, fb in zip(cnt["date"], cnt["nINT"], cnt["fallback"]):
        lt, liv, lr = L[d]
        if fb:
            out[d] = realise(lt, liv, lr)
        else:
            m = np.zeros(len(lt), bool); m[rng.choice(len(lt), size=n, replace=False)] = True
            out[d] = realise(lt, liv, lr, m)
    return out


def risk(ch):
    dds, worst = [], []
    for c in ch:
        eq = np.cumprod(1.0 + c["net"])
        pk = np.maximum.accumulate(np.r_[1.0, eq])[1:]
        dds.append(float((eq / pk - 1.0).min())); worst.append(float(c["net"].min()))
    exc = np.concatenate([c["exc"] for c in ch])
    return {"max_drawdown_mean_over_offsets": float(np.mean(dds)), "max_drawdown_worst_offset": float(np.min(dds)),
            "worst_40d_window_net": float(np.min(worst)), "worst_40d_window_excess": float(exc.min()),
            "sd_40d_net": float(np.concatenate([c["net"] for c in ch]).std())}


def era_score(tag, e):
    wp, dates, spy = e["wp"], e["dates"], e["spy"]
    bk, cnt = build_books(wp)
    net = {k: DD.chains(v, dates, spy, DR.COST_BPS) for k, v in bk.items()}
    gro = {k: DD.chains(v, dates, spy, 0.0) for k, v in bk.items()}
    po = {k: DD.per_offset(v) for k, v in net.items()}
    pg = {k: DD.per_offset(v) for k, v in gro.items()}
    prim = RW.compare(net["INT"], net["L"])
    out = {"window": f"{dates[0].date()}..{dates[-1].date()}", "primary_INT_minus_L": prim,
           "INT_minus_L_gross": float((pg["INT"] - pg["L"]).mean())}
    books = {}
    for k in bk:
        fn = float(np.mean(np.concatenate([c["f_new"] for c in net[k]])))
        books[k] = {"vs_spy_mean40_net": float(po[k].mean()), "vs_spy_mean40_gross": float(pg[k].mean()),
                    "sd_across_offsets": float(po[k].std()), "offsets_positive_vs_spy": int((po[k] > 0).sum()),
                    "mean_f_new": fn, "cost_drag_ann": float(pg[k].mean() - po[k].mean()),
                    "minus_L_net": float((po[k] - po["L"]).mean()),
                    "offsets_positive_vs_L": int(((po[k] - po["L"]) > 0).sum()),
                    "n_dates": int(len(bk[k])), **risk(net[k])}
    out["books"] = books
    pyI, pyL = DD.per_year(net["INT"]), DD.per_year(net["L"])
    out["per_year_INT_minus_L"] = {y: pyI[y] - v for y, v in pyL.items()}
    out["counts"] = {"n_dates": int(len(cnt)), "mean_L": float(cnt["nL"].mean()), "mean_R": float(cnt["nR"].mean()),
                     "mean_true_intersection": float(cnt["nINT"].mean()),
                     "min_true_intersection": int(cnt["nINT"].min()),
                     "overlap_share_INT_over_L": float((cnt["nINT"] / cnt["nL"]).mean()),
                     "fallback_dates": int(cnt["fallback"].sum()), "fallback_share": float(cnt["fallback"].mean()),
                     "mean_names_held_in_INT_book": float(np.where(cnt["fallback"], cnt["nL"], cnt["nINT"]).mean())}
    # size-matched null: random subsets of L with |INT| names per date
    dn, dg, fn = [], [], []
    for k in range(N_NULL):
        nb = null_book(wp, cnt, NULL_SEED0 + k)
        cn = DD.chains(nb, dates, spy, DR.COST_BPS); cg = DD.chains(nb, dates, spy, 0.0)
        dn.append(float((DD.per_offset(cn) - po["L"]).mean())); dg.append(float((DD.per_offset(cg) - pg["L"]).mean()))
        fn.append(float(np.mean(np.concatenate([c["f_new"] for c in cn]))))
    dn, dg = np.array(dn), np.array(dg)
    out["null_size_matched"] = {
        "n_draws": N_NULL, "seeds": f"{NULL_SEED0}..{NULL_SEED0+N_NULL-1}",
        "net": {"mean": float(dn.mean()), "sd": float(dn.std()), "min": float(dn.min()), "max": float(dn.max()),
                "real": prim["mean_diff_ann_40offset"],
                "percentile_share_null_below": float((dn < prim["mean_diff_ann_40offset"]).mean())},
        "gross": {"mean": float(dg.mean()), "sd": float(dg.std()), "min": float(dg.min()), "max": float(dg.max()),
                  "real": out["INT_minus_L_gross"],
                  "percentile_share_null_below": float((dg < out["INT_minus_L_gross"]).mean())},
        "null_mean_f_new": float(np.mean(fn))}
    log(f"[{tag}] INT-L {prim['mean_diff_ann_40offset']*100:+.3f}%/yr offsets+ {prim['offsets_positive']}/40 "
        f"LOYO min {prim['loyo_min']*100:+.3f} ({prim['loyo_min_dropped_year']}); null pct net "
        f"{out['null_size_matched']['net']['percentile_share_null_below']:.0%} gross "
        f"{out['null_size_matched']['gross']['percentile_share_null_below']:.0%}; |INT| {out['counts']['mean_true_intersection']:.1f} "
        f"fallback {out['counts']['fallback_dates']}/{len(cnt)}")
    return out


def stage_score():
    T0 = time.time()
    b = json.loads(BUILD_JSON.read_text())
    assert b["A"]["ok"] and b["B"]["ok"], "build not validated"
    with open(CACHE, "rb") as f:
        cache = pickle.load(f)
    out = {"work_order": "WO-44", "prereg": "final/models/2026-10-01-intersection-book.md", "holdout_read": 20,
           "cost_bps": DR.COST_BPS, "min_int": MIN_INT, "family_trial": 4}
    for tag in ("A", "B"):
        out[tag] = era_score(tag, cache[tag])
        EVAL_JSON.write_text(json.dumps(out, indent=2, default=float))
    a, bb = out["A"]["primary_INT_minus_L"], out["B"]["primary_INT_minus_L"]
    ex2020 = bb["loyo_by_dropped_year"][2020]
    if a["mean_diff_ann_40offset"] <= 0 or bb["mean_diff_ann_40offset"] <= 0:
        v = "KILL"
    elif a["offsets_positive"] >= 30 and bb["offsets_positive"] >= 30 and ex2020 > 0 and a["loyo_min"] > 0:
        v = "SUCCESS"
    else:
        v = "MIDDLE"
    out["verdict"] = {"verdict": v, "A_diff": a["mean_diff_ann_40offset"], "A_offsets": a["offsets_positive"],
                      "A_loyo_min": a["loyo_min"], "B_diff": bb["mean_diff_ann_40offset"],
                      "B_offsets": bb["offsets_positive"], "B_ex2020": ex2020}
    out["runtime_s"] = time.time() - T0
    EVAL_JSON.write_text(json.dumps(out, indent=2, default=float))
    log(f"VERDICT {v}; wrote {EVAL_JSON} ({out['runtime_s']:.0f}s)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", required=True, choices=["build", "score"])
    a = ap.parse_args()
    stage_build() if a.stage == "build" else stage_score()
