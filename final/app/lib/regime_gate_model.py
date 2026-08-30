"""
Dashboard-facing wrapper around the regime-gated stock signal in
final/src/current_signal_gated.py -- the HMM-gated blend of the baseline
(price-only) and augmented (price + fundamentals, no_staleness) models,
promoted out of beta into live use per Gabe's explicit request (see
models/fundamentals-beta-results.md, "Deployment" section).

Same design principle as lib/stock_model.py: this module doesn't
reimplement the gating or modeling logic. It reads whatever
current_signal_gated.py last wrote to out/, and can trigger a fresh run
of that script (plus the two upstream feature-build steps it depends on)
as a background job, using the same run_step_sequence machinery as every
other retrain button in this app.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

from . import paths
from . import stock_model as sm

paths.ensure_src_on_path()

GATED_CSV = paths.OUT_DIR / "current_signal_gated.csv"
GATED_META = paths.OUT_DIR / "current_signal_gated_meta.json"
FUND_PARQUET = paths.OUT_DIR / "features_with_fundamentals_beta.parquet"

BUY_PERCENTILE_THRESHOLD = sm.BUY_PERCENTILE_THRESHOLD  # top quartile -> BUY, same convention everywhere
CONTEXT_COLS = sm.CONTEXT_COLS  # same context columns as the secondary models' query tab, for consistency


def _mtime(p: Path) -> float:
    try:
        return p.stat().st_mtime
    except FileNotFoundError:
        return -1.0


def get_gated_signal() -> tuple[pd.DataFrame | None, dict | None]:
    """Reads the already-computed allocation + its metadata sidecar --
    no computation happens here, mirrors stock_model.get_current_top.

    current_signal_gated.py now writes both files atomically (temp file +
    os.replace), so a concurrent read during a retrain should always see a
    complete file. This still wraps the read in a try/except as a second
    line of defense -- a truncated/unreadable file (an interrupted retrain,
    a leftover pre-atomic-write file, anything unanticipated) degrades to
    "not available yet" instead of crashing the whole Streamlit page."""
    df = None
    if GATED_CSV.exists():
        try:
            df = pd.read_csv(GATED_CSV)
        except Exception:
            df = None
    meta = None
    if GATED_META.exists():
        try:
            meta = json.loads(GATED_META.read_text())
        except Exception:
            meta = None
    return df, meta


def fundamentals_panel_exists() -> bool:
    return FUND_PARQUET.exists()


def gated_status() -> dict:
    """Freshness check: is the saved allocation as-of the latest date the
    fundamentals-augmented panel actually has data for?

    fundamentals_features_beta.py now writes its parquet atomically too, but
    this read is still guarded: it's the single biggest file in the
    pipeline (the full price+fundamentals panel) and the one that actually
    triggered the "Parquet magic bytes not found in footer" crash the first
    time this raced a live retrain."""
    _, meta = get_gated_signal()
    if meta is None:
        return {"exists": False, "as_of_date": None, "stale": True, "latest_data_date": None}
    latest = None
    if FUND_PARQUET.exists():
        try:
            from features import latest_complete_date
            feat = pd.read_parquet(FUND_PARQUET, columns=["date", "ticker"])
            latest = str(latest_complete_date(feat).date())
        except Exception:
            latest = None  # mid-write or otherwise unreadable right now -- skip the staleness check this rerun
    as_of = meta.get("as_of_date")
    return {
        "exists": True, "as_of_date": as_of,
        "stale": latest is not None and as_of != latest,
        "latest_data_date": latest,
    }


# --------------------------------------------------------------------------
# Per-ticker query against the saved baseline/augmented checkpoints (fast
# path -- no retraining), mirroring stock_model.py's query_tickers() pattern
# but for the two models the HMM gate actually blends.
# --------------------------------------------------------------------------

@st.cache_data(show_spinner=False)
def _load_fundamentals_features(_mtime_key: float) -> pd.DataFrame:
    feat = pd.read_parquet(FUND_PARQUET)
    return feat.sort_values(["ticker", "date"]).reset_index(drop=True)


def get_fundamentals_features() -> pd.DataFrame | None:
    """The price+fundamentals panel current_signal_gated.py trains both
    models against. Needed for query scoring since the augmented model's
    feature columns (fundamentals) aren't in the plain features.parquet."""
    if not FUND_PARQUET.exists():
        return None
    return _load_fundamentals_features(_mtime(FUND_PARQUET))


def _augmented_feature_cols() -> list[str]:
    """Exactly matches AUGMENTED_FEATURE_COLS in final/src/current_signal_gated.py
    (FEATURE_COLS + fundamentals columns minus the staleness-age column) --
    duplicated here rather than imported because current_signal_gated.py is a
    script entry point (importing it would also require its module-level
    heavy imports); if that script's feature-column logic ever changes, this
    needs to change with it."""
    from features import FEATURE_COLS
    from fundamentals_features_beta import FUNDAMENTAL_FEATURE_COLS
    no_stale = [c for c in FUNDAMENTAL_FEATURE_COLS if c != "fundamentals_age_days"]
    return FEATURE_COLS + no_stale


@st.cache_resource(show_spinner=False)
def _load_cached_gated_model(kind: str, _mtime_key: float):
    from xgboost import XGBClassifier
    model = XGBClassifier()
    model.load_model(str(paths.STOCK_MODELS_DIR / f"xgb_gated_{kind}_model.json"))
    return model


def score_universe_cached(kind: str, gfeat: pd.DataFrame) -> tuple[pd.DataFrame | None, dict | None]:
    """kind: 'baseline' (price-only) or 'augmented' (price + fundamentals,
    no_staleness). Scores the FULL universe on the saved
    xgb_gated_{kind}_model.json checkpoint at the as-of date recorded in
    current_signal_gated_meta.json, so any ticker's rank/percentile can be
    looked up instantly. `gfeat` is features_with_fundamentals_beta.parquet
    (already loaded by the caller so it's only read once per session)."""
    model_path = paths.STOCK_MODELS_DIR / f"xgb_gated_{kind}_model.json"
    if not model_path.exists():
        return None, None
    _, meta = get_gated_signal()
    if meta is None:
        return None, None
    from features import FEATURE_COLS
    feature_cols = FEATURE_COLS if kind == "baseline" else _augmented_feature_cols()

    model = _load_cached_gated_model(kind, _mtime(model_path))
    as_of = pd.Timestamp(meta["as_of_date"])
    # current_signal_gated.py scores today_rows = feat[date==as_of].dropna(
    # subset=FEATURE_COLS) for BOTH models -- not dropna on the full
    # augmented list, since XGBoost handles missing fundamentals natively.
    # Match that exactly so ranks here agree with what it actually picked.
    rows = gfeat[gfeat["date"] == as_of].dropna(subset=FEATURE_COLS).copy()
    if rows.empty:
        return None, meta
    rows["buy_proba"] = model.predict_proba(rows[feature_cols])[:, 1]
    rows["rank"] = rows["buy_proba"].rank(ascending=False, method="min").astype(int)
    rows["percentile"] = rows["rank"] / len(rows)
    cols = ["ticker", "buy_proba", "rank", "percentile"] + CONTEXT_COLS
    return rows[cols].sort_values("buy_proba", ascending=False).reset_index(drop=True), meta


def query_tickers(tickers: list[str]) -> dict:
    """The regime-gate's 'query a specific ticker' feature: scores each
    ticker against BOTH the baseline (price-only) and augmented (price +
    fundamentals, no_staleness) models using their saved checkpoints (fast,
    no retraining) and reports whether they agree -- the same top-quartile
    BUY/NO BUY verdict rule as stock_model.query_tickers() and recommend.py.
    This is the HMM gate's OWN two inputs, so "do the models agree" here is
    literally what determines whether the gate's blended allocation (Today's
    Picks tab) leans on overlapping or conflicting picks today."""
    gfeat = get_fundamentals_features()
    if gfeat is None:
        return {"error": "features_with_fundamentals_beta.parquet not found -- "
                          "run a regime-gated retrain first (Today's Picks tab)."}

    tickers = [t.strip().upper() for t in tickers if t.strip()]
    base_df, base_meta = score_universe_cached("baseline", gfeat)
    aug_df, aug_meta = score_universe_cached("augmented", gfeat)

    rows = []
    for t in tickers:
        row = {"ticker": t}
        if base_df is not None:
            m = base_df[base_df["ticker"] == t]
            if not m.empty:
                r = m.iloc[0]
                row["baseline_verdict"] = "BUY" if r["percentile"] <= BUY_PERCENTILE_THRESHOLD else "NO BUY"
                row["baseline_rank"] = f"{int(r['rank'])}/{len(base_df)}"
                row["baseline_buy_proba"] = round(float(r["buy_proba"]), 4)
                row["baseline_percentile"] = round(float(r["percentile"]), 4)
                for c in CONTEXT_COLS:
                    row[c] = r.get(c)
            else:
                row["baseline_verdict"] = "N/A (no data)"
        else:
            row["baseline_verdict"] = "N/A (no saved model)"
        if aug_df is not None:
            m = aug_df[aug_df["ticker"] == t]
            if not m.empty:
                r = m.iloc[0]
                row["augmented_verdict"] = "BUY" if r["percentile"] <= BUY_PERCENTILE_THRESHOLD else "NO BUY"
                row["augmented_rank"] = f"{int(r['rank'])}/{len(aug_df)}"
                row["augmented_buy_proba"] = round(float(r["buy_proba"]), 4)
                row["augmented_percentile"] = round(float(r["percentile"]), 4)
            else:
                row["augmented_verdict"] = "N/A (no data)"
        else:
            row["augmented_verdict"] = "N/A (no saved model)"

        bv, av = row.get("baseline_verdict", "N/A"), row.get("augmented_verdict", "N/A")
        if "N/A" in bv or "N/A" in av:
            row["agreement"] = "N/A"
        elif bv == "BUY" and av == "BUY":
            row["agreement"] = "AGREE -- both BUY"
        elif bv == "NO BUY" and av == "NO BUY":
            row["agreement"] = "AGREE -- both NO BUY"
        else:
            row["agreement"] = "DISAGREE"
        rows.append(row)

    return {
        "as_of_baseline": base_meta["as_of_date"] if base_meta else None,
        "as_of_augmented": aug_meta["as_of_date"] if aug_meta else None,
        "hmm_weight_on_augmented": base_meta.get("hmm_weight_on_augmented") if base_meta else None,
        "rows": rows,
    }


# --------------------------------------------------------------------------
# Model weights + backtest for the regime-gated blend's two underlying
# models (mirrors stock_model.py's get_feature_importances() /
# get_backtest_tables() pattern, for xgb_gated_baseline/augmented instead).
# --------------------------------------------------------------------------

def get_gated_feature_importances() -> dict | None:
    """Feature importances straight off the saved xgb_gated_baseline_model.json
    / xgb_gated_augmented_model.json checkpoints (same gain-based
    feature_importances_ property stock_model.py's plain XGBoost uses).
    Note the HMM gate ITSELF has no feature weights in this sense -- it's a
    2-state Gaussian regime classifier fit only on SPY's own daily returns,
    not on any of these buy/no-buy features; it only picks the blend weight
    between these two models, whose importances actually drive the picks.
    Returns None if the models haven't been trained yet."""
    base_path = paths.STOCK_MODELS_DIR / "xgb_gated_baseline_model.json"
    aug_path = paths.STOCK_MODELS_DIR / "xgb_gated_augmented_model.json"
    if not base_path.exists() or not aug_path.exists():
        return None
    from features import FEATURE_COLS
    aug_cols = _augmented_feature_cols()

    base_model = _load_cached_gated_model("baseline", _mtime(base_path))
    aug_model = _load_cached_gated_model("augmented", _mtime(aug_path))

    base_imp = (pd.DataFrame({"feature": FEATURE_COLS, "importance": base_model.feature_importances_})
                .sort_values("importance", ascending=False).reset_index(drop=True))
    aug_imp = (pd.DataFrame({"feature": aug_cols, "importance": aug_model.feature_importances_})
               .sort_values("importance", ascending=False).reset_index(drop=True))

    fundamentals_cols = set(aug_cols) - set(FEATURE_COLS)
    aug_imp["is_fundamentals_feature"] = aug_imp["feature"].isin(fundamentals_cols)
    fundamentals_share = float(aug_imp.loc[aug_imp["is_fundamentals_feature"], "importance"].sum())

    return {"baseline": base_imp, "augmented": aug_imp, "fundamentals_share_of_augmented": fundamentals_share}


def get_backtest_tables() -> dict:
    """Backtest artifacts for the regime-gated blend and its two underlying
    models -- two different studies, both documented in this project's own
    docs:
      - fundamentals_beta: an 8-timepoint walk-forward (2013-2026) scoring
        baseline vs. augmented independently (models/fundamentals-beta-
        results.md) -- this is what justified promoting the augmented
        model out of beta.
      - ytd_sequential: the actual regime-gated BLEND (not the two models
        separately), walked forward sequentially through 2026 (backtest/
        2026-ytd-hmm-gated-sequential-results.md) -- the closest thing to
        a real track record of what the Today's Picks tab has been doing.
    Any file not present yet is simply omitted rather than raising."""
    result = {}
    p = paths.OUT_DIR / "backtest_fundamentals_beta.json"
    if p.exists():
        result["fundamentals_beta"] = json.loads(p.read_text())
    p = paths.OUT_DIR / "backtest_2026_hmm_gated.json"
    if p.exists():
        result["ytd_sequential"] = json.loads(p.read_text())
    p = paths.OUT_DIR / "horizon_sweep_fundamentals_beta_summary.json"
    if p.exists():
        result["horizon_sweep"] = json.loads(p.read_text())
    chart = paths.OUT_DIR / "fundamentals_beta_horizon_chart.png"
    result["chart_path"] = chart if chart.exists() else None
    return result


def retrain_commands() -> list[list[str]]:
    """The exact commands a regime-gated refresh runs, in order: rebuild
    the base price panel, merge fundamentals onto it, then train both
    models fresh and recompute today's HMM gate weight. Mirrors
    stock_model.retrain_commands()'s pattern for the price-only pipeline."""
    py = sys.executable
    return [
        [py, str(paths.SRC_DIR / "features.py")],
        [py, str(paths.SRC_DIR / "fundamentals_features_beta.py")],
        [py, str(paths.SRC_DIR / "current_signal_gated.py")],
    ]
