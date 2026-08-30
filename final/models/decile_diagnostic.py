"""
Supplementary diagnostic: rerun the same walk-forward loop as
optimizer_backtest.py but only to reconstruct the FINAL calibration pool
(all 6 usable timepoints' cohorts, 2021-2026), then print the full decile
table -- mean/var/count/p_win per decile -- to check whether the ranking
signal the Kelly sizing depends on is actually monotonic and sane, not
just accept the summary numbers at face value.
"""
import numpy as np
import pandas as pd
from sklearn.linear_model import TweedieRegressor
from sklearn.preprocessing import StandardScaler

FEATURES = [
    "moneyness_strike_over_spot", "days_to_expiration", "entry_iv",
    "garch_vol_forecast_1m", "realized_vol_21d_asof",
    "hv_current", "iv_current",
    "momentum_5", "momentum_20", "momentum_60", "momentum_120",
    "volatility_20", "volatility_60",
    "relative_strength_20", "pct_from_high_252", "pct_from_low_252",
    "daily_return", "cumulative_return",
]
TWEEDIE_POWER, TWEEDIE_ALPHA = 1.4, 0.001
TIMEPOINTS = [pd.Timestamp(f"{y}-01-15") for y in range(2020, 2027)]
COHORT_WINDOW_DAYS = 15
N_DECILES = 10

df = pd.read_parquet("/home/claude/garch_work/options_calls_training.parquet")
df["entry_date"] = pd.to_datetime(df["entry_date"])
df["expiration_date"] = pd.to_datetime(df["expiration_date"])
df["return_ratio"] = df["payoff_at_expiry"] / df["entry_premium"]
df["log_volume_20"] = np.log1p(df["volume_20"].clip(lower=0))
FEATS = FEATURES + ["log_volume_20"]
df = df.dropna(subset=FEATS + ["return_ratio"]).reset_index(drop=True)

pool = []
for T in TIMEPOINTS:
    train_mask = df["expiration_date"] <= T
    cohort_mask = (df["entry_date"] >= T - pd.Timedelta(days=COHORT_WINDOW_DAYS)) & \
                  (df["entry_date"] <= T + pd.Timedelta(days=COHORT_WINDOW_DAYS))
    train = df[train_mask]
    cohort = df[cohort_mask].copy()
    if len(train) < 5000 or len(cohort) < 20:
        continue
    scaler = StandardScaler().fit(train[FEATS].to_numpy())
    X_train = np.clip(scaler.transform(train[FEATS].to_numpy()), -5, 5)
    model = TweedieRegressor(power=TWEEDIE_POWER, alpha=TWEEDIE_ALPHA, link="log", max_iter=300)
    model.fit(X_train, train["return_ratio"].to_numpy())
    X_cohort = np.clip(scaler.transform(cohort[FEATS].to_numpy()), -5, 5)
    cohort["pred_pct_return"] = model.predict(X_cohort) - 1.0
    cohort["realized_pct_return"] = cohort["return_ratio"] - 1.0
    pool.append(cohort[["pred_pct_return", "realized_pct_return"]])
    print(f"{T.date()}: accumulated cohort n={len(cohort)}", flush=True)

pool_df = pd.concat(pool, ignore_index=True)
print(f"\nFull pool size: {len(pool_df)}", flush=True)

edges = np.quantile(pool_df["pred_pct_return"], np.linspace(0, 1, N_DECILES + 1))
edges[0], edges[-1] = -np.inf, np.inf
pool_df["decile"] = pd.cut(pool_df["pred_pct_return"], edges, labels=False, duplicates="drop")
stats = pool_df.groupby("decile").agg(
    n=("realized_pct_return", "count"),
    mean_realized=("realized_pct_return", "mean"),
    var_realized=("realized_pct_return", "var"),
    p_win=("realized_pct_return", lambda s: (s > 0).mean()),
    mean_pred=("pred_pct_return", "mean"),
    min_pred_edge=("pred_pct_return", "min"),
    max_pred_edge=("pred_pct_return", "max"),
)
print("\n=== Decile calibration table (pooled across all 6 timepoints, in-sample-ish since each\n    timepoint's own contribution used a model trained on PRIOR data only) ===")
print(stats.to_string(float_format=lambda x: f"{x:.4f}"))

corr = pool_df[["pred_pct_return", "realized_pct_return"]].corr().iloc[0, 1]
print(f"\nPooled pred vs realized correlation: {corr:.4f}")

# rank correlation is more relevant since we only use pred for RANKING/decile placement
from scipy.stats import spearmanr
rho, p = spearmanr(pool_df["pred_pct_return"], pool_df["realized_pct_return"])
print(f"Spearman rank correlation: {rho:.4f} (p={p:.2e})")

stats.to_csv("/home/claude/garch_work/decile_calibration_table.csv")
