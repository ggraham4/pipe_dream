"""WO-60 aggregate: null percentiles, Gate A, S1-S8 / K1-K4 verdict per the frozen pre-reg.
Writes final/out/shortbook/wo60_report.json."""
import glob
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import sb_common as K  # noqa: E402
import build_si as BS  # noqa: E402


def null(tier):
    v = np.array([json.loads(Path(f).read_text())["M"] for f in sorted(glob.glob(str(K.OUT_BIG / "null" / tier / "*.json")))])
    return {"n": int(len(v)), "p50": float(np.percentile(v, 50)), "p80": float(np.percentile(v, 80)),
            "p95": float(np.percentile(v, 95)), "mean": float(v.mean()), "sd": float(v.std()), "max": float(v.max())}


def a1():
    x = pd.read_parquet(BS.OUTP, columns=["datadate", "available"])
    lag_ok = bool((x["available"] == x["datadate"] + pd.offsets.BDay(8)).all())
    return {"si_available_eq_settlement_plus_8bd": lag_ok,
            "si_attach": "merge_asof(direction=backward) on available <= date, 45d staleness (build_si.attach)",
            "seas": "seas_live.seas_asof asserts last used month ends < t; A5 shows ext == seas_live exactly",
            "panel_factors": "composite_panel_v2 PIT columns (live scorer reads the same columns)",
            "pass": lag_ok}


def tier_block(tier, rep_null, real):
    p = real["primary_H1_B1"]
    return {"M": p["M"], "null": rep_null, "B3": real["B3_stress_H1"]["M"], "offsets_pos": p["offsets_pos"],
            "loyo_min": p["loyo_min"], "loyo_min_year": p["loyo_min_year"], "max_year_share": p["max_year_share"],
            "max_share_year": p["max_share_year"], "S6a": real["S6a_sector_neutral_H1"]["M"], "S6b_H2": real["H2_beta_SPY_B1"]["M"],
            "S6c": real["S6c_lowSIR_H1"]["M"], "S7_5": real["S7_frac0.05_H1"]["M"], "S7_20": real["S7_frac0.2_H1"]["M"],
            "H3": real["H3_spy1x_B1"]["M"], "no_fee": real["no_fee_H1"]["M"], "cap2x": real["cap_2x_H1_descr"]["M"]}


def main():
    pre = json.loads((K.OUT / "prechecks.json").read_text())
    a4 = json.loads((K.OUT / "gate_a4.json").read_text())
    rep = {"prereg": "final/models/2026-10-10-short-book-prereg.md (sha256 33fd448c...; commit c8f32d1)", "tiers": {}}
    for tier in ("cap2000", "cap150"):
        real = json.loads((K.OUT / f"real_{tier}.json").read_text())
        rep["tiers"][tier] = tier_block(tier, null(tier), real)
    b = rep["tiers"]["cap2000"]
    real = json.loads((K.OUT / "real_cap2000.json").read_text())
    A = {"A1": a1(),
         "A2": {**real["descr"]["A2"], "pass": real["descr"]["A2"]["dropped_nan_labels"] == 0},
         "A3": {"null_p50": b["null"]["p50"], "pass": b["null"]["p50"] <= 0},
         "A4": {"n_checked": a4["n_checked"], "n_ok": a4["n_ok"], "pass": a4["A4_pass"]},
         "A5": {"max_abs_score_diff": max(x["max_abs_score_diff"] for t in pre["a5"].values() for x in t),
                "min_overlap": min(x["bottom_decile_overlap"] for t in pre["a5"].values() for x in t)}}
    A["A5"]["pass"] = A["A5"]["max_abs_score_diff"] < 1e-9 and A["A5"]["min_overlap"] == 1.0
    rep["gate_A"] = A
    gate_all = all(v["pass"] for v in A.values())
    S = {"S1": (b["M"], b["M"] >= 0.03), "S2": (b["B3"], b["B3"] >= 0.01), "S3": ((b["M"], b["null"]["p95"]), b["M"] > b["null"]["p95"]),
         "S4": (b["offsets_pos"], b["offsets_pos"] >= 36),
         "S5": ((b["loyo_min"], b["max_year_share"]), b["loyo_min"] >= 0.015 and b["max_year_share"] is not None and b["max_year_share"] <= 0.35),
         "S6": ((b["S6a"], b["S6b_H2"], b["S6c"]), b["S6a"] > 0 and b["S6b_H2"] > 0 and b["S6c"] > 0),
         "S7": ((b["S7_5"], b["S7_20"]), b["S7_5"] > 0 and b["S7_20"] > 0), "S8": (None, gate_all)}
    Kc = {"K1": (b["M"], b["M"] <= 0), "K2": (b["S6c"], b["S6c"] <= 0), "K3": ((b["M"], b["null"]["p80"]), b["M"] <= b["null"]["p80"]),
          "K4": (b["loyo_min"], b["loyo_min"] <= 0)}
    rep["success"] = {k: {"value": v[0], "pass": bool(v[1])} for k, v in S.items()}
    rep["kill"] = {k: {"value": v[0], "fires": bool(v[1])} for k, v in Kc.items()}
    rep["verdict"] = ("DEAD" if any(v[1] for v in Kc.values()) else
                      "PROMOTE-CANDIDATE" if all(v[1] for v in S.values()) else "ITERATE")
    (K.OUT / "wo60_report.json").write_text(json.dumps(rep, indent=1, default=float))
    print(json.dumps(rep, indent=1, default=float))


if __name__ == "__main__":
    main()
