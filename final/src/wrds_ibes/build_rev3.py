"""WO-53: build rev3 (CJL 1996 analyst EPS revision, 3-month) on the v2 panel.

FACTOR ONLY. This script never opens a label, return or outcome column. It writes:
  final/out/wrds_ibes/cache/rev3_factor.parquet   (gitignored; ticker, date, rev3 + audit cols)
  final/out/wrds_ibes/rev3_integrity.json          (coverage, funnel, split checks, name checks)

Definition (frozen in final/models/2026-10-08-ibes-revisions.md):
  IBES ticker i, monthly statistical period s1 (statsumu_epsus, measure EPS, fiscalp ANN,
  usfirm 1, curcode USD). FY1 = fpi '1' at s1, fiscal period end E = fpedats.
  s0 = i's statpers in calendar month(s1) - 3. F0 = the s0 consensus mean for the SAME
  fiscal period E (fpi '1' or '2' at s0; matched on fpedats). numest >= 2 at both ends.
  Split basis: k = prod(1 + facshr) over CRSP dsedist distcd 5xxx events of the linked
  permno with s0 < exdt <= s1; F1 is restated to the s0 share basis as F1 * k.
  P0 = Sharadar SEP closeunadj on the last trading day <= s0 (within 7 days), s0 basis.
  rev3 = (F1 * k - F0) / P0.
  At panel date t the value from the latest s1 with s1 < t (strict; first usable on the
  next trading day) and t - s1 <= 45 calendar days is used; else NaN.
  Link: IBES ticker -> permno via wrdsapps.ibcrsphist (score <= 2, sdate <= s1 <= edate);
  permno -> Sharadar ticker via WO-51 final/data/wrds/link/permno_sharadar.parquet
  (valid_from <= date <= valid_to), applied at t for the panel row and at s0 for P0.
"""
import hashlib
import json
import time
from pathlib import Path

import numpy as np
import pandas as pd

DATA = Path("/Users/ggraham/pipe_dream/final/data")
IB = DATA / "wrds" / "ibes"
XWALK = DATA / "wrds" / "link" / "permno_sharadar.parquet"
SEP = DATA / "sharadar" / "panel" / "stocks"
PANEL = Path("/Users/ggraham/pipe_dream/final/out/reset2026/composite_panel_v2.parquet")
PANEL_V1 = Path("/Users/ggraham/pipe_dream/final/out/reset2026/composite_panel.parquet")
TM = DATA / "sharadar" / "tickers_master.csv"
HERE = Path(__file__).resolve().parent
OUT = HERE.parents[1] / "out" / "wrds_ibes"
LO, HI = pd.Timestamp("2007-01-01"), pd.Timestamp("2019-12-31")
HOLDOUT = pd.Timestamp("2020-01-01")
STALE_DAYS = 45
T0 = time.time()


def log(m):
    print(f"[{time.time() - T0:7.1f}s] {m}", flush=True)


def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


# ------------------------------------------------------------------ IBES revisions per (ibes ticker, s1)
def ibes_revisions(meta):
    df = pd.concat([pd.read_parquet(p) for p in sorted(IB.glob("statsumu_epsus_fy12_*.parquet"))], ignore_index=True)
    assert df["statpers"].max() < HOLDOUT
    n_raw = len(df)
    df = df[(df["usfirm"] == 1) & (df["curcode"] == "USD") & (df["fiscalp"] == "ANN")]
    df = df.dropna(subset=["meanest", "fpedats", "numest"])
    df["ym"] = df["statpers"].dt.to_period("M")
    dup = df.duplicated(["ticker", "ym", "fpi"]).sum()
    df = df.sort_values("statpers").drop_duplicates(["ticker", "ym", "fpi"], keep="last")
    meta["ibes"] = {"rows_raw": int(n_raw), "rows_us_usd_ann": int(len(df)), "dup_ticker_month_fpi_dropped": int(dup)}
    f1 = df[df["fpi"] == "1"][["ticker", "statpers", "ym", "fpedats", "meanest", "numest"]].rename(
        columns={"statpers": "s1", "fpedats": "E", "meanest": "F1", "numest": "n1"})
    f1["ym0"] = f1["ym"] - 3
    s0 = df[["ticker", "statpers", "ym", "fpedats", "meanest", "numest", "fpi"]].rename(
        columns={"statpers": "s0", "ym": "ym0", "fpedats": "E", "meanest": "F0", "numest": "n0", "fpi": "fpi0"})
    r = f1.merge(s0, on=["ticker", "ym0", "E"], how="left")
    assert not r.duplicated(["ticker", "s1"]).any()
    has_s0_month = f1.merge(df[["ticker", "ym"]].drop_duplicates().rename(columns={"ym": "ym0"}), on=["ticker", "ym0"], how="inner")
    fun = {"fy1_rows": int(len(f1)), "s0_month_exists": int(len(has_s0_month)),
           "same_E_matched": int(r["F0"].notna().sum()),
           "matched_via_fpi2_rollover": int((r["fpi0"] == "2").sum())}
    # rows failing a filter are KEPT with valid=False so the panel uses the LATEST s1 < t
    # (a failing latest s1 gives NaN; it never falls back to an older statpers)
    r["valid"] = r["F0"].notna() & (r["n1"] >= 2) & (r["n0"] >= 2)
    fun["numest_ge2_both"] = int(r["valid"].sum())
    assert (r.loc[r["F0"].notna(), "s0"] < r.loc[r["F0"].notna(), "s1"]).all()
    meta["ibes_funnel"] = fun
    log(f"IBES revisions: {fun}")
    return r.drop(columns=["ym", "ym0"])


# ------------------------------------------------------------------ link IBES ticker -> permno at s1
def link_permno(r, meta):
    lk = pd.read_parquet(IB / "ibcrsphist.parquet")
    lk = lk[lk["score"] <= 2].dropna(subset=["permno"])
    lk["sdate"] = pd.to_datetime(lk["sdate"]); lk["edate"] = pd.to_datetime(lk["edate"])
    lk["permno"] = lk["permno"].astype(np.int64)
    m = r.merge(lk[["ticker", "permno", "sdate", "edate", "score"]], on="ticker", how="inner")
    m = m[(m["sdate"] <= m["s1"]) & (m["s1"] <= m["edate"])]
    m = m.sort_values(["ticker", "s1", "score", "permno"])
    amb_t = int(m.duplicated(["ticker", "s1"]).sum())
    m = m.drop_duplicates(["ticker", "s1"], keep="first")
    amb_p = m.duplicated(["permno", "s1"], keep=False)
    meta["link_ibes_permno"] = {"rows_linked": int(len(m)), "ibes_ticker_multi_permno_dropped_extra": amb_t,
                                "permno_multi_ibes_ticker_rows_dropped": int(amb_p.sum()),
                                "unlinked_rows": int(len(r) - len(m) - amb_t)}
    m = m[~amb_p].drop(columns=["sdate", "edate"])
    log(f"link ibes->permno: {meta['link_ibes_permno']}")
    return m.rename(columns={"ticker": "ibes_ticker"})


# ------------------------------------------------------------------ split basis (CRSP distcd 5xxx)
def split_factor(m, meta):
    ev = pd.read_parquet(IB / "crsp_dsedist_facshr.parquet")
    ev = ev[ev["distcd"].astype(int).astype(str).str[0] == "5"][["permno", "exdt", "facshr"]]
    ev["permno"] = ev["permno"].astype(np.int64)
    ev = ev.groupby(["permno", "exdt"], as_index=False)["facshr"].sum()
    x = m[["permno", "s0", "s1"]].reset_index().merge(ev, on="permno", how="inner")
    x = x[(x["exdt"] > x["s0"]) & (x["exdt"] <= x["s1"])]
    assert (x["exdt"] < HOLDOUT).all()
    k = x.groupby("index")["facshr"].apply(lambda s: float(np.prod(1.0 + s.to_numpy())))
    m["k"] = 1.0
    m.loc[k.index, "k"] = k.to_numpy()
    m["split_in_window"] = m.index.isin(k.index)
    # extended exclusion window (s0 - 35d, s1]: IBES may lag a split by up to a monthly cycle
    xe = m[["permno", "s0", "s1"]].reset_index().merge(ev, on="permno", how="inner")
    xe = xe[(xe["exdt"] > xe["s0"] - pd.Timedelta(days=35)) & (xe["exdt"] <= xe["s1"])]
    m["split_ext"] = m.index.isin(xe["index"].unique())
    meta["splits"] = {"rows_with_split_in_window": int(m["split_in_window"].sum()),
                      "share": float(m["split_in_window"].mean()),
                      "k_quantiles": m.loc[m["split_in_window"], "k"].quantile([0, .05, .5, .95, 1]).round(4).tolist()}
    log(f"splits: {meta['splits']}")
    return m


# ------------------------------------------------------------------ Sharadar prices
def load_xwalk():
    x = pd.read_parquet(XWALK)
    x["valid_from"] = pd.to_datetime(x["valid_from"]); x["valid_to"] = pd.to_datetime(x["valid_to"])
    x["permno"] = x["permno"].astype(np.int64); x["ticker"] = x["ticker"].astype(str)
    return x[["permno", "ticker", "valid_from", "valid_to"]]


def interval_join(left, key, datecol, x, out_col):
    """left[key] at left[datecol] -> x[out_col] where valid_from <= date <= valid_to; ambiguous -> dropped."""
    j = left[[key, datecol]].reset_index().merge(x, on=key, how="inner")
    j = j[(j["valid_from"] <= j[datecol]) & (j[datecol] <= j["valid_to"])]
    amb = j["index"].duplicated(keep=False)
    j = j[~amb]
    s = pd.Series(np.nan, index=left.index, dtype=object)
    s.loc[j["index"].to_numpy()] = j[out_col].to_numpy()
    return s, int(amb.sum())


def attach_price(m, meta):
    x = load_xwalk()
    m["sh_ticker_s0"], amb = interval_join(m, "permno", "s0", x, "ticker")
    need = set(m["sh_ticker_s0"].dropna())
    months = pd.period_range(m["s0"].min().to_period("M") - 1, m["s0"].max().to_period("M"), freq="M")
    px = []
    for p in months:
        f = SEP / f"{p}.parquet"
        assert p.end_time < HOLDOUT, "HOLD-OUT BREACH (SEP month)"
        d = pd.read_parquet(f, columns=["ticker", "date", "close", "closeunadj"])
        px.append(d[d["ticker"].isin(need)])
    px = pd.concat(px, ignore_index=True)
    px["date"] = pd.to_datetime(px["date"]).astype("datetime64[ns]")
    px["ticker"] = px["ticker"].astype(object)
    px = px[(px["closeunadj"] > 0) & (px["close"] > 0)].sort_values("date")
    q = m[["sh_ticker_s0", "s0"]].dropna().reset_index().sort_values("s0")
    q["s0"] = q["s0"].astype("datetime64[ns]")
    q = pd.merge_asof(q, px.rename(columns={"ticker": "sh_ticker_s0", "date": "pdate"}),
                      left_on="s0", right_on="pdate", by="sh_ticker_s0", direction="backward",
                      tolerance=pd.Timedelta(days=7))
    q = q.set_index("index")
    m["pdate0"] = q["pdate"]; m["P0"] = q["closeunadj"]; m["adjc0"] = q["close"]
    assert (m["pdate0"].dropna() <= m.loc[m["pdate0"].notna(), "s0"]).all(), "price after s0"
    # diagnostic: SEP-implied split ratio between s0 and s1 vs CRSP k
    q1 = m[["sh_ticker_s0", "s1"]].dropna().reset_index().sort_values("s1")
    q1["s1"] = q1["s1"].astype("datetime64[ns]")
    q1 = pd.merge_asof(q1, px.rename(columns={"ticker": "sh_ticker_s0", "date": "pdate1"}),
                       left_on="s1", right_on="pdate1", by="sh_ticker_s0", direction="backward",
                       tolerance=pd.Timedelta(days=7)).set_index("index")
    c0 = m["P0"] / m["adjc0"]
    c1 = q1["closeunadj"] / q1["close"]
    sep_k = (c0 / c1.reindex(m.index))
    ok = sep_k.notna()
    agree = np.isclose(sep_k[ok], m.loc[ok, "k"], rtol=0.02)
    meta["price"] = {"permno_to_sharadar_at_s0_ambiguous_dropped": amb,
                     "rows_with_sharadar_ticker_s0": int(m["sh_ticker_s0"].notna().sum()),
                     "rows_with_P0": int(m["P0"].notna().sum()),
                     "sep_vs_crsp_split_ratio_agree_2pct": float(agree.mean()),
                     "agree_on_split_rows": float(np.isclose(sep_k[ok & m["split_in_window"]],
                                                             m.loc[ok & m["split_in_window"], "k"], rtol=0.02).mean()),
                     "sep_split_but_crsp_none": int(((~np.isclose(sep_k[ok], 1.0, rtol=0.02)) & (m.loc[ok, "k"] == 1.0)).sum())}
    m["sep_k"] = sep_k
    log(f"price: {meta['price']}")
    return m


# ------------------------------------------------------------------ panel mapping
def load_grid():
    p = pd.read_parquet(PANEL, columns=["ticker", "date", "eligible_cap150", "momentum_12_1"],
                        filters=[("date", ">=", "2007-01-01"), ("date", "<=", "2019-12-31")])
    p["date"] = pd.to_datetime(p["date"]); p["ticker"] = p["ticker"].astype(str)
    assert p["date"].max() < HOLDOUT
    old_t = set(pd.read_parquet(PANEL_V1, columns=["ticker"])["ticker"].astype(str).unique())
    tm = pd.read_csv(TM, dtype=str, usecols=["ticker", "sicindustry"]).drop_duplicates("ticker")
    spac = set(tm.loc[tm["sicindustry"].fillna("").str.contains("Blank Check"), "ticker"])
    p = p[p["ticker"].isin(old_t) | ~p["ticker"].isin(spac)]
    p["cap150"] = p["eligible_cap150"].astype(bool)
    p["added"] = ~p["ticker"].isin(old_t)
    return p.drop(columns=["eligible_cap150"]).reset_index(drop=True)


def map_panel(m, meta):  # noqa: C901
    g = load_grid()
    x = load_xwalk()
    # Sharadar ticker -> permno at t
    s, amb = interval_join(g, "ticker", "date", x, "permno")
    g["permno"] = pd.to_numeric(s)
    meta["panel_map"] = {"panel_rows_2007_2019": int(len(g)), "cap150_rows": int(g["cap150"].sum()),
                         "sharadar_to_permno_ambiguous_rows": amb,
                         "cap150_rows_with_permno": int((g["cap150"] & g["permno"].notna()).sum())}
    v = m[["permno", "s1", "s0", "rev3", "F1", "F0", "k", "P0", "n1", "n0", "ibes_ticker", "E", "fpi0", "split_in_window", "rev3_kadj", "basis_change"]]
    v = v.sort_values("s1")
    q = g[g["permno"].notna()][["permno", "date"]].reset_index()
    q["permno"] = q["permno"].astype(np.int64)
    q = q.sort_values("date")
    q["date"] = q["date"].astype("datetime64[ns]")
    v["s1"] = v["s1"].astype("datetime64[ns]")
    # strict: s1 < t (allow_exact_matches=False) -> usable from the next trading day
    j = pd.merge_asof(q, v, left_on="date", right_on="s1", by="permno", direction="backward",
                      allow_exact_matches=False, tolerance=pd.Timedelta(days=STALE_DAYS))
    j = j.set_index("index")
    for c in ["rev3", "s1", "s0", "F1", "F0", "k", "P0", "n1", "n0", "ibes_ticker", "E", "fpi0", "split_in_window", "rev3_kadj", "basis_change"]:
        g[c] = j[c].reindex(g.index)
    ok = g["s1"].notna()
    assert (g.loc[ok, "s1"] < g.loc[ok, "date"]).all(), "PIT: s1 >= t"
    ok0 = ok & g["s0"].notna()
    assert (g.loc[ok0, "s0"] < g.loc[ok0, "s1"]).all()
    assert ((g.loc[ok, "date"] - g.loc[ok, "s1"]).dt.days <= STALE_DAYS).all()
    # IBES can move to the new share basis before the ex-date (split_lead_check): also NaN any
    # row with a CRSP distcd-5 event in (s1, t]. PIT: every such exdt is <= t.
    ev = pd.read_parquet(IB / "crsp_dsedist_facshr.parquet")
    ev = ev[ev["distcd"].astype(int) // 1000 == 5][["permno", "exdt"]]
    ev["permno"] = ev["permno"].astype(float)
    x = g.loc[ok, ["permno", "s1", "date"]].reset_index().merge(ev, on="permno", how="inner")
    x = x[(x["exdt"] > x["s1"]) & (x["exdt"] <= x["date"])]
    assert (x["exdt"] < HOLDOUT).all()
    g["split_lead"] = g.index.isin(x["index"].unique())
    meta["split_lead_rows_excluded_cap150"] = int((g["split_lead"] & g["cap150"] & g["rev3"].notna()).sum())
    g.loc[g["split_lead"], "rev3"] = np.nan
    g["basis_change"] = g["basis_change"].fillna(False).astype(bool) | g["split_lead"]
    return g


def main():
    meta = {"work_order": "WO-53", "factor": "rev3", "built": time.strftime("%Y-%m-%d %H:%M"),
            "inputs": {"permno_sharadar_sha256": sha(XWALK), "panel_v2_sha256": sha(PANEL),
                       "xwalk_mtime": time.strftime("%Y-%m-%d %H:%M", time.localtime(XWALK.stat().st_mtime))}}
    r = ibes_revisions(meta)
    m = link_permno(r, meta)
    m = split_factor(m.reset_index(drop=True), meta)
    m = attach_price(m, meta)
    m["rev3_kadj"] = ((m["F1"] * m["k"] - m["F0"]) / m["P0"]).where(m["valid"])
    m.loc[~np.isfinite(m["rev3_kadj"]), "rev3_kadj"] = np.nan
    # frozen rule: no share-basis change allowed in the window -> NaN (no split adjustment is ever used)
    m["basis_change"] = m["split_ext"] | (m["sep_k"].notna() & ~np.isclose(m["sep_k"].fillna(1.0), 1.0, rtol=0.02))
    m["rev3"] = m["rev3_kadj"].where(~m["basis_change"])
    meta["basis_change_excluded_ibes_rows"] = int((m["basis_change"] & m["rev3_kadj"].notna()).sum())
    g = map_panel(m, meta)
    OUT.joinpath("cache").mkdir(parents=True, exist_ok=True)
    keep = ["ticker", "date", "rev3", "permno", "ibes_ticker", "s1", "s0", "E", "fpi0", "F1", "F0", "k", "P0", "n1", "n0",
            "split_in_window", "rev3_kadj", "basis_change", "cap150", "added"]
    g[keep].to_parquet(OUT / "cache" / "rev3_factor.parquet", index=False)
    m.to_parquet(OUT / "cache" / "rev3_ibes_level.parquet", index=False)
    c = g[g["cap150"]]
    fin = c["rev3"].notna()
    yr = c["date"].dt.year
    meta["coverage_cap150"] = {
        "rows": int(len(c)), "tickers": int(c["ticker"].nunique()), "dates": int(c["date"].nunique()),
        "finite_rev3": float(fin.mean()),
        "finite_old_grid": float(fin[~c["added"]].mean()), "finite_added": float(fin[c["added"]].mean()),
        "with_permno": float(c["permno"].notna().mean()),
        "by_year": {int(y): round(float(v), 4) for y, v in fin.groupby(yr).mean().items()},
        "rollover_matched_via_fpi2_share": float((c.loc[fin, "fpi0"] == "2").mean()),
        "basis_change_excluded_share_of_cap150": float(c["basis_change"].fillna(False).astype(bool).mean()),
        "finite_rev3_kadj_before_exclusion": float(c["rev3_kadj"].notna().mean()),
        "rev3_quantiles_1_5_25_50_75_95_99": c.loc[fin, "rev3"].quantile([.01, .05, .25, .5, .75, .95, .99]).round(5).tolist(),
        "share_exact_zero": float((c.loc[fin, "rev3"] == 0).mean()),
        "staleness_days_median": float((c.loc[fin, "date"] - c.loc[fin, "s1"]).dt.days.median()),
    }
    log(f"coverage cap150: {json.dumps(meta['coverage_cap150'])[:900]}")
    (OUT / "rev3_integrity.json").write_text(json.dumps(meta, indent=1, default=str))


if __name__ == "__main__":
    main()
