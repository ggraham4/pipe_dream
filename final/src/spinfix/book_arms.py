"""WO-57 Phase 2 (pre-registered): icw5_seas book on the spin-fixed patch panel, one arm per process.

Pre-registration: final/models/2026-10-09-spinfix-builder-prereg.md (hash asserted).
icw5_seas, v2 column c, cap150, decile_volq, net 15bp, h=40, 40 offsets, 2007-01-02..2019-12-31, excess vs SPY.
Harness = WO-54 path (signcheck/dropcheck.load("A"), score, picks_fast, chains). The U frame is patched from
final/out/spinfix_builder/patch_panel.parquet INSIDE load_theo, i.e. before V.add_ranks and V.Book, so ranks,
vol buckets, inverse-vol weights and labels all see the patched values.
Arms: U (all m = 1 recompute), L (labels fixed), F (features fixed), B (both; primary), B1 (B + variant V1).
    python book_arms.py --arm U      -> final/out/spinfix_builder/parts/arm_U.json
    python book_arms.py --compare    -> final/out/spinfix_builder/phase2_book.json
"""
from __future__ import annotations

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
PREREG = FINAL / "models" / "2026-10-09-spinfix-builder-prereg.md"
PREREG_SHA = "a4c44e9b813a7e656f42da8cbba56da64cc22c9e02f009336a1ca33de1d85d56"
assert hashlib.sha256(PREREG.read_bytes()).hexdigest() == PREREG_SHA, "PRE-REG CHANGED SINCE FREEZE: STOP"

OUT = FINAL / "out" / "spinfix_builder"
PARTS = OUT / "parts"
PATCH = OUT / "patch_panel.parquet"
REF_V5 = 0.036442521084825354          # WO-48b / WO-54 unfixed icw5_seas
REF_WO54_FIXED = None                  # read from final/out/spinfix/phase2.json
HOLDOUT = pd.Timestamp("2020-01-01")
FEAT = {"momentum_12_1": "mom", "seas": "seas", "volatility_60": "vol", "pct_from_high_252": "pfh"}
ARMS = {"U": ("u", "u"), "L": ("u", "f"), "F": ("f", "u"), "B": ("f", "f"), "B1": ("f1", "f1")}


def run_arm(arm):
    sys.path.insert(0, str(SRC / "signcheck"))
    import dropcheck as D  # noqa: E402
    import model_audit_wo23 as MA  # noqa: E402  (on sys.path via signcheck -> stateint)
    S, G = D.S, D.G
    fs, ls = ARMS[arm]
    pp = pd.read_parquet(PATCH)
    pp["date"] = pd.to_datetime(pp["date"])
    pp = pp.set_index(["ticker", "date"])
    assert pp.index.is_unique
    orig = MA.load_theo
    info = {}

    def patched(period, tier="cap150"):
        U, all_dates, spy = orig(period, tier)
        key = pd.MultiIndex.from_arrays([U["ticker"].astype(str), pd.to_datetime(U["date"])])
        hit = key.isin(pp.index)
        sub = pp.reindex(key[hit])
        info["patched_rows"] = int(hit.sum())
        for col, ab in list(FEAT.items()) + [("gross_return_40", "lab")]:
            s = fs if col != "gross_return_40" else ls
            v = sub[f"{ab}_{s}"].to_numpy(np.float64)
            old = U.loc[hit, col].to_numpy(np.float64)
            U.loc[hit, col] = v.astype(U[col].dtype)
            new = U.loc[hit, col].to_numpy(np.float64)
            info[f"changed_{col}"] = int((~((old == new) | (np.isnan(old) & np.isnan(new)))).sum())
        return U, all_dates, spy

    MA.load_theo = patched
    t0 = time.time()
    U = D.load("A")
    assert U["date"].max() < HOLDOUT and max(G["all_dates"]) < HOLDOUT and G["spy"].index.max() < HOLDOUT, "HOLD-OUT BREACH"
    V5 = dict(G["ICW"].PRODUCTION_WEIGHTS_V5_SEAS)
    sc = S.score(V5)
    pk = S.picks_fast(sc)
    ch = S.chains(pk)
    po = G["DD"].per_offset(ch)
    yrs, lm = G["DD"].loyo_vec(ch)
    out = {"arm": arm, "features": fs, "labels": ls, "mean40": float(po.mean()), "per_offset": po.tolist(),
           "loyo_years": yrs, "loyo": lm.tolist(), "patch": info,
           "picks": {str(pd.Timestamp(d).date()): sorted(G["uniq"][list(v[1])].tolist()) for d, v in pk.items()},
           "runtime_s": round(time.time() - t0, 1)}
    if arm == "U":
        out["reconcile_diff_vs_REF_V5"] = out["mean40"] - REF_V5
        assert abs(out["mean40"] - REF_V5) < 1e-10, f"C4 FAIL: U {out['mean40']} vs {REF_V5}"
    PARTS.mkdir(parents=True, exist_ok=True)
    (PARTS / f"arm_{arm}.json").write_text(json.dumps(out))
    print(f"arm {arm}: mean40 {out['mean40']:+.6%}  patch {info}  ({out['runtime_s']}s)", flush=True)


def compare():
    A = {a: json.loads((PARTS / f"arm_{a}.json").read_text()) for a in ARMS if (PARTS / f"arm_{a}.json").exists()}
    u = A["U"]
    po0 = np.array(u["per_offset"])
    wo54 = json.loads((FINAL / "out" / "spinfix" / "phase2.json").read_text())
    rep = {"model": "icw5_seas", "era": ["2007-01-02", "2019-12-31"], "tier": "cap150", "cost_bps": 15.0,
           "units": "fractions per year (0.01 = 1%/yr), 40-offset mean, net 15bp, excess vs SPY",
           "U_mean40": u["mean40"], "U_reconcile_diff_vs_REF_V5": u["mean40"] - REF_V5,
           "wo54_fixed_mean40": wo54["fixed"]["mean40"], "arms": {}}
    for a, r in A.items():
        if a == "U":
            continue
        po = np.array(r["per_offset"])
        d = po - po0
        ly = (np.array(r["loyo"]) - np.array(u["loyo"])).mean(axis=0)
        ov = [len(set(r["picks"][k]) & set(v)) / len(v) for k, v in u["picks"].items() if k in r["picks"] and v]
        rep["arms"][a] = {"mean40": r["mean40"], "delta": float(d.mean()), "offsets_positive": int((d > 0).sum()),
                          "offsets_zero": int((d == 0).sum()), "delta_min40": float(d.min()), "delta_max40": float(d.max()),
                          "delta_loyo_min": float(ly.min()), "delta_loyo_max": float(ly.max()),
                          "pick_overlap_mean": float(np.mean(ov)), "pick_dates_identical": int(sum(o == 1.0 for o in ov)),
                          "pick_dates": len(ov), "pick_date_sets_equal": set(r["picks"]) == set(u["picks"]),
                          "patch": r["patch"]}
    if "L" in rep["arms"]:
        rep["L_minus_wo54_fixed"] = rep["arms"]["L"]["mean40"] - wo54["fixed"]["mean40"]
    b = rep["arms"].get("B")
    if b:
        rep["primary_delta_B"] = b["delta"]
        rep["bar_delta_ge_m0p10pp"] = bool(b["delta"] >= -0.0010)
        rep["reweight_needed_abs_gt_0p25pp"] = bool(abs(b["delta"]) > 0.0025)
    (OUT / "phase2_book.json").write_text(json.dumps(rep, indent=1))
    for a, r in rep["arms"].items():
        print(f"{a}: {r['mean40']:+.4%}  delta {r['delta']:+.4%}  {r['offsets_positive']}/40  overlap {r['pick_overlap_mean']:.4f}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--arm", choices=list(ARMS))
    ap.add_argument("--compare", action="store_true")
    a = ap.parse_args()
    if a.compare:
        compare()
    else:
        run_arm(a.arm)
