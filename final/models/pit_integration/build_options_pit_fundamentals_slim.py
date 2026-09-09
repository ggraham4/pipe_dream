"""
Step 1 of the options-model PIT integration (2026-09-02).

Extracts a slim, ticker/column-filtered copy of
final/out/features_with_fundamentals_pit.parquet (928MB, 7.09M rows, every
PIT-tracked ticker including 264 delisted gap tickers) down to just the
market_cap/price/fundamentals columns for the tickers that actually appear
in the options training data (496 tickers -- the options universe never
included the delisted gap tickers to begin with, since DoltHub's options
history only exists for names that were listed and trading).

Uses pyarrow.dataset predicate pushdown (filter applied at the row-group
level, not a full pandas load) specifically because the full panel is large
enough to OOM a device-bridge shell (~3.8GB RAM) -- see AGENTS.md's
"Sandbox note for AI assistants". This script must run on Gabe's own
machine (same reason every other script touching features_with_fundamentals
_pit.parquet does), but is lightweight enough (<2s, ~40MB output) to run
directly via the device-bridge shell, unlike the full-panel scripts.

Run from final/:  python3 models/pit_integration/build_options_pit_fundamentals_slim.py
"""
import os
import time

import pandas as pd
import pyarrow.dataset as ds
import pyarrow.parquet as pq

CALLS_TRAINING = "data/training/options_calls_training.parquet"
FUND_PIT_PANEL = "out/features_with_fundamentals_pit.parquet"
OUT_PATH = "data/options_pit_fundamentals_slim.parquet"

SLIM_COLS = [
    "date", "ticker", "close", "market_cap", "pe_ratio", "pb_ratio", "ps_ratio",
    "debt_to_equity", "roe", "roa", "gross_margin", "operating_margin",
    "fcf_margin", "revenue_growth_yoy", "earnings_growth_yoy",
    "rnd_intensity", "fundamentals_age_days",
]

t0 = time.time()
calls = pd.read_parquet(CALLS_TRAINING, columns=["act_symbol"])
tickers = sorted(calls["act_symbol"].unique().tolist())
print(f"{len(tickers)} tickers in the options training universe", flush=True)

dataset = ds.dataset(FUND_PIT_PANEL, format="parquet")
table = dataset.to_table(columns=SLIM_COLS, filter=ds.field("ticker").isin(tickers))
print(f"{table.num_rows:,} rows extracted, {time.time() - t0:.1f}s", flush=True)

pq.write_table(table, OUT_PATH, compression="zstd")
print(f"Wrote {OUT_PATH} ({os.path.getsize(OUT_PATH):,} bytes)", flush=True)
