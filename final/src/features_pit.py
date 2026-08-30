"""
Point-in-time (survivorship-bias-corrected) price/feature panel. Companion
to features.py -- reuses its build_features() unchanged, but builds the
raw panel from BOTH the current universe (scripts/td_data_local/) and the
211 point-in-time gap tickers (scripts/td_data_delisted/, produced by
local_data_pull_delisted.py) -- see that script's docstring, and
pit_universe.py, for the full background on why.

Two things this does differently from features.py's own pipeline:

1. Merges in the delisted/gap tickers so they exist in the panel at all
   (features.py alone never sees them -- they're not in td_data_local/).

2. Fixes a real bug that would otherwise sabotage the whole point of this
   exercise: build_features()'s forward-return label is close.shift(-40),
   which is NaN for the last ~40 rows of ANY ticker's history -- for a
   currently-active ticker that's just "hasn't happened yet," correctly
   left as NaN. But for a DELISTED ticker, a NaN label there means "this
   stock stopped trading (bankruptcy, acquisition close, whatever) before
   the 40-day window resolved" -- and the standard backtest script drops
   any picked stock with a NaN label from the $ simulation ENTIRELY
   (picks_with_realized = top_picks.dropna(subset=[LABEL_COL])). Silently
   dropping a stock that went bankrupt right after being picked doesn't
   just fail to help this -- it defeats the entire fix, by hiding the
   downside exactly where it would show up. apply_delisting_exit_floor()
   below patches this: for gap tickers only, any NaN label gets replaced
   with (last available close / pick-date close - 1) -- the actual
   realized outcome, whether that's a bankruptcy wipeout (the pulled price
   series already reflects the crash toward the delisting date) or a
   fair-value acquisition (the deal price). Tickers still in the live
   universe are untouched -- their NaN tail is the normal "hasn't resolved
   yet" case and should stay NaN.

Note: DATA_DIR (scripts/td_data_local/) also contains the regime-gate
series (^VIX.csv, GLD.csv, HYG.csv, TLT.csv, ^TNX.csv) pulled earlier for
the HMM gate -- these get explicitly excluded here so they can never be
treated as scoreable "stocks." Worth flagging separately: features.py's
own load_all_tickers() does NOT exclude them, which means a future
"Retrain ALL models" run on the real app could technically let the model
see (though probably not favor) VIX/GLD/HYG/TLT rows as pickable tickers.
Not fixed here -- out of scope for this survivorship-bias pass, and Gabe
asked for nothing to touch the app/production pipeline right now -- but
worth a small fix later.

Usage:
    python3 features_pit.py

Output: out/features_pit.parquet
"""
import json

import pandas as pd

from features import (DATA_DIR, PROJECT_ROOT, OUT_DIR, FORWARD_WINDOW, LABEL_COL,
                       build_features, atomic_to_parquet)
from pit_universe import ALL_GAP_TICKERS, membership_summary

DELISTED_DATA_DIR = PROJECT_ROOT / "scripts" / "td_data_delisted"
NON_STOCK_FILES = {"^VIX", "^TNX", "GLD", "HYG", "TLT"}  # regime-gate series, not stocks

# Momentum_120 + pct_from_high/low_252 need real trailing history, not just
# a handful of rows, to mean anything -- a ticker needs data starting at
# least this many calendar days before a timepoint's snapshot date to be
# trusted for that timepoint at all.
MIN_TRAILING_DAYS = 380

# Approximate (month-level, not exact-day) TRUE delisting/acquisition-close
# dates for gap tickers, built from general knowledge -- used ONLY as a
# safety net in apply_delisting_exit_floor(), added 2026-08-28 when
# local_data_pull_delisted_v2.py introduced a second data source (a 2017
# snapshot dataset) whose per-ticker files can end mid-life rather than at
# a real delisting, for any company that didn't actually fail until after
# the snapshot was taken. Without this check, that kind of truncation
# would get silently treated as "the company went to zero here," which
# is wrong and would corrupt the backtest in the opposite direction of
# the bias this whole exercise is trying to fix. Deliberately
# conservative: a ticker NOT in this dict skips the safety check
# entirely (falls back to trusting the data's last date, same behavior
# as before this safeguard existed) -- only tickers explicitly listed
# here get the extra protection. Coverage is not exhaustive; extend as
# more tickers are identified. Dates are "YYYY-MM-01" precision, checked
# with a generous +/-120 day tolerance.
KNOWN_DELISTING_DATES = {
    "AABA": "2019-06-01", "ABMD": "2022-12-01", "AET": "2018-11-01", "AGN": "2020-05-01",
    "ALTR": "2015-12-01", "ALXN": "2021-07-01", "ANDV": "2018-10-01", "APOL": "2016-02-01",
    "ARG": "2016-05-01", "ATVI": "2023-10-01", "BCR": "2017-12-01", "BIG": "2024-05-01",
    "BMC": "2013-09-01", "BMS": "2019-08-01", "BRCM": "2016-02-01", "CBS": "2019-12-01",
    "CCE": "2016-05-01", "CELG": "2019-11-01", "CERN": "2022-06-01", "CFN": "2015-03-01",
    "COL": "2018-11-01", "COV": "2015-01-01", "CTXS": "2022-09-01", "CVC": "2016-06-01",
    "CVH": "2013-05-01", "CXO": "2021-01-01", "DF": "2019-11-01", "DISCA": "2022-04-01",
    "DISCK": "2022-04-01", "DNB": "2019-02-01", "DRE": "2022-10-01", "DTV": "2015-07-01",
    "ESRX": "2018-12-01", "ETFC": "2020-10-01", "EVHC": "2018-10-01", "FDO": "2015-07-01",
    "FLIR": "2021-05-01", "FRC": "2023-05-01", "FRX": "2014-07-01", "GAS": "2016-07-01",
    "GGP": "2018-08-01", "GMCR": "2016-03-01", "HAR": "2017-03-01", "HCBK": "2015-11-01",
    "HNZ": "2013-06-01", "HOT": "2016-09-01", "HRS": "2019-06-01", "HSP": "2015-09-01",
    "JCP": "2020-05-01", "JOY": "2017-04-01", "KRFT": "2015-07-01", "KSU": "2021-12-01",
    "LLL": "2019-06-01", "LLTC": "2017-03-01", "LM": "2020-07-01", "LO": "2015-06-01",
    "LSI": "2014-05-01", "LVLT": "2017-11-01", "MJN": "2017-06-01", "MOLX": "2013-04-01",
    "MON": "2018-06-01", "MWV": "2015-07-01", "MXIM": "2021-08-01", "MYL": "2020-11-01",
    "NBL": "2020-10-01", "NYX": "2013-11-01", "PBCT": "2022-04-01", "PCP": "2016-01-01",
    "PETM": "2015-03-01", "PLL": "2015-08-01", "PX": "2018-10-01", "QEP": "2021-03-01",
    "RAI": "2017-07-01", "RDC": "2019-05-01", "RHT": "2019-07-01", "RTN": "2020-04-01",
    "SCG": "2019-01-01", "SIAL": "2015-11-01", "SIVB": "2023-03-01", "SNI": "2018-03-01",
    "STJ": "2017-01-01", "SWY": "2015-01-01", "TEG": "2015-06-01", "TIF": "2021-01-01",
    "TSS": "2019-09-01", "TWC": "2016-05-01", "TWTR": "2022-10-01", "TWX": "2018-06-01",
    "UTX": "2020-04-01", "VAR": "2021-04-01", "WCG": "2020-01-01", "WFM": "2017-08-01",
    "WPX": "2021-01-01", "X": "2025-06-01", "XL": "2018-09-01", "XLNX": "2022-02-01",
    "APC": "2019-08-01", "BBBY": "2023-05-01", "CA": "2018-07-01", "CAM": "2016-04-01",
    "CSRA": "2018-04-01", "EMC": "2016-09-01", "INFO": "2022-02-01", "PCL": "2016-02-01",
    # 2024-2025 deals (verified via web search 2026-08-28, since these are
    # recent enough that training knowledge alone wasn't reliable):
    "MRO": "2024-11-01",   # ConocoPhillips completed acquisition 2024-11-22
    "HES": "2025-07-01",   # Chevron completed acquisition 2025-07-18
    "JNPR": "2025-07-01",  # HPE completed acquisition 2025-07 (after DOJ settlement)
    "WBA": "2025-08-01",   # Sycamore Partners completed take-private 2025-08-28/29
    "IPG": "2025-10-01",   # Omnicom completed acquisition, exchange offers finalized ~Sep-Oct 2025
    "JWN": "2025-05-01",   # Nordstrom family/Liverpool take-private, announced 2024-12, closed ~mid-2025 (approximate)
}
DELISTING_DATE_TOLERANCE_DAYS = 120


def load_all_tickers_pit():
    frames = []
    for f in sorted(DATA_DIR.glob("*.csv")):
        ticker = f.stem
        if ticker in NON_STOCK_FILES:
            continue
        df = pd.read_csv(f, parse_dates=["date"])
        df["ticker"] = ticker
        frames.append(df)
    n_current = len(frames)

    if DELISTED_DATA_DIR.exists():
        for f in sorted(DELISTED_DATA_DIR.glob("*.csv")):
            ticker = f.stem
            df = pd.read_csv(f, parse_dates=["date"])
            df["ticker"] = ticker
            frames.append(df)
    n_gap = len(frames) - n_current

    if n_gap == 0:
        print("WARNING: no files found in td_data_delisted/ -- run local_data_pull_delisted.py "
              "first, or this panel is identical to the biased one.")

    data = pd.concat(frames, ignore_index=True)
    # if a ticker somehow exists in both dirs, keep the current-universe copy
    data = data.drop_duplicates(subset=["ticker", "date"], keep="first")
    data = data.sort_values(["ticker", "date"]).reset_index(drop=True)
    return data, n_current, n_gap


def validate_gap_coverage(delisted_dir):
    """Yahoo Finance recycles delisted ticker symbols for unrelated new
    companies -- confirmed in practice on this pull: APC, AVB, BBBY, CA,
    CAM, CSRA, EQR and others came back with only a handful of rows dated
    mid-to-late 2026, not the historical company (Anadarko Petroleum,
    AvalonBay, the pre-2023-bankruptcy Bed Bath & Beyond, CA Technologies,
    Cameron International, CSRA Inc., ...) that was actually the point-in-
    time S&P 500 member. yf.download() just returns whatever is CURRENTLY
    trading under that symbol -- it has no notion of "the same company
    that used to trade here." Silently treating that as the historical
    entity's data would be worse than not having it at all: it would
    misrepresent what was actually investable at the relevant timepoint,
    potentially in either direction.

    A gap ticker only counts as valid FOR A GIVEN TIMEPOINT if its pulled
    CSV's earliest available date is at least MIN_TRAILING_DAYS before
    that timepoint's snapshot date -- enough for the rolling-252-day
    features to have real trailing history, and a strong signal (though
    not ironclad proof) that this is actually the pre-delisting company's
    own price series, not a reused symbol's unrelated recent trading.

    Returns (valid: {timepoint: [tickers]}, quarantined: [(ticker,
    earliest_date, [timepoints it fails])]) and writes both to
    out/pit_gap_ticker_validation.json for backtest_pit.py to consume.
    """
    membership = membership_summary()
    valid_by_ticker = {}
    quarantined = []

    if not delisted_dir.exists():
        return {}, []

    for f in sorted(delisted_dir.glob("*.csv")):
        ticker = f.stem
        try:
            df = pd.read_csv(f, usecols=["date"], parse_dates=["date"])
        except Exception:
            continue
        if df.empty:
            continue
        earliest = df["date"].min()

        relevant_tps = [tp for tp, v in membership.items() if ticker in v["gap"]]
        ok, bad = [], []
        for tp in relevant_tps:
            snap = pd.Timestamp(membership[tp]["snapshot_date_used"])
            if earliest <= snap - pd.Timedelta(days=MIN_TRAILING_DAYS):
                ok.append(tp)
            else:
                bad.append(tp)

        if ok:
            valid_by_ticker[ticker] = ok
        if bad:
            quarantined.append((ticker, str(earliest.date()), bad))

    valid_by_timepoint = {}
    for ticker, tps in valid_by_ticker.items():
        for tp in tps:
            valid_by_timepoint.setdefault(tp, []).append(ticker)

    out = {
        "valid_by_timepoint": valid_by_timepoint,
        "quarantined": [{"ticker": t, "earliest_date": e, "failed_timepoints": tps}
                         for t, e, tps in quarantined],
    }
    with open(OUT_DIR / "pit_gap_ticker_validation.json", "w") as f:
        json.dump(out, f, indent=2)

    n_fully_quarantined = len([t for t, _, _ in quarantined if t not in valid_by_ticker])
    print(f"Gap-ticker coverage validation: {len(valid_by_ticker)} tickers cleared for at least "
          f"one timepoint, {n_fully_quarantined} fully quarantined (likely a recycled ticker "
          f"symbol, not the historical company) -- see out/pit_gap_ticker_validation.json.")
    if quarantined[:15]:
        print("First few quarantine flags (ticker, earliest date found, timepoints it fails):")
        for t, e, tps in quarantined[:15]:
            print(f"  {t}: earliest={e}  fails={tps}")

    return valid_by_timepoint, quarantined


def apply_delisting_exit_floor(feat: pd.DataFrame, gap_tickers, label_col: str) -> pd.DataFrame:
    feat = feat.copy()
    gap_set = set(gap_tickers)
    present = sorted(set(feat.loc[feat["ticker"].isin(gap_set), "ticker"].unique()))
    fixed_count = 0
    skipped_untrusted = []
    for ticker in present:
        idx = feat.index[feat["ticker"] == ticker]
        g = feat.loc[idx].sort_values("date")
        last_date = g["date"].iloc[-1]

        # Safety net (added when local_data_pull_delisted_v2.py introduced a
        # second data source that can end mid-life rather than at a real
        # delisting -- see KNOWN_DELISTING_DATES's docstring above). If we
        # have a known true delisting date for this ticker, only trust
        # "last available close" as a real exit price when the data
        # actually ends near that date; otherwise this is very likely just
        # a data-source cutoff (e.g. the Kaggle 2017 snapshot) catching a
        # company mid-life, not a real failure -- leave the label NaN
        # rather than fabricate an exit price.
        known = KNOWN_DELISTING_DATES.get(ticker)
        if known is not None:
            gap_days = abs((last_date - pd.Timestamp(known)).days)
            if gap_days > DELISTING_DATE_TOLERANCE_DAYS:
                skipped_untrusted.append((ticker, str(last_date.date()), known))
                continue

        last_close = g["close"].iloc[-1]
        need_fix = g[label_col].isna()
        n = int(need_fix.sum())
        if n:
            feat.loc[g.index[need_fix], label_col] = last_close / g.loc[need_fix, "close"] - 1
            fixed_count += n
    print(f"Delisting exit-floor fix: relabeled {fixed_count} rows across "
          f"{len(present) - len(skipped_untrusted)}/{len(gap_set)} gap tickers found in the "
          f"panel (NaN forward-return -> exit at last available close, instead of being "
          f"silently dropped from the $ simulation).")
    if skipped_untrusted:
        print(f"  Skipped the exit-floor fix for {len(skipped_untrusted)} ticker(s) whose data "
              f"ends far from their known true delisting date (likely a truncated-but-still-"
              f"alive series, not a real failure) -- labels left NaN for these instead of risking "
              f"a false exit price: "
              + ", ".join(f"{t} (data ends {d}, known delisting ~{k})"
                           for t, d, k in skipped_untrusted[:10])
              + (" ..." if len(skipped_untrusted) > 10 else ""))
    return feat


def main():
    print("Loading merged price panel (current universe + point-in-time gap tickers)...")
    raw, n_current, n_gap = load_all_tickers_pit()
    gap_present = raw[raw["ticker"].isin(ALL_GAP_TICKERS)]["ticker"].nunique()
    print(f"Loaded {raw['ticker'].nunique()} tickers total ({n_current} files from the current "
          f"universe, {n_gap} from td_data_delisted/ -- {gap_present}/{len(ALL_GAP_TICKERS)} of "
          f"the 211 gap tickers actually found), {len(raw)} rows, "
          f"{raw['date'].min().date()} to {raw['date'].max().date()}")

    feat = build_features(raw)
    feat = apply_delisting_exit_floor(feat, ALL_GAP_TICKERS, LABEL_COL)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    validate_gap_coverage(DELISTED_DATA_DIR)

    out_path = OUT_DIR / "features_pit.parquet"
    atomic_to_parquet(feat, out_path)
    print(f"\nSaved -> {out_path}  shape={feat.shape}")


if __name__ == "__main__":
    main()
