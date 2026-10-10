"""WO-59 probe 4: is s34type1 unique per (fdate, mgrno) across ALL rdates? (type3 has no rdate.)"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from wrdsdb import q  # noqa: E402

print(q("""select count(*) n_dup_keys from (select fdate, mgrno from tr_13f.s34type1
           where fdate between '2005-12-31' and '2019-12-31' group by 1, 2 having count(*) > 1) x""").to_string())
