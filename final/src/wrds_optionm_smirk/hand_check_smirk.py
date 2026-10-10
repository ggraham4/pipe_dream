"""
WO-56: independent recompute of smirk for named name-dates and 100 random finite cap150 rows
(seed 56) plus 100 random NaN cap150 rows. Reads the raw vsurfd parquet with pyarrow filters and the
link tables row by row (separate code path from build_smirk.py). FACTOR ONLY, no label.
Writes out/wrds_optionm_smirk/smirk_integrity.json.
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
FINAL = HERE.parents[1]
MAIN = Path("/Users/ggraham/pipe_dream/final")
VS = MAIN / "data" / "wrds" / "optionm" / "vsurf"
OUT = FINAL / "out" / "wrds_optionm_smirk"
X = pd.read_parquet(MAIN / "data" / "wrds" / "link" / "permno_sharadar.parquet")
O = pd.read_parquet(MAIN / "data" / "wrds" / "link" / "opcrsphist.parquet")
_dates = {}


def surf_dates(y):
    if y not in _dates:
        _dates[y] = sorted(pd.to_datetime(pd.read_parquet(VS / f"vsurfd_{y}.parquet", columns=["date"]).date.unique()))
    return _dates[y]


def recompute(ticker, t):
    t = pd.Timestamp(t)
    prev = [d for d in surf_dates(t.year) + (surf_dates(t.year - 1) if t.year > 2006 else []) if d < t]
    s = max(prev)
    if (t - s).days > 5:
        return np.nan, {"s": str(s.date()), "why": "stale"}
    x = X[(X.ticker.astype(str) == ticker) & (pd.to_datetime(X.valid_from) <= t) & (pd.to_datetime(X.valid_to) >= t)]
    if x.empty:
        return np.nan, {"s": str(s.date()), "why": "no permno"}
    permno = int(x.sort_values(["match_quality", "permno"]).iloc[0].permno)
    o = O[(O.permno == permno) & (pd.to_datetime(O.sdate) <= s) & (O.edate.isna() | (pd.to_datetime(O.edate) >= s))]
    if o.empty:
        return np.nan, {"s": str(s.date()), "permno": permno, "why": "no secid"}
    raw = pd.read_parquet(VS / f"vsurfd_{s.year}.parquet", filters=[("secid", "in", [int(v) for v in o.secid])])
    raw = raw[pd.to_datetime(raw.date) == s]
    o = o.assign(has=o.secid.astype(int).isin(set(raw.secid))).sort_values(["score", "has", "secid"], ascending=[True, False, True])
    secid = int(o.iloc[0].secid)
    r = raw[raw.secid == secid]
    p = r[(r.cp_flag == "P") & (r.delta == -20)].impl_volatility
    c = r[(r.cp_flag == "C") & (r.delta == 50)].impl_volatility
    v = float(p.iloc[0] - c.iloc[0]) if len(p) == 1 and len(c) == 1 else np.nan
    return v, {"s": str(s.date()), "permno": permno, "secid": secid,
               "iv_put20": float(p.iloc[0]) if len(p) else None, "iv_call50": float(c.iloc[0]) if len(c) else None}


def same(a, b):
    return bool((np.isnan(a) and np.isnan(b)) or (np.isfinite(a) and np.isfinite(b) and abs(a - b) < 1e-12))


def main():
    F = pd.read_parquet(OUT / "cache" / "smirk_build_detail.parquet")
    F["date"] = pd.to_datetime(F.date)
    idx = F.set_index(["ticker", "date"]).smirk
    named = [("AAPL", "2012-06-15"), ("MSFT", "2015-06-15"), ("LEHMQ", "2008-06-16"), ("WAMUQ", "2008-06-16"),
             ("AAPL", "2007-01-03"), ("XOM", "2019-12-31")]
    hc = []
    for tk, d in named:
        b = float(idx.get((tk, pd.Timestamp(d)), np.nan))
        v, info = recompute(tk, d)
        hc.append({"ticker": tk, "date": d, "build": b, "recompute": v, "match": same(b, v), **info})
    G = F[F.eligible_cap150.astype(bool) & ~F.spac_drop]
    fin = G[G.smirk.notna()].sample(100, random_state=56)
    nan = G[G.smirk.isna()].sample(100, random_state=56)
    mm_f = sum(not same(float(r.smirk), recompute(r.ticker, r.date)[0]) for r in fin.itertuples())
    mm_n = sum(not same(float(r.smirk), recompute(r.ticker, r.date)[0]) for r in nan.itertuples())
    rep = {"hand_check": hc, "brute_force_100": {"seed": 56, "mismatches": int(mm_f)},
           "brute_force_100_nan_rows": {"seed": 56, "mismatches": int(mm_n)}}
    (OUT / "smirk_integrity.json").write_text(json.dumps(rep, indent=1, default=str))
    print(json.dumps({"named": [(h["ticker"], h["date"], h["build"], h["match"]) for h in hc],
                      "bf_finite_mm": mm_f, "bf_nan_mm": mm_n}, default=str))


if __name__ == "__main__":
    main()
