"""
Selling-premium strategy build (round 6, 2026-09-04): finalize the Put
training table with the SAME proper split-rescale, HV/IV, and stock
feature joins as the calls pipeline (build02c_v3_properrescale.py) --
just computes SHORT PUT economics instead of long call economics.

Economics of selling a cash-secured put: collateral = strike (cash set
aside to buy the stock if assigned). At expiration:
  - if underlying stays AT OR ABOVE strike: put expires worthless, seller
    keeps the full premium. loss_at_expiry = 0.
  - if underlying finishes BELOW strike: seller is assigned, effectively
    buying the stock at strike while it's worth less. loss_at_expiry =
    strike - underlying_close_expiry (the "insurance payout" the seller
    owes), unlimited in principle (down to a floor of the stock going to
    zero, capped at strike itself).
  seller's total pct return on collateral = (premium_received -
  loss_at_expiry) / strike.

Modeling target: loss_at_expiry / strike -- this is a right-skewed,
zero-inflated non-negative ratio (usually 0, occasionally large), the
SAME kind of quantity the Tweedie GLM already models well for the calls
side (where it predicts payoff/premium, also right-skewed non-negative).
Reusing the identical architecture: predict loss ratio, prefer selling
puts the model expects to have the SMALLEST loss ratio (safest), size
with the same calibrated-decile Kelly logic applied to pct_return_on_collateral.
"""
import gc
import time
from pathlib import Path
import pandas as pd
import numpy as np

REPO_FINAL = Path(__file__).resolve().parents[2]
OUT_DIR = Path(__file__).resolve().parent
t0 = time.time()

splits = pd.read_csv(OUT_DIR / "sharadar_splits_raw.csv")
splits = splits[splits["action"] == "split"][["ticker", "date", "value"]].copy()
splits["date"] = pd.to_datetime(splits["date"]).astype("datetime64[ns]")
splits["value"] = splits["value"].astype("float64")
splits = splits.dropna(subset=["value"])
splits = splits[splits["value"] > 0]
splits = splits.drop_duplicates(subset=["ticker", "date"]).sort_values(["ticker", "date"]).reset_index(drop=True)
splits["rev_cumprod"] = splits.iloc[::-1].groupby("ticker")["value"].cumprod().iloc[::-1]


def attach_still_to_come_ratio(df, date_col, ratio_col):
    left = df[["act_symbol", date_col]].reset_index().rename(columns={"index": "_idx", "act_symbol": "ticker"})
    left = left.sort_values(date_col)
    right = splits[["ticker", "date", "rev_cumprod"]].sort_values("date")
    m = pd.merge_asof(left, right, left_on=date_col, right_on="date", by="ticker", direction="forward")
    m[ratio_col] = m["rev_cumprod"].fillna(1.0)
    m = m.set_index("_idx").sort_index()
    df[ratio_col] = m[ratio_col].to_numpy()
    return df


puts = pd.read_parquet(OUT_DIR / "raw_puts_at_entry.parquet",
                        columns=["entry_date", "act_symbol", "expiration_date", "strike",
                                 "bid", "ask", "entry_iv"])
puts["entry_date"] = pd.to_datetime(puts["entry_date"]).astype("datetime64[ns]")
puts["expiration_date"] = pd.to_datetime(puts["expiration_date"]).astype("datetime64[ns]")
puts["days_to_expiration"] = (puts["expiration_date"] - puts["entry_date"]).dt.days.astype("int16")
puts["premium_received"] = ((puts["bid"] + puts["ask"]) / 2).astype("float32")
puts["strike"] = puts["strike"].astype("float32")
puts["entry_iv"] = puts["entry_iv"].astype("float32")
puts = puts.drop(columns=["bid", "ask"])
print(f"[{time.time()-t0:.0f}s] loaded raw puts: {puts.shape}", flush=True)

puts = attach_still_to_come_ratio(puts, "entry_date", "_ratio_entry")
puts = attach_still_to_come_ratio(puts, "expiration_date", "_ratio_expiry")

sf = pd.read_parquet(OUT_DIR / "expanded_stock_features.parquet")
sf["date"] = pd.to_datetime(sf["date"]).astype("datetime64[ns]")
float_cols = [c for c in sf.columns if sf[c].dtype == "float64"]
sf[float_cols] = sf[float_cols].astype("float32")

px_sorted = sf[["act_symbol", "date", "close"]].sort_values("date").rename(columns={"close": "underlying_close_entry"})
puts = puts.sort_values("entry_date")
puts = pd.merge_asof(puts, px_sorted, left_on="entry_date", right_on="date", by="act_symbol",
                      direction="backward", tolerance=pd.Timedelta(days=3)).drop(columns="date")
px2_sorted = sf[["act_symbol", "date", "close"]].sort_values("date").rename(
    columns={"close": "underlying_close_expiry", "date": "expiration_date"})
puts = puts.sort_values("expiration_date")
puts = pd.merge_asof(puts, px2_sorted, on="expiration_date", by="act_symbol",
                      direction="backward", tolerance=pd.Timedelta(days=3))
del px_sorted, px2_sorted
gc.collect()

before_px = len(puts)
puts = puts.dropna(subset=["underlying_close_entry", "underlying_close_expiry"]).reset_index(drop=True)
print(f"[{time.time()-t0:.0f}s] dropped {before_px - len(puts)} rows lacking exact underlying close "
      f"({(before_px-len(puts))/before_px*100:.2f}%)", flush=True)

puts["underlying_close_entry_raw"] = (puts["underlying_close_entry"] * puts["_ratio_entry"]).astype("float32")
puts["underlying_close_expiry_raw"] = (puts["underlying_close_expiry"] * puts["_ratio_expiry"]).astype("float32")
puts = puts.drop(columns=["_ratio_entry", "_ratio_expiry"])

puts["moneyness_strike_over_spot"] = (puts["strike"] / puts["underlying_close_entry_raw"]).astype("float32")
puts["loss_at_expiry"] = (puts["strike"] - puts["underlying_close_expiry_raw"]).clip(lower=0).astype("float32")

# below-intrinsic contamination filter, mirrored for puts: a put can't
# trade for less than 90% of its own intrinsic value in a liquid market
intrinsic_at_entry = (puts["strike"] - puts["underlying_close_entry_raw"]).clip(lower=0)
bad = puts["premium_received"] < 0.9 * intrinsic_at_entry
print(f"[{time.time()-t0:.0f}s] below-intrinsic contamination: {bad.sum()} rows ({bad.mean()*100:.2f}%)", flush=True)
puts = puts[~bad].reset_index(drop=True)
del intrinsic_at_entry, bad
puts = puts[puts["premium_received"] > 0.001].reset_index(drop=True)

resid_bad = ((puts["moneyness_strike_over_spot"] < 0.5) | (puts["moneyness_strike_over_spot"] > 2.0)).mean()
print(f"[{time.time()-t0:.0f}s] residual out-of-[0.5,2.0]-band rate: {resid_bad*100:.3f}%", flush=True)

puts["loss_ratio"] = (puts["loss_at_expiry"] / puts["strike"]).astype("float32")
puts["premium_pct_of_collateral"] = (puts["premium_received"] / puts["strike"]).astype("float32")
puts["pct_return_on_collateral"] = (puts["premium_pct_of_collateral"] - puts["loss_ratio"]).astype("float32")
# Tweedie needs a strictly non-negative target -- model 1+loss_ratio the
# same way the calls side models return_ratio=payoff/premium (also a
# 1-based non-negative ratio), so the exact same TweedieRegressor(power=1.4)
# recipe applies unchanged.
puts["loss_ratio_plus1"] = 1.0 + puts["loss_ratio"]

puts = puts.drop(columns=["underlying_close_entry_raw", "underlying_close_expiry_raw"])
gc.collect()
print(f"[{time.time()-t0:.0f}s] after cleaning: {puts.shape}", flush=True)

volhist = pd.read_parquet(REPO_FINAL / "data" / "options_raw" / "expanded" / "volatility_history_expanded.parquet",
                           columns=["act_symbol", "date", "hv_current", "iv_current"])
volhist["date"] = pd.to_datetime(volhist["date"]).astype("datetime64[ns]")
volhist[["hv_current", "iv_current"]] = volhist[["hv_current", "iv_current"]].astype("float32")
volhist = volhist.dropna(subset=["iv_current"]).sort_values("date").reset_index(drop=True)
puts = puts.sort_values("entry_date").reset_index(drop=True)
puts = pd.merge_asof(puts, volhist, left_on="entry_date", right_on="date", by="act_symbol", direction="backward")
puts = puts.drop(columns="date")
del volhist
gc.collect()

sf_feats = sf[["act_symbol", "date", "daily_return", "cumulative_return",
               "momentum_5", "momentum_20", "momentum_60", "momentum_120",
               "volatility_20", "volatility_60", "volume_20",
               "relative_strength_20", "pct_from_high_252", "pct_from_low_252"]].sort_values("date").reset_index(drop=True)
del sf
gc.collect()
puts = puts.sort_values("entry_date").reset_index(drop=True)
puts = pd.merge_asof(puts, sf_feats, left_on="entry_date", right_on="date", by="act_symbol", direction="backward")
puts = puts.drop(columns="date")
del sf_feats
gc.collect()
puts["realized_vol_21d_asof"] = puts["volatility_20"]

puts.to_parquet(OUT_DIR / "options_puts_training_expanded_properrescale.parquet")
print(f"[{time.time()-t0:.0f}s] FINAL: {puts.shape}, {puts['act_symbol'].nunique()} tickers, "
      f"entries {puts['entry_date'].min().date()} to {puts['expiration_date'].max().date()}", flush=True)
