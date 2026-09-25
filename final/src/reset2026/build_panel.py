"""
Assemble the single working panel the composite reads: base price/fundamentals
columns + the four new quality factors + the three existing-panel factors
(net issuance, short interest, earnings-filing timing) + sector + the
down-cap universe eligibility flags. One (ticker, date) row per trading day.

Every source panel below shares the SAME 12,270,047-row (ticker, date) grid --
they are all built from `features_sharadar_pit.parquet` plus one added column
family, per RUNBOOK's "new panel, don't overwrite" convention -- so this is a
column-wise join, not a row-wise one, and row count should not change except
where `downcap_universe.parquet` (a different source grid: Sharadar's raw
daily/stocks panel, not the feature pipeline) fails to match on (ticker,
date). That mismatch rate is measured and logged, not assumed away.

OUTPUT
    <MAIN_ROOT>/out/reset2026/composite_panel.parquet
"""
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

MAIN_ROOT = Path("/Users/ggraham/pipe_dream/final")
OUT_DIR = MAIN_ROOT / "out" / "reset2026"
OUT = OUT_DIR / "composite_panel.parquet"

BASE_PANEL = MAIN_ROOT / "out" / "features_with_fundamentals_sharadar_pit.parquet"
ISSUANCE_PANEL = MAIN_ROOT / "out" / "features_with_issuance_sharadar_pit.parquet"
SHORT_INT_PANEL = MAIN_ROOT / "out" / "features_with_short_interest_sharadar_pit.parquet"
EVENTS_PANEL = MAIN_ROOT / "out" / "features_with_events_sharadar_pit.parquet"
QUALITY_PANEL = OUT_DIR / "quality_factors.parquet"
DOWNCAP_UNIVERSE = MAIN_ROOT / "data" / "sharadar" / "downcap_universe.parquet"
TICKERS_MASTER = MAIN_ROOT / "data" / "sharadar" / "tickers_master.csv"

BASE_COLS = ["ticker", "date", "open", "close", "market_cap",
             "volatility_60", "pct_from_high_252",
             "forward_return_40", "forward_return_tradable_40"]


def log(msg):
    print(msg, flush=True)


def main():
    t0 = time.time()

    log(f"loading base panel ({BASE_PANEL.name}) ...")
    panel = pd.read_parquet(BASE_PANEL, columns=BASE_COLS)
    panel["ticker"] = panel["ticker"].astype(str)
    panel["date"] = pd.to_datetime(panel["date"])
    n0 = len(panel)
    log(f"  {n0:,} rows, {panel['ticker'].nunique():,} tickers ({time.time()-t0:.0f}s)")

    def merge_col(path, cols, label):
        nonlocal panel
        add = pd.read_parquet(path, columns=["ticker", "date"] + cols)
        add["ticker"] = add["ticker"].astype(str)
        add["date"] = pd.to_datetime(add["date"])
        before = len(panel)
        panel = panel.merge(add, on=["ticker", "date"], how="left")
        assert len(panel) == before, f"{label} merge changed row count"
        cov = panel[cols[0]].notna().mean()
        log(f"  + {label} {cols}: coverage {cov:.1%} ({time.time()-t0:.0f}s)")

    merge_col(ISSUANCE_PANEL, ["net_issuance_pct"], "issuance")
    merge_col(SHORT_INT_PANEL, ["short_interest_days_to_cover"], "short interest")
    merge_col(EVENTS_PANEL, ["days_to_next_filing_seasonal"], "events")
    merge_col(QUALITY_PANEL, ["gross_profitability", "accruals", "asset_growth", "momentum_12_1"], "quality")

    assert len(panel) == n0, "row count drifted across the column merges"

    log("merging sector (tickers_master.csv, current classification) ...")
    master = pd.read_csv(TICKERS_MASTER, dtype=str, usecols=["ticker", "sector"])
    master = master.drop_duplicates(subset="ticker", keep="first")
    panel = panel.merge(master, on="ticker", how="left")
    panel["sector"] = panel["sector"].fillna("Unknown")
    log(f"  sector coverage {(panel['sector'] != 'Unknown').mean():.1%}, "
        f"{panel['sector'].nunique()} distinct sectors ({time.time()-t0:.0f}s)")

    log("merging down-cap universe eligibility (separate source grid -- match rate matters) ...")
    uni = pd.read_parquet(DOWNCAP_UNIVERSE,
                           columns=["ticker", "date", "eligible_cap2000",
                                    "eligible_cap500", "eligible_cap150"])
    uni["ticker"] = uni["ticker"].astype(str)
    uni["date"] = pd.to_datetime(uni["date"])
    before = len(panel)
    panel = panel.merge(uni, on=["ticker", "date"], how="left")
    assert len(panel) == before, "universe merge changed row count"
    for c in ("eligible_cap2000", "eligible_cap500", "eligible_cap150"):
        panel[c] = panel[c].fillna(False)
        log(f"  {c}: {int(panel[c].sum()):,} eligible rows "
            f"({panel[c].mean():.1%} of panel)")
    # Sanity check against the standalone universe report: cap2000 should
    # land close to the deployed model's known ~1,600-name current universe
    # and to pit_universe_report.txt's per-date counts, not off by an order
    # of magnitude (that would mean a ticker-symbol mismatch between this
    # panel's grid and downcap_universe.parquet's grid, e.g. class-share
    # suffixes or a delisted-ticker aliasing issue).
    matched = int((uni.set_index(["ticker", "date"]).index
                   .isin(panel.set_index(["ticker", "date"]).index)).sum())
    log(f"  {matched:,} of {len(uni):,} downcap_universe rows found a matching "
        f"(ticker, date) in the feature panel ({matched/len(uni):.1%})")

    panel = panel.sort_values(["ticker", "date"]).reset_index(drop=True)
    panel["date"] = panel["date"].dt.strftime("%Y-%m-%d")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pandas(panel, preserve_index=False), OUT)
    log(f"\n-> {OUT}  ({len(panel):,} rows, {time.time()-t0:.0f}s total)")


if __name__ == "__main__":
    sys.exit(main())
