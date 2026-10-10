"""WO-59 WRDS Postgres helper: ONE connection (pool_size=1), direct psycopg2, no `wrds` package.
Credentials come from ~/.pgpass automatically; never printed or stored."""
from pathlib import Path

import pandas as pd
import sqlalchemy as sa

MAIN = Path("/Users/ggraham/pipe_dream")
TR_DIR = MAIN / "final" / "data" / "wrds" / "tr_13f"
_ENG = None


def engine():
    global _ENG
    if _ENG is None:
        _ENG = sa.create_engine("postgresql+psycopg2://gjg2134@wrds-pgdata.wharton.upenn.edu:9737/wrds",
                                connect_args={"sslmode": "require", "connect_timeout": 120},
                                pool_size=1, max_overflow=0)
    return _ENG


def q(sql, **params):
    with engine().connect() as c:
        return pd.read_sql(sa.text(sql), c, params=params)
