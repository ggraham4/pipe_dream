"""WO-59 probe 3 (labels-free; COO addendum): fdate<rdate share, vintages per mgrno-rdate,
type3 holdings rows for one quarter, and type1/type3 join consistency. Small aggregates only."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from wrdsdb import q  # noqa: E402

W = "fdate between '2005-09-30' and '2019-12-31'"
print(q(f"""select count(*) n, sum(case when fdate < rdate then 1 else 0 end) n_f_lt_r,
               sum(case when fdate = rdate then 1 else 0 end) n_eq, sum(case when fdate > rdate then 1 else 0 end) n_gt,
               sum(case when rdate is null then 1 else 0 end) n_rnull from tr_13f.s34type1 where {W}""").to_string())
print(q(f"""select nv, count(*) n_mgr_rdate, sum(case when first_eq then 1 else 0 end) n_first_is_rdate from (
             select mgrno, rdate, count(distinct fdate) nv, min(fdate) = rdate first_eq
             from tr_13f.s34type1 where {W} group by mgrno, rdate) x group by nv order by nv""").to_string())
# gap (quarters) between rdate and fdate on stale rows
print(q(f"""select (fdate - rdate) / 90 as qgap, count(*) n from tr_13f.s34type1 where {W} and fdate > rdate
            group by 1 order by 1""").head(12).to_string())
print(q("""select count(*) n, count(distinct mgrno) nm, sum(case when shares > 0 then 1 else 0 end) npos,
              sum(case when cusip is null then 1 else 0 end) ncnull
           from tr_13f.s34type3 where fdate = '2015-12-31'""").to_string())
