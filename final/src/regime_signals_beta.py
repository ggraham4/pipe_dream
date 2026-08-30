"""
BETA -- causal (no-lookahead) regime signals for the gate comparison
(regime_gate_compare_beta.py). Two independent, unsupervised gate designs:

1. Market-indicator composite: a hand-built "stress score" blending SPY
   realized volatility, SPY drawdown-from-high, VIX level, HYG (high-yield
   credit) trailing return, and GLD-vs-SPY relative return -- each turned
   into a causal rolling percentile rank (0-1, "how stressed is today
   relative to the last ~3 years, using only data up to today") and
   averaged. Deliberately NOT fit to any bull/bear label -- per the
   discussion in models/fundamentals-beta-results.md, training a
   supervised gate against SPY's future direction (or an ex-post bear-
   market label) with only one real crisis (2022) in the data would be
   fitting to n=1. This is a measurement of the PRESENT state, not a
   forecast.

2. HMM composite: a 2-state Gaussian HMM on SPY daily log returns,
   REFIT on an expanding window of history up to each as-of date (no
   future data ever enters a given fit), reading off the posterior
   probability of the higher-volatility/lower-mean ("stress") state at
   the final time step of that fit. Because every fit's data stops at
   the as-of date, the last-step posterior is causal by construction --
   it doesn't matter that hmmlearn's algorithm is technically the
   forward-backward (smoothing) recursion, since there's no future data
   in the window for it to smooth over.

Both gates output a continuous weight in [0, 1] -- interpreted as "how
much of the $10k should be allocated to the augmented (no_staleness,
defensive) model vs. the baseline (price-only, aggressive) model" -- a
continuous blend per Gabe's "80% baseline / 20% augmented" framing, not a
hard on/off switch (the doc's vol/drawdown ambiguity check found a hard
switch would bet everything on a call these signals can't reliably make).

Not wired into any trained model -- this only touches SPY.csv and the
locally-pulled VIX/GLD/TLT/HYG/TNX csvs in scripts/market_regime_data/,
and is consumed by regime_gate_compare_beta.py, which blends the ALREADY-
COMPUTED per-window returns from continuous_walkforward_beta_{baseline,
augmented}.json rather than retraining any XGBoost model.
"""
from pathlib import Path

import numpy as np
import pandas as pd
from hmmlearn.hmm import GaussianHMM

from features import DATA_DIR, PROJECT_ROOT

# VIX/GLD/HYG/TLT/TNX live alongside every other ticker's CSV in DATA_DIR
# (pulled via `local_data_pull.py "^VIX" GLD TLT HYG "^TNX"`, same directory
# local_data_pull.py always writes to) -- NOT a separate folder. yfinance's
# raw index tickers keep their "^" prefix in the filename.
REGIME_DIR = DATA_DIR
VIX_FILE, GLD_FILE, HYG_FILE, TLT_FILE, TNX_FILE = "^VIX.csv", "GLD.csv", "HYG.csv", "TLT.csv", "^TNX.csv"
ROLL_WINDOW = 756  # ~3 trading years, causal rolling lookback for percentile ranks
MIN_PERIODS = 252  # need at least ~1 trading year of history before a rank means anything


def _load_series(path, date_col="date", close_col="close"):
    df = pd.read_csv(path, parse_dates=[date_col]).sort_values(date_col).reset_index(drop=True)
    return df[[date_col, close_col]].rename(columns={date_col: "date", close_col: "close"})


def _rolling_percentile_rank(s: pd.Series, window: int, min_periods: int) -> pd.Series:
    """Causal: rank of s[t] within s[t-window+1 : t] inclusive, in [0, 1].
    Uses only data up to and including t -- no future leakage."""
    def rank_last(arr):
        return (arr <= arr[-1]).mean()
    return s.rolling(window=window, min_periods=min_periods).apply(rank_last, raw=True)


def build_market_indicator_panel():
    """Returns a DataFrame indexed by date with a causal 'stress_score' column
    in [0, 1] (higher = more stressed / more weight to the defensive model)."""
    spy = _load_series(DATA_DIR / "SPY.csv")
    vix = _load_series(REGIME_DIR / VIX_FILE)
    gld = _load_series(REGIME_DIR / GLD_FILE)
    hyg = _load_series(REGIME_DIR / HYG_FILE)

    spy["spy_ret"] = np.log(spy["close"] / spy["close"].shift(1))
    spy["vol60"] = spy["spy_ret"].rolling(60).std() * np.sqrt(252)
    spy["roll_high_252"] = spy["close"].rolling(252, min_periods=60).max()
    spy["drawdown"] = spy["close"] / spy["roll_high_252"] - 1  # <= 0
    spy["dd_depth"] = -spy["drawdown"]  # >= 0, higher = deeper drawdown

    gld["gld_ret20"] = gld["close"] / gld["close"].shift(20) - 1
    spy["spy_ret20"] = spy["close"] / spy["close"].shift(20) - 1
    hyg["hyg_ret20"] = hyg["close"] / hyg["close"].shift(20) - 1

    panel = spy[["date", "vol60", "dd_depth", "spy_ret20"]].merge(
        vix[["date", "close"]].rename(columns={"close": "vix"}), on="date", how="left"
    ).merge(
        hyg[["date", "hyg_ret20"]], on="date", how="left"
    ).merge(
        gld[["date", "gld_ret20"]], on="date", how="left"
    ).sort_values("date").reset_index(drop=True)

    # forward-fill the smaller regime-data series onto SPY's trading calendar
    # (all pulled via the same local yfinance pull, so gaps should be rare,
    # but this keeps a stray missing day from breaking a rolling window)
    panel[["vix", "hyg_ret20", "gld_ret20"]] = panel[["vix", "hyg_ret20", "gld_ret20"]].ffill()

    panel["gld_rel20"] = panel["gld_ret20"] - panel["spy_ret20"]  # GLD outperforming SPY = risk-off

    # each raw signal -> causal rolling percentile rank, all oriented so
    # HIGHER = more stress
    panel["pr_vol"] = _rolling_percentile_rank(panel["vol60"], ROLL_WINDOW, MIN_PERIODS)
    panel["pr_dd"] = _rolling_percentile_rank(panel["dd_depth"], ROLL_WINDOW, MIN_PERIODS)
    panel["pr_vix"] = _rolling_percentile_rank(panel["vix"], ROLL_WINDOW, MIN_PERIODS)
    panel["pr_hyg_stress"] = _rolling_percentile_rank(-panel["hyg_ret20"], ROLL_WINDOW, MIN_PERIODS)
    panel["pr_gld_rel"] = _rolling_percentile_rank(panel["gld_rel20"], ROLL_WINDOW, MIN_PERIODS)

    stress_cols = ["pr_vol", "pr_dd", "pr_vix", "pr_hyg_stress", "pr_gld_rel"]
    panel["stress_score"] = panel[stress_cols].mean(axis=1, skipna=True)
    panel["n_signals_available"] = panel[stress_cols].notna().sum(axis=1)

    return panel.set_index("date")


def market_indicator_weight(panel, as_of_date):
    """Causal lookup: stress_score using only data <= as_of_date (the panel
    was built entirely from trailing rolling windows, so a direct lookup at
    as_of_date is already causal -- no future rows are ever used to compute
    that row's percentile ranks)."""
    as_of_date = pd.Timestamp(as_of_date)
    idx = panel.index[panel.index <= as_of_date]
    if len(idx) == 0:
        return None, None
    row = panel.loc[idx[-1]]
    return (float(row["stress_score"]) if pd.notna(row["stress_score"]) else None,
            int(row["n_signals_available"]))


def hmm_weight(spy_returns: pd.Series, spy_dates: pd.DatetimeIndex, as_of_date, n_restarts=5):
    """Fit a 2-state Gaussian HMM on SPY daily log returns using ONLY dates
    <= as_of_date (expanding window, refit fresh each call -- cheap, ~seconds),
    then return the posterior probability of the higher-vol/lower-mean
    ('stress') state at the final (as-of) time step. Causal by construction:
    no data past as_of_date ever enters the fit or the posterior.

    EM for a Gaussian HMM has local optima, and single-seed fits on this
    data frequently reported "not converging" within a modest iteration cap
    -- refit with several random seeds (higher iter cap, tighter tol) and
    keep the highest-log-likelihood fit, rather than trusting one run."""
    as_of_date = pd.Timestamp(as_of_date)
    mask = spy_dates <= as_of_date
    rets = spy_returns[mask].dropna().values.reshape(-1, 1)
    if len(rets) < 300:
        return None

    best_score, best_model = None, None
    for seed in range(n_restarts):
        model = GaussianHMM(n_components=2, covariance_type="diag", n_iter=500,
                             random_state=seed, tol=1e-6)
        try:
            model.fit(rets)
            score = model.score(rets)
        except Exception:
            continue
        if best_score is None or score > best_score:
            best_score, best_model = score, model

    post = best_model.predict_proba(rets)  # shape (T, 2), smoothing over ONLY this expanding window
    means = best_model.means_.flatten()
    stress_state = int(np.argmin(means))  # lower mean daily return = the stress state
    return float(post[-1, stress_state])


def build_spy_returns():
    spy = _load_series(DATA_DIR / "SPY.csv")
    spy["spy_ret"] = np.log(spy["close"] / spy["close"].shift(1))
    return spy["spy_ret"], spy["date"]
