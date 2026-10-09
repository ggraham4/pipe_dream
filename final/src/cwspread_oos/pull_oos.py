"""
WO-55 Phase 1: pull OptionMetrics option quotes + underlying closes for the 80 WO-37 grid dates
2019-01-16 .. 2025-08-20 (the gap after WO-52's 2008-2018 pull). Same server-side filter as
final/src/wrds_optionm/pull_opprcd.py (WO-52 amendment section 1): ss_flag 0, contract_size 100,
exdate > date, not index/ETF; no DTE or delta band. Also pulls optionm.secnmd (name/CUSIP history,
for the link repair L2 in the pre-reg). Quotes and presence only: no forward return is read.

    caffeinate -i /opt/anaconda3/envs/pipe_dream/bin/python final/src/cwspread_oos/pull_oos.py

One query per entry date against optionm.opprcd{YYYY}, chunked reads, resumable (an existing date
parquet is skipped). Parquet only, under final/data/wrds/optionm/oos2019/ (main checkout, gitignored).
"""
from __future__ import annotations

import os
import time

import pandas as pd
import sqlalchemy as sa

import oos_paths as P
from pull_opprcd import OPT_COLS, engine  # WO-52, unchanged


def log(m):
    print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)


def main():
    P.RAW.mkdir(parents=True, exist_ok=True)
    dates = P.entry_dates()
    eng = engine()
    t0 = time.time()
    with eng.connect() as c:
        if not P.SECNMD.exists():
            pd.read_sql(sa.text("select secid, effect_date, cusip, ticker, issuer, issue from optionm.secnmd"), c).to_parquet(P.SECNMD, index=False)
            log("secnmd pulled")
        px_parts = []
        for d in dates:
            y = d[:4]
            dst = P.RAW / f"date={d}.parquet"
            if not dst.exists():
                q = sa.text(f"select {OPT_COLS} from optionm.opprcd{y} o join optionm.securd s on s.secid = o.secid "
                            "where o.date = :d and o.ss_flag = '0' and o.contract_size = 100 and o.exdate > o.date "
                            "and coalesce(s.issue_type, '') not in ('A', '%')")
                df = pd.concat(list(pd.read_sql(q, c, params={"d": d}, chunksize=200_000)), ignore_index=True)
                tmp = dst.with_suffix(".tmp")
                df.to_parquet(tmp, index=False)
                os.replace(tmp, dst)
                log(f"{d}: {len(df):,} rows, {df.secid.nunique()} secids ({time.time() - t0:.0f}s)")
            q = sa.text(f"select secid, date, close, cfadj from optionm.secprd{y} where date = :d")
            px_parts.append(pd.read_sql(q, c, params={"d": d}))
        px = pd.concat(px_parts, ignore_index=True)
        px.to_parquet(P.SECPRD, index=False)
        log(f"secprd: {len(px):,} rows on {px.date.nunique()} dates; done {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
