"""
Blend vs theoretical model: per-ticker two-model answers, freshness of both
files, and how much the two books agree. Added 2026-09-24 per Gabe.

Pure pandas, no Streamlit, so it can be checked from a plain Python shell.

The two models are NOT scored on the same universe:
    blend        cap2000 tier  (current_signal_blend*.csv)
    theoretical  cap150 tier   (current_signal_composite*.csv, composite alone)
So a theoretical pick the blend didn't take is either STRUCTURAL (the blend
could never have picked it: INELIGIBLE_TODAY / NOT SCANNED in the blend's full
file) or a GENUINE disagreement (ELIGIBLE_NOT_PICKED: the blend scored it and
ranked it out). The reverse split (blend picks the theoretical model could
not have taken) needs current_signal_composite_full.csv, which does not exist
yet; the code uses it automatically if it appears.

Agreement is descriptive. It is not evidence that either model is right.
"""
from __future__ import annotations

import datetime as _dt

import numpy as np
import pandas as pd

from . import blend_model as bm
from . import composite_model as cm

STALE_BUSINESS_DAYS = 5
BLEND_ELIGIBLE = ("PICK", "ELIGIBLE_NOT_PICKED", "ELIGIBLE_NOT_SCORED")
STRUCTURAL = ("INELIGIBLE_TODAY", "NOT SCANNED")


def freshness(today: _dt.date | None = None) -> dict:
    """as_of_date of both files, whether they differ, and business days old."""
    today = today or _dt.date.today()
    out = {}
    for key, mod in (("blend", bm), ("theoretical", cm)):
        _, meta = mod.get_signal()
        as_of = (meta or {}).get("as_of_date")
        age = None
        if as_of:
            age = int(np.busday_count(pd.Timestamp(as_of).date(), today))
        out[key] = {"as_of": as_of, "busdays_old": age,
                    "stale": age is not None and age > STALE_BUSINESS_DAYS}
    b, t = out["blend"]["as_of"], out["theoretical"]["as_of"]
    out["dates_differ"] = bool(b and t and b != t)
    return out


def two_model_query(tickers: list[str]) -> pd.DataFrame:
    """One row per ticker, blend columns then theoretical columns."""
    tickers = list(dict.fromkeys(t.upper().strip() for t in tickers if t.strip()))
    b = bm.query_tickers(tickers)
    t = cm.query_tickers(tickers)
    rows = []
    for tk in tickers:
        br, tr = b.get(tk, {}), t.get(tk, {})
        rows.append({
            "ticker": tk,
            "both_pick": "Yes" if br.get("status") == "PICK" and tr.get("status") == "PICK" else "No",
            "blend_status": br.get("status"),
            "theo_status": tr.get("status"),
            "sector": br.get("sector") or tr.get("sector"),
            "blend_weight_pct": br.get("weight_pct"),
            "theo_weight_pct": tr.get("weight_pct"),
            "blend_score": br.get("blend_score"),
            "theo_composite_score": tr.get("composite_score"),
            "blend_rank": br.get("rank_in_quintile") or "",
            "blend_detail": br.get("detail") or "",
            "theo_detail": tr.get("detail") or "",
        })
    return pd.DataFrame(rows)


def agreement() -> dict | None:
    """Overlap statistics between the two books. None if either picks file
    is missing. Every count is recomputed from the files on disk."""
    bdf, _ = bm.get_signal()
    tdf, _ = cm.get_signal()
    if bdf is None or tdf is None:
        return None
    bfull = bm.get_full_universe()
    tfull = cm.get_full_universe()

    bw = bdf.set_index("ticker")["weight"]
    tw = tdf.set_index("ticker")["weight"]
    B, T = set(bw.index), set(tw.index)
    shared = sorted(B & T)
    union = B | T

    res = {
        "n_blend": len(B), "n_theo": len(T), "n_shared": len(shared),
        "pct_blend_shared": len(shared) / len(B) if B else np.nan,
        "pct_theo_shared": len(shared) / len(T) if T else np.nan,
        "jaccard": len(shared) / len(union) if union else np.nan,
        "weight_overlap": float(sum(min(bw[x], tw[x]) for x in shared)),
        "blend_weight_sum": float(bw.sum()), "theo_weight_sum": float(tw.sum()),
        "n_theo_only": len(T - B), "n_blend_only": len(B - T),
        "has_blend_full": bfull is not None, "has_theo_full": tfull is not None,
    }

    # Theoretical-only picks, split by what the BLEND said about them.
    if bfull is not None:
        bstatus = bfull.set_index("ticker")["status"]
        st_of = {x: bstatus.get(x, "NOT SCANNED") for x in T}
        theo_only = T - B
        res["theo_only_structural"] = sum(st_of[x] in STRUCTURAL for x in theo_only)
        res["theo_only_genuine"] = sum(st_of[x] == "ELIGIBLE_NOT_PICKED" for x in theo_only)
        res["theo_only_not_scored"] = sum(st_of[x] == "ELIGIBLE_NOT_SCORED" for x in theo_only)
        elig = {x for x in T if st_of[x] in BLEND_ELIGIBLE}
        res["n_theo_in_blend_universe"] = len(elig)
        res["pct_theo_eligible_shared"] = len(elig & B) / len(elig) if elig else np.nan

    # Blend-only picks, split by what the THEORETICAL model said (future file).
    if tfull is not None:
        tstatus = tfull.set_index("ticker")["status"]
        blend_only = B - T
        res["blend_only_structural"] = sum(tstatus.get(x, "NOT SCANNED") in STRUCTURAL
                                           for x in blend_only)
        res["blend_only_genuine"] = sum(tstatus.get(x) == "ELIGIBLE_NOT_PICKED" for x in blend_only)
        elig_b = {x for x in B if tstatus.get(x, "NOT SCANNED") in BLEND_ELIGIBLE}
        res["n_blend_in_theo_universe"] = len(elig_b)
        res["pct_blend_eligible_shared"] = len(elig_b & T) / len(elig_b) if elig_b else np.nan

    bi = bdf.set_index("ticker")
    ti = tdf.set_index("ticker")
    res["shared_table"] = pd.DataFrame({
        "ticker": shared,
        "sector": [bi.at[x, "sector"] for x in shared],
        "blend_weight": [bi.at[x, "weight"] for x in shared],
        "theo_weight": [ti.at[x, "weight"] for x in shared],
        "blend_score": [bi.at[x, "blend_score"] for x in shared],
        # Each model's OWN composite score: the blend's is ranked in cap2000,
        # the theoretical model's in cap150. Both shown, labelled.
        "blend_composite_score": [bi.at[x, "composite_score"] for x in shared],
        "theo_composite_score": [ti.at[x, "composite_score"] for x in shared],
    })
    return res
