"""WO-47: confirm high rank_pct = pick on each forward ledger (so the 12 reuse-contaminated rows at
rank_pct <= 0.42 were not picks), and look up IPHXU / TBCVU in the ledgers.
Writes final/out/tickerreuse/pick_direction.json."""
import json

import pandas as pd

from common import OUT, MAIN

L = MAIN / "out" / "reset2026"
O = MAIN / "out"
picks = {"composite (icw9_seas live)": O / "current_signal_composite.csv", "r252": O / "current_signal_r252.csv"}
rank = {"v3": "ic_weighted_rank_pct", "ext": "icw9_leverage_rank_pct", "sue": "icw9_sue_rank_pct",
        "seas": "icw9_seas_rank_pct", "io": "icw10_io_rank_pct", "r252": "icw9_r252_rank_pct"}
res = {"ledgers": {}}
for nm, col in rank.items():
    x = pd.read_csv(L / f"prediction_ledger_{nm}.csv", low_memory=False)
    last = x.panel_date.max()
    x = x[x.panel_date == last]
    for pk, p in picks.items():
        ps = set(pd.read_csv(p).ticker.astype(str))
        r = x[x.ticker.astype(str).isin(ps)][col]
        res["ledgers"].setdefault(nm, {"panel_date": last})[f"picks[{pk}] rank_pct min/median"] = (
            [round(float(r.min()), 3), round(float(r.median()), 3)] if len(r) else None)
    x2 = pd.read_csv(L / f"prediction_ledger_{nm}.csv", low_memory=False)
    res["ledgers"][nm]["IPHXU_TBCVU_rows"] = int(x2.ticker.astype(str).isin(["IPHXU", "TBCVU", "STRRP"]).sum())
(OUT / "pick_direction.json").write_text(json.dumps(res, indent=2))
print(json.dumps(res, indent=2))
