"""
Ad-hoc live run, per Gabe's curiosity: train the Tweedie GLM on the FULL
cleaned calls training set (everything resolved through today), score the
actual current option chain (entry_date = 2026-08-25, the latest available
snapshot; expiration_date = 2026-09-18, the nearest monthly expiration to
30 days out, matching the training-data entry rule), and report both the
model's raw ranking AND the calibrated-decile Kelly size for each pick --
same methodology as optimizer_backtest.py, just run once, today, live.

Calibration source: the same expanding-pool walk-forward loop as
optimizer_backtest.py (Jan timepoints 2020-2026), rebuilt here so this
script is self-contained. This is the richest non-lookahead calibration
we've validated -- NOT the full ~595k-row dataset, so decile stats carry
the same small-sample caveat already flagged in the design doc.
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
N_DECILES = 10
MIN_DECILE_N = 30
KELLY_FRACTION_MULTIPLIER = 0.5
KELLY_CAP_PER_DECILE = 1.0
MAX_POSITION_FRAC = 0.30
TOTAL_CAPITAL = 10000
MAX_PICKS = 8

ENTRY_DATE = pd.Timestamp("2026-08-25")
EXPIRATION_DATE = pd.Timestamp("2026-09-18")

print("Loading full cleaned calls training table...", flush=True)
df = pd.read_parquet("/home/claude/garch_work/options_calls_training.parquet")
df["entry_date"] = pd.to_datetime(df["entry_date"])
df["expiration_date"] = pd.to_datetime(df["expiration_date"])
df["return_ratio"] = df["payoff_at_expiry"] / df["entry_premium"]
df["log_volume_20"] = np.log1p(df["volume_20"].clip(lower=0))
FEATS = FEATURES + ["log_volume_20"]
df = df.dropna(subset=FEATS + ["return_ratio"]).reset_index(drop=True)
print(f"  {len(df)} rows, resolved through {df['expiration_date'].max().date()}", flush=True)

# ---------------------------------------------------------------
# 1. Rebuild the calibration pool -- same walk-forward loop as
#    optimizer_backtest.py, Jan timepoints 2020-2026
# ---------------------------------------------------------------
print("\nRebuilding calibration pool (walk-forward, same as optimizer_backtest.py)...", flush=True)
CAL_TIMEPOINTS = [pd.Timestamp(f"{y}-01-15") for y in range(2020, 2027)]
COHORT_WINDOW_DAYS = 15
calibration_pool = []
for T in CAL_TIMEPOINTS:
    train_mask = df["expiration_date"] <= T
    cohort_mask = (df["entry_date"] >= T - pd.Timedelta(days=COHORT_WINDOW_DAYS)) & \
                  (df["entry_date"] <= T + pd.Timedelta(days=COHORT_WINDOW_DAYS))
    train = df[train_mask]
    cohort = df[cohort_mask].copy()
    if len(train) < 5000 or len(cohort) < 20:
        continue
    scaler_t = StandardScaler().fit(train[FEATS].to_numpy())
    X_train_t = np.clip(scaler_t.transform(train[FEATS].to_numpy()), -5, 5)
    model_t = TweedieRegressor(power=TWEEDIE_POWER, alpha=TWEEDIE_ALPHA, link="log", max_iter=300)
    model_t.fit(X_train_t, train["return_ratio"].to_numpy())
    X_cohort_t = np.clip(scaler_t.transform(cohort[FEATS].to_numpy()), -5, 5)
    cohort["pred_pct_return"] = model_t.predict(X_cohort_t) - 1.0
    cohort["realized_pct_return"] = cohort["return_ratio"] - 1.0
    calibration_pool.extend(cohort[["pred_pct_return", "realized_pct_return"]].to_dict("records"))

pool_df = pd.DataFrame(calibration_pool)
print(f"  calibration pool: {len(pool_df)} rows", flush=True)

edges = np.quantile(pool_df["pred_pct_return"], np.linspace(0, 1, N_DECILES + 1))
edges[0], edges[-1] = -np.inf, np.inf
pool_df["decile"] = pd.cut(pool_df["pred_pct_return"], edges, labels=False, duplicates="drop")
decile_stats = pool_df.groupby("decile")["realized_pct_return"].agg(["mean", "var", "count"])
print("\nDecile calibration table used for sizing today:")
print(decile_stats.to_string(float_format=lambda x: f"{x:.4f}"))


def kelly_fraction(decile):
    if pd.isna(decile) or decile not in decile_stats.index:
        return 0.0
    row = decile_stats.loc[decile]
    if row["count"] < MIN_DECILE_N or row["var"] <= 0 or row["mean"] <= 0:
        return 0.0
    f = np.clip(row["mean"] / row["var"], 0, KELLY_CAP_PER_DECILE)
    return min(f * KELLY_FRACTION_MULTIPLIER, MAX_POSITION_FRAC)


# ---------------------------------------------------------------
# 2. Train the FULL model on all resolved data through today
# ---------------------------------------------------------------
print("\nTraining Tweedie GLM on the full cleaned dataset (all resolved outcomes)...", flush=True)
scaler = StandardScaler().fit(df[FEATS].to_numpy())
X_full = np.clip(scaler.transform(df[FEATS].to_numpy()), -5, 5)
model = TweedieRegressor(power=TWEEDIE_POWER, alpha=TWEEDIE_ALPHA, link="log", max_iter=300)
model.fit(X_full, df["return_ratio"].to_numpy())
print(f"  trained on {len(df)} rows", flush=True)

# ---------------------------------------------------------------
# 3. Load and feature-build the LIVE current chain (unresolved -- no target)
# ---------------------------------------------------------------
print("\nBuilding live feature set for the current chain...", flush=True)
live = pd.read_parquet("/mnt/user-data/uploads/pipe_dream/final/data/live_score/live_calls_chain.parquet")
volhist = pd.read_parquet("/mnt/user-data/uploads/pipe_dream/final/data/live_score/live_volhist.parquet")
sf = pd.read_parquet("/home/claude/garch_work/stock_features.parquet")
garch = pd.read_parquet("/home/claude/garch_work/garch_vol.parquet")

live["entry_date"] = pd.to_datetime(live["entry_date"])
live["expiration_date"] = pd.to_datetime(live["expiration_date"])

sf_today = sf[sf["date"] == ENTRY_DATE][
    ["act_symbol", "close", "cumulative_return", "daily_return",
     "momentum_5", "momentum_20", "momentum_60", "momentum_120",
     "volatility_20", "volatility_60", "volume_20",
     "relative_strength_20", "pct_from_high_252", "pct_from_low_252"]
].rename(columns={"close": "underlying_close_entry"})
print(f"  stock features available for {len(sf_today)} tickers as of {ENTRY_DATE.date()}", flush=True)

garch["asof_date"] = pd.to_datetime(garch["asof_date"])
garch_latest = garch[garch["asof_date"] <= ENTRY_DATE].sort_values("asof_date").groupby("act_symbol").tail(1)
garch_latest = garch_latest[["act_symbol", "garch_vol_forecast_1m", "realized_vol_21d_asof"]]

volhist["date"] = pd.to_datetime(volhist["date"])
volhist_today = volhist[["act_symbol", "hv_current", "iv_current"]]

live = live.merge(sf_today, on="act_symbol", how="inner")
live = live.merge(garch_latest, on="act_symbol", how="left")
live = live.merge(volhist_today, on="act_symbol", how="left")
live["moneyness_strike_over_spot"] = live["strike"] / live["underlying_close_entry"]
live["log_volume_20"] = np.log1p(live["volume_20"].clip(lower=0))

before = len(live)
live = live.dropna(subset=FEATS).reset_index(drop=True)
print(f"  {len(live)} / {before} live contracts have complete features "
      f"({live['act_symbol'].nunique()} tickers)", flush=True)

# ---------------------------------------------------------------
# 4. Score, rank, and Kelly-size
# ---------------------------------------------------------------
X_live = np.clip(scaler.transform(live[FEATS].to_numpy()), -5, 5)
live["pred_pct_return"] = model.predict(X_live) - 1.0
live["decile"] = pd.cut(live["pred_pct_return"], edges, labels=False, duplicates="drop")
live["kelly_frac"] = live["decile"].map(kelly_fraction).fillna(0.0)

# best strike per ticker by raw predicted edge (the model's OWN ranking)
best_per_ticker = live.loc[live.groupby("act_symbol")["pred_pct_return"].idxmax()].copy()
ranked = best_per_ticker.sort_values("pred_pct_return", ascending=False).reset_index(drop=True)
ranked["rank"] = ranked.index + 1

print(f"\n=== FULL RANKING: top 20 of {len(ranked)} tickers by predicted edge, entry {ENTRY_DATE.date()}, "
      f"expiring {EXPIRATION_DATE.date()} ===", flush=True)
print(ranked[["rank", "act_symbol", "strike", "underlying_close_entry", "entry_premium",
              "days_to_expiration", "pred_pct_return", "decile", "kelly_frac"]].head(20)
      .to_string(index=False, float_format=lambda x: f"{x:.4f}"), flush=True)

# the actual Kelly-sized picks (mirrors optimizer_backtest.py's NEW approach)
candidates = ranked[ranked["kelly_frac"] > 0].sort_values(
    ["kelly_frac", "pred_pct_return"], ascending=False)
picks = candidates.head(MAX_PICKS).copy()
total_frac = picks["kelly_frac"].sum()
scale = min(1.0, 1.0 / total_frac) if total_frac > 1.0 else 1.0
picks["dollar_alloc"] = picks["kelly_frac"] * scale * TOTAL_CAPITAL
cash_left = TOTAL_CAPITAL - picks["dollar_alloc"].sum()

print(f"\n=== KELLY-SIZED PICKS (calibrated-decile optimizer, ${TOTAL_CAPITAL:,} notional) ===", flush=True)
if len(picks) > 0:
    print(picks[["rank", "act_symbol", "strike", "entry_premium", "days_to_expiration",
                  "pred_pct_return", "decile", "kelly_frac", "dollar_alloc"]]
          .to_string(index=False, float_format=lambda x: f"{x:.4f}"), flush=True)
else:
    print("(no positive-edge deciles today -- all cash)", flush=True)
print(f"Cash held: ${cash_left:,.2f} ({cash_left/TOTAL_CAPITAL:.0%})", flush=True)
print(f"Tickers with a positive-Kelly candidate: {live.loc[live['kelly_frac']>0,'act_symbol'].nunique()} "
      f"of {live['act_symbol'].nunique()} scored", flush=True)

ranked.to_csv("/home/claude/garch_work/live_score_full_ranking.csv", index=False)
picks.to_csv("/home/claude/garch_work/live_score_kelly_picks.csv", index=False)
print("\nSaved live_score_full_ranking.csv and live_score_kelly_picks.csv", flush=True)
