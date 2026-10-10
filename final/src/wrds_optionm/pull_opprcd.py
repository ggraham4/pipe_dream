"""
WO-52 Phase 1: pull OptionMetrics option quotes + underlying closes for the 133
WO-37 entry dates (2008-01-02 .. 2018-12-19). Spec:
final/models/2026-10-08-thinliq-optionmetrics-amendment.md section 1.

    caffeinate -i /opt/anaconda3/envs/pipe_dream/bin/python final/src/wrds_optionm/pull_opprcd.py

One query per entry date against optionm.opprcd{YYYY} (years in order), filtered
server-side (ss_flag 0, contract_size 100, exdate > date, not index/ETF), read
with chunksize. Resumable: a date whose parquet exists is skipped. Parquet only,
under the main checkout's final/data/wrds/optionm/ (gitignored, never committed).
No forward return is read; no date from 2019 on is touched.
"""
from __future__ import annotations

import os
import time
from pathlib import Path

import pandas as pd
import sqlalchemy as sa

ROOT = Path("/Users/ggraham/pipe_dream/final/data/wrds/optionm")
RAW = ROOT / "opprcd"
AV_MONTHLY = Path("/Users/ggraham/pipe_dream/final/data/alphavantage_full/options/monthly")
LO, HI = "2008-01-01", "2018-12-31"

OPT_COLS = ("o.secid, o.date, o.exdate, o.last_date, o.cp_flag, o.strike_price, o.best_bid, o.best_offer, "
            "o.volume, o.open_interest, o.impl_volatility, o.delta, o.optionid, o.cfadj, o.am_settlement, "
            "o.expiry_indicator")


def entry_dates():
    ds = sorted(p.stem.split("=")[1] for p in AV_MONTHLY.glob("date=*.parquet"))
    ds = [d for d in ds if LO <= d <= HI]
    assert len(ds) == 133, len(ds)
    return ds


def engine():
    return sa.create_engine("postgresql+psycopg2://gjg2134@wrds-pgdata.wharton.upenn.edu:9737/wrds",
                            connect_args={"sslmode": "require", "connect_timeout": 120})


def log(m):
    print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)


def main():
    RAW.mkdir(parents=True, exist_ok=True)
    dates = entry_dates()
    eng = engine()
    t0 = time.time()
    with eng.connect() as c:
        sec = ROOT / "securd.parquet"
        if not sec.exists():
            pd.read_sql(sa.text("select secid, cusip, ticker, issue_type, exchange_d from optionm.securd"), c).to_parquet(sec, index=False)
        px_parts = []
        for d in dates:
            y = d[:4]
            dst = RAW / f"date={d}.parquet"
            if not dst.exists():
                q = sa.text(f"select {OPT_COLS} from optionm.opprcd{y} o join optionm.securd s on s.secid = o.secid "
                            "where o.date = :d and o.ss_flag = '0' and o.contract_size = 100 and o.exdate > o.date "
                            "and coalesce(s.issue_type, '') not in ('A', '%')")
                parts = list(pd.read_sql(q, c, params={"d": d}, chunksize=200_000))
                df = pd.concat(parts, ignore_index=True)
                tmp = dst.with_suffix(".tmp")
                df.to_parquet(tmp, index=False)
                os.replace(tmp, dst)
                log(f"{d}: {len(df):,} rows, {df.secid.nunique()} secids ({time.time() - t0:.0f}s)")
            q = sa.text(f"select secid, date, close, cfadj from optionm.secprd{y} where date = :d")
            px_parts.append(pd.read_sql(q, c, params={"d": d}))
        px = pd.concat(px_parts, ignore_index=True)
        px.to_parquet(ROOT / "secprd.parquet", index=False)
        log(f"secprd: {len(px):,} rows on {px.date.nunique()} dates; done {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
