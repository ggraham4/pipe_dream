"""
WO-42 S1 (dispersion vs weight-matched null) and S2 (no harm), in-era
2007-01-02..2019-12-31. Pre-registration: final/models/2026-10-01-stabilizer-rule-ear.md
(committed 3c6a321 before any null sd was computed).

The WO-29 (final/src/ear/screen_ear.py) and WO-28 (final/src/volshock/
screen_volshock.py) harnesses are imported read-only; their main() is never
called. Only module path attributes are pointed at the worktrees that hold
the gitignored factor parquets.

Order of work per candidate:
  1 rebuild base icw9_seas (split-half OOS) and base+candidate, hard-assert
    against the committed screen report (1e-4 on mean/sd/min/LOYO, 1e-9 on
    the 40 per-offset increments, fitted weights to 1e-12)
  2 weight-matched null draws 0..19 must reproduce the report's
    weight_matched_null_DESCRIPTIVE book means to 1e-9
  3 draws 0..N-1: sd40 / min40 / mean40 / loyo_min of base + shuffled candidate
Usage: python s1s2.py --cand ear|str_lowturn [--draws 100]
Output: final/out/stabilizer/s1s2_<cand>.json
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
OUT = SRC.parent / "out" / "stabilizer"
WT = Path("/Users/ggraham/pipe_dream/.claude/worktrees")
EAR_DIR = WT / "agent-ad838240373d22717" / "final" / "out" / "ear"            # WO-29 gitignored factor
VOL_FACT = WT / "agent-a79a9999a5df053aa" / "final" / "out" / "volshock" / "volshock_inputs_v2.parquet"
REPORTS = {"ear": SRC.parent / "out" / "ear" / "ear_screen_report.json",
           "str_lowturn": SRC.parent / "out" / "volshock" / "str_lowturn_screen_report.json"}
HOLDOUT = pd.Timestamp("2020-01-01")
TOL = 1e-4          # WO-42 reconcile tolerance on the reported values (fractions)
KEYS = ("excess_cagr_vs_spy_mean40", "sd40", "min40", "loyo_min")
HEADLINE = {"base": (2.55, 0.47), "ear": (2.56, 0.42), "str_lowturn": (2.56, 0.43)}   # %/yr, sd40 pp


def log(m):
    print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)


def guard(U, all_dates, spy):
    """Hard hold-out assert on the S1/S2 code path."""
    assert U["date"].max() < HOLDOUT, "HOLD-OUT BREACH: universe"
    assert pd.Timestamp(max(all_dates)) < HOLDOUT, "HOLD-OUT BREACH: dates"
    assert spy.index.max() < HOLDOUT, "HOLD-OUT BREACH: spy"


def stats(r):
    return {k: float(r[k]) for k in KEYS} | {"offsets_positive": int(r["offsets_positive"]),
                                             "loyo_min_dropped_year": int(r["loyo_min_dropped_year"])}


def check(tag, got, ref):
    for k in KEYS:
        assert abs(got[k] - ref[k]) < TOL, f"RECONCILE FAIL {tag} {k}: {got[k]} vs {ref[k]}"
    return {k: [float(got[k]), float(ref[k])] for k in KEYS}


def headline(tag, r):
    m, s = HEADLINE[tag]
    assert round(100 * r["excess_cagr_vs_spy_mean40"], 2) == m, f"headline mean {tag}"
    assert round(100 * r["sd40"], 2) == s, f"headline sd40 {tag}"
    assert abs(r["sd40"] - float(np.std(r["per_offset"]))) < 1e-15, "sd40 is not the ddof=0 sd of per_offset"


def setup_ear(rep):
    sys.path.insert(0, str(SRC / "ear"))
    import screen_ear as S
    S.OUT = EAR_DIR                       # load_universe reads OUT / ear_factor_v2.parquet
    V = S.V
    U, all_dates, spy = S.load_universe()
    guard(U, all_dates, spy)
    V.add_ranks(U, S.FC9)
    U["rz_ear"] = U["ear"]
    book = V.Book(U, all_dates, spy)
    st = S.Stack(U)
    st.fit(S.FC9)
    _, common, s9, r9, w9 = S.base_reconcile(U, book, st)      # asserts WO-18 base to 1e-6
    st.fit(["ear"])
    w10 = st.weights(S.SIGNS_C)
    p = rep["portfolio"]
    for got, ref in zip(w10, (p["weights10_fit_odd"], p["weights10_fit_even"])):
        assert all(abs(got[k] - ref[k]) < 1e-12 for k in ref), "EAR fitted weights != report"
    r10, _ = S.run_book(book, st.score(w10).where(common).to_numpy())

    def null_book(seed):
        U["ear"] = S.shuffle_live(U, seed)
        U["rz_ear"] = U["ear"]
        return S.run_book(book, st.score(w10).where(common).to_numpy())[0]

    ref = {"base": p["icw9_seas"], "cand": p["icw10_ear"], "inc": p["increment_per_offset"],
           "wm": p["weight_matched_null_DESCRIPTIVE"]["draws"]}
    info = {"cand_weight_fit_odd_even": [w10[0]["ear"], w10[1]["ear"]], "rows": int(len(U)),
            "shuffle": "screen_ear.shuffle_live (live signed ranks permuted among live rows; neutral stays 0)"}
    return r9, r10, null_book, ref, info


def setup_str(rep):
    sys.path.insert(0, str(SRC / "volshock"))
    import screen_volshock as SV
    SV.B.FACT = VOL_FACT
    V, SI = SV.V, SV.SI
    name, sign = "str_lowturn", -1
    U, all_dates, spy = SV.load_universe()
    guard(U, all_dates, spy)
    V.add_ranks(U, SV.FC8)
    U["rz_seas"] = SI.rank_z(U, "seas")
    book = V.Book(U, all_dates, spy)
    yrs = U["date"].dt.year.to_numpy()
    odd = pd.Series(yrs % 2 == 1, index=U.index)
    t9, w9 = SV.base_fit(U, SV.FC9, SV.SIGNS9S, odd)
    s9 = V.oos_score(U, w9, odd)
    common = s9.notna()
    r9 = SV.run_book(book, s9.to_numpy())
    signs10 = {**SV.SIGNS9S, name: sign}
    real = U[name].to_numpy(np.float64).copy()
    U[f"rz_{name}"] = SV.cand_rz(U, name, real)
    tin = SV.cand_t(U, name, odd)
    w10 = (SI.fit_weights({**t9["odd"], name: tin["odd"]}, signs10),
           SI.fit_weights({**t9["even"], name: tin["even"]}, signs10))
    p = rep["portfolio"]
    for got, ref in zip(w10, (p["weights10_fit_odd"], p["weights10_fit_even"])):
        assert all(abs(got[k] - ref[k]) < 1e-12 for k in ref), "str_lowturn fitted weights != report"
    r10 = SV.run_book(book, V.oos_score(U, w10, odd).where(common).to_numpy())

    def null_book(seed):
        sh = V.shuffle_within_date(U, name, seed)       # U[name] is never overwritten
        U[f"rz_{name}"] = SV.cand_rz(U, name, sh)
        return SV.run_book(book, V.oos_score(U, w10, odd).where(common).to_numpy())

    ref = {"base": p["icw9_seas"], "cand": p["cand_plus_icw9_seas"], "inc": p["increment_per_offset"],
           "wm": p["weight_matched_null_DESCRIPTIVE"]["draws"]}
    info = {"cand_weight_fit_odd_even": [w10[0][name], w10[1][name]], "rows": int(len(U)),
            "shuffle": "screen_insider_v2grid.shuffle_within_date on str_lowturn (all finite values incl. exact zeros)"}
    return r9, r10, null_book, ref, info


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cand", required=True, choices=["ear", "str_lowturn"])
    ap.add_argument("--draws", type=int, default=100)
    a = ap.parse_args()
    t0 = time.time()
    OUT.mkdir(parents=True, exist_ok=True)
    out_json = OUT / f"s1s2_{a.cand}.json"
    rep = json.loads(REPORTS[a.cand].read_text())
    failed = rep["failed_gates"]
    assert len(failed) == 1 and "g4" in failed[0], f"candidate is not a gate-4-only fail: {failed}"
    r9, r10, null_book, ref, info = (setup_ear if a.cand == "ear" else setup_str)(rep)

    out = {"prereg": "final/models/2026-10-01-stabilizer-rule-ear.md @ 3c6a321", "candidate": a.cand,
           "era": "2007-01-02..2019-12-31", "screen_failed_gates": failed, **info}
    out["reconcile"] = {"tol": TOL, "base": check("base", r9, ref["base"]), "cand": check(a.cand, r10, ref["cand"])}
    headline("base", r9); headline(a.cand, r10)
    inc = np.array(r10["per_offset"]) - np.array(r9["per_offset"])
    d = float(np.abs(inc - np.array(ref["inc"])).max())
    assert d < 1e-9, f"per-offset increments differ from the report (max {d})"
    out["reconcile"]["increment_per_offset_max_abs_diff"] = d
    out["reconcile"]["headline_pct"] = {"base": HEADLINE["base"], a.cand: HEADLINE[a.cand]}
    out["base"] = {**stats(r9), "per_offset": r9["per_offset"]}
    out["cand_book"] = {**stats(r10), "per_offset": r10["per_offset"]}
    log(f"[{a.cand}] RECONCILE OK base {r9['excess_cagr_vs_spy_mean40']:+.6f} sd40 {r9['sd40']:.6f} | "
        f"+cand {r10['excess_cagr_vs_spy_mean40']:+.6f} sd40 {r10['sd40']:.6f}")

    # ---- S2 (from the reconciled books)
    s2 = {"mean_increment": float(inc.mean()),
          "a_mean_increment_ge_0": bool(inc.mean() >= 0),
          "b_worst_offset_not_lower": bool(r10["min40"] >= r9["min40"]),
          "c_loyo_min_not_lower": bool(r10["loyo_min"] >= r9["loyo_min"]),
          "min40_base_cand": [r9["min40"], r10["min40"]], "loyo_min_base_cand": [r9["loyo_min"], r10["loyo_min"]]}
    s2["pass"] = bool(s2["a_mean_increment_ge_0"] and s2["b_worst_offset_not_lower"] and s2["c_loyo_min_not_lower"])
    out["S2"] = s2
    out_json.write_text(json.dumps(out, indent=1, default=float))

    # ---- S1 null
    base_sd, base_min, base_mean = r9["sd40"], r9["min40"], r9["excess_cagr_vs_spy_mean40"]
    real_red = base_sd - r10["sd40"]
    draws = []
    for seed in range(a.draws):
        r = null_book(seed)
        if seed < len(ref["wm"]):
            dd = abs(r["excess_cagr_vs_spy_mean40"] - ref["wm"][seed])
            assert dd < 1e-9, f"weight-matched null draw {seed} != report ({r['excess_cagr_vs_spy_mean40']} vs {ref['wm'][seed]})"
        draws.append({"seed": seed, **stats(r), "sd_reduction": float(base_sd - r["sd40"])})
        red = np.array([x["sd_reduction"] for x in draws])
        s1 = {"statistic": "sd40(base) - sd40(base+cand), ddof=0, weight-matched null (real fitted weights, no refit)",
              "n_draws": len(draws), "real_sd_reduction": float(real_red),
              "null_p50": float(np.percentile(red, 50)), "null_p80": float(np.percentile(red, 80)),
              "null_mean": float(red.mean()), "null_sd": float(red.std()),
              "null_min": float(red.min()), "null_max": float(red.max()),
              "percentile_of_real": float((red < real_red).mean()),
              "pass": bool(real_red > np.percentile(red, 80)),
              "first_20_draws_reproduce_report_weight_matched_null": bool(len(draws) >= len(ref["wm"]))}
        nm = np.array([x["min40"] for x in draws]); nn = np.array([x["excess_cagr_vs_spy_mean40"] for x in draws])
        nl = np.array([x["loyo_min"] for x in draws])
        s1["descriptive"] = {
            "min40": {"base": base_min, "real": r10["min40"], "null_p50": float(np.percentile(nm, 50)),
                      "null_p80": float(np.percentile(nm, 80)), "percentile_of_real": float((nm < r10["min40"]).mean())},
            "mean40": {"base": base_mean, "real": r10["excess_cagr_vs_spy_mean40"], "null_p50": float(np.percentile(nn, 50)),
                       "null_p80": float(np.percentile(nn, 80)),
                       "percentile_of_real": float((nn < r10["excess_cagr_vs_spy_mean40"]).mean())},
            "loyo_min": {"base": r9["loyo_min"], "real": r10["loyo_min"], "null_p50": float(np.percentile(nl, 50)),
                         "null_p80": float(np.percentile(nl, 80)), "percentile_of_real": float((nl < r10["loyo_min"]).mean())},
            "null_share_sd_reduction_gt_0": float((red > 0).mean())}
        out["S1"] = s1; out["null_draws"] = draws; out["runtime_s"] = time.time() - t0
        out_json.write_text(json.dumps(out, indent=1, default=float))
        log(f"[{a.cand}] null {seed}: sd40 {r['sd40']:.6f} reduction {base_sd - r['sd40']:+.6f} "
            f"(real {real_red:+.6f}; p80 so far {s1['null_p80']:+.6f}, pct {s1['percentile_of_real']:.2f})")
    assert out["S1"]["n_draws"] == a.draws
    out["complete"] = True
    out_json.write_text(json.dumps(out, indent=1, default=float))
    log(f"[{a.cand}] S1 pass {out['S1']['pass']} S2 pass {s2['pass']} -> wrote {out_json} ({time.time()-t0:.0f}s)")


if __name__ == "__main__":
    main()
