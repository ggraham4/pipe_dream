"""Decile diagnostic (spearman rank corr + per-decile mean/var/win-rate),
rerun for all three variants at the fixed production hyperparameters
(power=1.4, alpha=0.001), to see whether adding PIT eligibility / fundamentals
changes the underlying finding from the original design doc: the model's
predicted edge separates "will pay out something" from "won't" well
(near-monotonic win rate) but is NOT a reliable fine-grained ranker of mean
return above that floor.

Run from final/:  python3 models/pit_integration/decile_diagnostic_pit_variants.py
"""
import os
import numpy as np
import pandas as pd
from sklearn.linear_model import TweedieRegressor
from sklearn.preprocessing import StandardScaler
from scipy.stats import spearmanr

os.makedirs("models/pit_integration/results", exist_ok=True)
os.makedirs("data/training", exist_ok=True)

BASE_FEATURES = [
    "moneyness_strike_over_spot", "days_to_expiration", "entry_iv",
    "garch_vol_forecast_1m", "realized_vol_21d_asof",
    "hv_current", "iv_current",
    "momentum_5", "momentum_20", "momentum_60", "momentum_120",
    "volatility_20", "volatility_60",
    "relative_strength_20", "pct_from_high_252", "pct_from_low_252",
    "daily_return", "cumulative_return",
]
FUND_FEATURES = [
    "pe_ratio", "pb_ratio", "ps_ratio", "debt_to_equity", "roe", "roa",
    "gross_margin", "operating_margin", "fcf_margin",
    "revenue_growth_yoy", "earnings_growth_yoy", "rnd_intensity",
    "fundamentals_age_days",
]
TIMEPOINTS = [pd.Timestamp(f"{y}-01-15") for y in range(2020, 2027)]
COHORT_WINDOW_DAYS = 15
N_DECILES = 10
POWER, ALPHA = 1.4, 0.001


def run(name, path, extra_feats):
    df = pd.read_parquet(path)
    df["entry_date"] = pd.to_datetime(df["entry_date"]).astype("datetime64[ns]")
    df["expiration_date"] = pd.to_datetime(df["expiration_date"]).astype("datetime64[ns]")
    df["return_ratio"] = df["payoff_at_expiry"] / df["entry_premium"]
    df["log_volume_20"] = np.log1p(df["volume_20"].clip(lower=0))
    feats = BASE_FEATURES + ["log_volume_20"] + extra_feats
    df = df.dropna(subset=BASE_FEATURES + ["log_volume_20", "return_ratio"]).reset_index(drop=True)
    for c in extra_feats:
        df[c] = df[c].fillna(df[c].median())

    pool = []
    for T in TIMEPOINTS:
        train = df[df["expiration_date"] <= T].copy()
        cohort = df[(df["entry_date"] >= T - pd.Timedelta(days=COHORT_WINDOW_DAYS)) &
                    (df["entry_date"] <= T + pd.Timedelta(days=COHORT_WINDOW_DAYS))].copy()
        if len(train) < 5000 or len(cohort) < 20:
            continue
        for c in extra_feats:
            med = train[c].median()
            train[c] = train[c].fillna(med)
            cohort[c] = cohort[c].fillna(med)
        scaler = StandardScaler().fit(train[feats].to_numpy())
        Xtr = np.clip(scaler.transform(train[feats].to_numpy()), -5, 5)
        model = TweedieRegressor(power=POWER, alpha=ALPHA, link="log", max_iter=300)
        model.fit(Xtr, train["return_ratio"].to_numpy())
        Xc = np.clip(scaler.transform(cohort[feats].to_numpy()), -5, 5)
        cohort["pred_pct_return"] = model.predict(Xc) - 1.0
        cohort["realized_pct_return"] = cohort["return_ratio"] - 1.0
        pool.append(cohort[["pred_pct_return", "realized_pct_return"]])

    pool_df = pd.concat(pool, ignore_index=True)
    edges = np.quantile(pool_df["pred_pct_return"], np.linspace(0, 1, N_DECILES + 1))
    edges[0], edges[-1] = -np.inf, np.inf
    pool_df["decile"] = pd.cut(pool_df["pred_pct_return"], edges, labels=False, duplicates="drop")
    stats = pool_df.groupby("decile").agg(
        n=("realized_pct_return", "count"), mean_realized=("realized_pct_return", "mean"),
        p_win=("realized_pct_return", lambda s: (s > 0).mean()))
    rho, p = spearmanr(pool_df["pred_pct_return"], pool_df["realized_pct_return"])
    print(f"\n=== {name} ===")
    print(f"pool size: {len(pool_df):,} | spearman rho={rho:.4f} (p={p:.2e})")
    print(stats.to_string(float_format=lambda x: f"{x:.4f}"))
    stats.to_csv(f"models/pit_integration/results/decile_table_{name}.csv")
    return rho, stats


run("OLD", "data/training/options_calls_training.parquet", [])
run("BASE_PIT", "data/training/options_calls_training_pit.parquet", [])
run("AUG_PIT", "data/training/options_calls_training_pit.parquet", FUND_FEATURES)
