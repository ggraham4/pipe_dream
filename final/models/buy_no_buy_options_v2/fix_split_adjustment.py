"""
Fix for the stock-split price/strike scale mismatch discovered while
running the strike percentage grid search (2026-09-04).

Root cause: local price data (scripts/td_data_local/*.csv) is
split-adjusted (backward-adjusted for continuity across history), but
DoltHub's option chain strikes are NOT retroactively adjusted for later
stock splits. For any ticker that had a split during 2019-2026, rows
dated BEFORE that split have underlying_close_entry on the split-adjusted
scale while strike (and therefore moneyness_strike_over_spot,
pct_return_on_premium, return_ratio) are on the pre-split nominal scale --
badly corrupting both strike selection AND the modeling target for those
rows. Confirmed directly for NVDA (10-for-1 split 2024-06-10) and NFLX
(7-for-1 split 2004, but also had a 2015 7-for-1 split): pre-split entry
dates show strikes 5-10x the local close price with no economic meaning.

This script flags every row where moneyness_strike_over_spot falls
outside a generous sanity band and removes it, rather than trying to
locate exact split dates and re-scale (re-scaling is a bigger project;
dropping the corrupted rows is the safe, honest fix for now). We use a
per-row filter (not a whole-ticker exclusion) because the excluded 24
tickers are only bad BEFORE their split date -- dropping the whole
ticker throws away perfectly good post-split rows.

Band: moneyness_strike_over_spot in [0.5, 2.0]. This is generous (a real
book of near-the-money short-dated calls should mostly fall in
[0.8, 1.2]) but conservative enough not to bias legitimate deep ITM/OTM
strikes we might deliberately choose in the grid search (target grid runs
0.80-1.20, so 0.5-2.0 gives headroom above/below without keeping in the
5-10x split artifacts).
"""
from pathlib import Path
import pandas as pd
import numpy as np

OUT_DIR = Path(__file__).resolve().parent

df = pd.read_parquet(OUT_DIR / "options_calls_expanded_with_pit_capcheck.parquet")
n_before = len(df)

bad_mask = (df["moneyness_strike_over_spot"] < 0.5) | (df["moneyness_strike_over_spot"] > 2.0)
n_bad = int(bad_mask.sum())
bad_tickers = sorted(df.loc[bad_mask, "act_symbol"].unique().tolist())

print(f"Total rows: {n_before}")
print(f"Rows outside moneyness [0.5, 2.0] sanity band: {n_bad} ({n_bad/n_before*100:.3f}%)")
print(f"Tickers affected: {len(bad_tickers)}")
print(bad_tickers)

# per-ticker breakdown for the affected tickers: how many rows removed vs kept
detail = (df.assign(bad=bad_mask)
            .groupby("act_symbol")["bad"]
            .agg(["sum", "count"])
            .rename(columns={"sum": "n_bad", "count": "n_total"}))
detail = detail[detail["n_bad"] > 0].sort_values("n_bad", ascending=False)
detail["pct_bad"] = (detail["n_bad"] / detail["n_total"] * 100).round(1)
print(detail.to_string())

clean = df.loc[~bad_mask].reset_index(drop=True)
clean.to_parquet(OUT_DIR / "options_calls_expanded_with_pit_capcheck_splitfixed.parquet", index=False)
print(f"\nSaved cleaned file: {len(clean)} rows ({len(clean)/n_before*100:.2f}% retained)")
