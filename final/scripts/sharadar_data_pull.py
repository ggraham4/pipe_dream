"""
Run this ON YOUR OWN MACHINE (not through Claude) -- same reason every
other local_*.py script in this folder exists: this needs live network
access to a paid API, which isn't reachable from Claude's cloud sandbox
or (for some providers) even the device-bridge shell.

WHAT THIS DOES

Pulls price history for the 211 survivorship-bias "gap tickers" (real S&P
500 constituents at some backtest timepoint, missing from today's
universe -- see backtest/survivorship-bias-correction-results.md in the
Claude Project) from Sharadar's own REST API (api.sharadar.com), which
Gabe subscribed to specifically to close this gap. This supersedes the
free/DIY stooq+Kaggle attempt in local_data_pull_delisted_v2.py -- Sharadar
is a real point-in-time securities database that's supposed to have
correct, complete delisted-security history, not a live-quote service
that recycles ticker symbols.

Output goes to the SAME place the old Yahoo/Kaggle pull wrote to --
td_data_delisted/{TICKER}.csv, same schema (date, open, high, low, close,
volume) -- so features_pit.py needs ZERO changes to pick this up. Any
existing file there gets moved aside to
td_data_delisted/_pre_sharadar_backup/ first (never overwritten silently),
in case Sharadar's data for a given ticker turns out to be worse or
missing and you want the old partial data back.

ALSO pulls real fundamentals (added 2026-09-01, after the first run's
schema probe came back and was verified against actual row data, not just
column names -- see "FUNDAMENTALS SCHEMA MAPPING" below) into
fundamentals_raw_delisted/{TICKER}.csv, in the EXACT SAME long/tidy
schema local_fundamentals_pull_delisted*.py already produces (ticker, cik,
concept, tag_used, unit, fiscal_year, fiscal_period, period_end,
filed_date, form, accn, value) -- so fundamentals_features_pit.py needs
ZERO changes to pick this up either, same as the price pull. Any existing
fundamentals_raw_delisted/{TICKER}.csv (from the old SEC-CIK pipeline)
gets backed up to fundamentals_raw_delisted/_pre_sharadar_backup/ first,
never silently overwritten -- same convention as the price pull.

FUNDAMENTALS SCHEMA MAPPING -- verified against real row data, not just
column names, specifically to avoid a repeat of the SEC-CIK-lookup
saga (two wrong versions before a correct one -- see
backtest/survivorship-bias-correction-results.md Round 2b/2c):
  - Sharadar's "dimension" column tags each row's reporting granularity.
    Confirmed by inspecting real AAPL rows: "ARQ" = as-reported quarterly
    (one row per fiscal quarter, filed on its own date -- e.g. AAPL's
    1993 Q4 row has date=1994-01-26, a realistic ~4-6 week filing lag
    after the 1993-12-31 quarter end). "ARY" = as-reported annual (one
    row per fiscal year, revenue/etc are the true annual total, not a
    Q4-only figure -- confirmed AAPL FY2025 ARY revenue $416.161B differs
    from the FY2025-Q4 ARQ row's $102.466B, i.e. ARQ's Q4 row is discrete
    quarterly, not cumulative). "MRQ"/"MRY"/"MRT" and "ART" (most-recent
    restated, and trailing-twelve-month) are deliberately NOT used here
    -- MR* would leak later-restated figures into a supposedly
    point-in-time value, breaking exactly the discipline this whole
    Sharadar migration exists to protect.
  - Sharadar's "date" column (not "lastupdated", which is a constant
    "when Sharadar's DB last refreshed this row" timestamp, not a filing
    date) is used as filed_date -- confirmed by the same AAPL row above:
    "date" tracks real historical filing lag row-by-row, "lastupdated"
    doesn't. This is the single most safety-critical mapping decision
    here: fundamentals_features_beta.py's point-in-time join
    (merge_asof, filed_date <= price date) depends entirely on this being
    a real historical filing date, not today's refresh date.
  - ARY rows are written with form="10-K", fiscal_period="FY" (parsed
    from Sharadar's "fiscalperiod" field, e.g. "2025-FY" -> "FY"); ARQ
    rows with form="10-Q", fiscal_period=the quarter code (e.g. "Q3").
    This matters because fundamentals_features_beta.py's FLOW_CONCEPTS
    (revenue, net_income, etc.) are filtered to annual-only
    (form in ("10-K","10-K/A") & fiscal_period=="FY") to avoid the
    quarterly cumulative-vs-discrete XBRL ambiguity already documented
    there -- so only ARY rows actually feed flow concepts. STOCK_CONCEPTS
    (total_assets, equity, etc.) use whichever's most recently filed,
    ARQ or ARY, same as before.
  - Concept name -> Sharadar column: revenue->revenue, net_income->netinc,
    gross_profit->gp, operating_income->opinc, total_assets->assets,
    total_liabilities->liabilities, stockholders_equity->equity,
    long_term_debt->debtnc, cash->cashneq, eps_diluted->epsdil,
    eps_basic->eps, shares_outstanding->sharesbas,
    operating_cash_flow->ncfo, capex->capex, rnd_expense->rnd.
    shares_outstanding_dei has no Sharadar equivalent and is left NaN --
    process_ticker() in fundamentals_features_beta.py already falls back
    to shares_outstanding when the _dei variant is missing, so this is
    harmless, not a gap.
  - UNVERIFIED, worth a sanity check after running: Sharadar's
    "sharesbas" for AAPL's 1996 fiscal year read ~13.9B shares in the
    schema-probe data, which doesn't obviously square with Apple's real
    pre-split-adjusted share count at that time. Possibly a
    split-adjustment convention difference (retroactively adjusted like
    closeadj is), possibly a Sharadar backfill quirk -- not something
    this script can resolve without vendor docs, but market_cap and
    pe_ratio in the final feature panel are worth a plausibility check
    for older delisted tickers once this runs.

SETUP

1. Sign up at https://sharadar.com/subscribe -- pick the **Bundle plan,
   Full History tier: $69/month ($499/year)**, not the 10-year tier
   ($49/mo). Pricing is tiered by history depth (5yr/10yr/Full), corrected
   here 2026-09-01 -- an earlier estimate said $49/mo got full history,
   that's actually the 10-year tier's price. Full History matters for
   this project specifically: the backtest's earliest timepoints
   (2013-01-02, 2015-01-02, and marginally 2017-01-03) need trailing
   price history further back than a 10-years-from-today rolling window
   would reach (MIN_TRAILING_DAYS=380 in features_pit.py needs ~1.5yr of
   history *before* each timepoint too) -- the 10-year tier would leave
   ~3 of 8 backtest timepoints without usable Sharadar coverage, right
   where the oldest gap tickers live.
2. Get your API key from your Sharadar account/docs page after signing
   up (Claude could not see this page's exact contents -- it renders
   behind a login session).
3. Set it as an environment variable, don't paste it into this file:
       export SHARADAR_API_KEY="your-key-here"
4. pip install requests   (almost certainly already installed)

Usage:
    python3 sharadar_data_pull.py                  # pull prices AND fundamentals
                                                       for all 211 gap tickers
    python3 sharadar_data_pull.py --skip-prices     # fundamentals only -- use
                                                       this if you already ran
                                                       the price pull and just
                                                       need fundamentals now
    python3 sharadar_data_pull.py --skip-fundamentals  # prices only
    python3 sharadar_data_pull.py --probe-only      # neither -- just the old
                                                       3-ticker schema sanity
                                                       check (schema is already
                                                       confirmed, this is just
                                                       a quick API check now)
    python3 sharadar_data_pull.py --tickers RHT,BBBY  # just these (testing)

NOTE ON API MECHANICS -- READ THIS IF IT DOESN'T WORK FIRST TRY:
Confirmed from Sharadar's own docs (2026-08-30): base URL
https://api.sharadar.com/v1.0/data/{table}?api_key={key}&{params}&format=csv,
tables include "stocks" (equity prices), "fundamentals", "tickers"
(securities master), "actions" (corporate actions), "sp500" (index
membership). The EXACT column names in the response were not confirmed
(the docs page listing them renders behind a login session) -- this
script reads the CSV header row and matches columns by fuzzy
name-matching (e.g. anything containing "date", "close", "adj") rather
than hardcoding exact names, specifically so a small naming difference
doesn't silently break it. If it still fails, the printed error will show
the actual column names/response Sharadar sent back -- paste that back to
Claude and the column-matching logic gets a one-line fix, not a rewrite.
"""
import argparse
import csv
import io
import os
import sys
import time
from pathlib import Path

import requests

SCRIPT_DIR = Path(__file__).parent
TD_DATA_DELISTED = SCRIPT_DIR / "td_data_delisted"
BACKUP_DIR = TD_DATA_DELISTED / "_pre_sharadar_backup"
FUNDAMENTALS_RAW_DELISTED_DIR = SCRIPT_DIR / "fundamentals_raw_delisted"
FUNDAMENTALS_PROBE_DIR = FUNDAMENTALS_RAW_DELISTED_DIR / "_sharadar_schema_probe"
FUNDAMENTALS_BACKUP_DIR = FUNDAMENTALS_RAW_DELISTED_DIR / "_pre_sharadar_backup"

# Concept name (as consumed by fundamentals_features_beta.py's
# STOCK_CONCEPTS/FLOW_CONCEPTS) -> Sharadar fundamentals column name.
# See "FUNDAMENTALS SCHEMA MAPPING" in the module docstring for how each
# of these was verified against real row data, not just column names.
CONCEPT_TO_SHARADAR_COL = {
    # stock (balance-sheet) concepts
    "total_assets": "assets",
    "total_liabilities": "liabilities",
    "stockholders_equity": "equity",
    "cash": "cashneq",
    "long_term_debt": "debtnc",
    "shares_outstanding": "sharesbas",
    # shares_outstanding_dei intentionally omitted -- no Sharadar
    # equivalent; process_ticker() already falls back to
    # shares_outstanding when this is NaN.
    # flow (income-statement/cash-flow) concepts
    "revenue": "revenue",
    "net_income": "netinc",
    "gross_profit": "gp",
    "operating_income": "opinc",
    "operating_cash_flow": "ncfo",
    "capex": "capex",
    "rnd_expense": "rnd",
}
# Concepts that are dollar amounts vs. per-share -- cosmetic only (the
# "unit" column isn't consumed downstream), kept for CSV readability.
PER_SHARE_CONCEPTS = {"eps_diluted", "eps_basic"}
CONCEPT_TO_SHARADAR_COL.update({"eps_diluted": "epsdil", "eps_basic": "eps"})

BASE_URL = "https://api.sharadar.com/v1.0/data"
START_DATE = "2006-01-01"  # matches local_data_pull.py's depth
REQUEST_DELAY_SECONDS = 0.3

API_KEY = os.environ.get("SHARADAR_API_KEY")

# Same 211 tickers as local_data_pull_delisted.py / v2 -- real S&P 500
# constituents at some backtest timepoint, missing from today's universe.
GAP_TICKERS_CORE = [
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

# Added 2026-09-01 to extend PIT candidate-pool coverage back toward 2007-2008
# (Gabe: "Can we go farther back than 2011 with this new data? I'd like to get
# coverage of 2008."). Derived by pit_universe_continuous.py: union of every
# S&P 500 constituent present in scripts/pit_universe/sp500_updated.csv at any
# monthly-sampled snapshot from 1996-01-02 through today, minus tickers already
# in GAP_TICKERS_CORE and minus current_universe_tickers.txt. 128 tickers, many
# recognizable real 2008-financial-crisis names (LEHMQ, WAMUQ, FNMA, FMCC, MER,
# CFC, NCC, SOV, MBI, SGP, WYE, GENZ, XTO, BUD).
#
# CAVEAT (not yet resolved, flagged deliberately rather than guessed at): the
# "Q"-suffixed tickers here (ABKFQ, ANRZQ, CITGQ, LEHMQ, RSHCQ, SUNEQ, WAMUQ,
# CCTYQ, EKDKQ, MTLQQ) are pulled verbatim from sp500_updated.csv, which appears
# to retroactively label some historical snapshot rows with the company's
# eventual post-bankruptcy/delisting-era ticker rather than the symbol it
# actually traded under as a going concern (e.g. Lehman Brothers traded as
# "LEH" before its Sept 2008 bankruptcy, not "LEHMQ"). Rather than hand-guess
# corrections and risk repeating past ticker-mapping mistakes, these ship as-is
# -- the existing graceful-failure reporting in pull_price_history() /
# pull_fundamentals_for_ticker() will cleanly report a miss for any of these
# that Sharadar's API doesn't recognize (same as it already does for 60-68
# other tickers), rather than silently fabricating data. Any well-known name
# that fails here is worth a manual check against Sharadar's own `tickers`
# (securities master) table before adding a hand-crafted symbol override.
GAP_TICKERS_2007_EXTENSION = [
    "ABI", "ABKFQ", "ACAS", "ACS", "ADCT", "AKS", "ANRZQ", "APCC",
    "ASN", "AT", "ATGE", "AV", "AW", "AYE", "BDK", "BJS",
    "BLS", "BMET", "BNI", "BOL", "BRL", "BSC", "BUD", "BXLT",
    "CBE", "CBH", "CBSS", "CCEP", "CCTYQ", "CCU", "CEPH", "CFC",
    "CITGQ", "CMCSK", "CMVT", "CMX", "CPGX", "CPWR", "CTX", "CVG",
    "DDR", "DJ", "EDS", "EKDKQ", "EOP", "EP", "EQ", "FDC",
    "FII", "FMCC", "FNMA", "GENZ", "GR", "HCR", "HET", "HMA",
    "HPC", "HSH", "IAC", "JAVA", "JNS", "JNY", "KATE", "KG",
    "KSE", "LEHMQ", "LXK", "MBI", "MDP", "MEDI", "MEE", "MEL",
    "MER", "MFE", "MHS", "MI", "MIL", "MMI", "MTLQQ", "MTW",
    "MWW", "NCC", "NCR", "NOVL", "NSM", "NVLS", "ODP", "OMX",
    "PBG", "PD", "PGL", "PGN", "PMCS", "PTV", "QLGC", "ROH",
    "RRD", "RSHCQ", "RX", "SAF", "SBL", "SGP", "SHLD", "SII",
    "SLR", "SNV", "SOV", "SSP", "STR", "SUNEQ", "SVU", "TEK",
    "TIE", "TIN", "TLAB", "TRB", "TSG", "TXU", "UIS", "UST",
    "UVN", "WAMUQ", "WB", "WEN", "WFT", "WWY", "WYE", "XTO",
]

GAP_TICKERS = GAP_TICKERS_CORE + GAP_TICKERS_2007_EXTENSION

FUNDAMENTALS_PROBE_TICKERS = ["AAPL", "RHT", "BBBY"]  # AAPL as a sanity check
                                                        # (should always have data)


def _find_col(fieldnames, *substrings):
    """Case-insensitive: return the first column whose name contains ALL
    the given substrings, or None. Used instead of hardcoding exact
    column names, since the exact schema wasn't confirmable from the
    (session-gated) docs -- see the module docstring."""
    for name in fieldnames:
        low = name.lower()
        if all(s in low for s in substrings):
            return name
    return None


def fetch_table(table: str, ticker: str, extra_params: dict = None):
    """GET https://api.sharadar.com/v1.0/data/{table}?api_key=...&ticker=...&format=csv
    Returns (csv.DictReader rows as list of dicts, fieldnames) or (None, None)
    on failure, printing the actual error/response so a real problem is
    visible instead of silently swallowed."""
    params = {"api_key": API_KEY, "ticker": ticker, "format": "csv"}
    if extra_params:
        params.update(extra_params)
    try:
        resp = requests.get(f"{BASE_URL}/{table}", params=params, timeout=30)
    except requests.RequestException as e:
        print(f"    ERROR: request failed: {e}")
        return None, None

    if resp.status_code != 200:
        print(f"    ERROR: HTTP {resp.status_code}: {resp.text[:300]}")
        return None, None

    text = resp.text
    if not text.strip():
        print(f"    (empty response -- no data for {ticker} on {table})")
        return [], []

    reader = csv.DictReader(io.StringIO(text))
    rows = list(reader)
    return rows, reader.fieldnames or []


def pull_price_history(ticker: str) -> bool:
    rows, fieldnames = fetch_table("stocks", ticker, {"from": START_DATE})
    if rows is None:
        return False
    if not rows:
        print(f"    no price rows returned for {ticker}")
        return False

    date_col = _find_col(fieldnames, "date")
    open_col = _find_col(fieldnames, "open")
    high_col = _find_col(fieldnames, "high")
    low_col = _find_col(fieldnames, "low")
    # prefer the split/dividend-ADJUSTED close for a momentum/volatility
    # feature pipeline (unadjusted close has artificial cliffs on split
    # days) -- NOTE this may differ from the original Yahoo pull's
    # convention (local_data_pull_delisted.py used auto_adjust=False);
    # flagged here deliberately, not a silent change -- worth a second
    # look at final/src/features.py before assuming this is fine to mix.
    close_col = _find_col(fieldnames, "closeadj") or _find_col(fieldnames, "close")
    volume_col = _find_col(fieldnames, "volume")

    missing = [n for n, c in [("date", date_col), ("open", open_col), ("high", high_col),
                               ("low", low_col), ("close", close_col), ("volume", volume_col)]
               if c is None]
    if missing:
        print(f"    ERROR: couldn't find columns for {missing} in response. "
              f"Actual columns returned: {fieldnames}")
        print(f"    -> paste this column list back to Claude, the _find_col() "
              f"matching above needs a one-line adjustment.")
        return False

    out_rows = []
    for r in rows:
        try:
            out_rows.append({
                "date": r[date_col],
                "open": r[open_col],
                "high": r[high_col],
                "low": r[low_col],
                "close": r[close_col],
                "volume": r[volume_col],
            })
        except (KeyError, ValueError):
            continue

    if not out_rows:
        print(f"    parsed 0 usable rows for {ticker} (had {len(rows)} raw rows)")
        return False

    out_rows.sort(key=lambda r: r["date"])

    TD_DATA_DELISTED.mkdir(exist_ok=True)
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    dest = TD_DATA_DELISTED / f"{ticker}.csv"
    if dest.exists():
        backup_dest = BACKUP_DIR / f"{ticker}.csv"
        if not backup_dest.exists():  # don't clobber a backup across re-runs
            dest.rename(backup_dest)
        else:
            dest.unlink()

    with open(dest, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["date", "open", "high", "low", "close", "volume"])
        writer.writeheader()
        writer.writerows(out_rows)

    print(f"    {ticker}: {len(out_rows)} rows, {out_rows[0]['date']} to {out_rows[-1]['date']} "
          f"(using '{close_col}' as close)")
    return True


def pull_fundamentals_for_ticker(ticker: str) -> bool:
    """Pull real fundamentals for one ticker into fundamentals_raw_delisted/
    {ticker}.csv, in the exact schema local_fundamentals_pull_delisted*.py
    already uses -- see "FUNDAMENTALS SCHEMA MAPPING" in the module
    docstring for the dimension/date-column/concept-mapping decisions."""
    rows, fieldnames = fetch_table("fundamentals", ticker)
    if rows is None:
        return False
    if not rows:
        print(f"    no fundamentals rows returned for {ticker}")
        return False

    out_rows = []
    for r in rows:
        dimension = r.get("dimension", "")
        if dimension not in ("ARQ", "ARY"):
            continue  # skip MRQ/MRY/MRT (restated, not point-in-time-safe) and ART (TTM, unused)

        filed_date = r.get("date", "")
        if not filed_date:
            continue

        fiscalperiod = r.get("fiscalperiod", "")
        fp_suffix = fiscalperiod.split("-")[-1] if fiscalperiod else ""
        fp_year = fiscalperiod.split("-")[0] if fiscalperiod else ""
        if dimension == "ARY":
            form = "10-K"
            fiscal_period = "FY"
        else:
            form = "10-Q"
            fiscal_period = fp_suffix  # e.g. "Q3"

        for concept, sharadar_col in CONCEPT_TO_SHARADAR_COL.items():
            raw_val = r.get(sharadar_col, "")
            if raw_val in ("", None):
                continue
            try:
                value = float(raw_val)
            except ValueError:
                continue
            out_rows.append({
                "ticker": ticker,
                "cik": "",
                "concept": concept,
                "tag_used": sharadar_col,  # Sharadar's own column name, for traceability
                "unit": "USD/share" if concept in PER_SHARE_CONCEPTS else "USD",
                "fiscal_year": fp_year,
                "fiscal_period": fiscal_period,
                "period_end": r.get("reportperiod", ""),
                "filed_date": filed_date,
                "form": form,
                "accn": "",
                "value": value,
            })

    if not out_rows:
        print(f"    parsed 0 usable fundamentals rows for {ticker} "
              f"(had {len(rows)} raw ARQ/ARY+other rows)")
        return False

    FUNDAMENTALS_RAW_DELISTED_DIR.mkdir(parents=True, exist_ok=True)
    FUNDAMENTALS_BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    dest = FUNDAMENTALS_RAW_DELISTED_DIR / f"{ticker}.csv"
    if dest.exists():
        backup_dest = FUNDAMENTALS_BACKUP_DIR / f"{ticker}.csv"
        if not backup_dest.exists():  # don't clobber a backup across re-runs
            dest.rename(backup_dest)
        else:
            dest.unlink()

    fieldnames_out = ["ticker", "cik", "concept", "tag_used", "unit", "fiscal_year",
                       "fiscal_period", "period_end", "filed_date", "form", "accn", "value"]
    with open(dest, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames_out)
        writer.writeheader()
        writer.writerows(out_rows)

    print(f"    {ticker}: {len(out_rows)} fundamentals facts "
          f"({len({r['concept'] for r in out_rows})} concepts)")
    return True


def probe_fundamentals_schema():
    print(f"\nProbing fundamentals schema for {FUNDAMENTALS_PROBE_TICKERS} "
          f"(not yet wired into fundamentals_features_pit.py -- this is just "
          f"to see the real column names before integrating it)...")
    FUNDAMENTALS_PROBE_DIR.mkdir(parents=True, exist_ok=True)
    for ticker in FUNDAMENTALS_PROBE_TICKERS:
        rows, fieldnames = fetch_table("fundamentals", ticker)
        time.sleep(REQUEST_DELAY_SECONDS)
        if rows is None:
            continue
        if not rows:
            print(f"  {ticker}: no fundamentals rows returned")
            continue
        print(f"  {ticker}: {len(rows)} rows. Columns: {fieldnames}")
        dest = FUNDAMENTALS_PROBE_DIR / f"{ticker}.csv"
        with open(dest, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
    print(f"\nRaw probe files saved in {FUNDAMENTALS_PROBE_DIR}/. Send Claude the "
          f"column list printed above (or these files) to wire up real fundamentals "
          f"pulling next.")


def main():
    if not API_KEY:
        print("ERROR: SHARADAR_API_KEY environment variable not set.\n"
              "Run:  export SHARADAR_API_KEY=\"your-key-here\"\nthen re-run this script.")
        sys.exit(1)

    parser = argparse.ArgumentParser()
    parser.add_argument("--probe-only", action="store_true",
                         help="skip price + fundamentals pulls, just probe the "
                              "fundamentals schema for 3 test tickers (no longer "
                              "needed for schema discovery -- that's done -- but "
                              "still useful as a quick API sanity check)")
    parser.add_argument("--skip-prices", action="store_true",
                         help="skip the price pull (use this on a re-run if prices "
                              "already succeeded and you only need fundamentals)")
    parser.add_argument("--skip-fundamentals", action="store_true",
                         help="skip the fundamentals pull (prices only)")
    parser.add_argument("--tickers", type=str, default=None,
                         help="comma-separated tickers to pull instead of all 211 (for testing)")
    args = parser.parse_args()

    tickers = GAP_TICKERS
    if args.tickers:
        tickers = [t.strip().upper() for t in args.tickers.split(",")]

    if args.probe_only:
        probe_fundamentals_schema()
        return

    if not args.skip_prices:
        print(f"Pulling price history for {len(tickers)} gap tickers from Sharadar...")
        ok, failed = 0, []
        for i, t in enumerate(tickers, 1):
            print(f"[{i}/{len(tickers)}] {t}:")
            if pull_price_history(t):
                ok += 1
            else:
                failed.append(t)
            time.sleep(REQUEST_DELAY_SECONDS)
        print(f"\nPrices done: {ok}/{len(tickers)} succeeded.")
        if failed:
            print(f"Failed/no data ({len(failed)}): {', '.join(failed)}")
        print(f"Old price data for any overwritten ticker backed up to {BACKUP_DIR}/.")

    if not args.skip_fundamentals:
        print(f"\nPulling fundamentals for {len(tickers)} gap tickers from Sharadar...")
        ok, failed = 0, []
        for i, t in enumerate(tickers, 1):
            print(f"[{i}/{len(tickers)}] {t}:")
            if pull_fundamentals_for_ticker(t):
                ok += 1
            else:
                failed.append(t)
            time.sleep(REQUEST_DELAY_SECONDS)
        print(f"\nFundamentals done: {ok}/{len(tickers)} succeeded.")
        if failed:
            print(f"Failed/no data ({len(failed)}): {', '.join(failed)}")
        print(f"Old fundamentals data for any overwritten ticker backed up to "
              f"{FUNDAMENTALS_BACKUP_DIR}/.")
        print("\nRun fundamentals_features_pit.py (from final/src/) to pick these up "
              "-- no code changes needed there.")


if __name__ == "__main__":
    main()
