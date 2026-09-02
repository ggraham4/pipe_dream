"""
Point-in-time (survivorship-bias-corrected) fundamentals panel. Companion
to fundamentals_features_beta.py -- reuses its per-ticker processing logic
unchanged (process_ticker, build_ticker_fact_series, asof_lookup, the
stock/flow concept lists), but merges fundamentals from BOTH the current
universe (scripts/fundamentals_raw/) and the 211 point-in-time gap tickers
(scripts/fundamentals_raw_delisted/, produced by
local_fundamentals_pull_delisted.py), and merges onto features_pit.parquet
(the survivorship-bias-corrected price panel) instead of features.parquet.
See features_pit.py and pit_universe.py for the full background.

Usage:
    python3 fundamentals_features_pit.py

Output: out/features_with_fundamentals_pit.parquet
"""
import gc

import numpy as np
import pandas as pd

from features import OUT_DIR, PROJECT_ROOT, atomic_to_parquet
from fundamentals_features_beta import (
    STOCK_CONCEPTS, FLOW_CONCEPTS, FUNDAMENTAL_FEATURE_COLS,
    process_ticker,
)

FUNDAMENTALS_RAW_DIR = PROJECT_ROOT / "scripts" / "fundamentals_raw"
FUNDAMENTALS_RAW_DELISTED_DIR = PROJECT_ROOT / "scripts" / "fundamentals_raw_delisted"


def load_fundamentals_raw_pit():
    import glob
    import os

    frames = []
    for d in (FUNDAMENTALS_RAW_DIR, FUNDAMENTALS_RAW_DELISTED_DIR):
        if not d.exists():
            continue
        files = [f for f in glob.glob(str(d / "*.csv")) if not os.path.basename(f).startswith("_")]
        for f in files:
            df = pd.read_csv(f, parse_dates=["filed_date"],
                              usecols=["ticker", "concept", "form", "fiscal_period", "filed_date", "value"])
            frames.append(df)
    if not frames:
        raise SystemExit("No fundamentals CSVs found in fundamentals_raw/ or "
                          "fundamentals_raw_delisted/ -- run the two local_*_pull*.py scripts first.")
    combined = pd.concat(frames, ignore_index=True)
    # a ticker present in both dirs (shouldn't happen) -- keep the current-universe copy
    combined = combined.drop_duplicates(subset=["ticker", "concept", "form", "fiscal_period", "filed_date"])
    return combined


def main():
    print("Loading point-in-time price feature panel (features_pit.parquet)...")
    price_pit_path = OUT_DIR / "features_pit.parquet"
    if not price_pit_path.exists():
        raise SystemExit(f"{price_pit_path} not found -- run features_pit.py first.")
    price_full = pd.read_parquet(price_pit_path)
    # ticker_orig (added by price_discontinuity.py, features_pit.py) holds the
    # REAL symbol even for a segmented "TICKER__postYYYYMMDD" row -- needed
    # below so a split ticker's post-break segment still finds its real
    # fundamentals data, which is naturally filed under the real symbol only.
    has_ticker_orig = "ticker_orig" in price_full.columns
    lean_cols = ["ticker", "date", "close"] + (["ticker_orig"] if has_ticker_orig else [])
    price_lean = price_full[lean_cols].sort_values(["ticker", "date"]).reset_index(drop=True)

    print("Loading raw fundamentals pull (current universe + point-in-time gap tickers)...")
    raw = load_fundamentals_raw_pit()
    print(f"  {raw['ticker'].nunique()} tickers, {len(raw)} raw fact rows, "
          f"filed {raw['filed_date'].min().date()} to {raw['filed_date'].max().date()}")
    raw_by_ticker = {t: g for t, g in raw.groupby("ticker", sort=False)}
    del raw
    gc.collect()

    print("Grouping price panel by ticker...")
    if has_ticker_orig:
        orig_by_segment = price_lean.drop_duplicates("ticker").set_index("ticker")["ticker_orig"].to_dict()
        price_lean = price_lean.drop(columns=["ticker_orig"])
    else:
        orig_by_segment = {}
    price_by_ticker = {t: g for t, g in price_lean.groupby("ticker", sort=False)}
    del price_lean
    gc.collect()

    tickers = list(price_by_ticker.keys())
    print(f"Processing {len(tickers)} tickers, one pass each...")

    pieces = []
    for i, ticker in enumerate(tickers, 1):
        price_g = price_by_ticker[ticker]
        # look up real fundamentals under the ORIGINAL symbol for a segmented
        # ticker (e.g. "CHRD__post20201118" -> "CHRD"); a non-segmented
        # ticker's orig equals itself, same lookup either way
        raw_g = raw_by_ticker.get(orig_by_segment.get(ticker, ticker))
        pieces.append(process_ticker(ticker, price_g, raw_g))
        if i % 200 == 0:
            print(f"  {i}/{len(tickers)} tickers done")

    fundamentals_panel = pd.concat(pieces, ignore_index=True)
    del pieces, price_by_ticker, raw_by_ticker
    gc.collect()

    for col in FUNDAMENTAL_FEATURE_COLS:
        fundamentals_panel[col] = fundamentals_panel[col].replace([np.inf, -np.inf], np.nan).astype("float32")

    print("\nCoverage of derived ratios (non-null share of ALL price rows):")
    for col in FUNDAMENTAL_FEATURE_COLS:
        print(f"  {col:<22} {fundamentals_panel[col].notna().mean():.1%}")

    merged = price_full.merge(fundamentals_panel, on=["ticker", "date"], how="left")
    del price_full, fundamentals_panel
    gc.collect()

    out_path = OUT_DIR / "features_with_fundamentals_pit.parquet"
    atomic_to_parquet(merged, out_path)
    print(f"\nSaved -> {out_path}  shape={merged.shape}")


if __name__ == "__main__":
    main()
