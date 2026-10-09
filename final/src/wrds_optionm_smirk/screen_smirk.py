"""
WO-56: screen IV smirk (Xing-Zhang-Zhao 2010) -- WO-53's 7 gates, g1 t >= 3.0, g7 >= 24/40.
Pre-registration: final/models/2026-10-09-iv-smirk.md (sha256 PREREG_SHA below, asserted at import).
Copy of final/src/wrds_ibes/screen_rev3.py (WO-53); changes: COL/SIGN/T_BAR/OFF_POS_MIN/SEED0,
factor source, IC gates 1-6 on cap2000 in a separate process (--ic2000; WO-56 "cap2000 for the IC"),
book weight from the cap150 NW t (same universe as the V5 t_k), and the D-NWT null-t sd report.
Harness = this checkout's own final/src (branch based on origin/integration).

Era 2007-01-02..2019-12-31 ONLY (hard asserts; the harness loader asserts too).

Usage (python = /opt/anaconda3/envs/pipe_dream/bin/python, under caffeinate -i):
  screen_smirk.py --ic2000             -> parts/ic2000.json   (gates 1-6, placebo, D-NWT null t's)
  screen_smirk.py --real               -> parts/real.json     (cap150 IC descriptive + book)
  screen_smirk.py --null 100 --procs 4 -> parts/null/NNN.json
  screen_smirk.py --recheck            -> null draw 0 rerun identical
  screen_smirk.py --aggregate 100      -> smirk_report.json
"""
import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
SRC = HERE.parent
FINAL = HERE.parents[1]
PREREG = FINAL / "models" / "2026-10-09-iv-smirk.md"
PREREG_SHA = "71517f642946b03027d8dd976fb567e7ede64dd1aabdd72d4eef892b0e95d0af"   # frozen 2026-10-09T16:36:09Z
assert hashlib.sha256(PREREG.read_bytes()).hexdigest() == PREREG_SHA, "PRE-REG CHANGED SINCE FREEZE: STOP"
sys.path.insert(0, str(SRC / "signcheck"))
import dropcheck as D   # noqa: E402  (imports signcheck -> stateint -> harness)

S, G = D.S, D.G
COL = "smirk"
SIGN = -1
T_BAR = 3.0
SECTOR_T_BAR = 1.0
RESID_T_BAR = 1.0
YEAR_SHARE_MAX = 0.45
OFF_POS_MIN = 24
N_NULL = 100
SEED0 = 56000
HOLDOUT = pd.Timestamp("2020-01-01")
REF_V5 = 0.036442521084825354          # WO-48b real_A.json arms.D4.arm_mean40 (weights == V5_SEAS)
OUT = FINAL / "out" / "wrds_optionm_smirk"
PARTS = OUT / "parts"
NULLD = PARTS / "null"
FEAT = OUT / "cache" / "smirk_factor.parquet"
FEAT_SHA = "820c3f3a99ddd4dcff6e531fb6518de6d9b69308add599a4b9237cf699c3a2b8"   # frozen in the pre-reg
ICW_REPORT = Path("/Users/ggraham/pipe_dream/final/out/reset2026/ic_weighted_composite_report.json")
log = D.log


def merge_factor(U):
    assert hashlib.sha256(FEAT.read_bytes()).hexdigest() == FEAT_SHA, "factor file changed since pre-reg"
    f = pd.read_parquet(FEAT, columns=["ticker", "date", COL])
    f["ticker"] = f["ticker"].astype(str); f["date"] = pd.to_datetime(f["date"])
    assert f["date"].max() < HOLDOUT
    key = pd.MultiIndex.from_arrays([U["ticker"], U["date"]])
    v = f.set_index(["ticker", "date"])[COL]
    assert v.index.is_unique
    U[COL] = v.reindex(key).to_numpy(np.float64)
    log(f"factor merged: finite {np.isfinite(U[COL]).mean():.4%}")


def load():
    U = D.load("A")
    assert U["date"].max() < HOLDOUT and max(G["all_dates"]) < HOLDOUT and G["spy"].index.max() < HOLDOUT, "HOLD-OUT BREACH"
    G["V5"] = dict(G["ICW"].PRODUCTION_WEIGHTS_V5_SEAS)
    merge_factor(U)
    G["V"].add_ranks(U, [COL])
    G["rz"][COL] = U[f"rz_{COL}"].to_numpy(np.float64)
    return U


def load_cap2000():
    import model_audit_wo23 as MA
    import trailfilter as TF
    MA.SEAS_EXT = TF.SEAS_EXT_RO
    U, all_dates, spy = MA.load_theo("A", "cap2000")
    assert U["date"].max() < HOLDOUT and max(pd.Timestamp(d) for d in all_dates) < HOLDOUT, "HOLD-OUT BREACH"
    G.update(V=MA.V, SI=MA.SI)
    merge_factor(U)
    return U


def base_v5():
    ch5 = S.chains(S.picks_fast(S.score(G["V5"])))
    got = float(G["DD"].per_offset(ch5).mean())
    assert abs(got - REF_V5) < 1e-10, f"V5 RECONCILE FAIL {got} vs {REF_V5}"
    log(f"icw5_seas reconcile OK {got:+.9f} (ref {REF_V5})")
    return ch5, got


def scale_k():
    ICW = G["ICW"]
    t = {c: v["t"] for c, v in json.loads(ICW_REPORT.read_text())["per_factor_t"]["full"].items()}
    t["seas"] = ICW.SEAS_T
    raw = {c: max(0.1, abs(t[c]) - 1.0) for c in G["V5"]}
    k = sum(abs(w) for w in G["V5"].values()) / sum(raw.values())
    for c, w in G["V5"].items():
        assert abs(abs(w) - raw[c] * k) < 2e-4, (c, w, raw[c] * k)
    return k, raw


def w6(t_150):
    k, raw = scale_k()
    return {**G["V5"], COL: SIGN * max(0.1, abs(t_150) - 1.0) * k}, k, raw


def resid_on_mom(U):
    """Same construction as WO-50's ind_mom_resid / WO-53 gate 6."""
    x = U[COL].to_numpy(np.float64); m = U["momentum_12_1"].to_numpy(np.float64)
    ok = np.isfinite(x) & np.isfinite(m)
    df = pd.DataFrame({"d": U["date"].to_numpy()[ok], "x": x[ok], "m": m[ok]})
    g = df.groupby("d")
    mx, mm = g["x"].transform("mean"), g["m"].transform("mean")
    cov = ((df["x"] - mx) * (df["m"] - mm)).groupby(df["d"]).transform("sum")
    var = ((df["m"] - mm) ** 2).groupby(df["d"]).transform("sum")
    beta = (cov / var.replace(0, np.nan)).fillna(0.0)
    out = np.full(len(U), np.nan)
    out[ok] = (df["x"] - mx - beta * (df["m"] - mm)).to_numpy()
    return out


def ic_block(U):
    r, _ = G["V"].ic_gates(U, COL)
    U["_resid"] = resid_on_mom(U)
    rr, _ = G["V"].ic_gates(U, "_resid")
    U.drop(columns=["_resid"], inplace=True)
    r["resid_on_mom"] = rr["pooled"]
    sp = []
    for _, d in U[["date", COL, "momentum_12_1"]].dropna().groupby("date"):
        if len(d) >= 20:
            sp.append(d[COL].rank().corr(d["momentum_12_1"].rank()))
    r["spearman_mom_median"] = float(np.median(sp))
    g = {"g1_pooled_t": bool(SIGN * r["pooled"]["t"] >= T_BAR),
         "g2_halves": bool(SIGN * r["odd"]["mean"] > 0 and SIGN * r["even"]["mean"] > 0),
         "g3_sector_both_sides": bool(SIGN * r["sector_both_sides"]["t"] >= SECTOR_T_BAR),
         "g4_offsets": bool(r["offsets"]["sign_flips"] == 0 and np.sign(r["pooled"]["mean"]) == SIGN),
         "g5_loyo": bool(SIGN * r["year_share"]["total_sum_ic"] > 0
                         and r["year_share"]["max_share"] <= YEAR_SHARE_MAX
                         and SIGN * min(r["loyo_t"].values()) > 0),
         "g6_resid_mom": bool(SIGN * rr["pooled"]["t"] >= RESID_T_BAR)}
    r["loyo_min_t"] = float(min(r["loyo_t"].values()))
    r["loyo_extreme_signed_t"] = float(min(SIGN * v for v in r["loyo_t"].values()))
    return r, g


def pooled_t(U, col):
    s = G["SI"].daily_corr(U, col, "forward_return_tradable_40")
    return float(G["V"].nw(s.to_numpy())["t"])


def run_ic2000(n_null):
    T0 = time.time()
    PARTS.mkdir(parents=True, exist_ok=True)
    U = load_cap2000()
    out = {"work_order": "WO-56", "universe": "cap2000 col c 2007-2019", "era": "2007-01-02..2019-12-31"}
    r, g = ic_block(U)
    out["ic"] = r; out["gates_1_6"] = g
    log(f"cap2000 IC t {r['pooled']['t']:+.3f} mean {r['pooled']['mean']:+.5f}; resid t {r['resid_on_mom']['t']:+.3f}; gates {g}")
    U["_plc"] = G["V"].shuffle_within_date(U, COL, SEED0)
    pr, _ = G["V"].ic_gates(U, "_plc")
    out["placebo"] = {"seed": SEED0, "pooled": pr["pooled"], "fails_gate1": bool(SIGN * pr["pooled"]["t"] < T_BAR)}
    ts = []
    for s in range(n_null):                       # D-NWT: null NW t sd (reported, not gated)
        U["_plc"] = G["V"].shuffle_within_date(U, COL, SEED0 + s)
        ts.append(pooled_t(U, "_plc"))
    U.drop(columns=["_plc"], inplace=True)
    ts = np.array(ts)
    out["dnwt_null_t"] = {"n": n_null, "seeds": [SEED0, SEED0 + n_null - 1], "sd": float(ts.std(ddof=1)),
                          "mean": float(ts.mean()), "p95_abs": float(np.percentile(np.abs(ts), 95)),
                          "emp_p_one_sided": float((SIGN * ts >= SIGN * r["pooled"]["t"]).mean()), "t": ts.tolist()}
    log(f"D-NWT null t sd {out['dnwt_null_t']['sd']:.3f}")
    out["runtime_s"] = time.time() - T0
    (PARTS / "ic2000.json").write_text(json.dumps(out, indent=1, default=float))


def run_real():
    T0 = time.time()
    PARTS.mkdir(parents=True, exist_ok=True)
    U = load()
    _, rec9 = D.base_chain("A")
    ch5, got5 = base_v5()
    out = {"work_order": "WO-56", "era": "2007-01-02..2019-12-31",
           "reconcile": {"icw9_seas": rec9, "icw5_seas": got5, "icw5_ref": REF_V5}}
    r, g = ic_block(U)
    out["ic_cap150_descriptive"] = r; out["gates_1_6_cap150_not_gated"] = g
    log(f"cap150 IC t {r['pooled']['t']:+.3f} (descriptive; sets the book weight)")
    W6, k, raw = w6(r["pooled"]["t"])
    ch6 = S.chains(S.picks_fast(S.score(W6)))
    d = S.diff_block(ch5, ch6)
    po5 = G["DD"].per_offset(ch5)
    out["book"] = {"t_cap150": r["pooled"]["t"], "k": k, "raw": raw, "W6": W6,
                   "icw5_mean40": float(po5.mean()), "icw5_sd40": float(np.std(po5)),
                   "icw6_mean40": float(G["DD"].per_offset(ch6).mean()), "paired": d}
    log(f"book: w_smirk {W6[COL]:.5f}; icw6-icw5 {d['diff']*100:+.4f} pp/yr, {d['diff_offsets_pos']}/40 > 0")
    out["runtime_s"] = time.time() - T0
    (PARTS / "real.json").write_text(json.dumps(out, indent=1, default=float))


def prep_null():
    load()
    G["ch5"] = base_v5()[0]
    G["W6"] = json.loads((PARTS / "real.json").read_text())["book"]["W6"]


def null_one(s, path=None):
    p = path or NULLD / f"{s:03d}.json"
    if p.exists():
        return s
    v = G["V"].shuffle_within_date(G["U"], COL, SEED0 + s)
    rz = G["SI"].rank_z(pd.DataFrame({"date": G["U"]["date"], "x": v}), "x").to_numpy(np.float64)
    ch = S.chains(S.picks_fast(S.score(G["W6"], {COL: rz})))      # SAME weight as the real factor
    inc = G["DD"].per_offset(ch) - G["DD"].per_offset(G["ch5"])
    p.write_text(json.dumps({"draw": s, "seed": SEED0 + s, "inc": float(inc.mean()), "offsets_pos": int((inc > 0).sum())}))
    return s


def run_null(n, procs):
    import multiprocessing as mp
    NULLD.mkdir(parents=True, exist_ok=True)
    prep_null()
    todo = [s for s in range(n) if not (NULLD / f"{s:03d}.json").exists()]
    log(f"null: {len(todo)} draws on {procs} procs")
    with mp.get_context("fork").Pool(procs) as pool:
        for i, s in enumerate(pool.imap_unordered(null_one, todo)):
            if i % 10 == 0:
                log(f"null {s} done ({i+1}/{len(todo)})")


def run_recheck():
    prep_null()
    q = PARTS / "recheck_000.json"
    q.unlink(missing_ok=True)
    null_one(0, q)
    x = json.loads((NULLD / "000.json").read_text())["inc"]; y = json.loads(q.read_text())["inc"]
    q.unlink()
    (PARTS / "null_recheck.json").write_text(json.dumps({"draw0": x, "rerun": y, "identical": x == y}))
    assert x == y, "NULL RERUN MISMATCH"


def aggregate(n):
    real = json.loads((PARTS / "real.json").read_text())
    ic = json.loads((PARTS / "ic2000.json").read_text())
    inc = np.array([json.loads((NULLD / f"{s:03d}.json").read_text())["inc"] for s in range(n)])
    d = real["book"]["paired"]
    p80 = float(np.percentile(inc, 80))
    g7 = bool(d["diff"] > p80 and d["diff_offsets_pos"] >= OFF_POS_MIN)
    integ = json.loads((OUT / "smirk_integrity.json").read_text())
    gA = bool(ic["placebo"]["fails_gate1"] and integ["brute_force_100"]["mismatches"] == 0
              and all(h.get("match") for h in integ["hand_check"]))
    gates = {**ic["gates_1_6"], "g7_book": g7, "gate_A_integrity": gA}
    verdict = "ADMIT (nomination only)" if all(gates.values()) else "KILL"
    r = ic["ic"]
    rep = {"work_order": "WO-56", "factor": COL, "sign": SIGN, "prereg": "final/models/2026-10-09-iv-smirk.md",
           "era": real["era"], "reconcile": real["reconcile"], "verdict": verdict, "gates": gates,
           "gate_numbers": {
               "g1_pooled_ic_cap2000": r["pooled"], "bar": T_BAR, "dnwt_null_t_sd": ic["dnwt_null_t"]["sd"],
               "dnwt_emp_p": ic["dnwt_null_t"]["emp_p_one_sided"],
               "g2_odd": r["odd"], "g2_even": r["even"],
               "g3_sector_both_sides": r["sector_both_sides"], "g3_factor_only_not_gated": r["sector_factor_only"],
               "g4_offset_flips": r["offsets"]["sign_flips"], "g4_offset_min_max": [r["offsets"]["min"], r["offsets"]["max"]],
               "g5_total_sum_ic": r["year_share"]["total_sum_ic"],
               "g5_max_year_share": r["year_share"]["max_share"], "g5_max_year": r["year_share"]["max_year"],
               "g5_loyo_min_t": r["loyo_min_t"], "g5_loyo_t": r["loyo_t"],
               "g6_resid_on_mom": r["resid_on_mom"], "spearman_mom_median": r["spearman_mom_median"],
               "cap150_ic_descriptive": real["ic_cap150_descriptive"]["pooled"],
               "g7_paired_inc": d["diff"], "g7_offsets_pos": d["diff_offsets_pos"], "g7_null_p80": p80,
               "g7_null": {"n": n, "p50": float(np.percentile(inc, 50)), "p95": float(np.percentile(inc, 95)),
                           "pct_below_real": float((inc < d["diff"]).mean())},
               "g7_base_sd40_not_bar": real["book"]["icw5_sd40"], "g7_w_smirk": real["book"]["W6"][COL],
               "gA_placebo_t": ic["placebo"]["pooled"]["t"]},
           "null_recheck": json.loads((PARTS / "null_recheck.json").read_text())}
    (OUT / "smirk_report.json").write_text(json.dumps(rep, indent=1, default=float))
    print(json.dumps({"verdict": verdict, "gates": gates}, indent=1))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ic2000", action="store_true")
    ap.add_argument("--real", action="store_true")
    ap.add_argument("--null", type=int, default=0)
    ap.add_argument("--procs", type=int, default=4)
    ap.add_argument("--recheck", action="store_true")
    ap.add_argument("--aggregate", type=int, default=0)
    a = ap.parse_args()
    if a.ic2000:
        run_ic2000(N_NULL)
    if a.real:
        run_real()
    if a.null:
        run_null(a.null, a.procs)
    if a.recheck:
        run_recheck()
    if a.aggregate:
        aggregate(a.aggregate)


if __name__ == "__main__":
    main()
