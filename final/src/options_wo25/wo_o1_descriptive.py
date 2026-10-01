"""
WO-35 descriptive add-on to WO-O1. Changes no decision: the verdict is the one
in wo_o1_results.json. From the positions file the runner wrote (gitignored
wo_o1_positions.parquet) it rebuilds each arm's per-cycle book, asserts that the
annualized excess equals wo_o1_results.json, and reports the worst cycle
("worst month") and the mean per-cycle returns.

    cd final/src/options_wo25 && /opt/anaconda3/envs/pipe_dream/bin/python wo_o1_descriptive.py
"""
from __future__ import annotations

import json

import pandas as pd

import run_wo_o1 as W


def cyc(df):
    g = df.groupby("date").agg(pnl=("pnl", "sum"), coll=("collateral", "sum"), spy=("spy_tr", "first"),
                               days=("days", "first"), n=("pnl", "size"))
    g["R"] = g.pnl / g.coll
    g["ex"] = g.R - g.spy
    return g


def main():
    res = json.loads((W.OUT / "wo_o1_results.json").read_text())
    P = pd.read_parquet(W.OUT / "wo_o1_positions.parquet")
    out = {}
    for tgt, B in P.groupby("bucket"):
        sc = B[B.score.notna()]
        k = sc.groupby("date").score.transform(lambda s: max(1, int(round(W.QUINTILE * len(s)))))
        rk = sc.groupby("date").score.rank(ascending=False, method="first")
        cell = res["cells"][str(tgt)]
        out[str(tgt)] = {}
        for arm, g in (("arm_a", cyc(B)), ("arm_b_icw8", cyc(sc[rk <= k]))):
            ann = float(g.ex.mean() * 365.25 / g.days.mean())
            assert abs(ann - cell[arm]["excess_ann"]) < 1e-9, (tgt, arm, ann, cell[arm]["excess_ann"])
            i, j = g.ex.idxmin(), g.R.idxmin()
            out[str(tgt)][arm] = {
                "excess_ann_recomputed": ann, "n_cycles": int(len(g)),
                "worst_excess_cycle": {"entry": str(i.date()), "excess": float(g.ex[i]), "book_R": float(g.R[i]), "spy_tr": float(g.spy[i])},
                "worst_book_return_cycle": {"entry": str(j.date()), "book_R": float(g.R[j]), "spy_tr": float(g.spy[j])},
                "mean_cycle_R": float(g.R.mean()), "mean_cycle_spy_tr": float(g.spy.mean()),
                "mean_positions_per_cycle": float(g.n.mean())}
            print(tgt, arm, "ann %.4f" % ann, out[str(tgt)][arm]["worst_excess_cycle"], out[str(tgt)][arm]["worst_book_return_cycle"])
        out[str(tgt)]["rows_without_score_in_arm_a"] = int(B.score.isna().sum())
    (W.OUT / "wo_o1_descriptive.json").write_text(json.dumps(out, indent=2))
    print("recomputed excess_ann matches wo_o1_results.json in all 6 cells; wrote wo_o1_descriptive.json")


if __name__ == "__main__":
    main()
