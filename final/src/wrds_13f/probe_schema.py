"""WO-59 probe: tr_13f table list + column names + a 5-row sample (tiny queries only)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from wrdsdb import q  # noqa: E402

print(q("select table_name from information_schema.tables where table_schema='tr_13f' order by 1").table_name.tolist())
for t in ("s34", "s34type1", "s34type3"):
    c = q("select column_name, data_type from information_schema.columns "
          "where table_schema='tr_13f' and table_name=:t order by ordinal_position", t=t)
    print(t, list(zip(c.column_name, c.data_type)))
print(q("select mgrno, rdate, fdate, cusip, shares from tr_13f.s34 where rdate='2015-12-31' limit 5").to_string())
