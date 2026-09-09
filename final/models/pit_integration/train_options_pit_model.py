"""
Retrain the options calls Tweedie GLM, comparing three variants head to
head on the SAME purged walk-forward CV protocol Round 2 used
(models/options-premium-model-design.md):

  A. OLD        -- original options_calls_training.parquet, unfiltered
                   universe, price/volatility features only. This is the
                   exact Round 2 setup, recomputed here (not just quoted
                   from the doc) so the comparison is apples-to-apples
                   under identical code.
  B. BASE-PIT   -- options_calls_training_pit.parquet (point-in-time
                   market_cap>=$2B / close>=$10 eligibility floor applied
                   at each option's own entry_date), same price/volatility
                   features only. Isolates the effect of the eligibility
                   floor alone.
  C. AUG-PIT    -- same PIT-eligible universe as B, PLUS the 13 fundamentals
                   features newly joined in from the PIT panel (pe_ratio,
                   pb_ratio, ps_ratio, debt_to_equity, roe, roa,
                   gross_margin, operating_margin, fcf_margin,
                   revenue_growth_yoy, earnings_growth_yoy, rnd_intensity,
                   fundamentals_age_days). Isolates the effect of adding
                   fundamentals on top of B.

Protocol (matching Round 2 exactly): 4 purged walk-forward folds, cutoffs
2023-01-01 / 2024-01-01 / 2025-01-01 / 2026-01-01, each testing entries in
the following ~3 months, training on rows whose EXPIRATION has already
resolved by the cutoff (not just entry before cutoff -- purged). Sweep
power in {1.2,1.4,1.5,1.6,1.8} x alpha in {0,0.001,0.01,0.1,1.0} (25
combos), pick lowest mean Tweedie deviance across folds, refit on all
pre-holdout data, score once on a final holdout (entry_date >= 2026-04-01)
that the search never touched.

Missing fundamentals values (real -- e.g. rnd_intensity is legitimately
absent for ~58% of non-R&D-heavy companies) are median-imputed using ONLY
the training fold's median each time, never the full dataset -- avoids
leaking test-period information into the impute value.
Run from final/:  python3 models/pit_integration/train_options_pit_model.py
"""
import os
import json

os.makedirs("models/pit_integration/results", exist_ok=True)
os.makedirs("data/training", exist_ok=True)
import numpy as np
import pandas as pd
from sklearn.linear_model import TweedieRegressor
from sklearn.preprocessing import StandardScaler

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

POWER_GRID = [1.2, 1.4, 1.5, 1.6, 1.8]
ALPHA_GRID = [0, 0.001, 0.01, 0.1, 1.0]
FOLD_CUTOFFS = [pd.Timestamp(d) for d in
                ["2023-01-01", "2024-01-01", "2025-01-01", "2026-01-01"]]
FOLD_TEST_DAYS = 92
HOLDOUT_START = pd.Timestamp("2026-04-01")


def load(path, extra_feats):
    df = pd.read_parquet(path)
    df["entry_date"] = pd.to_datetime(df["entry_date"]).astype("datetime64[ns]")
    df["expiration_date"] = pd.to_datetime(df["expiration_date"]).astype("datetime64[ns]")
    df["return_ratio"] = df["payoff_at_expiry"] / df["entry_premium"]
    df["log_volume_20"] = np.log1p(df["volume_20"].clip(lower=0))
    feats = BASE_FEATURES + ["log_volume_20"] + extra_feats
    keep_cols = feats + ["entry_date", "expiration_date", "return_ratio", "act_symbol"]
    df = df[keep_cols].copy()
    # only require the BASE features to be non-null (matches original round-2
    # behavior); fundamentals nulls are imputed per-fold below, not dropped
    df = df.dropna(subset=BASE_FEATURES + ["log_volume_20", "return_ratio"]).reset_index(drop=True)
    return df, feats


def tweedie_deviance(y_true, y_pred, power):
    y_pred = np.clip(y_pred, 1e-6, None)
    y_true = np.clip(y_true, 0, None)
    if power == 0:
        return float(np.mean((y_true - y_pred) ** 2))
    if power == 1:
        with np.errstate(divide="ignore", invalid="ignore"):
            term = np.where(y_true > 0, y_true * np.log(y_true / y_pred), 0)
        return float(2 * np.mean(term - (y_true - y_pred)))
    if power == 2:
        return float(2 * np.mean(np.log(y_pred / y_true) + y_true / y_pred - 1))
    a = y_true ** (2 - power) / ((1 - power) * (2 - power))
    b = y_true * y_pred ** (1 - power) / (1 - power)
    c = y_pred ** (2 - power) / (2 - power)
    return float(2 * np.mean(a - b + c))


def fit_impute(train_df, test_df, feats):
    """Median-impute fundamentals nulls using TRAIN fold stats only."""
    train_df = train_df.copy()
    test_df = test_df.copy()
    for c in feats:
        if train_df[c].isna().any() or test_df[c].isna().any():
            med = train_df[c].median()
            if pd.isna(med):
                med = 0.0
            train_df[c] = train_df[c].fillna(med)
            test_df[c] = test_df[c].fillna(med)
    return train_df, test_df


def run_variant(name, path, extra_feats):
    print(f"\n{'='*70}\nVARIANT {name}: {path}\n{'='*70}", flush=True)
    df, feats = load(path, extra_feats)
    print(f"  {len(df):,} rows, {len(feats)} features: {feats}", flush=True)

    holdout_mask = df["entry_date"] >= HOLDOUT_START
    search_df = df[~holdout_mask].reset_index(drop=True)
    holdout_df = df[holdout_mask].reset_index(drop=True)
    print(f"  search pool: {len(search_df):,} rows | final holdout: {len(holdout_df):,} rows", flush=True)

    grid_scores = {}
    for power in POWER_GRID:
        for alpha in ALPHA_GRID:
            fold_devs = []
            for cutoff in FOLD_CUTOFFS:
                test_start, test_end = cutoff, cutoff + pd.Timedelta(days=FOLD_TEST_DAYS)
                train = search_df[search_df["expiration_date"] <= cutoff]
                test = search_df[(search_df["entry_date"] >= test_start) & (search_df["entry_date"] < test_end)]
                if len(train) < 5000 or len(test) < 50:
                    continue
                train_i, test_i = fit_impute(train, test, feats)
                scaler = StandardScaler().fit(train_i[feats].to_numpy())
                Xtr = np.clip(scaler.transform(train_i[feats].to_numpy()), -5, 5)
                Xte = np.clip(scaler.transform(test_i[feats].to_numpy()), -5, 5)
                model = TweedieRegressor(power=power, alpha=alpha, link="log", max_iter=300)
                model.fit(Xtr, train_i["return_ratio"].to_numpy())
                pred = model.predict(Xte)
                fold_devs.append(tweedie_deviance(test_i["return_ratio"].to_numpy(), pred, power))
            if fold_devs:
                grid_scores[(power, alpha)] = float(np.mean(fold_devs))

    best_combo = min(grid_scores, key=grid_scores.get)
    best_power, best_alpha = best_combo
    print(f"  best combo: power={best_power}, alpha={best_alpha}, "
          f"mean CV deviance={grid_scores[best_combo]:.4f}", flush=True)

    # refit on ALL pre-holdout data with the winning hyperparameters
    train_i, holdout_i = fit_impute(search_df, holdout_df, feats)
    scaler = StandardScaler().fit(train_i[feats].to_numpy())
    Xtr = np.clip(scaler.transform(train_i[feats].to_numpy()), -5, 5)
    Xho = np.clip(scaler.transform(holdout_i[feats].to_numpy()), -5, 5)
    model = TweedieRegressor(power=best_power, alpha=best_alpha, link="log", max_iter=300)
    model.fit(Xtr, train_i["return_ratio"].to_numpy())
    pred_ho = model.predict(Xho)
    y_ho = holdout_i["return_ratio"].to_numpy()

    mae = float(np.mean(np.abs(y_ho - pred_ho)))
    dev = tweedie_deviance(y_ho, pred_ho, best_power)
    dir_acc = float(np.mean((pred_ho > 1.0) == (y_ho > 1.0)))
    benchmark_mae = float(np.mean(np.abs(y_ho - 1.0)))
    benchmark_dev = tweedie_deviance(y_ho, np.ones_like(y_ho), best_power)
    benchmark_dir_acc = float(np.mean((y_ho > 1.0) == False))

    result = dict(
        variant=name, n_features=len(feats), features=feats,
        best_power=best_power, best_alpha=best_alpha,
        cv_deviance=grid_scores[best_combo],
        holdout_n=len(holdout_i),
        holdout_mae=mae, holdout_deviance=dev, holdout_dir_accuracy=dir_acc,
        benchmark_mae=benchmark_mae, benchmark_deviance=benchmark_dev,
        benchmark_dir_accuracy=benchmark_dir_acc,
        grid_scores={f"{p}_{a}": v for (p, a), v in grid_scores.items()},
    )
    print(f"  HOLDOUT ({len(holdout_i):,} rows): MAE={mae:.4f} (benchmark {benchmark_mae:.4f}) | "
          f"deviance={dev:.4f} (benchmark {benchmark_dev:.4f}) | "
          f"dir.acc={dir_acc:.4f} (benchmark {benchmark_dir_acc:.4f})", flush=True)
    return result, model, scaler


results = {}
results["OLD"], _, _ = run_variant(
    "OLD (unfiltered universe, price/vol only)",
    "data/training/options_calls_training.parquet", [])
results["BASE_PIT"], _, _ = run_variant(
    "BASE-PIT (PIT-eligible universe, price/vol only)",
    "data/training/options_calls_training_pit.parquet", [])
results["AUG_PIT"], aug_model, aug_scaler = run_variant(
    "AUG-PIT (PIT-eligible universe + fundamentals)",
    "data/training/options_calls_training_pit.parquet", FUND_FEATURES)

print(f"\n\n{'='*70}\nSUMMARY\n{'='*70}")
print(f"{'variant':<10} {'n_feat':>7} {'power':>6} {'alpha':>7} {'holdout MAE':>12} "
      f"{'holdout dev':>12} {'dir.acc':>8}")
for k, r in results.items():
    print(f"{k:<10} {r['n_features']:>7} {r['best_power']:>6} {r['best_alpha']:>7} "
          f"{r['holdout_mae']:>12.4f} {r['holdout_deviance']:>12.4f} {r['holdout_dir_accuracy']:>8.4f}")
print(f"{'benchmark':<10} {'':>7} {'':>6} {'':>7} "
      f"{results['AUG_PIT']['benchmark_mae']:>12.4f} {results['AUG_PIT']['benchmark_deviance']:>12.4f} "
      f"{results['AUG_PIT']['benchmark_dir_accuracy']:>8.4f}")

with open("models/pit_integration/results/pit_model_comparison_results.json", "w") as f:
    json.dump(results, f, indent=2, default=str)

import pickle
with open("models/pit_integration/results/final_model_calls_pit_augmented.pkl", "wb") as f:
    pickle.dump({
        "model": aug_model, "scaler": aug_scaler,
        "features": BASE_FEATURES + ["log_volume_20"] + FUND_FEATURES,
        "power": results["AUG_PIT"]["best_power"], "alpha": results["AUG_PIT"]["best_alpha"],
    }, f)
print("\nSaved pit_model_comparison_results.json and final_model_calls_pit_augmented.pkl")
