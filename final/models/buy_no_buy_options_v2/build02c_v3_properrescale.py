"""
Proper split-rescale (2026-09-04, round 3), replacing the row-drop
workaround. Same pipeline as build02c_finalize_training.py, but uses
Gabe's Sharadar 'actions' pull (sharadar_splits_raw.csv, validated against
5 known real splits -- NVDA/TSLA/GOOGL/CMG/SMCI all matched exactly) to
reconstruct the underlying's RAW (as-it-actually-traded, pre-continuity-
adjustment) price at entry and at expiration, and compute moneyness/
payoff/targets against THAT instead of against the continuity-adjusted
local close -- so strike (DoltHub, never adjusted) and the price it's
compared against are finally on the same scale, at every date, not just
for rows that happen to fall in a sane sanity band.

Mechanism: local prices are backward-adjusted for continuity (a pre-split
date's price is already divided by every split that happens AFTER it, so
the whole series reads smoothly on today's scale). To undo that for a
given entry_date, multiply the continuity-adjusted close by the product
of every split ratio dated AFTER that entry_date -- that reconstructs the
actual nominal price as it traded back then, which is what DoltHub's
strike is already denominated in. Applied separately to underlying_close
at entry and at expiration (using each date's own "still to come" split
product), so a split falling between entry and expiration -- rare given
~30 DTE, but handled correctly rather than assumed away -- doesn't
silently break things.
"""
import gc
import time
from pathlib import Path
import pandas as pd
import numpy as np

REPO_FINAL = Path(__file__).resolve().parents[2]
OUT_DIR = Path(__file__).resolve().parent

t0 = time.time()

# ---- split ratios -> per-(ticker, asof-date) "still-to-come" cumulative ratio ----
splits = pd.read_csv(OUT_DIR / "sharadar_splits_raw.csv")
splits = splits[splits["action"] == "split"][["ticker", "date", "value"]].copy()
splits["date"] = pd.to_datetime(splits["date"]).astype("datetime64[ns]")
splits["value"] = splits["value"].astype("float64")
splits = splits.dropna(subset=["value"])
splits = splits[splits["value"] > 0]
splits = splits.drop_duplicates(subset=["ticker", "date"]).sort_values(["ticker", "date"]).reset_index(drop=True)
# reverse-cumulative product per ticker: at row i, product of value[i:] for that ticker
# = product of every split dated on/after date[i] -- i.e. "how much more this ticker
# will still split, from this date forward"
splits["rev_cumprod"] = splits.iloc[::-1].groupby("ticker")["value"].cumprod().iloc[::-1]
print(f"[{time.time()-t0:.0f}s] {splits['ticker'].nunique()} tickers with >=1 split, "
      f"{len(splits)} split events", flush=True)


def attach_still_to_come_ratio(df, date_col, ratio_col):
    """merge_asof: for each row, find the split with the NEXT date >= that
    row's date_col (direction='forward'); its rev_cumprod is exactly the
    product of every split still to come on/after that date. No match
    (ticker never splits again after this date, or never splits at all)
    -> ratio 1.0 (no rescale needed)."""
    left = df[["act_symbol", date_col]].reset_index().rename(columns={"index": "_idx", "act_symbol": "ticker"})
    left = left.sort_values(date_col)
    right = splits[["ticker", "date", "rev_cumprod"]].sort_values("date")
    m = pd.merge_asof(left, right, left_on=date_col, right_on="date", by="ticker", direction="forward")
    m[ratio_col] = m["rev_cumprod"].fillna(1.0)
    m = m.set_index("_idx").sort_index()
    df[ratio_col] = m[ratio_col].to_numpy()
    return df


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

calls = attach_still_to_come_ratio(calls, "entry_date", "_ratio_entry")
calls = attach_still_to_come_ratio(calls, "expiration_date", "_ratio_expiry")
n_rescaled = int((calls["_ratio_entry"] != 1.0).sum())
print(f"[{time.time()-t0:.0f}s] {n_rescaled} rows ({n_rescaled/len(calls)*100:.2f}%) "
      f"need a non-trivial entry-side rescale", flush=True)

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

# reconstruct the RAW (as-actually-traded, same scale as strike/premium)
# underlying price at entry and expiry -- this is the actual fix
calls["underlying_close_entry_raw"] = (calls["underlying_close_entry"] * calls["_ratio_entry"]).astype("float32")
calls["underlying_close_expiry_raw"] = (calls["underlying_close_expiry"] * calls["_ratio_expiry"]).astype("float32")

calls["moneyness_strike_over_spot"] = (calls["strike"] / calls["underlying_close_entry_raw"]).astype("float32")
calls["payoff_at_expiry"] = (calls["underlying_close_expiry_raw"] - calls["strike"]).clip(lower=0).astype("float32")
intrinsic_at_entry = (calls["underlying_close_entry_raw"] - calls["strike"]).clip(lower=0)

bad = calls["entry_premium"] < 0.9 * intrinsic_at_entry
print(f"[{time.time()-t0:.0f}s] below-intrinsic contamination: {bad.sum()} rows "
      f"({bad.mean()*100:.2f}%)", flush=True)
calls = calls[~bad].reset_index(drop=True)
del intrinsic_at_entry, bad
calls = calls[calls["entry_premium"] > 0.001].reset_index(drop=True)

calls["pct_return_on_premium"] = ((calls["payoff_at_expiry"] - calls["entry_premium"]) / calls["entry_premium"]).astype("float32")
calls["return_ratio"] = (calls["payoff_at_expiry"] / calls["entry_premium"]).astype("float32")

# sanity band check -- should now be nearly empty (a handful of genuine
# deep ITM/OTM picks, not systematic split artifacts)
resid_bad = ((calls["moneyness_strike_over_spot"] < 0.5) | (calls["moneyness_strike_over_spot"] > 2.0)).mean()
print(f"[{time.time()-t0:.0f}s] residual out-of-[0.5,2.0]-band rate AFTER proper rescale: "
      f"{resid_bad*100:.3f}% (was 4.40% under the old row-drop workaround)", flush=True)

calls = calls.drop(columns=["_ratio_entry", "_ratio_expiry", "underlying_close_entry_raw", "underlying_close_expiry_raw"])
gc.collect()
print(f"[{time.time()-t0:.0f}s] after cleaning: {calls.shape}", flush=True)

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

calls.to_parquet(OUT_DIR / "options_calls_training_expanded_v3_properrescale.parquet")
print(f"[{time.time()-t0:.0f}s] FINAL: {calls.shape}, {calls['act_symbol'].nunique()} tickers, "
      f"entries {calls['entry_date'].min().date()} to {calls['expiration_date'].max().date()}", flush=True)
print("volatility_60 null rate:", calls["volatility_60"].isna().mean())
