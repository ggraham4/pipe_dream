"""
Insider-trading columns from the SEC "Insider Transactions Data Sets"
(structured Form 3/4/5, quarterly zips under data/edgar/form345/). Spec:
models/2026-09-23-insider-congress-preregistration.md -- read it first.

Availability is FILING_DATE (not TRANS_DATE). Issuer join is ISSUERCIK ->
tickers_master.secfilings CIK, never the reported trading symbol. Only
non-derivative P (buy) and S (sell) codes by officer/director owners on
original Form 4s. No filing -> 0, not NaN, for every CIK-mapped name.

Counting distinct owners in a trailing window uses interval arithmetic, not
merge_asof: an owner's filing at f covers panel dates t with f <= t < f+W.
Per (cik, owner) the covering intervals are unioned, and the count at t is
#starts<=t - #ends<=t (Round 16's merge_asof index-reset bug cannot occur).

OUTPUTS
    out/insider/insider_events.parquet   one row per (filing, owner, code)
    out/insider/insider_features.parquet ticker, date + feature columns on
                                         the composite panel's grid
Usage: python3 build_insider_panel.py
"""
import glob
import time
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

MAIN_ROOT = Path("/Users/ggraham/pipe_dream/final")
RAW_DIR = MAIN_ROOT / "data" / "edgar" / "form345"
TICKERS_MASTER = MAIN_ROOT / "data" / "sharadar" / "tickers_master.csv"
PANEL = MAIN_ROOT / "out" / "reset2026" / "composite_panel.parquet"
OUT_DIR = MAIN_ROOT / "out" / "insider"
EVENTS_OUT = OUT_DIR / "insider_events.parquet"
FEAT_OUT = OUT_DIR / "insider_features.parquet"

WINDOW_DAYS = 90


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def _read(zf, name, cols):
    with zf.open(name) as fh:
        return pd.read_csv(fh, sep="\t", usecols=cols, dtype=str, quoting=3, on_bad_lines="skip")


def load_events():
    rows = []
    for path in sorted(glob.glob(str(RAW_DIR / "*_form345.zip"))):
        with zipfile.ZipFile(path) as zf:
            sub = _read(zf, "SUBMISSION.tsv", ["ACCESSION_NUMBER", "FILING_DATE", "DOCUMENT_TYPE", "ISSUERCIK"])
            own = _read(zf, "REPORTINGOWNER.tsv", ["ACCESSION_NUMBER", "RPTOWNERCIK", "RPTOWNER_RELATIONSHIP"])
            tr = _read(zf, "NONDERIV_TRANS.tsv", ["ACCESSION_NUMBER", "TRANS_DATE", "TRANS_CODE",
                                                  "TRANS_SHARES", "TRANS_PRICEPERSHARE"])
        sub = sub[sub["DOCUMENT_TYPE"] == "4"]
        tr = tr[tr["TRANS_CODE"].isin(["P", "S"])]
        tr = tr.assign(value=pd.to_numeric(tr["TRANS_SHARES"], errors="coerce")
                       * pd.to_numeric(tr["TRANS_PRICEPERSHARE"], errors="coerce"))
        tr = (tr.groupby(["ACCESSION_NUMBER", "TRANS_CODE"], as_index=False)
                .agg(value=("value", "sum"), trans_date=("TRANS_DATE", "min")))
        rel = own["RPTOWNER_RELATIONSHIP"].fillna("")
        own = own.assign(is_od=rel.str.contains("Officer|Director", regex=True),
                         is_10pct_only=rel.str.contains("TenPercentOwner") & ~rel.str.contains("Officer|Director"))
        df = tr.merge(sub, on="ACCESSION_NUMBER").merge(own, on="ACCESSION_NUMBER")
        df["source_file"] = Path(path).name
        rows.append(df)
        log(f"  {Path(path).name}: {len(df):,} owner-code rows")
    ev = pd.concat(rows, ignore_index=True)
    ev["filing_date"] = pd.to_datetime(ev["FILING_DATE"], format="%d-%b-%Y", errors="coerce")
    ev["trans_date"] = pd.to_datetime(ev["trans_date"], format="%d-%b-%Y", errors="coerce")
    ev["issuer_cik"] = pd.to_numeric(ev["ISSUERCIK"], errors="coerce").astype("Int64")
    ev["owner_cik"] = pd.to_numeric(ev["RPTOWNERCIK"], errors="coerce").astype("Int64")
    ev = ev.rename(columns={"TRANS_CODE": "code", "ACCESSION_NUMBER": "accession",
                            "RPTOWNER_RELATIONSHIP": "relationship"})
    ev = ev[["accession", "issuer_cik", "owner_cik", "relationship", "is_od", "is_10pct_only",
             "code", "filing_date", "trans_date", "value", "source_file"]]
    # the quarterly sets can overlap at their boundaries; one row per accession/owner/code
    ev = ev.dropna(subset=["filing_date", "issuer_cik", "owner_cik"]).drop_duplicates(
        ["accession", "owner_cik", "code"])
    return ev.reset_index(drop=True)


def cik_map():
    tm = pd.read_csv(TICKERS_MASTER, usecols=["ticker", "secfilings"])
    tm["cik"] = pd.to_numeric(tm["secfilings"].str.extract(r"CIK=0*(\d+)")[0], errors="coerce")
    return tm.dropna(subset=["cik"]).astype({"cik": "int64"})[["ticker", "cik"]]


def window_counts(ev_cik, dates_int, window):
    """Distinct owners with a filing in (t-window, t] for each t in dates_int
    (days since epoch, sorted). ev_cik: rows with owner_cik, fday."""
    starts, ends = [], []
    for _, g in ev_cik.groupby("owner_cik", sort=False):
        f = np.sort(g["fday"].to_numpy())
        # union of [f, f+window) intervals for this owner
        s0, e0 = f[0], f[0] + window
        for x in f[1:]:
            if x <= e0:
                e0 = x + window
            else:
                starts.append(s0); ends.append(e0)
                s0, e0 = x, x + window
        starts.append(s0); ends.append(e0)
    starts = np.sort(np.asarray(starts)); ends = np.sort(np.asarray(ends))
    return (np.searchsorted(starts, dates_int, side="right")
            - np.searchsorted(ends, dates_int, side="right"))


def window_sum(ev_cik, dates_int, window, col):
    f = ev_cik["fday"].to_numpy(); v = np.nan_to_num(ev_cik[col].to_numpy(np.float64))
    o = np.argsort(f); f = f[o]; c = np.concatenate([[0.0], np.cumsum(v[o])])
    hi = np.searchsorted(f, dates_int, side="right")
    lo = np.searchsorted(f, dates_int - window, side="right")
    return c[hi] - c[lo]


def main():
    t0 = time.time()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    log("reading SEC Form 345 zips ...")
    ev = load_events()
    ev.to_parquet(EVENTS_OUT, index=False)
    log(f"events: {len(ev):,} rows -> {EVENTS_OUT}")

    panel = pd.read_parquet(PANEL, columns=["ticker", "date"])
    panel["ticker"] = panel["ticker"].astype(str)
    panel["date"] = pd.to_datetime(panel["date"])
    cmap = cik_map()
    panel = panel.merge(cmap, on="ticker", how="left")
    log(f"panel {len(panel):,} rows; CIK known for {panel['cik'].notna().mean():.4%}")

    od = ev[ev["is_od"]].copy()
    od["fday"] = (od["filing_date"] - pd.Timestamp("1970-01-01")).dt.days.astype(np.int64)
    od["issuer_cik"] = od["issuer_cik"].astype("int64")
    buys = {k: g for k, g in od[od["code"] == "P"].groupby("issuer_cik")}
    sells = {k: g for k, g in od[od["code"] == "S"].groupby("issuer_cik")}

    out_cols = {c: np.full(len(panel), np.nan) for c in
                ["ins_buyers_90", "ins_sellers_90", "ins_buy_value_90", "ins_sell_value_90"]}
    panel = panel.reset_index(drop=True)
    dint_all = (panel["date"] - pd.Timestamp("1970-01-01")).dt.days.to_numpy(np.int64)
    for cik, idx in panel.groupby("cik").indices.items():
        idx = np.asarray(idx)
        d = dint_all[idx]
        for c in out_cols:
            out_cols[c][idx] = 0.0
        if cik in buys:
            out_cols["ins_buyers_90"][idx] = window_counts(buys[cik], d, WINDOW_DAYS)
            out_cols["ins_buy_value_90"][idx] = window_sum(buys[cik], d, WINDOW_DAYS, "value")
        if cik in sells:
            out_cols["ins_sellers_90"][idx] = window_counts(sells[cik], d, WINDOW_DAYS)
            out_cols["ins_sell_value_90"][idx] = window_sum(sells[cik], d, WINDOW_DAYS, "value")
    for c, v in out_cols.items():
        panel[c] = v
    panel["ins_cluster_buy_90"] = (panel["ins_buyers_90"] >= 2).astype(float).where(panel["ins_buyers_90"].notna())
    panel.drop(columns=["cik"]).to_parquet(FEAT_OUT, index=False)
    log(f"features -> {FEAT_OUT} ({time.time()-t0:.0f}s)")


if __name__ == "__main__":
    main()
