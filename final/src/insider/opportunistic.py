"""
Opportunistic vs routine insider buyers (Cohen, Malloy & Pomorski 2012), as a
point-in-time cross-section for the forward prediction ledger. Spec:
models/2026-09-23-forward-ledger-leverage-opportunistic-buyers.md section 1b.

Definition is posthoc_insider.py's, made causal. At panel date t only events
with filing_date <= t are used, both for the routine key-set and for the
"first purchase >= 3 years earlier" classifiability test.

  routine        same (issuer, owner) O/D P purchase in the same calendar
                 month of each of years y-1, y-2, y-3 (trans_date)
  classifiable   year - first purchase year >= 3
  opportunistic  classifiable and not routine
  unclassifiable not classifiable (excluded from opp_buyers_90, COO ruling)

Counts are distinct O/D owners with a qualifying P filing whose FILING_DATE
is in (t-90d, t]. There is no filing -> 0 for a CIK-mapped ticker; no CIK -> NaN.

Event sources: the bulk Form 345 events (out/insider/insider_events.parquet,
build_insider_panel.py) plus the live refresh
(out/insider/insider_events_live.parquet, scripts/edgar_form4_refresh.py).
"""
from pathlib import Path

import numpy as np
import pandas as pd

MAIN_ROOT = Path("/Users/ggraham/pipe_dream/final")
EVENTS_PATH = MAIN_ROOT / "out" / "insider" / "insider_events.parquet"
LIVE_EVENTS_PATH = MAIN_ROOT / "out" / "insider" / "insider_events_live.parquet"
TICKERS_MASTER = MAIN_ROOT / "data" / "sharadar" / "tickers_master.csv"
WINDOW_DAYS = 90
EVENT_COLS = ["accession", "issuer_cik", "owner_cik", "relationship", "is_od", "is_10pct_only",
              "code", "filing_date", "trans_date", "value", "source_file"]


def load_events(include_live=True):
    parts = [pd.read_parquet(EVENTS_PATH)]
    if include_live and LIVE_EVENTS_PATH.exists():
        parts.append(pd.read_parquet(LIVE_EVENTS_PATH))
    ev = pd.concat([p[EVENT_COLS] for p in parts], ignore_index=True)
    # int64 CIKs on both sources -- a str/int mismatch would silently make
    # every owner look non-routine.
    ev["issuer_cik"] = pd.to_numeric(ev["issuer_cik"], errors="coerce").astype("Int64")
    ev["owner_cik"] = pd.to_numeric(ev["owner_cik"], errors="coerce").astype("Int64")
    ev["filing_date"] = pd.to_datetime(ev["filing_date"])
    ev["trans_date"] = pd.to_datetime(ev["trans_date"])
    ev = ev.dropna(subset=["issuer_cik", "owner_cik", "filing_date"])
    return ev.drop_duplicates(["accession", "owner_cik", "code"]).reset_index(drop=True)


def max_filing_date(ev):
    return pd.Timestamp(ev["filing_date"].max()).normalize()


def cik_map():
    tm = pd.read_csv(TICKERS_MASTER, usecols=["ticker", "secfilings"])
    tm["cik"] = pd.to_numeric(tm["secfilings"].str.extract(r"CIK=0*(\d+)")[0], errors="coerce")
    tm = tm.dropna(subset=["cik"]).astype({"cik": "int64"})[["ticker", "cik"]]
    tm["ticker"] = tm["ticker"].astype(str)
    return tm.drop_duplicates("ticker", keep="first")


def classify_od_buys(ev, asof):
    """O/D P events with filing_date <= asof, each tagged routine/classifiable
    using only that same causal subset."""
    asof = pd.Timestamp(asof)
    b = ev[ev["is_od"].astype(bool) & (ev["code"] == "P") & (ev["filing_date"] <= asof)].copy()
    b["issuer_cik"] = b["issuer_cik"].astype("int64")
    b["owner_cik"] = b["owner_cik"].astype("int64")
    b["y"] = b["trans_date"].dt.year
    b["m"] = b["trans_date"].dt.month
    key = set(zip(b["issuer_cik"], b["owner_cik"], b["y"], b["m"]))
    first_y = b.groupby(["issuer_cik", "owner_cik"])["y"].transform("min")
    b["classifiable"] = (b["y"] - first_y) >= 3          # NaN trans_date -> False
    b["routine"] = [all((c, o, y - k, m) in key for k in (1, 2, 3))
                    for c, o, y, m in zip(b["issuer_cik"], b["owner_cik"], b["y"], b["m"])]
    b["opportunistic"] = b["classifiable"] & ~b["routine"]
    return b


def cross_section_counts(ev, tickers, date, window=WINDOW_DAYS):
    """opp_buyers_90, ins_buyers_90, unclass_buyers_90 for `tickers` on `date`."""
    date = pd.Timestamp(date)
    b = classify_od_buys(ev, date)
    w = b[b["filing_date"] > date - pd.Timedelta(days=window)]
    counts = pd.DataFrame({
        "ins_buyers_90": w.groupby("issuer_cik")["owner_cik"].nunique(),
        "opp_buyers_90": w[w["opportunistic"]].groupby("issuer_cik")["owner_cik"].nunique(),
        "unclass_buyers_90": w[~w["classifiable"]].groupby("issuer_cik")["owner_cik"].nunique(),
    })
    out = pd.DataFrame({"ticker": pd.Series(list(tickers), dtype=str)})
    out = out.merge(cik_map(), on="ticker", how="left")
    for c in ["opp_buyers_90", "ins_buyers_90", "unclass_buyers_90"]:
        v = out["cik"].map(counts[c]).astype(float).fillna(0.0)
        out[c] = v.where(out["cik"].notna())
    return out.drop(columns=["cik"]), w
