"""
Run this ON YOUR OWN MACHINE (not through Claude) -- same reason
local_data_pull.py exists: the cloud sandbox's network allowlist blocks
Yahoo Finance entirely (confirmed via curl: query1/query2.finance.yahoo.com,
stooq.com, and data.sec.gov all time out / connection-refused from the
sandbox; only pypi.org, registry.npmjs.org, and raw.githubusercontent.com
are reachable there). Your own machine's normal internet connection has
none of these restrictions.

WHY THIS SCRIPT EXISTS -- survivorship bias fix (2026-08-28):

Gabe asked (after questioning why the backtest numbers looked implausibly
good) to rebuild the training/backtest universe so it isn't survivorship-
biased. The existing 1,620-ticker universe (universe/2026-08-27-expanded-
universe-methodology.md) was built by screening for companies worth >$2B
TODAY and applying that list retroactively across the whole 2013-2026
backtest -- which means any company that was a real, investable candidate
at some point in that window, but later went bankrupt, got delisted, or
fell below the size/price floor, simply never appears in the backtest.
That's a serious, known bias (already flagged in models/final-buy-no-buy-
model.md's "Known limitations": "Survivorship bias from the current-
screen-applied-retroactively approach") and it disproportionately hides
exactly the failure mode this model is most exposed to, since the price-
only model has learned to chase the most volatile names in the universe.

This script pulls price history for the 211 tickers identified as GAPS:
companies that were actual S&P 500 constituents on at least one of the 8
backtest timepoints (2013-01-02, 2015-01-02, 2017-01-03, 2019-01-02,
2021-01-04, 2023-01-03, 2025-01-02, 2026-06-01) but are NOT in today's
1,620-ticker universe -- because they were later acquired, delisted,
renamed, or went bankrupt. Source: point-in-time S&P 500 membership
snapshots from https://github.com/fja05680/sp500 (the "Historical
Components & Changes (Updated)" file, 1996 through 2026-06-30, plus the
"changes_since_2019" file), diffed against the current universe's ticker
list. See scripts/pit_universe/ for the full derivation (gap_summary_per_
timepoint.json has the per-timepoint breakdown -- e.g. 154 of 497 S&P 500
constituents from 2013-01-02, 31% of the index, are missing from today's
universe).

Output goes to a SEPARATE directory (td_data_delisted/, NOT td_data_local/)
so this never gets mixed into the live production universe or touches
current_signal.py / current_signal_gated.py / the app -- Gabe was explicit
that nothing should be pushed to the app while this is being sorted out.
It's consumed only by the new point-in-time-aware backtest script.

Same output schema as local_data_pull.py: one CSV per ticker at
./td_data_delisted/{TICKER}.csv, columns [date, open, high, low, close,
volume].

Known limitation: Yahoo Finance does NOT reliably retain price history for
companies delisted long enough ago or obscurely enough (very old
bankruptcies especially) -- this script will legitimately fail for some
tickers, and that's expected, not a bug. It tries the plain ticker first,
then a "Q" suffix (the standard convention for a company trading OTC
post-Chapter-11, e.g. a hypothetical "XYZQ"), and logs everything it
couldn't get in _delisted_pull_report.txt so the gap is visible rather
than silent.

Usage:
    pip install yfinance pandas
    python3 local_data_pull_delisted.py

Re-running is resumable (SKIP_EXISTING below).
"""
import sys
import time
from pathlib import Path

try:
    import yfinance as yf
except ImportError:
    print("Missing dependency. Run: pip install yfinance pandas")
    sys.exit(1)

import pandas as pd

OUT_DIR = Path(__file__).parent / "td_data_delisted"
START_DATE = "2006-01-01"  # matches local_data_pull.py's depth
SKIP_EXISTING = True
SLEEP_BETWEEN = 0.5

# 211 tickers: real S&P 500 constituents at one of the 8 backtest
# timepoints, not in today's 1,620-ticker universe. See scripts/
# pit_universe/gap_tickers_all.txt (this list) and gap_summary_per_
# timepoint.json (which timepoint(s) each one matters for, and why it's
# missing -- acquired, delisted, bankrupt, renamed, or just resized below
# the current $2B/$10 floor).
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


def yf_symbol(ticker: str) -> str:
    return ticker.replace(".", "-")


def _clean(df):
    if df is None or df.empty:
        return None
    df = df.reset_index()
    df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
    df = df.rename(columns={
        "Date": "date", "Open": "open", "High": "high",
        "Low": "low", "Close": "close", "Volume": "volume",
    })
    return df[["date", "open", "high", "low", "close", "volume"]]


def pull_ticker(ticker: str):
    """Try the plain ticker, then a Q-suffix (standard post-Chapter-11 OTC
    convention). Returns (df, symbol_used) or (None, None)."""
    for symbol in (yf_symbol(ticker), yf_symbol(ticker) + "Q"):
        try:
            df = yf.download(symbol, start=START_DATE, progress=False, auto_adjust=False)
        except Exception:
            continue
        df = _clean(df)
        if df is not None and len(df) > 5:
            return df, symbol
    return None, None


def main():
    OUT_DIR.mkdir(exist_ok=True)
    tickers = GAP_TICKERS
    if SKIP_EXISTING:
        before = len(tickers)
        tickers = [t for t in tickers if not (OUT_DIR / f"{t}.csv").exists()]
        if before - len(tickers):
            print(f"SKIP_EXISTING on: {before - len(tickers)} already pulled, skipping those.")

    print(f"Pulling {len(tickers)} delisted/gap tickers into {OUT_DIR}/ ...")
    ok, failed = 0, []
    for i, t in enumerate(tickers, 1):
        try:
            df, symbol_used = pull_ticker(t)
            if df is None:
                failed.append(t)
                print(f"[{i}/{len(tickers)}] {t}: no data from Yahoo (plain or Q-suffix) -- "
                      f"likely purged (older/obscure delisting) or needs a manual ticker fix")
            else:
                df.to_csv(OUT_DIR / f"{t}.csv", index=False)
                tag = f" (as {symbol_used})" if symbol_used != yf_symbol(t) else ""
                print(f"[{i}/{len(tickers)}] {t}{tag}: {len(df)} rows, "
                      f"{df['date'].min()} to {df['date'].max()}")
                ok += 1
        except Exception as e:
            print(f"[{i}/{len(tickers)}] {t}: FAILED - {e}")
            failed.append(t)
        if SLEEP_BETWEEN:
            time.sleep(SLEEP_BETWEEN)

    report = (
        f"Delisted/gap ticker pull: {ok}/{len(tickers)} succeeded, {len(failed)} failed.\n\n"
        f"Failed (no usable data found): {', '.join(failed) if failed else '(none)'}\n\n"
        f"A handful of failures here is expected and fine -- this doesn't fully undo the "
        f"survivorship-bias fix, it just means those specific names' effect on the corrected "
        f"backtest can't be measured. Re-run this script (SKIP_EXISTING will only retry "
        f"failures) if you want to try again after a manual ticker-symbol fix.\n"
    )
    print("\n" + report)
    (OUT_DIR / "_delisted_pull_report.txt").write_text(report)
    print(f"Done. Send the td_data_delisted/ folder back the same way you'd send td_data_local/.")


if __name__ == "__main__":
    main()
