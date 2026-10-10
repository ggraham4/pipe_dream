"""WO-60 oracle: engine.pick_cells (vectorized bottom decile within vol quintile) == composite.pick_decile_volq
on the negated score, on every 25th date of each tier. No outcome used."""
import json
import sys
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE)); sys.path.insert(0, str(HERE.parent / "reset2026"))
import composite as C  # noqa: E402
import engine as E  # noqa: E402
import sb_common as K  # noqa: E402

out = {}
for tier in ("cap2000", "cap150"):
    E.load(tier)
    R = E.G["R"]; sc = R["score"].to_numpy()
    m = E.pick_cells(sc, E.G["volq"], 0.10)
    bad, n = 0, 0
    for dt, s, e in E.G["sl"][::25]:
        g = R.iloc[s:e]
        pk = {t for t, _ in C.pick_decile_volq(g, pd.DataFrame({"ticker": g["ticker"].values, "composite": -g["score"].values}))}
        bad += pk != set(g["ticker"].values[m[s:e]]); n += 1
    out[tier] = {"dates_checked": n, "mismatch": bad, "shortable_share_of_picks": float((m & E.G["shortable"]).sum() / m.sum())}
    K.log(f"{tier} {out[tier]}")
(K.OUT / "check_picker.json").write_text(json.dumps(out, indent=1))
assert all(v["mismatch"] == 0 for v in out.values())
