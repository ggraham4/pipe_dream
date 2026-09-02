"""
Dashboard-facing wrapper around the PIT (point-in-time / survivorship-bias-
corrected) buy signal in final/src/current_signal_pit.py -- the augmented
+ stop-loss model, promoted to PRIMARY at Gabe's explicit request
(2026-09-02): "we are no longer using the HMM, augmented stoploss should
be the primary model displayed in the app." Replaces
lib/regime_gate_model.py (the HMM-gated blend) as the app's "Today's
Picks" model. See backtest/survivorship-bias-correction-results.md,
Round 7 (point-in-time mid-cap+ eligibility floor) and Round 8 (stop-loss
percentage optimization -> 15%), for the full backtest history and
caveats behind this model.

Same design principle as lib/stock_model.py / lib/regime_gate_model.py:
this module doesn't reimplement the modeling logic. It reads whatever
current_signal_pit.py last wrote to out/, and can trigger a fresh run of
that script (plus its upstream feature-build steps) as a background job,
using the same run_step_sequence machinery as every other retrain button
in this app.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

from . import paths

paths.ensure_src_on_path()

SIGNAL_CSV = paths.OUT_DIR / "current_signal_pit.csv"
SIGNAL_META = paths.OUT_DIR / "current_signal_pit_meta.json"
FUND_PIT_PARQUET = paths.OUT_DIR / "features_with_fundamentals_pit.parquet"
MODEL_PATH = paths.STOCK_MODELS_DIR / "xgb_pit_augmented_model.json"

BUY_PERCENTILE_THRESHOLD = 0.25  # top quartile -> BUY, same convention as every other model in this app

CONTEXT_COLS = [
    "close", "momentum_20", "momentum_60", "momentum_120",
    "relative_strength_20", "pct_from_high_252", "pct_from_low_252", "volatility_20",
    "market_cap",
]


def _mtime(p: Path) -> float:
    try:
        return p.stat().st_mtime
    except FileNotFoundError:
        return -1.0


def get_signal() -> tuple[pd.DataFrame | None, dict | None]:
    """Reads the already-computed picks + metadata sidecar -- no computation
    happens here, mirrors stock_model.get_current_top / regime_gate_model.
    get_gated_signal. current_signal_pit.py writes both files atomically
    (temp file + os.replace), but this still wraps the read in try/except
    as a second line of defense against a concurrent-read race."""
    df = None
    if SIGNAL_CSV.exists():
        try:
            df = pd.read_csv(SIGNAL_CSV)
        except Exception:
            df = None
    meta = None
    if SIGNAL_META.exists():
        try:
            meta = json.loads(SIGNAL_META.read_text())
        except Exception:
            meta = None
    return df, meta


def fundamentals_pit_panel_exists() -> bool:
    return FUND_PIT_PARQUET.exists()


@st.cache_data(show_spinner=False)
def _pit_universe_counts(_mtime_key: float) -> dict:
    """Total distinct tickers in the PIT panel (current-universe + valid
    point-in-time gap tickers), split out from the plain current-universe
    count -- a cheap single-column read (just "ticker"), cached on the
    panel's mtime. Added 2026-09-02: the Overview tab was showing the
    OLD, non-PIT features.parquet ticker count (~1,652 -- unchanged,
    since the underlying current-universe screen didn't change) for a
    card that's now backed by the PIT model, which was confusing next to
    the PIT pipeline's own printed universe size (~1,910). This gives the
    Overview tab a number that actually reflects what the primary model
    can see."""
    from continuous_walkforward_pit import load_gap_ticker_set
    tickers = pd.read_parquet(FUND_PIT_PARQUET, columns=["ticker"])["ticker"]
    total = int(tickers.nunique())
    try:
        gap_tickers = load_gap_ticker_set()
        current_universe = int(tickers[~tickers.isin(gap_tickers)].nunique())
    except FileNotFoundError:
        current_universe = None
    return {"total_pit_tickers": total, "current_universe_tickers": current_universe}


def universe_counts() -> dict | None:
    if not FUND_PIT_PARQUET.exists():
        return None
    return _pit_universe_counts(_mtime(FUND_PIT_PARQUET))


def signal_status() -> dict:
    """Freshness check: is the saved signal as-of the latest date the
    PIT fundamentals panel actually has data for."""
    _, meta = get_signal()
    if meta is None:
        return {"exists": False, "as_of_date": None, "stale": True, "latest_data_date": None}
    latest = None
    if FUND_PIT_PARQUET.exists():
        try:
            # NOT features.latest_complete_date() -- that requires 90% of ALL
            # tickers in the panel to have a row on a date, and this panel
            # also carries ~260+ permanently-delisted point-in-time gap
            # tickers that never will. Same fix as current_signal_pit.py's
            # latest_complete_date_pit() -- current-universe tickers only.
            from current_signal_pit import latest_complete_date_pit
            from continuous_walkforward_pit import load_gap_ticker_set
            feat = pd.read_parquet(FUND_PIT_PARQUET, columns=["date", "ticker"])
            gap_tickers = load_gap_ticker_set()
            latest = str(latest_complete_date_pit(feat, gap_tickers).date())
        except Exception:
            latest = None  # mid-write or otherwise unreadable right now -- skip the staleness check this rerun
    as_of = meta.get("as_of_date")
    return {
        "exists": True, "as_of_date": as_of,
        "stale": latest is not None and as_of != latest,
        "latest_data_date": latest,
    }


# --------------------------------------------------------------------------
# Per-ticker query against the saved checkpoint (fast path -- no retraining)
# --------------------------------------------------------------------------

@st.cache_data(show_spinner=False)
def _load_fundamentals_pit_features(_mtime_key: float) -> pd.DataFrame:
    feat = pd.read_parquet(FUND_PIT_PARQUET)
    return feat.sort_values(["ticker", "date"]).reset_index(drop=True)


def get_fundamentals_pit_features() -> pd.DataFrame | None:
    if not FUND_PIT_PARQUET.exists():
        return None
    return _load_fundamentals_pit_features(_mtime(FUND_PIT_PARQUET))


def _augmented_feature_cols() -> list[str]:
    """Exactly matches AUGMENTED_FEATURE_COLS in
    final/src/current_signal_pit.py -- duplicated here rather than imported
    for the same reason regime_gate_model.py duplicates it: that script is a
    script entry point, not a lightweight import."""
    from features import FEATURE_COLS
    from fundamentals_features_beta import FUNDAMENTAL_FEATURE_COLS
    no_stale = [c for c in FUNDAMENTAL_FEATURE_COLS if c != "fundamentals_age_days"]
    return FEATURE_COLS + no_stale


def _min_market_cap_and_price() -> tuple[float, float]:
    """Reads the point-in-time mid-cap+ eligibility floor constants straight
    from continuous_walkforward_pit.py (the backtest that validated this
    model) rather than duplicating the numbers here, so a future change to
    the floor doesn't silently desync the dashboard from what was actually
    backtested."""
    from continuous_walkforward_pit import MIN_MARKET_CAP, MIN_PRICE
    return MIN_MARKET_CAP, MIN_PRICE


@st.cache_resource(show_spinner=False)
def _load_cached_pit_model(_mtime_key: float):
    from xgboost import XGBClassifier
    model = XGBClassifier()
    model.load_model(str(MODEL_PATH))
    return model


def score_universe_cached(gfeat: pd.DataFrame) -> tuple[pd.DataFrame | None, dict | None]:
    """Scores the full ELIGIBLE universe (point-in-time mid-cap+ floor
    applied) on the saved xgb_pit_augmented_model.json checkpoint at the
    as-of date recorded in current_signal_pit_meta.json, so any ticker's
    rank/percentile can be looked up instantly. `gfeat` is
    features_with_fundamentals_pit.parquet (already loaded by the caller so
    it's only read once per session). Ineligible tickers (below the
    mid-cap+ floor) are NOT dropped here -- they're scored too and flagged
    via an `eligible_today` column, so query_tickers() can tell "the model
    doesn't like it" apart from "it's not actually pickable today."""
    if not MODEL_PATH.exists():
        return None, None
    _, meta = get_signal()
    if meta is None:
        return None, None
    from features import FEATURE_COLS
    feature_cols = _augmented_feature_cols()
    min_cap, min_price = _min_market_cap_and_price()

    model = _load_cached_pit_model(_mtime(MODEL_PATH))
    as_of = pd.Timestamp(meta["as_of_date"])
    rows = gfeat[gfeat["date"] == as_of].dropna(subset=FEATURE_COLS).copy()
    if rows.empty:
        return None, meta
    rows["buy_proba"] = model.predict_proba(rows[feature_cols])[:, 1]
    rows["eligible_today"] = (rows["close"] > min_price) & (rows["market_cap"] >= min_cap)

    eligible_rows = rows[rows["eligible_today"]].copy()
    eligible_rows["rank"] = eligible_rows["buy_proba"].rank(ascending=False, method="min").astype(int)
    eligible_rows["percentile"] = eligible_rows["rank"] / len(eligible_rows) if len(eligible_rows) else None
    rows = rows.merge(eligible_rows[["ticker", "rank", "percentile"]], on="ticker", how="left")

    cols = ["ticker", "buy_proba", "rank", "percentile", "eligible_today"] + CONTEXT_COLS
    return rows[cols].sort_values("buy_proba", ascending=False).reset_index(drop=True), meta


def query_tickers(tickers: list[str]) -> dict:
    """The dashboard's 'query a specific ticker' feature for the primary
    model. Uses the cached checkpoint (fast, no retraining) and reports a
    BUY / NO BUY / INELIGIBLE / N/A verdict per ticker -- INELIGIBLE means
    the model may like it, but it fails the point-in-time mid-cap+
    eligibility floor today (e.g. market cap fell below $2B, or price fell
    below $10) so it isn't actually a live pick, distinct from a plain
    NO BUY (eligible, model just doesn't rank it highly enough)."""
    gfeat = get_fundamentals_pit_features()
    if gfeat is None:
        return {"error": "features_with_fundamentals_pit.parquet not found -- "
                          "run a retrain first (Today's Picks tab)."}

    tickers = [t.strip().upper() for t in tickers if t.strip()]
    df, meta = score_universe_cached(gfeat)

    rows = []
    for t in tickers:
        row = {"ticker": t}
        if df is not None:
            m = df[df["ticker"] == t]
            if not m.empty:
                r = m.iloc[0]
                if not bool(r["eligible_today"]):
                    row["verdict"] = "INELIGIBLE (below mid-cap+ floor today)"
                elif r["percentile"] is not None and r["percentile"] <= BUY_PERCENTILE_THRESHOLD:
                    row["verdict"] = "BUY"
                else:
                    row["verdict"] = "NO BUY"
                row["buy_proba"] = round(float(r["buy_proba"]), 4)
                if pd.notna(r["rank"]):
                    n_eligible = int(df["eligible_today"].sum())
                    row["rank"] = f"{int(r['rank'])}/{n_eligible}"
                    row["percentile"] = round(float(r["percentile"]), 4)
                for c in CONTEXT_COLS:
                    row[c] = r.get(c)
            else:
                row["verdict"] = "N/A (no data)"
        else:
            row["verdict"] = "N/A (no saved model)"
        rows.append(row)

    return {
        "as_of_date": meta["as_of_date"] if meta else None,
        "stop_loss_pct": meta.get("stop_loss_pct") if meta else None,
        "rows": rows,
    }


# --------------------------------------------------------------------------
# Model weights + backtest (mirrors stock_model.py / regime_gate_model.py's
# get_feature_importances() / get_backtest_tables() pattern)
# --------------------------------------------------------------------------

def get_feature_importances() -> pd.DataFrame | None:
    """Feature importances straight off the saved xgb_pit_augmented_model.json
    checkpoint (same gain-based feature_importances_ property every other
    model in this app uses). Returns None if the model hasn't been trained
    yet."""
    if not MODEL_PATH.exists():
        return None
    aug_cols = _augmented_feature_cols()
    model = _load_cached_pit_model(_mtime(MODEL_PATH))
    imp = (pd.DataFrame({"feature": aug_cols, "importance": model.feature_importances_})
           .sort_values("importance", ascending=False).reset_index(drop=True))
    from features import FEATURE_COLS
    fundamentals_cols = set(aug_cols) - set(FEATURE_COLS)
    imp["is_fundamentals_feature"] = imp["feature"].isin(fundamentals_cols)
    fundamentals_share = float(imp.loc[imp["is_fundamentals_feature"], "importance"].sum())
    return {"importances": imp, "fundamentals_share": fundamentals_share}


def get_backtest_tables() -> dict:
    """Backtest artifacts for the PIT augmented+stoploss model -- the
    continuous/rolling walk-forward in backtest/survivorship-bias-
    correction-results.md, Round 7 (point-in-time mid-cap+ eligibility
    floor) and Round 8 (stop-loss percentage optimization). Any file not
    present yet is simply omitted rather than raising."""
    result = {}
    p = paths.OUT_DIR / "continuous_walkforward_pit_summary_stop15.json"
    if p.exists():
        result["continuous_walkforward_summary"] = json.loads(p.read_text())
    p = paths.OUT_DIR / "continuous_walkforward_pit_augmented_stoploss_sweep.json"
    if p.exists():
        result["stop_pct_sweep"] = json.loads(p.read_text())
    return result


def retrain_commands() -> list[list[str]]:
    """The exact commands a PIT-model refresh runs, in order: rebuild the
    base price panel, apply the PIT correction (gap tickers + the
    price-discontinuity fix), merge PIT fundamentals onto it, then train
    the model fresh and recompute today's picks. Mirrors stock_model.
    retrain_commands() / regime_gate_model.retrain_commands()'s pattern.

    Note, flagged rather than silently glossed over: this does NOT refresh
    scripts/fundamentals_raw/ (current-universe SEC EDGAR fundamentals) or
    scripts/fundamentals_raw_delisted/ (Sharadar gap-ticker data) -- those
    are their own, much less frequent, separate pulls (see AGENTS.md /
    backtest/survivorship-bias-correction-results.md), same as the
    regime-gated model's retrain never refreshed its own raw fundamentals
    pull either."""
    py = sys.executable
    return [
        [py, str(paths.SRC_DIR / "features.py")],
        [py, str(paths.SRC_DIR / "features_pit.py")],
        [py, str(paths.SRC_DIR / "fundamentals_features_pit.py")],
        [py, str(paths.SRC_DIR / "current_signal_pit.py")],
    ]
