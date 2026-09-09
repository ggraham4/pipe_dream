"""
Plain baseline (Tweedie GLM + calibrated-decile Kelly, no buy/no-buy gate
at all -- Gabe's confirmed production choice, 2026-09-04 round 3) on the
PROPERLY split-rescaled (not row-dropped) + wider (1,266-ticker
fundamentals coverage) universe. For direct comparison against round 2's
row-drop-workaround numbers (+2.11% avg / 15.12% std / 2-5 win, Kelly).
"""
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
TIMEPOINTS = [pd.Timestamp(f"{y}-01-15") for y in range(2021, 2027)]
COHORT_WINDOW_DAYS = 15
MIN_MARKET_CAP, MIN_PRICE = 2_000_000_000.0, 10.0

df = pd.read_parquet(OUT_DIR / "options_calls_expanded_pit_properrescale_v3.parquet")
df["entry_date"] = df["entry_date"].astype("datetime64[ns]")
df["expiration_date"] = df["expiration_date"].astype("datetime64[ns]")
df = df[(df["market_cap"].notna()) & (df["market_cap"] >= MIN_MARKET_CAP) &
        (df["underlying_close_entry"] > MIN_PRICE)].copy()
print(f"PIT-corrected, properly-rescaled universe: {len(df)} rows, {df['act_symbol'].nunique()} tickers", flush=True)
df["log_volume_20"] = np.log1p(df["volume_20"].clip(lower=0))
df = df.dropna(subset=BASE_FEATURES + ["return_ratio", "pct_return_on_premium"]).reset_index(drop=True)
print(f"After feature dropna: {df.shape}", flush=True)


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
    cohort = df[(df["entry_date"] >= T - pd.Timedelta(days=COHORT_WINDOW_DAYS)) &
                (df["entry_date"] <= T + pd.Timedelta(days=COHORT_WINDOW_DAYS))].copy()
    if len(train) < 2000 or cohort.empty:
        print(f"  skip {T.date()}: train={len(train)} cohort={len(cohort)}", flush=True)
        continue
    scaler = StandardScaler().fit(train[BASE_FEATURES].to_numpy())
    Xtr = np.clip(scaler.transform(train[BASE_FEATURES].to_numpy()), -5, 5)
    model = TweedieRegressor(power=TWEEDIE_POWER, alpha=TWEEDIE_ALPHA, link="log", max_iter=300)
    model.fit(Xtr, train["return_ratio"].to_numpy())
    Xc = np.clip(scaler.transform(cohort[BASE_FEATURES].to_numpy()), -5, 5)
    cohort["pred_pct_return"] = model.predict(Xc) - 1.0
    cohort["realized_pct_return"] = cohort["return_ratio"] - 1.0

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
        row["eq_picks"] = [{"t": t, "mny": round(float(m), 3)} for t, m in zip(top5["act_symbol"], top5["moneyness_strike_over_spot"])]

        kpicks = best[best["kelly_frac"] > 0].sort_values("pred_pct_return", ascending=False).head(8)
        tf = kpicks["kelly_frac"].sum()
        if tf > 1.0:
            kpicks = kpicks.copy(); kpicks["kelly_frac"] /= tf; tf = 1.0
        row["kelly_pct"] = round(float((kpicks["kelly_frac"]*kpicks["realized_pct_return"]).sum())*100, 2) if len(kpicks) else 0.0
        row["kelly_cash"] = round(1.0 - tf, 3)
    else:
        row.update(eq_pct=None, kelly_pct=None)

    per_timepoint.append(row)
    print(f"  {T.date()}: cohort={row['n_cohort']} (tickers={row['n_tickers']}) EQ={row.get('eq_pct')} KELLY={row.get('kelly_pct')}", flush=True)
    calibration_pool.extend(cohort[["pred_pct_return", "realized_pct_return"]].to_dict("records"))

with open(OUT_DIR / "baseline_properrescale_results.json", "w") as f:
    json.dump(per_timepoint, f, indent=2, default=str)
print("\nsaved baseline_properrescale_results.json")
