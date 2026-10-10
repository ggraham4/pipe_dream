"""
WO-56: build the IV smirk factor (Xing-Zhang-Zhao 2010) on the v2 grid. FACTOR ONLY: never opens a
label, return or outcome file. Spec: final/models/2026-10-09-iv-smirk.md.

smirk(i, t) = IV(put, delta -20, 30d) - IV(call, delta +50, 30d) from optionm.vsurfd on the surface
date s(t) = the latest OptionMetrics surface date strictly before panel date t (global date set),
with t - s(t) <= 5 calendar days. No per-name fallback: if name i has no (complete) surface on s(t),
smirk is NaN. Composite sign -1 (score = -smirk).

Link: Sharadar ticker -> permno at t (WO-51 permno_sharadar, valid_from <= t <= valid_to; best
match_quality, then lowest permno); permno -> secid at s(t) (opcrsphist sdate <= s <= edate or open;
lowest score, then the secid with a surface row on s, then lowest secid) -- WO-52's rule.

    caffeinate -i /opt/anaconda3/envs/pipe_dream/bin/python final/src/wrds_optionm_smirk/build_smirk.py
"""
import hashlib
import json
import time
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
FINAL = HERE.parents[1]
MAIN = Path("/Users/ggraham/pipe_dream/final")
VS = MAIN / "data" / "wrds" / "optionm" / "vsurf"
XWALK = MAIN / "data" / "wrds" / "link" / "permno_sharadar.parquet"
OPCRSP = MAIN / "data" / "wrds" / "link" / "opcrsphist.parquet"
PANEL = MAIN / "out" / "reset2026" / "composite_panel_v2.parquet"
PANEL_OLD = MAIN / "out" / "reset2026" / "composite_panel.parquet"
TICKERS = MAIN / "data" / "sharadar" / "tickers_master.csv"
OUT = FINAL / "out" / "wrds_optionm_smirk"
CACHE = OUT / "cache"
LO, HI = pd.Timestamp("2007-01-02"), pd.Timestamp("2019-12-31")
STALE_MAX = 5


def log(m):
    print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)


def load_surface():
    d = pd.concat([pd.read_parquet(VS / f"vsurfd_{y}.parquet") for y in range(2006, 2020)], ignore_index=True)
    d["date"] = pd.to_datetime(d["date"])
    assert d.date.max() <= HI
    sdates = np.array(sorted(d.date.unique()), dtype="datetime64[ns]")
    p = d[(d.cp_flag == "P") & (d.delta == -20)].set_index(["secid", "date"]).impl_volatility
    c = d[(d.cp_flag == "C") & (d.delta == 50)].set_index(["secid", "date"]).impl_volatility
    assert p.index.is_unique and c.index.is_unique
    rows = pd.Index(d[["secid", "date"]].drop_duplicates().itertuples(index=False, name=None))
    sm = (p - c.reindex(p.index)).rename("smirk")         # NaN if either leg missing / NaN
    sm = sm.reindex(sm.index.union(c.index))
    return sm, sdates, rows, {"surface_rows": len(d), "surface_dates": len(sdates),
                              "secid_dates": len(rows), "complete_smirk": int(sm.notna().sum())}


def load_grid():
    p = pd.read_parquet(PANEL, columns=["ticker", "date", "eligible_cap150", "eligible_cap2000"],
                        filters=[("date", ">=", "2007-01-02"), ("date", "<=", "2019-12-31")])
    p["date"] = pd.to_datetime(p.date); p["ticker"] = p.ticker.astype(str)
    p = p[p.eligible_cap150.astype(bool) | p.eligible_cap2000.astype(bool)].reset_index(drop=True)
    old_t = set(pd.read_parquet(PANEL_OLD, columns=["ticker"])["ticker"].astype(str).unique())
    tm = pd.read_csv(TICKERS, dtype=str, usecols=["ticker", "sicindustry"]).drop_duplicates("ticker")
    spac = set(tm.loc[tm["sicindustry"].fillna("").str.contains("Blank Check"), "ticker"])
    p["spac_drop"] = ~(p.ticker.isin(old_t) | ~p.ticker.isin(spac))     # same SPAC rule as load_theo
    return p


def main():
    t0 = time.time()
    CACHE.mkdir(parents=True, exist_ok=True)
    sm, sdates, rows, smeta = load_surface()
    log(f"surface {smeta}")
    U = load_grid()
    log(f"grid rows {len(U):,}, dates {U.date.nunique()}")
    X = pd.read_parquet(XWALK, columns=["permno", "ticker", "valid_from", "valid_to", "match_quality"])
    X["ticker"] = X.ticker.astype(str); X["permno"] = X.permno.astype("int64")
    X["valid_from"] = pd.to_datetime(X.valid_from); X["valid_to"] = pd.to_datetime(X.valid_to)
    X = X[X.ticker.isin(set(U.ticker))]
    O = pd.read_parquet(OPCRSP)
    O = O[O.permno.notna() & O.sdate.notna()].copy()
    O["sdate"] = pd.to_datetime(O.sdate); O["edate"] = pd.to_datetime(O.edate)
    O["permno"] = O.permno.astype("int64"); O["secid"] = O.secid.astype("int64")
    O = O[O.permno.isin(set(X.permno))]
    rowset = set(rows)
    out = []
    for t, g in U.groupby("date", sort=True):
        i = np.searchsorted(sdates, np.datetime64(t), side="left") - 1
        s = pd.Timestamp(sdates[i]) if i >= 0 else pd.NaT
        assert pd.isna(s) or s < t
        stale = (t - s).days if not pd.isna(s) else 999
        x = X[(X.valid_from <= t) & (X.valid_to >= t)].sort_values(["match_quality", "permno"]).drop_duplicates("ticker")
        m = g[["ticker"]].merge(x[["ticker", "permno"]], on="ticker", how="left")
        if stale <= STALE_MAX:
            o = O[(O.sdate <= s) & (O.edate.isna() | (O.edate >= s))][["permno", "secid", "score"]].copy()
            o["has"] = [(sid, s) in rowset for sid in o.secid]
            o = o.sort_values(["permno", "score", "has", "secid"], ascending=[True, True, False, True]).drop_duplicates("permno")
            m = m.merge(o[["permno", "secid", "score"]], on="permno", how="left")
            key = pd.MultiIndex.from_arrays([m.secid.fillna(-1).astype("int64"), np.repeat(s, len(m))])
            v = sm.reindex(key).to_numpy()
        else:
            m["secid"] = np.nan; m["score"] = np.nan; v = np.full(len(m), np.nan)
        out.append(pd.DataFrame({"ticker": m.ticker.to_numpy(), "date": t, "surf_date": s, "permno": m.permno.to_numpy(),
                                 "secid": m.secid.to_numpy(), "link_score": m.score.to_numpy(), "smirk": v}))
    F = pd.concat(out, ignore_index=True)
    assert len(F) == len(U)
    F = F.merge(U[["ticker", "date", "eligible_cap150", "eligible_cap2000", "spac_drop"]], on=["ticker", "date"], how="left", validate="1:1")
    ok = F.smirk.notna()
    assert (F.loc[ok, "surf_date"] < F.loc[ok, "date"]).all() and ((F.loc[ok, "date"] - F.loc[ok, "surf_date"]).dt.days <= STALE_MAX).all()
    assert F.date.max() <= HI and F.date.min() >= LO
    fac = F[["ticker", "date", "smirk"]].copy()
    dst = CACHE / "smirk_factor.parquet"
    fac.to_parquet(dst, index=False)
    sha = hashlib.sha256(dst.read_bytes()).hexdigest()
    F.to_parquet(CACHE / "smirk_build_detail.parquet", index=False)
    # integrity (factor only)
    K = F[~F.spac_drop]
    cov = {}
    for tier in ("cap150", "cap2000"):
        k = K[K[f"eligible_{tier}"].astype(bool)]
        cov[tier] = {"rows": len(k), "finite_share": float(k.smirk.notna().mean()),
                     "permno_share": float(k.permno.notna().mean()), "secid_share": float(k.secid.notna().mean()),
                     "by_year": {int(y): float(v) for y, v in k.groupby(k.date.dt.year).smirk.apply(lambda s: s.notna().mean()).items()}}
    f150 = K[K.eligible_cap150.astype(bool) & K.smirk.notna()]
    q = f150.smirk.quantile([.01, .05, .25, .5, .75, .95, .99])
    rep = {"factor_sha256": sha, "rows": len(F), "surface": smeta, "stale_max_days": STALE_MAX,
           "coverage_spac_rule_applied": cov,
           "dist_cap150_finite": {str(k): float(v) for k, v in q.items()},
           "share_negative_cap150": float((f150.smirk < 0).mean()),
           "link_score_counts_finite": F[ok].link_score.value_counts().sort_index().to_dict(),
           "secid_multi_ticker_same_date_rows": int(F[ok].duplicated(["date", "secid"], keep=False).sum()),
           "staleness_days_counts": (F.loc[ok, "date"] - F.loc[ok, "surf_date"]).dt.days.value_counts().sort_index().to_dict(),
           "runtime_s": round(time.time() - t0, 1)}
    (OUT / "smirk_build.json").write_text(json.dumps(rep, indent=1, default=str))
    log(json.dumps({k: rep[k] for k in ("factor_sha256", "rows", "dist_cap150_finite", "share_negative_cap150")}, default=str))
    log(f"coverage cap150 {cov['cap150']['finite_share']:.3f} cap2000 {cov['cap2000']['finite_share']:.3f}")


if __name__ == "__main__":
    main()
