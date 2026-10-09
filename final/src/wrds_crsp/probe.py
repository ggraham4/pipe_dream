"""Probe WRDS schemas: columns of the tables WO-51 pulls (small queries)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from wrdsdb import q  # noqa: E402

for sch, tb in [("wrdsapps", "opcrsphist"), ("wrdsapps", "ibcrsphist"), ("crsp", "stocknames"),
                ("crsp", "dsedelist"), ("crsp", "dsf"), ("crsp", "stkdlysecuritydata"), ("crsp", "stkdelists")]:
    c = q("select column_name, data_type from information_schema.columns where table_schema=:s and table_name=:t order by ordinal_position", s=sch, t=tb)
    print(sch, tb, ", ".join(f"{a}:{b[:4]}" for a, b in zip(c.column_name, c.data_type)))
print(q("select max(date) as mx from crsp.dsf"))
