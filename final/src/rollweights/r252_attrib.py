"""
WO-34 Part A (COO, 2026-09-30): where did R252's 2020-26 gain over EXP come from?

Descriptive only. No new fit: every weight path is WO-33's (weight_paths.csv
for 2010-2019, weight_paths_step2.csv for 2020-26), read exactly as WO-33's
stage_eval / stage_eval2 read them, scored with WO-33's score_path, booked
with WO-33's Book / chains / compare. The 2020-26 reads are part of hold-out
read #13 (Gabe-approved fit on 2020+, logged by WO-33); nothing here fits.

Variants (per era, 40 offsets, net 15 bp, control = EXP):
  swapin_<f>     EXP path with factor f's weight column replaced by R252's
  swapout_<f>    R252 path with factor f's weight column replaced by EXP's
  R252_si_exp    = swapout_short_interest_days_to_cover (named separately)
  R252_si_floor  R252 path with SI's t set to NaN -> fit_weights floor (how the
                 live icw9_seas holds SI: -0.0105; the task text's -0.008 is
                 icw10_io's floor)
Renormalization: after a column swap each row is rescaled to sum|w| = 1.
composite_score divides by sum|w| over the non-NaN ranks, so the rescale
never changes a score; it is done for the reported weights only.

    python final/src/rollweights/r252_attrib.py            # both eras
    python final/src/rollweights/r252_attrib.py --era B    # one era
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
OUT_JSON = RW.OUT / "r252_attrib.json"
SI_F = "short_interest_days_to_cover"
WC = [f"w_{c}" for c in FT]
TC = [f"t_{c}" for c in FT]
REF = {"A": {"diff": -0.01109435031575894, "offsets_positive": 0},
       "B": {"diff": 0.026025300395121343, "offsets_positive": 38}}
TOL = 1e-4                                  # reconcile tolerance on the headline diff (task: +-0.01 %/yr)
log = RW.log


def renorm(p):
    p = p.copy()
    s = p[WC].abs().sum(axis=1)
    p[WC] = p[WC].div(s, axis=0)
    return p


def variants(P):
    exp = P[P["arm"] == "EXP"].reset_index(drop=True)
    r = P[P["arm"] == "R252"].reset_index(drop=True)
    assert len(exp) == len(r) and (exp["refit_date"].to_numpy() == r["refit_date"].to_numpy()).all(), \
        "EXP/R252 refit dates differ"
    out = {"EXP": exp, "R252": r}
    for c in FT:
        a = exp.copy(); a[f"w_{c}"] = r[f"w_{c}"].to_numpy(); out[f"swapin_{c}"] = renorm(a)
        b = r.copy(); b[f"w_{c}"] = exp[f"w_{c}"].to_numpy(); out[f"swapout_{c}"] = renorm(b)
    out["R252_si_exp"] = out[f"swapout_{SI_F}"]
    fl = r.copy()
    for i in range(len(fl)):
        ts = {c: float(fl.at[i, f"t_{c}"]) for c in FT}
        ts[SI_F] = float("nan")
        w = SI.fit_weights(ts, SIGNS)
        for c in FT:
            fl.at[i, f"w_{c}"] = w[c]
    out["R252_si_floor"] = fl
    return out


def setup(era):
    if era == "A":
        U, cal, spy = RW.load_v2()
        V.add_ranks(U, FT)
        P = pd.read_csv(RW.PATH_CSV, parse_dates=["refit_date", "first_used", "last_used"])
        RW.hold(P["refit_date"].max(), "paths csv")
        lo = RW.EVAL_START
    else:
        U, cal, spy = RW.load_B()
        V.add_ranks(U, FT)
        P = pd.read_csv(RW.PATH2_CSV, parse_dates=["refit_date", "first_used", "last_used"])
        RW.hold2(P["refit_date"].max(), "paths2")
        lo = None
    return U, cal, spy, P, lo


def run_one(book, U, cal, spy, path, lo):
    s = RW.score_path(U, path).to_numpy()
    pk = book.picks(s)
    if lo is not None:
        pk, cal2 = DD.window(pk, cal, lo=lo)
    else:
        cal2 = cal
    return {cn: DD.chains(pk, cal2, spy, cost) for cn, cost in (("net", DR.COST_BPS), ("gross", 0.0))}


def summarize(ch, ch_ctl):
    c = RW.compare(ch["net"], ch_ctl["net"])
    net = float(DD.per_offset(ch["net"]).mean()); gross = float(DD.per_offset(ch["gross"]).mean())
    return {"diff_vs_EXP_ann": c["mean_diff_ann_40offset"], "offsets_positive": c["offsets_positive"],
            "nw39_t": c["nw39_t"], "loyo_min": c["loyo_min"],
            "book_vs_spy_net": net, "book_vs_spy_gross": gross, "cost_drag_ann": gross - net,
            "mean_f_new": float(np.mean(np.concatenate([x["f_new"] for x in ch["net"]]))),
            "per_year_net": DD.per_year(ch["net"])}


def mean_weights(p, lo=None):
    q = p if lo is None else p[p["refit_date"] >= lo]
    return {c: float(q[f"w_{c}"].mean()) for c in FT}


def run_era(era, res):
    T0 = time.time()
    U, cal, spy, P, lo = setup(era)
    book = V.Book(U, cal, spy)
    var = variants(P)
    order = ["EXP", "R252"] + [f"swapin_{c}" for c in FT] + [f"swapout_{c}" for c in FT] + ["R252_si_floor"]
    ch = {}
    er = res.setdefault("eras", {}).setdefault(era, {"variants": {}})
    er["window"] = (f"{RW.EVAL_START.date()}..{RW.END.date()}" if era == "A"
                    else f"{RW.B_START.date()}..{RW.B_END.date()}")
    for k in order:
        ch[k] = run_one(book, U, cal, spy, var[k], lo)
        if k == "EXP":
            continue
        s = summarize(ch[k], ch["EXP"])
        s["mean_weights"] = mean_weights(var[k], lo)
        er["variants"][k] = s
        if k == "R252":
            ok = (abs(s["diff_vs_EXP_ann"] - REF[era]["diff"]) < TOL
                  and s["offsets_positive"] == REF[era]["offsets_positive"])
            er["reconcile"] = {"R252_minus_EXP": s["diff_vs_EXP_ann"], "offsets_positive": s["offsets_positive"],
                               "wo33_ref": REF[era], "ok": bool(ok)}
            log(f"[{era}] reconcile R252-EXP {s['diff_vs_EXP_ann']:+.5f} ({s['offsets_positive']}/40) "
                f"vs WO-33 {REF[era]['diff']:+.5f} ({REF[era]['offsets_positive']}/40)")
            assert ok, f"RECONCILE FAIL era {era}"
        log(f"[{era}] {k:45s} {s['diff_vs_EXP_ann']:+.4f}/yr t {s['nw39_t']:+.2f} "
            f"{s['offsets_positive']:2d}/40 f_new {s['mean_f_new']:.3f} ({time.time()-T0:.0f}s)")
        OUT_JSON.write_text(json.dumps(res, indent=1, default=float))
    ex = summarize(ch["EXP"], ch["EXP"])
    er["EXP_book"] = {k: ex[k] for k in ("book_vs_spy_net", "book_vs_spy_gross", "cost_drag_ann", "mean_f_new",
                                         "per_year_net")}
    er["EXP_book"]["mean_weights"] = mean_weights(var["EXP"], lo)
    er["variants"]["R252_si_exp"] = er["variants"][f"swapout_{SI_F}"]
    # decomposition
    tot = er["variants"]["R252"]["diff_vs_EXP_ann"]
    sin = {c: er["variants"][f"swapin_{c}"]["diff_vs_EXP_ann"] for c in FT}
    sout = {c: tot - er["variants"][f"swapout_{c}"]["diff_vs_EXP_ann"] for c in FT}
    er["decomposition"] = {
        "total_R252_minus_EXP": tot,
        "swapin_gain": sin, "swapin_sum": float(sum(sin.values())),
        "swapin_interaction_residual": float(tot - sum(sin.values())),
        "swapout_loss": sout, "swapout_sum": float(sum(sout.values())),
        "swapout_interaction_residual": float(tot - sum(sout.values())),
        "si_share_swapin": float(sin[SI_F] / tot) if tot else None,
        "si_share_swapout": float(sout[SI_F] / tot) if tot else None,
        "si_floor_loss": float(tot - er["variants"]["R252_si_floor"]["diff_vs_EXP_ann"]),
        "si_share_floor": float((tot - er["variants"]["R252_si_floor"]["diff_vs_EXP_ann"]) / tot) if tot else None,
        "definitions": {
            "swapin_gain[f]": "(EXP with f's weight path from R252) - EXP",
            "swapout_loss[f]": "R252 - (R252 with f's weight path from EXP)",
            "si_share_swapin": "swapin_gain[SI] / total",
            "si_share_swapout": "(R252 - R252_si_exp) / total",
            "si_share_floor": "(R252 - R252_si_floor) / total"}}
    # t-sign disagreement with the fixed sign, R252, this era's refits
    r = var["R252"] if lo is None else var["R252"][var["R252"]["refit_date"] >= lo]
    dis = {}
    for c in FT:
        t = r[f"t_{c}"].to_numpy(np.float64)
        m = np.isfinite(t)
        dis[c] = {"share_t_opposes_sign": float((np.sign(t[m]) != SIGNS[c]).mean()) if m.any() else None,
                  "n_finite": int(m.sum()), "mean_t": float(t[m].mean()) if m.any() else None}
    er["R252_t_vs_fixed_sign"] = dis
    er["runtime_s"] = time.time() - T0
    OUT_JSON.write_text(json.dumps(res, indent=1, default=float))
    log(f"[{era}] done ({er['runtime_s']:.0f}s)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--era", choices=["A", "B", "both"], default="both")
    a = ap.parse_args()
    res = json.loads(OUT_JSON.read_text()) if OUT_JSON.exists() else {}
    res.update({"work_order": "WO-34 Part A", "holdout_read": "13 (part of; no new fit)",
                "control": "EXP", "cost_bps": DR.COST_BPS, "offsets": 40,
                "paths": {"A": "final/out/rollweights/weight_paths.csv", "B": "final/out/rollweights/weight_paths_step2.csv"},
                "renormalization_note": "rows rescaled to sum|w|=1 after a swap; scores are scale-invariant"})
    for e in (["B", "A"] if a.era == "both" else [a.era]):
        run_era(e, res)
