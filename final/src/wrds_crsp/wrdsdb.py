"""Shared WRDS Postgres connection for WO-51 (direct psycopg2; no `wrds` package).

Credentials come from ~/.pgpass automatically. Never print or store them.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import sqlalchemy as sa

MAIN = Path("/Users/ggraham/pipe_dream")
WRDS_DATA = MAIN / "final" / "data" / "wrds"
CRSP_DIR = WRDS_DATA / "crsp"
LINK_DIR = WRDS_DATA / "link"

_ENG = None


def engine():
    global _ENG
    if _ENG is None:
        _ENG = sa.create_engine(
            "postgresql+psycopg2://gjg2134@wrds-pgdata.wharton.upenn.edu:9737/wrds",
            connect_args={"sslmode": "require", "connect_timeout": 120},
            pool_size=1, max_overflow=0,
        )
    return _ENG


def q(sql: str, **params) -> pd.DataFrame:
    with engine().connect() as c:
        return pd.read_sql(sa.text(sql), c, params=params)
