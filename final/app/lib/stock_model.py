"""
Dashboard-facing wrapper around the stock buy/no-buy pipeline in final/src/.

Design principle: this module never re-implements the modeling logic. It
imports FEATURE_COLS, FORWARD_WINDOW, LABEL_COL, SEQ_LEN, BuySignalLSTM,
SequenceIndex, train_lstm, etc. directly from final/src/features.py and
final/src/lstm_backtest.py, and reads the same out/*.csv, out/*.json,
out/models/* artifacts those scripts already produce. If Gabe changes a
hyperparameter, adds a feature, or changes the horizon in features.py, this
module picks it up automatically the next time the underlying scripts are
rerun -- there is nothing here to keep in sync by hand.

Two ways a ticker gets scored, and this module is explicit about which one
is happening:
  1. "cached" -- load the already-trained xgb_current_model.json /
     lstm_current_model.pt (saved by current_signal.py / lstm_current_
     signal.py) and just run inference. Instant. This is what "Today's
     Picks" and "Query a Ticker" use by default.
  2. "retrain" -- actually rerun current_signal.py / lstm_current_signal.py
     as a subprocess against the latest features.parquet. Slower (LSTM
     retrain is ~40-60s per the project's own backtest logs), but is the
     only way to pick up newly-pulled price data. Triggered explicitly by
     the "Retrain on latest data" button, not automatically.
"""
from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st

from . import paths

paths.ensure_src_on_path()

BUY_PERCENTILE_THRESHOLD = 0.25  # top quartile -> BUY, mirrors recommend.py / the label's own definition

CONTEXT_COLS = [
    "close", "momentum_20", "momentum_60", "momentum_120",
    "relative_strength_20", "pct_from_high_252", "pct_from_low_252", "volatility_20",
]


# --------------------------------------------------------------------------
# Data loading
# --------------------------------------------------------------------------

def _mtime(p: Path) -> float:
    try:
        return p.stat().st_mtime
    except FileNotFoundError:
        return -1.0


@st.cache_data(show_spinner=False)
def load_features(_mtime_key: float) -> pd.DataFrame:
    """Cache-keyed on the file's mtime so a data refresh invalidates it."""
    feat = pd.read_parquet(paths.FEATURES_PARQUET)
    return feat.sort_values(["ticker", "date"]).reset_index(drop=True)


def get_features() -> pd.DataFrame | None:
    if not paths.FEATURES_PARQUET.exists():
        return None
    return load_features(_mtime(paths.FEATURES_PARQUET))


def features_available() -> bool:
    return paths.FEATURES_PARQUET.exists()


def universe_summary() -> dict:
    """Universe size + training-data extent, read live from features.parquet
    (and the raw per-ticker CSV count) rather than hardcoded, so this stays
    correct as the universe grows."""
    from features import FORWARD_WINDOW, FEATURE_COLS, LABEL_COL  # local import: needs sys.path set up

    out = {
        "csv_ticker_count": None,
        "feature_ticker_count": None,
        "date_min": None,
        "date_max": None,
        "forward_window_days": FORWARD_WINDOW,
        "feature_cols": FEATURE_COLS,
        "total_rows": None,
        "labeled_rows": None,
    }
    if paths.STOCK_DATA_DIR.exists():
        out["csv_ticker_count"] = len(list(paths.STOCK_DATA_DIR.glob("*.csv")))
    feat = get_features()
    if feat is not None:
        out["feature_ticker_count"] = feat["ticker"].nunique()
        out["date_min"] = feat["date"].min()
        out["date_max"] = feat["date"].max()
        out["total_rows"] = len(feat)
        out["labeled_rows"] = feat.dropna(subset=FEATURE_COLS + [LABEL_COL]).shape[0]
    return out


def get_current_top(model: str) -> tuple[pd.DataFrame | None, dict | None]:
    """model: 'xgb' or 'lstm'. Reads the already-computed top-N list + its
    metadata sidecar, exactly what current_signal.py / lstm_current_signal.py
    last wrote -- no computation happens here."""
    if model == "xgb":
        csv_path, meta_path = paths.OUT_DIR / "current_top10.csv", paths.OUT_DIR / "current_signal_meta.json"
    else:
        csv_path, meta_path = paths.OUT_DIR / "lstm_current_top10.csv", paths.OUT_DIR / "lstm_current_signal_meta.json"
    df = pd.read_csv(csv_path) if csv_path.exists() else None
    meta = json.loads(meta_path.read_text()) if meta_path.exists() else None
    return df, meta


def get_feature_importances() -> pd.DataFrame | None:
    p = paths.OUT_DIR / "feature_importances.csv"
    if not p.exists():
        return None
    df = pd.read_csv(p)
    df.columns = ["feature", "importance"]
    return df.sort_values("importance", ascending=False).reset_index(drop=True)


def get_backtest_tables() -> dict:
    """Everything backtest.py / lstm_backtest.py / horizon_sweep.py wrote to
    out/, bundled for display. Any file that isn't there yet (e.g. before
    the first backtest run) is simply omitted rather than raising."""
    result = {}
    for key, fname, kind in [
        ("xgb_picks", "backtest_picks.csv", "csv"),
        ("xgb_metrics", "backtest_metrics.json", "json"),
        ("xgb_results", "backtest_results.json", "json"),
        ("lstm_picks", "lstm_backtest_picks.csv", "csv"),
        ("lstm_metrics", "lstm_backtest_metrics.json", "json"),
        ("lstm_results", "lstm_backtest_results.json", "json"),
        ("horizon_sweep", "horizon_sweep_summary.json", "json"),
    ]:
        p = paths.OUT_DIR / fname
        if not p.exists():
            continue
        if kind == "csv":
            result[key] = pd.read_csv(p)
        else:
            result[key] = json.loads(p.read_text())
    chart = paths.OUT_DIR / "backtest_chart.png"
    result["chart_path"] = chart if chart.exists() else None
    return result


# --------------------------------------------------------------------------
# Cached-model scoring (fast path -- no retraining)
# --------------------------------------------------------------------------

@dataclass
class CachedModelStatus:
    exists: bool
    as_of_date: str | None
    stale: bool          # True if features.parquet has newer data than the saved model
    latest_data_date: str | None


def _xgb_meta():
    p = paths.STOCK_MODELS_DIR / "xgb_current_model_meta.json"
    return json.loads(p.read_text()) if p.exists() else None


def _lstm_meta():
    p = paths.STOCK_MODELS_DIR / "lstm_current_model_meta.json"
    return json.loads(p.read_text()) if p.exists() else None


def lstm_meta():
    """Public accessor -- the LSTM's full saved-checkpoint metadata
    (architecture + training config), for the Model Weights tab."""
    return _lstm_meta()


def cached_model_status(model: str) -> CachedModelStatus:
    from features import latest_complete_date

    meta = _xgb_meta() if model == "xgb" else _lstm_meta()
    feat = get_features()
    latest = str(latest_complete_date(feat).date()) if feat is not None else None
    if meta is None:
        return CachedModelStatus(False, None, True, latest)
    as_of = meta.get("as_of_date")
    return CachedModelStatus(True, as_of, (latest is not None and as_of != latest), latest)


@st.cache_resource(show_spinner=False)
def _load_cached_xgb(_meta_mtime: float):
    from xgboost import XGBClassifier
    model = XGBClassifier()
    model.load_model(str(paths.STOCK_MODELS_DIR / "xgb_current_model.json"))
    meta = _xgb_meta()
    return model, meta


@st.cache_resource(show_spinner=False)
def _load_cached_lstm(_meta_mtime: float):
    import torch
    from lstm_backtest import BuySignalLSTM

    meta = _lstm_meta()
    norm = np.load(paths.STOCK_MODELS_DIR / "lstm_current_norm.npz")
    model = BuySignalLSTM(
        num_features=len(meta["feature_cols"]),
        hidden_size=meta.get("hidden_size", 32),
        num_layers=meta.get("num_layers", 1),
    )
    state = torch.load(paths.STOCK_MODELS_DIR / "lstm_current_model.pt", map_location="cpu")
    model.load_state_dict(state)
    model.eval()
    return model, meta, norm["mean"], norm["std"]


def score_universe_cached(model: str, feat: pd.DataFrame) -> tuple[pd.DataFrame | None, dict | None]:
    """Score the FULL universe on the cached model's as_of_date, so any
    ticker's rank/percentile can be looked up instantly. Returns
    (dataframe[ticker, buy_proba, rank, percentile, ...context], meta)."""
    if model == "xgb":
        meta_path = paths.STOCK_MODELS_DIR / "xgb_current_model_meta.json"
        if not meta_path.exists():
            return None, None
        xgb_model, meta = _load_cached_xgb(_mtime(meta_path))
        as_of = pd.Timestamp(meta["as_of_date"])
        rows = feat[feat["date"] == as_of].dropna(subset=meta["feature_cols"]).copy()
        if rows.empty:
            return None, meta
        rows["buy_proba"] = xgb_model.predict_proba(rows[meta["feature_cols"]])[:, 1]
        rows["rank"] = rows["buy_proba"].rank(ascending=False, method="min").astype(int)
        rows["percentile"] = rows["rank"] / len(rows)
        cols = ["ticker", "buy_proba", "rank", "percentile"] + CONTEXT_COLS
        return rows[cols].sort_values("buy_proba", ascending=False).reset_index(drop=True), meta

    else:
        meta_path = paths.STOCK_MODELS_DIR / "lstm_current_model_meta.json"
        if not meta_path.exists():
            return None, None
        import torch
        from lstm_backtest import SequenceIndex

        model_obj, meta, mean, std = _load_cached_lstm(_mtime(meta_path))
        as_of = np.datetime64(pd.Timestamp(meta["as_of_date"]))
        idx_store = SequenceIndex(feat)
        mask = idx_store.dates == as_of
        idxs = np.where(mask)[0]
        if len(idxs) == 0:
            return None, meta
        X = (idx_store.sequences_for(idxs) - mean) / std
        with torch.no_grad():
            probs = torch.sigmoid(model_obj(torch.tensor(X, dtype=torch.float32))).numpy()
        tickers = idx_store.tickers_for(idxs)
        df = pd.DataFrame({"ticker": tickers, "buy_proba": probs})
        df["rank"] = df["buy_proba"].rank(ascending=False, method="min").astype(int)
        df["percentile"] = df["rank"] / len(df)
        latest_feat = feat[feat["date"] == pd.Timestamp(meta["as_of_date"])].set_index("ticker")
        for c in CONTEXT_COLS:
            df[c] = df["ticker"].map(latest_feat[c]) if c in latest_feat.columns else np.nan
        return df.sort_values("buy_proba", ascending=False).reset_index(drop=True), meta


def query_tickers(tickers: list[str]) -> dict:
    """The dashboard's 'query a specific ticker' feature. Uses the cached
    models (fast) and returns both models' probability/rank/percentile and
    a BUY / NO BUY / N/A verdict per ticker, mirroring recommend.py's
    top-quartile verdict rule -- without needing to retrain anything."""
    feat = get_features()
    if feat is None:
        return {"error": "features.parquet not found -- run a data refresh first."}

    tickers = [t.strip().upper() for t in tickers if t.strip()]
    xgb_df, xgb_meta = score_universe_cached("xgb", feat)
    lstm_df, lstm_meta = score_universe_cached("lstm", feat)

    rows = []
    for t in tickers:
        row = {"ticker": t}
        if xgb_df is not None:
            m = xgb_df[xgb_df["ticker"] == t]
            if not m.empty:
                r = m.iloc[0]
                row["xgb_buy_proba"] = round(float(r["buy_proba"]), 4)
                row["xgb_rank"] = f"{int(r['rank'])}/{len(xgb_df)}"
                row["xgb_percentile"] = round(float(r["percentile"]), 4)
                row["xgb_verdict"] = "BUY" if r["percentile"] <= BUY_PERCENTILE_THRESHOLD else "NO BUY"
                for c in CONTEXT_COLS:
                    row[c] = r.get(c)
            else:
                row["xgb_verdict"] = "N/A (no data)"
        if lstm_df is not None:
            m = lstm_df[lstm_df["ticker"] == t]
            if not m.empty:
                r = m.iloc[0]
                row["lstm_buy_proba"] = round(float(r["buy_proba"]), 4)
                row["lstm_rank"] = f"{int(r['rank'])}/{len(lstm_df)}"
                row["lstm_percentile"] = round(float(r["percentile"]), 4)
                row["lstm_verdict"] = "BUY" if r["percentile"] <= BUY_PERCENTILE_THRESHOLD else "NO BUY"
            else:
                row["lstm_verdict"] = "N/A (no data)"
        xv, lv = row.get("xgb_verdict", "N/A"), row.get("lstm_verdict", "N/A")
        if "N/A" in xv or "N/A" in lv:
            row["combined_verdict"] = "N/A"
        elif xv == "BUY" and lv == "BUY":
            row["combined_verdict"] = "BUY -- both models agree"
        elif xv == "NO BUY" and lv == "NO BUY":
            row["combined_verdict"] = "PASS -- both models agree"
        else:
            row["combined_verdict"] = "MIXED -- models disagree"
        rows.append(row)

    return {
        "as_of_xgb": xgb_meta["as_of_date"] if xgb_meta else None,
        "as_of_lstm": lstm_meta["as_of_date"] if lstm_meta else None,
        "rows": rows,
    }


def ticker_history(ticker: str, feat: pd.DataFrame | None = None) -> pd.DataFrame | None:
    """Raw price/feature history for one ticker, for a quick price chart on
    the query page."""
    if feat is None:
        feat = get_features()
    if feat is None:
        return None
    df = feat[feat["ticker"] == ticker.strip().upper()].sort_values("date")
    return df if not df.empty else None


# --------------------------------------------------------------------------
# Retraining / refresh (slow path -- subprocess, see lib/data_refresh.py for
# the generic background-process machinery this builds on)
# --------------------------------------------------------------------------

def retrain_commands() -> list[list[str]]:
    """The exact commands a full stock-model refresh runs, in order. Exposed
    as a function (not inlined in data_refresh.py) so this module stays the
    single place that knows how the stock pipeline is invoked."""
    py = sys.executable
    return [
        [py, str(paths.SRC_DIR / "features.py")],
        [py, str(paths.SRC_DIR / "current_signal.py")],
        [py, str(paths.SRC_DIR / "lstm_current_signal.py")],
    ]
