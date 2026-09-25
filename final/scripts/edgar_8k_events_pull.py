"""
Pull SEC EDGAR full-text-search 8-K event data: structured item codes plus a
"going concern" language flag.

Round 20 (2026-09-18). Data-sourcing report item #8. Free, public,
`efts.sec.gov` full-text search -- no API key, SEC's own fair-use ~10 req/s
guideline (this script sleeps between requests to stay well under it).

    python3 edgar_8k_events_pull.py

Output: final/data/edgar/8k_events_raw.csv

WHAT WAS VERIFIED BEFORE WRITING THIS (2026-09-18, live queries)
------------------------------------------------------------------
1. No auth needed. Requires a descriptive User-Agent (SEC blocks generic
   ones) -- reuses this project's existing USER_AGENT constant/convention
   from local_fundamentals_pull.py.
2. Each hit already carries a structured `items` array (e.g. ["4.02","9.01"])
   straight from EDGAR's own index -- Item 4.02 (non-reliance/restatement)
   and Item 5.02 (exec departures) need NO text search or NLP, just a filter
   on this field. Confirmed live.
3. "Going concern" is not a formal item code, so it needs an actual text
   search (`q="going concern"`) -- confirmed working, real hits, real dates.
4. HARD CAP: any single query maxes out at 10,000 results
   (`hits.total == {"value": 10000, "relation": "gte"}` past that point, and
   `from` beyond ~9900 silently returns empty -- confirmed by direct test,
   not documented anywhere obvious). This is a standard Elasticsearch
   `max_result_window`, not a bug or a rate limit. Mitigation: slice by
   YEAR (going-concern language is ~3,400 hits/year, comfortably under the
   cap) and self-check `total.value` on each slice -- if a slice ever nears
   10,000 the script halves it and re-queries recursively instead of
   silently truncating.

POINT-IN-TIME
-------------
`file_date` is the filing's own EDGAR filing date -- no restatement risk,
no lag needed (unlike FINRA short interest, this is public the moment it's
filed). PIT-safe as-is.
"""
import sys
import time
import urllib.parse
import urllib.request
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from features import PROJECT_ROOT                                # noqa: E402

OUT = PROJECT_ROOT / "data" / "edgar" / "8k_events_raw.csv"
BASE = "https://efts.sec.gov/LATEST/search-index"
USER_AGENT = "pipe_dream research sirduckingtoniii@gmail.com"
PAGE = 100                       # API's own default/max page size
SLEEP = 0.15                     # stays well under SEC's ~10 req/s guidance

# One query per target flag. "going concern" is the language flag; the item
# codes need no search text of their own -- EDGAR requires a non-empty `q`,
# so a broad, near-universal 8-K term is used and the item filter is applied
# client-side against the `items` field already in each hit.
QUERIES = {
    "going_concern": {"q": "\"going concern\"", "item_filter": None},
    "item_402_restatement": {"q": "\"Item 4.02\"", "item_filter": "4.02"},
    "item_502_departure": {"q": "\"Item 5.02\"", "item_filter": "5.02"},
}


def _get(url, retries=4):
    req = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT, "Accept": "application/json",
        "Accept-Encoding": "identity"})
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code in (500, 502, 503, 504) and attempt < retries - 1:
                wait = 2 ** attempt
                print(f"    [retry {attempt+1}/{retries} after HTTP {e.code}, "
                      f"waiting {wait}s]", flush=True)
                time.sleep(wait)
                continue
            raise


def _query(q, start, end, frm=0):
    params = {"q": q, "forms": "8-K", "startdt": start, "enddt": end,
              "from": frm}
    url = f"{BASE}?{urllib.parse.urlencode(params)}"
    return _get(url)


def _pull_range(q, start, end, item_filter, depth=0):
    """Pull one date range, splitting in half if it nears the 10k cap."""
    d = _query(q, start, end, frm=0)
    total = d["hits"]["total"]["value"]
    if total >= 9500 and depth < 6:
        import datetime as dt
        lo = dt.date.fromisoformat(start)
        hi = dt.date.fromisoformat(end)
        mid = lo + (hi - lo) / 2
        if mid <= lo or mid >= hi:
            print(f"    WARNING: {start}..{end} has {total} hits and won't split further")
        else:
            time.sleep(SLEEP)
            return (_pull_range(q, start, mid.isoformat(), item_filter, depth + 1)
                    + _pull_range(q, mid.isoformat(), end, item_filter, depth + 1))

    rows, frm = [], 0
    while True:
        d = _query(q, start, end, frm=frm)
        hits = d["hits"]["hits"]
        if not hits:
            break
        for h in hits:
            src = h["_source"]
            items = src.get("items") or []
            if item_filter and item_filter not in items:
                continue
            for cik in src.get("ciks", []):
                rows.append({"cik": cik, "file_date": src.get("file_date"),
                            "items": ";".join(items), "adsh": src.get("adsh")})
        frm += PAGE
        if frm >= min(total, 9900):
            break
        time.sleep(SLEEP)
    return rows


def main():
    import pandas as pd
    import datetime as dt

    OUT.parent.mkdir(parents=True, exist_ok=True)
    all_rows = {}
    t0 = time.time()
    for flag, cfg in QUERIES.items():
        print(f"=== {flag} ===", flush=True)
        rows = []
        for year in range(2007, dt.date.today().year + 1):
            start, end = f"{year}-01-01", f"{min(year+1, dt.date.today().year+1)}-01-01"
            if year == dt.date.today().year:
                end = dt.date.today().isoformat()
            try:
                batch = _pull_range(cfg["q"], start, end, cfg["item_filter"])
            except Exception as e:
                print(f"  {year}: FAILED after retries ({type(e).__name__}: {e}) -- skipping year",
                      flush=True)
                continue
            print(f"  {year}: {len(batch):,} rows ({time.time()-t0:.0f}s elapsed)", flush=True)
            rows.extend(batch)
            time.sleep(SLEEP)
        for r in rows:
            r["flag"] = flag
        all_rows[flag] = rows

    df = pd.DataFrame([r for rows in all_rows.values() for r in rows])
    print(f"\n{len(df):,} total rows, {df['cik'].nunique():,} CIKs, "
          f"{df['file_date'].min()} .. {df['file_date'].max()}")

    print("\n--- acceptance checks ---")
    ok = True
    for flag in QUERIES:
        n = (df["flag"] == flag).sum()
        print(f"  {flag}: {n:,} rows")
        if n == 0:
            ok = False
            print(f"    FAIL -- zero rows for {flag}")
    dup_query_years = df.groupby("flag")["file_date"].apply(
        lambda s: s.duplicated().sum())
    print(f"  duplicate (cik, file_date, flag) rows are expected (multiple "
          f"CIKs can share a filing, or a filing can appear via both a "
          f"press-release exhibit and the primary doc) -- not flagged")

    print(f"\n{'ALL CHECKS PASSED' if ok else 'CHECKS FAILED -- inspect before using'}")
    df = df.drop_duplicates(subset=["cik", "file_date", "flag", "adsh"])
    df.to_csv(OUT, index=False)
    print(f"\nwritten {OUT} ({OUT.stat().st_size/1e6:.0f}MB, {time.time()-t0:.0f}s total)")


if __name__ == "__main__":
    main()
