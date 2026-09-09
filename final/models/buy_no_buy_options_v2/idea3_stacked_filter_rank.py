"""
Idea 3 (my own proposal, per Gabe's "something else, I don't know" ask):
a stacked filter-then-rank model. The decile diagnostic in
models/options-premium-model-design.md found the options Tweedie GLM's
cleanest signal is separating "will pay out something" from "won't"
(win rate near-perfectly monotonic by decile) -- but its fine-grained
ranking WITHIN the non-junk deciles is weak/non-monotonic (decile 5 beat
decile 9 on mean realized return in the original documented diagnostic).
Meanwhile the buy/no-buy stock classifier has its own, separately
validated directional edge on WHICH ticker to prefer.

So: use the (baseline, no buy/no-buy feature) options Tweedie GLM purely
as an ITM-likely FILTER (keep only contracts whose predicted decile >= 3,
mirroring the production Kelly optimizer's own "zero below decile 2"
finding), then, among survivors, RANK AND SELECT tickers by the buy/no-buy
model's probability instead of the options model's own predicted edge.
Each model does the job it's actually shown evidence of being good at.

Two sizing variants, same as idea 2: equal-weight top-5, and Kelly-sized
(decile-calibrated) but with pick ORDER set by buy_no_buy_proba rather
than predicted edge.
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
TWEEDIE_POWER, TWEEDIE_ALPHA = 1.4, 0.001
N_DECILES = 10
MIN_DECILE_N = 30
KELLY_FRACTION_MULTIPLIER = 0.5
KELLY_CAP_PER_DECILE = 1.0
MAX_POSITION_FRAC = 0.30
MIN_DECILE_FOR_FILTER = 3   # keep decile >= 3 ("not junk"), per the decile diagnostic
TIMEPOINTS = [pd.Timestamp(f"{y}-01-15") for y in range(2021, 2027)]
COHORT_WINDOW_DAYS = 15

df = pd.read_parquet(OUT_DIR / "options_calls_training_expanded_v2_with_bnb.parquet")
df["entry_date"] = pd.to_datetime(df["entry_date"])
df["expiration_date"] = pd.to_datetime(df["expiration_date"])
df["log_volume_20"] = np.log1p(df["volume_20"].clip(lower=0))
df = df.dropna(subset=BASE_FEATURES + ["buy_no_buy_proba", "return_ratio", "pct_return_on_premium"]).reset_index(drop=True)
print(f"Modeling dataset: {df.shape}", flush=True)


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
    train_mask = df["expiration_date"] <= T
    cohort_mask = (df["entry_date"] >= T - pd.Timedelta(days=COHORT_WINDOW_DAYS)) & \
                  (df["entry_date"] <= T + pd.Timedelta(days=COHORT_WINDOW_DAYS))
    train = df[train_mask]
    cohort = df[cohort_mask].copy()
    if len(train) < 5000 or cohort.empty:
        print(f"  skip {T.date()}", flush=True)
        continue
    t0 = time.time()
    scaler = StandardScaler().fit(train[BASE_FEATURES].to_numpy())
    Xtr = np.clip(scaler.transform(train[BASE_FEATURES].to_numpy()), -5, 5)
    model = TweedieRegressor(power=TWEEDIE_POWER, alpha=TWEEDIE_ALPHA, link="log", max_iter=300)
    model.fit(Xtr, train["return_ratio"].to_numpy())

    Xc = np.clip(scaler.transform(cohort[BASE_FEATURES].to_numpy()), -5, 5)
    cohort["pred_pct_return"] = model.predict(Xc) - 1.0
    cohort["realized_pct_return"] = cohort["return_ratio"] - 1.0

    pool_df = pd.DataFrame(calibration_pool)
    result_row = {"timepoint": str(T.date()), "n_cohort": len(cohort)}
    if len(pool_df) >= 2000:
        edges = np.quantile(pool_df["pred_pct_return"], np.linspace(0, 1, N_DECILES + 1))
        edges[0], edges[-1] = -np.inf, np.inf
        pool_df["decile"] = pd.cut(pool_df["pred_pct_return"], edges, labels=False, duplicates="drop")
        decile_stats = pool_df.groupby("decile")["realized_pct_return"].agg(["mean", "var", "count"])
        cohort["decile"] = pd.cut(cohort["pred_pct_return"], edges, labels=False, duplicates="drop")

        # best (highest predicted edge) contract per ticker, THEN filter by that
        # contract's decile, THEN rank survivors by buy_no_buy_proba
        best_per_ticker = cohort.loc[cohort.groupby("act_symbol")["pred_pct_return"].idxmax()].copy()
        survivors = best_per_ticker[best_per_ticker["decile"] >= MIN_DECILE_FOR_FILTER]
        result_row["n_survivors"] = len(survivors)

        # equal-weight top-5 by buy_no_buy_proba among survivors
        top5 = survivors.sort_values("buy_no_buy_proba", ascending=False).head(5)
        eq_return = (10000 / len(top5) * (1 + top5["realized_pct_return"])).sum() / 10000 - 1 if len(top5) else None
        result_row["equal_weight_return_pct"] = round(float(eq_return) * 100, 2) if eq_return is not None else None
        result_row["equal_weight_picks"] = top5["act_symbol"].tolist()

        # Kelly-sized, ORDER by buy_no_buy_proba, size by decile-calibrated kelly_frac
        survivors = survivors.copy()
        survivors["kelly_frac"] = survivors["decile"].apply(lambda d: kelly_fraction(d, decile_stats))
        picks = survivors[survivors["kelly_frac"] > 0].sort_values("buy_no_buy_proba", ascending=False).head(8)
        total_frac = picks["kelly_frac"].sum()
        if total_frac > 1.0:
            picks = picks.copy()
            picks["kelly_frac"] = picks["kelly_frac"] / total_frac
            total_frac = 1.0
        kelly_return = (picks["kelly_frac"] * picks["realized_pct_return"]).sum() if len(picks) else 0.0
        result_row["kelly_return_pct"] = round(float(kelly_return) * 100, 2)
        result_row["kelly_cash_frac"] = round(float(1.0 - total_frac), 3)
        result_row["kelly_picks"] = picks["act_symbol"].tolist()
    else:
        result_row["equal_weight_return_pct"] = None
        result_row["kelly_return_pct"] = None

    per_timepoint.append(result_row)
    print(f"  {T.date()}: cohort={len(cohort)} survivors={result_row.get('n_survivors')} "
          f"EQ={result_row['equal_weight_return_pct']} KELLY={result_row['kelly_return_pct']} "
          f"fit={time.time()-t0:.1f}s", flush=True)

    calibration_pool.extend(cohort[["pred_pct_return", "realized_pct_return"]].to_dict("records"))

with open(OUT_DIR / "idea3_results.json", "w") as f:
    json.dump(per_timepoint, f, indent=2)
print("\nSaved idea3_results.json", flush=True)
