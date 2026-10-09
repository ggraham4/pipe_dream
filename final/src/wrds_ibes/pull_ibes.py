"""WO-53: pull IBES unadjusted summary EPS (FY1 + FY2, annual, US, USD) and the
IBES-CRSP link table. Data -> /Users/ggraham/pipe_dream/final/data/wrds/ibes/ (parquet only,
gitignored, never committed; WRDS licence).

statpers 2006-06-01..2019-12-31. Months before 2007 are lag inputs only (the t-3m end of
the revision for early-2007 dates); no outcome is ever computed before 2007-01-02.
FY2 is pulled only so the FY1-rollover rule can match the SAME fiscal period at t-3m.

Run: caffeinate -i /opt/anaconda3/envs/pipe_dream/bin/python pull_ibes.py
"""
import json
import time
from pathlib import Path

import pandas as pd
import sqlalchemy as sa

OUT = Path("/Users/ggraham/pipe_dream/final/data/wrds/ibes")
OUT.mkdir(parents=True, exist_ok=True)
eng = sa.create_engine("postgresql+psycopg2://gjg2134@wrds-pgdata.wharton.upenn.edu:9737/wrds",
                       connect_args={"sslmode": "require", "connect_timeout": 120})

SQL = """
select ticker, cusip, oftic, statpers, fpi, fiscalp, fpedats, numest, meanest, medest, curcode, usfirm
from ibes.statsumu_epsus
where measure = 'EPS' and fpi in ('1','2') and fiscalp = 'ANN'
  and statpers between :a and :b
"""

meta = {"years": {}}
with eng.connect() as c:
    for y in range(2006, 2020):
        p = OUT / f"statsumu_epsus_fy12_{y}.parquet"
        if p.exists():
            meta["years"][y] = "exists"
            continue
        t0 = time.time()
        a = f"{y}-06-01" if y == 2006 else f"{y}-01-01"
        df = pd.read_sql(sa.text(SQL), c, params={"a": a, "b": f"{y}-12-31"})
        df["statpers"] = pd.to_datetime(df["statpers"])
        df["fpedats"] = pd.to_datetime(df["fpedats"])
        df.to_parquet(p, index=False)
        meta["years"][y] = {"rows": int(len(df)), "usfirm1_usd": int(((df.usfirm == 1) & (df.curcode == "USD")).sum()),
                            "secs": round(time.time() - t0, 1)}
        print(y, meta["years"][y], flush=True)
    lk = pd.read_sql(sa.text("select ticker, permno, ncusip, sdate, edate, score from wrdsapps.ibcrsphist"), c)
    lk.to_parquet(OUT / "ibcrsphist.parquet", index=False)
    meta["ibcrsphist_rows"] = int(len(lk))
    meta["ibcrsphist_score_counts"] = {str(k): int(v) for k, v in lk["score"].value_counts().sort_index().items()}
    print("link rows", len(lk), meta["ibcrsphist_score_counts"], flush=True)
meta["pulled"] = time.strftime("%Y-%m-%d %H:%M")
(OUT / "pull_meta_wo53.json").write_text(json.dumps(meta, indent=1, default=str))
