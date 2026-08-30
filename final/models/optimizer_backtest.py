"""
The strike/sizing optimizer from design-doc question 3, built the way
the previous backtest's calibration-gap finding demands: the model's
raw predicted % return was shown to be overconfident in magnitude (top
picks predicted 224-389% return, realized 33% to -50%) even though its
RANKING had real value (beat the naive universe average in 5/6 years).
So this optimizer does NOT trust the raw predicted number directly.
Instead:

  1. Bin every scored contract into deciles by the model's raw predicted
     edge (this uses the model only for its ranking/ordering, matching
     Gabe's fallback plan).
  2. For each decile, look at what ACTUALLY happened historically to
     contracts the model ranked that way (empirical mean return,
     variance, win rate) -- this is the calibration step, done with a
     running pool of PRIOR timepoints' full cohorts only (expanding
     window, no lookahead: a timepoint's calibration pool never
     includes itself or anything after it).
  3. Kelly-size off the empirical decile statistics (f* ~= mean/var,
     half-Kelly, capped) rather than the model's own predicted
     magnitude. A decile with empirical mean <= 0 gets sized to zero --
     this is the "use the model to filter out bad contracts" mode Gabe
     described, falling out of the sizing rule automatically rather
     than needing a separate switch.

Compares three approaches head to head at each timepoint: this
optimizer, the previous backtest's equal-weight-top-5-by-raw-prediction
approach, and the SPY / naive-universe benchmarks.
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
MIN_POOL_FOR_CALIBRATION = 2000
MIN_DECILE_N = 30            # don't trust a decile's Kelly stats below this
KELLY_FRACTION_MULTIPLIER = 0.5   # half-Kelly, standard practical safety margin
KELLY_CAP_PER_DECILE = 1.0        # cap raw f* before the half-Kelly multiplier
MAX_POSITION_FRAC = 0.30          # no single pick over 30% of capital
MAX_PICKS = 8
TOTAL_CAPITAL = 10000
OLD_N_PICKS, OLD_DOLLARS_PER_PICK = 5, 2000   # previous backtest's equal-weight rule

print("Loading calls training table (cleaned)...", flush=True)
df = pd.read_parquet("/home/claude/garch_work/options_calls_training.parquet")
df["entry_date"] = pd.to_datetime(df["entry_date"])
df["expiration_date"] = pd.to_datetime(df["expiration_date"])
df["return_ratio"] = df["payoff_at_expiry"] / df["entry_premium"]
df["log_volume_20"] = np.log1p(df["volume_20"].clip(lower=0))
FEATS = FEATURES + ["log_volume_20"]
df = df.dropna(subset=FEATS + ["return_ratio"]).reset_index(drop=True)

spy = pd.read_parquet("/home/claude/garch_work/stock_features.parquet")
spy = spy[spy["act_symbol"] == "SPY"][["date", "close"]].sort_values("date").reset_index(drop=True)


def spy_return(entry_date, exit_date):
    e = spy.loc[spy["date"] <= entry_date, "close"]
    x = spy.loc[spy["date"] <= exit_date, "close"]
    if e.empty or x.empty:
        return np.nan
    return x.iloc[-1] / e.iloc[-1] - 1


calibration_pool = []  # list of dicts: pred_pct_return, realized_pct_return
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

    scaler = StandardScaler().fit(train[FEATS].to_numpy())
    X_train = np.clip(scaler.transform(train[FEATS].to_numpy()), -5, 5)
    model = TweedieRegressor(power=TWEEDIE_POWER, alpha=TWEEDIE_ALPHA, link="log", max_iter=300)
    model.fit(X_train, train["return_ratio"].to_numpy())

    X_cohort = np.clip(scaler.transform(cohort[FEATS].to_numpy()), -5, 5)
    cohort["pred_pct_return"] = model.predict(X_cohort) - 1.0
    cohort["realized_pct_return"] = cohort["return_ratio"] - 1.0

    universe_avg_return = cohort["realized_pct_return"].mean()

    # ---------------- OLD approach: equal-weight top-5-by-raw-prediction ----------------
    best_per_ticker_old = cohort.loc[cohort.groupby("act_symbol")["pred_pct_return"].idxmax()]
    old_picks = best_per_ticker_old.sort_values("pred_pct_return", ascending=False).head(OLD_N_PICKS)
    old_dollar_pnl = (old_picks["realized_pct_return"].to_numpy() * OLD_DOLLARS_PER_PICK).sum()
    old_return_pct = old_dollar_pnl / (OLD_N_PICKS * OLD_DOLLARS_PER_PICK) if len(old_picks) == OLD_N_PICKS else np.nan

    # ---------------- NEW: calibrated-decile Kelly optimizer ----------------
    pool_df = pd.DataFrame(calibration_pool)
    if len(pool_df) >= MIN_POOL_FOR_CALIBRATION:
        edges = np.quantile(pool_df["pred_pct_return"], np.linspace(0, 1, N_DECILES + 1))
        edges[0], edges[-1] = -np.inf, np.inf
        pool_df["decile"] = pd.cut(pool_df["pred_pct_return"], edges, labels=False, duplicates="drop")
        decile_stats = pool_df.groupby("decile")["realized_pct_return"].agg(["mean", "var", "count"])
        decile_stats["p_win"] = pool_df.groupby("decile")["realized_pct_return"].apply(lambda s: (s > 0).mean())

        def kelly_fraction(decile):
            if decile not in decile_stats.index:
                return 0.0
            row = decile_stats.loc[decile]
            if row["count"] < MIN_DECILE_N or row["var"] <= 0 or row["mean"] <= 0:
                return 0.0
            f = np.clip(row["mean"] / row["var"], 0, KELLY_CAP_PER_DECILE)
            return min(f * KELLY_FRACTION_MULTIPLIER, MAX_POSITION_FRAC)

        # best strike per ticker judged by decile-implied Kelly fraction
        # (not raw prediction) -- ties broken by raw predicted edge
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
            new_picks_str = ", ".join(f"{t}({f:.0%})" for t, f in
                                       zip(picks_new["act_symbol"], picks_new["kelly_frac"] * scale))
        else:
            new_return_pct, new_picks_str, cash_left = 0.0, "(no positive-edge deciles -- all cash)", TOTAL_CAPITAL
    else:
        new_return_pct, new_picks_str, cash_left = np.nan, "(calibration pool not built up yet)", np.nan

    spy_rets_old = [spy_return(e, x) for e, x in zip(old_picks["entry_date"], old_picks["expiration_date"])]
    spy_return_pct = (np.array(spy_rets_old) * OLD_DOLLARS_PER_PICK).sum() / (OLD_N_PICKS * OLD_DOLLARS_PER_PICK) \
        if len(old_picks) == OLD_N_PICKS else np.nan

    row = dict(
        timepoint=T.date().isoformat(),
        old_picks=", ".join(old_picks["act_symbol"].tolist()),
        old_return_pct=old_return_pct,
        new_picks=new_picks_str,
        new_return_pct=new_return_pct,
        cash_left_pct=(cash_left / TOTAL_CAPITAL) if pd.notna(cash_left) else np.nan,
        spy_return_pct=spy_return_pct,
        universe_avg_return_pct=universe_avg_return,
        pool_size=len(pool_df),
    )
    rows_out.append(row)
    print(f"{T.date()}: OLD={old_return_pct:+.2%} picks=[{row['old_picks']}] | "
          f"NEW={new_return_pct if pd.notna(new_return_pct) else float('nan'):+.2%} "
          f"picks=[{new_picks_str}] cash={row['cash_left_pct'] if pd.notna(row['cash_left_pct']) else float('nan'):.0%} | "
          f"SPY={spy_return_pct:+.2%} universe={universe_avg_return:+.2%} | pool={len(pool_df)}", flush=True)

    # accumulate this timepoint's FULL cohort into the pool for future timepoints
    calibration_pool.extend(cohort[["pred_pct_return", "realized_pct_return"]].to_dict("records"))

results = pd.DataFrame(rows_out)
results.to_csv("/home/claude/garch_work/optimizer_backtest_results.csv", index=False)

valid = results.dropna(subset=["new_return_pct"])
print(f"\n=== SUMMARY (timepoints with a working calibration pool: {len(valid)}) ===", flush=True)
print(f"OLD (equal-weight top-5): avg={valid['old_return_pct'].mean():+.2%} "
      f"std={valid['old_return_pct'].std():.2%} win_vs_spy={(valid['old_return_pct']>valid['spy_return_pct']).sum()}/{len(valid)}", flush=True)
print(f"NEW (Kelly-sized, calibrated): avg={valid['new_return_pct'].mean():+.2%} "
      f"std={valid['new_return_pct'].std():.2%} win_vs_spy={(valid['new_return_pct']>valid['spy_return_pct']).sum()}/{len(valid)}", flush=True)
print(f"SPY: avg={valid['spy_return_pct'].mean():+.2%}", flush=True)
print(f"Universe avg: avg={valid['universe_avg_return_pct'].mean():+.2%}", flush=True)
