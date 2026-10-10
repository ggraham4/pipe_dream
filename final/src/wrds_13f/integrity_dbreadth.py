"""
WO-59 integrity (FACTOR ONLY, no label/return/outcome): independent recompute of dbreadth (no import of
build_dbreadth), named hand checks, 100-row brute force, mapped-permno counts per quarter.
Writes final/out/wrds_13f/dbreadth_integrity.json (keys hand_check, brute_force_100 read by the screen).
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd

MAIN = Path("/Users/ggraham/pipe_dream/final")
TR = MAIN / "data" / "wrds" / "tr_13f"
OUT = Path(__file__).resolve().parents[2] / "out" / "wrds_13f"
QS = list(pd.date_range("2005-12-31", "2019-12-31", freq="QE"))
names = pd.read_parquet(MAIN / "data" / "wrds" / "crsp" / "stocknames.parquet", columns=["permno", "namedt", "nameenddt", "ncusip"])
names = names[names.ncusip.notna()].copy()
names["namedt"] = pd.to_datetime(names.namedt); names["nameenddt"] = pd.to_datetime(names.nameenddt)
xw = pd.read_parquet(MAIN / "data" / "wrds" / "link" / "permno_sharadar.parquet")
xw["valid_from"] = pd.to_datetime(xw.valid_from); xw["valid_to"] = pd.to_datetime(xw.valid_to)
F = pd.read_parquet(OUT / "cache" / "dbreadth_build_detail.parquet")
_H = {}


def Q(q):
    """per quarter: raw holdings, CF set (frozenset comparison of (cusip, shares) tuples), filers."""
    if q in _H:
        return _H[q]
    h = pd.read_parquet(TR / f"holdings_{q.date()}.parquet")
    sets = {m: frozenset(zip(g.cusip, g.shares)) if not g.duplicated(["cusip", "shares"]).any()
            else tuple(sorted(zip(g.cusip, g.shares))) for m, g in h.groupby("mgrno")}
    i = QS.index(q)
    cf = set()
    if i > 0:
        prev = Q(QS[i - 1])[3]
        cf = {m for m, s in sets.items() if m in prev and prev[m] == s}
    h2 = h[~h.mgrno.isin(cf)]
    _H[q] = (h2, cf, set(h2.mgrno), sets)
    return _H[q]


def cusips_for(permno, q):
    n = names[(names.permno == permno) & (names.namedt <= q) & (names.nameenddt >= q)]
    c = set(n.ncusip)
    # drop cusips that map to >1 permno at q (ambiguous), same as the build rule
    amb = names[names.ncusip.isin(c) & (names.namedt <= q) & (names.nameenddt >= q)].groupby("ncusip").permno.nunique()
    return c - set(amb[amb > 1].index)


def holders(q, permno, mgrs=None):
    h = Q(q)[0]
    s = set(h.mgrno[h.cusip.isin(cusips_for(permno, q))])
    return s if mgrs is None else s & mgrs


def recompute(permno, q):
    i = QS.index(q); p = QS[i - 1]
    B = Q(q)[2] & Q(p)[2]
    if not cusips_for(permno, q) or not cusips_for(permno, p):
        return np.nan, {}
    a, b = holders(q, permno), holders(p, permno)
    if not a and not b:
        return np.nan, {}
    nq, np_ = len(a & B), len(b & B)
    return (nq - np_) / len(Q(p)[2]), {"N_q": nq, "N_prev_B": np_, "M_prev": len(Q(p)[2]), "B": len(B),
                                        "holders_raw_q": len(holders(q, permno)), "cf_q": len(Q(q)[1])}


def qstar(t):
    return [q for q in QS if q + pd.Timedelta(days=60) <= t][-1]


def permno_at(tk, t):
    x = xw[(xw.ticker == tk) & (xw.valid_from <= t) & (xw.valid_to >= t)].sort_values(["match_quality", "permno"])
    return int(x.permno.iloc[0]) if len(x) else None


def check_row(tk, t):
    t = pd.Timestamp(t)
    ds = F.date[(F.ticker == tk) & (F.date >= t)]
    if not len(ds):
        return {"ticker": tk, "date": str(t.date()), "match": None, "note": "not on grid (cap150/cap2000) at/after date"}
    t = ds.min()                                  # first grid date on/after the named date
    pm = permno_at(tk, t); q = qstar(t)
    v, det = recompute(pm, q) if pm is not None else (np.nan, {})
    got = F[(F.ticker == tk) & (F.date == t)].dbreadth.iloc[0]
    match = bool((np.isnan(v) and np.isnan(got)) or abs(v - got) < 1e-12)
    return {"ticker": tk, "date": str(t.date()), "permno": pm, "q": str(q.date()), "recomputed": v,
            "built": float(got), "match": match, **det}


def main():
    rep = {}
    # 1) AAPL holder counts (first vintage, after CF removal) per quarter 2015 -- external: well over 2,000
    rep["aapl_holders_2015"] = {str(q.date()): len(holders(q, 14593)) for q in QS if q.year == 2015}
    # 2) Lehman (permno 80599) holders 2007Q1..2008Q4 and built dbreadth on dates in 2008
    rep["lehman_holders"] = {str(q.date()): len(holders(q, 80599)) for q in QS if q.year in (2007, 2008)}
    L = F[(F.ticker == "LEHMQ")].dropna(subset=["dbreadth"]).groupby("q").dbreadth.first()
    rep["lehman_dbreadth_by_q"] = {str(pd.Timestamp(k).date()): float(v) for k, v in L.items() if pd.Timestamp(k).year >= 2007}
    # 3) delisted mid-sample: WAMU (81593, failed 2008-09) and APC (70332, acquired 2019-08)
    rep["wamu_holders"] = {str(q.date()): len(holders(q, 81593)) for q in QS if q.year in (2008, 2009)}
    rep["apc_holders"] = {str(q.date()): len(holders(q, 70332)) for q in QS if q.year == 2019}
    # 4) named row hand checks
    hc = [check_row(tk, t) for tk, t in
          [("AAPL", "2015-06-15"), ("MSFT", "2012-03-15"), ("LEHMQ", "2008-06-16"),
           ("WAMUQ", "2008-06-16"), ("APC", "2019-06-14")]]
    rep["hand_check_not_on_grid"] = [h for h in hc if h["match"] is None]
    rep["hand_check"] = [h for h in hc if h["match"] is not None]
    # 5) brute force 100 random finite cap150 rows
    rng = np.random.default_rng(59)
    pool = F[F.eligible_cap150.astype(bool) & ~F.spac_drop & F.dbreadth.notna()]
    smp = pool.iloc[rng.choice(len(pool), 100, replace=False)]
    bf = [check_row(r.ticker, r.date) for r in smp.itertuples()]
    rep["brute_force_100"] = {"seed": 59, "n": len(bf), "mismatches": int(sum(not b["match"] for b in bf)),
                              "pit_ok": bool(all(pd.Timestamp(b["q"]) + pd.Timedelta(days=60) <= pd.Timestamp(b["date"]) for b in bf)),
                              "examples": bf[:3]}
    # 5b) trap rule applied: every grid row whose change spans a flagged quarter is NaN
    st = pd.read_csv(OUT / "manager_counts.csv")
    fl = set(pd.to_datetime(st.q[st.flag]))
    nxt = {QS[i]: QS[i + 1] for i in range(len(QS) - 1)}
    span = set(fl) | {nxt[q] for q in fl if q in nxt}
    sp = F.q.isin(span)
    rep["trap_rule"] = {"flagged_quarters": sorted(str(q.date()) for q in fl),
                        "nan_change_quarters": sorted(str(q.date()) for q in span),
                        "grid_rows_spanning": int(sp.sum()), "all_nan": bool(F.dbreadth[sp].isna().all())}
    # 6) distinct mapped permnos per quarter (2017Q4 TR regime check)
    rep["mapped_permnos_per_q"] = {}
    for q in QS:
        h = Q(q)[0]
        v = names[(names.namedt <= q) & (names.nameenddt >= q)].drop_duplicates(["ncusip", "permno"])
        rep["mapped_permnos_per_q"][str(q.date())] = int(h[h.cusip.isin(set(v.ncusip))].cusip.nunique())
    (OUT / "dbreadth_integrity.json").write_text(json.dumps(rep, indent=1, default=float))
    print(json.dumps({k: rep[k] for k in ("aapl_holders_2015", "lehman_holders", "lehman_dbreadth_by_q", "wamu_holders", "apc_holders")}, default=float))
    print([(h["ticker"], h["match"], h["recomputed"]) for h in rep["hand_check"]])
    print({k: v for k, v in rep["brute_force_100"].items() if k != "examples"})
    print(rep["mapped_permnos_per_q"])


if __name__ == "__main__":
    main()
