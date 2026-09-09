"""
Step 1 of the expanded-universe calls training table build: compute the
monthly-expiration calendar and, for each expiration, the nearest available
DoltHub snapshot date to the 30-calendar-day-out entry target (global,
since DoltHub's snapshot dates are the same across the whole DB on any
given day -- confirmed via the dataset's own date column: same set of
dates apply to every ticker). Mirrors the entry/exit mechanics described
in models/options-premium-model-design.md's "Training dataset built"
section (the original build script no longer exists on disk -- a known
gap flagged in AGENTS.md).
"""
from pathlib import Path
import pandas as pd
import numpy as np
import duckdb

REPO_FINAL = Path(__file__).resolve().parents[2]
OPT_PARQUET = REPO_FINAL / "data" / "options_raw" / "expanded" / "option_chain_expanded_merged.parquet"
OUT_DIR = Path(__file__).resolve().parent

con = duckdb.connect()
dates = con.execute(f"SELECT DISTINCT date FROM '{OPT_PARQUET}' ORDER BY date").fetchdf()["date"]
dates = pd.to_datetime(dates).sort_values().reset_index(drop=True)
print(f"{len(dates)} distinct snapshot dates, {dates.min().date()} to {dates.max().date()}", flush=True)

def third_friday(year, month):
    d = pd.Timestamp(year=year, month=month, day=1)
    # first friday
    first_friday = d + pd.Timedelta(days=(4 - d.weekday()) % 7)
    tf = first_friday + pd.Timedelta(days=14)
    return tf

# Good Friday dates (Easter-2 days) within our range, for the "Thursday before" rule
# computed via a simple known list (2019-2027) rather than pulling in a holiday lib
GOOD_FRIDAYS = {
    2019: "2019-04-19", 2020: "2020-04-10", 2021: "2021-04-02", 2022: "2022-04-15",
    2023: "2023-04-07", 2024: "2024-03-29", 2025: "2025-04-18", 2026: "2026-04-03",
}

expirations = []
for year in range(2019, 2027):
    for month in range(1, 13):
        tf = third_friday(year, month)
        if tf > dates.max() + pd.Timedelta(days=60) or tf < pd.Timestamp("2019-01-01"):
            continue
        gf = GOOD_FRIDAYS.get(year)
        if gf is not None and tf == pd.Timestamp(gf):
            tf = tf - pd.Timedelta(days=1)  # Thursday before
        expirations.append(tf)
expirations = sorted(set(expirations))
print(f"{len(expirations)} candidate monthly expirations", flush=True)

pairs = []
for exp in expirations:
    target = exp - pd.Timedelta(days=2)
    candidates = dates[dates < exp]
    if len(candidates) == 0:
        continue
    nearest = candidates.iloc[(candidates - target).abs().argmin()]
    dte = (exp - nearest).days
    pairs.append({"expiration": exp, "entry_date": nearest, "days_to_expiration": dte})

pairs_df = pd.DataFrame(pairs)
pairs_df = pairs_df[(pairs_df["days_to_expiration"] >= 1) & (pairs_df["days_to_expiration"] <= 4)].reset_index(drop=True)
print(pairs_df["days_to_expiration"].describe(), flush=True)
pairs_df.to_parquet(OUT_DIR / "entry_expiration_pairs_2d.parquet")
print(f"Wrote {len(pairs_df)} (entry_date, expiration) pairs, "
      f"entries {pairs_df['entry_date'].min().date()} to {pairs_df['entry_date'].max().date()}", flush=True)
