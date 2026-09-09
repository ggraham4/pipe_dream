"""
Add a Black-Scholes richness sanity filter to the puts training table,
symmetric to the pipeline's existing below-intrinsic contamination filter.
Diagnostic (round 6) found that ~11-17% of the moneyness<=1.0 universe has
premium_received priced 3x-1000s of x above what its OWN stated entry_iv
would justify via BS -- these are unexecutable/stale quotes, and they are
exactly what the Kelly walk-forward selector was chasing (explaining the
implausible ~12-15% per-cohort "edge" found in round 6 raw backtests).
Filter: drop rows where richness_ratio = actual_premium / bs_theoretical > 3.
"""
from pathlib import Path
import numpy as np
import pandas as pd
from scipy.stats import norm

OUT_DIR = Path(__file__).resolve().parent
RICHNESS_CAP = 3.0

df = pd.read_parquet(OUT_DIR / "options_puts_expanded_pit_properrescale.parquet")
print(f"before richness filter: {df.shape}", flush=True)

valid_iv = (df["entry_iv"] > 0) & (df["entry_iv"] < 3.0)
S = df["strike"] / df["moneyness_strike_over_spot"]
T = df["days_to_expiration"].astype(float) / 365.0
sigma = df["entry_iv"].clip(lower=1e-4)
d1 = (np.log(S / df["strike"]) + 0.5 * sigma**2 * T) / (sigma * np.sqrt(T))
d2 = d1 - sigma * np.sqrt(T)
bs_price = df["strike"] * norm.cdf(-d2) - S * norm.cdf(-d1)
actual_premium = df["premium_pct_of_collateral"] * df["strike"]
richness_ratio = actual_premium / bs_price.clip(lower=0.001)

# only apply the filter where we have a usable entry_iv to judge against;
# rows with missing/garbage entry_iv are left to the existing dropna in the
# backtest script (BASE_FEATURES requires entry_iv anyway)
drop_mask = valid_iv & (richness_ratio > RICHNESS_CAP)
print(f"dropping {drop_mask.sum()} rows ({drop_mask.mean()*100:.2f}%) with richness_ratio > {RICHNESS_CAP}x BS-theoretical", flush=True)
df_clean = df[~drop_mask].reset_index(drop=True)
print(f"after richness filter: {df_clean.shape}, {df_clean['act_symbol'].nunique()} tickers", flush=True)

df_clean.to_parquet(OUT_DIR / "options_puts_expanded_pit_properrescale_cleaned.parquet", index=False)
print("saved options_puts_expanded_pit_properrescale_cleaned.parquet")
