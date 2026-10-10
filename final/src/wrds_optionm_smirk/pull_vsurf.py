"""
WO-56: pull OptionMetrics standardized volatility surface (optionm.vsurfdYYYY) for the IV smirk
factor. Server-side filter: days = 30 and ((cp_flag 'P', delta -20) or (cp_flag 'C', delta 50)),
secid in the set linked (any score) to v2-grid names (eligible_cap150 or eligible_cap2000,
2007-2019). One engine, one year per query, sequential, chunked reads (WO-55 shares WRDS).
2006 is pulled for December only: a lag input for the 2007-01-02 panel date, not an era extension.
No label / return is read here.

    caffeinate -i /opt/anaconda3/envs/pipe_dream/bin/python final/src/wrds_optionm_smirk/pull_vsurf.py
"""
import json
import os
import time
from pathlib import Path

import numpy as np
import pandas as pd
import sqlalchemy as sa

MAIN = Path("/Users/ggraham/pipe_dream/final")
DST = MAIN / "data" / "wrds" / "optionm" / "vsurf"
XWALK = MAIN / "data" / "wrds" / "link" / "permno_sharadar.parquet"
OPCRSP = MAIN / "data" / "wrds" / "link" / "opcrsphist.parquet"
PANEL = MAIN / "out" / "reset2026" / "composite_panel_v2.parquet"
LO, HI = pd.Timestamp("2006-12-01"), pd.Timestamp("2019-12-31")


def log(m):
    print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)


def linked_secids():
    p = pd.read_parquet(PANEL, columns=["ticker", "date", "eligible_cap150", "eligible_cap2000"],
                        filters=[("date", ">=", "2007-01-01"), ("date", "<=", "2019-12-31")])
    p = p[p.eligible_cap150.astype(bool) | p.eligible_cap2000.astype(bool)]
    tk = set(p.ticker.astype(str).unique())
    X = pd.read_parquet(XWALK, columns=["permno", "ticker", "valid_from", "valid_to"])
    X["ticker"] = X.ticker.astype(str)
    X = X[X.ticker.isin(tk) & (pd.to_datetime(X.valid_to) >= LO) & (pd.to_datetime(X.valid_from) <= HI)]
    O = pd.read_parquet(OPCRSP)
    O = O[O.permno.notna() & O.sdate.notna()].copy()
    O["sdate"] = pd.to_datetime(O.sdate); O["edate"] = pd.to_datetime(O.edate)
    O = O[O.permno.astype("int64").isin(set(X.permno.astype("int64"))) & (O.sdate <= HI) & (O.edate.isna() | (O.edate >= LO))]
    ids = sorted(set(O.secid.astype("int64")))
    log(f"grid tickers {len(tk):,}; crosswalk permnos {X.permno.nunique():,}; secids {len(ids):,}")
    return ids, {"grid_tickers": len(tk), "permnos": int(X.permno.nunique()), "secids": len(ids),
                 "opcrsphist_score_counts": O.score.value_counts().sort_index().to_dict()}


def main():
    DST.mkdir(parents=True, exist_ok=True)
    ids, meta = linked_secids()
    eng = sa.create_engine("postgresql+psycopg2://gjg2134@wrds-pgdata.wharton.upenn.edu:9737/wrds",
                           connect_args={"sslmode": "require", "connect_timeout": 120})
    meta["years"] = {}
    with eng.connect() as c:
        for y in range(2006, 2020):
            dst = DST / f"vsurfd_{y}.parquet"
            if dst.exists():
                log(f"{y}: exists, skip"); meta["years"][y] = {"rows": int(pd.read_parquet(dst, columns=["secid"]).shape[0])}
                continue
            lo = "2006-12-01" if y == 2006 else f"{y}-01-01"
            q = sa.text(f"""select secid, date, cp_flag, delta, impl_volatility
                            from optionm.vsurfd{y}
                            where days = 30 and date between :lo and :hi
                              and ((cp_flag = 'P' and delta = -20) or (cp_flag = 'C' and delta = 50))
                              and secid = any(:ids)""")
            t0 = time.time()
            parts = list(pd.read_sql(q, c, params={"lo": lo, "hi": f"{y}-12-31", "ids": [float(i) for i in ids]},
                                     chunksize=500_000))
            d = pd.concat(parts, ignore_index=True)
            d["secid"] = d.secid.astype("int64"); d["date"] = pd.to_datetime(d.date)
            d["delta"] = d.delta.astype("int16"); d["cp_flag"] = d.cp_flag.astype(str)
            tmp = dst.with_suffix(".tmp"); d.to_parquet(tmp, index=False); os.replace(tmp, dst)
            meta["years"][y] = {"rows": len(d), "secids": int(d.secid.nunique()), "dates": int(d.date.nunique()),
                                "iv_null_share": float(d.impl_volatility.isna().mean()), "s": round(time.time() - t0, 1)}
            log(f"{y}: {meta['years'][y]}")
    meta["filter"] = "days=30 and ((P,-20) or (C,50)) and secid in linked set"
    meta["pulled"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    (DST / "pull_meta_wo56.json").write_text(json.dumps(meta, indent=1, default=str))


if __name__ == "__main__":
    main()
