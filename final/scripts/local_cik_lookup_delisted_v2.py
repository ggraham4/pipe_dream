"""
Run this ON YOUR OWN MACHINE (not through Claude). URGENT FIX for a real
bug in local_cik_lookup_delisted.py (the v1 CIK lookup): it used SEC
EDGAR's full-text search index (efts.sec.gov), which searches filing
CONTENT, not a company name registry. For distinctive company names that
worked fine (e.g. "Red Hat Inc" correctly found Red Hat). For shorter or
more generic names it frequently matched some OTHER company's filing that
merely mentioned the target name -- confirmed by checking the output for
impossible collisions (the same CIK assigned to two different, unrelated
companies): MeadWestvaco (MWV) got matched to United States Steel's CIK,
Newfield Exploration (NFX) got matched to Plum Creek Timber's CIK, SCANA
(SCG) and Southwestern Energy (SWN) both got matched to an unrelated Ohio
utility holding company (DPL Inc). There are certainly more wrong matches
among the ones that didn't happen to collide.

This script:
  1. VALIDATES every ticker in fundamentals_raw_delisted/manual_cik_overrides.json
     by fetching that CIK's real ticker history from SEC's submissions API
     (data.sec.gov/submissions/CIK##########.json, which has a "tickers"
     field listing every ticker ever associated with that CIK -- the
     correct, authoritative source, unlike a content search). If the
     ticker we're checking isn't in that list, the original match was
     wrong.
  2. For anything that fails validation: quarantines the wrong CSV
     already pulled (moves it to fundamentals_raw_delisted/_quarantined_wrong_cik/
     so a future SKIP_EXISTING run doesn't treat it as done), then tries
     to re-resolve the CIK properly using SEC's actual company NAME
     search (browse-edgar, a name registry -- not full-text content
     search), re-validating each candidate the same way before accepting
     it.
  3. Overwrites manual_cik_overrides.json with only VALIDATED entries.
     Nothing gets written there without passing the ticker-history check.

Usage:
    python3 local_cik_lookup_delisted_v2.py

Then re-run local_fundamentals_pull_delisted_v2.py (SKIP_EXISTING will
only re-pull the tickers whose CSVs got quarantined) to backfill correct
data for whatever this fixes.
"""
import csv
import json
import re
import time
import urllib.request
import urllib.error
import urllib.parse
import xml.etree.ElementTree as ET
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
OUT_DIR = SCRIPT_DIR / "fundamentals_raw_delisted"
OVERRIDES_PATH = OUT_DIR / "manual_cik_overrides.json"
QUARANTINE_DIR = OUT_DIR / "_quarantined_wrong_cik"

USER_AGENT = "pipe_dream research sirduckingtoniii@gmail.com"
REQUEST_DELAY_SECONDS = 0.3

# same names used by the v1 lookup, needed again here for re-resolution
from local_cik_lookup_delisted import TICKER_COMPANY_NAMES


def http_get(url, retries=3, as_json=True):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                raw = resp.read()
                return (json.loads(raw) if as_json else raw.decode("utf-8", errors="replace")), None
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None, "404 not found"
            if attempt < retries - 1:
                time.sleep(1.0 * (attempt + 1))
                continue
            return None, f"HTTP {e.code}"
        except Exception as e:
            if attempt < retries - 1:
                time.sleep(1.0 * (attempt + 1))
                continue
            return None, str(e)
    return None, "exhausted retries"


def validate_cik_owns_ticker(cik: str, ticker: str):
    """The authoritative check: does this CIK's real ticker history
    (SEC's submissions API) actually include this ticker? Returns
    (True/False, entity_name_or_reason)."""
    cik_padded = str(cik).zfill(10)
    data, err = http_get(f"https://data.sec.gov/submissions/CIK{cik_padded}.json")
    if data is None:
        return False, f"submissions lookup failed: {err}"
    tickers = [t.upper() for t in (data.get("tickers") or [])]
    name = data.get("name", "?")
    if ticker.upper() in tickers:
        return True, name
    return False, f"'{name}' -- tickers on file: {tickers or '(none)'}"


CIK_RE = re.compile(r"CIK=(\d+)")


def search_company_name_registry(company_name: str):
    """SEC EDGAR's company NAME search (not full-text content search) --
    returns candidate CIKs ranked by name match. Tries progressively
    shorter/simpler versions of the name (SEC's search is a prefix/
    contains match, so a shorter query is often more forgiving)."""
    simplified = re.sub(r"\b(Inc|Corp|Corporation|Co|Company|plc|Ltd|LLC|N V|/DE/|/NEW/|/PA/)\b\.?",
                         "", company_name, flags=re.IGNORECASE).strip()
    candidates_seen = []
    for query in (company_name, simplified):
        q = urllib.parse.quote(query)
        url = (f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&company={q}"
               f"&type=10-K&dateb=&owner=include&count=20&output=atom")
        text, err = http_get(url, as_json=False)
        if text is None:
            continue
        try:
            root = ET.fromstring(text)
        except ET.ParseError:
            continue
        ns = {"a": "http://www.w3.org/2005/Atom"}
        for entry in root.findall("a:entry", ns):
            title = entry.findtext("a:title", default="", namespaces=ns)
            link_el = entry.find("a:link", ns)
            href = link_el.get("href") if link_el is not None else ""
            m = CIK_RE.search(href)
            if m:
                cik = m.group(1)
                if cik not in [c for c, _ in candidates_seen]:
                    candidates_seen.append((cik, title))
        if candidates_seen:
            break
    return candidates_seen[:8]


def main():
    if not OVERRIDES_PATH.exists():
        raise SystemExit(f"{OVERRIDES_PATH} not found -- nothing to validate.")
    with open(OVERRIDES_PATH) as f:
        overrides = json.load(f)

    QUARANTINE_DIR.mkdir(parents=True, exist_ok=True)

    confirmed, fixed, still_unresolved = {}, {}, []

    print(f"Validating {len(overrides)} existing CIK matches against SEC's real ticker history "
          f"(data.sec.gov/submissions)...")
    for i, (ticker, cik) in enumerate(sorted(overrides.items()), 1):
        ok, info = validate_cik_owns_ticker(cik, ticker)
        time.sleep(REQUEST_DELAY_SECONDS)
        if ok:
            confirmed[ticker] = cik
            print(f"[{i}/{len(overrides)}] {ticker}: CIK {cik} CONFIRMED ({info})")
            continue

        print(f"[{i}/{len(overrides)}] {ticker}: CIK {cik} WRONG ({info}) -- quarantining and "
              f"re-resolving...")
        bad_csv = OUT_DIR / f"{ticker}.csv"
        if bad_csv.exists():
            bad_csv.rename(QUARANTINE_DIR / f"{ticker}.csv")

        name = TICKER_COMPANY_NAMES.get(ticker, ticker)
        candidates = search_company_name_registry(name)
        resolved = None
        for cand_cik, cand_title in candidates:
            ok2, info2 = validate_cik_owns_ticker(cand_cik, ticker)
            time.sleep(REQUEST_DELAY_SECONDS)
            if ok2:
                resolved = (cand_cik, info2)
                break
        if resolved:
            fixed[ticker] = resolved[0]
            print(f"    -> fixed: CIK {resolved[0]} ({resolved[1]})")
        else:
            still_unresolved.append((ticker, name, [t for _, t in candidates]))
            print(f"    -> still unresolved ({len(candidates)} candidates tried, none validated)")

    final_overrides = {**confirmed, **fixed}
    with open(OVERRIDES_PATH, "w") as f:
        json.dump(final_overrides, f, indent=2)

    report_lines = [
        f"CIK validation pass: {len(confirmed)} confirmed correct as-is, {len(fixed)} were wrong "
        f"and got fixed, {len(still_unresolved)} still unresolved (need manual lookup).",
        "",
        "Fixed (was wrong, now corrected):",
    ] + [f"  {t}: -> CIK {c}" for t, c in sorted(fixed.items())] + [
        "",
        "Still unresolved (manually search https://www.sec.gov/cgi-bin/browse-edgar if you want "
        "these -- these tickers are NOT in manual_cik_overrides.json, so "
        "local_fundamentals_pull_delisted_v2.py will simply skip them):",
    ] + [f"  {t} ({name}): tried {cands}" for t, name, cands in still_unresolved]

    report = "\n".join(report_lines)
    print("\n" + report)
    with open(OUT_DIR / "_cik_validation_report.txt", "w") as f:
        f.write(report + "\n")

    n_quarantined = len(list(QUARANTINE_DIR.glob("*.csv")))
    print(f"\nDone. {n_quarantined} wrong CSVs quarantined in {QUARANTINE_DIR}/. "
          f"manual_cik_overrides.json now has {len(final_overrides)} validated tickers "
          f"(was {len(overrides)}, all unverified). "
          f"Re-run local_fundamentals_pull_delisted_v2.py to pull correct data for the "
          f"{len(fixed)} that got fixed.")


if __name__ == "__main__":
    main()
