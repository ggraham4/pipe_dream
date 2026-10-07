"""WO-47 B-v2 attribution. On every pre-2020 row whose *_v1 eligibility flag changed between the
Sep-8 and current v2 panels, test whether the current *_v1 flag now equals the v2 flag (the v1 flag
columns rebuilt with the v2 rule), and whether the row is a reverse-split name (close/closeunadj
differs). Writes final/out/tickerreuse/b_v2_attrib.json."""
import json

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from common import OUT, SCRATCH, FROZEN, MAIN, SEP_DIR
from b_diff_v2 import SEPV2, CURV2, load

D = pd.read_parquet(SCRATCH / "b_v2_rowdiff.parquet")
flagcols = ["eligible_cap2000", "eligible_cap500", "eligible_cap150",
            "eligible_cap2000_v1", "eligible_cap500_v1", "eligible_cap150_v1"]
tick = sorted(D.ticker.unique())


def sub(p):
    df = pq.read_table(p, columns=["ticker", "date", "close"] + flagcols,
                       filters=[("ticker", "in", tick)]).to_pandas()
    df["date"] = pd.to_datetime(df["date"])
    return df


a, b = sub(SEPV2), sub(CURV2)
keys = D[["ticker", "date"]].assign(date=lambda x: pd.to_datetime(x.date))
A = keys.merge(a, on=["ticker", "date"]).set_index(["ticker", "date"])
B = keys.merge(b, on=["ticker", "date"]).set_index(["ticker", "date"]).loc[A.index]
Dd = D.assign(date=pd.to_datetime(D.date)).set_index(["ticker", "date"]).loc[A.index]
res = {"rows": int(len(A))}
for t in ("500", "150"):
    ch = Dd[f"d_eligible_cap{t}_v1"].to_numpy()
    now_eq_v2 = (B[f"eligible_cap{t}_v1"].to_numpy() == B[f"eligible_cap{t}"].to_numpy())
    was_eq_v2 = (A[f"eligible_cap{t}_v1"].to_numpy() == A[f"eligible_cap{t}"].to_numpy())
    v2_same = (A[f"eligible_cap{t}"].to_numpy() == B[f"eligible_cap{t}"].to_numpy())
    res[f"cap{t}_v1_changed_rows"] = int(ch.sum())
    res[f"cap{t}_v1_changed_and_now_equals_v2_flag"] = int((ch & now_eq_v2).sum())
    res[f"cap{t}_v1_changed_and_was_not_equal_v2_flag"] = int((ch & ~was_eq_v2).sum())
    res[f"cap{t}_v2_flag_unchanged_on_these_rows"] = int((ch & v2_same).sum())
    res[f"cap{t}_v1_direction_true_to_false"] = int((ch & A[f"eligible_cap{t}_v1"].to_numpy() & ~B[f"eligible_cap{t}_v1"].to_numpy()).sum())
# reverse-split signature: close / closeunadj on the panel rows, from raw SEP
fr = [pd.read_parquet(f, columns=["ticker", "date", "close", "closeunadj"], filters=[("ticker", "in", tick)])
      for f in sorted(SEP_DIR.glob("*.parquet")) if f.stem < "2020"]
s = pd.concat(fr)
s["date"] = pd.to_datetime(s["date"])
s = s.set_index(["ticker", "date"]).reindex(A.index)
r = (s.close / s.closeunadj).to_numpy()
res["rows_close_ne_closeunadj"] = int((np.abs(r - 1) > 1e-6).sum())
res["rows_adj_close_gt_unadj (reverse split later)"] = int((r > 1 + 1e-6).sum())
res["rows_adj_close_lt_unadj (forward split later)"] = int((r < 1 - 1e-6).sum())
res["tickers"] = len(tick)
(OUT / "b_v2_attrib.json").write_text(json.dumps(res, indent=2))
print(json.dumps(res, indent=2))
