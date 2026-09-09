"""
Rerun the design doc's two backtests (equal-weight top-5, and the
calibrated-decile Kelly optimizer) for three universe/feature variants --
OLD (original, unfiltered universe, price/vol features only), BASE_PIT
(point-in-time market_cap>=$2B/close>=$10 eligibility floor applied at each
option's own entry_date, price/vol features only), and AUG_PIT (same
PIT-eligible universe plus 13 fundamentals features newly joined in from
the PIT panel). Same walk-forward discipline as the original
optimizer_backtest.py: at each of 7 annual timepoints (Jan 15, 2020-2026),
refit fresh on rows whose expiration has already resolved by that
timepoint, score the +/-15-day cohort around it, and pick either the top-5
tickers equal-weight ($2000 each) or the calibrated-decile Kelly-sized
picks (up to 8, $10,000 total, calibration pool built from all STRICTLY
PRIOR timepoints' cohorts only).

HYPERPARAM_SOURCE below controls which power/alpha each variant is scored
with:
  "fixed"  -- all three variants use the SAME hyperparameters as the
              currently-documented production model (power=1.4,
              alpha=0.001). This is the recommended, decision-relevant
              comparison: it isolates the effect of the DATA change alone
              (PIT eligibility, fundamentals) from any effect of
              independently re-tuning hyperparameters, and its OLD variant
              exactly reproduces the numbers in
              models/options-premium-model-design.md's existing backtest
              table (validated 2026-09-02: every per-timepoint return and
              the average matched to the basis point).
  "tuned"  -- each variant uses its OWN best hyperparameters from
              train_options_pit_model.py's from-scratch CV re-tune. Useful
              as a secondary check, but conflates "does the data help" with
              "did this particular from-scratch retune protocol find a
              better model" -- read it as a secondary appendix, not the
              primary comparison.
Run from final/:  python3 models/pit_integration/backtest_pit_variants.py
"""
import os
import json
import numpy as np
import pandas as pd
from sklearn.linear_model import TweedieRegressor

os.makedirs("models/pit_integration/results", exist_ok=True)
os.makedirs("data/training", exist_ok=True)
from sklearn.preprocessing import StandardScaler

HYPERPARAM_SOURCE = "fixed"  # "fixed" (recommended) or "tuned"
FIXED_POWER, FIXED_ALPHA = 1.4, 0.001

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
MIN_POOL_FOR_CALIBRATION = 2000
MIN_DECILE_N = 30
KELLY_FRACTION_MULTIPLIER = 0.5
KELLY_CAP_PER_DECILE = 1.0
MAX_POSITION_FRAC = 0.30
MAX_PICKS = 8
TOTAL_CAPITAL = 10000
OLD_N_PICKS, OLD_DOLLARS_PER_PICK = 5, 2000

with open("models/pit_integration/results/pit_model_comparison_results.json") as f:
    tuned = json.load(f)


def hyperparams_for(variant_key):
    if HYPERPARAM_SOURCE == "fixed":
        return FIXED_POWER, FIXED_ALPHA
    return tuned[variant_key]["best_power"], tuned[variant_key]["best_alpha"]


def spy_return_factory(spy_df):
    def spy_return(entry_date, exit_date):
        e = spy_df.loc[spy_df["date"] <= entry_date, "close"]
        x = spy_df.loc[spy_df["date"] <= exit_date, "close"]
        if e.empty or x.empty:
            return np.nan
        return x.iloc[-1] / e.iloc[-1] - 1
    return spy_return


def load_spy():
    # SPY close series: reconstruct from the options training data's own
    # SPY rows (SPY options trade too, so it's already in the panel) rather
    # than assume a separate stock-price file exists.
    df = pd.read_parquet("data/training/options_calls_training.parquet",
                          columns=["act_symbol", "entry_date", "underlying_close_entry"])
    spy_rows = df[df["act_symbol"] == "SPY"].copy()
    if spy_rows.empty:
        raise RuntimeError("No SPY rows found in options training data for benchmark construction.")
    spy_rows["entry_date"] = pd.to_datetime(spy_rows["entry_date"]).astype("datetime64[ns]")
    spy_rows = spy_rows.rename(columns={"entry_date": "date", "underlying_close_entry": "close"})
    spy_rows = spy_rows[["date", "close"]].drop_duplicates("date").sort_values("date").reset_index(drop=True)
    return spy_rows


SPY_DF = load_spy()
spy_return = spy_return_factory(SPY_DF)


def load_variant(path, extra_feats):
    df = pd.read_parquet(path)
    df["entry_date"] = pd.to_datetime(df["entry_date"]).astype("datetime64[ns]")
    df["expiration_date"] = pd.to_datetime(df["expiration_date"]).astype("datetime64[ns]")
    df["return_ratio"] = df["payoff_at_expiry"] / df["entry_premium"]
    df["log_volume_20"] = np.log1p(df["volume_20"].clip(lower=0))
    feats = BASE_FEATURES + ["log_volume_20"] + extra_feats
    df = df.dropna(subset=BASE_FEATURES + ["log_volume_20", "return_ratio"]).reset_index(drop=True)
    # median-impute any fundamentals nulls globally here (per-timepoint
    # refit below re-imputes properly with train-only stats; this global
    # fill is just to keep dtype clean before that)
    for c in extra_feats:
        df[c] = df[c].fillna(df[c].median())
    return df, feats


def run_backtest(name, path, extra_feats, power, alpha):
    print(f"\n{'='*70}\n{name}  (power={power}, alpha={alpha})\n{'='*70}", flush=True)
    df, feats = load_variant(path, extra_feats)

    calibration_pool = []
    rows_out = []
    for T in TIMEPOINTS:
        train_mask = df["expiration_date"] <= T
        cohort_mask = (df["entry_date"] >= T - pd.Timedelta(days=COHORT_WINDOW_DAYS)) & \
                      (df["entry_date"] <= T + pd.Timedelta(days=COHORT_WINDOW_DAYS))
        train = df[train_mask]
        cohort = df[cohort_mask].copy()
        if len(train) < 5000 or len(cohort) < 20:
            print(f"{T.date()}: skipped (train={len(train)}, cohort={len(cohort)})", flush=True)
            continue

        # re-impute fundamentals nulls using train-only median (no leakage)
        train = train.copy()
        for c in extra_feats:
            med = train[c].median()
            train[c] = train[c].fillna(med)
            cohort[c] = cohort[c].fillna(med)

        scaler = StandardScaler().fit(train[feats].to_numpy())
        X_train = np.clip(scaler.transform(train[feats].to_numpy()), -5, 5)
        model = TweedieRegressor(power=power, alpha=alpha, link="log", max_iter=300)
        model.fit(X_train, train["return_ratio"].to_numpy())

        X_cohort = np.clip(scaler.transform(cohort[feats].to_numpy()), -5, 5)
        cohort["pred_pct_return"] = model.predict(X_cohort) - 1.0
        cohort["realized_pct_return"] = cohort["return_ratio"] - 1.0
        universe_avg_return = cohort["realized_pct_return"].mean()

        best_per_ticker_old = cohort.loc[cohort.groupby("act_symbol")["pred_pct_return"].idxmax()]
        old_picks = best_per_ticker_old.sort_values("pred_pct_return", ascending=False).head(OLD_N_PICKS)
        old_dollar_pnl = (old_picks["realized_pct_return"].to_numpy() * OLD_DOLLARS_PER_PICK).sum()
        old_return_pct = old_dollar_pnl / (OLD_N_PICKS * OLD_DOLLARS_PER_PICK) if len(old_picks) == OLD_N_PICKS else np.nan

        pool_df = pd.DataFrame(calibration_pool)
        if len(pool_df) >= MIN_POOL_FOR_CALIBRATION:
            edges = np.quantile(pool_df["pred_pct_return"], np.linspace(0, 1, N_DECILES + 1))
            edges[0], edges[-1] = -np.inf, np.inf
            pool_df["decile"] = pd.cut(pool_df["pred_pct_return"], edges, labels=False, duplicates="drop")
            decile_stats = pool_df.groupby("decile")["realized_pct_return"].agg(["mean", "var", "count"])

            def kelly_fraction(decile):
                if decile not in decile_stats.index:
                    return 0.0
                row = decile_stats.loc[decile]
                if row["count"] < MIN_DECILE_N or row["var"] <= 0 or row["mean"] <= 0:
                    return 0.0
                f = np.clip(row["mean"] / row["var"], 0, KELLY_CAP_PER_DECILE)
                return min(f * KELLY_FRACTION_MULTIPLIER, MAX_POSITION_FRAC)

            cohort["decile"] = pd.cut(cohort["pred_pct_return"], edges, labels=False, duplicates="drop")
            cohort["kelly_frac"] = cohort["decile"].map(kelly_fraction).fillna(0.0)
            candidates = cohort[cohort["kelly_frac"] > 0]
            if len(candidates) > 0:
                best_per_ticker_new = candidates.loc[
                    candidates.groupby("act_symbol").apply(
                        lambda g: g.sort_values(["kelly_frac", "pred_pct_return"], ascending=False).index[0])
                ]
                picks_new = best_per_ticker_new.sort_values(
                    ["kelly_frac", "pred_pct_return"], ascending=False).head(MAX_PICKS)
                total_frac = picks_new["kelly_frac"].sum()
                scale = min(1.0, 1.0 / total_frac) if total_frac > 1.0 else 1.0
                picks_new = picks_new.copy()
                picks_new["dollar_alloc"] = picks_new["kelly_frac"] * scale * TOTAL_CAPITAL
                new_dollar_pnl = (picks_new["dollar_alloc"] * picks_new["realized_pct_return"]).sum()
                cash_left = TOTAL_CAPITAL - picks_new["dollar_alloc"].sum()
                new_return_pct = new_dollar_pnl / TOTAL_CAPITAL
            else:
                new_return_pct, cash_left = 0.0, TOTAL_CAPITAL
        else:
            new_return_pct, cash_left = np.nan, np.nan

        spy_rets_old = [spy_return(e, x) for e, x in zip(old_picks["entry_date"], old_picks["expiration_date"])]
        spy_return_pct = (np.array(spy_rets_old) * OLD_DOLLARS_PER_PICK).sum() / (OLD_N_PICKS * OLD_DOLLARS_PER_PICK) \
            if len(old_picks) == OLD_N_PICKS else np.nan

        row = dict(timepoint=T.date().isoformat(), old_picks=", ".join(old_picks["act_symbol"].tolist()),
                   old_return_pct=old_return_pct, new_return_pct=new_return_pct,
                   cash_left_pct=(cash_left / TOTAL_CAPITAL) if pd.notna(cash_left) else np.nan,
                   spy_return_pct=spy_return_pct, universe_avg_return_pct=universe_avg_return,
                   pool_size=len(pool_df))
        rows_out.append(row)
        print(f"{T.date()}: OLD={old_return_pct:+.2%} | NEW={new_return_pct if pd.notna(new_return_pct) else float('nan'):+.2%} "
              f"| SPY={spy_return_pct:+.2%} | universe={universe_avg_return:+.2%} | pool={len(pool_df)}", flush=True)

        calibration_pool.extend(cohort[["pred_pct_return", "realized_pct_return"]].to_dict("records"))

    results = pd.DataFrame(rows_out)
    valid = results.dropna(subset=["new_return_pct"])
    summary = dict(
        variant=name,
        old_avg=float(valid["old_return_pct"].mean()), old_std=float(valid["old_return_pct"].std()),
        old_win_vs_spy=int((valid["old_return_pct"] > valid["spy_return_pct"]).sum()), n=len(valid),
        new_avg=float(valid["new_return_pct"].mean()), new_std=float(valid["new_return_pct"].std()),
        new_win_vs_spy=int((valid["new_return_pct"] > valid["spy_return_pct"]).sum()),
        spy_avg=float(valid["spy_return_pct"].mean()), universe_avg=float(valid["universe_avg_return_pct"].mean()),
    )
    print(f"\n{name} SUMMARY: OLD avg={summary['old_avg']:+.2%} std={summary['old_std']:.2%} "
          f"win={summary['old_win_vs_spy']}/{summary['n']} | "
          f"NEW avg={summary['new_avg']:+.2%} std={summary['new_std']:.2%} win={summary['new_win_vs_spy']}/{summary['n']} | "
          f"SPY avg={summary['spy_avg']:+.2%} | universe avg={summary['universe_avg']:+.2%}", flush=True)
    return results, summary


all_summaries = {}
p, a = hyperparams_for("OLD")
results_old, all_summaries["OLD"] = run_backtest(
    "OLD (unfiltered universe, price/vol only)",
    "data/training/options_calls_training.parquet", [], p, a)
p, a = hyperparams_for("BASE_PIT")
results_base, all_summaries["BASE_PIT"] = run_backtest(
    "BASE-PIT (PIT-eligible universe, price/vol only)",
    "data/training/options_calls_training_pit.parquet", [], p, a)
p, a = hyperparams_for("AUG_PIT")
results_aug, all_summaries["AUG_PIT"] = run_backtest(
    "AUG-PIT (PIT-eligible universe + fundamentals)",
    "data/training/options_calls_training_pit.parquet", FUND_FEATURES, p, a)

print(f"\n\n{'='*70}\nFINAL COMPARISON\n{'='*70}")
print(f"{'variant':<10} {'OLD avg':>9} {'OLD std':>9} {'winOLD':>7} | {'NEW avg':>9} {'NEW std':>9} {'winNEW':>7}")
for k, s in all_summaries.items():
    print(f"{k:<10} {s['old_avg']:>8.2%} {s['old_std']:>8.2%} {s['old_win_vs_spy']:>4}/{s['n']:<2} | "
          f"{s['new_avg']:>8.2%} {s['new_std']:>8.2%} {s['new_win_vs_spy']:>4}/{s['n']:<2}")
print(f"SPY avg: {all_summaries['OLD']['spy_avg']:+.2%} (OLD variant's window) / "
      f"{all_summaries['BASE_PIT']['spy_avg']:+.2%} (PIT variants' window)")

suffix = HYPERPARAM_SOURCE
results_old.to_csv(f"models/pit_integration/results/backtest_OLD_{suffix}.csv", index=False)
results_base.to_csv(f"models/pit_integration/results/backtest_BASE_PIT_{suffix}.csv", index=False)
results_aug.to_csv(f"models/pit_integration/results/backtest_AUG_PIT_{suffix}.csv", index=False)
with open(f"models/pit_integration/results/backtest_summaries_{suffix}.json", "w") as f:
    json.dump(all_summaries, f, indent=2, default=str)
print(f"\nSaved per-variant CSVs and backtest_summaries_{suffix}.json")
