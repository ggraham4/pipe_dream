"""
Dashboard-facing wrapper around the options premium (calls) model. Reads
static backtest/design artifacts directly (fast), and uses
lib/options_common.py (cached via Streamlit) for anything that needs the
Tweedie GLM fitted or the live chain scored.

Puts are intentionally NOT surfaced here as a scoreable model: per
models/options-premium-model-design.md, puts never cleared the benchmark in
round 2 and haven't been rerun since the below-intrinsic-value data cleanup
(8.36% of puts rows were contaminated, vs 0.43% for calls). The backtest
tab still shows whatever puts numbers exist in round2_results.json for
transparency, clearly labeled as "not production," but there's no puts
"Today's Picks" -- showing one would imply a working model that doesn't
exist yet.
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd
import streamlit as st

from . import paths
from . import options_common as oc


def _mtime(p):
    try:
        return p.stat().st_mtime
    except FileNotFoundError:
        return -1.0


# --------------------------------------------------------------------------
# Universe / data freshness
# --------------------------------------------------------------------------

@st.cache_data(show_spinner=False)
def _scan_parquet_dates(_path_str: str, _mtime_key: float, date_col: str, ticker_col: str):
    df = pd.read_parquet(_path_str, columns=[date_col, ticker_col])
    return {
        "n_rows": len(df),
        "n_tickers": df[ticker_col].nunique(),
        "date_min": pd.to_datetime(df[date_col]).min(),
        "date_max": pd.to_datetime(df[date_col]).max(),
    }


def universe_summary() -> dict:
    out = {"chain": None, "volhist": None, "calls_training": None, "puts_training": None}
    if paths.OPTION_CHAIN_SP500.exists():
        out["chain"] = _scan_parquet_dates(str(paths.OPTION_CHAIN_SP500), _mtime(paths.OPTION_CHAIN_SP500),
                                            "date", "act_symbol")
    if paths.VOLATILITY_HISTORY_SP500.exists():
        out["volhist"] = _scan_parquet_dates(str(paths.VOLATILITY_HISTORY_SP500), _mtime(paths.VOLATILITY_HISTORY_SP500),
                                              "date", "act_symbol")
    if paths.OPTIONS_CALLS_TRAINING.exists():
        out["calls_training"] = _scan_parquet_dates(str(paths.OPTIONS_CALLS_TRAINING), _mtime(paths.OPTIONS_CALLS_TRAINING),
                                                     "entry_date", "act_symbol")
    if paths.OPTIONS_PUTS_TRAINING.exists():
        out["puts_training"] = _scan_parquet_dates(str(paths.OPTIONS_PUTS_TRAINING), _mtime(paths.OPTIONS_PUTS_TRAINING),
                                                    "entry_date", "act_symbol")
    return out


def live_chain_meta() -> dict | None:
    if not paths.LIVE_CALLS_CHAIN.exists():
        return None
    live, _ = oc.load_live_chain()
    return {
        "entry_date": str(live["entry_date"].iloc[0].date()),
        "expiration_date": str(live["expiration_date"].iloc[0].date()),
        "n_contracts": len(live),
        "n_tickers": live["act_symbol"].nunique(),
        "snapshot_mtime": pd.Timestamp(_mtime(paths.LIVE_CALLS_CHAIN), unit="s"),
    }


# --------------------------------------------------------------------------
# Model fitting / scoring (cached)
# --------------------------------------------------------------------------

@st.cache_resource(show_spinner="Fitting the calls Tweedie GLM on the full training table...")
def _fitted_model(_mtime_key: float):
    df = oc.load_calls_training()
    scaler, model = oc.fit_tweedie(df)
    return scaler, model, df


@st.cache_resource(show_spinner="Rebuilding the decile calibration pool (walk-forward, 2020-2026)...")
def _calibration(_mtime_key: float):
    saved = oc.load_saved_decile_table()
    if saved is not None:
        # Rebuild edges from the saved table's own min/max per decile so
        # `pd.cut` reproduces the same bucketing without recomputing the
        # whole walk-forward pool every session start.
        edges = np.concatenate([[-np.inf], saved["max_pred_edge"].to_numpy()[:-1], [np.inf]])
        return saved, edges
    df = oc.load_calls_training()
    timepoints = [pd.Timestamp(f"{y}-01-15") for y in range(2020, 2027)]
    pool = oc.build_calibration_pool(df, timepoints)
    return oc.decile_table_from_pool(pool)


def get_model_and_calibration():
    if not oc.calls_training_available():
        return None
    scaler, model, df = _fitted_model(_mtime(paths.OPTIONS_CALLS_TRAINING))
    decile_stats, edges = _calibration(_mtime(paths.OPTIONS_CALLS_TRAINING))
    return {"scaler": scaler, "model": model, "training_df": df, "decile_stats": decile_stats, "edges": edges}


def get_live_scored(stock_features: pd.DataFrame):
    """Returns (ranked_df, picks_df, cash_left, meta) or None if inputs are
    missing. `stock_features` is the stock model's features.parquet -- pass
    it in rather than reloading, since the caller almost certainly already
    has it loaded for the stock-model tabs."""
    bundle = get_model_and_calibration()
    if bundle is None:
        return None
    live_scored = oc.build_scoreable_live_chain(stock_features)
    if live_scored is None:
        return None
    ranked, picks, cash_left = oc.score_and_rank(
        live_scored, bundle["scaler"], bundle["model"], bundle["decile_stats"], bundle["edges"]
    )
    meta = live_chain_meta()
    return ranked, picks, cash_left, meta


def query_ticker_options(ticker: str, stock_features: pd.DataFrame) -> pd.DataFrame | None:
    """All live strikes for one ticker, with predicted edge / decile / Kelly
    weight -- the options-model counterpart to the stock model's
    query_tickers()."""
    result = get_live_scored(stock_features)
    if result is None:
        return None
    ranked, _, _, _ = result
    # ranked only kept each ticker's BEST strike; re-score the full chain
    # for this one ticker so every available strike is shown, not just the
    # winner.
    bundle = get_model_and_calibration()
    live_scored = oc.build_scoreable_live_chain(stock_features)
    if live_scored is None:
        return None
    one = live_scored[live_scored["act_symbol"] == ticker.strip().upper()].copy()
    if one.empty:
        return None
    one = one.dropna(subset=oc.FEATURES)
    if one.empty:
        return None
    one["pred_pct_return"] = oc.predict_pct_return(bundle["scaler"], bundle["model"], one)
    one["decile"] = pd.cut(one["pred_pct_return"], bundle["edges"], labels=False, duplicates="drop")
    one["kelly_frac"] = one["decile"].apply(lambda d: oc.kelly_fraction(d, bundle["decile_stats"]))
    return one.sort_values("pred_pct_return", ascending=False).reset_index(drop=True)


# --------------------------------------------------------------------------
# Static backtest / design artifacts
# --------------------------------------------------------------------------

def get_backtest_tables() -> dict:
    result = {}
    p = paths.OPTIONS_SRC_DIR / "backtest_results.csv"
    if p.exists():
        result["calls_backtest"] = pd.read_csv(p)
    p = paths.OPTIONS_SRC_DIR / "optimizer_backtest_results.csv"
    if p.exists():
        result["old_vs_new"] = pd.read_csv(p)
    p = paths.OPTIONS_SRC_DIR / "decile_calibration_table.csv"
    if p.exists():
        result["decile_table"] = pd.read_csv(p)
    p = paths.OPTIONS_SRC_DIR / "round2_results.json"
    if p.exists():
        result["round2"] = json.loads(p.read_text())
    return result
