"""
WO-59: build the 13F breadth-change factor `dbreadth` (Chen-Hong-Stein 2002) on the v2 grid.
FACTOR ONLY: never opens a label, return or outcome column. Spec: final/models/2026-10-10-13f-breadth.md.

Rules (frozen in the pre-reg):
  * First vintage only: holdings of manager m for report quarter q are the s34type3 rows with fdate = q whose
    s34type1 row has rdate = fdate = q (pull_13f.py). Later vintages (fdate > rdate: carried-forward or late) are
    never used. shares > 0 only.
  * Carried-forward detection: manager-quarter (m, q) is CF-flagged if its multiset {(cusip, shares)} at q is
    exactly identical to its first-vintage multiset at q-1. CF-flagged manager-quarters are removed everywhere
    (not a filer, holds nothing) at q.
  * Filers F_q = managers with >= 1 first-vintage holding at q after CF removal; M_q = |F_q|.
  * Manager-count trap rule: quarter q is FLAGGED if Mraw_q < 0.90 * Mraw_{q-1} (Mraw = first-vintage holders
    before CF removal; a drop vs the preceding quarter, rises are not drops), OR if more than 100 permnos with
    >= 10 both-quarter holders at q-1 have 0 holders at q while CRSP still lists them (security-coverage gap,
    probe_vanish.py; flags 2011Q1, 2015Q2, 2017Q4 on the probe). A change spanning a flagged
    quarter (q or q-1 flagged) is NaN.
  * cusip (8) -> permno at rdate q via crsp.stocknames ncusip, namedt <= q <= nameenddt.
  * B_q = F_q & F_{q-1}. N_q(p) = #{m in B_q holding p at q}; N'_{q-1}(p) = #{m in B_q holding p at q-1}.
    dbreadth_q(p) = (N_q(p) - N'_{q-1}(p)) / M_{q-1}. Defined only if p has a date-valid stocknames record at
    BOTH rdates and appears (any first-vintage holder, before the B restriction) in at least one of the two
    quarters; otherwise NaN.
  * PIT: at panel date t use q* = the latest quarter-end with q* + 60 calendar days <= t (asserted row by row).
  * Grid ticker -> permno at t via the WO-51 crosswalk (valid_from <= t <= valid_to; best match_quality, then
    lowest permno), respecting WO-47 ticker-reuse segmentation (crosswalk tickers are the segmented ones).

    caffeinate -i /opt/anaconda3/envs/pipe_dream/bin/python final/src/wrds_13f/build_dbreadth.py
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
TR = MAIN / "data" / "wrds" / "tr_13f"
NAMES = MAIN / "data" / "wrds" / "crsp" / "stocknames.parquet"
XWALK = MAIN / "data" / "wrds" / "link" / "permno_sharadar.parquet"
PANEL = MAIN / "out" / "reset2026" / "composite_panel_v2.parquet"
PANEL_OLD = MAIN / "out" / "reset2026" / "composite_panel.parquet"
TICKERS = MAIN / "data" / "sharadar" / "tickers_master.csv"
OUT = FINAL / "out" / "wrds_13f"
CACHE = OUT / "cache"
LO, HI = pd.Timestamp("2007-01-02"), pd.Timestamp("2019-12-31")
QS = pd.date_range("2005-12-31", "2019-12-31", freq="QE")
DELIST = MAIN / "data" / "wrds" / "crsp" / "dsedelist.parquet"
LAG = 60
DROP = 0.90
VANISH_MAX = 100


def log(m):
    print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def load_names():
    s = pd.read_parquet(NAMES, columns=["permno", "namedt", "nameenddt", "ncusip"])
    s = s[s.ncusip.notna()].copy()
    s["namedt"] = pd.to_datetime(s.namedt); s["nameenddt"] = pd.to_datetime(s.nameenddt)
    return s


def map_cusip(names, q):
    """cusip -> permno valid at q (ambiguous cusips dropped and counted)."""
    v = names[(names.namedt <= q) & (names.nameenddt >= q)][["ncusip", "permno"]].drop_duplicates()
    amb = v.ncusip.duplicated(keep=False)
    return v[~amb].set_index("ncusip").permno, int(amb.sum()), set(v.permno)


def holdings(q):
    h = pd.read_parquet(TR / f"holdings_{q.date()}.parquet")
    return h


def mset(h):
    """per-manager hash of the sorted (cusip, shares) multiset."""
    k = h.sort_values(["mgrno", "cusip", "shares"])
    s = k.cusip.astype(str) + ":" + k.shares.map(lambda x: f"{x:.0f}")
    return s.groupby(k.mgrno).agg(lambda z: hashlib.md5("|".join(z).encode()).hexdigest())


def quarters():
    names = load_names()
    raw, mapped, stat, prevhash = {}, {}, [], None
    for q in QS:
        h = holdings(q)
        hs = mset(h)
        cf = set()
        if prevhash is not None:
            j = hs.to_frame("a").join(prevhash.to_frame("b"), how="inner")
            cf = set(j.index[j.a == j.b])
        prevhash = hs
        n_pos = h.groupby("mgrno").size()
        h = h[~h.mgrno.isin(cf)]
        cmap, n_amb, valid_permnos = map_cusip(names, q)
        h = h.assign(permno=h.cusip.map(cmap))
        stat.append({"q": str(q.date()), "mgr_raw": int(n_pos.size), "cf_flagged": len(cf),
                     "cf_flagged_le2_positions": int(n_pos.reindex(list(cf)).le(2).sum()) if cf else 0,
                     "mgr": int(h.mgrno.nunique()), "rows": len(h), "cusips": int(h.cusip.nunique()),
                     "rows_mapped_share": float(h.permno.notna().mean()), "ambiguous_ncusip": n_amb})
        mapped[q] = (h[h.permno.notna()][["mgrno", "permno"]].drop_duplicates().astype("int64"),
                     set(h.mgrno.unique()), valid_permnos)
        log(f"{q.date()} mgr {stat[-1]['mgr']} cf {len(cf)} rows {len(h):,} mapped {stat[-1]['rows_mapped_share']:.3f}")
    st = pd.DataFrame(stat).set_index("q")
    st["flag"] = st.mgr_raw < DROP * st.mgr_raw.shift(1)      # raw first-vintage holder counts (pre-CF)
    return mapped, st


def changes(mapped, st):
    out = []
    for i in range(1, len(QS)):
        q, p = QS[i], QS[i - 1]
        hq, fq, vq = mapped[q]; hp, fp, vp = mapped[p]
        B = fq & fp
        Mp = len(fp)
        nq = hq[hq.mgrno.isin(B)].groupby("permno").mgrno.nunique()
        np_ = hp[hp.mgrno.isin(B)].groupby("permno").mgrno.nunique()
        anyq = set(hq.permno); anyp = set(hp.permno)
        perm = sorted((anyq | anyp) & vq & vp)
        idx = pd.Index(perm, name="permno")
        d = (nq.reindex(idx).fillna(0) - np_.reindex(idx).fillna(0)) / Mp
        out.append(pd.DataFrame({"permno": perm, "q": q, "N_q": nq.reindex(idx).fillna(0).to_numpy(),
                                 "N_prev_B": np_.reindex(idx).fillna(0).to_numpy(), "M_prev": Mp,
                                 "B": len(B), "dbreadth_raw": d.to_numpy()}))
    C = pd.concat(out, ignore_index=True)
    # security-coverage trap rule (probe_vanish.py): quarter q is FLAGGED if more than VANISH_MAX permnos that
    # had >= 10 both-quarter holders at q-1 have 0 at q while CRSP still lists them (no dsedelist dlstdt
    # on or before q + 45 days).
    dl = pd.read_parquet(DELIST, columns=["permno", "dlstdt"]).dropna()
    dl["dlstdt"] = pd.to_datetime(dl.dlstdt)
    dl = dl.sort_values("dlstdt").drop_duplicates("permno", keep="first").set_index("permno").dlstdt
    v = C[(C.N_prev_B >= 10) & (C.N_q == 0)].copy()
    dd = dl.reindex(v.permno).to_numpy()
    v["alive"] = pd.isna(dd) | (dd > (v.q + pd.Timedelta(days=45)).to_numpy())
    van = v[v.alive].groupby("q").size().reindex(QS[1:], fill_value=0)
    st["vanish_still_listed"] = [0] + van.tolist()
    st["flag_mgr"] = st["flag"]
    st["flag_vanish"] = st.vanish_still_listed > VANISH_MAX
    st["flag"] = st.flag_mgr | st.flag_vanish
    fl = set(pd.to_datetime(st.index[st.flag]))
    prevq = dict(zip(QS[1:], QS[:-1]))
    bad = C.q.isin(fl) | C.q.map(prevq).isin(fl)
    C["dbreadth"] = C.dbreadth_raw.where(~bad)
    return C


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


def qstar(t):
    """latest quarter-end q with q + LAG days <= t."""
    c = QS[QS + pd.Timedelta(days=LAG) <= t]
    return c[-1]


def main():
    t0 = time.time()
    CACHE.mkdir(parents=True, exist_ok=True)
    mapped, st = quarters()
    C = changes(mapped, st)
    st.to_csv(OUT / "manager_counts.csv")
    C.to_parquet(CACHE / "dbreadth_by_permno_quarter.parquet", index=False)
    log(f"changes rows {len(C):,}; flagged quarters {st.index[st.flag].tolist()}")
    U = load_grid()
    X = pd.read_parquet(XWALK, columns=["permno", "ticker", "valid_from", "valid_to", "match_quality"])
    X["ticker"] = X.ticker.astype(str); X["permno"] = X.permno.astype("int64")
    X["valid_from"] = pd.to_datetime(X.valid_from); X["valid_to"] = pd.to_datetime(X.valid_to)
    X = X[X.ticker.isin(set(U.ticker))]
    Cv = C.set_index(["permno", "q"])["dbreadth"]
    assert Cv.index.is_unique
    out = []
    for t, g in U.groupby("date", sort=True):
        qs = qstar(t)
        x = X[(X.valid_from <= t) & (X.valid_to >= t)].sort_values(["match_quality", "permno"]).drop_duplicates("ticker")
        m = g[["ticker"]].merge(x[["ticker", "permno"]], on="ticker", how="left")
        key = pd.MultiIndex.from_arrays([m.permno.fillna(-1).astype("int64"), np.repeat(qs, len(m))])
        out.append(pd.DataFrame({"ticker": m.ticker.to_numpy(), "date": t, "q": qs, "permno": m.permno.to_numpy(),
                                 "dbreadth": Cv.reindex(key).to_numpy()}))
    F = pd.concat(out, ignore_index=True)
    assert len(F) == len(U)
    F = F.merge(U[["ticker", "date", "eligible_cap150", "eligible_cap2000", "spac_drop"]], on=["ticker", "date"],
                how="left", validate="1:1")
    assert ((F.q + pd.Timedelta(days=LAG)) <= F.date).all(), "PIT FAIL"
    assert F.date.max() <= HI and F.date.min() >= LO
    dst = CACHE / "dbreadth_factor.parquet"
    F[["ticker", "date", "dbreadth"]].to_parquet(dst, index=False)
    F.to_parquet(CACHE / "dbreadth_build_detail.parquet", index=False)
    K = F[~F.spac_drop]
    cov = {}
    for tier in ("cap150", "cap2000"):
        k = K[K[f"eligible_{tier}"].astype(bool)]
        cov[tier] = {"rows": len(k), "finite_share": float(k.dbreadth.notna().mean()),
                     "permno_share": float(k.permno.notna().mean()),
                     "by_year": {int(y): float(v) for y, v in
                                 k.groupby(k.date.dt.year).dbreadth.apply(lambda s: s.notna().mean()).items()}}
    f150 = K[K.eligible_cap150.astype(bool) & K.dbreadth.notna()]
    qd = f150.dbreadth.quantile([.01, .05, .25, .5, .75, .95, .99])
    rep = {"factor_sha256": sha(dst), "rows": len(F), "lag_days": LAG, "drop_rule": DROP,
           "inputs": {"permno_sharadar_sha256": sha(XWALK), "stocknames_sha256": sha(NAMES),
                      "panel_v2_sha256": sha(PANEL)},
           "flagged_quarters": st.index[st.flag].tolist(),
           "coverage_spac_rule_applied": cov,
           "dist_cap150_finite": {str(k): float(v) for k, v in qd.items()},
           "share_zero_cap150": float((f150.dbreadth == 0).mean()),
           "runtime_s": round(time.time() - t0, 1)}
    (OUT / "dbreadth_build.json").write_text(json.dumps(rep, indent=1, default=str))
    log(json.dumps({k: rep[k] for k in ("factor_sha256", "flagged_quarters", "dist_cap150_finite")}, default=str))
    log(f"coverage cap150 {cov['cap150']['finite_share']:.3f} cap2000 {cov['cap2000']['finite_share']:.3f}")


if __name__ == "__main__":
    main()
