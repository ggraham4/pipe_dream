"""WO-53: independent hand-check of rev3 (factor only, no outcome). Recomputes a few
(Sharadar ticker, date) values straight from the raw IBES / CRSP / SEP parquet with
row-by-row logic (no import of build_rev3), and lists split-window examples.
Appends results to final/out/wrds_ibes/rev3_integrity.json under "hand_check".
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd

DATA = Path("/Users/ggraham/pipe_dream/final/data")
IB = DATA / "wrds" / "ibes"
OUT = Path(__file__).resolve().parents[2] / "out" / "wrds_ibes"
fac = pd.read_parquet(OUT / "cache" / "rev3_factor.parquet")
fac["date"] = pd.to_datetime(fac["date"])
raw = pd.concat([pd.read_parquet(p) for p in sorted(IB.glob("statsumu_epsus_fy12_*.parquet"))], ignore_index=True)
raw = raw[(raw.usfirm == 1) & (raw.curcode == "USD") & (raw.fiscalp == "ANN")]
lk = pd.read_parquet(IB / "ibcrsphist.parquet")
ev = pd.read_parquet(IB / "crsp_dsedist_facshr.parquet")
xw = pd.read_parquet(DATA / "wrds" / "link" / "permno_sharadar.parquet")


def sep_close(tk, d):
    for p in [d.to_period("M"), d.to_period("M") - 1]:
        s = pd.read_parquet(DATA / "sharadar" / "panel" / "stocks" / f"{p}.parquet", columns=["ticker", "date", "closeunadj"])
        s = s[(s.ticker == tk) & (pd.to_datetime(s.date) <= d)]
        if len(s):
            r = s.sort_values("date").iloc[-1]
            return float(r.closeunadj), str(pd.Timestamp(r.date).date())
    return np.nan, None


def recompute(tk, t):
    t = pd.Timestamp(t)
    x = xw[(xw.ticker == tk) & (pd.to_datetime(xw.valid_from) <= t) & (pd.to_datetime(xw.valid_to) >= t)]
    permno = int(x.permno.iloc[0])
    l = lk[(lk.permno == permno) & (lk.score <= 2)]
    cands = raw[raw.ticker.isin(l.ticker) & (raw.fpi == "1") & (raw.statpers < t)]
    best = None
    for _, r in cands.iterrows():          # row-by-row: latest statpers < t inside a valid link window
        ok = ((l.ticker == r.ticker) & (pd.to_datetime(l.sdate) <= r.statpers) & (pd.to_datetime(l.edate) >= r.statpers)).any()
        if ok and (best is None or r.statpers > best.statpers):
            best = r
    s1, E, F1, n1, it = best.statpers, best.fpedats, best.meanest, best.numest, best.ticker
    assert (t - s1).days <= 45
    m0 = (s1.to_period("M") - 3)
    r0 = raw[(raw.ticker == it) & (raw.statpers.dt.to_period("M") == m0) & (raw.fpedats == E)].iloc[0]
    s0, F0, n0 = r0.statpers, r0.meanest, r0.numest
    e = ev[(ev.permno == permno) & (ev.distcd.astype(int) // 1000 == 5) & (ev.exdt > s0) & (ev.exdt <= s1)]
    k = float(np.prod(1 + e.facshr.to_numpy())) if len(e) else 1.0
    P0, pd0 = sep_close(tk, s0)
    rev = (F1 * k - F0) / P0
    row = fac[(fac.ticker == tk) & (fac.date == t)].iloc[0]; got, gf = row.rev3_kadj, row.rev3
    return {"ticker": tk, "date": str(t.date()), "permno": permno, "ibes": it, "s1": str(s1.date()), "s0": str(s0.date()),
            "E": str(pd.Timestamp(E).date()), "fpi0": r0.fpi, "F1": F1, "F0": F0, "n1": int(n1), "n0": int(n0), "k": k,
            "P0": P0, "P0_date": pd0, "rev3_recomputed": rev, "rev3_kadj_built": float(got), "rev3_final": float(gf), "match": bool(abs(rev - got) < 1e-12)}


checks = [("AAPL", "2012-06-15"), ("MSFT", "2015-06-15"), ("LEHMQ", "2008-06-16"), ("WAMUQ", "2008-06-16"),
          ("AAPL", "2014-07-01")]
res = []
for tk, t in checks:
    try:
        res.append(recompute(tk, t))
    except Exception as ex:  # report, don't hide
        res.append({"ticker": tk, "date": t, "error": repr(ex)})
# random brute-force sample: 100 cap150 rows with finite rev3 (seed 53), all must match
rs = fac[fac.cap150 & fac.rev3.notna()].sample(100, random_state=53)
bf = [recompute(r.ticker, r.date) for r in rs.itertuples()]
brute = {"n": len(bf), "mismatches": int(sum(not b["match"] for b in bf)),
         "pit_s1_lt_t": bool(all(pd.Timestamp(b["s1"]) < pd.Timestamp(b["date"]) for b in bf)),
         "E_matches_build_and_s0_matched_on_E": bool(all(b["E"] == str(pd.Timestamp(r.E).date()) for b, r in zip(bf, rs.itertuples())))}
print("brute force", brute)
for r in res:
    print({k: (round(v, 6) if isinstance(v, float) else v) for k, v in r.items()})

# split-window examples (largest |log k| among cap150 rows, one per name), compare rev3 with unadjusted naive
lv = pd.read_parquet(OUT / "cache" / "rev3_ibes_level.parquet")
sp = lv[lv.split_in_window & lv.rev3_kadj.notna()].copy()
sp["naive"] = (sp.F1 - sp.F0) / sp.P0
sp["abslogk"] = np.log(sp.k).abs()
ex = sp.sort_values("abslogk", ascending=False).drop_duplicates("permno")
pick = pd.concat([ex[ex.sh_ticker_s0 == "AAPL"], ex[(ex.k == 2.0)].head(1), ex[(ex.k < 1)].head(1)])
split_examples = pick[["sh_ticker_s0", "s0", "s1", "F0", "F1", "k", "sep_k", "P0", "rev3_kadj", "rev3", "naive"]].astype(str).to_dict("records")
for r in split_examples:
    print(r)
# fake-revision check: rev3 distribution on split vs non-split rows (factor only)
q = lambda s: s.quantile([.01, .5, .99]).round(4).tolist()
dist = {"split_rows_rev3_kadj_q01_50_99": q(sp.rev3_kadj), "split_rows_naive_q01_50_99": q(sp.naive),
        "nonsplit_rows_rev3_q01_50_99": q(lv[~lv.split_in_window & lv.rev3.notna()].rev3)}
print(dist)
disagree = sp[~np.isclose(sp.sep_k, sp.k, rtol=0.02) & sp.sep_k.notna()]
dis = {"n": int(len(disagree)), "examples": disagree[["sh_ticker_s0", "s0", "s1", "k", "sep_k", "rev3_kadj"]].head(6).astype(str).to_dict("records")}
print(dis)
meta = json.loads((OUT / "rev3_integrity.json").read_text())
meta["hand_check"] = res
meta["brute_force_100"] = brute
meta["split_examples"] = split_examples
meta["split_distribution"] = dist
meta["split_sep_crsp_disagree"] = dis
(OUT / "rev3_integrity.json").write_text(json.dumps(meta, indent=1, default=str))
