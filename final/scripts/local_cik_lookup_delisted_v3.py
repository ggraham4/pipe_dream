"""
Run this ON YOUR OWN MACHINE (not through Claude). Fixes a bug in
local_cik_lookup_delisted_v2.py's validator, which was ALSO wrong (sorry
-- second bug in a row on this specific piece). v2 checked whether the
ticker literally appeared in SEC's "tickers" field from
data.sec.gov/submissions/CIK##########.json. That field only lists a
company's CURRENTLY ACTIVE ticker(s) -- for a company that's been
delisted, renamed, or merged, its old ticker is simply never in that
list, even when the CIK is exactly correct. Running v2 therefore
quarantined almost everything, including plenty of matches that were
actually right (e.g. RHT -> CIK 0001087423 "RED HAT INC" is exactly
correct, but got flagged WRONG because "RHT" isn't Red Hat's current
ticker -- Red Hat doesn't have one anymore, it's a private IBM
subsidiary).

This script re-validates properly using the RIGHT field: submissions.json
also has "name" (the entity's current legal name) and "formerNames" (a
full history of every name that CIK has ever filed under, with date
ranges) -- exactly what you want when a delisted company was later
renamed by its acquirer (e.g. Alliance Data Systems Corp -> Bread
Financial Holdings, Inc., same CIK, correct match) or converted to an LLC
subsidiary post-acquisition. A ticker's expected company name is checked
against BOTH the current name and every former name; it only needs to
match one of them.

What this does:
  1. Restores anything from fundamentals_raw_delisted/_quarantined_wrong_cik/
     whose CIK re-validates correctly under the proper name-history check
     (the v2 run over-quarantined -- this un-does the false positives).
  2. Keeps quarantined (and tries to re-resolve via SEC's company NAME
     registry search, same as v2) anything that still doesn't validate.
  3. Writes the corrected, validated manual_cik_overrides.json.

Usage:
    python3 local_cik_lookup_delisted_v3.py

Then re-run local_fundamentals_pull_delisted_v2.py (SKIP_EXISTING means
it will only pull for tickers newly added back to the overrides file that
don't already have a CSV).
"""
import json
import re
import time
import urllib.request
import urllib.error
import urllib.parse
import xml.etree.ElementTree as ET
from difflib import SequenceMatcher
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
OUT_DIR = SCRIPT_DIR / "fundamentals_raw_delisted"
OVERRIDES_PATH = OUT_DIR / "manual_cik_overrides.json"
QUARANTINE_DIR = OUT_DIR / "_quarantined_wrong_cik"

USER_AGENT = "pipe_dream research sirduckingtoniii@gmail.com"
REQUEST_DELAY_SECONDS = 0.25

from local_cik_lookup_delisted import TICKER_COMPANY_NAMES

# The 171 candidate CIKs from the v2 run's output (before that run's
# broken validator quarantined them) -- re-validating these properly
# instead of re-querying full-text search again. EA (CIK 0000712515) is
# not here because v2's check happened to already confirm it correctly.
CANDIDATE_CIKS = {
    "AABA": "0001610532", "ABC": "0000722104", "ABMD": "0000815094", "ADS": "0001101215",
    "AET": "0001122304", "AGN": "0001578845", "ALTR": "0000768251", "ALXN": "0000899866",
    "ANDV": "0000050104", "ANSS": "0001013462", "ANTM": "0001156039", "APOL": "0000929887",
    "ARG": "0000804212", "ARNC": "0000004281", "ATVI": "0000718877", "AVP": "0000008868",
    "BCR": "0000009892", "BIG": "0000768835", "BK": "0001390777", "BLL": "0000812074",
    "BMC": "0000835729", "BMS": "0000042542", "BRCM": "0001649345", "BTUUQ": "0001064728",
    "CA": "0000895930", "CAM": "0000098222", "CBS": "0000813828", "CCE": "0000804055",
    "CDAY": "0001725057", "CELG": "0001302573", "CERN": "0001268904", "CFN": "0000109261",
    "CHK": "0000895126", "CMA": "0000028412", "COG": "0000858470", "COL": "0001137411",
    "COV": "0001385187", "CSRA": "0001646383", "CTL": "0000018926", "CTLT": "0001596783",
    "CTRA": "0000858470", "CTXS": "0000877890", "CVC": "0001020620", "CVH": "0001054833",
    "CXO": "0001358071", "DAY": "0001725057", "DF": "0000802481", "DFS": "0001393612",
    "DISCA": "0001437107", "DISCK": "0001437107", "DISH": "0001568319", "DNB": "0001115222",
    "DNR": "0000945764", "DO": "0000949039", "DRE": "0000912242", "DTV": "0000826773",
    "DWDP": "0001666700", "EMC": "0000064247", "ENDP": "0002008861", "EQR": "0000906107",
    "ESRX": "0000052428", "ESV": "0000314808", "ETFC": "0001015780", "EVHC": "0001588272",
    "FB": "0001326801", "FBHS": "0001519751", "FDO": "0000034408", "FI": "0000798354",
    "FL": "0000850209", "FLIR": "0000354908", "FLT": "0001175454", "FRC": "0001137138",
    "FRX": "0000038074", "FTR": "0000020520", "GAS": "0001004155", "GGP": "0001496048",
    "GMCR": "0000909954", "GPS": "0000039911", "HAR": "0000800459", "HBI": "0001359841",
    "HCBK": "0000921847", "HCP": "0000765880", "HES": "0001035002", "HFC": "0000048039",
    "HNZ": "0000046640", "HOLX": "0000859737", "HOT": "0000316206", "HRS": "0000068505",
    "HSP": "0001274057", "IGT": "0001799332", "INFO": "0001598014", "IPG": "0000051644",
    "JCP": "0001166126", "JEC": "0000052988", "JNPR": "0001043604", "JOY": "0000801898",
    "JWN": "0000757439", "K": "0000055067", "KORS": "0000352363", "KRFT": "0001103982",
    "KSU": "0000054480", "LLL": "0001039101", "LLTC": "0001280452", "LM": "0000704051",
    "LO": "0001424847", "LSI": "0001201663", "LVLT": "0001044430", "MJN": "0000724024",
    "MMC": "0000062709", "MNK": "0001567892", "MOLX": "0000206005", "MON": "0001110783",
    "MRO": "0001157806", "MWV": "0001163302", "MXIM": "0000743316", "NBL": "0000072207",
    "NFX": "0000849213", "NLOK": "0000849399", "NLSN": "0001492633", "NYX": "0001368007",
    "PBCT": "0001378946", "PCL": "0000849213", "PCP": "0000079958", "PDCO": "0000891024",
    "PEAK": "0000765880", "PETM": "0000863157", "PKI": "0000031791", "PLL": "0000014195",
    "PX": "0000884905", "PXD": "0001349436", "QEP": "0001108827", "RAI": "0001275283",
    "RDC": "0000314808", "RE": "0001095073", "RHT": "0001087423", "RTN": "0000052795",
    "SATS": "0001645494", "SCG": "0000787250", "SEE": "0000200406", "SIAL": "0000090185",
    "SIVB": "0000719739", "SNI": "0001430602", "SRCL": "0000861878", "STJ": "0000203077",
    "SWN": "0000787250", "SWY": "0000086144", "SYMC": "0001098277", "TEG": "0000916863",
    "TGNA": "0000039899", "TIF": "0000098246", "TMK": "0000055362", "TSS": "0000721683",
    "TWC": "0001005757", "TWTR": "0001418091", "TWX": "0001105705", "UTX": "0000101829",
    "VAR": "0000203527", "VIAB": "0000813828", "VIAC": "0000813828", "WBA": "0001618921",
    "WCG": "0001279363", "WFM": "0000865436", "WIN": "0001620280", "WLTW": "0001140536",
    "WPX": "0001518832", "WRK": "0000011199", "WYND": "0001434620", "X": "0001163302",
    "XEC": "0000046765", "XL": "0000875159", "XLNX": "0000743988",
}
ALREADY_CONFIRMED = {"EA": "0000712515"}


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


_SUFFIX_RE = re.compile(
    r"\b(INC|CORP|CORPORATION|CO|COMPANY|PLC|LTD|LLC|LP|L P|N V|NEW|DE|PA|THE|GROUP|HOLDINGS?|"
    r"INTERNATIONAL|WORLDWIDE|GLOBAL)\b", re.IGNORECASE)


def normalize_name(name: str) -> str:
    name = re.sub(r"[/\.,\-]", " ", name)
    name = _SUFFIX_RE.sub("", name)
    name = re.sub(r"\s+", " ", name).strip().upper()
    return name


def name_similarity(a: str, b: str) -> float:
    na, nb = normalize_name(a), normalize_name(b)
    if not na or not nb:
        return 0.0
    # token overlap (order-independent, handles "Alliance Data Systems" vs
    # "Bread Financial" correctly scoring low, and "Red Hat" vs "Red Hat"
    # scoring 1.0) combined with a sequence-ratio as a tiebreaker
    ta, tb = set(na.split()), set(nb.split())
    token_overlap = len(ta & tb) / max(1, len(ta | tb))
    seq_ratio = SequenceMatcher(None, na, nb).ratio()
    return max(token_overlap, seq_ratio)


SIMILARITY_THRESHOLD = 0.5


def validate_cik_matches_name(cik: str, expected_name: str):
    """The correct check: does this CIK's current name OR any former name
    in its SEC-tracked history match the expected company name? Returns
    (True/False, best_matching_name, score)."""
    cik_padded = str(cik).zfill(10)
    data, err = http_get(f"https://data.sec.gov/submissions/CIK{cik_padded}.json")
    if data is None:
        return False, None, 0.0

    candidates = [data.get("name", "")]
    for fn in (data.get("formerNames") or []):
        if fn.get("name"):
            candidates.append(fn["name"])

    best_name, best_score = None, 0.0
    for cand in candidates:
        score = name_similarity(expected_name, cand)
        if score > best_score:
            best_name, best_score = cand, score

    return best_score >= SIMILARITY_THRESHOLD, best_name, best_score


CIK_RE = re.compile(r"CIK=(\d+)")


def search_company_name_registry(company_name: str):
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
    confirmed = dict(ALREADY_CONFIRMED)
    restored, still_wrong, fixed, unresolved = [], [], {}, []

    print(f"Re-validating {len(CANDIDATE_CIKS)} candidate CIKs against SEC's name/former-name "
          f"history (the correct check this time)...")
    for i, (ticker, cik) in enumerate(sorted(CANDIDATE_CIKS.items()), 1):
        expected = TICKER_COMPANY_NAMES.get(ticker, ticker)
        ok, matched_name, score = validate_cik_matches_name(cik, expected)
        time.sleep(REQUEST_DELAY_SECONDS)

        if ok:
            confirmed[ticker] = cik
            restored.append(ticker)
            print(f"[{i}/{len(CANDIDATE_CIKS)}] {ticker}: CIK {cik} CONFIRMED "
                  f"(matched '{matched_name}', score {score:.2f})")
            continue

        print(f"[{i}/{len(CANDIDATE_CIKS)}] {ticker}: CIK {cik} still doesn't match "
              f"'{expected}' (best guess was '{matched_name}', score {score:.2f}) -- "
              f"re-resolving via company name search...")
        candidates = search_company_name_registry(expected)
        resolved = None
        for cand_cik, cand_title in candidates:
            ok2, matched_name2, score2 = validate_cik_matches_name(cand_cik, expected)
            time.sleep(REQUEST_DELAY_SECONDS)
            if ok2:
                resolved = (cand_cik, matched_name2, score2)
                break
        if resolved:
            confirmed[ticker] = resolved[0]
            fixed[ticker] = resolved[0]
            print(f"    -> fixed: CIK {resolved[0]} (matched '{resolved[1]}', score {resolved[2]:.2f})")
        else:
            still_wrong.append(ticker)
            unresolved.append((ticker, expected, [t for _, t in candidates]))
            print(f"    -> still unresolved ({len(candidates)} candidates tried, none validated)")

    # restore quarantined CSVs for anything now confirmed (either as-is or fixed to a NEW cik --
    # if the cik changed, don't restore the old wrong file, it'll get re-pulled fresh)
    n_restored_files = 0
    for ticker in restored:
        q_path = QUARANTINE_DIR / f"{ticker}.csv"
        if q_path.exists():
            q_path.rename(OUT_DIR / f"{ticker}.csv")
            n_restored_files += 1

    with open(OVERRIDES_PATH, "w") as f:
        json.dump(confirmed, f, indent=2)

    report_lines = [
        f"CIK re-validation (v3, correct name/former-name check): "
        f"{len(restored)}/{len(CANDIDATE_CIKS)} of the v2 candidates were ACTUALLY correct all "
        f"along (v2's ticker-field check was itself the bug) and got restored, "
        f"{n_restored_files} quarantined CSVs moved back. {len(fixed)} were genuinely wrong and "
        f"got re-resolved to a different, correct CIK (will need re-pulling). "
        f"{len(still_wrong)} still unresolved.",
        "",
        "Genuinely fixed (was wrong, now a different validated CIK):",
    ] + [f"  {t}: -> CIK {c}" for t, c in sorted(fixed.items())] + [
        "",
        "Still unresolved (stayed quarantined; local_fundamentals_pull_delisted_v2.py will "
        "simply skip these until you resolve them manually):",
    ] + [f"  {t} ({name}): tried {cands}" for t, name, cands in unresolved]

    report = "\n".join(report_lines)
    print("\n" + report)
    with open(OUT_DIR / "_cik_validation_v3_report.txt", "w") as f:
        f.write(report + "\n")

    n_remaining_quarantine = len(list(QUARANTINE_DIR.glob("*.csv")))
    print(f"\nDone. manual_cik_overrides.json now has {len(confirmed)} validated tickers. "
          f"{n_remaining_quarantine} CSVs remain quarantined (still wrong/unresolved). "
          f"Re-run local_fundamentals_pull_delisted_v2.py to pull data for the {len(fixed)} "
          f"newly-fixed tickers.")


if __name__ == "__main__":
    main()
