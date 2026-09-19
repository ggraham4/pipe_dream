"""
What the model is actually betting on, at every level of the industry tree.

Round 13 established that essentially all of the deployed model's performance
is a sector bet, and 2026-09-16's hierarchy screen found the bet is somewhat
FINER than sector at the traded tail (industry-level neutralisation explains
~47% more of the decile edge than sector-level does, t ~1.5). Neither of those
is visible anywhere in the app. This module makes it visible.

--------------------------------------------------------------------------
DESCRIPTION GOES DEEPER THAN NEUTRALISATION, AND THAT IS NOT A CONTRADICTION
--------------------------------------------------------------------------
sweep/taxonomy.py excludes sic3 (241 groups) and sicindustry (366) from the
neutralisation experiment: their median group holds 4-5 names, and fitting 366
dummies on a 1,665-name cross-section absorbs noise rather than industry.

That objection is about REGRESSION. It says nothing about COUNTING. "Three of
today's five picks are in Biotechnology" is a sound statement about a four-name
group -- it is a fact about the portfolio, not an estimate with a standard
error. So the descriptor runs the whole tree down to sicindustry while the
statistics stop at 145 groups, and the two are consistent.

--------------------------------------------------------------------------
ACTIVE WEIGHT, NOT PORTFOLIO WEIGHT
--------------------------------------------------------------------------
The number that matters is the portfolio's weight in a group MINUS the eligible
universe's weight in that group on the same date. A portfolio 30% in technology
when the universe is 28% technology is not a technology bet; it is the market.
Showing raw portfolio weight would make every concentrated-sector universe look
like a conviction call.

The universe weight is EQUAL-WEIGHTED over eligible names, because that is the
benchmark the model's own construction-matched null uses -- a random pick from
the eligible set. Cap-weighting it would compare the model against an index it
was never selecting from.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

from . import paths

paths.ensure_src_on_path()

# Coarse to fine. Everything below `industry` is description-only -- see the
# module docstring. sic2/sic3 are numeric codes in the source file and are
# rendered through taxonomy.display_label_map(), which names each rollup by its
# modal 4-digit industry, so the UI never shows a bare "38".
DISPLAY_LEVELS = ["sector", "famaindustry", "sic2", "industry", "sic3",
                  "sicindustry"]
NEUTRALISABLE = ["sector", "famaindustry", "sic2", "industry"]

TILT_HISTORY = paths.OUT_DIR / "sector_tilt_history.json"
ENRICHMENT = paths.OUT_DIR / "sector_enrichment.json"

N_VOL_BUCKETS = 5          # must match current_signal_pit.N_VOL_BUCKETS


def _taxonomy():
    from sweep import taxonomy as T
    return T


def level_map(level: str) -> dict:
    """ticker -> DISPLAY label. Grouping is identical to taxonomy.load(); only
    the SIC rollups' presentation differs."""
    return _taxonomy().display_label_map(level)


def tilt_levels(hist: dict | None) -> list:
    """Levels the tilt history actually carries.

    build_sector_tilt.py predates the finer levels and stores four. Any control
    that indexes hist["levels"] must be driven by this, not by DISPLAY_LEVELS,
    or selecting sic2 raises a KeyError.
    """
    if not hist:
        return []
    return [l for l in DISPLAY_LEVELS if l in hist.get("levels", {})]


def _base(t: str) -> str:
    from sweep.factors import _base_ticker
    return _base_ticker(t)


def eligible_universe(as_of) -> set:
    """The names the model could have picked on that date.

    Read straight from pit_universe.parquet rather than through
    continuous_walkforward_pit.load_pit_universe(), which is the canonical
    loader but imports xgboost at module scope -- so in any environment where
    xgboost is absent or broken the import raises, the old bare `except` handed
    back an EMPTY set, and describe() then reported every group at 100% active
    weight with no indication that the denominator had vanished. A silently
    empty benchmark is worse than a missing tab. The parquet's contract is two
    columns and a date slice, which is stable enough to read directly, and
    describe() now reports `universe_ok` either way so the app can say so.
    """
    path = paths.PIT_UNIVERSE_PARQUET
    if not path.exists():
        return set()
    try:
        u = _pit_universe_map(str(path))
        return u.get(str(pd.Timestamp(as_of).date()), set())
    except Exception:
        return set()


@lru_cache(maxsize=2)
def _pit_universe_map(path: str) -> dict:
    u = pd.read_parquet(path, columns=["date", "ticker"])
    u["date"] = u["date"].astype(str).str.slice(0, 10)
    u["ticker"] = u["ticker"].astype(str)
    return {d: frozenset(g) for d, g in u.groupby("date")["ticker"]}


def describe(picks: pd.DataFrame, as_of, levels=None) -> dict:
    """Active weights at each level.

    picks: DataFrame with `ticker` and `allocation_pct` (the live signal CSV).
    Returns {level: DataFrame[group, portfolio_pct, universe_pct, active_pct,
    n_picks, n_universe]} sorted by active weight, plus a concentration summary.
    """
    levels = levels or DISPLAY_LEVELS
    uni = eligible_universe(as_of)
    out = {"_universe_ok": bool(uni), "_n_universe": len(uni)}
    for lvl in levels:
        m = level_map(lvl)
        p = picks.copy()
        p["group"] = [m.get(_base(t), "(unclassified)") for t in p["ticker"]]
        port = p.groupby("group")["allocation_pct"].sum()
        n_picks = p.groupby("group")["ticker"].count()

        if uni:
            ulabs = pd.Series([m.get(_base(t), "(unclassified)") for t in uni])
            uw = ulabs.value_counts(normalize=True) * 100.0
            un = ulabs.value_counts()
        else:
            uw = pd.Series(dtype=float); un = pd.Series(dtype=int)

        df = pd.DataFrame({"portfolio_pct": port}).join(
            pd.DataFrame({"universe_pct": uw}), how="outer").join(
            pd.DataFrame({"n_picks": n_picks}), how="outer").join(
            pd.DataFrame({"n_universe": un}), how="outer")
        df = df.fillna({"portfolio_pct": 0.0, "universe_pct": 0.0,
                        "n_picks": 0, "n_universe": 0})
        df["active_pct"] = df["portfolio_pct"] - df["universe_pct"]
        df = df[(df["portfolio_pct"] > 0) | (df["universe_pct"] > 0)]
        df = df.sort_values("active_pct", ascending=False)
        df.index.name = lvl
        out[lvl] = df.reset_index()
    return out


def concentration(desc: dict) -> dict:
    """How concentrated is the bet at each level, in one number per level.

    Sum of POSITIVE active weight -- the share of the book that is an
    overweight somewhere. 0% means the portfolio matches the universe's
    composition; 100% means every holding is in a group the universe has none
    of. It rises mechanically as the tree gets finer (a 5-name portfolio cannot
    match a 366-group universe), which is why it is reported per level and
    never compared across them.
    """
    return {lvl: float(d.loc[d["active_pct"] > 0, "active_pct"].sum())
            for lvl, d in desc.items() if not lvl.startswith("_")}


def group_members(level: str, group: str, scored: pd.DataFrame,
                  picks: pd.DataFrame | None = None) -> pd.DataFrame:
    """Every name the model SCORED in one group, with its overall standing.

    `scored` is pit_model.scored_universe()'s frame -- the whole eligible
    cross-section, not just the five held. That distinction is the point: it
    shows what the model thought of the names it did NOT buy in a group it is
    overweight."""
    m = level_map(level)
    d = scored.copy()
    d["group"] = [m.get(_base(t), "(unclassified)") for t in d["ticker"]]
    d = d[d["group"] == group].copy()
    held = set(picks["ticker"]) if picks is not None else set()
    d["held"] = d["ticker"].isin(held)
    if "rank" in d.columns:
        d = d.sort_values("rank", na_position="last")
    return d


def group_rank_profile(level: str, group: str, scored: pd.DataFrame) -> dict:
    """Does the model like the whole GROUP, or only the names it bought?

    This is Round 13's question asked one group at a time. `median_percentile`
    is where a typical member of the group sits in the model's overall ranking,
    against 0.50 for a group the model is indifferent to.

    Well below 0.50  -> the model rates the whole group highly. A sector bet:
                        the picks are incidental, almost any member would do.
    Near 0.50        -> the model is indifferent to the group as a whole and
                        the holdings are genuine within-group selection.

    Round 13 measured within-sector picking as at or below random in aggregate,
    so the expectation is the former. Seeing it per group, on today's actual
    bet, is the part that was never visible.
    """
    d = group_members(level, group, scored)
    el = d[d.get("eligible_today", True) == True] if "eligible_today" in d else d
    pc = pd.to_numeric(el.get("percentile"), errors="coerce").dropna()
    if not len(pc):
        return {}
    return {"n_scored": int(len(d)), "n_eligible": int(len(el)),
            "median_percentile": float(pc.median()),
            "best_rank": int(pd.to_numeric(el["rank"], errors="coerce").min()),
            "share_top_decile": float((pc <= 0.10).mean())}


def load_tilt_history() -> dict | None:
    """Realised historical tilt, from build_sector_tilt.py. None if not built."""
    if not TILT_HISTORY.exists():
        return None
    import json
    try:
        return json.loads(TILT_HISTORY.read_text())
    except Exception:
        return None


# --------------------------------------------------------------------------
# ENRICHMENT
# --------------------------------------------------------------------------
# Gabe's question (2026-09-16): which groups are significantly over-picked?
# The statistics are in sweep/enrich.py and its docstring is the explanation.
# The one thing to carry in mind here: the selection takes the best name in
# each of five trailing-volatility quintiles, so the null is five one-draw
# hypergeometrics, not one five-draw hypergeometric. Both are reported.


def _enrich():
    from sweep import enrich as E
    return E


def enrichment_today(level: str, picks: pd.DataFrame,
                     scored: pd.DataFrame) -> list:
    """The hypergeometric test on TODAY's five picks. Underpowered by design.

    Five draws against up to 439 groups: a group needs 2 of the 5 before BH
    can call anything, so an empty result is the expected result and must be
    presented as such rather than as evidence of no tilt. The pooled version
    (`enrichment_history`) is where the power is.

    `scored` is pit_model.scored_universe()'s frame; the eligible rows carry
    volatility_60, which is what the quintiles are cut on.
    """
    E = _enrich()
    from sweep.portfolio import _bucket_idx

    el = scored[scored.get("eligible_today", True) == True].copy()
    if "volatility_60" not in el.columns or el.empty:
        return []
    v = pd.to_numeric(el["volatility_60"], errors="coerce").to_numpy(float)
    if not np.isfinite(v).all():
        # _bucket_idx files a NaN into bucket 0, which is a real defect (it was
        # the Round 18 live-pool bug); refuse rather than silently mis-stratify.
        return []
    el = el.assign(_b=_bucket_idx(v, N_VOL_BUCKETS))

    m = level_map(level)
    el["_g"] = [m.get(_base(t), "(unclassified)") for t in el["ticker"]]
    held = set(picks["ticker"])
    hit = el[el["ticker"].isin(held)]
    if hit.empty:
        return []

    obs, ps = {}, {}
    for g in hit["_g"]:
        obs[g] = obs.get(g, 0) + 1
    for b in sorted(hit["_b"].unique()):
        sub = el[el["_b"] == b]
        share = sub["_g"].value_counts(normalize=True)
        for g, pr in share.items():
            ps.setdefault(g, []).append(float(pr))
    return E.enrich({g: (obs.get(g, 0), p) for g, p in ps.items()})


def load_enrichment() -> dict | None:
    """Pooled enrichment from build_sector_enrichment.py. None if not built."""
    if not ENRICHMENT.exists():
        return None
    import json
    try:
        return json.loads(ENRICHMENT.read_text())
    except Exception:
        return None


def enrichment_frame(enr: dict, level: str, era: str = "nominate",
                     q_max: float | None = None) -> pd.DataFrame:
    """One era's table at one level, ready to render."""
    rows = (enr or {}).get("levels", {}).get(level, {}).get(era, [])
    if not rows:
        return pd.DataFrame()
    d = pd.DataFrame(rows)
    if q_max is not None:
        d = d[d["q_enrich"] <= q_max]
    return d.sort_values(["q_enrich", "observed"], ascending=[True, False])


def ticker_groups(ticker: str, as_of=None, enr: dict | None = None,
                  era: str = "all") -> pd.DataFrame:
    """Where one ticker sits in the industry tree, at every level.

    Answers "what is this name, and does the model have a standing preference
    for its kind?" in one table. Each row is a level, its group, how many
    eligible names share that group today, and -- when the pooled enrichment
    has been built -- what the model did with that group across 620 draws.

    That join is the point. A group label on its own is a fact about the
    ticker; the enrichment columns beside it are a fact about the MODEL, and
    the useful question is whether a name the model likes sits in a group it
    has always liked. Nothing here is a reason to buy a ticker: the enrichment
    describes what was picked, not what paid (Round 13: sector-neutralising
    removes essentially all of the edge).
    """
    t = _base(str(ticker).strip().upper())
    uni = eligible_universe(as_of) if as_of is not None else set()
    rows = []
    for lvl in DISPLAY_LEVELS:
        m = level_map(lvl)
        g = m.get(t)
        row = {"level": lvl, "group": g or "(unclassified)"}
        if uni and g:
            row["n_eligible_today"] = sum(
                1 for x in uni if m.get(_base(x)) == g)
        if enr and g:
            hit = [r for r in enr.get("levels", {}).get(lvl, {}).get(era, [])
                   if r["group"] == g]
            if hit:
                h = hit[0]
                row.update({"picks": h["observed"], "expected": h["expected"],
                            "ratio": h["ratio"], "q_enrich": h["q_enrich"],
                            "q_deplete": h["q_deplete"]})
        rows.append(row)
    return pd.DataFrame(rows)


def known_ticker(ticker: str) -> bool:
    """Is this ticker classified at all? False means it is absent from
    tickers_master.csv, which is a data question, not a model verdict."""
    t = _base(str(ticker).strip().upper())
    return any(t in level_map(lvl) for lvl in DISPLAY_LEVELS)
