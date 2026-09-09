"""
Strike moneyness grid search, round 3b -- same idea as v2 but with a
SINGLE shared decile-calibration pool per timepoint (built from the whole
eligible cohort's predicted-vs-realized pairs, exactly like the plain
baseline strategy calibrates in production), rather than one pool per
moneyness target. The decile calibration is a property of the GLM's
predicted-vs-realized relationship in general, not specific to a strike
level, so there's no reason to slice it up -- doing so just delayed
warmup and lost 2 of 6 timepoints for no benefit. This recovers the full
5-timepoint sample and matches production calibration exactly.
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
MONEYNESS_GRID = [0.80, 0.85, 0.90, 0.95, 1.00, 1.05, 1.10, 1.15, 1.20]

df = pd.read_parquet(OUT_DIR / "options_calls_expanded_pit_properrescale_v3.parquet")
df["entry_date"] = df["entry_date"].astype("datetime64[ns]")
df["expiration_date"] = df["expiration_date"].astype("datetime64[ns]")
df = df[(df["market_cap"].notna()) & (df["market_cap"] >= MIN_MARKET_CAP) &
        (df["underlying_close_entry"] > MIN_PRICE)].copy()
df["log_volume_20"] = np.log1p(df["volume_20"].clip(lower=0))
df = df.dropna(subset=BASE_FEATURES + ["return_ratio", "pct_return_on_premium"]).reset_index(drop=True)
print(f"Universe: {len(df)} rows, {df['act_symbol'].nunique()} tickers", flush=True)


def kelly_fraction(decile, decile_stats):
    if pd.isna(decile) or decile not in decile_stats.index:
        return 0.0
    row = decile_stats.loc[decile]
    if row["count"] < MIN_DECILE_N or row["var"] <= 0 or row["mean"] <= 0:
        return 0.0
    f = np.clip(row["mean"] / row["var"], 0, KELLY_CAP_PER_DECILE)
    return min(f * KELLY_FRACTION_MULTIPLIER, MAX_POSITION_FRAC)


calibration_pool = []
grid_results = {m: [] for m in MONEYNESS_GRID}

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
    have_calib = len(pool_df) >= 1000
    if have_calib:
        edges = np.quantile(pool_df["pred_pct_return"], np.linspace(0, 1, N_DECILES + 1))
        edges[0], edges[-1] = -np.inf, np.inf
        pool_df["decile"] = pd.cut(pool_df["pred_pct_return"], edges, labels=False, duplicates="drop")
        decile_stats = pool_df.groupby("decile")["realized_pct_return"].agg(["mean", "var", "count"])
        cohort["decile"] = pd.cut(cohort["pred_pct_return"], edges, labels=False, duplicates="drop")

        for target_m in MONEYNESS_GRID:
            cohort["_dist"] = (cohort["moneyness_strike_over_spot"] - target_m).abs()
            nearest = cohort.loc[cohort.groupby("act_symbol")["_dist"].idxmin()].copy()
            nearest["kelly_frac"] = nearest["decile"].apply(lambda d: kelly_fraction(d, decile_stats))

            top5 = nearest.sort_values("pred_pct_return", ascending=False).head(5)
            eq_pct = float((10000/len(top5)*(1+top5["realized_pct_return"])).sum()/10000*100 - 100) if len(top5) else None

            kpicks = nearest[nearest["kelly_frac"] > 0].sort_values("pred_pct_return", ascending=False).head(8)
            tf = kpicks["kelly_frac"].sum()
            if tf > 1.0:
                kpicks = kpicks.copy(); kpicks["kelly_frac"] /= tf; tf = 1.0
            kelly_pct = float((kpicks["kelly_frac"]*kpicks["realized_pct_return"]).sum())*100 if len(kpicks) else 0.0
            actual_m = float(top5["moneyness_strike_over_spot"].mean()) if len(top5) else None
            grid_results[target_m].append({"timepoint": str(T.date()), "eq_pct": round(eq_pct, 2) if eq_pct is not None else None,
                                            "kelly_pct": round(kelly_pct, 2), "actual_avg_moneyness": round(actual_m, 3) if actual_m else None,
                                            "n": len(top5)})
    print(f"  {T.date()} done (calib_pool={'ready' if have_calib else 'warming up'}, cohort={len(cohort)})", flush=True)
    # grow the calibration pool from the FULL cohort (all strikes, all
    # tickers) -- matches the plain baseline's own calibration exactly
    # (production calibrates the GLM's predicted-vs-realized relationship
    # across the whole distribution it sees, not one strike level), and
    # warms up in one round like the baseline does instead of two.
    calibration_pool.extend(cohort[["pred_pct_return", "realized_pct_return"]].to_dict("records"))

spy = pd.read_csv(OUT_DIR.parents[1] / "scripts" / "td_data_local" / "SPY.csv", parse_dates=["date"]).sort_values("date")
spy_rets = {}
for T in TIMEPOINTS:
    e = spy[spy["date"] <= T]; x = spy[spy["date"] <= T + pd.Timedelta(days=32)]
    if e.empty or x.empty: continue
    spy_rets[str(T.date())] = (x.iloc[-1]["close"]/e.iloc[-1]["close"] - 1)*100

print(f"\n{'target':>8}{'n':>4}{'eq avg':>10}{'eq std':>10}{'eq win':>8}{'kelly avg':>11}{'kelly std':>11}{'kelly win':>10}{'realized mny':>14}")
summary = []
for m in MONEYNESS_GRID:
    rows = [r for r in grid_results[m] if r["eq_pct"] is not None]
    eq_vals = [r["eq_pct"] for r in rows]
    kelly_vals = [r["kelly_pct"] for r in rows]
    spys = [spy_rets.get(r["timepoint"]) for r in rows]
    eq_wins = sum(1 for v, s in zip(eq_vals, spys) if s is not None and v > s)
    kelly_wins = sum(1 for v, s in zip(kelly_vals, spys) if s is not None and v > s)
    avg_mny = np.mean([r["actual_avg_moneyness"] for r in rows]) if rows else None
    n = len(eq_vals)
    print(f"{m:>8.2f}{n:>4}{np.mean(eq_vals):>10.2f}{np.std(eq_vals):>10.2f}{f'{eq_wins}/{n}':>8}"
          f"{np.mean(kelly_vals):>11.2f}{np.std(kelly_vals):>11.2f}{f'{kelly_wins}/{n}':>10}{avg_mny:>14.3f}")
    summary.append({"target_moneyness": m, "n": n, "eq_avg": round(float(np.mean(eq_vals)), 2), "eq_std": round(float(np.std(eq_vals)), 2),
                     "eq_win": f"{eq_wins}/{n}", "kelly_avg": round(float(np.mean(kelly_vals)), 2), "kelly_std": round(float(np.std(kelly_vals)), 2),
                     "kelly_win": f"{kelly_wins}/{n}", "avg_realized_moneyness": round(float(avg_mny), 3) if avg_mny else None,
                     "per_timepoint": rows})

with open(OUT_DIR / "strike_grid_search_v3_sharedpool_results.json", "w") as f:
    json.dump({"summary": summary, "spy_rets": spy_rets}, f, indent=2, default=str)
print("\nsaved strike_grid_search_v3_sharedpool_results.json")
