"""WO-59 probe 5 (local parquet, labels-free; COO addendum): managers whose first-vintage holdings multiset
{(cusip, shares)} at q is IDENTICAL to their first-vintage multiset at q-1, by quarter and position-count bucket.
Also identical cusip SETS (shares changed) for contrast. Writes out/wrds_13f/probe_cf.json."""
import hashlib
import json
from pathlib import Path

import pandas as pd

TR = Path("/Users/ggraham/pipe_dream/final/data/wrds/tr_13f")
OUT = Path(__file__).resolve().parents[2] / "out" / "wrds_13f"
QS = pd.date_range("2005-12-31", "2019-12-31", freq="QE")


def hashes(h, with_shares):
    k = h.sort_values(["mgrno", "cusip", "shares"])
    s = k.cusip.astype(str) + (":" + k.shares.map(lambda x: f"{x:.0f}") if with_shares else "")
    return s.groupby(k.mgrno).agg(lambda z: hashlib.md5("|".join(z).encode()).hexdigest())


rows, prev = [], None
for q in QS:
    h = pd.read_parquet(TR / f"holdings_{q.date()}.parquet")
    hs, hc, n = hashes(h, True), hashes(h, False), h.groupby("mgrno").size()
    if prev is not None:
        ps, pc = prev
        both = hs.index.intersection(ps.index)
        same = both[(hs[both] == ps[both]).to_numpy()]
        samec = both[(hc[both] == pc[both]).to_numpy()]
        b = pd.cut(n[same], [0, 1, 2, 5, 20, 100, 10**7]).value_counts().sort_index()
        rows.append({"q": str(q.date()), "mgr": int(n.size), "both": int(len(both)), "identical": int(len(same)),
                     "identical_share_of_both": len(same) / len(both), "same_cusip_set": int(len(samec)),
                     "identical_by_npos": {str(k): int(v) for k, v in b.items()},
                     "identical_rows": int(n[same].sum())})
    prev = (hs, hc)
d = pd.DataFrame(rows)
OUT.mkdir(parents=True, exist_ok=True)
(OUT / "probe_cf.json").write_text(json.dumps(rows, indent=1))
print(d[["q", "mgr", "both", "identical", "identical_share_of_both", "same_cusip_set", "identical_rows"]].to_string())
tot = pd.DataFrame([r["identical_by_npos"] for r in rows]).sum()
print(tot.to_string())
