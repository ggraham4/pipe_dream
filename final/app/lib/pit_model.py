"""
Dashboard-facing wrapper around the live buy signals in
final/src/current_signal_pit.py.

ROUND 18 (2026-09-16). This module now serves TWO signals, at Gabe's request,
so the app can show a pick alongside a second opinion:

    q75    PRIMARY    the deployed configuration
    xrank  CANDIDATE  tracked and displayed, explicitly NOT acted on

The candidate exists on the page because Round 17b found that switching the
training target to a within-date percentile rank flipped every feature family's
model-level IC positive -- and Round 18 then put it on the 2020-2026 hold-out,
where it returned -4.28%/yr excess (0.771x SPY) against the deployed model's
+7.33%/yr (1.526x). It is shown so its disagreements with the deployed model
are visible in real time, not as an alternative to follow. Anything in this
module that renders the candidate must carry that number with it.

Design principle, unchanged from lib/stock_model.py: this module does not
reimplement any modelling logic. It reads whatever current_signal_pit.py and
build_app_benchmarks.py last wrote to out/, and can trigger a fresh run of
those scripts as a background job through the same run_step_sequence machinery
every other retrain button in this app uses.

REMOVED in this rewrite: get_backtest_tables()'s stop-loss sweep artifacts.
The deployed configuration holds to the 40-day horizon with NO stop-loss, so
a page built around optimizing the stop level was describing a model the app
does not run. The 15% level is still reported per name as risk guidance and is
labelled as guidance everywhere it appears.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

from . import paths

paths.ensure_src_on_path()

# --------------------------------------------------------------------------
# The two signals.
#
# Mirrors VARIANTS in final/src/current_signal_pit.py, duplicated here for the
# same reason _augmented_feature_cols() duplicates its feature list: that file
# is a script entry point that imports xgboost and the full walk-forward module
# at import time, and the dashboard must not pay for that on every rerun. The
# per-signal meta JSON is authoritative at render time -- everything below is
# only what the app shows BEFORE a first run has produced one.
# --------------------------------------------------------------------------
VARIANTS = [
    {
        "key": "q75",
        "role": "primary",
        "display_name": "Deployed (q75 / classifier)",
        "short_name": "Deployed",
        "cell_id": "price_fund_h40_q75_trd_xgb_d3e01r100_expanding_cap500k_pit_s40",
        "signal_csv": "current_signal_pit.csv",
        "signal_meta": "current_signal_pit_meta.json",
        "model_file": "xgb_pit_augmented_model.json",
        "model_kind": "classifier",
        "score_label": "buy_proba",
    },
    {
        "key": "xrank",
        "role": "candidate",
        "display_name": "Candidate (xrank / regressor)",
        "short_name": "Candidate",
        "cell_id": "price_fund_h40_xrank_trd_xgb_reg_d3e01r100_expanding_cap500k_pit_s40",
        "signal_csv": "current_signal_pit_xrank.csv",
        "signal_meta": "current_signal_pit_xrank_meta.json",
        "model_file": "xgb_pit_xrank_model.json",
        "model_kind": "regressor",
        "score_label": "predicted rank",
    },
]

PRIMARY = "q75"
CANDIDATE = "xrank"


def variant(key: str) -> dict:
    for v in VARIANTS:
        if v["key"] == key:
            return v
    raise KeyError(key)


def variant_keys() -> list[str]:
    return [v["key"] for v in VARIANTS]


# --------------------------------------------------------------------------
# paths
# --------------------------------------------------------------------------
FUND_PIT_PARQUET = paths.OUT_DIR / "features_with_fundamentals_sharadar_pit.parquet"
COMPARISON_JSON = paths.OUT_DIR / "app_model_comparison.json"
AGREEMENT_JSON = paths.OUT_DIR / "current_signal_compare.json"

BUY_PERCENTILE_THRESHOLD = 0.25   # top quartile -> BUY, the convention used everywhere in this app

CONTEXT_COLS = [
    "close", "momentum_20", "momentum_60", "momentum_120",
    "relative_strength_20", "pct_from_high_252", "pct_from_low_252", "volatility_20",
    "market_cap",
]


def signal_csv(key: str) -> Path:
    return paths.OUT_DIR / variant(key)["signal_csv"]


def signal_meta_path(key: str) -> Path:
    return paths.OUT_DIR / variant(key)["signal_meta"]


def model_path(key: str) -> Path:
    return paths.STOCK_MODELS_DIR / variant(key)["model_file"]


def _mtime(p: Path) -> float:
    try:
        return p.stat().st_mtime
    except FileNotFoundError:
        return -1.0


# --------------------------------------------------------------------------
# saved picks
# --------------------------------------------------------------------------
def get_signal(key: str = PRIMARY) -> tuple[pd.DataFrame | None, dict | None]:
    """The already-computed picks + metadata sidecar for one variant. No
    computation happens here. current_signal_pit.py writes both files
    atomically (temp file + os.replace), but the reads are still wrapped as a
    second line of defense against a concurrent-read race while a background
    retrain is mid-write."""
    df = None
    p = signal_csv(key)
    if p.exists():
        try:
            df = pd.read_csv(p)
        except Exception:
            df = None
    meta = None
    m = signal_meta_path(key)
    if m.exists():
        try:
            meta = json.loads(m.read_text())
        except Exception:
            meta = None
    return df, meta


def get_all_signals() -> dict:
    return {v["key"]: get_signal(v["key"]) for v in VARIANTS}


def get_agreement() -> dict | None:
    """current_signal_compare.json -- which names the two models share today.

    Read the `caveat` field before showing overlap as reassurance. The two
    share features, hyperparameters and construction and differ only in the
    training target, so their errors are correlated by design; agreement is
    close to a foregone conclusion and is not independent confirmation."""
    if not AGREEMENT_JSON.exists():
        return None
    try:
        return json.loads(AGREEMENT_JSON.read_text())
    except Exception:
        return None


def fundamentals_pit_panel_exists() -> bool:
    return FUND_PIT_PARQUET.exists()


# --------------------------------------------------------------------------
# freshness
# --------------------------------------------------------------------------
@st.cache_data(show_spinner=False)
def _pit_universe_counts(_mtime_key: float) -> dict:
    """Distinct tickers in the PIT panel, split into current-universe and
    point-in-time gap tickers. A cheap single-column read, cached on the
    panel's mtime. The Overview card used to show the OLD non-PIT
    features.parquet count, which did not match the universe the primary model
    can actually see."""
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


def _latest_data_date() -> str | None:
    if not FUND_PIT_PARQUET.exists():
        return None
    try:
        # NOT features.latest_complete_date() -- that needs 90% of ALL tickers
        # in the panel to have a row on a date, and this panel carries
        # thousands of permanently-delisted names that never will. Same fix as
        # current_signal_pit.latest_complete_date_pit().
        from current_signal_pit import latest_complete_date_pit
        from continuous_walkforward_pit import load_gap_ticker_set
        feat = pd.read_parquet(FUND_PIT_PARQUET, columns=["date", "ticker"])
        gap_tickers = load_gap_ticker_set()
        return str(latest_complete_date_pit(feat, gap_tickers).date())
    except Exception:
        # mid-write, or otherwise unreadable this rerun -- skip the check
        return None


def signal_status(key: str = PRIMARY) -> dict:
    """Is this variant's saved signal as-of the latest date the panel has."""
    _, meta = get_signal(key)
    if meta is None:
        return {"exists": False, "as_of_date": None, "stale": True,
                "latest_data_date": None}
    latest = _latest_data_date()
    as_of = meta.get("as_of_date")
    return {"exists": True, "as_of_date": as_of,
            "stale": latest is not None and as_of != latest,
            "latest_data_date": latest}


def all_signal_status() -> dict:
    return {v["key"]: signal_status(v["key"]) for v in VARIANTS}


# --------------------------------------------------------------------------
# per-ticker query against the saved checkpoints (fast path -- no retraining)
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
    """Exactly AUGMENTED_FEATURE_COLS in final/src/current_signal_pit.py --
    duplicated rather than imported because that script is an entry point, not
    a lightweight import. Verified identical to the backtested cell's
    feature_cols (24 columns, same order)."""
    from features import FEATURE_COLS
    from fundamentals_features_beta import FUNDAMENTAL_FEATURE_COLS
    no_stale = [c for c in FUNDAMENTAL_FEATURE_COLS if c != "fundamentals_age_days"]
    return FEATURE_COLS + no_stale


@st.cache_resource(show_spinner=False)
def _load_cached_model(key: str, _mtime_key: float):
    """Returns None rather than raising if the checkpoint will not load.

    A checkpoint can be present but unreadable -- half-written by a retrain
    that is still running, or saved by a different xgboost major version. The
    caller checking .exists() is not enough, and before Round 18 a bad file
    here took the whole page down with a traceback instead of one tab with a
    message. Streamlit caches the None too, so a failed load is retried when
    the file's mtime changes, i.e. when the retrain finishes."""
    from xgboost import XGBClassifier, XGBRegressor
    v = variant(key)
    model = XGBClassifier() if v["model_kind"] == "classifier" else XGBRegressor()
    try:
        model.load_model(str(model_path(key)))
    except Exception:
        return None
    return model


def _eligible_mask(rows: pd.DataFrame, as_of: pd.Timestamp) -> pd.Series:
    """Today's eligibility, taken from the SAME screen current_signal_pit.py
    applies -- membership in that date's point-in-time universe.

    Before Round 18 this function re-derived eligibility from the panel's own
    market_cap (= close x sharesbas) and split-adjusted close. Those are not
    the quantities pit_universe.parquet was built from (daily.marketcap and
    closeunadj), so the query tab could call a name ineligible that the picks
    tab had just bought. The mid-cap+ floor below is only the fallback for the
    pre-Round-11 `expanded` universe path, where no PIT universe file exists."""
    try:
        from continuous_walkforward_pit import load_pit_universe
        day = load_pit_universe().get(str(pd.Timestamp(as_of).date()))
        if day:
            return rows["ticker"].isin(day)
    except Exception:
        pass
    from continuous_walkforward_pit import MIN_MARKET_CAP, MIN_PRICE
    return (rows["close"] > MIN_PRICE) & (rows["market_cap"] >= MIN_MARKET_CAP)


def _score_universe(key: str, gfeat: pd.DataFrame) -> tuple[pd.DataFrame | None, dict | None]:
    """Scores the eligible universe on one variant's saved checkpoint at the
    as-of date in its meta sidecar, so any ticker's rank can be looked up
    instantly.

    Ineligible tickers are NOT dropped -- they are scored and flagged via
    `eligible_today`, so the query can tell "the model doesn't like it" apart
    from "it isn't pickable today".

    Note the deliberate absence of a dropna on FEATURE_COLS. Round 18 aligned
    the live candidate pool to the backtest, which scores every name in the
    day's point-in-time universe and lets XGBoost handle missing features
    natively. Reintroducing a dropna here would make this query disagree with
    the picks on the Today's Picks tab."""
    if not model_path(key).exists():
        return None, None
    _, meta = get_signal(key)
    if meta is None:
        return None, None
    feature_cols = _augmented_feature_cols()

    model = _load_cached_model(key, _mtime(model_path(key)))
    if model is None:
        return None, meta
    as_of = pd.Timestamp(meta["as_of_date"])
    rows = gfeat[gfeat["date"] == as_of].copy()
    if rows.empty:
        return None, meta

    X = rows[feature_cols]
    v = variant(key)
    rows["score"] = (model.predict_proba(X)[:, 1] if v["model_kind"] == "classifier"
                     else model.predict(X))
    rows["eligible_today"] = _eligible_mask(rows, as_of)

    elig = rows[rows["eligible_today"]].copy()
    elig["rank"] = elig["score"].rank(ascending=False, method="min").astype(int)
    elig["percentile"] = elig["rank"] / len(elig) if len(elig) else None
    rows = rows.merge(elig[["ticker", "rank", "percentile"]], on="ticker", how="left")

    cols = ["ticker", "score", "rank", "percentile", "eligible_today"] + CONTEXT_COLS
    return rows[cols].sort_values("score", ascending=False).reset_index(drop=True), meta


def query_tickers(tickers: list[str]) -> dict:
    """BUY / NO BUY / INELIGIBLE / N/A per ticker, from BOTH models.

    INELIGIBLE means the model may like it but it fails the point-in-time
    mid-cap+ floor today (market cap < $2B or price < $10), so it is not a live
    pick regardless -- distinct from a plain NO BUY.

    The candidate's verdict is returned in its own columns and must be rendered
    as a second opinion, never blended with the primary's. It lost to SPY on
    the hold-out; averaging it into the deployed signal would be acting on a
    result that has already failed once."""
    gfeat = get_fundamentals_pit_features()
    if gfeat is None:
        return {"error": "features_with_fundamentals_sharadar_pit.parquet not found -- "
                          "run a retrain first (Today's Picks tab)."}

    tickers = [t.strip().upper() for t in tickers if t.strip()]
    scored = {v["key"]: _score_universe(v["key"], gfeat) for v in VARIANTS}

    rows = []
    for t in tickers:
        row = {"ticker": t}
        ctx_done = False
        for v in VARIANTS:
            k = v["key"]
            df, _ = scored[k]
            pre = "" if k == PRIMARY else "candidate_"
            if df is None:
                row[f"{pre}verdict"] = "N/A (no saved model)"
                continue
            m = df[df["ticker"] == t]
            if m.empty:
                row[f"{pre}verdict"] = "N/A (no data)"
                continue
            r = m.iloc[0]
            if not bool(r["eligible_today"]):
                row[f"{pre}verdict"] = "INELIGIBLE (below mid-cap+ floor today)"
            elif r["percentile"] is not None and pd.notna(r["percentile"]) \
                    and r["percentile"] <= BUY_PERCENTILE_THRESHOLD:
                row[f"{pre}verdict"] = "BUY"
            else:
                row[f"{pre}verdict"] = "NO BUY"
            row[f"{pre}score"] = round(float(r["score"]), 4)
            if pd.notna(r["rank"]):
                n_elig = int(df["eligible_today"].sum())
                row[f"{pre}rank"] = f"{int(r['rank'])}/{n_elig}"
            if not ctx_done:
                for c in CONTEXT_COLS:
                    row[c] = r.get(c)
                ctx_done = True
        rows.append(row)

    metas = {k: (scored[k][1] or {}) for k in scored}
    return {
        "as_of_date": metas.get(PRIMARY, {}).get("as_of_date"),
        "candidate_as_of_date": metas.get(CANDIDATE, {}).get("as_of_date"),
        "stop_loss_pct": metas.get(PRIMARY, {}).get("stop_loss_pct"),
        "rows": rows,
    }


# --------------------------------------------------------------------------
# model weights
# --------------------------------------------------------------------------
def get_feature_importances(key: str = PRIMARY) -> dict | None:
    """Gain-based feature importances straight off one variant's saved
    checkpoint. Returns None if that model has not been trained yet.

    Worth keeping in view while reading the chart: Round 13 showed that every
    fundamental feature that looked significant is a sector bet, and Round 17
    showed that the ranking these importances describe does not survive the
    pipeline -- a raw feature with t = +3.40 came out of the model at t =
    -0.65. A high importance means the tree split on it often, not that it
    carries forward-predictive information."""
    if not model_path(key).exists():
        return None
    aug_cols = _augmented_feature_cols()
    model = _load_cached_model(key, _mtime(model_path(key)))
    if model is None:
        return None
    imp = (pd.DataFrame({"feature": aug_cols, "importance": model.feature_importances_})
           .sort_values("importance", ascending=False).reset_index(drop=True))
    from features import FEATURE_COLS
    fundamentals_cols = set(aug_cols) - set(FEATURE_COLS)
    imp["is_fundamentals_feature"] = imp["feature"].isin(fundamentals_cols)
    share = float(imp.loc[imp["is_fundamentals_feature"], "importance"].sum())
    return {"importances": imp, "fundamentals_share": share}


# --------------------------------------------------------------------------
# backtest + benchmarks
# --------------------------------------------------------------------------
def get_comparison() -> dict | None:
    """out/app_model_comparison.json -- window-by-window equity curves and
    summary statistics for both models against SPY and USMV, over both the
    2007-2019 selection era and the 2020-2026 hold-out.

    Built by final/src/build_app_benchmarks.py. Returns None if that has not
    been run yet. The `noise_scale` block, when present, is the most important
    thing on the page: it is the spread of ten same-idea variants of the
    deployed cell (-8.01 to +9.15 %/yr, sd 5.03), which is the yardstick any
    gap between two curves has to be read against."""
    if not COMPARISON_JSON.exists():
        return None
    try:
        return json.loads(COMPARISON_JSON.read_text())
    except Exception:
        return None


def comparison_frame(era: str = "holdout") -> pd.DataFrame | None:
    """One era's curves as a wide DataFrame indexed by window date, ready for
    st.line_chart. Series that do not span the whole era (USMV before its 2011
    inception) are left as NaN rather than back-filled."""
    comp = get_comparison()
    if comp is None or era not in comp.get("eras", {}):
        return None
    curves = comp["eras"][era]["curves"]
    labels = {}
    for k, v in comp.get("cells", {}).items():
        labels[k] = v["display_name"]
    for k, v in comp.get("benchmarks", {}).items():
        labels[k] = v["display_name"]
    frame = {labels.get(k, k): {row["timepoint"]: row["value"] for row in c}
             for k, c in curves.items() if c}
    if not frame:
        return None
    df = pd.DataFrame(frame)
    df.index = pd.to_datetime(df.index)
    return df.sort_index()


# --------------------------------------------------------------------------
# retrain
# --------------------------------------------------------------------------
PIT_STEP_LABELS = [
    "Top up the Sharadar price/marketcap panel (needs SHARADAR_API_KEY)",
    "Rebuild the point-in-time universe",
    "Rebuild price features",
    "Rebuild fundamental features",
    "Export per-ticker OHLCV for execution",
    "Retrain BOTH signals + compute today's picks",
    "Rebuild the benchmark comparison (SPY / USMV curves)",
]


def retrain_commands() -> list[list[str]]:
    """The exact commands a refresh runs, in order: top up the Sharadar panel,
    rebuild the point-in-time universe, rebuild price then fundamental
    features, export OHLCV for execution, retrain both signals and recompute
    today's picks, then rebuild the app's comparison chart.

    Flagged rather than glossed over: this does NOT refresh
    scripts/fundamentals_raw/ (current-universe SEC EDGAR) or
    scripts/fundamentals_raw_delisted/ (Sharadar gap-ticker data). Those are
    separate, much less frequent pulls -- see AGENTS.md.

    The last step needs network access the first time it runs, to pull USMV.
    If it cannot reach the network the run still succeeds; the comparison
    chart is simply drawn without the USMV line and says why."""
    py = sys.executable
    return [
        [py, str(paths.SRC_DIR / "sharadar_pull_pit_panel.py")],
        [py, str(paths.SRC_DIR / "build_pit_universe.py")],
        [py, str(paths.SRC_DIR / "build_features_sharadar.py")],
        [py, str(paths.SRC_DIR / "build_features_fundamentals_sharadar.py")],
        [py, str(paths.SRC_DIR / "export_sharadar_ohlc.py")],
        [py, str(paths.SRC_DIR / "current_signal_pit.py")],
        [py, str(paths.SRC_DIR / "build_app_benchmarks.py")],
    ]
