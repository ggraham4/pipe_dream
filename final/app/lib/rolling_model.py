"""
Read-only loaders for the "Rolling weights (candidate)" tab (2026-10-01).

Gabe, 2026-10-01: "ok I think it can be added to the live but as a separate
tab until we verify on new data". The model is icw9_r252: the live Theoretical
(icw9_seas) factors with weights refit every 21 trading days on the trailing
1 year. It is TRACKED ONLY. Nothing here feeds Today's Picks, the Theoretical
tab, or any live weight.

Everything is read from files the WO-34 recording path writes
(final/src/rollweights/r252_forward.py, called from reset2026/record_weekly.py;
doc final/models/2026-09-30-r252-forward.md). This module never imports that
code and never computes a score, a weight, a t or a rank-IC: it only reads,
filters and joins. If a file is missing the tab shows an empty state.

WO-34b (2026-10-01) added a real picks file, written on every non-dry weekly
run (not only in weeks with a new record), in final/out/:
  current_signal_r252.csv            the Theoretical picks file's schema: ticker,
                                     sector, close, market_cap, volatility_60,
                                     composite_score, weight, seas. Same universe,
                                     date, seas and decile_volq construction as the
                                     Theoretical picks; only the weights differ.
  current_signal_r252_meta.json      the Theoretical meta's keys + one `r252` block
                                     (refit_date, refit_idx, refit_in_weight_path,
                                     factor_weights_full, picks_overlap_vs_icw9_seas,
                                     written_at). QUIRK: its `picks_overlap_vs_icw8`
                                     reuses the Theoretical helper, so the keys named
                                     n_icw9_seas / share_of_icw9_seas hold the R252
                                     count. Never display that key.
The tab shows these picks when both files are readable, else the ledger's
top-N ranking, else an empty state.

Files (all under final/out/reset2026/, none exist before the first record):
  prediction_ledger_r252.csv         append-only, one block of rows per weekly
                                     record: panel_date, recorded_at, r252_version,
                                     refit_date, refit_idx, ticker, sector, seas,
                                     icw8_score, icw9_seas_score, icw9_r252_score,
                                     icw9_r252_rank_pct
  r252_weight_path.csv               append-only, one row per refit: refit_date,
                                     refit_idx, first_used, last_used, n_min, ...,
                                     w_<factor>, t_<factor>, r252_version, ...
  prediction_ledger_r252_scores.csv  one row per matured, scored record:
                                     panel_date, n_names, rho_icw9_r252,
                                     rho_icw9_seas, gain, scored_at, version,
                                     refit_idx. Written by the weekly run since
                                     WO-34b; the first row appears ~41 trading days
                                     after the first record.
  ledger_r252_guard_log.csv          logged_at, ledger, panel_date, iso_week,
                                     event, detail. Events: r252_skipped (no
                                     record), r252_score_skipped,
                                     r252_picks_skipped (picks file not rewritten)
  ledger_record_log.csv / ledger_record_annotations.csv
                                     shared; recorded_late / incomplete_week flags

To add a second model column (e.g. a sign-aware variant): append one dict to
MODELS with that model's own files and column names. The tab loops over MODELS.
"""
from __future__ import annotations

import json

import pandas as pd

from . import paths

R26 = paths.OUT_DIR / "reset2026"
RECORD_LOG = R26 / "ledger_record_log.csv"
RECORD_ANNOTATIONS = R26 / "ledger_record_annotations.csv"

# Review rule fixed in the doc (sec. B5) before any record was written.
FIRST_REVIEW, FINAL_REVIEW = 26, 52

MODELS = [
    {
        "key": "icw9_r252",
        "label": "R252 (weights refit on the trailing 1 year)",
        "short": "R252",
        "ledger": R26 / "prediction_ledger_r252.csv",
        "scores": R26 / "prediction_ledger_r252_scores.csv",
        "weight_path": R26 / "r252_weight_path.csv",
        "guard_log": R26 / "ledger_r252_guard_log.csv",
        "picks": paths.OUT_DIR / "current_signal_r252.csv",
        "picks_meta": paths.OUT_DIR / "current_signal_r252_meta.json",
        "meta_block": "r252",                    # the model's own block in the picks meta
        "score_col": "icw9_r252_score",
        "rank_col": "icw9_r252_rank_pct",
        "version_col": "r252_version",
        "baseline_col": "icw9_seas_score",      # the live Theoretical score on the same rows
        "gain_col": "gain",                      # rank-IC(model) - rank-IC(icw9_seas), per record
        "rho_col": "rho_icw9_r252",
        "rho_baseline_col": "rho_icw9_seas",
    },
]


def _mtime(p) -> float:
    try:
        return p.stat().st_mtime
    except OSError:
        return -1.0


def mtimes() -> tuple:
    """Cache key: every file the tab reads."""
    ps = [RECORD_LOG, RECORD_ANNOTATIONS]
    for m in MODELS:
        ps += [m["ledger"], m["scores"], m["weight_path"], m["guard_log"]]
        ps += [m[k] for k in ("picks", "picks_meta") if k in m]
    return tuple(_mtime(p) for p in ps)


def _read(p):
    """(df, error). (None, None) when the file doesn't exist. A file that
    exists but can't be parsed (e.g. caught mid-write) gives (None, message)."""
    if not p.exists():
        return None, None
    try:
        return pd.read_csv(p), None
    except Exception as e:  # noqa: BLE001 -- display only, never raise into the page
        return None, f"{p.name} could not be read ({type(e).__name__}: {e})"


# The picks table needs these; the rest of the Theoretical schema is optional.
PICKS_NEED = {"ticker", "composite_score", "weight"}
PICKS_COLS = ["ticker", "sector", "close", "market_cap", "volatility_60",
              "composite_score", "weight", "seas"]


def load_picks(spec) -> tuple:
    """(picks df, meta dict, errors). (None, {}, []) when the model has no
    picks file yet. The pair is all-or-nothing: if one file is missing,
    unreadable or the wrong shape, no picks are returned and the tab falls
    back to the ledger ranking, with the reason in errors."""
    csv, mj = spec.get("picks"), spec.get("picks_meta")
    if csv is None or mj is None or (not csv.exists() and not mj.exists()):
        return None, {}, []
    fallback = "showing the ledger ranking instead of picks"
    if not csv.exists() or not mj.exists():
        missing = mj if csv.exists() else csv
        return None, {}, [f"{missing.name} is missing while its pair exists; {fallback}"]
    df, err = _read(csv)
    if err:
        return None, {}, [f"{err}; {fallback}"]
    if df is None or df.empty or not PICKS_NEED <= set(df.columns):
        return None, {}, [f"{csv.name} is empty or missing columns "
                          f"{sorted(PICKS_NEED - set(df.columns))}; {fallback}"]
    try:
        meta = json.loads(mj.read_text())
    except Exception as e:  # noqa: BLE001 -- display only
        return None, {}, [f"{mj.name} could not be read ({type(e).__name__}: {e}); {fallback}"]
    if not isinstance(meta, dict) or not meta.get("as_of_date"):
        return None, {}, [f"{mj.name} has no as_of_date; {fallback}"]
    df["ticker"] = df["ticker"].astype(str)
    return df[[c for c in PICKS_COLS if c in df.columns]], meta, []


def picks_block(spec, data: dict) -> dict:
    """The model's own block of the picks meta ({} if absent or not a dict)."""
    b = (data.get("picks_meta") or {}).get(spec.get("meta_block", ""))
    return b if isinstance(b, dict) else {}


def picks_table(data: dict, live_picks: set | None) -> pd.DataFrame:
    """The picks file as written (its own order: weight descending), plus the
    marker against the live Theoretical picks. Nothing is recomputed."""
    df = data["picks"].copy()
    if live_picks is not None:
        df["vs live Theoretical picks"] = ["also a live pick" if t in live_picks
                                           else "NOT a live pick" for t in df["ticker"]]
    return df


def weights_row_for(spec, data: dict, use_picks: bool):
    """(row, refit_idx, source) for the weights table.

    use_picks False: the refit the latest ledger RECORD used.
    use_picks True: the refit the PICKS file used (its meta's refit_idx). That
    can be newer than every row in the weight path (the path only grows when a
    record is written); then the weights come from the meta's
    factor_weights_full and there is no t to show."""
    if not use_picks:
        return data["weights_row"], data["refit_idx"], "record"
    blk = picks_block(spec, data)
    idx = blk.get("refit_idx")
    idx = int(idx) if isinstance(idx, (int, float)) and not pd.isna(idx) else None
    wp = data.get("weight_path")
    if wp is not None and idx is not None:
        hit = wp[wp["refit_idx"].astype("Int64") == idx]
        if len(hit):
            return hit.iloc[-1], idx, "path"
    full = blk.get("factor_weights_full")
    if isinstance(full, dict) and full:
        try:
            return pd.Series({f"w_{k}": float(v) for k, v in full.items()}), idx, "meta"
        except (TypeError, ValueError):
            pass
    return None, idx, "none"


def _excluded(spec) -> tuple[set, set]:
    """(late, incomplete_week) panel dates for this ledger. Same filters as
    r252_forward.excluded_dates(): those records are descriptive only."""
    late, inc = set(), set()
    lg, _ = _read(RECORD_LOG)
    if lg is not None and {"ledger", "panel_date", "recorded_late"} <= set(lg.columns):
        lg = lg[(lg["ledger"] == spec["ledger"].name)
                & lg["recorded_late"].astype(str).str.lower().eq("true")]
        late = set(lg["panel_date"].astype(str))
    an, _ = _read(RECORD_ANNOTATIONS)
    if an is not None and {"ledger", "panel_date", "annotation"} <= set(an.columns):
        an = an[(an["ledger"] == spec["ledger"].name)
                & an["annotation"].astype(str).str.startswith("incomplete_week")]
        inc = set(an["panel_date"].astype(str))
    return late, inc


def load(spec) -> dict:
    """Everything the tab shows for one model, as plain data.

    keys: errors (list[str]), has_record (bool), dates (list[str]),
    latest (DataFrame of the newest record's rows, or None), panel_date,
    recorded_at, version, refit_idx, refit_date, weights_row (Series or None),
    scores (DataFrame or None), late / incomplete (sets), guard (DataFrame or None),
    picks (DataFrame or None), picks_meta (dict), weight_path (DataFrame or None)
    """
    out = {"errors": [], "has_record": False, "dates": [], "latest": None,
           "panel_date": None, "recorded_at": None, "version": None,
           "refit_idx": None, "refit_date": None, "weights_row": None,
           "scores": None, "late": set(), "incomplete": set(), "guard": None,
           "picks": None, "picks_meta": {}, "weight_path": None}

    # picks and the weight path don't depend on a ledger record existing
    out["picks"], out["picks_meta"], errs = load_picks(spec)
    out["errors"] += errs
    wp, err = _read(spec["weight_path"])
    if err:
        out["errors"].append(err)
    if wp is not None and "refit_idx" in wp.columns:
        out["weight_path"] = wp

    guard, err = _read(spec["guard_log"])
    if err:
        out["errors"].append(err)
    out["guard"] = guard

    led, err = _read(spec["ledger"])
    if err:
        out["errors"].append(err)
    need = {"panel_date", "ticker", spec["score_col"]}
    if led is not None and not need <= set(led.columns):
        out["errors"].append(f"{spec['ledger'].name} is missing columns "
                             f"{sorted(need - set(led.columns))}")
        led = None
    if led is None or led.empty:
        return out

    led["panel_date"] = led["panel_date"].astype(str)
    out["dates"] = sorted(led["panel_date"].unique())
    out["panel_date"] = out["dates"][-1]
    latest = led[led["panel_date"] == out["panel_date"]].reset_index(drop=True)
    out["latest"] = latest
    out["has_record"] = True
    first = latest.iloc[0]
    out["recorded_at"] = first.get("recorded_at")
    out["version"] = first.get(spec["version_col"])
    out["refit_date"] = first.get("refit_date")
    if "refit_idx" in latest.columns and pd.notna(first["refit_idx"]):
        out["refit_idx"] = int(first["refit_idx"])
    out["late"], out["incomplete"] = _excluded(spec)

    # the weights the latest RECORD used (match on refit_idx -- the path can
    # already hold a newer refit than the latest record)
    wp = out["weight_path"]
    if wp is not None and out["refit_idx"] is not None:
        hit = wp[wp["refit_idx"].astype("Int64") == out["refit_idx"]]
        if len(hit):
            out["weights_row"] = hit.iloc[-1]

    sc, err = _read(spec["scores"])
    if err:
        out["errors"].append(err)
    if sc is not None and {"panel_date", spec["gain_col"]} <= set(sc.columns):
        sc["panel_date"] = sc["panel_date"].astype(str)
        out["scores"] = sc.drop_duplicates("panel_date", keep="last")
    return out


def weights_table(live_weights: dict | None, rows: dict) -> pd.DataFrame | None:
    """One row per factor: the live Theoretical weight, then per model its
    weight, its trailing-1y t, and whether that t points against the weight.

    live_weights = the Theoretical meta's factor_weights (may be None).
    rows = {model key: weight-path row (or a w_-only Series from the picks
    meta), or None}. Returns None if no model has weights."""
    cols = {}
    factors = list(live_weights or {})
    for spec in MODELS:
        row = rows.get(spec["key"])
        if row is None:
            continue
        fs = [c[2:] for c in row.index if c.startswith("w_")]
        factors += [f for f in fs if f not in factors]
        w = {f: float(row[f"w_{f}"]) for f in fs}
        t = {f: (float(row[f"t_{f}"]) if f"t_{f}" in row.index else float("nan")) for f in fs}
        cols[spec["short"]] = (w, t)
    if not cols:
        return None
    df = pd.DataFrame({"factor": factors})
    df["Live Theoretical weight"] = [(live_weights or {}).get(f) for f in factors]
    for short, (w, t) in cols.items():
        df[f"{short} weight"] = [w.get(f) for f in factors]
        df[f"{short} trailing-1y t"] = [t.get(f) for f in factors]
        df[f"{short} t vs weight"] = [_agree(w.get(f), t.get(f)) for f in factors]
    return df


OPPOSITE = "OPPOSITE"


def _agree(w, t) -> str:
    if w is None or t is None or pd.isna(w) or pd.isna(t):
        return "no t"
    if w == 0 or t == 0:
        return "—"
    return OPPOSITE if (w > 0) != (t > 0) else "same sign"


def top_table(spec, data: dict, n: int, live_picks: set | None) -> pd.DataFrame:
    """The n highest-scored names in the latest record, with a marker for
    names that are / are not in the live Theoretical picks file."""
    df = data["latest"]
    keep = [c for c in ["ticker", "sector", spec["score_col"], spec["rank_col"],
                        spec["baseline_col"], "seas"] if c in df.columns]
    top = (df[keep].dropna(subset=[spec["score_col"]])
           .sort_values([spec["score_col"], "ticker"], ascending=[False, True], kind="mergesort")
           .head(n).reset_index(drop=True))
    if live_picks is not None:
        top["vs live Theoretical picks"] = ["also a live pick" if t in live_picks
                                            else "NOT a live pick" for t in top["ticker"]]
    return top


def scores_table(spec, data: dict) -> pd.DataFrame | None:
    """The recorder's per-record scores as written, newest first, plus whether
    each record counts toward the review. None if nothing is scored yet."""
    sc = data["scores"]
    if sc is None or sc.empty:
        return None
    keep = [c for c in ["panel_date", "n_names", spec["rho_col"], spec["rho_baseline_col"],
                        spec["gain_col"], "refit_idx", "scored_at"] if c in sc.columns]
    df = sc[keep].sort_values("panel_date", ascending=False).reset_index(drop=True)
    df.insert(1, "counts toward review", [
        "no (recorded late)" if d in data["late"] else
        "no (incomplete week)" if d in data["incomplete"] else
        "no (not in the ledger)" if d not in data["dates"] else "yes"
        for d in df["panel_date"]])
    return df


def tracker_row(spec, data: dict) -> dict:
    """Forward-tracker counts for one model. The paired difference is the
    recorder's own per-record `gain` column, averaged over counted records
    (on-time, complete-week), as r252_forward.status() does. No rank-IC is
    computed here."""
    dates = data["dates"]
    counted = [d for d in dates if d not in data["late"] and d not in data["incomplete"]]
    sc = data["scores"]
    gains = []
    if sc is not None:
        g = sc.set_index("panel_date")[spec["gain_col"]]
        gains = [float(g[d]) for d in counted if d in g.index and pd.notna(g[d])]
    return {
        "model": spec["short"],
        "weekly records": len(dates),
        "counted (on time, full week)": len(counted),
        "matured and scored": len(gains),
        "mean rank-IC difference vs live Theoretical": (sum(gains) / len(gains)) if gains else None,
        "records with a positive difference": (sum(x > 0 for x in gains) if gains else None),
        "first record": dates[0] if dates else None,
        "latest record": dates[-1] if dates else None,
    }
