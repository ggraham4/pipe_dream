"""Small shared I/O helper for WO-25 scripts."""
from __future__ import annotations

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq


def read_on_dates(path, columns, dates):
    """Read `columns` of a parquet for the given dates, whether its `date`
    column is a timestamp, a date or a string (downcap_universe_v2 is string).
    Returns `date` as datetime64."""
    t = pq.ParquetFile(path).schema_arrow.field("date").type
    ds = [pd.Timestamp(d) for d in dates]
    if pa.types.is_string(t) or pa.types.is_large_string(t):
        vals = [d.strftime("%Y-%m-%d") for d in ds]
    elif pa.types.is_date(t):
        vals = [d.date() for d in ds]
    else:
        vals = [d.to_pydatetime() for d in ds]
    df = pd.read_parquet(path, columns=columns, filters=[("date", "in", vals)])
    df["date"] = pd.to_datetime(df["date"])
    return df
