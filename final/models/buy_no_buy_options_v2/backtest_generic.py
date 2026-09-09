"""
Generic walk-forward backtest: Tweedie GLM + calibrated-decile Kelly.
Supports MODE=calls|puts and CADENCE=annual|monthly.

calls: predicts return_ratio (payoff/premium), picks highest predicted
       pct return (long call, ATM-ish already chosen upstream).
puts:  predicts loss_ratio_plus1 (mirrors return_ratio), converts to a
       predicted pct_return_on_collateral using the known
       premium_pct_of_collateral minus predicted loss_ratio, and picks
       the highest predicted pct_return_on_collateral (best cash-secured
       put to sell).

annual cadence: 6 x Jan-15 timepoints, +-15 day cohort window (matches
       every prior round today).
monthly cadence: the 77-91 actual entry dates already present in the
       data (from entry_expiration_pairs.parquet), cohort = exact
       entry_date match (no window needed/possible -- avoids any
       overlap between adjacent ~monthly cohorts).
"""
import sys
from pathlib import Path
import json
import numpy as np
import pandas as pd
from sklearn.linear_model import TweedieRegressor
from sklearn.preprocessing import StandardScaler

OUT_DIR = Path(__file__).resolve().parent
BASE_FEATURES = [
    "moneyness_strike_over_spot", "days_to_expiration", "entry_iv",
    "realized_vol_21d_asof", "hv_current", "iv_current",
    "momentum_5", "momentum_20", "momentum_60", "momentum_120",
    "volatility_20", "volatility_60",
    "relative_strength_20", "pct_from_high_252", "pct_from_low_252",
    "daily_return", "cumulative_return", "log_volume_20",
]
TWEEDIE_POWER, TWEEDIE_ALPHA = 1.4, 0.001
N_DECILES, MIN_DECILE_N = 10, 30
KELLY_FRACTION_MULTIPLIER, KELLY_CAP_PER_DECILE, MAX_POSITION_FRAC = 0.5, 1.0, 0.30
COHORT_WINDOW_DAYS = 15
MIN_MARKET_CAP, MIN_PRICE = 2_000_000_000.0, 10.0
MIN_TRAIN_N = 2000

MODE = sys.argv[1]      # "calls" or "puts"
CADENCE = sys.argv[2]   # "annual" or "monthly"
MAX_MONEYNESS = float(sys.argv[3]) if len(sys.argv) > 3 else None  # puts only: cap strike/spot (e.g. 1.0 = true OTM/ATM cash-secured put, no deep-ITM)
assert MODE in ("calls", "puts") and CADENCE in ("annual", "monthly")

if MODE == "calls":
    df = pd.read_parquet(OUT_DIR / "options_calls_expanded_pit_properrescale_v3.parquet")
    TARGET = "return_ratio"
else:
    df = pd.read_parquet(OUT_DIR / ("options_puts_expanded_pit_properrescale_cleaned.parquet" if __import__("os").environ.get("USE_CLEANED_PUTS")=="1" else "options_puts_expanded_pit_properrescale.parquet"))
    TARGET = "loss_ratio_plus1"

df["entry_date"] = df["entry_date"].astype("datetime64[ns]")
df["expiration_date"] = df["expiration_date"].astype("datetime64[ns]")
df = df[(df["market_cap"].notna()) & (df["market_cap"] >= MIN_MARKET_CAP) &
        (df["underlying_close_entry"] > MIN_PRICE)].copy()
df["log_volume_20"] = np.log1p(df["volume_20"].clip(lower=0))
needed = BASE_FEATURES + [TARGET]
if MODE == "puts":
    needed += ["pct_return_on_collateral", "premium_pct_of_collateral"]
df = df.dropna(subset=needed).reset_index(drop=True)
import os as _os2
if MODE == "puts" and _os2.environ.get("FILTER_BAD_IV") == "1":
    _before = len(df)
    df = df[(df["entry_iv"] > 0) & (df["entry_iv"] <= 1.5)].copy()
    print(f"IV sanity filter: dropped {_before-len(df)} rows ({(_before-len(df))/_before*100:.2f}%) with entry_iv<=0 or >150%", flush=True)
if MODE == "puts" and MAX_MONEYNESS is not None:
    df = df[df["moneyness_strike_over_spot"] <= MAX_MONEYNESS].copy()
import os
if os.environ.get("EXCLUDE_RECENT_SPLITS") == "1":
    _splits = pd.read_csv(OUT_DIR / "sharadar_splits_raw.csv")
    _splits["date"] = pd.to_datetime(_splits["date"])
    _bad = set(_splits[_splits["date"] >= pd.Timestamp("2026-09-04")-pd.Timedelta(days=500)]["ticker"].unique())
    before = len(df)
    df = df[~df["act_symbol"].isin(_bad)].copy()
    print(f"excluded {len(_bad)} recent-split tickers: {before-len(df)} rows dropped", flush=True)
print(f"[{MODE}/{CADENCE}/moneyness<={MAX_MONEYNESS}] universe after filters: {df.shape}, tickers={df['act_symbol'].nunique()}", flush=True)

if CADENCE == "annual":
    TIMEPOINTS = [pd.Timestamp(f"{y}-01-15") for y in range(2021, 2027)]
else:
    pairs = pd.read_parquet(OUT_DIR / "entry_expiration_pairs.parquet")
    TIMEPOINTS = sorted(pairs["entry_date"].unique())
print(f"{len(TIMEPOINTS)} timepoints", flush=True)


def kelly_fraction(decile, decile_stats):
    if pd.isna(decile) or decile not in decile_stats.index:
        return 0.0
    row = decile_stats.loc[decile]
    if row["count"] < MIN_DECILE_N or row["var"] <= 0 or row["mean"] <= 0:
        return 0.0
    f = np.clip(row["mean"] / row["var"], 0, KELLY_CAP_PER_DECILE)
    return min(f * KELLY_FRACTION_MULTIPLIER, MAX_POSITION_FRAC)


calibration_pool = []
per_timepoint = []
for T in TIMEPOINTS:
    train = df[df["expiration_date"] <= T]
    if CADENCE == "annual":
        cohort = df[(df["entry_date"] >= T - pd.Timedelta(days=COHORT_WINDOW_DAYS)) &
                    (df["entry_date"] <= T + pd.Timedelta(days=COHORT_WINDOW_DAYS))].copy()
    else:
        cohort = df[df["entry_date"] == T].copy()

    if len(train) < MIN_TRAIN_N or cohort.empty:
        print(f"  skip {T.date()}: train={len(train)} cohort={len(cohort)}", flush=True)
        continue

    scaler = StandardScaler().fit(train[BASE_FEATURES].to_numpy())
    Xtr = np.clip(scaler.transform(train[BASE_FEATURES].to_numpy()), -5, 5)
    model = TweedieRegressor(power=TWEEDIE_POWER, alpha=TWEEDIE_ALPHA, link="log", max_iter=300)
    model.fit(Xtr, train[TARGET].to_numpy())
    Xc = np.clip(scaler.transform(cohort[BASE_FEATURES].to_numpy()), -5, 5)
    pred_raw = model.predict(Xc)

    if MODE == "calls":
        cohort["pred_pct_return"] = pred_raw - 1.0
        cohort["realized_pct_return"] = cohort[TARGET] - 1.0
    else:
        pred_loss_ratio = pred_raw - 1.0
        cohort["pred_pct_return"] = cohort["premium_pct_of_collateral"] - pred_loss_ratio
        cohort["realized_pct_return"] = cohort["pct_return_on_collateral"]

    pool_df = pd.DataFrame(calibration_pool)
    row = {"timepoint": str(T.date()), "n_cohort": len(cohort), "n_tickers": cohort["act_symbol"].nunique()}
    if len(pool_df) >= 1000:
        edges = np.quantile(pool_df["pred_pct_return"], np.linspace(0, 1, N_DECILES + 1))
        edges[0], edges[-1] = -np.inf, np.inf
        pool_df["decile"] = pd.cut(pool_df["pred_pct_return"], edges, labels=False, duplicates="drop")
        decile_stats = pool_df.groupby("decile")["realized_pct_return"].agg(["mean", "var", "count"])
        cohort["decile"] = pd.cut(cohort["pred_pct_return"], edges, labels=False, duplicates="drop")
        best = cohort.loc[cohort.groupby("act_symbol")["pred_pct_return"].idxmax()].copy()
        best["kelly_frac"] = best["decile"].apply(lambda d: kelly_fraction(d, decile_stats))

        top5 = best.sort_values("pred_pct_return", ascending=False).head(5)
        row["eq_pct"] = round(float((10000/len(top5)*(1+top5["realized_pct_return"])).sum()/10000*100 - 100), 2) if len(top5) else None

        kpicks = best[best["kelly_frac"] > 0].sort_values("pred_pct_return", ascending=False).head(8)
        tf = kpicks["kelly_frac"].sum()
        if tf > 1.0:
            kpicks = kpicks.copy(); kpicks["kelly_frac"] /= tf; tf = 1.0
        row["kelly_pct"] = round(float((kpicks["kelly_frac"]*kpicks["realized_pct_return"]).sum())*100, 2) if len(kpicks) else 0.0
        row["kelly_cash"] = round(1.0 - tf, 3)
        row["n_kelly_positions"] = int(len(kpicks))
    else:
        row.update(eq_pct=None, kelly_pct=None)

    per_timepoint.append(row)
    print(f"  {T.date()}: cohort={row['n_cohort']} (tickers={row['n_tickers']}) EQ={row.get('eq_pct')} KELLY={row.get('kelly_pct')}", flush=True)
    calibration_pool.extend(cohort[["pred_pct_return", "realized_pct_return"]].to_dict("records"))

suffix = f"_mny{MAX_MONEYNESS}" if (MODE == "puts" and MAX_MONEYNESS is not None) else ""
out_name = f"backtest_{MODE}_{CADENCE}{suffix}_results.json"
with open(OUT_DIR / out_name, "w") as f:
    json.dump(per_timepoint, f, indent=2, default=str)
print(f"\nsaved {out_name}")

scored = [r for r in per_timepoint if r.get("kelly_pct") is not None]
if scored:
    kvals = [r["kelly_pct"] for r in scored]
    wins = sum(1 for v in kvals if v > 0)
    print(f"\nSUMMARY [{MODE}/{CADENCE}/moneyness<={MAX_MONEYNESS}]: n={len(kvals)}  Kelly avg={np.mean(kvals):.2f}%  std={np.std(kvals):.2f}%  win={wins}/{len(kvals)}")
