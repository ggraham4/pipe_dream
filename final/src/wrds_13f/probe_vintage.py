"""WO-59 probe 2 (manager table s34type1 only; small aggregates, no holdings, no outcomes):
fdate/rdate structure, first-vintage counts, distinct managers per quarter 2005Q4..2019Q4."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from wrdsdb import q  # noqa: E402

d = q("""select fdate, rdate, count(*) n, count(distinct mgrno) nm
         from tr_13f.s34type1 where fdate between '2005-09-30' and '2020-03-31'
         group by fdate, rdate order by fdate, rdate""")
d["fdate"] = d.fdate.astype(str); d["rdate"] = d.rdate.astype(str)
print("non-quarter-end fdates:", sorted(set(x for x in d.fdate if x[5:] not in ("03-31", "06-30", "09-30", "12-31")))[:10])
print("non-quarter-end rdates:", sorted(set(x for x in d.rdate if x[5:] not in ("03-31", "06-30", "09-30", "12-31")))[:10])
same = d[d.fdate == d.rdate].set_index("fdate")[["n", "nm"]]
tot = d.groupby("fdate")[["n", "nm"]].sum()
lag = d[d.fdate != d.rdate].groupby("fdate")[["nm"]].sum().rename(columns={"nm": "nm_stale"})
print(same.join(tot, rsuffix="_all").join(lag).to_string())
# duplicated (mgrno, rdate, fdate) rows in type1
print(q("""select fdate, count(*) - count(distinct mgrno) dup from tr_13f.s34type1
          where fdate=rdate and fdate between '2005-09-30' and '2019-12-31' group by fdate having count(*) > count(distinct mgrno) order by fdate""").to_string())
