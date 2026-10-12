"""
WO-61 Part 2 pull: crsp.dsf closing bid/ask for the thin book pool's permnos, 2008-01-01..2019-03-31.
One WRDS connection (direct Postgres via ~/.pgpass, no `wrds` package), one query per year.
Writes parquet ONLY to /Users/ggraham/pipe_dream/final/data/wrds/crsp/dsf_bidask_YYYY.parquet (gitignored,
never committed). Label-free: reads no return. Refuses to overwrite an existing year file.

    caffeinate -i $PY pull_bidask.py
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import ta_common as A
import common as K       # wrds_crsp/common.py (WO-51): crosswalk attach
import wrdsdb as W       # one pooled engine, pool_size=1

log = A.log


def thin_permnos():
    cols = ["ticker", "date", "eligible_cap150", "eligible_cap2000"]
    p = pd.read_parquet(A.PANEL_V2, columns=cols, filters=[("date", ">=", "2008-01-01"), ("date", "<=", "2018-12-31")])
    p = p[p.eligible_cap150 & ~p.eligible_cap2000][["ticker", "date"]]
    p["ticker"] = p.ticker.astype(str)
    pm = K.attach(p, K.crosswalk())
    return sorted({int(x) for x in pm[np.isfinite(pm)]}), float(np.isfinite(pm).mean())


def main():
    A.guard_inputs([A.PANEL_V2, A.XWALK])
    perms, mapped = thin_permnos()
    log(f"thin name-dates mapped share {mapped:.4f}; permnos {len(perms)}")
    t = W.q("select permno, date, bid, ask from crsp.dsf where permno = :p and date between :a and :b",
            p=perms[0], a="2008-01-02", b="2008-01-10")
    log(f"smoke query rows {len(t)}")
    for y in range(2008, 2020):
        f = W.CRSP_DIR / f"dsf_bidask_{y}.parquet"
        if f.exists():
            log(f"{f.name} exists, skipped")
            continue
        a, b = f"{y}-01-01", (f"{y}-12-31" if y < 2019 else A.READ_CAP.strftime("%Y-%m-%d"))
        d = W.q("select permno, date, bid, ask from crsp.dsf where permno = any(:p) and date between :a and :b",
                p=perms, a=a, b=b)
        d["date"] = pd.to_datetime(d.date)
        assert d.date.max() <= A.READ_CAP
        d["permno"] = d.permno.astype("int64")
        d.to_parquet(f, index=False)
        log(f"{f.name}: {len(d):,} rows, {d.permno.nunique()} permnos, quote share {d.bid.notna().mean():.3f}")


if __name__ == "__main__":
    main()
