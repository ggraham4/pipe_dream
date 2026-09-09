"""
Round 10 (2026-09-08): why do two runs of the same model disagree?

    null_test.py   model top-5   $49,472   arith 2.93%/window   p76.5
    rank_depth.py  N=5           $24,041   arith 2.37%/window   p30.3

Those must be the same portfolio. null_test read picks from the saved retrain
(continuous_walkforward_pit_augmented_realistic_tradable.json); rank_depth
retrained and re-derived them. XGBoost with fixed params on fixed data is
deterministic, so a 2x gap in terminal wealth means one of:

  A. the two runs scored DIFFERENT WINDOWS. rank_depth refuses to record a
     ranking unless >=50 names are eligible AND >=50 realize successfully;
     the walk-forward needed only 5. Both happened to end at 117 windows,
     which does NOT mean they are the same 117.
  B. the two runs made DIFFERENT PICKS on shared windows -- a real
     reproducibility failure in training or scoring.
  C. the picks agree and the difference is downstream, in realization or
     costing.

Each leaves a different fingerprint. This tells them apart before anything in
the depth table gets interpreted.

    python3 reconcile_ranks.py
"""
import json

import numpy as np

from features import OUT_DIR

MODEL = OUT_DIR / "continuous_walkforward_pit_augmented_realistic_tradable.json"
RANKS = OUT_DIR / "rank_depth_ranks.json"

saved = {r["timepoint"]: list(r["picks"])
         for r in json.load(open(MODEL))["results"]}
ranks = {k: list(v) for k, v in json.load(open(RANKS)).items()}

sk, rk = set(saved), set(ranks)
print(f"saved retrain windows : {len(sk)}  {min(sk)} .. {max(sk)}")
print(f"rank_depth windows    : {len(rk)}  {min(rk)} .. {max(rk)}")
print(f"in both               : {len(sk & rk)}")
only_s, only_r = sorted(sk - rk), sorted(rk - sk)
if only_s:
    print(f"  only in saved retrain ({len(only_s)}): "
          f"{only_s[:8]}{' ...' if len(only_s) > 8 else ''}")
if only_r:
    print(f"  only in rank_depth    ({len(only_r)}): "
          f"{only_r[:8]}{' ...' if len(only_r) > 8 else ''}")

both = sorted(sk & rk)
exact = 0
overlaps = []
for k in both:
    a, b = saved[k], ranks[k][:5]
    overlaps.append(len(set(a) & set(b)))
    if a == b:
        exact += 1
overlaps = np.array(overlaps)

print(f"\nTOP-5 AGREEMENT on the {len(both)} shared windows:")
print(f"  identical (same names, same order) : {exact}")
print(f"  mean overlap of the 5 names        : {overlaps.mean():.2f} / 5 "
      f"({overlaps.mean() / 5:.0%})")
for v in range(6):
    c = int((overlaps == v).sum())
    if c:
        print(f"    {v}/5 overlap: {c} windows")

print("\nVERDICT")
if only_s or only_r:
    print("  (A) window sets DIFFER -- the two runs are not scoring the same")
    print("      periods, so their terminal values are not comparable at all.")
if len(both) and overlaps.mean() < 4.5:
    print("  (B) picks DIFFER on shared windows -- the model does not reproduce")
    print("      itself. That is a correctness bug, not a modelling result, and")
    print("      it invalidates every number derived from either run.")
if not (only_s or only_r) and len(both) and overlaps.mean() > 4.9:
    print("  (C) picks AGREE -- the discrepancy is downstream, in realization")
    print("      or costing. Compare per-window returns next.")

if len(both):
    worst = [both[i] for i in np.argsort(overlaps)[:5]]
    print("\nlowest-overlap windows for inspection:")
    for k in worst:
        print(f"  {k}  saved      = {saved[k]}")
        print(f"{'':14}rank_depth = {ranks[k][:5]}")
