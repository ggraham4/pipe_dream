"""
WO-42 S3: top up the 8-K Item 2.02 pool for CIKs that the two earlier pulls
never requested. WO-5 (8k_item202.parquet) requested the v1-panel CIKs and
WO-29 (8k_item202_v2topup.parquet) the CIKs of v2 tickers with 2007-2019
rows, so names that first appear in 2020+ are missing.

Universe here = CIKs of composite_panel_v2 tickers with any eligible_cap150
row dated >= 2020-01-02, MINUS every CIK already in either pool file, MINUS
the CIKs those pulls recorded as having zero 2.02 filings.

The pull logic (EDGAR submissions API, user agent, cache, rate limit, row
filter) is final/src/ear/pull_8k_v2topup.py imported as a module; its main()
is never called and it is not edited. Output goes to NEW files only:
  final/out/stabilizer/8k_item202_2020topup.parquet   (gitignored)
  final/out/stabilizer/8k_item202_2020topup_pull_meta.json
This script reads no price and no label.
Usage: python pull_8k_2020topup.py
"""
import json
import sys
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "ear"))
import pull_8k_v2topup as P            # noqa: E402

OUT_DIR = HERE.parents[1] / "out" / "stabilizer"
OUT = OUT_DIR / "8k_item202_2020topup.parquet"
META = OUT_DIR / "8k_item202_2020topup_pull_meta.json"
EDGAR = P.MAIN_ROOT / "data" / "edgar"
POOLS = [EDGAR / "8k_item202.parquet", EDGAR / "8k_item202_v2topup.parquet"]
POOL_METAS = [EDGAR / "8k_item202_pull_meta.json", EDGAR / "8k_item202_v2topup_pull_meta.json"]
log = P.log


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    q = pd.read_parquet(P.PANEL_V2, columns=["ticker", "eligible_cap150"], filters=[("date", ">=", "2020-01-02")])
    tick = sorted(q.loc[q["eligible_cap150"].astype(bool), "ticker"].astype(str).unique())
    want = P.ciks_for(tick)
    tm = pd.read_csv(P.TICKERS_MASTER, usecols=["ticker", "secfilings"], dtype=str)
    tm["cik"] = pd.to_numeric(tm["secfilings"].str.extract(r"CIK=0*(\d+)")[0], errors="coerce")
    mapped = set(tm.dropna(subset=["cik"])["ticker"])
    no_cik = [t for t in tick if t not in mapped]
    have, zero = set(), set()
    for p in POOLS:
        have |= set(pd.read_parquet(p, columns=["cik"])["cik"].astype("int64").unique().tolist())
    for m in POOL_METAS:
        zero |= set(json.loads(m.read_text())["ciks_zero_202"])
    ciks = sorted(want - have - zero)
    log(f"cap150 2020+ tickers {len(tick):,} -> {len(want):,} CIKs; in pool {len(want & have):,}; "
        f"known zero-2.02 {len(want & zero):,}; to pull {len(ciks):,}; tickers with no CIK {no_cik}")
    rows, empty, missing = P.pull(ciks)
    assert rows, "top-up returned no rows at all"
    df = P.to_frame(rows)
    df.to_parquet(OUT, index=False)
    log(f"wrote {OUT}: {len(df):,} rows, {df['cik'].nunique():,} CIKs, "
        f"{df['filing_date'].min().date()}..{df['filing_date'].max().date()}")
    meta = {"n_tickers_cap150_2020plus": len(tick), "n_ciks_cap150_2020plus": len(want),
            "n_ciks_already_in_pool": len(want & have), "n_ciks_known_zero_202": len(want & zero),
            "n_ciks_requested": len(ciks), "n_ciks_with_202": int(df["cik"].nunique()),
            "ciks_zero_202": empty, "ciks_404": missing, "tickers_without_cik": no_cik,
            "n_rows": int(len(df)), "n_rows_8k": int((df["form"] == "8-K").sum()),
            "filing_date_min": str(df["filing_date"].min().date()), "filing_date_max": str(df["filing_date"].max().date()),
            "rows_filing_date_lt_2020": int((df["filing_date"] < "2020-01-01").sum())}
    META.write_text(json.dumps(meta, indent=2))
    log(f"meta: {len(empty)} CIKs with zero 2.02s, {len(missing)} 404s")


if __name__ == "__main__":
    main()
