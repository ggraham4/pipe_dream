"""
Path-safe, reusable core of the options premium (calls) model.

This consolidates the logic that was previously scattered across three
cloud-sandbox scripts with hardcoded /home/claude/... paths --
final/models/live_score.py, final/models/optimizer_backtest.py, and
final/models/decile_diagnostic.py -- into one module that:

  1. Resolves every input path relative to the repo (via app/lib/paths.py),
     so it runs on Gabe's Mac the same way features.py already does for the
     stock model.
  2. Reconstructs the two features (`cumulative_return`, `volume_20`) that
     the options training table has but the current final/src/features.py
     does not compute, directly from the same raw per-ticker price CSVs --
     see `compute_extra_stock_features()` below for the exact definitions
     and why they're needed. This was reverse-engineered from the existing
     options_calls_training.parquet (verified against AMP/AAPL rows,
     2026-08-27); if you have the original script that built that table,
     prefer it over this reconstruction.
  3. Never trusts a pickled model across a fresh session -- it refits the
     Tweedie GLM from the training parquet every time it's needed (this is
     documented in the design doc as a sub-second fit even on the full
     ~600k-row table), the same "retrain fresh, don't rely on a stale
     binary" philosophy the stock model's query_day.py already uses.

Hyperparameters below (TWEEDIE_POWER/ALPHA, FEATURES) are the round-2
winning configuration recorded in final/models/round2_results.json ("calls"
key) as of 2026-08-26. If a future hyperparameter sweep changes these,
update the two constants here -- everything downstream (the app, the CLI
refresh script) picks the change up automatically.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import paths

# ---- round-2 winning hyperparameters (final/models/round2_results.json, "calls") ----
TWEEDIE_POWER = 1.4
TWEEDIE_ALPHA = 0.001

# ---- the exact feature set live_score.py / optimizer_backtest.py trained on ----
BASE_FEATURES = [
    "moneyness_strike_over_spot", "days_to_expiration", "entry_iv",
    "garch_vol_forecast_1m", "realized_vol_21d_asof",
    "hv_current", "iv_current",
    "momentum_5", "momentum_20", "momentum_60", "momentum_120",
    "volatility_20", "volatility_60",
    "relative_strength_20", "pct_from_high_252", "pct_from_low_252",
    "daily_return", "cumulative_return",
]
FEATURES = BASE_FEATURES + ["log_volume_20"]

N_DECILES = 10
MIN_DECILE_N = 30
KELLY_FRACTION_MULTIPLIER = 0.5
KELLY_CAP_PER_DECILE = 1.0
MAX_POSITION_FRAC = 0.30
TOTAL_CAPITAL_DEFAULT = 10000
MAX_PICKS_DEFAULT = 8


# --------------------------------------------------------------------------
# Training data
# --------------------------------------------------------------------------

def load_calls_training() -> pd.DataFrame:
    df = pd.read_parquet(paths.OPTIONS_CALLS_TRAINING)
    df["entry_date"] = pd.to_datetime(df["entry_date"])
    df["expiration_date"] = pd.to_datetime(df["expiration_date"])
    df["return_ratio"] = df["payoff_at_expiry"] / df["entry_premium"]
    df["log_volume_20"] = np.log1p(df["volume_20"].clip(lower=0))
    df = df.dropna(subset=FEATURES + ["return_ratio"]).reset_index(drop=True)
    return df


def calls_training_available() -> bool:
    return paths.OPTIONS_CALLS_TRAINING.exists()


def fit_tweedie(df: pd.DataFrame):
    """Fit scaler + TweedieRegressor fresh (sub-second even on the full
    table per the design doc). Returns (scaler, model)."""
    from sklearn.linear_model import TweedieRegressor
    from sklearn.preprocessing import StandardScaler

    scaler = StandardScaler().fit(df[FEATURES].to_numpy())
    X = np.clip(scaler.transform(df[FEATURES].to_numpy()), -5, 5)
    model = TweedieRegressor(power=TWEEDIE_POWER, alpha=TWEEDIE_ALPHA, link="log", max_iter=300)
    model.fit(X, df["return_ratio"].to_numpy())
    return scaler, model


def predict_pct_return(scaler, model, df: pd.DataFrame) -> np.ndarray:
    X = np.clip(scaler.transform(df[FEATURES].to_numpy()), -5, 5)
    return model.predict(X) - 1.0


# --------------------------------------------------------------------------
# Decile calibration (Kelly sizing)
# --------------------------------------------------------------------------

def build_calibration_pool(df: pd.DataFrame, timepoints: list[pd.Timestamp],
                            cohort_window_days: int = 15, min_train: int = 5000,
                            min_cohort: int = 20) -> pd.DataFrame:
    """Walk-forward, no-lookahead decile calibration pool -- same procedure
    as optimizer_backtest.py: at each timepoint, fit on everything already
    RESOLVED (expiration <= T), score that timepoint's entry cohort, and
    only ever use PRIOR timepoints' cohorts to calibrate the NEXT one when
    this is used inside a backtest. Here (for the live dashboard) we just
    want the pooled calibration table across all historical timepoints, so
    every timepoint contributes to the pool -- there's no "current" trade
    being sized within this function.
    """
    rows = []
    for T in timepoints:
        train = df[df["expiration_date"] <= T]
        cohort_mask = (df["entry_date"] >= T - pd.Timedelta(days=cohort_window_days)) & \
                      (df["entry_date"] <= T + pd.Timedelta(days=cohort_window_days))
        cohort = df[cohort_mask].copy()
        if len(train) < min_train or len(cohort) < min_cohort:
            continue
        scaler_t, model_t = fit_tweedie(train)
        cohort["pred_pct_return"] = predict_pct_return(scaler_t, model_t, cohort)
        cohort["realized_pct_return"] = cohort["return_ratio"] - 1.0
        rows.extend(cohort[["pred_pct_return", "realized_pct_return"]].to_dict("records"))
    return pd.DataFrame(rows)


def decile_table_from_pool(pool: pd.DataFrame) -> tuple[pd.DataFrame, np.ndarray]:
    edges = np.quantile(pool["pred_pct_return"], np.linspace(0, 1, N_DECILES + 1))
    edges[0], edges[-1] = -np.inf, np.inf
    pool = pool.copy()
    pool["decile"] = pd.cut(pool["pred_pct_return"], edges, labels=False, duplicates="drop")
    stats = pool.groupby("decile")["realized_pct_return"].agg(["mean", "var", "count"])
    stats["p_win"] = pool.groupby("decile")["realized_pct_return"].apply(lambda s: (s > 0).mean())
    return stats, edges


def kelly_fraction(decile, decile_stats: pd.DataFrame) -> float:
    if decile is None or pd.isna(decile) or decile not in decile_stats.index:
        return 0.0
    row = decile_stats.loc[decile]
    if row["count"] < MIN_DECILE_N or row["var"] <= 0 or row["mean"] <= 0:
        return 0.0
    f = np.clip(row["mean"] / row["var"], 0, KELLY_CAP_PER_DECILE)
    return min(f * KELLY_FRACTION_MULTIPLIER, MAX_POSITION_FRAC)


def load_saved_decile_table() -> pd.DataFrame | None:
    """The already-computed pooled decile table from
    final/models/decile_calibration_table.csv, indexed by decile, with
    columns renamed to match what kelly_fraction()/decile_table_from_pool()
    expect (mean/var/count) -- the saved CSV uses mean_realized/var_realized/n."""
    p = paths.OPTIONS_SRC_DIR / "decile_calibration_table.csv"
    if not p.exists():
        return None
    df = pd.read_csv(p).set_index("decile")
    df.index = df.index.astype(int)
    df = df.rename(columns={"mean_realized": "mean", "var_realized": "var", "n": "count"})
    return df


# --------------------------------------------------------------------------
# Feature reconstruction for live/current scoring
# --------------------------------------------------------------------------

def compute_extra_stock_features(min_periods: int = 20) -> pd.DataFrame:
    """`cumulative_return` and `volume_20` as they appear in
    options_calls_training.parquet are NOT produced by final/src/features.py
    (verified 2026-08-27 -- features.py has volume_ratio_20, a ratio, not
    volume_20, a raw rolling average; and has no cumulative_return column at
    all). Reconstructed here directly from the raw per-ticker price CSVs so
    live/current options scoring has these two features available:

        cumulative_return = close / close_at_first_available_date - 1
            (verified against AMP and AAPL rows in the existing training
            table: e.g. AAPL's ~30.7 cumulative_return on 2020-01-22 matches
            a ~$2.50 split-adjusted starting price around 2006 -> ~$79 by
            that date)
        volume_20 = rolling 20-trading-day mean of raw daily volume

    If you still have the original script that built the training table,
    prefer it over this reconstruction -- it's a best-effort match, not a
    confirmed-identical reimplementation, and a silent mismatch here would
    bias live predictions relative to what the model was trained on.
    """
    frames = []
    for f in sorted(paths.STOCK_DATA_DIR.glob("*.csv")):
        try:
            df = pd.read_csv(f, parse_dates=["date"])
        except (pd.errors.EmptyDataError, pd.errors.ParserError):
            # Can happen if this file is read exactly while
            # scripts/local_data_pull.py is rewriting it in the background
            # (a refresh job and a page load overlapping). local_data_pull.py
            # now writes atomically (temp file + rename) so this should be
            # rare, but skip-and-warn beats crashing the whole page over one
            # ticker -- just rerun after the refresh job finishes to pick it
            # back up.
            print(f"compute_extra_stock_features: couldn't read {f.name}, skipping "
                  f"(a refresh job may be rewriting it right now)")
            continue
        if df.empty:
            continue
        df = df.sort_values("date").reset_index(drop=True)
        first_close = df["close"].iloc[0]
        df["cumulative_return"] = df["close"] / first_close - 1.0
        df["volume_20"] = df["volume"].rolling(min_periods).mean()
        df["act_symbol"] = f.stem
        frames.append(df[["act_symbol", "date", "cumulative_return", "volume_20"]])
    if not frames:
        return pd.DataFrame(columns=["act_symbol", "date", "cumulative_return", "volume_20"])
    return pd.concat(frames, ignore_index=True)


# --------------------------------------------------------------------------
# Live chain scoring
# --------------------------------------------------------------------------

def load_live_chain() -> tuple[pd.DataFrame | None, pd.DataFrame | None]:
    if not paths.LIVE_CALLS_CHAIN.exists():
        return None, None
    live = pd.read_parquet(paths.LIVE_CALLS_CHAIN)
    live["entry_date"] = pd.to_datetime(live["entry_date"])
    live["expiration_date"] = pd.to_datetime(live["expiration_date"])
    volhist = pd.read_parquet(paths.LIVE_VOLHIST) if paths.LIVE_VOLHIST.exists() else None
    if volhist is not None:
        volhist["date"] = pd.to_datetime(volhist["date"])
    return live, volhist


def build_scoreable_live_chain(feat: pd.DataFrame) -> pd.DataFrame | None:
    """Join the live chain snapshot with everything the model needs:
    stock features (from features.parquet), GARCH forecast, HV/IV panel,
    and the two reconstructed features above. `feat` is the stock model's
    features.parquet (already loaded by the caller so it's only read once
    per session)."""
    live, volhist = load_live_chain()
    if live is None:
        return None
    entry_date = live["entry_date"].iloc[0]

    # Use the most recent available row ON OR BEFORE entry_date per ticker,
    # not an exact-date match -- the live chain snapshot and the stock
    # model's last feature rebuild won't always land on the same calendar
    # day (e.g. the chain was refreshed today but features.parquet is a day
    # or two stale), and an exact-match join would silently score 0
    # contracts instead of degrading gracefully to "yesterday's features."
    sf_asof = feat[feat["date"] <= entry_date].sort_values("date")
    sf_today = (sf_asof.groupby("ticker").tail(1))[
        ["ticker", "close", "daily_return", "momentum_5", "momentum_20", "momentum_60",
         "momentum_120", "volatility_20", "volatility_60", "relative_strength_20",
         "pct_from_high_252", "pct_from_low_252"]
    ].rename(columns={"ticker": "act_symbol", "close": "underlying_close_entry"})

    extra = compute_extra_stock_features()
    extra_asof = extra[extra["date"] <= entry_date].sort_values("date")
    extra_today = (extra_asof.groupby("act_symbol").tail(1))[["act_symbol", "cumulative_return", "volume_20"]]

    garch = pd.read_parquet(paths.GARCH_PARQUET) if paths.GARCH_PARQUET.exists() else None
    if garch is not None:
        garch["asof_date"] = pd.to_datetime(garch["asof_date"])
        garch_latest = (garch[garch["asof_date"] <= entry_date]
                        .sort_values("asof_date").groupby("act_symbol").tail(1)
                        [["act_symbol", "garch_vol_forecast_1m", "realized_vol_21d_asof"]])
    else:
        garch_latest = pd.DataFrame(columns=["act_symbol", "garch_vol_forecast_1m", "realized_vol_21d_asof"])

    if volhist is not None:
        volhist_today = volhist[volhist["date"] == volhist["date"].max()][["act_symbol", "hv_current", "iv_current"]]
    else:
        volhist_today = pd.DataFrame(columns=["act_symbol", "hv_current", "iv_current"])

    out = live.merge(sf_today, on="act_symbol", how="inner")
    out = out.merge(extra_today, on="act_symbol", how="left")
    out = out.merge(garch_latest, on="act_symbol", how="left")
    out = out.merge(volhist_today, on="act_symbol", how="left")
    out["moneyness_strike_over_spot"] = out["strike"] / out["underlying_close_entry"]
    out["log_volume_20"] = np.log1p(out["volume_20"].clip(lower=0))
    return out


def score_and_rank(live_scored: pd.DataFrame, scaler, model, decile_stats: pd.DataFrame,
                    edges: np.ndarray, max_picks: int = MAX_PICKS_DEFAULT,
                    total_capital: float = TOTAL_CAPITAL_DEFAULT) -> tuple[pd.DataFrame, pd.DataFrame, float]:
    before = len(live_scored)
    scoreable = live_scored.dropna(subset=FEATURES).reset_index(drop=True)
    if scoreable.empty:
        empty = scoreable.assign(pred_pct_return=[], decile=[], kelly_frac=[], rank=[])
        return empty, empty.assign(dollar_alloc=[]), total_capital
    scoreable["pred_pct_return"] = predict_pct_return(scaler, model, scoreable)
    scoreable["decile"] = pd.cut(scoreable["pred_pct_return"], edges, labels=False, duplicates="drop")
    scoreable["kelly_frac"] = scoreable["decile"].apply(lambda d: kelly_fraction(d, decile_stats))

    best_per_ticker = scoreable.loc[scoreable.groupby("act_symbol")["pred_pct_return"].idxmax()].copy()
    ranked = best_per_ticker.sort_values("pred_pct_return", ascending=False).reset_index(drop=True)
    ranked["rank"] = ranked.index + 1

    candidates = ranked[ranked["kelly_frac"] > 0].sort_values(["kelly_frac", "pred_pct_return"], ascending=False)
    picks = candidates.head(max_picks).copy()
    total_frac = picks["kelly_frac"].sum()
    scale = min(1.0, 1.0 / total_frac) if total_frac > 1.0 else 1.0
    picks["dollar_alloc"] = picks["kelly_frac"] * scale * total_capital
    cash_left = total_capital - picks["dollar_alloc"].sum()
    return ranked, picks, cash_left
