"""
WO-49: screen opp_buy_90 (opportunistic insider buyers) -- gates 1-7.
Pre-registration: final/models/2026-10-08-opportunistic-insiders.md section 1
(committed and pushed before any outcome statistic was computed).

Era 2007-01-02..2019-12-31 ONLY (hard asserts; the harness loader asserts too).
Harness imported read-only: signcheck/dropcheck (D.load, S.score, picks_fast,
chains, diff_block), screen_insider_v2grid (ic_gates, shuffle_within_date,
add_ranks). Base book = icw5_seas (PRODUCTION_WEIGHTS_V5_SEAS), reconciled to the
WO-48b D4 arm (real_A.json arm_mean40 = 0.036442521084825354) before anything else.

Usage (python = /opt/anaconda3/envs/pipe_dream/bin/python, under caffeinate -i):
  oppinsider.py --real                -> out/oppinsider/parts/real.json
  oppinsider.py --null 100 --procs 4  -> out/oppinsider/parts/null/NNN.json
  oppinsider.py --recheck             -> null draw 0 rerun identical
  oppinsider.py --aggregate 100       -> out/oppinsider/opp_report.json
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
sys.path.insert(0, str(SRC / "signcheck"))
import dropcheck as D   # noqa: E402  (imports signcheck -> stateint -> harness)

S, G = D.S, D.G
COL = "opp_buy_90"
SIGN = +1
T_BAR = 2.58
SECTOR_T_BAR = 1.0
YEAR_SHARE_MAX = 0.45
OFF_POS_MIN = 26
N_NULL = 100
SEED0 = 49000
HOLDOUT = pd.Timestamp("2020-01-01")
REF_V5 = 0.036442521084825354          # WO-48b real_A.json arms.D4.arm_mean40 (weights == V5_SEAS)
OUT = FINAL / "out" / "oppinsider"
PARTS = OUT / "parts"
NULLD = PARTS / "null"
FEAT = OUT / "cache" / "opp_features.parquet"
ICW_REPORT = Path("/Users/ggraham/pipe_dream/final/out/reset2026/ic_weighted_composite_report.json")
PANEL_V1 = Path("/Users/ggraham/pipe_dream/final/out/reset2026/composite_panel.parquet")
log = D.log


# ------------------------------------------------------------------ load
def load():
    U = D.load("A")
    assert U["date"].max() < HOLDOUT and max(G["all_dates"]) < HOLDOUT and G["spy"].index.max() < HOLDOUT, "HOLD-OUT BREACH"
    ICW = G["ICW"]
    V5 = dict(ICW.PRODUCTION_WEIGHTS_V5_SEAS)
    G["V5"] = V5
    f = pd.read_parquet(FEAT, columns=["ticker", "date", COL])
    f["ticker"] = f["ticker"].astype(str); f["date"] = pd.to_datetime(f["date"])
    assert f["date"].max() < HOLDOUT
    key = pd.MultiIndex.from_arrays([U["ticker"], U["date"]])
    v = f.set_index(["ticker", "date"])[COL]
    assert v.index.is_unique
    U[COL] = v.reindex(key).to_numpy(np.float64)
    G["V"].add_ranks(U, [COL])
    G["rz"][COL] = U[f"rz_{COL}"].to_numpy(np.float64)
    log(f"factor merged: non-null {np.isfinite(U[COL]).mean():.4%}, fire {(U[COL] > 0).mean():.4%}")
    return U


def base_v5():
    ch5 = S.chains(S.picks_fast(S.score(G["V5"])))
    got = float(G["DD"].per_offset(ch5).mean())
    assert abs(got - REF_V5) < 1e-10, f"V5 RECONCILE FAIL {got} vs {REF_V5}"
    log(f"icw5_seas reconcile OK {got:+.9f} (ref {REF_V5})")
    return ch5, got


def scale_k():
    """k such that V5_k = sign_k * max(0.1, |t_k|-1) * k (frozen rule, full-era t's)."""
    ICW = G["ICW"]
    t = {c: v["t"] for c, v in json.loads(ICW_REPORT.read_text())["per_factor_t"]["full"].items()}
    t["seas"] = ICW.SEAS_T
    raw = {c: max(0.1, abs(t[c]) - 1.0) for c in G["V5"]}
    k = sum(abs(w) for w in G["V5"].values()) / sum(raw.values())
    for c, w in G["V5"].items():
        assert abs(abs(w) - raw[c] * k) < 2e-4, (c, w, raw[c] * k)
    return k, raw


def w6(t_opp):
    k, raw = scale_k()
    w = SIGN * max(0.1, abs(t_opp) - 1.0) * k
    return {**G["V5"], COL: w}, k, raw


def ic_block(U):
    r, _ = G["V"].ic_gates(U, COL)
    g = {"g1_pooled_t": bool(SIGN * r["pooled"]["t"] >= T_BAR),
         "g2_halves": bool(SIGN * r["odd"]["mean"] > 0 and SIGN * r["even"]["mean"] > 0),
         "g3_sector_both_sides": bool(SIGN * r["sector_both_sides"]["t"] >= SECTOR_T_BAR),
         "g4_offsets": bool(r["offsets"]["sign_flips"] == 0 and np.sign(r["pooled"]["mean"]) == SIGN),
         "g5_loyo": bool(SIGN * r["year_share"]["total_sum_ic"] > 0
                         and r["year_share"]["max_share"] <= YEAR_SHARE_MAX
                         and SIGN * min(r["loyo_t"].values()) > 0)}
    r["loyo_min_t"] = float(min(r["loyo_t"].values()))
    return r, g


# ------------------------------------------------------------------ real
def run_real():
    T0 = time.time()
    PARTS.mkdir(parents=True, exist_ok=True)
    U = load()
    _, rec9 = D.base_chain("A")
    ch5, got5 = base_v5()
    out = {"work_order": "WO-49", "era": "2007-01-02..2019-12-31", "reconcile": {"icw9_seas": rec9, "icw5_seas": got5, "icw5_ref": REF_V5}}
    # gates 1-5 (primary, column c cap150)
    r, g = ic_block(U)
    out["ic"] = r; out["gates_1_5"] = g
    log(f"IC t {r['pooled']['t']:+.3f} mean {r['pooled']['mean']:+.5f} n_dates {r['pooled']['n_dates']}; gates {g}")
    # gate 7b placebo: seed-0 null shuffle through gate 1
    U["_plc"] = G["V"].shuffle_within_date(U, COL, SEED0)
    pr, _ = G["V"].ic_gates(U, "_plc")
    out["placebo"] = {"seed": SEED0, "pooled": pr["pooled"], "fails_gate1": bool(SIGN * pr["pooled"]["t"] < T_BAR)}
    U.drop(columns=["_plc"], inplace=True)
    log(f"placebo t {pr['pooled']['t']:+.3f}")
    # registered secondary (report only): added tickers (column c minus column b)
    old_t = set(pd.read_parquet(PANEL_V1, columns=["ticker"])["ticker"].astype(str).unique())
    Ua = U[~U["ticker"].isin(old_t)].reset_index(drop=True)
    ra, ga = ic_block(Ua)
    out["secondary_added"] = {"rows": int(len(Ua)), "tickers": int(Ua["ticker"].nunique()), "ic": ra, "gates_1_5": ga,
                              "fire": float((Ua[COL] > 0).mean())}
    log(f"secondary added: t {ra['pooled']['t']:+.3f}; gates {ga}")
    del Ua
    # gate 6 book
    W6, k, raw = w6(r["pooled"]["t"])
    ch6 = S.chains(S.picks_fast(S.score(W6)))
    d = S.diff_block(ch5, ch6)            # diff = icw6 - icw5
    po5 = G["DD"].per_offset(ch5)
    out["book"] = {"t_opp": r["pooled"]["t"], "k": k, "raw": raw, "W6": W6,
                   "icw5_mean40": float(po5.mean()), "icw5_sd40": float(np.std(po5)),
                   "icw6_mean40": float(G["DD"].per_offset(ch6).mean()), "paired": d}
    log(f"book: w_opp {W6[COL]:.5f}; icw6-icw5 {d['diff']*100:+.4f} pp/yr, {d['diff_offsets_pos']}/40 offsets > 0 "
        f"(base sd40 {np.std(po5)*100:.4f})")
    out["runtime_s"] = time.time() - T0
    (PARTS / "real.json").write_text(json.dumps(out, indent=1, default=float))


# ------------------------------------------------------------------ null
def prep_null():
    load()
    G["ch5"] = base_v5()[0]
    real = json.loads((PARTS / "real.json").read_text())
    G["W6"] = real["book"]["W6"]


def null_one(s, path=None):
    p = path or NULLD / f"{s:03d}.json"
    if p.exists():
        return s
    v = G["V"].shuffle_within_date(G["U"], COL, SEED0 + s)
    rz = G["SI"].rank_z(pd.DataFrame({"date": G["U"]["date"], "x": v}), "x").to_numpy(np.float64)
    ch = S.chains(S.picks_fast(S.score(G["W6"], {COL: rz})))
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
    x = json.loads((NULLD / "000.json").read_text())["inc"]
    y = json.loads(q.read_text())["inc"]
    q.unlink()
    (PARTS / "null_recheck.json").write_text(json.dumps({"draw0": x, "rerun": y, "identical": x == y}))
    assert x == y, "NULL RERUN MISMATCH"
    log("recheck identical")


# ------------------------------------------------------------------ aggregate
def aggregate(n):
    real = json.loads((PARTS / "real.json").read_text())
    inc = np.array([json.loads((NULLD / f"{s:03d}.json").read_text())["inc"] for s in range(n)])
    d = real["book"]["paired"]
    p80 = float(np.percentile(inc, 80))
    g6 = bool(d["diff"] > p80 and d["diff_offsets_pos"] >= OFF_POS_MIN)
    integ = json.loads((OUT / "opp_integrity.json").read_text())
    hc = integ.get("hand_check", [])
    g7 = bool(real["placebo"]["fails_gate1"] and len(hc) == 3 and all(h["steps_up_day_after"] and h["class"] == "opportunistic" for h in hc)
              and integ["pit_brute_force"]["mismatches"] == 0)
    gates = {**real["gates_1_5"], "g6_book": g6, "g7_gateA": g7}
    verdict = "PASS (nomination only)" if all(gates.values()) else "KILL"
    r = real["ic"]
    rep = {"work_order": "WO-49", "factor": COL, "sign": SIGN, "prereg": "final/models/2026-10-08-opportunistic-insiders.md",
           "era": real["era"], "reconcile": real["reconcile"], "verdict": verdict, "gates": gates,
           "gate_numbers": {
               "g1_pooled_ic": r["pooled"], "bar": T_BAR,
               "g2_odd": r["odd"], "g2_even": r["even"],
               "g3_sector_both_sides": r["sector_both_sides"], "g3_factor_only_not_gated": r["sector_factor_only"],
               "g4_offset_flips": r["offsets"]["sign_flips"], "g4_offset_min_max": [r["offsets"]["min"], r["offsets"]["max"]],
               "g5_max_year_share": r["year_share"]["max_share"], "g5_max_year": r["year_share"]["max_year"],
               "g5_loyo_min_t": r["loyo_min_t"], "g5_total_sum_ic": r["year_share"]["total_sum_ic"],
               "g6_paired_inc": d["diff"], "g6_offsets_pos": d["diff_offsets_pos"], "g6_null_p80": p80,
               "g6_null": {"n": n, "p50": float(np.percentile(inc, 50)), "p95": float(np.percentile(inc, 95)),
                           "mean": float(inc.mean()), "sd": float(inc.std()), "pct_below_real": float((inc < d["diff"]).mean())},
               "g6_base_sd40_not_bar": real["book"]["icw5_sd40"], "g6_w_opp": real["book"]["W6"][COL],
               "g7_placebo_t": real["placebo"]["pooled"]["t"], "g7_pit_brute_force": integ["pit_brute_force"],
               "g7_hand_check": [{k: h[k] for k in ("ticker", "owner", "filing_date", "class", "steps_up_day_after",
                                                    "factor_on_and_before_filing_date", "factor_after_filing_date")} for h in hc]},
           "null_recheck": json.loads((PARTS / "null_recheck.json").read_text()),
           "secondary_added_report_only": {"pooled": real["secondary_added"]["ic"]["pooled"],
                                           "gates_1_5": real["secondary_added"]["gates_1_5"],
                                           "sector_both_sides": real["secondary_added"]["ic"]["sector_both_sides"]},
           "book_detail": {k: real["book"]["paired"][k] for k in real["book"]["paired"] if k != "diff_per_offset"}}
    (OUT / "opp_report.json").write_text(json.dumps(rep, indent=1, default=float))
    print(json.dumps({"verdict": verdict, "gates": gates}, indent=1))
    print(json.dumps(rep["gate_numbers"], indent=1, default=float)[:4000])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--real", action="store_true")
    ap.add_argument("--null", type=int, default=0)
    ap.add_argument("--procs", type=int, default=4)
    ap.add_argument("--recheck", action="store_true")
    ap.add_argument("--aggregate", type=int, default=0)
    a = ap.parse_args()
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
