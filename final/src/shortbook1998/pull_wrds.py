"""WO-63 Phase 1: raw WRDS pulls for the 1998-2006 short-book confirmation panel.

Raw inputs only (no features, no outcomes aggregated). Resumable: each output file is
skipped when it already exists. Large files go to the main checkout (gitignored):
    /Users/ggraham/pipe_dream/final/data/wrds/crsp/dsf_<YYYY>.parquet     1986..2006 (2007+ already on disk)
    /Users/ggraham/pipe_dream/final/data/wrds/comp/funda_1985_2010.parquet
    /Users/ggraham/pipe_dream/final/data/wrds/comp/fundq_1985_2010.parquet
    /Users/ggraham/pipe_dream/final/data/wrds/comp/co_filedate_1985_2010.parquet
    /Users/ggraham/pipe_dream/final/data/wrds/comp/sec_shortint_legacy_1996_2007.parquet
    /Users/ggraham/pipe_dream/final/data/wrds/crsp/msenames.parquet (via stocknames already on disk)

No 2020+ data: every query is bounded at 2010-12-31 or earlier.
No code here can place, modify or cancel an order.

    caffeinate -i python pull_wrds.py [dsf|comp|si|all]
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "wrds_crsp"))
from wrdsdb import q  # noqa: E402

WRDS = Path("/Users/ggraham/pipe_dream/final/data/wrds")
CRSP = WRDS / "crsp"
COMP = WRDS / "comp"
DSF_COLS = "permno, date, ret, retx, prc, openprc, shrout, vol, cfacpr"   # same columns as dsf_2007+.parquet
COMP_FILT = "indfmt='INDL' and datafmt='STD' and popsrc='D' and consol='C'"


def log(m):
    print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)


def pull_dsf():
    for y in range(1986, 2007):
        p = CRSP / f"dsf_{y}.parquet"
        if p.exists():
            continue
        t0 = time.time()
        d = q(f"select {DSF_COLS} from crsp.dsf where date between '{y}-01-01' and '{y}-12-31'")
        tmp = p.with_suffix(".tmp")
        d.to_parquet(tmp, index=False)
        tmp.rename(p)
        log(f"dsf {y}: {len(d):,} rows ({time.time()-t0:.0f}s)")


def pull_comp():
    jobs = {
        "funda_1985_2010.parquet":
            f"select gvkey, datadate, fyear, fyr, at, revt, cogs, gp, xsga, dp, ni, ib, oancf, csho, ajex, "
            f"curcd, sich from comp.funda where {COMP_FILT} and datadate between '1985-01-01' and '2010-12-31'",
        "fundq_1985_2010.parquet":
            f"select gvkey, datadate, fyearq, fqtr, rdq, atq, cshoq, ajexq, curcdq "
            f"from comp.fundq where {COMP_FILT} and datadate between '1985-01-01' and '2010-12-31'",
        "co_filedate_1985_2010.parquet":
            "select gvkey, datadate, srctype, filedate from comp.co_filedate "
            "where datadate between '1985-01-01' and '2010-12-31' and srctype in ('10K','10Q','10K405','10KSB','10QSB')",
    }
    for name, sql in jobs.items():
        p = COMP / name
        if p.exists():
            continue
        t0 = time.time()
        d = q(sql)
        d.to_parquet(p, index=False)
        log(f"{name}: {len(d):,} rows ({time.time()-t0:.0f}s)")


def pull_si():
    p = COMP / "sec_shortint_legacy_1996_2007.parquet"
    if not p.exists():
        d = q("select gvkey, iid, datadate, shortint, shortintadj, splitadjdate from comp.sec_shortint_legacy "
              "where datadate between '1996-01-01' and '2007-12-31'")
        d.to_parquet(p, index=False)
        log(f"si legacy: {len(d):,} rows")


if __name__ == "__main__":
    what = sys.argv[1] if len(sys.argv) > 1 else "all"
    COMP.mkdir(parents=True, exist_ok=True)
    if what in ("si", "all"):
        pull_si()
    if what in ("comp", "all"):
        pull_comp()
    if what in ("dsf", "all"):
        pull_dsf()
    log("done")
