"""
Run this ON YOUR OWN MACHINE (not through Claude) -- companion to
local_data_pull_delisted.py, same survivorship-bias-fix effort (see that
script's docstring for the full why). Pulls point-in-time fundamentals for
the same 211 gap tickers (S&P 500 constituents at one of the 8 backtest
timepoints, missing from today's universe) from SEC EDGAR's XBRL API,
exactly the same method as local_fundamentals_pull.py -- this is that
script with a different, smaller ticker list and a separate output
directory, nothing about the underlying method changed.

Output goes to fundamentals_raw_delisted/ (NOT fundamentals_raw/), kept
fully separate from the live universe's fundamentals pull, same reason
local_data_pull_delisted.py uses its own td_data_delisted/ directory --
nothing here touches the production pipeline or the app.

KNOWN LIMITATION worth expecting up front: SEC's ticker->CIK mapping file
(company_tickers.json) reflects presently-recognized tickers, not a full
historical archive of every ticker ever used -- so some of the older
gap tickers (names delisted well before ~2020) may simply not resolve to
a CIK this way, even though SEC still has their old filings on record
under that CIK. Those show up as "NO MATCH" in _ticker_cik_map.csv. This
script doesn't attempt a fuzzy company-name lookup to recover them --
that's a manual follow-up if it turns out to matter a lot for the final
result, not a blocker for a first honest pass.

Usage:
    pip install requests pandas
    python3 local_fundamentals_pull_delisted.py

Output: fundamentals_raw_delisted/{TICKER}.csv, same long-format schema as
local_fundamentals_pull.py: [ticker, cik, concept, tag_used, unit,
fiscal_year, fiscal_period, period_end, filed_date, form, accn, value].
Also fundamentals_raw_delisted/_pull_report.txt and
_ticker_cik_map.csv.

Re-running is resumable (SKIP_EXISTING below).
"""
import csv
import json
import time
import urllib.request
import urllib.error
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
OUT_DIR = SCRIPT_DIR / "fundamentals_raw_delisted"

SKIP_EXISTING = True
REQUEST_DELAY_SECONDS = 0.15
MAX_RETRIES = 3

USER_AGENT = "pipe_dream research sirduckingtoniii@gmail.com"

# Same 211 tickers as local_data_pull_delisted.py's GAP_TICKERS -- see that
# script's docstring and scripts/pit_universe/ for the full derivation.
GAP_TICKERS = [
    "AABA", "ABC", "ABMD", "ADS", "ADT", "AET", "AGN", "AIV",
    "ALTR", "ALXN", "ANDV", "ANSS", "ANTM", "APC", "APOL", "ARG",
    "ARNC", "ATVI", "AVB", "AVP", "BBBY", "BCR", "BHGE", "BIG",
    "BK", "BLL", "BMC", "BMS", "BRCM", "BTUUQ", "CA", "CAM",
    "CBS", "CCE", "CDAY", "CELG", "CERN", "CFN", "CHK", "CMA",
    "COG", "COL", "COTY", "COV", "CPRI", "CSRA", "CTL", "CTLT",
    "CTRA", "CTXS", "CVC", "CVH", "CXO", "DAY", "DF", "DFS",
    "DISCA", "DISCK", "DISH", "DNB", "DNR", "DO", "DRE", "DTV",
    "DWDP", "DXC", "EA", "EMC", "ENDP", "EQR", "ESRX", "ESV",
    "ETFC", "EVHC", "FB", "FBHS", "FDO", "FI", "FISV", "FL",
    "FLIR", "FLT", "FMC", "FOSL", "FRC", "FRX", "FTI", "FTR",
    "GAS", "GGP", "GMCR", "GNW", "GPS", "GT", "HAR", "HBI",
    "HCBK", "HCP", "HES", "HFC", "HNZ", "HOLX", "HOT", "HRS",
    "HSP", "IGT", "INFO", "IPG", "JCP", "JEC", "JNPR", "JOY",
    "JWN", "K", "KORS", "KRFT", "KSU", "LEG", "LLL", "LLTC",
    "LM", "LO", "LSI", "LUMN", "LVLT", "MJN", "MMC", "MNK",
    "MOLX", "MON", "MRO", "MRSH", "MWV", "MXIM", "MYL", "NAVI",
    "NBL", "NBR", "NFX", "NLOK", "NLSN", "NWL", "NYX", "OI",
    "PARA", "PBCT", "PCL", "PCP", "PDCO", "PEAK", "PETM", "PKI",
    "PLL", "POM", "PRGO", "PX", "PXD", "QEP", "RAI", "RDC",
    "RE", "RHT", "RIG", "RTN", "SATS", "SBNY", "SCG", "SE",
    "SEDG", "SEE", "SIAL", "SIG", "SIVB", "SNI", "SPLS", "SRCL",
    "STI", "STJ", "SWN", "SWY", "SYMC", "TE", "TEG", "TGNA",
    "TIF", "TMK", "TRIP", "TSS", "TWC", "TWTR", "TWX", "UA",
    "UAA", "UTX", "VAR", "VIAB", "VIAC", "WBA", "WCG", "WFM",
    "WIN", "WLTW", "WPX", "WRK", "WU", "WYND", "X", "XEC",
    "XL", "XLNX", "XRX",
]

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


def build_ticker_cik_map(tickers):
    print("Fetching SEC's ticker->CIK mapping (www.sec.gov/files/company_tickers.json)...")
    data, err = http_get_json("https://www.sec.gov/files/company_tickers.json")
    if data is None:
        print(f"FATAL: couldn't fetch the ticker/CIK mapping ({err}). Nothing else can proceed.")
        raise SystemExit(1)
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
            w.writerow([t, mapping.get(t, ""), "matched" if t in mapping else "NO MATCH"])

    print(f"Matched {len(mapping)}/{len(tickers)} tickers to a CIK. {len(unmatched)} unmatched "
          f"(see _ticker_cik_map.csv) -- expected for older delistings, see this script's "
          f"docstring.")
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
                        continue
                    rows.append({
                        "ticker": ticker, "cik": cik, "concept": concept, "tag_used": tag_used,
                        "unit": unit, "fiscal_year": e.get("fy"), "fiscal_period": e.get("fp"),
                        "period_end": e.get("end"), "filed_date": e.get("filed"),
                        "form": form, "accn": e.get("accn"), "value": e.get("val"),
                    })
    return rows


def main():
    tickers = GAP_TICKERS
    mapping = build_ticker_cik_map(tickers)

    to_pull = [t for t in tickers if t in mapping]
    if SKIP_EXISTING:
        before = len(to_pull)
        to_pull = [t for t in to_pull if not (OUT_DIR / f"{t}.csv").exists()]
        skipped = before - len(to_pull)
        if skipped:
            print(f"SKIP_EXISTING on: {skipped} tickers already have a CSV, skipping those.")

    print(f"Pulling companyfacts for {len(to_pull)} delisted/gap tickers "
          f"(~{len(to_pull) * (REQUEST_DELAY_SECONDS + 0.3) / 60:.1f} min estimated)...")

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
            failed.append((ticker, "no matching concepts found in companyfacts"))
            print(f"[{i}/{len(to_pull)}] {ticker}: no usable facts extracted")
        else:
            out_path = OUT_DIR / f"{ticker}.csv"
            with open(out_path, "w", newline="") as f:
                w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
                w.writeheader()
                w.writerows(rows)
            ok += 1
            if i % 25 == 0 or i == len(to_pull):
                print(f"[{i}/{len(to_pull)}] {ticker}: {len(rows)} facts written "
                      f"({ok} ok, {len(failed)} failed so far)")

        time.sleep(REQUEST_DELAY_SECONDS)

    report_lines = [
        f"Delisted/gap fundamentals pull: {ok} succeeded, {len(failed)} failed, out of "
        f"{len(to_pull)} attempted ({len(tickers) - len(to_pull)} skipped as already-done "
        f"or unmapped).",
        "",
        "Failures:",
    ] + [f"  {t}: {reason}" for t, reason in failed]
    report = "\n".join(report_lines)
    print("\n" + report)
    with open(OUT_DIR / "_pull_report.txt", "w") as f:
        f.write(report + "\n")
    print(f"\nDone. Output in {OUT_DIR}/ -- send this folder back the same way you'd send "
          f"fundamentals_raw/.")


if __name__ == "__main__":
    main()
