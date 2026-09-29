"""
WO-25 (COO): re-derive the Theoretical composite's ICW weights on the v2
working panel (Gabe 2026-09-29: "re derive on v2, fit on 2020-26").
Method doc (committed before any backtest): final/models/2026-09-29-icw-v2-reweight.md

This step reads ONLY already-published numbers (no new outcome read):
  1. Name-check: the unchanged ICW rule reproduces the live constants from
     the live (v1) t's -- icw8 via ICW.fit_weights, icw9_seas via
     SI.fit_weights (8 v1 full-era t's + SEAS_T) -- exact at 4 dp.
  2. icw9_v2 = SI.fit_weights on
       8 non-SI factors: WO-23 period-A pooled NW t (v2 col c, cap150, h=40, 2007-2019)
       short_interest_days_to_cover: WO-23 period-B t (2020-01..2026-07-30)
     signs = ICW.SIGNS_V9_SEAS (unchanged).
  3. icw9_v2_si_floor = same, SI t = NaN (floor weight); must equal WO-23's
     "implied w A" column exactly.
The recomputation of those t's from the panel (to 1e-6) is done in
backtest_reweight.py, after the method-doc commit.

Usage: python final/src/reweight/derive_weights.py
Output: final/out/reweight/icw9_v2_weights.json
"""
import json
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
SRC = HERE.parent
sys.path.insert(0, str(SRC / "insider"))
sys.path.insert(0, str(SRC / "reset2026"))
import ic_weighted_composite as ICW   # noqa: E402
import screen_insider as SI           # noqa: E402

ROOT = HERE.parents[1]
AUDIT = ROOT / "out" / "audit"
OUT = ROOT / "out" / "reweight"
V1_REPORT = Path("/Users/ggraham/pipe_dream/final/out/reset2026/ic_weighted_composite_report.json")

SIGNS = dict(ICW.SIGNS_V9_SEAS)
FT = list(ICW.PRODUCTION_WEIGHTS_V9_SEAS)
SI_COL = "short_interest_days_to_cover"
NON_SI = [k for k in FT if k != SI_COL]


def r4(w):
    return {k: round(v, 4) for k, v in w.items()}


def name_check():
    t1 = {k: v["t"] for k, v in json.loads(V1_REPORT.read_text())["per_factor_t"]["full"].items()}
    w8 = ICW.fit_weights({k: {"t": v} for k, v in t1.items()}, list(ICW.PRODUCTION_WEIGHTS))
    w9 = SI.fit_weights({**t1, "seas": ICW.SEAS_T}, SIGNS)
    ok8 = r4(w8) == ICW.PRODUCTION_WEIGHTS
    ok9 = r4(w9) == ICW.PRODUCTION_WEIGHTS_V9_SEAS
    assert ok8 and ok9, (r4(w8), r4(w9))
    return {"v1_t_source": str(V1_REPORT), "v1_full_t": t1, "seas_t": ICW.SEAS_T,
            "icw8_full_precision": w8, "icw8_4dp_equals_PRODUCTION_WEIGHTS": ok8,
            "icw9_seas_full_precision": w9, "icw9_seas_4dp_equals_PRODUCTION_WEIGHTS_V9_SEAS": ok9}


def wo23_t():
    a = json.loads((AUDIT / "model_audit_wo23_A.json").read_text())["theoretical"]["factors"]
    b = json.loads((AUDIT / "model_audit_wo23_B.json").read_text())["theoretical"]["factors"]
    return ({k: a[k]["t"] for k in FT}, {k: b[k]["t"] for k in FT},
            {k: a[k]["implied_weight"] for k in FT})


def derive(tA, tB):
    t = {k: tA[k] for k in NON_SI}
    t[SI_COL] = tB[SI_COL]
    w = SI.fit_weights({k: t[k] for k in FT}, SIGNS)
    tf = {**t, SI_COL: float("nan")}
    wf = SI.fit_weights({k: tf[k] for k in FT}, SIGNS)
    return t, w, wf


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    nc = name_check()
    print("NAME-CHECK PASS: ICW rule reproduces PRODUCTION_WEIGHTS and PRODUCTION_WEIGHTS_V9_SEAS at 4 dp")
    tA, tB, implied_A = wo23_t()
    t, w, wf = derive(tA, tB)
    # SI-at-floor weights == WO-23's implied-A column (same rule, same t's)
    for k in FT:
        assert abs(wf[k] - implied_A[k]) < 1e-12, (k, wf[k], implied_A[k])
    print("CHECK PASS: icw9_v2_si_floor == WO-23 implied_weight (period A)")
    print(f"{'factor':32s} {'sign':>4s} {'t used':>9s} {'live':>8s} {'icw9_v2':>8s} {'SI@floor':>8s}")
    for k in FT:
        print(f"{k:32s} {SIGNS[k]:+d} {t[k]:+9.4f} {ICW.PRODUCTION_WEIGHTS_V9_SEAS[k]:+8.4f} "
              f"{w[k]:+8.4f} {wf[k]:+8.4f}")
    print(f"seas: WO-23 A t {tA['seas']:+.10f} vs SEAS_T {ICW.SEAS_T:+.10f} (diff {tA['seas']-ICW.SEAS_T:+.2e})")
    out = {"work_order": "WO-25 icw v2 reweight", "rule": "w_k = sign_k*max(0.1,|t_k|-1)/sum|.| (SI.fit_weights)",
           "signs": SIGNS, "name_check": nc,
           "t_used": t, "t_source": {k: ("WO-23 period B 2020-01-02..2026-07-30" if k == SI_COL
                                          else "WO-23 period A 2007-01-02..2019-12-31") for k in FT},
           "wo23_t_A": tA, "wo23_t_B": tB, "seas_t_wo23_A_minus_SEAS_T": tA["seas"] - ICW.SEAS_T,
           "icw9_v2_full_precision": w, "icw9_v2_4dp": r4(w),
           "icw9_v2_si_floor_full_precision": wf, "icw9_v2_si_floor_4dp": r4(wf),
           "live_icw9_seas_4dp": ICW.PRODUCTION_WEIGHTS_V9_SEAS}
    (OUT / "icw9_v2_weights.json").write_text(json.dumps(out, indent=1))
    print(f"wrote {OUT / 'icw9_v2_weights.json'}")


if __name__ == "__main__":
    main()
