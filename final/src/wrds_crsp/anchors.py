"""WO-51 Phase 1 named-anchor check of the crosswalk (identity only, no return statistic).

For each anchor, the expected permno is found independently on the CRSP side (stocknames by
company name / the WO's stated permno), and compared with what the crosswalk gives for the
Sharadar ticker on the anchor date. Also reports CRSP delisting date/code and the crosswalk valid_to.
Writes final/out/wrds_crsp/anchors.json.
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from wrdsdb import CRSP_DIR, LINK_DIR, MAIN  # noqa: E402

REPO = Path(__file__).resolve().parents[3]
xw = pd.read_parquet(LINK_DIR / "permno_sharadar.parquet")
nm = pd.read_parquet(CRSP_DIR / "stocknames.parquet")
dl = pd.read_parquet(CRSP_DIR / "dsedelist.parquet")
tk = pd.read_csv(MAIN / "final/data/sharadar/tickers_master.csv", low_memory=False)
grid = set(pd.read_parquet(MAIN / "final/out/reset2026/downcap_v2/grid_tickers_v2.parquet").ticker)


def crsp_permno(pattern, on_date):
    d = pd.Timestamp(on_date)
    m = nm[nm.comnam.str.contains(pattern, regex=True, na=False)
           & (pd.to_datetime(nm.namedt) <= d) & (pd.to_datetime(nm.nameenddt) >= d) & nm.shrcd.isin([10, 11])]
    return sorted(m.permno.unique().tolist())


def xw_permno(ticker, on_date):
    d = pd.Timestamp(on_date)
    m = xw[(xw.ticker == ticker) & (xw.valid_from <= d) & (xw.valid_to >= d)]
    return (int(m.permno.iloc[0]), m.match_quality.iloc[0], str(m.valid_to.iloc[0].date())) if len(m) else (None, None, None)


anchors = [
    ("AAPL 2008", "AAPL", "2008-06-30", "^APPLE ", 14593),
    ("Lehman", "LEHMQ", "2008-06-30", "LEHMAN BROTHERS HOLDINGS", 80599),
    ("Bear Stearns", "BSC1", "2008-03-14", "BEAR STEARNS COMPANIES", None),
    ("Washington Mutual", "WAMUQ", "2008-06-30", "WASHINGTON MUTUAL INC", None),
    ("old General Motors", "MTLQQ", "2009-03-02", "GENERAL MOTORS CORP", None),
]
# 5 random dead names: grid tickers delisted 2007-2019 (Sharadar), seed 51
dead = tk[tk.ticker.isin(grid) & (tk.isdelisted == "Y")
          & pd.to_datetime(tk.lastpricedate).between("2007-06-01", "2019-12-31")
          & pd.to_datetime(tk.firstpricedate).lt("2007-01-01")]
pick = dead.sample(5, random_state=51)
for _, r in pick.iterrows():
    d = (pd.Timestamp(r.lastpricedate) - pd.Timedelta(days=365)).strftime("%Y-%m-%d")
    anchors.append((f"random dead {r.ticker}", r.ticker, d, None, None))

res = []
for label, t, d, pat, want in anchors:
    got, qual, vto = xw_permno(t, d)
    if pat is not None:
        exp = crsp_permno(pat, d)
    else:  # random dead names: CRSP name whose ticker on date matches the Sharadar ticker or its related tickers
        rel = set(str(tk.loc[tk.ticker == t, "relatedtickers"].fillna("").iloc[0]).split()) | {t}
        dd = pd.Timestamp(d)
        m = nm[nm.ticker.isin(rel) & (pd.to_datetime(nm.namedt) <= dd) & (pd.to_datetime(nm.nameenddt) >= dd)]
        exp = sorted(m.permno.unique().tolist())
    if want is not None:
        exp = [want] if (not exp or want in exp) else exp + [want]
    dli = dl[dl.permno == got] if got else dl.iloc[0:0]
    sh = tk[tk.ticker == t].iloc[0]
    ok = got is not None and got in exp and (want is None or got == want)
    res.append({"anchor": label, "sharadar_ticker": t, "permaticker": int(sh.permaticker), "date": d,
                "crosswalk_permno": got, "expected_permno": exp, "quality": qual,
                "crosswalk_valid_to": vto, "sharadar_lastpricedate": sh.lastpricedate,
                "crsp_dlstdt": str(dli.dlstdt.iloc[0]) if len(dli) else None,
                "crsp_dlstcd": int(dli.dlstcd.iloc[0]) if len(dli) else None,
                "crsp_dlret": (None if not len(dli) or pd.isna(dli.dlret.iloc[0]) else float(dli.dlret.iloc[0])),
                "ok": bool(ok)})
out = REPO / "final/out/wrds_crsp/anchors.json"
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps(res, indent=1, default=str))
for r in res:
    print(f"{r['anchor']:<22} {r['sharadar_ticker']:<7} {r['date']} xw={r['crosswalk_permno']} exp={r['expected_permno']} "
          f"q={r['quality']} vto={r['crosswalk_valid_to']} shr_last={r['sharadar_lastpricedate']} "
          f"dlst={r['crsp_dlstdt']}/{r['crsp_dlstcd']} dlret={r['crsp_dlret']} {'OK' if r['ok'] else 'FAIL'}")
