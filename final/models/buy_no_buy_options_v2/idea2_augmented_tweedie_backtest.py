"""
Idea 2 (Gabe's framing): "a more advanced model, but the buy/no-buy model
is an input" -- add the buy/no-buy classifier's walk-forward probability
as one more feature to the production options Tweedie GLM (power=1.4,
alpha=0.001, unchanged -- isolating the effect of the new feature, not
re-tuning), retrain BASELINE (without) vs AUGMENTED (with) on the same
expanded-universe calls data, and run the identical walk-forward dollar
backtest (equal-weight top-5 AND calibrated-decile Kelly sizing) used
throughout models/options-premium-model-design.md.

GARCH forecast is dropped from FEATURES (not rebuilt for the expanded
universe here -- see build02c's docstring for why); everything else
matches live_score.py's FEATURES list and Kelly-sizing constants exactly.
"""
from pathlib import Path
import time
import json
import numpy as np
import pandas as pd
from sklearn.linear_model import TweedieRegressor
from sklearn.preprocessing import StandardScaler

OUT_DIR = Path(__file__).resolve().parent
REPO_FINAL = Path(__file__).resolve().parents[2]

BASE_FEATURES = [
    "moneyness_strike_over_spot", "days_to_expiration", "entry_iv",
    "realized_vol_21d_asof", "hv_current", "iv_current",
    "momentum_5", "momentum_20", "momentum_60", "momentum_120",
    "volatility_20", "volatility_60",
    "relative_strength_20", "pct_from_high_252", "pct_from_low_252",
    "daily_return", "cumulative_return", "log_volume_20",
]
AUG_FEATURES = BASE_FEATURES + ["buy_no_buy_proba"]
TWEEDIE_POWER, TWEEDIE_ALPHA = 1.4, 0.001
N_DECILES = 10
MIN_DECILE_N = 30
KELLY_FRACTION_MULTIPLIER = 0.5
KELLY_CAP_PER_DECILE = 1.0
MAX_POSITION_FRAC = 0.30
TIMEPOINTS = [pd.Timestamp(f"{y}-01-15") for y in range(2021, 2027)]
COHORT_WINDOW_DAYS = 15

df = pd.read_parquet(OUT_DIR / "options_calls_training_expanded_v2_with_bnb.parquet")
df["entry_date"] = pd.to_datetime(df["entry_date"])
df["expiration_date"] = pd.to_datetime(df["expiration_date"])
df["log_volume_20"] = np.log1p(df["volume_20"].clip(lower=0))
df = df.dropna(subset=AUG_FEATURES + ["return_ratio", "pct_return_on_premium"]).reset_index(drop=True)
print(f"Modeling dataset: {df.shape}, entries {df['entry_date'].min().date()} to {df['entry_date'].max().date()}", flush=True)

spy = pd.read_csv(REPO_FINAL / "scripts" / "td_data_local" / "SPY.csv", parse_dates=["date"]).sort_values("date")


def fit_tweedie(train_df, feats):
    scaler = StandardScaler().fit(train_df[feats].to_numpy())
    X = np.clip(scaler.transform(train_df[feats].to_numpy()), -5, 5)
    model = TweedieRegressor(power=TWEEDIE_POWER, alpha=TWEEDIE_ALPHA, link="log", max_iter=300)
    model.fit(X, train_df["return_ratio"].to_numpy())
    return model, scaler


def predict_tweedie(model, scaler, test_df, feats):
    X = np.clip(scaler.transform(test_df[feats].to_numpy()), -5, 5)
    return model.predict(X) - 1.0  # pred_pct_return


def kelly_fraction(decile, decile_stats):
    if pd.isna(decile) or decile not in decile_stats.index:
        return 0.0
    row = decile_stats.loc[decile]
    if row["count"] < MIN_DECILE_N or row["var"] <= 0 or row["mean"] <= 0:
        return 0.0
    f = np.clip(row["mean"] / row["var"], 0, KELLY_CAP_PER_DECILE)
    return min(f * KELLY_FRACTION_MULTIPLIER, MAX_POSITION_FRAC)


def run_variant(feats, label):
    print(f"\n=== {label} ({len(feats)} features) ===", flush=True)
    calibration_pool = []
    per_timepoint = []
    for T in TIMEPOINTS:
        train_mask = df["expiration_date"] <= T
        cohort_mask = (df["entry_date"] >= T - pd.Timedelta(days=COHORT_WINDOW_DAYS)) & \
                      (df["entry_date"] <= T + pd.Timedelta(days=COHORT_WINDOW_DAYS))
        train = df[train_mask]
        cohort = df[cohort_mask].copy()
        if len(train) < 5000 or cohort.empty:
            print(f"  skip {T.date()}: train={len(train)} cohort={len(cohort)}", flush=True)
            continue
        t0 = time.time()
        model, scaler = fit_tweedie(train, feats)
        cohort["pred_pct_return"] = predict_tweedie(model, scaler, cohort, feats)
        cohort["realized_pct_return"] = cohort["return_ratio"] - 1.0

        # decile calibration from the pool BEFORE this timepoint (no lookahead)
        pool_df = pd.DataFrame(calibration_pool)
        if len(pool_df) >= 2000:
            edges = np.quantile(pool_df["pred_pct_return"], np.linspace(0, 1, N_DECILES + 1))
            edges[0], edges[-1] = -np.inf, np.inf
            pool_df["decile"] = pd.cut(pool_df["pred_pct_return"], edges, labels=False, duplicates="drop")
            decile_stats = pool_df.groupby("decile")["realized_pct_return"].agg(["mean", "var", "count"])
            cohort["decile"] = pd.cut(cohort["pred_pct_return"], edges, labels=False, duplicates="drop")
            cohort["kelly_frac"] = cohort["decile"].apply(lambda d: kelly_fraction(d, decile_stats))
            kelly_ready = True
        else:
            kelly_ready = False

        # OLD sizing: equal-weight top-5 TICKERS by best-predicted-edge strike
        best_per_ticker = cohort.loc[cohort.groupby("act_symbol")["pred_pct_return"].idxmax()]
        top5 = best_per_ticker.sort_values("pred_pct_return", ascending=False).head(5)
        old_return = (10000 / len(top5) * (1 + top5["realized_pct_return"])).sum() / 10000 - 1 if len(top5) else None

        # NEW sizing: Kelly across up to 8 picks (best per ticker, ranked by kelly weight)
        new_return, cash_frac = None, None
        if kelly_ready:
            best_per_ticker["decile"] = pd.cut(best_per_ticker["pred_pct_return"], edges, labels=False, duplicates="drop")
            best_per_ticker["kelly_frac"] = best_per_ticker["decile"].apply(lambda d: kelly_fraction(d, decile_stats))
            picks = best_per_ticker[best_per_ticker["kelly_frac"] > 0].sort_values("kelly_frac", ascending=False).head(8)
            total_frac = picks["kelly_frac"].sum()
            if total_frac > 1.0:
                picks = picks.copy()
                picks["kelly_frac"] = picks["kelly_frac"] / total_frac
                total_frac = 1.0
            invested_return = (picks["kelly_frac"] * picks["realized_pct_return"]).sum() if len(picks) else 0.0
            cash_frac = 1.0 - total_frac
            new_return = invested_return  # cash contributes 0

        spy_entry = spy[spy["date"] <= T].iloc[-1] if not spy[spy["date"] <= T].empty else None

        per_timepoint.append({
            "timepoint": str(T.date()), "n_cohort": len(cohort),
            "old_return_pct": round(float(old_return) * 100, 2) if old_return is not None else None,
            "new_return_pct": round(float(new_return) * 100, 2) if new_return is not None else None,
            "cash_frac": round(float(cash_frac), 3) if cash_frac is not None else None,
        })
        print(f"  {T.date()}: train={len(train)} cohort={len(cohort)} fit={time.time()-t0:.1f}s "
              f"OLD={per_timepoint[-1]['old_return_pct']} NEW={per_timepoint[-1]['new_return_pct']}", flush=True)

        calibration_pool.extend(cohort[["pred_pct_return", "realized_pct_return"]].to_dict("records"))

    return per_timepoint


baseline_results = run_variant(BASE_FEATURES, "BASELINE (no buy/no-buy feature)")
augmented_results = run_variant(AUG_FEATURES, "AUGMENTED (+ buy_no_buy_proba)")

with open(OUT_DIR / "idea2_results.json", "w") as f:
    json.dump({"baseline": baseline_results, "augmented": augmented_results}, f, indent=2)
print("\nSaved idea2_results.json", flush=True)
