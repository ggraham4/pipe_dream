"""
Run this ON YOUR OWN MACHINE (not through Claude) -- second-pass fix for
local_fundamentals_pull_delisted.py's known limitation. That script only
matched 35/211 gap tickers to a CIK, because SEC's bulk ticker->CIK file
(company_tickers.json) only lists PRESENTLY-recognized tickers -- once a
company delists, its old ticker symbol drops out of that file entirely,
even though SEC keeps every filing it ever made, forever, under its
original CIK. The CIK never goes away; only the file that maps a *ticker
string* to it does.

This script recovers CIKs the other way: by COMPANY NAME instead of
ticker, using SEC EDGAR's full text search index (efts.sec.gov), which
covers every company that has ever filed, active or not. It's the same
approach used to look up "Red Hat Inc" -> CIK 0001087423 during this
investigation (confirmed working). Company names below are hand-built
from general knowledge of what each gap ticker used to be (e.g. AGN =
Allergan plc, RHT = Red Hat Inc) -- most of these are well-known
2013-2025 M&A/bankruptcy targets, so this should have a good hit rate,
but ALWAYS SPOT-CHECK a handful of entries in manual_cik_overrides.json
against sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=... in a
browser before trusting the pull -- ticker/company-name search can
occasionally match the wrong (similarly-named) company, and a wrong CIK
would pull some OTHER company's fundamentals under this ticker's name,
which would be worse than leaving it unmatched.

A handful of these tickers may turn out to actually still be live,
currently-traded companies (e.g. GPS, HES, MRO, WBA, X) that are simply
missing from the *production* universe for some unrelated reason -- not
true delistings. That's fine; a correct CIK for those is still useful
(harmless if the ticker turns out to already be covered elsewhere) and
worth noting as a separate, smaller data-quality finding in its own
right, flagged in the pull report below.

Usage:
    pip install requests
    python3 local_cik_lookup_delisted.py

Reads:  fundamentals_raw_delisted/_ticker_cik_map.csv (to skip tickers
        local_fundamentals_pull_delisted.py already matched)
Writes: fundamentals_raw_delisted/manual_cik_overrides.json
        fundamentals_raw_delisted/_cik_lookup_report.txt

Then run local_fundamentals_pull_delisted_v2.py to actually pull
companyfacts for the newly-resolved CIKs.
"""
import csv
import json
import re
import time
import urllib.request
import urllib.error
import urllib.parse
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
OUT_DIR = SCRIPT_DIR / "fundamentals_raw_delisted"
EXISTING_MAP_CSV = OUT_DIR / "_ticker_cik_map.csv"

USER_AGENT = "pipe_dream research sirduckingtoniii@gmail.com"
REQUEST_DELAY_SECONDS = 0.3  # efts.sec.gov is a shared search index, be polite

# Hand-built ticker -> best-guess legal/registrant company name, for every
# gap ticker local_fundamentals_pull_delisted.py's automatic ticker->CIK
# match was expected to struggle with (older/obscure delistings). Names
# don't need to be exact -- SEC's search ranks by relevance -- but should
# be close enough that the right company is the top or near-top hit.
TICKER_COMPANY_NAMES = {
    "AABA": "Altaba Inc",
    "ABC": "AmerisourceBergen Corp",
    "ABMD": "Abiomed Inc",
    "ADS": "Alliance Data Systems Corp",
    "AET": "Aetna Inc",
    "AGN": "Allergan plc",
    "ALTR": "Altera Corp",
    "ALXN": "Alexion Pharmaceuticals Inc",
    "ANDV": "Andeavor",
    "ANSS": "Ansys Inc",
    "ANTM": "Anthem Inc",
    "APOL": "Apollo Education Group Inc",
    "ARG": "Airgas Inc",
    "ARNC": "Arconic Inc",
    "ATVI": "Activision Blizzard Inc",
    "AVP": "Avon Products Inc",
    "BCR": "C R Bard Inc",
    "BHGE": "Baker Hughes a GE Co",
    "BIG": "Big Lots Inc",
    "BK": "Bank of New York Mellon Corp",
    "BLL": "Ball Corp",
    "BMC": "BMC Software Inc",
    "BMS": "Bemis Co Inc",
    "BRCM": "Broadcom Corp",
    "BTUUQ": "Peabody Energy Corp",
    "CBS": "CBS Corp",
    "CCE": "Coca Cola Enterprises Inc",
    "CDAY": "Ceridian HCM Holding Inc",
    "CELG": "Celgene Corp",
    "CERN": "Cerner Corp",
    "CFN": "CareFusion Corp",
    "CHK": "Chesapeake Energy Corp",
    "CMA": "Comerica Inc",
    "COG": "Cabot Oil & Gas Corp",
    "COL": "Rockwell Collins Inc",
    "COV": "Covidien plc",
    "CTL": "CenturyLink Inc",
    "CTLT": "Catalent Inc",
    "CTRA": "Coterra Energy Inc",
    "CTXS": "Citrix Systems Inc",
    "CVC": "Cablevision Systems Corp",
    "CVH": "Coventry Health Care Inc",
    "CXO": "Concho Resources Inc",
    "DAY": "Dayforce Inc",
    "DF": "Dean Foods Co",
    "DFS": "Discover Financial Services",
    "DISCA": "Discovery Communications Inc",
    "DISCK": "Discovery Communications Inc",
    "DISH": "DISH Network Corp",
    "DNB": "Dun & Bradstreet Corp",
    "DNR": "Denbury Inc",
    "DO": "Diamond Offshore Drilling Inc",
    "DRE": "Duke Realty Corp",
    "DTV": "DIRECTV",
    "DWDP": "DowDuPont Inc",
    "ENDP": "Endo International plc",
    "ESRX": "Express Scripts Holding Co",
    "ESV": "Ensco plc",
    "ETFC": "E TRADE Financial Corp",
    "EVHC": "Envision Healthcare Corp",
    "FBHS": "Fortune Brands Home & Security Inc",
    "FDO": "Family Dollar Stores Inc",
    "FI": "Fiserv Inc",
    "FL": "Foot Locker Inc",
    "FLIR": "FLIR Systems Inc",
    "FLT": "FleetCor Technologies Inc",
    "FRC": "First Republic Bank",
    "FRX": "Forest Laboratories Inc",
    "FTR": "Frontier Communications Parent Inc",
    "GAS": "AGL Resources Inc",
    "GGP": "General Growth Properties Inc",
    "GMCR": "Keurig Green Mountain Inc",
    "GPS": "Gap Inc",
    "HAR": "Harman International Industries Inc",
    "HBI": "Hanesbrands Inc",
    "HCBK": "Hudson City Bancorp Inc",
    "HCP": "HCP Inc",
    "HES": "Hess Corp",
    "HFC": "HollyFrontier Corp",
    "HNZ": "H J Heinz Co",
    "HOLX": "Hologic Inc",
    "HOT": "Starwood Hotels & Resorts Worldwide Inc",
    "HRS": "Harris Corp",
    "HSP": "Hospira Inc",
    "IGT": "International Game Technology PLC",
    "IPG": "Interpublic Group of Companies Inc",
    "JCP": "J C Penney Co Inc",
    "JEC": "Jacobs Engineering Group Inc",
    "JNPR": "Juniper Networks Inc",
    "JOY": "Joy Global Inc",
    "JWN": "Nordstrom Inc",
    "K": "Kellanova",
    "KORS": "Michael Kors Holdings Ltd",
    "KRFT": "Kraft Foods Group Inc",
    "KSU": "Kansas City Southern",
    "LLL": "L3 Technologies Inc",
    "LLTC": "Linear Technology Corp",
    "LM": "Legg Mason Inc",
    "LO": "Lorillard Inc",
    "LSI": "LSI Corp",
    "LVLT": "Level 3 Communications Inc",
    "MJN": "Mead Johnson Nutrition Co",
    "MMC": "Marsh & McLennan Companies Inc",
    "MNK": "Mallinckrodt plc",
    "MOLX": "Molex Inc",
    "MON": "Monsanto Co",
    "MRO": "Marathon Oil Corp",
    "MWV": "MeadWestvaco Corp",
    "MXIM": "Maxim Integrated Products Inc",
    "MYL": "Mylan N V",
    "NBL": "Noble Energy Inc",
    "NLOK": "NortonLifeLock Inc",
    "NLSN": "Nielsen Holdings plc",
    "NYX": "NYSE Euronext Inc",
    "PBCT": "People's United Financial Inc",
    "PCP": "Precision Castparts Corp",
    "PDCO": "Patterson Companies Inc",
    "PEAK": "Healthpeak Properties Inc",
    "PETM": "PetSmart Inc",
    "PKI": "PerkinElmer Inc",
    "PLL": "Pall Corp",
    "PX": "Praxair Inc",
    "PXD": "Pioneer Natural Resources Co",
    "QEP": "QEP Resources Inc",
    "RAI": "Reynolds American Inc",
    "RDC": "Rowan Companies plc",
    "RE": "Everest Re Group Ltd",
    "RHT": "Red Hat Inc",
    "RTN": "Raytheon Co",
    "SATS": "EchoStar Corp",
    "SCG": "SCANA Corp",
    "SEE": "Sealed Air Corp",
    "SIAL": "Sigma Aldrich Corp",
    "SIVB": "SVB Financial Group",
    "SNI": "Scripps Networks Interactive Inc",
    "SRCL": "Stericycle Inc",
    "STJ": "St Jude Medical Inc",
    "SWN": "Southwestern Energy Co",
    "SWY": "Safeway Inc",
    "SYMC": "Symantec Corp",
    "TEG": "Integrys Energy Group Inc",
    "TGNA": "TEGNA Inc",
    "TIF": "Tiffany & Co",
    "TMK": "Torchmark Corp",
    "TSS": "Total System Services Inc",
    "TWC": "Time Warner Cable Inc",
    "TWTR": "Twitter Inc",
    "TWX": "Time Warner Inc",
    "UTX": "United Technologies Corp",
    "VAR": "Varian Medical Systems Inc",
    "VIAB": "Viacom Inc",
    "VIAC": "ViacomCBS Inc",
    "WBA": "Walgreens Boots Alliance Inc",
    "WCG": "WellCare Health Plans Inc",
    "WFM": "Whole Foods Market Inc",
    "WIN": "Windstream Holdings Inc",
    "WLTW": "Willis Towers Watson plc",
    "WPX": "WPX Energy Inc",
    "WRK": "WestRock Co",
    "WYND": "Wyndham Worldwide Corp",
    "X": "United States Steel Corp",
    "XEC": "Cimarex Energy Co",
    "XL": "XL Group Ltd",
    "XLNX": "Xilinx Inc",
    # gap tickers that DID get price data but might still lack a CIK match
    "APC": "Anadarko Petroleum Corp",
    "AVB": "AvalonBay Communities Inc",
    "BBBY": "Bed Bath & Beyond Inc",
    "CA": "CA Inc",
    "CAM": "Cameron International Corp",
    "CSRA": "CSRA Inc",
    "EA": "Electronic Arts Inc",
    "EMC": "EMC Corp",
    "EQR": "Equity Residential",
    "FB": "Facebook Inc",
    "INFO": "IHS Markit Ltd",
    "NAVI": "Navient Corp",
    "NFX": "Newfield Exploration Co",
    "PCL": "Plum Creek Timber Co Inc",
}


def load_already_matched():
    if not EXISTING_MAP_CSV.exists():
        print(f"WARNING: {EXISTING_MAP_CSV} not found -- run local_fundamentals_pull_delisted.py "
              f"first so this script knows what's already matched. Proceeding as if nothing is "
              f"matched yet.")
        return set()
    matched = set()
    with open(EXISTING_MAP_CSV) as f:
        for row in csv.DictReader(f):
            if row["status"] == "matched":
                matched.add(row["ticker"])
    return matched


def http_get_json(url, retries=3):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                return json.loads(resp.read()), None
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


CIK_RE = re.compile(r"CIK\s*(\d{10})", re.IGNORECASE)


def lookup_cik_by_name(company_name):
    """Query SEC EDGAR's full text search index by company name. Returns
    (cik, matched_display_name) or (None, reason)."""
    q = urllib.parse.quote(f'"{company_name}"')
    url = f"https://efts.sec.gov/LATEST/search-index?q={q}&forms=10-K"
    data, err = http_get_json(url)
    if data is None:
        return None, err

    hits = data.get("hits", {}).get("hits", [])
    if not hits:
        return None, "no hits"

    src = hits[0].get("_source", {})
    ciks = src.get("ciks") or []
    display_names = src.get("display_names") or []
    if ciks:
        cik = str(ciks[0]).zfill(10)
        name = display_names[0] if display_names else company_name
        return cik, name

    # fallback: pull CIK out of the display_names string like "RED HAT INC (CIK 0001087423)"
    for name in display_names:
        m = CIK_RE.search(name)
        if m:
            return m.group(1).zfill(10), name

    return None, "hit found but no CIK extractable"


def main():
    already_matched = load_already_matched()
    to_lookup = {t: name for t, name in TICKER_COMPANY_NAMES.items() if t not in already_matched}

    print(f"{len(already_matched)} tickers already matched by the automatic pull. "
          f"Attempting name-based CIK lookup for {len(to_lookup)} more via SEC EDGAR full text "
          f"search (efts.sec.gov)...")

    resolved = {}
    misses = []
    for i, (ticker, name) in enumerate(sorted(to_lookup.items()), 1):
        cik, info = lookup_cik_by_name(name)
        if cik:
            resolved[ticker] = {"cik": cik, "matched_name": info, "queried_name": name}
            print(f"[{i}/{len(to_lookup)}] {ticker} ({name}) -> CIK {cik}  ({info})")
        else:
            misses.append((ticker, name, info))
            print(f"[{i}/{len(to_lookup)}] {ticker} ({name}) -> NO MATCH ({info})")
        time.sleep(REQUEST_DELAY_SECONDS)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    overrides_path = OUT_DIR / "manual_cik_overrides.json"
    with open(overrides_path, "w") as f:
        json.dump({t: v["cik"] for t, v in resolved.items()}, f, indent=2)

    report_lines = [
        f"CIK name-lookup: resolved {len(resolved)}/{len(to_lookup)} additional tickers "
        f"(on top of {len(already_matched)} already matched automatically).",
        "",
        "SPOT-CHECK a few of these before trusting them -- verify at",
        "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=<cik>&type=10-K",
        "that the CIK really is the company you expect, not a similarly-named one.",
        "",
        "Resolved:",
    ] + [f"  {t}: CIK {v['cik']}  (queried '{v['queried_name']}', matched '{v['matched_name']}')"
         for t, v in sorted(resolved.items())] + [
        "",
        "Still unmatched (may need a manual EDGAR company search, or the company never filed "
        "10-Ks under this name, e.g. a foreign private issuer that files 20-F instead):",
    ] + [f"  {t} ({name}): {reason}" for t, name, reason in misses]

    report = "\n".join(report_lines)
    print("\n" + report)
    with open(OUT_DIR / "_cik_lookup_report.txt", "w") as f:
        f.write(report + "\n")

    print(f"\nDone. {overrides_path} is ready for local_fundamentals_pull_delisted_v2.py.")


if __name__ == "__main__":
    main()
