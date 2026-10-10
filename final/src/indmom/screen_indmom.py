"""
WO-50: screen ind_mom_12_1 (industry momentum) -- pre-reg gate stack section 1.7, exactly.
Pre-registration: final/models/2026-10-08-industry-momentum.md (sha256 asserted at import).
Amendment (pre-outcome, no spec change): final/models/2026-10-10-industry-momentum-amendment.md.
Harness: final/src/signcheck/dropcheck.py (WO-48b) imported read-only; structure follows
final/src/wrds_optionm_smirk/screen_smirk.py, with WO-50's own gates (IC on cap150, gate 3 =
ind_mom_resid t >= 1.0, gate 4 = every offset mean > 0, gate 5 = share + LOYO, gate 6 = paired
book vs a same-weight null p80 and >= 26/40, gate 7 = Gate A).

Era 2007-01-02..2019-12-31 ONLY (hard asserts; the harness loader asserts too). No trading code.

Usage (python = /opt/anaconda3/envs/pipe_dream/bin/python, under caffeinate -i):
  screen_indmom.py --coverage            -> parts/coverage.json (outcome-free)
  screen_indmom.py --real                -> parts/real.json     (gates 1-5, placebo, icw6 book)
  screen_indmom.py --null 100 --procs 4  -> parts/null/NNN.json
  screen_indmom.py --recheck             -> null draw 0 rerun identical
  screen_indmom.py --aggregate 100       -> indmom_report.json
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
PREREG = FINAL / "models" / "2026-10-08-industry-momentum.md"
PREREG_SHA = "c686ad7e9f29b1d26491de2ef6d9865c25ca5804c3412085c79100fb3f28cc16"
assert hashlib.sha256(PREREG.read_bytes()).hexdigest() == PREREG_SHA, "PRE-REG CHANGED SINCE FREEZE: STOP"
sys.path.insert(0, str(SRC / "signcheck"))
import dropcheck as D   # noqa: E402

S, G = D.S, D.G
COL = "ind_mom_12_1"
SIGN = +1
T_BAR = 2.0
RESID_T_BAR = 1.0
YEAR_SHARE_MAX = 0.45
OFF_POS_MIN = 26
N_NULL = 100
SEED0 = 50000
HOLDOUT = pd.Timestamp("2020-01-01")
REF_V5 = 0.0364425          # pre-reg 1.5 (dropcheck_report.json eras.A.arms.D4.arm_mean40)
REF_TOL = 0.0002
FLOOR_W9 = 0.0105
OUT = FINAL / "out" / "indmom"
PARTS = OUT / "parts"
NULLD = PARTS / "null"
FEAT = OUT / "cache" / "indmom_factor.parquet"
log = D.log


def merge_factor(U):
    build = json.loads((PARTS / "build.json").read_text())
    assert hashlib.sha256(FEAT.read_bytes()).hexdigest() == build["cache_sha256"], "factor cache changed since build"
    f = pd.read_parquet(FEAT, columns=["ticker", "date", COL])
    f["ticker"] = f["ticker"].astype(str); f["date"] = pd.to_datetime(f["date"])
    assert f["date"].max() < HOLDOUT
    key = pd.MultiIndex.from_arrays([U["ticker"], U["date"]])
    v = f.set_index(["ticker", "date"])[COL]
    assert v.index.is_unique
    U[COL] = v.reindex(key).to_numpy(np.float64)      # literal (ticker, date) join: non-population rows NaN
    log(f"factor merged: finite {np.isfinite(U[COL]).mean():.4%}")


def load():
    U = D.load("A")
    assert U["date"].max() < HOLDOUT and max(G["all_dates"]) < HOLDOUT and G["spy"].index.max() < HOLDOUT, "HOLD-OUT BREACH"
    G["V5"] = dict(G["ICW"].PRODUCTION_WEIGHTS_V5_SEAS)
    merge_factor(U)
    G["V"].add_ranks(U, [COL])
    G["rz"][COL] = U[f"rz_{COL}"].to_numpy(np.float64)
    return U


def base_v5():
    ch5 = S.chains(S.picks_fast(S.score(G["V5"])))
    got = float(G["DD"].per_offset(ch5).mean())
    ok = abs(got - REF_V5) <= REF_TOL
    log(f"icw5_seas reconcile {got:+.9f} vs {REF_V5} (tol {REF_TOL}): {'OK' if ok else 'FAIL'}")
    assert ok, f"V5 RECONCILE FAIL {got} vs {REF_V5}: STOP"
    return ch5, got


def w6(t_ind):
    """Pre-reg 1.6: raw_k = W9_k * 0.1 / 0.0105 (five V5 factors), raw_new = +max(0.1, |t|-1);
    W6 = raw / sum|raw| * sum|W5|."""
    W9, V5 = dict(G["ICW"].PRODUCTION_WEIGHTS_V9_SEAS), G["V5"]
    raw = {k: W9[k] * 0.1 / FLOOR_W9 for k in V5}
    raw[COL] = SIGN * max(0.1, abs(t_ind) - 1.0)
    s5 = sum(abs(w) for w in V5.values())
    sr = sum(abs(r) for r in raw.values())
    W6 = {k: r / sr * s5 for k, r in raw.items()}
    # sanity: the five V5 weights alone re-normalise to V5 (same relative raw magnitudes)
    s_old = sum(abs(raw[k]) for k in V5)
    for k in V5:
        assert abs(raw[k] / s_old * s5 - V5[k]) < 2e-4, (k, raw[k] / s_old * s5, V5[k])
    return W6, raw


def resid_on_mom(U):
    """ind_mom_resid: per-date OLS residual of ind_mom_12_1 on momentum_12_1 (intercept),
    fit on the cap150 rows of that date where both are finite."""
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
    r["ind_mom_resid"] = rr["pooled"]
    sp = []
    for _, d in U[["date", COL, "momentum_12_1"]].dropna().groupby("date"):
        if len(d) >= 20:
            sp.append(d[COL].rank().corr(d["momentum_12_1"].rank()))
    r["spearman_own_mom_median"] = float(np.median(sp))
    offs = np.array(r["offsets"]["means"])
    r["offsets_all_positive"] = bool(np.all(SIGN * offs > 0))
    r["offsets_n_nonpositive"] = int(np.sum(SIGN * offs <= 0))
    r["loyo_min_t"] = float(min(r["loyo_t"].values()))
    g = {"g1_pooled_t": bool(SIGN * r["pooled"]["t"] >= T_BAR),
         "g2_halves": bool(SIGN * r["odd"]["mean"] > 0 and SIGN * r["even"]["mean"] > 0),
         "g3_resid_on_own_mom": bool(SIGN * rr["pooled"]["t"] >= RESID_T_BAR),
         "g4_offsets": r["offsets_all_positive"],
         "g5_loyo": bool(SIGN * r["year_share"]["total_sum_ic"] > 0
                         and r["year_share"]["max_share"] <= YEAR_SHARE_MAX
                         and SIGN * r["loyo_min_t"] > 0)}
    return r, g


def run_coverage():
    PARTS.mkdir(parents=True, exist_ok=True)
    U = load()
    fin = np.isfinite(U[COL].to_numpy())
    yr = U["date"].dt.year
    per_date = pd.Series(fin).groupby(U["date"].to_numpy()).sum()
    tot_date = U.groupby("date").size()
    cov = {"cap150_rows": int(len(U)), "finite_share": float(fin.mean()),
           "finite_share_by_year": {int(y): float(v) for y, v in pd.Series(fin).groupby(yr.to_numpy()).mean().items()},
           "median_names_per_date_with_value": float(per_date.median()),
           "median_cap150_names_per_date": float(tot_date.median()),
           "own_mom_nan_share": float((~np.isfinite(U["momentum_12_1"].to_numpy(np.float64))).mean())}
    (PARTS / "coverage.json").write_text(json.dumps(cov, indent=1, default=float))
    log(json.dumps(cov, default=float))


def run_real():
    T0 = time.time()
    PARTS.mkdir(parents=True, exist_ok=True)
    U = load()
    _, rec9 = D.base_chain("A")
    ch5, got5 = base_v5()
    out = {"work_order": "WO-50", "era": "2007-01-02..2019-12-31",
           "reconcile": {"icw9_seas": rec9, "icw5_seas": got5, "icw5_ref": REF_V5, "tol": REF_TOL,
                         "abs_diff": abs(got5 - REF_V5)}}
    r, g = ic_block(U)
    out["ic"] = r; out["gates_1_5"] = g
    log(f"cap150 IC t {r['pooled']['t']:+.3f} mean {r['pooled']['mean']:+.5f}; resid t {r['ind_mom_resid']['t']:+.3f}; gates {g}")
    U["_plc"] = G["V"].shuffle_within_date(U, COL, SEED0)
    pr, _ = G["V"].ic_gates(U, "_plc")
    U.drop(columns=["_plc"], inplace=True)
    out["placebo"] = {"seed": SEED0, "pooled": pr["pooled"], "fails_gate1": bool(SIGN * pr["pooled"]["t"] < T_BAR)}
    log(f"placebo t {pr['pooled']['t']:+.3f}")
    W6, raw = w6(r["pooled"]["t"])
    ch6 = S.chains(S.picks_fast(S.score(W6)))
    d = S.diff_block(ch5, ch6)
    po5 = G["DD"].per_offset(ch5)
    out["book"] = {"t_ind": r["pooled"]["t"], "raw": raw, "W6": W6,
                   "icw5_mean40": float(po5.mean()), "icw5_sd40": float(np.std(po5)),
                   "icw6_mean40": float(G["DD"].per_offset(ch6).mean()), "paired": d}
    log(f"book: w_ind {W6[COL]:.5f}; icw6-icw5 {d['diff']*100:+.4f} pp/yr, {d['diff_offsets_pos']}/40 > 0")
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
    ch = S.chains(S.picks_fast(S.score(G["W6"], {COL: rz})))      # SAME icw6 weight as the real factor
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
    inc = np.array([json.loads((NULLD / f"{s:03d}.json").read_text())["inc"] for s in range(n)])
    d = real["book"]["paired"]
    p80 = float(np.percentile(inc, 80))
    g6 = bool(d["diff"] > p80 and d["diff_offsets_pos"] >= OFF_POS_MIN)
    integ = json.loads((OUT / "indmom_integrity.json").read_text())
    g7 = bool(real["placebo"]["fails_gate1"] and integ["pass_a_c"])
    gates = {**real["gates_1_5"], "g6_book": g6, "g7_gate_A": g7}
    kill = not all(gates[k] for k in list(real["gates_1_5"]) + ["g6_book"])
    verdict = "KILL" if kill else ("PASS" if g7 else "NO VERDICT (gate A failed)")
    r = real["ic"]
    rep = {"work_order": "WO-50", "factor": COL, "sign": SIGN, "prereg": "final/models/2026-10-08-industry-momentum.md",
           "prereg_sha256": PREREG_SHA, "era": real["era"], "reconcile": real["reconcile"], "verdict": verdict,
           "gates": gates, "coverage": json.loads((PARTS / "coverage.json").read_text()),
           "gate_numbers": {
               "g1_pooled_ic": r["pooled"], "g1_bar": T_BAR,
               "g2_odd": r["odd"], "g2_even": r["even"],
               "g3_ind_mom_resid": r["ind_mom_resid"], "g3_bar": RESID_T_BAR,
               "sector_both_sides_descriptive": r["sector_both_sides"],
               "g4_offset_means_min_max": [r["offsets"]["min"], r["offsets"]["max"]],
               "g4_n_nonpositive": r["offsets_n_nonpositive"],
               "g5_total_sum_ic": r["year_share"]["total_sum_ic"], "g5_max_year_share": r["year_share"]["max_share"],
               "g5_max_year": r["year_share"]["max_year"], "g5_loyo_min_t": r["loyo_min_t"], "g5_loyo_t": r["loyo_t"],
               "spearman_own_mom_median": r["spearman_own_mom_median"],
               "g6_paired_inc": d["diff"], "g6_offsets_pos": d["diff_offsets_pos"], "g6_null_p80": p80,
               "g6_offsets_bar": OFF_POS_MIN,
               "g6_null": {"n": n, "seeds": [SEED0, SEED0 + n - 1], "p50": float(np.percentile(inc, 50)),
                           "p95": float(np.percentile(inc, 95)), "pct_below_real": float((inc < d["diff"]).mean())},
               "g6_base_sd40_not_bar": real["book"]["icw5_sd40"], "g6_w_ind": real["book"]["W6"][COL],
               "g6_W6": real["book"]["W6"],
               "g7_placebo_t": real["placebo"]["pooled"]["t"], "g7_integrity_pass": integ["pass_a_c"]},
           "null_recheck": json.loads((PARTS / "null_recheck.json").read_text())}
    (OUT / "indmom_report.json").write_text(json.dumps(rep, indent=1, default=float))
    print(json.dumps({"verdict": verdict, "gates": gates}, indent=1))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--coverage", action="store_true")
    ap.add_argument("--real", action="store_true")
    ap.add_argument("--null", type=int, default=0)
    ap.add_argument("--procs", type=int, default=4)
    ap.add_argument("--recheck", action="store_true")
    ap.add_argument("--aggregate", type=int, default=0)
    a = ap.parse_args()
    if a.coverage:
        run_coverage()
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
