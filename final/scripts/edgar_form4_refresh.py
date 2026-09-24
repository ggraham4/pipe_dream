"""
Live Form 4 refresh for the forward prediction ledger (WO-3, 2026-09-23).
Spec: final/models/2026-09-23-forward-ledger-leverage-opportunistic-buyers.md.

SEC's quarterly "Insider Transactions Data Sets" (data/edgar/form345/) lag by a
quarter or more. This script fills the gap from EDGAR directly. It reads the
daily form index (Archives/edgar/daily-index/YYYY/QTRn/form.YYYYMMDD.idx),
keeps original Form 4s ("4" only, not "4/A"), and then fetches each filing's
complete submission text to parse the ownershipDocument XML. The output rows
use the same schema as out/insider/insider_events.parquet (see
src/insider/build_insider_panel.py): one row per (accession, owner, code) for
codes P/S, value = sum(shares*price), and trans_date = the earliest transaction
date in the filing.

Scope. Only filings where one of the CIKs listed in the index belongs to a
ticker that was cap150-eligible on any composite-panel date in the last 400
days. That's the ledger's universe, and it keeps the request count down.
Filings are listed under both the issuer and the reporting owner(s), so the
match is on either one. Classification uses the issuer CIK in the XML.

Resumable. Processed index days and fetched accessions are recorded in
out/insider/form4_refresh_state/. A rerun skips them and continues. Retries on
RemoteDisconnected / IncompleteRead / URLError / timeouts / 429 / 5xx.
Rate: <= ~8 req/s (SEC fair-access limit is 10).

Usage (run from anywhere):
  python3 edgar_form4_refresh.py                  # from the day after the bulk
                                                  # data's last filing, to today
  python3 edgar_form4_refresh.py --start 2026-04-01 --end 2026-09-23
  python3 edgar_form4_refresh.py --validate       # parse 2026-03-02..06 into a
                                                  # scratch file and diff it
                                                  # against the bulk events
"""
import argparse
import http.client
import json
import re
import socket
import sys
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

import pandas as pd

MAIN_ROOT = Path("/Users/ggraham/pipe_dream/final")
BULK_EVENTS = MAIN_ROOT / "out" / "insider" / "insider_events.parquet"
LIVE_EVENTS = MAIN_ROOT / "out" / "insider" / "insider_events_live.parquet"
STATE_DIR = MAIN_ROOT / "out" / "insider" / "form4_refresh_state"
PANEL = MAIN_ROOT / "out" / "reset2026" / "composite_panel.parquet"
TICKERS_MASTER = MAIN_ROOT / "data" / "sharadar" / "tickers_master.csv"

USER_AGENT = "pipe_dream research sirduckingtoniii@gmail.com"  # scripts/edgar_8k_events_pull.py convention
SLEEP = 0.125
RETRYABLE = (http.client.RemoteDisconnected, http.client.IncompleteRead, urllib.error.URLError,
             socket.timeout, TimeoutError, ConnectionResetError)


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def get(url, retries=6):
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept-Encoding": "identity"})
            with urllib.request.urlopen(req, timeout=30) as r:
                data = r.read()
            time.sleep(SLEEP)
            return data.decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            if e.code == 404:
                time.sleep(SLEEP)
                return None
            if e.code in (429, 500, 502, 503, 504) and attempt < retries - 1:
                time.sleep(2 ** attempt * 2)
                continue
            raise
        except RETRYABLE:
            if attempt == retries - 1:
                raise
            time.sleep(2 ** attempt * 2)
    return None


def universe_ciks():
    p = pd.read_parquet(PANEL, columns=["ticker", "date", "eligible_cap150"])
    p["date"] = pd.to_datetime(p["date"])
    recent = p[(p["date"] >= p["date"].max() - pd.Timedelta(days=400)) & p["eligible_cap150"]]
    tickers = set(recent["ticker"].astype(str))
    tm = pd.read_csv(TICKERS_MASTER, usecols=["ticker", "secfilings"])
    tm["cik"] = pd.to_numeric(tm["secfilings"].str.extract(r"CIK=0*(\d+)")[0], errors="coerce")
    tm = tm[tm["ticker"].astype(str).isin(tickers)].dropna(subset=["cik"])
    return set(tm["cik"].astype("int64"))


def daily_index(day):
    q = (day.month - 1) // 3 + 1
    url = f"https://www.sec.gov/Archives/edgar/daily-index/{day.year}/QTR{q}/form.{day:%Y%m%d}.idx"
    txt = get(url)
    if txt is None:
        return None  # weekend/holiday
    rows = []
    for line in txt.splitlines():
        if not line.startswith("4 "):
            continue
        m = re.match(r"^(\S+)\s+(.*?)\s+(\d+)\s+(\d{8})\s+(edgar/\S+\.txt)\s*$", line)
        if m and m.group(1) == "4":
            rows.append({"cik": int(m.group(3)), "fdate": m.group(4), "path": m.group(5)})
    return rows


def _t(el, path):
    x = el.find(path)
    return x.text.strip() if x is not None and x.text else None


def _flag(el, path):
    v = (_t(el, path) or "").lower()
    return v in ("1", "true")


def parse_form4(txt, accession, filing_date, source):
    m = re.search(r"<XML>(.*?)</XML>", txt, re.S)
    if not m:
        return []
    root = ET.fromstring(m.group(1).strip())
    if (_t(root, "documentType") or "") != "4":
        return []
    issuer_cik = int(_t(root, "issuer/issuerCik"))
    trans = {}
    for tr in root.findall("nonDerivativeTable/nonDerivativeTransaction"):
        code = _t(tr, "transactionCoding/transactionCode")
        if code not in ("P", "S"):
            continue
        d = pd.to_datetime(_t(tr, "transactionDate/value"), errors="coerce")
        try:
            v = float(_t(tr, "transactionAmounts/transactionShares/value")) * float(
                _t(tr, "transactionAmounts/transactionPricePerShare/value"))
        except (TypeError, ValueError):
            v = float("nan")
        agg = trans.setdefault(code, {"value": 0.0, "trans_date": pd.NaT})
        agg["value"] = agg["value"] + (0.0 if pd.isna(v) else v)
        if pd.notna(d) and (pd.isna(agg["trans_date"]) or d < agg["trans_date"]):
            agg["trans_date"] = d
    out = []
    for ro in root.findall("reportingOwner"):
        rel = [n for n, f in (("Director", "isDirector"), ("Officer", "isOfficer"),
                              ("TenPercentOwner", "isTenPercentOwner"), ("Other", "isOther"))
               if _flag(ro, f"reportingOwnerRelationship/{f}")]
        rels = ",".join(rel)
        is_od = ("Director" in rel) or ("Officer" in rel)
        for code, agg in trans.items():
            out.append({"accession": accession, "issuer_cik": issuer_cik,
                        "owner_cik": int(_t(ro, "reportingOwnerId/rptOwnerCik")),
                        "relationship": rels, "is_od": is_od,
                        "is_10pct_only": ("TenPercentOwner" in rel) and not is_od,
                        "code": code, "filing_date": pd.Timestamp(filing_date),
                        "trans_date": agg["trans_date"], "value": agg["value"], "source_file": source})
    return out


def run(start, end, out_path, state_dir):
    state_dir.mkdir(parents=True, exist_ok=True)
    days_done_f = state_dir / "index_days_done.txt"
    acc_done_f = state_dir / "accessions_done.txt"
    rows_f = state_dir / "rows.jsonl"
    days_done = set(days_done_f.read_text().split()) if days_done_f.exists() else set()
    acc_done = set(acc_done_f.read_text().split()) if acc_done_f.exists() else set()
    ciks = universe_ciks()
    log(f"universe CIKs: {len(ciks)}; {start.date()} -> {end.date()}; "
        f"{len(days_done)} days / {len(acc_done)} accessions already done")
    n_fetch = 0
    for day in pd.bdate_range(start, end):
        key = f"{day:%Y%m%d}"
        if key in days_done:
            continue
        idx = daily_index(day)
        if idx is None:
            log(f"{day.date()}: no index (holiday or not yet published)")
            if day.normalize() < pd.Timestamp.today().normalize():
                with open(days_done_f, "a") as f:
                    f.write(key + "\n")
            continue
        by_acc = {}
        for r in idx:
            acc = Path(r["path"]).stem
            by_acc.setdefault(acc, {"path": r["path"], "ciks": set(), "fdate": r["fdate"]})["ciks"].add(r["cik"])
        todo = [(a, v) for a, v in by_acc.items() if v["ciks"] & ciks and a not in acc_done]
        log(f"{day.date()}: {len(by_acc)} Form 4 accessions, {len(todo)} in universe to fetch")
        with open(rows_f, "a") as fr, open(acc_done_f, "a") as fa:
            for a, v in todo:
                txt = get("https://www.sec.gov/Archives/" + v["path"])
                n_fetch += 1
                if txt:
                    try:
                        for row in parse_form4(txt, a, v["fdate"], f"daily-index {key}"):
                            row = {k: (x.isoformat() if isinstance(x, pd.Timestamp) else
                                       (None if x is pd.NaT else x)) for k, x in row.items()}
                            fr.write(json.dumps(row) + "\n")
                    except ET.ParseError as e:
                        log(f"  parse error {a}: {e}")
                fa.write(a + "\n")
                acc_done.add(a)
        if day.normalize() < pd.Timestamp.today().normalize():   # today's index may still grow
            with open(days_done_f, "a") as f:
                f.write(key + "\n")
    consolidate(rows_f, out_path)
    log(f"done: {n_fetch} filings fetched this run")


def consolidate(rows_f, out_path):
    if not rows_f.exists():
        log("no rows yet")
        return
    df = pd.read_json(rows_f, lines=True, dtype=False)
    if df.empty:
        return
    df["filing_date"] = pd.to_datetime(df["filing_date"], format="%Y%m%d", errors="coerce").fillna(
        pd.to_datetime(df["filing_date"], errors="coerce"))
    df["trans_date"] = pd.to_datetime(df["trans_date"], errors="coerce")
    for c in ("issuer_cik", "owner_cik"):
        df[c] = df[c].astype("int64")
    df = df.drop_duplicates(["accession", "owner_cik", "code"]).reset_index(drop=True)
    df.to_parquet(out_path, index=False)
    log(f"-> {out_path}: {len(df):,} rows, filing dates {df['filing_date'].min().date()} .. "
        f"{df['filing_date'].max().date()}")


def validate():
    """Parse 2026-03-02..06 from EDGAR and diff against the bulk 2026q1 set."""
    scratch = STATE_DIR.parent / "form4_refresh_validate"
    out = scratch / "validate_events.parquet"
    run(pd.Timestamp("2026-03-02"), pd.Timestamp("2026-03-06"), out, scratch)
    live = pd.read_parquet(out)
    bulk = pd.read_parquet(BULK_EVENTS)
    bulk = bulk[bulk["accession"].isin(set(live["accession"]))].copy()
    k = ["accession", "owner_cik", "code"]
    for c in ("issuer_cik", "owner_cik"):
        bulk[c] = bulk[c].astype("int64")
    m = live.merge(bulk, on=k, how="outer", suffixes=("_live", "_bulk"), indicator=True)
    both = m[m["_merge"] == "both"]
    rep = {
        "live_rows": int(len(live)), "bulk_rows_same_accessions": int(len(bulk)),
        "only_live": int((m["_merge"] == "left_only").sum()), "only_bulk": int((m["_merge"] == "right_only").sum()),
        "issuer_match": float((both["issuer_cik_live"] == both["issuer_cik_bulk"]).mean()),
        "is_od_match": float((both["is_od_live"] == both["is_od_bulk"]).mean()),
        "filing_date_match": float((both["filing_date_live"] == both["filing_date_bulk"]).mean()),
        "trans_date_match": float(((both["trans_date_live"] == both["trans_date_bulk"])
                                   | (both["trans_date_live"].isna() & both["trans_date_bulk"].isna())).mean()),
        "value_match_1pct": float(((both["value_live"] - both["value_bulk"]).abs()
                                   <= 0.01 * both["value_bulk"].abs() + 1).mean()),
    }
    print(json.dumps(rep, indent=2))
    (scratch / "validate_report.json").write_text(json.dumps(rep, indent=2))
    if rep["only_live"] or rep["only_bulk"]:
        print(m[m["_merge"] != "both"][k + ["_merge"]].head(20).to_string())
    return rep


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start")
    ap.add_argument("--end")
    ap.add_argument("--validate", action="store_true")
    a = ap.parse_args()
    if a.validate:
        validate()
        return
    if a.start:
        start = pd.Timestamp(a.start)
    else:
        start = pd.read_parquet(BULK_EVENTS, columns=["filing_date"])["filing_date"].max() + pd.Timedelta(days=1)
    end = pd.Timestamp(a.end) if a.end else pd.Timestamp.today().normalize()
    run(start, end, LIVE_EVENTS, STATE_DIR)


if __name__ == "__main__":
    sys.exit(main())
