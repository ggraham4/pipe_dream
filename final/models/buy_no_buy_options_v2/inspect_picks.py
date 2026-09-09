"""
Re-run idea2-baseline (Kelly) and idea3 (Kelly + equal-weight), this time
logging FULL contract detail for every pick (strike, spot, moneyness,
premium, predicted edge, decile, buy_no_buy_proba) so we can actually look
at what's being bought, per Gabe's flag that some picks look like deep-ITM
strikes "several hundred dollars below spot."
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
N_DECILES = 10
MIN_DECILE_N = 30
KELLY_FRACTION_MULTIPLIER = 0.5
KELLY_CAP_PER_DECILE = 1.0
MAX_POSITION_FRAC = 0.30
MIN_DECILE_FOR_FILTER = 3
TIMEPOINTS = [pd.Timestamp(f"{y}-01-15") for y in range(2021, 2027)]
COHORT_WINDOW_DAYS = 15

df = pd.read_parquet(OUT_DIR / "options_calls_training_expanded_v2_with_bnb.parquet")
df["entry_date"] = pd.to_datetime(df["entry_date"])
df["expiration_date"] = pd.to_datetime(df["expiration_date"])
df["log_volume_20"] = np.log1p(df["volume_20"].clip(lower=0))
df = df.dropna(subset=BASE_FEATURES + ["buy_no_buy_proba", "return_ratio", "pct_return_on_premium"]).reset_index(drop=True)


def kelly_fraction(decile, decile_stats):
    if pd.isna(decile) or decile not in decile_stats.index:
        return 0.0
    row = decile_stats.loc[decile]
    if row["count"] < MIN_DECILE_N or row["var"] <= 0 or row["mean"] <= 0:
        return 0.0
    f = np.clip(row["mean"] / row["var"], 0, KELLY_CAP_PER_DECILE)
    return min(f * KELLY_FRACTION_MULTIPLIER, MAX_POSITION_FRAC)


calibration_pool = []
detail_log = []
for T in TIMEPOINTS:
    train_mask = df["expiration_date"] <= T
    cohort_mask = (df["entry_date"] >= T - pd.Timedelta(days=COHORT_WINDOW_DAYS)) & \
                  (df["entry_date"] <= T + pd.Timedelta(days=COHORT_WINDOW_DAYS))
    train = df[train_mask]
    cohort = df[cohort_mask].copy()
    if len(train) < 5000 or cohort.empty:
        continue
    scaler = StandardScaler().fit(train[BASE_FEATURES].to_numpy())
    Xtr = np.clip(scaler.transform(train[BASE_FEATURES].to_numpy()), -5, 5)
    model = TweedieRegressor(power=TWEEDIE_POWER, alpha=TWEEDIE_ALPHA, link="log", max_iter=300)
    model.fit(Xtr, train["return_ratio"].to_numpy())
    Xc = np.clip(scaler.transform(cohort[BASE_FEATURES].to_numpy()), -5, 5)
    cohort["pred_pct_return"] = model.predict(Xc) - 1.0
    cohort["realized_pct_return"] = cohort["return_ratio"] - 1.0

    pool_df = pd.DataFrame(calibration_pool)
    if len(pool_df) >= 2000:
        edges = np.quantile(pool_df["pred_pct_return"], np.linspace(0, 1, N_DECILES + 1))
        edges[0], edges[-1] = -np.inf, np.inf
        pool_df["decile"] = pd.cut(pool_df["pred_pct_return"], edges, labels=False, duplicates="drop")
        decile_stats = pool_df.groupby("decile")["realized_pct_return"].agg(["mean", "var", "count"])
        cohort["decile"] = pd.cut(cohort["pred_pct_return"], edges, labels=False, duplicates="drop")

        best_per_ticker = cohort.loc[cohort.groupby("act_symbol")["pred_pct_return"].idxmax()].copy()
        best_per_ticker["kelly_frac"] = best_per_ticker["decile"].apply(lambda d: kelly_fraction(d, decile_stats))

        # idea2-baseline style: top by predicted edge (Kelly-sized)
        idea2_picks = best_per_ticker[best_per_ticker["kelly_frac"] > 0].sort_values("pred_pct_return", ascending=False).head(8)
        # idea3 style: decile>=3 filter, THEN rank by buy_no_buy_proba
        survivors = best_per_ticker[best_per_ticker["decile"] >= MIN_DECILE_FOR_FILTER]
        idea3_picks = survivors[survivors["kelly_frac"] > 0].sort_values("buy_no_buy_proba", ascending=False).head(8)

        cols = ["act_symbol", "strike", "underlying_close_entry", "moneyness_strike_over_spot",
                "entry_premium", "pred_pct_return", "buy_no_buy_proba", "decile", "kelly_frac",
                "realized_pct_return"]
        detail_log.append({
            "timepoint": str(T.date()),
            "idea2_baseline_kelly_picks": idea2_picks[cols].round(4).to_dict("records"),
            "idea3_kelly_picks": idea3_picks[cols].round(4).to_dict("records"),
        })

    calibration_pool.extend(cohort[["pred_pct_return", "realized_pct_return"]].to_dict("records"))

with open(OUT_DIR / "pick_detail_inspection.json", "w") as f:
    json.dump(detail_log, f, indent=2, default=str)

for entry in detail_log:
    print(f"\n=== {entry['timepoint']} ===")
    print("-- idea2 baseline (by predicted edge) --")
    for p in entry["idea2_baseline_kelly_picks"]:
        print(f"  {p['act_symbol']:6s} strike={p['strike']:>8.2f} spot={p['underlying_close_entry']:>8.2f} "
              f"moneyness={p['moneyness_strike_over_spot']:.3f} pred%={p['pred_pct_return']*100:>7.1f} "
              f"decile={p['decile']} kelly_frac={p['kelly_frac']:.3f} realized%={p['realized_pct_return']*100:>7.1f}")
    print("-- idea3 (decile filter + buy/no-buy rank) --")
    for p in entry["idea3_kelly_picks"]:
        print(f"  {p['act_symbol']:6s} strike={p['strike']:>8.2f} spot={p['underlying_close_entry']:>8.2f} "
              f"moneyness={p['moneyness_strike_over_spot']:.3f} pred%={p['pred_pct_return']*100:>7.1f} "
              f"bnb_proba={p['buy_no_buy_proba']:.3f} decile={p['decile']} kelly_frac={p['kelly_frac']:.3f} "
              f"realized%={p['realized_pct_return']*100:>7.1f}")
