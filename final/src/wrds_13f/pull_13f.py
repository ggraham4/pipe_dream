"""WO-59 pull: Thomson-Reuters 13F (tr_13f) 2005Q4..2019Q4, server-side filtered, one connection.

Writes parquet only to /Users/ggraham/pipe_dream/final/data/wrds/tr_13f/ (gitignored, never committed):
  managers.parquet              s34type1 rows with fdate in 2005-12-31..2019-12-31 (fdate, mgrno, rdate, typecode)
  holdings_YYYY-MM-DD.parquet   FIRST-VINTAGE holdings for report quarter q: s34type3 rows with fdate = q joined to
                                s34type1 rows with fdate = rdate = q, shares > 0 (mgrno, cusip, shares)
No price/return/outcome field is pulled.

    caffeinate -i /opt/anaconda3/envs/pipe_dream/bin/python final/src/wrds_13f/pull_13f.py
"""
import sys
import time
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from wrdsdb import TR_DIR, q  # noqa: E402

QS = pd.date_range("2005-12-31", "2019-12-31", freq="QE")


def main():
    TR_DIR.mkdir(parents=True, exist_ok=True)
    m = q("""select fdate, mgrno, rdate, typecode from tr_13f.s34type1
             where fdate between '2005-12-31' and '2019-12-31'""")
    m["mgrno"] = m.mgrno.astype("int64")
    m.to_parquet(TR_DIR / "managers.parquet", index=False)
    print("managers", m.shape, flush=True)
    for d in QS:
        p = TR_DIR / f"holdings_{d.date()}.parquet"
        if p.exists():
            continue
        t0 = time.time()
        h = q("""select t3.mgrno, t3.cusip, t3.shares from tr_13f.s34type3 t3
                 join tr_13f.s34type1 t1 on t1.fdate = t3.fdate and t1.mgrno = t3.mgrno
                 where t3.fdate = :d and t1.rdate = :d and t3.shares > 0""", d=d.date())
        h["mgrno"] = h.mgrno.astype("int64")
        h.to_parquet(p, index=False)
        print(d.date(), len(h), h.mgrno.nunique(), f"{time.time()-t0:.0f}s", flush=True)


if __name__ == "__main__":
    main()
