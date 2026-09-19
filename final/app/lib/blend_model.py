"""
Loader for the composite+q75 blend -- PRIMARY signal as of 2026-09-19,
promoted per Gabe's explicit instruction over the caveats recorded in
current_signal_blend.py's docstring and final/models/2026-09-19-
factor-composite-reset.md. Read those before presenting this signal's
numbers as more settled than they are.
"""
import json
import sys

import pandas as pd

from . import paths

SIGNAL_CSV = paths.OUT_DIR / "current_signal_blend.csv"
SIGNAL_META = paths.OUT_DIR / "current_signal_blend_meta.json"


def _mtime(p):
    try:
        return p.stat().st_mtime
    except FileNotFoundError:
        return -1.0


def get_signal():
    """Returns (picks_df, meta_dict) or (None, None) if not yet generated."""
    if not SIGNAL_CSV.exists() or not SIGNAL_META.exists():
        return None, None
    df = pd.read_csv(SIGNAL_CSV)
    meta = json.loads(SIGNAL_META.read_text())
    return df, meta


def signal_status():
    return {"exists": SIGNAL_CSV.exists() and SIGNAL_META.exists(), "mtime": _mtime(SIGNAL_META)}


def retrain_commands() -> list[list[str]]:
    """Rebuild the composite's down-cap universe + factor panel, then rescore
    today's blend. Does NOT retrain q75's own XGBoost model or refresh the
    base Sharadar/fundamentals panels -- run the primary "Retrain" pipeline
    (pit_model.retrain_commands()) first if those are stale; this only
    refreshes what's specific to the blend."""
    py = sys.executable
    reset_src = paths.SRC_DIR / "reset2026"
    return [
        [py, str(reset_src / "downcap_universe.py")],
        [py, str(reset_src / "quality_factors.py")],
        [py, str(reset_src / "build_panel.py")],
        [py, str(paths.SRC_DIR / "current_signal_blend.py")],
    ]


def query_tickers(tickers: list[str]) -> dict:
    """Per-ticker lookup against the full scored universe this run produced.
    NOTE: current_signal_blend.py only writes the ~165 actual picks to disk,
    not the full 1,665-name scored universe -- so a ticker not in the picks
    reads as 'not currently a pick', not 'the model doesn't like it', since
    we don't have its score persisted. See the caveat in the app tab."""
    df, meta = get_signal()
    out = {}
    if df is None:
        for t in tickers:
            out[t] = {"status": "NO SIGNAL", "detail": "Blend has not been generated yet."}
        return out
    picked = set(df["ticker"])
    by_ticker = df.set_index("ticker").to_dict("index")
    for t in tickers:
        t = t.upper().strip()
        if t in picked:
            row = by_ticker[t]
            out[t] = {"status": "PICK", "weight_pct": round(row["weight"] * 100, 2),
                      "blend_score": round(row["blend_score"], 4),
                      "composite_score": round(row["composite_score"], 4),
                      "q75_score": round(row["q75_score"], 4),
                      "sector": row["sector"]}
        else:
            out[t] = {"status": "NOT A CURRENT PICK",
                      "detail": "Either not in the day's ~1,665-name cap2000 eligible "
                                "universe, or eligible but outside the top decile-per-"
                                "vol-quintile the blend selected. Full-universe scores "
                                "for every eligible name are not yet persisted -- only "
                                "the picks themselves."}
    return out
