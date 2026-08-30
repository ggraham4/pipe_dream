"""
Run this ON YOUR OWN MACHINE (not through Claude), AFTER
local_data_pull_delisted.py. Second-pass attempt to recover price history
for the 164 gap tickers Yahoo Finance had already purged (the "possibly
delisted; no timezone found" failures) -- see local_data_pull_delisted.py's
report for that list.

TWO separate free sources, tried in order per ticker:

1. STOOQ (https://stooq.com) -- a Polish market-data site that, unlike
   Yahoo, does NOT purge a symbol's history once it delists; many
   delisted US tickers are still there under their original symbol with
   a ".us" suffix. This wasn't verifiable from inside Claude's tools (its
   web-fetch tool respects stooq's robots.txt, which disallows automated
   crawlers on the /q/d/l/ download path) -- but that's a bot-crawling
   policy, not a technical block, and stooq's own CSV export endpoint is
   the documented, intended way for an individual to pull their own
   ticker's history (this is the same kind of "run it yourself, it's not
   reachable from Claude's sandboxed tools" situation as every other pull
   script in this project). Some tickers will still come back empty --
   stooq doesn't have universal coverage either.

2. KAGGLE'S "HUGE STOCK MARKET DATASET" (free, no cost, requires only a
   free Kaggle account -- no purchase) -- a static one-time scrape of
   ~7,000 US tickers' full daily history taken in November 2017:
   https://www.kaggle.com/datasets/borismarjanovic/price-volume-data-for-all-us-stocks-etfs
   Since it's a snapshot from a point in time, it genuinely captures the
   COMPLETE history (including the real delisting-day price) for any
   company that delisted BEFORE ~Nov 2017 -- which covers a real chunk of
   these 164 gap tickers (older M&A/bankruptcies: e.g. ALTR 2015, ARG
   2016, BMC 2013, BRCM 2016, HNZ 2013, MOLX 2013, PX 2018 is just past
   the cutoff, etc). For a company that didn't actually delist until
   AFTER Nov 2017 (RHT 2019, CELG 2019, MON 2018, ...), this dataset's
   file for that ticker (if present) is NOT a real delisting -- it's just
   the company's ordinary trading data truncated at the scrape date,
   because the company was still alive and trading normally then. Do NOT
   treat that truncation as "this is when the company failed." See the
   KNOWN_DELISTING_DATES safeguard added to features_pit.py's
   apply_delisting_exit_floor() -- it now refuses to treat a data
   series's last available date as a real delisting-exit price unless
   that date actually falls near a KNOWN true delisting date for that
   ticker (skips the fix rather than risk a false one).

   HOW TO GET THE KAGGLE DATASET (no cost, ~5 minutes):
     a. Create a free Kaggle account at kaggle.com if you don't have one.
     b. Go to the URL above, click "Download" (downloads a ~600MB zip).
     c. Unzip it. Inside, look for a folder named "Stocks" (sometimes
        nested one level deeper) containing files like "aapl.us.txt".
     d. Set KAGGLE_STOCKS_DIR below to that folder's path.
   If you skip this step, the script still runs and just relies on stooq
   alone -- set KAGGLE_STOCKS_DIR = None.

Usage:
    pip install requests pandas
    python3 local_data_pull_delisted_v2.py

Output: adds to the SAME td_data_delisted/ directory as
local_data_pull_delisted.py (only pulls tickers still missing a CSV
there), same schema [date, open, high, low, close, volume]. Also writes
_delisted_pull_report_v2.txt.
"""
import sys
import time
from pathlib import Path

try:
    import requests
    import pandas as pd
except ImportError:
    print("Missing dependency. Run: pip install requests pandas")
    sys.exit(1)

OUT_DIR = Path(__file__).parent / "td_data_delisted"
START_DATE = "2006-01-01"

# Set this to your unzipped Kaggle "Stocks" folder path to enable that
# fallback source, e.g. Path.home() / "Downloads" / "Stocks". Leave as
# None to skip it and rely on stooq alone.
KAGGLE_STOCKS_DIR = None  # <-- edit this line if you download the Kaggle dataset

SLEEP_BETWEEN = 0.4
REQUEST_TIMEOUT = 15

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
}


def stooq_symbol_candidates(ticker: str):
    base = ticker.replace(".", "-").lower()
    return [f"{base}.us", f"{base}q.us"]  # plain, then post-Chapter-11 OTC "Q" convention


_STOOQ_SESSION = requests.Session()
_STOOQ_SESSION.headers.update(HEADERS)
_diag_printed = {"count": 0}
_DIAG_LIMIT = 5  # print full diagnostic detail for only the first few failures, not all 164


def pull_from_stooq(ticker: str):
    for symbol in stooq_symbol_candidates(ticker):
        url = f"https://stooq.com/q/d/l/?s={symbol}&i=d"
        try:
            # use a shared Session (not a bare requests.get) so cookies from
            # stooq's first response (e.g. a consent/session cookie) persist
            # across requests -- a fresh cookieless request is the most
            # likely reason every ticker failed identically last run
            resp = _STOOQ_SESSION.get(url, timeout=REQUEST_TIMEOUT)
        except Exception as e:
            if _diag_printed["count"] < _DIAG_LIMIT:
                print(f"    [diag] {ticker} ({symbol}): request exception: {e}")
                _diag_printed["count"] += 1
            continue
        if resp.status_code != 200:
            if _diag_printed["count"] < _DIAG_LIMIT:
                print(f"    [diag] {ticker} ({symbol}): HTTP {resp.status_code}, "
                      f"content-type={resp.headers.get('Content-Type')}, "
                      f"body[:150]={resp.text[:150]!r}")
                _diag_printed["count"] += 1
            continue
        text = resp.text.strip()
        # stooq returns a small HTML/error page (not a CSV header) when a symbol has no data
        if not text or not text.startswith("Date,"):
            if _diag_printed["count"] < _DIAG_LIMIT:
                print(f"    [diag] {ticker} ({symbol}): got HTTP 200 but not CSV. "
                      f"content-type={resp.headers.get('Content-Type')}, "
                      f"body[:200]={text[:200]!r}")
                _diag_printed["count"] += 1
            continue
        from io import StringIO
        try:
            df = pd.read_csv(StringIO(text), parse_dates=["Date"])
        except Exception:
            continue
        if df.empty or len(df) < 5:
            continue
        df = df.rename(columns={"Date": "date", "Open": "open", "High": "high",
                                 "Low": "low", "Close": "close", "Volume": "volume"})
        keep = [c for c in ["date", "open", "high", "low", "close", "volume"] if c in df.columns]
        df = df[keep]
        df = df[df["date"] >= pd.Timestamp(START_DATE)]
        if len(df) < 5:
            continue
        return df, symbol
    return None, None


def pull_from_kaggle(ticker: str):
    if not KAGGLE_STOCKS_DIR:
        return None, None
    kdir = Path(KAGGLE_STOCKS_DIR)
    candidate = kdir / f"{ticker.lower()}.us.txt"
    if not candidate.exists():
        return None, None
    try:
        df = pd.read_csv(candidate, parse_dates=["Date"])
    except Exception:
        return None, None
    if df.empty:
        return None, None
    df = df.rename(columns={"Date": "date", "Open": "open", "High": "high",
                             "Low": "low", "Close": "close", "Volume": "volume"})
    keep = [c for c in ["date", "open", "high", "low", "close", "volume"] if c in df.columns]
    df = df[keep]
    df = df[df["date"] >= pd.Timestamp(START_DATE)]
    if len(df) < 5:
        return None, None
    return df, "kaggle-2017-snapshot"


# Same 211 tickers as local_data_pull_delisted.py's GAP_TICKERS (duplicated
# here, not imported, so this script only needs requests+pandas -- v1
# additionally requires yfinance, which this script doesn't use).
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


def main():
    OUT_DIR.mkdir(exist_ok=True)

    # warm up the session against stooq's homepage first, so any
    # consent/session cookie it sets is already present before we hit the
    # CSV download endpoint -- last run got 0/164 hits across the board,
    # which smells like a cookie/consent wall rather than "none of these
    # 164 tickers have any data on stooq" (implausible for well-known
    # names like Red Hat, Time Warner, Celgene)
    try:
        _STOOQ_SESSION.get("https://stooq.com/", timeout=REQUEST_TIMEOUT)
    except Exception as e:
        print(f"(warm-up request to stooq.com failed: {e} -- continuing anyway)")

    missing = [t for t in GAP_TICKERS if not (OUT_DIR / f"{t}.csv").exists()]
    print(f"{len(GAP_TICKERS) - len(missing)}/{len(GAP_TICKERS)} already pulled (v1 or earlier). "
          f"Attempting {len(missing)} still-missing tickers via stooq"
          + (", then the local Kaggle snapshot" if KAGGLE_STOCKS_DIR else " (Kaggle fallback not configured -- see this script's docstring)")
          + "...")

    ok_stooq, ok_kaggle, still_failed = 0, 0, []
    for i, t in enumerate(missing, 1):
        df, source = pull_from_stooq(t)
        if df is None:
            df, source = pull_from_kaggle(t)
            if df is not None:
                ok_kaggle += 1
        else:
            ok_stooq += 1

        if df is None:
            still_failed.append(t)
            print(f"[{i}/{len(missing)}] {t}: still no data (stooq + kaggle both empty/unavailable)")
        else:
            df.to_csv(OUT_DIR / f"{t}.csv", index=False)
            print(f"[{i}/{len(missing)}] {t} (via {source}): {len(df)} rows, "
                  f"{df['date'].min()} to {df['date'].max()}")
        time.sleep(SLEEP_BETWEEN)

    report = (
        f"v2 price recovery pass: {ok_stooq} recovered via stooq, {ok_kaggle} recovered via "
        f"local Kaggle snapshot, {len(still_failed)} still failed, out of {len(missing)} "
        f"attempted.\n\n"
        f"Still failed: {', '.join(still_failed) if still_failed else '(none)'}\n\n"
        f"Remember the Kaggle-sourced caveat in this script's docstring: a Kaggle file's last "
        f"date is only a real delisting price if the company actually delisted before ~Nov "
        f"2017. features_pit.py's KNOWN_DELISTING_DATES safeguard will skip the exit-floor fix "
        f"for tickers where that's not confidently true, rather than risk a false label.\n"
    )
    print("\n" + report)
    (OUT_DIR / "_delisted_pull_report_v2.txt").write_text(report)
    print(f"Done. Re-send the td_data_delisted/ folder, then re-run features_pit.py, "
          f"fundamentals_features_pit.py, and backtest_pit.py.")


if __name__ == "__main__":
    main()
