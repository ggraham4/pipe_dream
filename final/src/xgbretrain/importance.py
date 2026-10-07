"""
WO-43: how much do Arms 1/2 use the 5 new columns? Aggregates the per-fit
stats run_arms.py wrote (total gain, split counts, parent-child split pairs,
mean |SHAP| on every 20th score date).

Output: final/out/xgbretrain/importance.json
"""
import glob
import json
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
OUTD = HERE.parents[1] / "out" / "xgbretrain"
STORE = Path.home() / ".cache" / "wo43_xgbretrain"
NEW = ["io_gap", "seas", "sue", "ear", "str_lowturn"]


def main():
    cols = json.loads((OUTD / "store_meta.json").read_text())["feature_cols_24"] + NEW
    out = {}
    for arm in ("arm1", "arm2"):
        st = {}
        for f in sorted(glob.glob(str(OUTD / "scores" / arm / "chunk_*.json"))):
            st.update(json.loads(Path(f).read_text()))
        dates = sorted(st)
        G = np.array([st[d]["gain"] for d in dates])
        Gs = G / G.sum(axis=1, keepdims=True)
        S = np.array([st[d]["splits_by_feature"] for d in dates])
        pt = np.array([st[d]["pairs_total"] for d in dates]); pno = np.array([st[d]["pairs_new_old"] for d in dates])
        pnn = np.array([st[d]["pairs_new_new"] for d in dates]); tn = np.array([st[d]["trees_using_new"] for d in dates])
        sh = [(d, st[d]["mean_abs_shap"]) for d in dates if "mean_abs_shap" in st[d]]
        SH = np.array([v for _, v in sh])
        yrs = np.array([int(d[:4]) for d in dates])
        res = {"n_fits": len(dates),
               "gain_share_mean": {c: float(Gs[:, i].mean()) for i, c in enumerate(cols)},
               "new_cols_gain_share_total_mean": float(Gs[:, 24:].sum(axis=1).mean()),
               "new_cols_gain_share_by_year": {int(y): float(Gs[yrs == y, 24:].sum(axis=1).mean()) for y in np.unique(yrs)},
               "split_share_new_cols": float(S[:, 24:].sum() / S.sum()),
               "splits_per_fit_new": {c: float(S[:, 24 + j].mean()) for j, c in enumerate(NEW)},
               "parent_child_pairs_per_fit": float(pt.mean()),
               "pairs_new_x_old_per_fit": float(pno.mean()), "pairs_new_x_new_per_fit": float(pnn.mean()),
               "share_pairs_involving_new": float((pno + pnn).sum() / pt.sum()),
               "trees_using_new_per_fit_of_100": float(tn.mean()),
               "shap_n_dates": len(sh),
               "mean_abs_shap_share": ({c: float((SH[:, i] / SH.sum(axis=1)).mean()) for i, c in enumerate(cols)}
                                       if len(sh) else {}),
               "top5_gain_cols": sorted(cols, key=lambda c: -Gs[:, cols.index(c)].mean())[:5]}
        out[arm] = res
        print(arm, res["new_cols_gain_share_total_mean"], res["share_pairs_involving_new"], res["top5_gain_cols"])
    (OUTD / "importance.json").write_text(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
