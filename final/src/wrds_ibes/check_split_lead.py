"""WO-53 factor-only check: does IBES move to a new share basis BEFORE the ex-date?
Rows (cap150, finite rev3) whose permno has a CRSP distcd-5 event with exdt in (s1, t]:
compare their |rev3| and F1/F0 with k against clean rows. No outcome is read."""
import json
from pathlib import Path

import numpy as np
import pandas as pd

OUT = Path(__file__).resolve().parents[2] / "out" / "wrds_ibes"
f = pd.read_parquet(OUT / "cache" / "rev3_factor.parquet", columns=["date", "permno", "s1", "rev3", "F1", "F0", "cap150"])
f = f[f.cap150 & f.rev3.notna()].reset_index(drop=True)
ev = pd.read_parquet("/Users/ggraham/pipe_dream/final/data/wrds/ibes/crsp_dsedist_facshr.parquet")
ev = ev[ev.distcd.astype(int) // 1000 == 5][["permno", "exdt", "facshr"]]
ev["permno"] = ev.permno.astype(float)
x = f[["permno", "s1", "date"]].reset_index().merge(ev, on="permno")
x = x[(x.exdt > x.s1) & (x.exdt <= x.date)]
k = x.groupby("index").facshr.apply(lambda s: float(np.prod(1 + s.to_numpy())))
f["lead"] = f.index.isin(k.index)
f["klead"] = 1.0
f.loc[k.index, "klead"] = k.to_numpy()
L = f[f.lead]
ratio = (L.F1 / L.F0).where((L.F0.abs() > 0.05) & (L.F1 * L.F0 > 0))
near_k = np.isclose(ratio, 1 / L.klead, rtol=0.15) & ~np.isclose(L.klead, 1, rtol=0.15)
q = lambda s: s.abs().quantile([.5, .9, .99]).round(5).tolist()
res = {"lead_rows": int(f.lead.sum()), "lead_share": float(f.lead.mean()),
       "abs_rev3_q50_90_99_lead": q(L.rev3), "abs_rev3_q50_90_99_clean": q(f[~f.lead].rev3),
       "lead_rows_F1_over_F0_near_1_over_k": int(near_k.sum()),
       "lead_rows_with_ratio_defined": int(ratio.notna().sum())}
print(res)
m = json.loads((OUT / "rev3_integrity.json").read_text())
m["split_lead_check"] = res
(OUT / "rev3_integrity.json").write_text(json.dumps(m, indent=1, default=str))
