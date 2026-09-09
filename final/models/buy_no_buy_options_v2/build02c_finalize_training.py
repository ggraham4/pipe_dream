"""
Step 3 (memory-conscious rewrite): join underlying close, HV/IV panel, and
stock features onto the raw calls pulled in step 2, compute targets, apply
the below-intrinsic-value cleaning filter. Runs inside a 3.8GB-RAM device
bridge shell, so this downcasts to float32 and drops unneeded columns
aggressively between steps rather than keeping every intermediate frame
alive at once (an earlier float64, keep-everything version got OOM-killed).
"""
import gc
import time
from pathlib import Path
import pandas as pd
import numpy as np

REPO_FINAL = Path(__file__).resolve().parents[2]
OUT_DIR = Path(__file__).resolve().parent

t0 = time.time()
calls = pd.read_parquet(OUT_DIR / "raw_calls_at_entry.parquet",
                         columns=["entry_date", "act_symbol", "expiration_date", "strike",
                                  "bid", "ask", "entry_iv"])
calls["entry_date"] = pd.to_datetime(calls["entry_date"]).astype("datetime64[ns]")
calls["expiration_date"] = pd.to_datetime(calls["expiration_date"]).astype("datetime64[ns]")
calls["days_to_expiration"] = (calls["expiration_date"] - calls["entry_date"]).dt.days.astype("int16")
calls["entry_premium"] = ((calls["bid"] + calls["ask"]) / 2).astype("float32")
calls["strike"] = calls["strike"].astype("float32")
calls["entry_iv"] = calls["entry_iv"].astype("float32")
calls = calls.drop(columns=["bid", "ask"])
print(f"[{time.time()-t0:.0f}s] loaded raw calls: {calls.shape}", flush=True)

sf = pd.read_parquet(OUT_DIR / "expanded_stock_features.parquet")
sf["date"] = pd.to_datetime(sf["date"]).astype("datetime64[ns]")
float_cols = [c for c in sf.columns if sf[c].dtype == "float64"]
sf[float_cols] = sf[float_cols].astype("float32")

px = sf[["act_symbol", "date", "close"]].rename(columns={"close": "underlying_close_entry"})
calls = calls.merge(px, left_on=["act_symbol", "entry_date"], right_on=["act_symbol", "date"], how="left").drop(columns="date")
px2 = sf[["act_symbol", "date", "close"]].rename(columns={"close": "underlying_close_expiry", "date": "expiration_date"})
calls = calls.merge(px2, on=["act_symbol", "expiration_date"], how="left")
del px, px2
gc.collect()

before_px = len(calls)
calls = calls.dropna(subset=["underlying_close_entry", "underlying_close_expiry"]).reset_index(drop=True)
print(f"[{time.time()-t0:.0f}s] dropped {before_px - len(calls)} rows "
      f"({(before_px-len(calls))/before_px*100:.2f}%) lacking exact underlying close", flush=True)

calls["moneyness_strike_over_spot"] = (calls["strike"] / calls["underlying_close_entry"]).astype("float32")
calls["payoff_at_expiry"] = (calls["underlying_close_expiry"] - calls["strike"]).clip(lower=0).astype("float32")
intrinsic_at_entry = (calls["underlying_close_entry"] - calls["strike"]).clip(lower=0)

bad = calls["entry_premium"] < 0.9 * intrinsic_at_entry
print(f"[{time.time()-t0:.0f}s] below-intrinsic contamination: {bad.sum()} rows "
      f"({bad.mean()*100:.2f}%)", flush=True)
calls = calls[~bad].reset_index(drop=True)
del intrinsic_at_entry, bad
calls = calls[calls["entry_premium"] > 0.001].reset_index(drop=True)

calls["pct_return_on_premium"] = ((calls["payoff_at_expiry"] - calls["entry_premium"]) / calls["entry_premium"]).astype("float32")
calls["return_ratio"] = (calls["payoff_at_expiry"] / calls["entry_premium"]).astype("float32")
gc.collect()
print(f"[{time.time()-t0:.0f}s] after cleaning: {calls.shape}", flush=True)

# HV/IV panel join
volhist = pd.read_parquet(REPO_FINAL / "data" / "options_raw" / "expanded" / "volatility_history_expanded.parquet",
                           columns=["act_symbol", "date", "hv_current", "iv_current"])
volhist["date"] = pd.to_datetime(volhist["date"]).astype("datetime64[ns]")
volhist[["hv_current", "iv_current"]] = volhist[["hv_current", "iv_current"]].astype("float32")
volhist = volhist.sort_values("date").reset_index(drop=True)
calls = calls.sort_values("entry_date").reset_index(drop=True)
calls = pd.merge_asof(calls, volhist, left_on="entry_date", right_on="date",
                       by="act_symbol", direction="backward")
calls = calls.drop(columns="date")
del volhist
gc.collect()
print(f"[{time.time()-t0:.0f}s] HV/IV joined: {calls.shape}", flush=True)

# stock features join
sf_feats = sf[["act_symbol", "date", "daily_return", "cumulative_return",
               "momentum_5", "momentum_20", "momentum_60", "momentum_120",
               "volatility_20", "volatility_60", "volume_20",
               "relative_strength_20", "pct_from_high_252", "pct_from_low_252"]].sort_values("date").reset_index(drop=True)
del sf
gc.collect()
calls = calls.sort_values("entry_date").reset_index(drop=True)
calls = pd.merge_asof(calls, sf_feats, left_on="entry_date", right_on="date",
                       by="act_symbol", direction="backward")
calls = calls.drop(columns="date")
del sf_feats
gc.collect()

calls["realized_vol_21d_asof"] = calls["volatility_20"]

calls.to_parquet(OUT_DIR / "options_calls_training_expanded_v2.parquet")
print(f"[{time.time()-t0:.0f}s] FINAL: {calls.shape}, {calls['act_symbol'].nunique()} tickers, "
      f"entries {calls['entry_date'].min().date()} to {calls['entry_date'].max().date()}", flush=True)
