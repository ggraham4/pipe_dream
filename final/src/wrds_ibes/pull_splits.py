"""WO-53: pull CRSP share-adjustment events (splits / stock dividends) for the split-basis
alignment of IBES unadjusted EPS between the two revision dates.
crsp.dsedist (legacy, to 2024-12-31), rows with facshr != 0, exdt 2006-01-01..2019-12-31.
Data -> /Users/ggraham/pipe_dream/final/data/wrds/ibes/crsp_dsedist_facshr.parquet (not committed).
"""
from pathlib import Path

import pandas as pd
import sqlalchemy as sa

OUT = Path("/Users/ggraham/pipe_dream/final/data/wrds/ibes")
eng = sa.create_engine("postgresql+psycopg2://gjg2134@wrds-pgdata.wharton.upenn.edu:9737/wrds",
                       connect_args={"sslmode": "require", "connect_timeout": 120})
with eng.connect() as c:
    cols = pd.read_sql(sa.text("select column_name from information_schema.columns "
                               "where table_schema='crsp' and table_name='dsedist'"), c)
    print(sorted(cols.column_name))
    df = pd.read_sql(sa.text("select permno, distcd, exdt, facshr, facpr from crsp.dsedist "
                             "where facshr is not null and facshr <> 0 and exdt between '2006-01-01' and '2019-12-31'"), c)
df["exdt"] = pd.to_datetime(df["exdt"])
df.to_parquet(OUT / "crsp_dsedist_facshr.parquet", index=False)
print(len(df), df["distcd"].astype(str).str[0].value_counts().to_dict())
