"""
Integrate the PIT (point-in-time, survivorship-bias-corrected) fundamentals
panel into the options calls training data.

Two things happen here, both point-in-time correct (no lookahead):

1. FUNDAMENTALS JOIN: for each options row (act_symbol, entry_date), attach
   the most recent PIT fundamentals snapshot dated ON OR BEFORE entry_date
   for that ticker (pe_ratio, pb_ratio, ps_ratio, debt_to_equity, roe, roa,
   gross_margin, operating_margin, fcf_margin, revenue_growth_yoy,
   earnings_growth_yoy, rnd_intensity, fundamentals_age_days). This is new
   information the original options model never had -- its feature set was
   entirely price/volatility-derived (flagged explicitly as a lever worth
   trying in models/options-premium-model-design.md).

2. POINT-IN-TIME ELIGIBILITY FLOOR: reapply the same market_cap >= $2B and
   close >= $10 screen the stock PIT model uses (continuous_walkforward_pit.py,
   MIN_MARKET_CAP/MIN_PRICE), evaluated AT THE OPTION'S OWN ENTRY DATE rather
   than "is this ticker on today's S&P 500 list" (which is what the original
   options universe construction effectively did). This closes the same
   look-ahead-bias hole Round 7 closed for the stock model: a ticker being
   large enough today doesn't mean it was actually investable-sized back in
   2019-2021.

Input: options_calls_training.parquet (595,303 rows, 496 tickers, already
cleaned of the below-intrinsic-value data defect) and
options_pit_fundamentals_slim.parquet (a column/ticker-filtered extract of
final/out/features_with_fundamentals_pit.parquet -- same 496 tickers, full
date range, just the fundamentals + market_cap + close columns).
Run from final/:  python3 models/pit_integration/build_options_pit_features.py
"""
import os

import numpy as np
import pandas as pd

os.makedirs("data/training", exist_ok=True)

MIN_MARKET_CAP = 2_000_000_000.0
MIN_PRICE = 10.0

FUND_COLS = [
    "pe_ratio", "pb_ratio", "ps_ratio", "debt_to_equity", "roe", "roa",
    "gross_margin", "operating_margin", "fcf_margin",
    "revenue_growth_yoy", "earnings_growth_yoy", "rnd_intensity",
    "fundamentals_age_days",
]

print("Loading options calls training data...", flush=True)
opt = pd.read_parquet("data/training/options_calls_training.parquet")
opt["entry_date"] = pd.to_datetime(opt["entry_date"]).astype("datetime64[ns]")
opt["expiration_date"] = pd.to_datetime(opt["expiration_date"]).astype("datetime64[ns]")
print(f"  {len(opt):,} rows, {opt['act_symbol'].nunique()} tickers, "
      f"entry_date {opt['entry_date'].min().date()} - {opt['entry_date'].max().date()}", flush=True)

print("Loading PIT fundamentals panel (slim extract)...", flush=True)
fund = pd.read_parquet("data/options_pit_fundamentals_slim.parquet")
fund["date"] = pd.to_datetime(fund["date"]).astype("datetime64[ns]")
fund = fund.rename(columns={"close": "pit_close"})
print(f"  {len(fund):,} rows, {fund['ticker'].nunique()} tickers, "
      f"date {fund['date'].min().date()} - {fund['date'].max().date()}", flush=True)

# merge_asof requires global sort on the "on" column
opt_sorted = opt.sort_values("entry_date").reset_index(drop=True)
fund_sorted = fund.sort_values("date").reset_index(drop=True)

print("Point-in-time asof join (nearest fundamentals snapshot <= entry_date, per ticker)...", flush=True)
merged = pd.merge_asof(
    opt_sorted,
    fund_sorted[["date", "ticker", "pit_close", "market_cap"] + FUND_COLS],
    left_on="entry_date", right_on="date",
    left_by="act_symbol", right_by="ticker",
    direction="backward",
)
merged = merged.drop(columns=["date", "ticker"])

n_total = len(merged)
n_no_match = merged["market_cap"].isna().sum()
print(f"\nJoin result: {n_total:,} rows, {n_no_match:,} ({n_no_match/n_total:.2%}) "
      f"have no PIT fundamentals snapshot on or before their entry_date "
      f"(ticker not yet covered by the PIT panel that early, or genuinely missing).", flush=True)

# staleness check: how old is the matched snapshot on average / at the tail
merged["fundamentals_age_days"] = merged["fundamentals_age_days"].astype(float)
print(f"Matched-row fundamentals age (days): median={merged['fundamentals_age_days'].median():.0f}, "
      f"p90={merged['fundamentals_age_days'].quantile(0.9):.0f}, "
      f"max={merged['fundamentals_age_days'].max():.0f}", flush=True)

# point-in-time eligibility floor -- unmatched rows (can't verify) fail closed
eligible = (merged["market_cap"] >= MIN_MARKET_CAP) & (merged["pit_close"] >= MIN_PRICE)
eligible = eligible.fillna(False)
n_eligible = eligible.sum()
print(f"\nPoint-in-time eligibility floor (market_cap >= ${MIN_MARKET_CAP:,.0f} and "
      f"close >= ${MIN_PRICE:.0f} ON THE ENTRY DATE, not today's values):", flush=True)
print(f"  {n_eligible:,} / {n_total:,} rows pass ({n_eligible/n_total:.2%}); "
      f"{n_total - n_eligible:,} ({(n_total-n_eligible)/n_total:.2%}) dropped.", flush=True)

# breakdown by year, to see whether the drop concentrates in the earlier/thinner years
merged["entry_year"] = merged["entry_date"].dt.year
by_year = merged.groupby("entry_year").apply(
    lambda g: pd.Series({
        "n": len(g),
        "pct_eligible": eligible.loc[g.index].mean(),
        "pct_no_fund_match": g["market_cap"].isna().mean(),
    }), include_groups=False
)
print("\nBy entry year:")
print(by_year.to_string(float_format=lambda x: f"{x:.3f}"))

out = merged[eligible].copy().reset_index(drop=True)
out.to_parquet("data/training/options_calls_training_pit.parquet", compression="zstd")
print(f"\nWrote {len(out):,} rows -> options_calls_training_pit.parquet "
      f"({out['act_symbol'].nunique()} tickers)", flush=True)

# also save the pre-eligibility-filter, fundamentals-only-joined version
# (useful to isolate "does adding fundamentals help" from "does the PIT
# eligibility floor change the answer" -- kept for the ablation)
merged.to_parquet("data/training/options_calls_training_fundjoin_only.parquet", compression="zstd")
print(f"Also wrote unfiltered fundamentals-joined table ({len(merged):,} rows) for ablation.", flush=True)
