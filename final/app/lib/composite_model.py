"""
Loader for the "theoretical model" -- the factor-composite reset's live
picks -- a TRACKED CANDIDATE, deliberately kept separate from pit_model.py's
VARIANTS machinery rather than threaded into it, because that machinery
(model_path, feature importances, XGBoost scoring) is built around a trained
model and this composite has no trained parameters to load (it also has
nothing in common with blend_model.py's machinery, which scores a blend of
this composite WITH q75 -- this module shows the composite ALONE, for direct
comparison against that blend). See current_signal_composite.py and
final/models/2026-09-22-composite-model-full-specification.md for what this
is (the 2026-09-19 write-up covers the original, now-superseded 9-factor
equal-weight version).

Reading this file's output never touches, imports, or can break the
deployed q75/xrank signals in pit_model.py, or the blend, in either
direction -- that separation is deliberate.
"""
import json
import sys

import pandas as pd

from . import paths

SIGNAL_CSV = paths.OUT_DIR / "current_signal_composite.csv"
SIGNAL_META = paths.OUT_DIR / "current_signal_composite_meta.json"
EQUITY_CURVE_CSV = paths.OUT_DIR / "reset2026" / "backtest_equity_curve.csv"


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
    meta_mtime = _mtime(SIGNAL_META)
    return {
        "exists": SIGNAL_CSV.exists() and SIGNAL_META.exists(),
        "mtime": meta_mtime,
    }


def get_equity_curve():
    """Full-history (2007-2026, nomination+hold-out stitched) equity curve,
    IC-weighted composite vs SPY, net of 15bp turnover cost -- see
    build_backtest_equity_curve.py. Returns None if not yet generated.
    Plotting this is NOT a new hold-out spend (per Gabe, 2026-09-22): every
    number in it reproduces an already-reported cell."""
    if not EQUITY_CURVE_CSV.exists():
        return None
    df = pd.read_csv(EQUITY_CURVE_CSV, parse_dates=["date"])
    return df


def retrain_commands() -> list[list[str]]:
    """Rescore today's theoretical-model picks, and re-extend the backtest-
    history plot, off the composite panel that blend_model.retrain_commands()
    already rebuilds -- does NOT rebuild the panel itself (downcap_universe.py
    / quality_factors.py / build_panel.py), to avoid redoing that work when
    this runs alongside the blend refresh. If you ever call this WITHOUT also
    running blend_model.retrain_commands() (or an equivalent panel rebuild)
    first, the panel may be stale. The equity-curve rebuild (~10s) reruns the
    same already-reported backtest cells, just re-including whatever new
    trading days have rolled into the hold-out era -- not a new spend."""
    py = sys.executable
    reset_src = paths.SRC_DIR / "reset2026"
    return [
        [py, str(paths.SRC_DIR / "current_signal_composite.py")],
        [py, str(reset_src / "build_backtest_equity_curve.py")],
    ]
