"""WO-54: pull CRSP dsedist 3xxx distributions (metadata only), exdt 2007-01-01..2020-03-31.

2020Q1 rows are kept only to COUNT spin records that late-2019 label windows would cross (no 2020 return is read).
Writes final/data/wrds/crsp/dsedist_3xxx.parquet (main checkout, gitignored, never committed).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "wrds_crsp"))
import wrdsdb as W  # noqa: E402

OUT = W.CRSP_DIR / "dsedist_3xxx.parquet"
d = W.q("select permno, distcd, divamt, facpr, facshr, dclrdt, exdt, paydt, acperm, accomp from crsp.dsedist "
        "where distcd between 3000 and 3999 and exdt between '2007-01-01' and '2020-03-31'")
d.to_parquet(OUT, index=False)
print(f"{len(d):,} rows, {d.permno.nunique():,} permnos -> {OUT}")
