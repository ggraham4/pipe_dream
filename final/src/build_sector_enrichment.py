"""
Which industry groups does the deployed model over-pick, beyond chance?

    python3 build_sector_enrichment.py

Writes out/sector_enrichment.json for the app's Sector Bets tab.

Gabe's question (2026-09-16): a hypergeometric enrichment test, the same one
used for GO terms. The statistics live in sweep/enrich.py -- read its docstring
first, because the naive version of this test is wrong here in a way that
matters (the selection takes one name per volatility quintile, so the null is a
sum of five one-draw hypergeometrics, not one five-draw hypergeometric).

WHY THIS IS A BUILD STEP AND NOT AN APP FUNCTION
------------------------------------------------
Today's five picks are five draws. Against 366 sicindustry groups that is very
nearly powerless: a group would need 2 of the 5 to clear BH at all. The test
only has teeth pooled over the 124 rebalance windows in the score cache -- 620
draws -- and that needs the cached score cross-section, which the app does not
load. So the pooled result is computed here and the app reads the JSON; the
app still runs the single-date test live, clearly labelled as underpowered.

ERA. Split nominate / holdout / all. This is descriptive -- it reports what the
model did, it selects nothing -- so the hold-out rule does not bind, and the
split is published anyway so nobody has to take that on trust.

THE UNIVERSE IS THE SCORED CROSS-SECTION, NOT THE PIT UNIVERSE
--------------------------------------------------------------
build_sector_tilt.py computes active weight against the point-in-time universe,
which is the right benchmark for a WEIGHT. The right denominator for a DRAW is
the set the selection actually drew from: the names that reached _pick_idx with
a finite score, which is the score cache's cross-section for that date. Those
differ (the panel drops names with incomplete features), and using the PIT
universe here would attribute the feature-completeness filter's industry
composition to the model.
"""
import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from features import OUT_DIR                                  # noqa: E402
from sweep import enrich as E                                 # noqa: E402
from sweep import portfolio as P                              # noqa: E402
from sweep import taxonomy as T                               # noqa: E402
from sweep.factors import _base_ticker                        # noqa: E402

SCORES = OUT_DIR / "sweep" / "scores"
CELL = "price_fund_h40_q75_trd_xgb_d3e01r100_expanding_cap500k_pit_s40"
DST = OUT_DIR / "sector_enrichment.json"
LEVELS = T.ALL_LEVELS
TOP_N, N_BUCKETS = 5, 5
ERAS = {"nominate": ("2007-01-01", "2020-01-01"),
        "holdout": ("2020-01-01", "2027-01-01"),
        "all": ("2000-01-01", "2100-01-01")}
UNCLASSIFIED = "(unclassified)"


def _window_draws(d, maps):
    """One rebalance date -> per level, the draws it contributes.

    Returns {level: (picked_groups, [(bucket_group_shares)])} where the shares
    dict for each drawn bucket gives every group's fraction OF THAT BUCKET --
    the per-draw Bernoulli probabilities the stratified null needs.
    """
    idx = P._pick_idx(d, TOP_N, "volq", n_buckets=N_BUCKETS)
    if not len(idx):
        return None
    b = P._bucket_idx(d["vol"], N_BUCKETS)
    tick = [_base_ticker(str(t)) for t in d["ticker"]]
    drawn = sorted({int(x) for x in b[idx]})          # buckets that yielded a pick
    out = {}
    for lvl, m in maps.items():
        labs = np.array([m.get(t, UNCLASSIFIED) for t in tick], dtype=object)
        picked = [labs[i] for i in idx]
        shares = []
        for bi in drawn:
            sel = labs[b == bi]
            if not len(sel):
                continue
            vc = pd.Series(sel).value_counts(normalize=True)
            shares.append({str(k): float(v) for k, v in vc.items()})
        flat = pd.Series(labs).value_counts(normalize=True)
        out[lvl] = (picked, shares, {str(k): float(v) for k, v in flat.items()},
                    len(idx))
    return out


def main():
    tab = pd.read_parquet(OUT_DIR / "sweep" / "outcomes.parquet")
    tab["ticker"] = tab["ticker"].astype(str)
    sc = pd.read_parquet(SCORES / f"{CELL}.parquet")
    prep = P.Prepared(sc, tab, 40, None)
    # display_label_map, not load: the app groups on the display label, and a
    # JSON keyed on the bare SIC code ("283") would silently fail to join
    # against the "283 · Pharmaceutical Preparations" the tables show.
    maps = {lvl: T.display_label_map(lvl) for lvl in LEVELS}
    print(f"{len(prep.tps)} windows, {len(LEVELS)} levels "
          f"({', '.join(f'{l}:{len(set(maps[l].values()))}' for l in LEVELS)})")

    # per era, per level: group -> [observed, [stratified p per draw],
    #                               [flat p per draw]]
    acc = {era: {lvl: defaultdict(lambda: [0, [], []]) for lvl in LEVELS}
           for era in ERAS}
    n_win = {era: 0 for era in ERAS}
    n_draw = {era: 0 for era in ERAS}

    for tp in prep.tps:
        d = prep.g.get(np.datetime64(tp))
        if d is None or not len(d["score"]):
            continue
        res = _window_draws(d, maps)
        if res is None:
            continue
        day = str(pd.Timestamp(tp).date())
        eras = [e for e, (lo, hi) in ERAS.items() if lo <= day < hi]
        for e in eras:
            n_win[e] += 1
        for lvl, (picked, shares, flat, npicks) in res.items():
            for e in eras:
                a = acc[e][lvl]
                for g in picked:
                    a[str(g)][0] += 1
                for sh in shares:
                    for g, p in sh.items():
                        a[g][1].append(p)
                for g, p in flat.items():
                    a[g][2].extend([p] * npicks)
            if lvl == LEVELS[0]:
                for e in eras:
                    n_draw[e] += npicks

    out = {"cell_id": CELL, "levels": {}, "eras": {}}
    for era in ERAS:
        out["eras"][era] = {"n_windows": n_win[era], "n_draws": n_draw[era],
                            "span": list(ERAS[era])}
    for lvl in LEVELS:
        out["levels"][lvl] = {}
        for era in ERAS:
            a = acc[era][lvl]
            rows = E.enrich({g: (v[0], v[1]) for g, v in a.items()})
            flat_p = {g: E.poisson_binomial_tail(v[2], v[0]) for g, v in a.items()}
            for r in rows:
                r["p_enrich_flat"] = float(flat_p.get(r["group"], 1.0))
            # A group with no picks and a negligible expectation carries no
            # information in either tail; dropping it is what keeps the JSON
            # small enough for the app to load on every rerun. Groups the
            # model AVOIDED are kept (expected >= 1) so the depletion side
            # stays readable -- they are the other half of the question.
            rows = [r for r in rows if r["observed"] > 0 or r["expected"] >= 1.0]
            for r in rows:
                for k in ("expected", "sd", "ratio"):
                    r[k] = round(float(r[k]), 4)
                for k in ("p_enrich", "p_deplete", "q_enrich", "q_deplete",
                          "p_enrich_flat"):
                    r[k] = float(f"{r[k]:.4g}")
            out["levels"][lvl][era] = rows

    DST.write_text(json.dumps(out, indent=1))

    for era in ("nominate", "holdout"):
        print(f"\n{era}  ({n_win[era]} windows, {n_draw[era]} draws)")
        for lvl in ("sector", "industry"):
            sig = [r for r in out["levels"][lvl][era] if r["q_enrich"] < 0.10]
            print(f"  {lvl}: {len(sig)} group(s) at q<0.10 of "
                  f"{len(out['levels'][lvl][era])}")
            for r in sig[:6]:
                print(f"    {r['group'][:38]:<40} obs {r['observed']:>3} "
                      f"exp {r['expected']:>6.1f}  {r['ratio']:>5.2f}x  "
                      f"q={r['q_enrich']:.3g}  (flat p={r['p_enrich_flat']:.3g})")
    print(f"\nwritten {DST} ({DST.stat().st_size/1e3:.0f}KB)")


if __name__ == "__main__":
    main()
