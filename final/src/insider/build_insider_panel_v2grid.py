"""
WO-4: `ins_buyers_90` on the survivorship-safe v2 down-cap grid.
Spec: models/2026-09-24-insider-buyers-v2-grid.md (pre-registered first).

Reuses build_insider_panel.py by import (load_events, window_counts,
WINDOW_DAYS); that file is owned by WO-8 and is not edited here. Only
`ins_buyers_90` is built. Events are rebuilt from the raw Form 345 zips, so
the shared out/insider/insider_events.parquet (being rewritten by WO-8) is
never read.

Hold-out: every frame is cut to <= 2019-12-31 and asserted.

Outputs (new files only):
    out/insider/insider_features_v2grid.parquet   ticker, date, ins_buyers_90
    out/insider/insider_v2grid_integrity.json     integrity checks
Usage: python3 build_insider_panel_v2grid.py
"""
import json
import sys
import time
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import build_insider_panel as B  # noqa: E402

MAIN = Path("/Users/ggraham/pipe_dream/final")
R26 = MAIN / "out" / "reset2026"
PANEL_V2 = R26 / "composite_panel_v2.parquet"
PANEL_V1 = R26 / "composite_panel.parquet"
OLD_FEAT = MAIN / "out" / "insider" / "insider_features.parquet"
TM = MAIN / "data" / "sharadar" / "tickers_master.csv"
OUT_FEAT = MAIN / "out" / "insider" / "insider_features_v2grid.parquet"
OUT_INTEG = MAIN / "out" / "insider" / "insider_v2grid_integrity.json"
EVENTS_CACHE = Path("/tmp/wo4_insider_events_from_zips.parquet")
HOLDOUT = pd.Timestamp("2020-01-01")
END = "2019-12-31"
A1_NAMES = ["ANIK", "NGS", "WTBA", "NRIM", "ACHN"]


def log(m):
    print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)


def guard(df):
    assert df["date"].max() < HOLDOUT, "HOLD-OUT BREACH"
    return df


def cik_map_dedup():
    tm = pd.read_csv(TM, usecols=["ticker", "secfilings"], dtype=str)
    tm["cik"] = pd.to_numeric(tm["secfilings"].str.extract(r"CIK=0*(\d+)")[0], errors="coerce")
    tm = tm.sort_values(["ticker", "cik"], na_position="last").drop_duplicates("ticker", keep="first")
    tm = tm.dropna(subset=["cik"]).astype({"cik": "int64"})[["ticker", "cik"]]
    assert tm["ticker"].is_unique
    return tm


def load_events_cached():
    if EVENTS_CACHE.exists():
        return pd.read_parquet(EVENTS_CACHE)
    ev = B.load_events()
    ev.to_parquet(EVENTS_CACHE, index=False)
    return ev


def build(panel, ev, cmap):
    n0 = len(panel)
    panel = panel.merge(cmap, on="ticker", how="left")
    assert len(panel) == n0, "CIK merge changed row count"
    od = ev[ev["is_od"] & (ev["code"] == "P")].copy()
    od["fday"] = (od["filing_date"] - pd.Timestamp("1970-01-01")).dt.days.astype(np.int64)
    od["issuer_cik"] = od["issuer_cik"].astype("int64")
    buys = {k: g for k, g in od.groupby("issuer_cik")}
    out = np.full(len(panel), np.nan)
    dint = (panel["date"] - pd.Timestamp("1970-01-01")).dt.days.to_numpy(np.int64)
    for cik, idx in panel.groupby("cik").indices.items():
        idx = np.asarray(idx)
        out[idx] = 0.0
        if cik in buys:
            out[idx] = B.window_counts(buys[cik], dint[idx], B.WINDOW_DAYS)
    panel["ins_buyers_90"] = out
    return panel


def dimon_check(ev, feat):
    """Find Dimon's 2016 JPM purchase in the raw 2016q1 zip by owner name."""
    z = B.RAW_DIR / "2016q1_form345.zip"
    with zipfile.ZipFile(z) as zf:
        own = B._read(zf, "REPORTINGOWNER.tsv", ["ACCESSION_NUMBER", "RPTOWNERCIK", "RPTOWNERNAME"])
    d = own[own["RPTOWNERNAME"].fillna("").str.contains("Dimon", case=False)]
    acc = set(d["ACCESSION_NUMBER"])
    e = ev[ev["accession"].isin(acc) & (ev["code"] == "P")]
    rows = e[["accession", "issuer_cik", "owner_cik", "filing_date", "value", "is_od"]].astype(str).to_dict("records")
    s = feat[feat["ticker"] == "JPM"].set_index("date")["ins_buyers_90"]
    win = s.loc["2016-02-05":"2016-02-16"]
    step = float(s.get(pd.Timestamp("2016-02-11"), np.nan) - s.get(pd.Timestamp("2016-02-10"), np.nan))
    return {"raw_zip_rows": rows, "jpm_ins_buyers_90_2016-02-05..16": {str(k.date()): float(v) for k, v in win.items()},
            "step_on_2016-02-11": step, "pass": bool(len(rows) > 0 and step >= 1)}


def named_ticker_buys(ev, feat, cmap, tickers, n_each=2):
    """For each ticker, the first O/D P filings in 2007-2019 from the raw
    events, and the ins_buyers_90 step on the first panel date on/after the
    filing date (vs the prior panel date)."""
    res = {}
    for t in tickers:
        cik = cmap.loc[cmap["ticker"] == t, "cik"]
        if cik.empty:
            res[t] = {"cik": None}; continue
        cik = int(cik.iloc[0])
        e = ev[(ev["issuer_cik"] == cik) & ev["is_od"] & (ev["code"] == "P")
               & (ev["filing_date"] >= "2007-01-02") & (ev["filing_date"] <= END)].sort_values("filing_date")
        s = feat[feat["ticker"] == t].set_index("date")["ins_buyers_90"].sort_index()
        checks = []
        for _, r in e.drop_duplicates("filing_date").head(n_each).iterrows():
            after = s.index[s.index >= r["filing_date"]]
            before = s.index[s.index < r["filing_date"]]
            if len(after) == 0 or len(before) == 0:
                continue
            d1, d0 = after[0], before[-1]
            checks.append({"accession": r["accession"], "filing_date": str(r["filing_date"].date()),
                           "trans_date": str(r["trans_date"].date()) if pd.notna(r["trans_date"]) else None,
                           "value": float(r["value"]) if pd.notna(r["value"]) else None,
                           "panel_date": str(d1.date()), "prev": float(s[d0]), "on": float(s[d1]),
                           "step_up": bool(s[d1] > s[d0])})
        res[t] = {"cik": cik, "n_od_P_filings_2007_2019": int(e["accession"].nunique()), "checks": checks}
    return res


def main():
    t0 = time.time()
    rep = {}
    log("events from raw zips (build_insider_panel.load_events) ...")
    ev = load_events_cached()
    log(f"events {len(ev):,}")
    cmap = cik_map_dedup()
    rep["cik_map"] = {"tickers_with_cik": int(len(cmap)), "one_cik_per_ticker": True}

    cols = ["ticker", "date", "eligible_cap150", "eligible_cap500", "eligible_cap2000"]
    panel = pd.read_parquet(PANEL_V2, columns=cols, filters=[("date", "<=", END)])
    panel["ticker"] = panel["ticker"].astype(str); panel["date"] = pd.to_datetime(panel["date"])
    panel = guard(panel).reset_index(drop=True)
    assert not panel.duplicated(["ticker", "date"]).any()
    n0 = len(panel)
    log(f"v2 panel <=2019: {n0:,} rows, {panel['ticker'].nunique():,} tickers")
    feat = build(panel, ev, cmap)
    assert len(feat) == n0
    rep["panel_rows"] = {"before_merge": n0, "after_merge": int(len(feat))}

    # --- coverage & fire rate: old vs added, mutually exclusive cap bands, 2007-2019
    old_t = set(pd.read_parquet(PANEL_V1, columns=["ticker"])["ticker"].astype(str).unique())
    tm = pd.read_csv(TM, dtype=str, usecols=["ticker", "sicindustry"]).drop_duplicates("ticker")
    spac = set(tm.loc[tm["sicindustry"].fillna("").str.contains("Blank Check"), "ticker"])
    f = feat[feat["date"] >= "2007-01-02"]
    grp = np.where(f["ticker"].isin(old_t), "old", np.where(f["ticker"].isin(spac), "added_spac", "added"))
    band = np.select([f["eligible_cap2000"], f["eligible_cap500"], f["eligible_cap150"]],
                     ["cap2000", "cap500_not_2000", "cap150_not_500"], "not_cap150")
    t = pd.DataFrame({"g": grp, "band": band, "mapped": f["ins_buyers_90"].notna(),
                      "fire": f["ins_buyers_90"] > 0, "cluster": f["ins_buyers_90"] >= 2})
    cov = t.groupby(["g", "band"]).agg(rows=("mapped", "size"), cik_mapped=("mapped", "mean"),
                                        fire_rate=("fire", "mean"), cluster2_rate=("cluster", "mean"))
    # fire rate among mapped rows only
    cov["fire_rate_mapped"] = t[t["mapped"]].groupby(["g", "band"])["fire"].mean()
    log("coverage/fire by group x band:\n" + cov.to_string())
    rep["coverage_fire"] = {f"{g}|{b}": {k: float(v) for k, v in r.items()} for (g, b), r in cov.iterrows()}
    c150 = t[f["eligible_cap150"].to_numpy() & (t["g"] != "added_spac")]
    rep["coverage_fire_cap150_all"] = {g: {"rows": int(len(s)), "cik_mapped": float(s["mapped"].mean()),
                                          "fire_rate": float(s["fire"].mean())} for g, s in c150.groupby("g")}
    log(f"cap150 all bands: {rep['coverage_fire_cap150_all']}")

    # --- named checks
    rep["named_dimon_jpm"] = dimon_check(ev, feat)
    log(f"Dimon: {json.dumps(rep['named_dimon_jpm'])[:600]}")
    rep["named_old_tickers"] = named_ticker_buys(ev, feat, cmap, ["JPM", "XOM"], 1)
    rep["named_added_A1"] = named_ticker_buys(ev, feat, cmap, A1_NAMES, 2)
    for t_, v in rep["named_added_A1"].items():
        log(f"A1 {t_}: {json.dumps(v)[:500]}")
    assert all(not (tk in old_t) for tk in A1_NAMES)

    # --- reconcile vs the old insider_features.parquet on column b cap150 rows
    old = pd.read_parquet(OLD_FEAT, columns=["ticker", "date", "ins_buyers_90"])
    old["ticker"] = old["ticker"].astype(str); old["date"] = pd.to_datetime(old["date"])
    old = old[old["date"] <= END]
    dup = int(old.duplicated(["ticker", "date"]).sum())
    rep["old_file_duplicate_keys"] = dup
    old = old.drop_duplicates(["ticker", "date"])
    b = feat[feat["ticker"].isin(old_t) & feat["eligible_cap150"] & (feat["date"] >= "2007-01-02")]
    m = b.merge(old, on=["ticker", "date"], how="inner", suffixes=("", "_old"))
    both_nan = m["ins_buyers_90"].isna() & m["ins_buyers_90_old"].isna()
    eq = (m["ins_buyers_90"] == m["ins_buyers_90_old"]) | both_nan
    rep["reconcile_column_b_cap150"] = {"rows_col_b_cap150": int(len(b)), "rows_matched_to_old": int(len(m)),
                                        "mismatches": int((~eq).sum()), "mismatch_rate": float((~eq).mean()),
                                        "mismatch_tickers": m.loc[~eq, "ticker"].value_counts().head(10).to_dict()}
    log(f"reconcile: {rep['reconcile_column_b_cap150']}  (old dup keys {dup})")

    OUT_INTEG.write_text(json.dumps(rep, indent=2, default=str))
    feat[["ticker", "date", "ins_buyers_90"]].to_parquet(OUT_FEAT, index=False)
    log(f"wrote {OUT_FEAT} and {OUT_INTEG} ({time.time()-t0:.0f}s)")


if __name__ == "__main__":
    main()
