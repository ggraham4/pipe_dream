"""WO-60 data substitution: in-era short interest (the panel's FINRA SI starts 2020-04).

Source: Compustat comp.sec_shortint (gvkey, iid, shortint, datadate = settlement date), WRDS.
  days_to_cover = shortint / mean CRSP dsf `vol` over the 20 trading days ending at datadate
  available     = datadate + 8 business days (FINRA Rule 4560 publication lag; same rule as
                  final/src/sweep/short_interest.py), never datadate itself.
Link: gvkey/iid -> permno via crsp.ccmxpf_lnkhist (LC/LU, P/C, iid == liid, datadate in link range),
      permno -> Sharadar ticker via final/data/wrds/link/permno_sharadar.parquet (valid range).
Output (gitignored): final/data/wrds/comp/si_dtc_2007_2019.parquet
  ticker, permno, datadate, available, shortint, adv20, dtc
No outcome data is read.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "wrds_crsp"))
import sb_common as K  # noqa: E402
from wrdsdb import q  # noqa: E402

COMP = K.WRDS / "comp"
OUTP = COMP / "si_dtc_2007_2019.parquet"


def main():
    COMP.mkdir(parents=True, exist_ok=True)
    raw_p = COMP / "sec_shortint_2006_2019.parquet"
    if not raw_p.exists():
        K.log("pull comp.sec_shortint 2006-10..2019-12")
        si = q("select gvkey, iid, datadate, shortint, shortintadj from comp.sec_shortint "
               "where datadate between '2006-10-01' and '2019-12-31'")
        si.to_parquet(raw_p)
    si = pd.read_parquet(raw_p)
    lk_p = COMP / "ccmxpf_lnkhist.parquet"
    if not lk_p.exists():
        K.log("pull crsp.ccmxpf_lnkhist")
        lk = q("select gvkey, liid, lpermno, linktype, linkprim, linkdt, linkenddt from crsp.ccmxpf_lnkhist "
               "where linktype in ('LC','LU') and linkprim in ('P','C') and lpermno is not null")
        lk.to_parquet(lk_p)
    lk = pd.read_parquet(lk_p)
    v06_p = COMP / "dsf_vol_2006q4.parquet"
    if not v06_p.exists():
        K.log("pull crsp.dsf vol 2006-09..2006-12")
        v = q("select permno, date, vol from crsp.dsf where date between '2006-09-01' and '2006-12-31'")
        v.to_parquet(v06_p)
    K.log(f"si rows {len(si):,}, links {len(lk):,}")

    si["datadate"] = pd.to_datetime(si["datadate"]).astype("datetime64[ns]")
    lk["linkdt"] = pd.to_datetime(lk["linkdt"]).astype("datetime64[ns]")
    lk["linkenddt"] = pd.to_datetime(lk["linkenddt"], errors="coerce").astype("datetime64[ns]").fillna(pd.Timestamp("2099-12-31"))
    m = si.merge(lk, left_on=["gvkey", "iid"], right_on=["gvkey", "liid"], how="inner")
    m = m[(m["datadate"] >= m["linkdt"]) & (m["datadate"] <= m["linkenddt"])]
    m = m.rename(columns={"lpermno": "permno"})
    m["permno"] = m["permno"].astype(int)
    m = m.sort_values(["permno", "datadate", "linkprim"]).drop_duplicates(["permno", "datadate"])

    # ADV20 from CRSP dsf vol (shares), 20 trading days ending at datadate
    vols = [pd.read_parquet(v06_p)]
    for y in range(2007, 2020):
        vols.append(pd.read_parquet(K.WRDS / "crsp" / f"dsf_{y}.parquet", columns=["permno", "date", "vol"]))
    v = pd.concat(vols, ignore_index=True)
    v["date"] = pd.to_datetime(v["date"]).astype("datetime64[ns]"); v["permno"] = v["permno"].astype(int)
    v = v[v["date"] <= K.PRICE_HI].sort_values(["permno", "date"])
    v["adv20"] = v.groupby("permno")["vol"].transform(lambda s: s.rolling(20, min_periods=10).mean())
    m = m.sort_values("datadate")
    v = v.sort_values("date")
    m = pd.merge_asof(m, v[["permno", "date", "adv20"]], left_on="datadate", right_on="date", by="permno",
                      direction="backward", tolerance=pd.Timedelta(days=7))
    m["dtc"] = m["shortint"] / m["adv20"].where(m["adv20"] > 0)
    m["available"] = m["datadate"] + pd.offsets.BDay(8)

    ln = pd.read_parquet(K.WRDS / "link" / "permno_sharadar.parquet")
    ln["valid_from"] = pd.to_datetime(ln["valid_from"]); ln["valid_to"] = pd.to_datetime(ln["valid_to"]).fillna(pd.Timestamp("2099-12-31"))
    x = m.merge(ln[["permno", "ticker", "valid_from", "valid_to"]], on="permno", how="inner")
    x = x[(x["datadate"] >= x["valid_from"] - pd.Timedelta(days=31)) & (x["datadate"] <= x["valid_to"] + pd.Timedelta(days=31))]
    x = x[["ticker", "permno", "datadate", "available", "shortint", "adv20", "dtc"]].dropna(subset=["dtc"])
    x = x.sort_values(["ticker", "datadate"]).drop_duplicates(["ticker", "datadate"])
    x.to_parquet(OUTP)
    K.log(f"wrote {OUTP}: {len(x):,} rows, {x['ticker'].nunique():,} tickers, dtc median {x['dtc'].median():.2f}")


def attach(U: pd.DataFrame, stale_days=45) -> pd.Series:
    """As-of (available <= date, at most stale_days old) days_to_cover for U's (ticker, date)."""
    x = pd.read_parquet(OUTP)
    x = x.sort_values("available")
    left = U[["ticker", "date"]].reset_index().sort_values("date")
    r = pd.merge_asof(left, x[["ticker", "available", "dtc"]].rename(columns={"available": "date"}),
                      on="date", by="ticker", direction="backward", tolerance=pd.Timedelta(days=stale_days))
    return r.set_index("index")["dtc"].reindex(U.index)


if __name__ == "__main__":
    main()
