"""WO-51 Phase 2 pull: CRSP legacy daily stock file for the crosswalk's permnos, by year.

Writes final/data/wrds/crsp/dsf_<year>.parquet (main checkout, gitignored):
  permno, date, ret, retx, prc, openprc, shrout, vol, cfacpr
Years given on the command line (default 2007..2019). Server-side filter on permno + date.
Skips years already written unless --force.
"""
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from wrdsdb import CRSP_DIR, LINK_DIR, engine  # noqa: E402
import sqlalchemy as sa  # noqa: E402

args = [a for a in sys.argv[1:] if not a.startswith("--")]
force = "--force" in sys.argv
years = [int(a) for a in args] or list(range(2007, 2020))
permnos = sorted(pd.read_parquet(LINK_DIR / "permno_sharadar.parquet").permno.unique().tolist())
print("permnos", len(permnos))
sql = sa.text("""select permno, date, ret, retx, prc, openprc, shrout, vol, cfacpr
                 from crsp.dsf where date between :a and :b and permno = any(:p)""")
for y in years:
    out = CRSP_DIR / f"dsf_{y}.parquet"
    if out.exists() and not force:
        print(y, "exists"); continue
    parts = []
    with engine().connect() as c:
        for ch in pd.read_sql(sql, c, params={"a": f"{y}-01-01", "b": (f"{y}-03-31" if y == 2020 else f"{y}-12-31"), "p": permnos}, chunksize=500_000):
            parts.append(ch)
    df = pd.concat(parts, ignore_index=True)
    for col in ["ret", "retx", "prc", "openprc", "shrout", "vol", "cfacpr"]:
        df[col] = pd.to_numeric(df[col], errors="coerce").astype("float64")
    df["permno"] = df.permno.astype("int64")
    df["date"] = pd.to_datetime(df.date)
    df.to_parquet(out, index=False)
    print(y, df.shape, flush=True)
