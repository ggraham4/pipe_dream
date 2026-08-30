"""
Run this ON YOUR OWN MACHINE (not through Claude) to pull point-in-time
fundamentals data for the pipe_dream universe from SEC EDGAR's XBRL API,
sidestepping the cloud sandbox's network restrictions entirely -- same
reason local_data_pull.py exists for price data: the sandbox's egress
allowlist blocks data.sec.gov outright (confirmed via curl -- CONNECT
tunnel gets a 403 from the proxy), and even Claude's own fetch tool only
reaches it through a summarizing step that isn't reliable for exact numeric
data at this scale. Your own machine's normal internet connection has none
of these restrictions.

Why SEC EDGAR and not a paid data vendor: it's the only free source that
covers the WHOLE universe (every US public company files XBRL with the
SEC, not just S&P 500 names) with real depth (back to ~2009+ for most
large/mid caps) AND genuine point-in-time correctness -- every fact comes
with the actual date it was FILED, not just the fiscal period it covers.
That's exactly what's needed to build features without lookahead: a
quarter's numbers don't exist to the market until the 10-Q/10-K reporting
them is actually filed, which is usually 30-75 days after the period ends,
not on the period-end date itself.

Usage:
    pip install requests pandas
    python3 local_fundamentals_pull.py                 # pulls the full universe (reads tickers from td_data_local/)
    python3 local_fundamentals_pull.py AAPL MSFT NVDA   # pulls just these tickers

Output: writes one CSV per ticker to ./fundamentals_raw/{TICKER}.csv, long
format: [ticker, cik, concept, tag_used, unit, fiscal_year, fiscal_period,
period_end, filed_date, form, accn, value]. Also writes
./fundamentals_raw/_pull_report.txt summarizing successes/failures, and
./fundamentals_raw/_ticker_cik_map.csv for anything that needs a manual
CIK fix.

Re-running is resumable: SKIP_EXISTING (below) skips any ticker that
already has a CSV, so an interrupted run just needs to be re-started.

Send the resulting fundamentals_raw/ folder back the same way
td_data_local/ was sent for prices, so the feature-engineering step can be
built on top of it.
"""
import csv
import json
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
PRICE_DATA_DIR = SCRIPT_DIR / "td_data_local"
OUT_DIR = SCRIPT_DIR / "fundamentals_raw"

SKIP_EXISTING = True
REQUEST_DELAY_SECONDS = 0.15   # SEC's documented fair-access limit is 10 req/sec; this stays well under it
MAX_RETRIES = 3

# SEC requires a descriptive User-Agent identifying the requester -- generic
# or missing User-Agents get blocked. This is a real request from Gabe's own
# machine, so using his contact info here is correct and expected practice.
USER_AGENT = "pipe_dream research sirduckingtoniii@gmail.com"

# us-gaap concept -> list of candidate XBRL tag names, tried in order (GAAP
# taxonomy naming isn't fully standardized across filers/years, so several
# companies report the "same" line item under different tags -- e.g. some
# use Revenues, others RevenueFromContractWithCustomerExcludingAssessedTax
# post-ASC606). First match wins per ticker; which tag actually matched is
# recorded in the output so this is auditable, not silently guessed.
CONCEPTS_US_GAAP = {
    "revenue": ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax",
                "RevenueFromContractWithCustomerIncludingAssessedTax", "SalesRevenueNet"],
    "net_income": ["NetIncomeLoss", "ProfitLoss"],
    "gross_profit": ["GrossProfit"],
    "operating_income": ["OperatingIncomeLoss"],
    "total_assets": ["Assets"],
    "total_liabilities": ["Liabilities"],
    "stockholders_equity": ["StockholdersEquity",
                             "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"],
    "long_term_debt": ["LongTermDebtNoncurrent", "LongTermDebt"],
    "cash": ["CashAndCashEquivalentsAtCarryingValue",
             "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"],
    "eps_diluted": ["EarningsPerShareDiluted"],
    "eps_basic": ["EarningsPerShareBasic"],
    "shares_outstanding": ["CommonStockSharesOutstanding"],
    "operating_cash_flow": ["NetCashProvidedByUsedInOperatingActivities",
                             "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations"],
    "capex": ["PaymentsToAcquirePropertyPlantAndEquipment"],
    "rnd_expense": ["ResearchAndDevelopmentExpense"],
}
# dei (Document and Entity Information) namespace -- separate from us-gaap
CONCEPTS_DEI = {
    "shares_outstanding_dei": ["EntityCommonStockSharesOutstanding"],
}


def http_get_json(url, retries=MAX_RETRIES):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept-Encoding": "gzip"})
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                data = resp.read()
                if resp.headers.get("Content-Encoding") == "gzip":
                    import gzip
                    data = gzip.decompress(data)
                return json.loads(data), None
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


def load_universe():
    if len(sys.argv) > 1:
        return [t.upper() for t in sys.argv[1:]]
    if not PRICE_DATA_DIR.exists():
        print(f"ERROR: {PRICE_DATA_DIR} not found and no tickers given on the command line.")
        sys.exit(1)
    tickers = sorted(p.stem for p in PRICE_DATA_DIR.glob("*.csv") if p.stem != "SPY")
    print(f"Loaded {len(tickers)} tickers from {PRICE_DATA_DIR} (SPY excluded -- it's an ETF, has no fundamentals)")
    return tickers


def build_ticker_cik_map(tickers):
    print("Fetching SEC's ticker->CIK mapping (www.sec.gov/files/company_tickers.json)...")
    data, err = http_get_json("https://www.sec.gov/files/company_tickers.json")
    if data is None:
        print(f"FATAL: couldn't fetch the ticker/CIK mapping ({err}). Nothing else can proceed.")
        sys.exit(1)
    by_ticker = {}
    for row in data.values():
        by_ticker[row["ticker"].upper()] = str(row["cik_str"]).zfill(10)

    mapping = {}
    unmatched = []
    for t in tickers:
        candidates = [t, t.replace(".", "-"), t.replace(".", ""), t.replace("-", ".")]
        cik = next((by_ticker[c] for c in candidates if c in by_ticker), None)
        if cik:
            mapping[t] = cik
        else:
            unmatched.append(t)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(OUT_DIR / "_ticker_cik_map.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["ticker", "cik", "status"])
        for t in tickers:
            w.writerow([t, mapping.get(t, ""), "matched" if t in mapping else "NO MATCH -- needs manual lookup"])

    print(f"Matched {len(mapping)}/{len(tickers)} tickers to a CIK. "
          f"{len(unmatched)} unmatched (see _ticker_cik_map.csv) -- these are usually very recent "
          f"IPOs not yet in SEC's list, foreign private issuers filing 20-F instead of 10-K/10-Q, "
          f"or a ticker that changed recently.")
    return mapping


def extract_facts(company_facts, ticker, cik):
    rows = []
    for namespace, concept_map in (("us-gaap", CONCEPTS_US_GAAP), ("dei", CONCEPTS_DEI)):
        ns_facts = company_facts.get("facts", {}).get(namespace, {})
        for concept, tag_candidates in concept_map.items():
            tag_used = next((tag for tag in tag_candidates if tag in ns_facts), None)
            if tag_used is None:
                continue
            units = ns_facts[tag_used].get("units", {})
            for unit, entries in units.items():
                for e in entries:
                    form = e.get("form", "")
                    if form not in ("10-K", "10-K/A", "10-Q", "10-Q/A"):
                        continue  # skip non-periodic-report facts (e.g. 8-K exhibits)
                    rows.append({
                        "ticker": ticker, "cik": cik, "concept": concept, "tag_used": tag_used,
                        "unit": unit, "fiscal_year": e.get("fy"), "fiscal_period": e.get("fp"),
                        "period_end": e.get("end"), "filed_date": e.get("filed"),
                        "form": form, "accn": e.get("accn"), "value": e.get("val"),
                    })
    return rows


def main():
    tickers = load_universe()
    mapping = build_ticker_cik_map(tickers)

    to_pull = [t for t in tickers if t in mapping]
    if SKIP_EXISTING:
        before = len(to_pull)
        to_pull = [t for t in to_pull if not (OUT_DIR / f"{t}.csv").exists()]
        skipped = before - len(to_pull)
        if skipped:
            print(f"SKIP_EXISTING on: {skipped} tickers already have a CSV, skipping those.")

    print(f"Pulling companyfacts for {len(to_pull)} tickers (~{len(to_pull) * (REQUEST_DELAY_SECONDS + 0.3) / 60:.1f} "
          f"min estimated)...")

    ok, failed = 0, []
    for i, ticker in enumerate(to_pull, 1):
        cik = mapping[ticker]
        url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
        data, err = http_get_json(url)
        if data is None:
            failed.append((ticker, err))
            print(f"[{i}/{len(to_pull)}] {ticker}: FAILED ({err})")
            time.sleep(REQUEST_DELAY_SECONDS)
            continue

        rows = extract_facts(data, ticker, cik)
        if not rows:
            failed.append((ticker, "no matching concepts found in companyfacts (unusual filer/taxonomy)"))
            print(f"[{i}/{len(to_pull)}] {ticker}: no usable facts extracted")
        else:
            out_path = OUT_DIR / f"{ticker}.csv"
            with open(out_path, "w", newline="") as f:
                w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
                w.writeheader()
                w.writerows(rows)
            ok += 1
            if i % 25 == 0 or i == len(to_pull):
                print(f"[{i}/{len(to_pull)}] {ticker}: {len(rows)} facts written ({ok} ok, {len(failed)} failed so far)")

        time.sleep(REQUEST_DELAY_SECONDS)

    report_lines = [
        f"Pull complete: {ok} succeeded, {len(failed)} failed, out of {len(to_pull)} attempted "
        f"({len(tickers) - len(to_pull)} were skipped as already-done or unmapped).",
        "",
        "Failures:",
    ] + [f"  {t}: {reason}" for t, reason in failed]
    report = "\n".join(report_lines)
    print("\n" + report)
    with open(OUT_DIR / "_pull_report.txt", "w") as f:
        f.write(report + "\n")
    print(f"\nDone. Output in {OUT_DIR}/ -- send this folder back (zip it if easier) along with "
          f"_pull_report.txt and _ticker_cik_map.csv.")


if __name__ == "__main__":
    main()
