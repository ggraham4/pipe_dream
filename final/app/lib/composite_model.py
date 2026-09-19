"""
Loader for the factor-composite reset's live picks -- a TRACKED CANDIDATE,
deliberately kept separate from pit_model.py's VARIANTS machinery rather than
threaded into it, because that machinery (model_path, feature importances,
XGBoost scoring) is built around a trained model and this composite has no
trained parameters to load. See current_signal_composite.py and
final/models/2026-09-19-factor-composite-reset.md for what this is.

Reading this file's output never touches, imports, or can break the
deployed q75/xrank signals in pit_model.py -- that separation is deliberate.
"""
import json

import pandas as pd

from . import paths

SIGNAL_CSV = paths.OUT_DIR / "current_signal_composite.csv"
SIGNAL_META = paths.OUT_DIR / "current_signal_composite_meta.json"


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
