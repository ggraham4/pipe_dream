"""
Run this ON YOUR OWN MACHINE (not through Claude), AFTER
local_cik_lookup_delisted.py. Second pass of the delisted-ticker
fundamentals pull: same companyfacts logic as
local_fundamentals_pull_delisted.py, but sourced from
fundamentals_raw_delisted/manual_cik_overrides.json (name-based CIK
matches for tickers the automatic ticker->CIK file couldn't find) instead
of the automatic ticker->CIK map.

Usage:
    pip install requests
    python3 local_cik_lookup_delisted.py          # if you haven't already
    python3 local_fundamentals_pull_delisted_v2.py

Output: same fundamentals_raw_delisted/{TICKER}.csv files as v1 (adds to
the same directory, same schema) -- fundamentals_features_pit.py picks
these up automatically, no changes needed there. Also appends to
_pull_report.txt.
"""
import csv
import json
import time
import urllib.request
import urllib.error
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
OUT_DIR = SCRIPT_DIR / "fundamentals_raw_delisted"
OVERRIDES_PATH = OUT_DIR / "manual_cik_overrides.json"

SKIP_EXISTING = True
REQUEST_DELAY_SECONDS = 0.15
MAX_RETRIES = 3

USER_AGENT = "pipe_dream research sirduckingtoniii@gmail.com"

# same concept lists as local_fundamentals_pull_delisted.py -- identical
# extraction logic, only the CIK source differs
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
                        continue
                    rows.append({
                        "ticker": ticker, "cik": cik, "concept": concept, "tag_used": tag_used,
                        "unit": unit, "fiscal_year": e.get("fy"), "fiscal_period": e.get("fp"),
                        "period_end": e.get("end"), "filed_date": e.get("filed"),
                        "form": form, "accn": e.get("accn"), "value": e.get("val"),
                    })
    return rows


def main():
    if not OVERRIDES_PATH.exists():
        raise SystemExit(f"{OVERRIDES_PATH} not found -- run local_cik_lookup_delisted.py first.")
    with open(OVERRIDES_PATH) as f:
        overrides = json.load(f)

    to_pull = list(overrides.items())
    if SKIP_EXISTING:
        before = len(to_pull)
        to_pull = [(t, c) for t, c in to_pull if not (OUT_DIR / f"{t}.csv").exists()]
        skipped = before - len(to_pull)
        if skipped:
            print(f"SKIP_EXISTING on: {skipped} tickers already have a CSV, skipping those.")

    print(f"Pulling companyfacts for {len(to_pull)} name-resolved delisted/gap tickers "
          f"(~{len(to_pull) * (REQUEST_DELAY_SECONDS + 0.3) / 60:.1f} min estimated)...")

    ok, failed = 0, []
    for i, (ticker, cik) in enumerate(to_pull, 1):
        url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
        data, err = http_get_json(url)
        if data is None:
            failed.append((ticker, err))
            print(f"[{i}/{len(to_pull)}] {ticker}: FAILED ({err})")
            time.sleep(REQUEST_DELAY_SECONDS)
            continue

        rows = extract_facts(data, ticker, cik)
        if not rows:
            failed.append((ticker, "no matching concepts found in companyfacts"))
            print(f"[{i}/{len(to_pull)}] {ticker}: no usable facts extracted")
        else:
            out_path = OUT_DIR / f"{ticker}.csv"
            with open(out_path, "w", newline="") as f:
                w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
                w.writeheader()
                w.writerows(rows)
            ok += 1
            print(f"[{i}/{len(to_pull)}] {ticker}: {len(rows)} facts written")

        time.sleep(REQUEST_DELAY_SECONDS)

    report_lines = [
        "",
        f"--- v2 (name-resolved CIK) pass: {ok} succeeded, {len(failed)} failed, out of "
        f"{len(to_pull)} attempted ---",
    ] + [f"  {t}: {reason}" for t, reason in failed]
    report = "\n".join(report_lines)
    print("\n" + report)
    with open(OUT_DIR / "_pull_report.txt", "a") as f:
        f.write(report + "\n")
    print(f"\nDone. {ok} more tickers now have fundamentals in {OUT_DIR}/. "
          f"Re-run fundamentals_features_pit.py and backtest_pit.py to pick these up.")


if __name__ == "__main__":
    main()
