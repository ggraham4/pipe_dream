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
SIGNAL_FULL_CSV = paths.OUT_DIR / "current_signal_blend_full.csv"


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


def get_full_universe():
    """Every name scanned on the as-of date, not just the picks -- see
    current_signal_blend.py's OUTPUT docstring for the `status` values.
    Returns None if not yet generated (older signal run, or first checkout
    before a re-run)."""
    if not SIGNAL_FULL_CSV.exists():
        return None
    return pd.read_csv(SIGNAL_FULL_CSV)


def query_tickers(tickers: list[str]) -> dict:
    """Per-ticker lookup against the full scanned universe (PICK /
    ELIGIBLE_NOT_PICKED / ELIGIBLE_NOT_SCORED / INELIGIBLE_TODAY), so 'not a
    pick' always comes with a reason, not a shrug."""
    full = get_full_universe()
    out = {}
    if full is None:
        # Fall back to the picks-only file so old runs don't crash outright,
        # but say plainly that the detailed answer isn't available yet.
        df, _ = get_signal()
        if df is None:
            for t in tickers:
                out[t] = {"status": "NO SIGNAL", "detail": "Blend has not been generated yet."}
            return out
        picked = set(df["ticker"])
        for t in tickers:
            t = t.upper().strip()
            out[t] = ({"status": "PICK"} if t in picked else
                      {"status": "UNKNOWN", "detail": "current_signal_blend_full.csv not found "
                                                       "(re-run the signal to get a real answer "
                                                       "for non-picks) -- only pick/not-pick is "
                                                       "known from the older file."})
        return out

    by_ticker = full.set_index("ticker").to_dict("index")
    for t in tickers:
        t = t.upper().strip()
        if t not in by_ticker:
            out[t] = {"status": "NOT SCANNED",
                      "detail": "Not in today's full scanned base panel at all -- likely "
                                "delisted, a symbol change, or not covered by this project's "
                                "price data."}
            continue
        row = by_ticker[t]
        status = row["status"]
        entry = {"status": status, "sector": row.get("sector"), "close": row.get("close"),
                 "market_cap": row.get("market_cap")}
        if status == "PICK":
            entry.update({"weight_pct": round(row["weight"] * 100, 2),
                          "blend_score": round(row["blend_score"], 4),
                          "composite_score": round(row["composite_score"], 4),
                          "q75_score": round(row["q75_score"], 4),
                          "vol_quintile": int(row["vol_quintile"]),
                          "rank_in_quintile": f"{int(row['rank_in_quintile'])} of {int(row['n_in_quintile'])} "
                                              f"(top {int(row['quintile_cutoff_rank'])} picked)"})
        elif status == "ELIGIBLE_NOT_PICKED":
            entry.update({"blend_score": round(row["blend_score"], 4),
                          "composite_score": round(row["composite_score"], 4),
                          "q75_score": round(row["q75_score"], 4),
                          "vol_quintile": int(row["vol_quintile"]),
                          "rank_in_quintile": f"{int(row['rank_in_quintile'])} of {int(row['n_in_quintile'])} "
                                              f"in its volatility quintile -- needed top "
                                              f"{int(row['quintile_cutoff_rank'])} to be picked",
                          "detail": "Eligible and scored, but ranked outside the top decile "
                                    "of its own trailing-volatility quintile."})
        elif status == "ELIGIBLE_NOT_SCORED":
            entry["detail"] = ("In today's cap2000 eligible universe, but missing a score from "
                               "q75 and/or the composite (e.g. incomplete features) -- excluded "
                               "from ranking, not ranked low.")
        else:  # INELIGIBLE_TODAY
            entry["detail"] = ("Not in today's point-in-time cap2000 universe (market cap < $2B, "
                               "price < $10, or not domestic common stock as of today) -- not "
                               "considered at all, regardless of what either model would score it.")
        out[t] = entry
    return out
