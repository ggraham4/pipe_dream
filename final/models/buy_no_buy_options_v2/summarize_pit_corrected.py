import json
import numpy as np
import pandas as pd
from pathlib import Path

OUT_DIR = Path(__file__).resolve().parent
REPO_FINAL = OUT_DIR.parents[1]

rows = json.load(open(OUT_DIR / "pit_corrected_results.json"))
rows = [r for r in rows if r.get("baseline_eq_pct") is not None]

spy = pd.read_csv(REPO_FINAL / "scripts" / "td_data_local" / "SPY.csv", parse_dates=["date"]).sort_values("date")
def spy_ret(tp_str):
    T = pd.Timestamp(tp_str)
    e = spy[spy["date"] <= T]
    x = spy[spy["date"] <= T + pd.Timedelta(days=32)]
    if e.empty or x.empty: return None
    return (x.iloc[-1]["close"]/e.iloc[-1]["close"] - 1)*100

for label, key in [("baseline_eq","baseline_eq_pct"), ("baseline_kelly","baseline_kelly_pct"),
                    ("idea3_eq","idea3_eq_pct"), ("idea3_kelly","idea3_kelly_pct")]:
    vals = [r[key] for r in rows]
    spys = [spy_ret(r["timepoint"]) for r in rows]
    wins = sum(1 for v,s in zip(vals,spys) if s is not None and v > s)
    print(f"{label:16s} n={len(vals)} avg={np.mean(vals):7.2f}  std={np.std(vals):7.2f}  win={wins}/{len(vals)}  vals={vals}")

print("\nSPY returns per timepoint:", {r['timepoint']: round(spy_ret(r['timepoint']),2) for r in rows})
