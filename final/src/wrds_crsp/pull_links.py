"""WO-51 Phase 1 pulls: CRSP name history + delistings, and WRDS link tables.

Writes parquet only, to the main checkout (gitignored):
  final/data/wrds/crsp/stocknames.parquet      crsp.stocknames (legacy SIZ name history)
  final/data/wrds/crsp/dsedelist.parquet       crsp.dsedelist (legacy delisting info, dlret)
  final/data/wrds/crsp/stkdelists.parquet      crsp.stkdelists (CIZ v2 delisting info)
  final/data/wrds/link/opcrsphist.parquet      wrdsapps.opcrsphist (OptionMetrics secid <-> permno)
  final/data/wrds/link/ibcrsphist.parquet      wrdsapps.ibcrsphist (IBES ticker <-> permno)
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from wrdsdb import CRSP_DIR, LINK_DIR, q  # noqa: E402

CRSP_DIR.mkdir(parents=True, exist_ok=True)
LINK_DIR.mkdir(parents=True, exist_ok=True)

jobs = [
    (CRSP_DIR / "stocknames.parquet",
     "select permno, permco, namedt, nameenddt, shrcd, exchcd, siccd, ncusip, cusip, ticker, comnam, shrcls, st_date, end_date from crsp.stocknames"),
    (CRSP_DIR / "dsedelist.parquet",
     "select permno, permco, dlstdt, dlstcd, nwperm, nwcomp, nextdt, dlamt, dlretx, dlprc, dlpdt, dlret, cusip from crsp.dsedelist"),
    (CRSP_DIR / "stkdelists.parquet",
     "select permno, delistingdt, deldtprc, delactiontype, delstatustype, delreasontype, delpaymenttype, delpermno, delret, delretmisstype, delnextdt, delnextprc, deldlydt from crsp.stkdelists"),
    (LINK_DIR / "opcrsphist.parquet", "select secid, sdate, edate, permno, score from wrdsapps.opcrsphist"),
    (LINK_DIR / "ibcrsphist.parquet", "select ticker, permno, ncusip, sdate, edate, score from wrdsapps.ibcrsphist"),
]
for path, sql in jobs:
    df = q(sql)
    for c in df.columns:
        if df[c].dtype == object and c not in ("ncusip", "cusip", "ticker", "comnam", "shrcls", "delactiontype",
                                                "delstatustype", "delreasontype", "delpaymenttype", "delretmisstype"):
            try:
                df[c] = df[c].astype("float64")
            except (TypeError, ValueError):
                pass
    df.to_parquet(path, index=False)
    print(path.name, df.shape)
