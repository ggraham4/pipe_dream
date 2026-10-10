"""WO-59 probe 6 (labels-free): per quarter, permnos with >= 10 holders at q-1 and 0 holders at q although
CRSP still lists them at q (date-valid name record) -- the 'should be there' check for TR coverage gaps.
Also the cross-sectional median |dbreadth| per quarter. Reads the build's by-permno-quarter cache."""
import json
from pathlib import Path

import pandas as pd

OUT = Path(__file__).resolve().parents[2] / "out" / "wrds_13f"
C = pd.read_parquet(OUT / "cache" / "dbreadth_by_permno_quarter.parquet")
dl = pd.read_parquet("/Users/ggraham/pipe_dream/final/data/wrds/crsp/dsedelist.parquet", columns=["permno", "dlstdt"])
dl["dlstdt"] = pd.to_datetime(dl.dlstdt)
rows = []
for q, g in C.groupby("q"):
    # N_prev_B >= 10 and N_q == 0 (both counted on managers filing both quarters), name valid at both rdates
    v = g[(g.N_prev_B >= 10) & (g.N_q == 0)]
    d = dl.set_index("permno").dlstdt.reindex(v.permno)
    alive = int((d.isna() | (d > q + pd.Timedelta(days=45))).sum())
    rows.append({"q": str(pd.Timestamp(q).date()), "vanish_ge10": len(v), "vanish_still_listed": alive,
                 "n": len(g), "med_abs": float(g.dbreadth.abs().median())})
d = pd.DataFrame(rows)
(OUT / "probe_vanish.json").write_text(json.dumps(rows, indent=1))
print(d.to_string())
