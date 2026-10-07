"""WO-47 B: assign every differing pre-2020 row to a named cause, from the counterfactual outputs.
Writes final/out/tickerreuse/b_attribution.json."""
import json

import pandas as pd

from common import OUT, SCRATCH

cf = json.loads((OUT / "b_universe_cf.json").read_text())
rule = json.loads((OUT / "b_universe_rule.json").read_text())
v2a = json.loads((OUT / "b_v2_attrib.json").read_text())

# ---- B-XGB: all differences are one-sided (membership); 0 value differences on shared rows
X = pd.read_parquet(SCRATCH / "b_xgb_rowdiff.parquet", columns=["ticker", "side"])
floor_set = set(rule["variants"]["unadj_floor+agree (current rule)"]["missing_vs_sep11"])   # in Sep-11 only under adj floor
assert rule["variants"]["adj_floor+agree"]["equals_sep11"]
sw = cf["single_swaps_from_sep"]
master_add = set(sw["master=cur,shares=sep,through=sep"]["added"])
dates_add = set(sw["master=sep,shares=sep,through=cur"]["added"])
shares_add = set(sw["master=sep,shares=cur,through=sep"]["added"]) | set(sw["master=sep,shares=cur,through=sep"]["removed"])
REUSE = {"ADRX"}


def cause_xgb(r):
    if r.side == "both":
        return "unexplained (value change)"
    if r.side == "sep11_only" and r.ticker in floor_set:
        return "U-floor: $10 floor on split-adjusted close in the Sep-11 universe, closeunadj now"
    if r.side == "current_only" and r.ticker in REUSE and r.ticker in dates_add:
        return "R-reuse: new listing under a recycled symbol became eligible after Sep-11, pulling in the old entity's rows"
    if r.side == "current_only" and r.ticker in master_add:
        return "U-master: symbol absent from the 2026-09-08 tickers_master, present in 2026-09-26"
    if r.side == "current_only" and r.ticker in dates_add:
        return "U-dates: first PIT-eligible after the Sep-11 build (2026-09-11..10-05)"
    if r.ticker in shares_add:
        return "U-shares"
    return "unexplained"


t = X.drop_duplicates(["ticker", "side"]).copy()
t["cause"] = t.apply(cause_xgb, axis=1)
X = X.merge(t, on=["ticker", "side"])
xgb = X.groupby("cause").agg(rows=("ticker", "size"), tickers=("ticker", lambda s: sorted(set(s)))).reset_index()
n = len(X)
expl = int(X[~X.cause.str.startswith("unexplained")].shape[0])

# ---- B-v2
V = pd.read_parquet(SCRATCH / "b_v2_rowdiff.parquet")
lab = V.d_forward_return_40 | V.d_forward_return_tradable_40
flag = V.d_eligible_cap500_v1 | V.d_eligible_cap150_v1
other = V[[c for c in V.columns if c.startswith("d_") and c not in
           ("d_forward_return_40", "d_forward_return_tradable_40", "d_eligible_cap500_v1", "d_eligible_cap150_v1")]].any(axis=1)
v1_ok = (v2a["cap500_v1_changed_and_now_equals_v2_flag"] == v2a["cap500_v1_changed_rows"]
         and v2a["cap150_v1_changed_and_now_equals_v2_flag"] == v2a["cap150_v1_changed_rows"])
cv = pd.Series("unexplained", index=V.index)
cv[flag & ~lab & ~other & v1_ok] = "V1-flags: *_v1 columns rewritten with the v2 eligibility rule (live eligible_cap* unchanged)"
cv[lab & ~flag & ~other & V.ticker.isin(REUSE)] = "R-reuse: ADRX 2006 labels now exit in 2026"
v2 = cv.value_counts().to_dict()
res = {"B_XGB": {"differing_rows": n, "explained_rows": expl, "explained_pct": round(100 * expl / n, 3),
                 "by_cause": xgb.to_dict("records")},
       "B_v2": {"differing_rows": int(len(V)), "by_cause": v2,
                "explained_pct": round(100 * (1 - v2.get("unexplained", 0) / len(V)), 3)},
       "bar_95pct_both": None}
res["bar_95pct_both"] = bool(res["B_XGB"]["explained_pct"] >= 95 and res["B_v2"]["explained_pct"] >= 95)
(OUT / "b_attribution.json").write_text(json.dumps(res, indent=2, default=str))
print(json.dumps(res, indent=2, default=str))
