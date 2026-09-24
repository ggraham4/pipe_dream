"""
Pull every 8-K carrying Item 2.02 ("Results of Operations and Financial
Condition") for every CIK in this project's universe, from EDGAR's
structured submissions API. WO-5 (2026-09-23), see
final/models/2026-09-23-earnings-announcement-premium-8k.md.

    /opt/anaconda3/envs/pipe_dream/bin/python3.11 edgar_8k_item202_pull.py

Output: final/data/edgar/8k_item202.parquet (MAIN checkout; *.parquet is
gitignored) with columns
    cik, form, filing_date, acceptance_datetime (raw EDGAR string),
    acceptance_et (naive US/Eastern wall clock, converted from UTC), accession, items
One row per (cik, accession). Only form == "8-K" and "8-K/A" are kept here;
the signal builder decides which forms it uses (pre-registered: 8-K only).

SOURCE CHOICE
-------------
data.sec.gov/submissions/CIK##########.json carries per-filing `items`,
`filingDate`, `acceptanceDateTime` and `form` for every filing a CIK ever
made, dead or alive, with older filings paged into `files` (each page
listed with filingFrom/filingTo). One CIK = 1 + (#pages) requests,
~4,000 CIKs, a few thousand requests total, deterministic and complete.

efts.sec.gov full-text search (edgar_8k_events_pull.py) was rejected as the
primary source: it has no server-side item filter (needs a text query like
"Item 2.02", which misses filings whose text never spells the item out),
every exhibit is its own hit, and it hard-caps at 10,000 hits per query --
Item 2.02 runs ~25-30k filings/year, heavily bunched in earnings season,
so it would need week-level slicing. It is used here only as a
cross-check on a sample (see --crosscheck).

Raw JSON is cached OUTSIDE the repo at ~/.cache/pipe_dream/edgar_submissions
so re-runs cost nothing and nothing large lands in git.

Rate: SLEEP between requests keeps us well under SEC's 10 req/s; 403/429
responses back off exponentially.
"""
import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import pandas as pd

MAIN_ROOT = Path("/Users/ggraham/pipe_dream/final")
TICKERS_MASTER = MAIN_ROOT / "data" / "sharadar" / "tickers_master.csv"
PANEL = MAIN_ROOT / "out" / "reset2026" / "composite_panel.parquet"
OUT = MAIN_ROOT / "data" / "edgar" / "8k_item202.parquet"
CACHE = Path.home() / ".cache" / "pipe_dream" / "edgar_submissions"
# Same constant/convention as final/scripts/edgar_8k_events_pull.py
USER_AGENT = "pipe_dream research sirduckingtoniii@gmail.com"
SLEEP = 0.13                      # ~7.5 req/s ceiling
EARLIEST_PAGE_NEEDED = "2004-08-01"  # Item codes begin 2004-08-23


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def _get_json(url, retries=6):
    req = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT, "Accept": "application/json",
        "Accept-Encoding": "identity"})
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            if e.code in (403, 429, 500, 502, 503, 504) and attempt < retries - 1:
                wait = 2 ** (attempt + 1)
                log(f"  HTTP {e.code} on {url}; backing off {wait}s")
                time.sleep(wait)
                continue
            raise
        except (urllib.error.URLError, TimeoutError) as e:
            if attempt < retries - 1:
                time.sleep(2 ** (attempt + 1))
                continue
            raise


def fetch_cached(name):
    CACHE.mkdir(parents=True, exist_ok=True)
    p = CACHE / name
    if p.exists():
        return json.loads(p.read_text()), False
    d = _get_json(f"https://data.sec.gov/submissions/{name}")
    p.write_text(json.dumps(d))
    time.sleep(SLEEP)
    return d, True


def block_rows(cik, blk):
    n = len(blk.get("form", []))
    out = []
    for i in range(n):
        form = blk["form"][i]
        if form not in ("8-K", "8-K/A"):
            continue
        items = blk.get("items", [""] * n)[i] or ""
        if "2.02" not in items.split(","):
            continue
        out.append({"cik": cik, "form": form, "filing_date": blk["filingDate"][i],
                    "acceptance_datetime": blk.get("acceptanceDateTime", [None] * n)[i],
                    "accession": blk["accessionNumber"][i], "items": items})
    return out


def universe_ciks():
    tick = pd.read_parquet(PANEL, columns=["ticker"])["ticker"].astype(str).unique()
    tm = pd.read_csv(TICKERS_MASTER, usecols=["ticker", "secfilings"])
    tm["cik"] = pd.to_numeric(tm["secfilings"].str.extract(r"CIK=0*(\d+)")[0], errors="coerce")
    tm = tm.dropna(subset=["cik"]).astype({"cik": "int64"})
    return sorted(tm[tm["ticker"].isin(set(tick))]["cik"].unique().tolist())


def pull(ciks):
    rows, n_req, empty, missing = [], 0, [], []
    t0 = time.time()
    for k, cik in enumerate(ciks):
        d, fresh = fetch_cached(f"CIK{cik:010d}.json")
        n_req += fresh
        if d is None:
            missing.append(cik)
            continue
        got = block_rows(cik, d["filings"]["recent"])
        for f in d["filings"].get("files", []):
            if f.get("filingTo", "9999") < EARLIEST_PAGE_NEEDED:
                continue
            pg, fresh = fetch_cached(f["name"])
            n_req += fresh
            if pg is not None:
                got += block_rows(cik, pg)
        if not got:
            empty.append(cik)
        rows += got
        if (k + 1) % 250 == 0:
            log(f"  {k+1}/{len(ciks)} CIKs, {len(rows):,} rows, {n_req} fresh requests, "
                f"{time.time()-t0:.0f}s")
    return rows, empty, missing


def to_frame(rows):
    df = pd.DataFrame(rows).drop_duplicates(subset=["cik", "accession"])
    df["filing_date"] = pd.to_datetime(df["filing_date"])
    # acceptanceDateTime is genuine UTC: AAPL's 16:30 ET releases read
    # 20:30Z in summer (EDT) and 21:30Z in winter (EST) -- 2012-07-24
    # 20:31Z vs 2012-01-24 21:30Z. Convert to naive US/Eastern wall clock.
    df["acceptance_et"] = (pd.to_datetime(df["acceptance_datetime"], utc=True, errors="coerce")
                           .dt.tz_convert("America/New_York").dt.tz_localize(None))
    return df.sort_values(["cik", "filing_date", "accession"]).reset_index(drop=True)


def crosscheck(df, n=10):
    """Compare a sample of CIK-quarters against efts full-text search."""
    base = "https://efts.sec.gov/LATEST/search-index"
    samp = df[df["form"] == "8-K"].sample(n, random_state=7)
    res = []
    for _, r in samp.iterrows():
        d0 = (r["filing_date"] - pd.Timedelta(days=3)).date().isoformat()
        d1 = (r["filing_date"] + pd.Timedelta(days=3)).date().isoformat()
        q = {"q": "\"results of operations\"", "forms": "8-K", "ciks": f"{r['cik']:010d}",
             "startdt": d0, "enddt": d1}
        j = _get_json(f"{base}?{urllib.parse.urlencode(q)}")
        time.sleep(SLEEP)
        adsh = {h["_source"].get("adsh") for h in (j or {}).get("hits", {}).get("hits", [])}
        items = {i for h in (j or {}).get("hits", {}).get("hits", [])
                 for i in (h["_source"].get("items") or [])}
        res.append({"cik": int(r["cik"]), "filing_date": str(r["filing_date"].date()),
                    "accession": r["accession"], "efts_found_accession": r["accession"] in adsh,
                    "efts_items_has_202": "2.02" in items})
        log(f"  crosscheck {res[-1]}")
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--crosscheck", type=int, default=10)
    a = ap.parse_args()
    ciks = universe_ciks()
    if a.limit:
        ciks = ciks[: a.limit]
    log(f"{len(ciks):,} CIKs to pull")
    rows, empty, missing = pull(ciks)
    df = to_frame(rows)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(OUT, index=False)
    log(f"wrote {OUT}: {len(df):,} rows, {df['cik'].nunique():,} CIKs, "
        f"{df['filing_date'].min().date()}..{df['filing_date'].max().date()}")
    meta = {"n_ciks_requested": len(ciks), "n_ciks_with_202": int(df["cik"].nunique()),
            "ciks_zero_202": empty, "ciks_404": missing, "n_rows": int(len(df)),
            "n_rows_8k": int((df["form"] == "8-K").sum())}
    if a.crosscheck:
        meta["efts_crosscheck"] = crosscheck(df, a.crosscheck)
    (OUT.parent / "8k_item202_pull_meta.json").write_text(json.dumps(meta, indent=2))
    log(f"meta: {len(empty)} CIKs with zero 2.02s, {len(missing)} 404s")


if __name__ == "__main__":
    main()
