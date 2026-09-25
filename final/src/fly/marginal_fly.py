"""
Marginal effect of each design choice, as a within-window 2x2 factorial.

    python3 marginal_fly.py

THE DESIGN. Four cells crossing two binary factors:

                      ordered time      scrambled time
    real topology     real/ordered      real/scrambled
    rewired           rewired/ordered   rewired/scrambled

plus a fifth arm, a ridge on the same features with NO network at all, which
sits outside the 2x2 and estimates what the reservoir itself is worth.

WHY WITHIN-WINDOW. Every cell scores the same names on the same 78 dates; only
the model differs. So the window is a matched block, and differencing inside it
removes the market-wide variation that dominates every one of these series.
Reading main effects off unpaired averages -- which is what the earlier
pairwise contrasts did -- throws that away and leaves the comparison swamped by
2008 and 2020.

The main effect of ORDER is the average over windows of

    (real_ord + rewired_ord)/2  -  (real_scr + rewired_scr)/2

i.e. the effect of ordering averaged across both topologies, which is what a
marginal effect means. Topology is the same expression transposed, and the
interaction asks whether ordering matters MORE on the real connectome than on a
rewired one -- the only cell in this table where "the fly is special" could
legitimately appear.

THREE METRICS, because they disagree and the disagreement is the finding:

  ic             full cross-section Spearman. ~2,200 names/window.
  decile_excess  top 10% by score vs universe mean. ~116 names/window.
  top5_excess    the 5 names actually held. 5 names/window.

Power falls by ~20x at each step; relevance to what is traded rises. An effect
that appears only in top5_excess and vanishes in decile_excess is five names
being five names.
"""
import sys
from pathlib import Path
from itertools import combinations

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from features import OUT_DIR                     # noqa: E402
from sweep import portfolio as P                 # noqa: E402
from sweep import _num                           # noqa: E402

SCORES = OUT_DIR / "sweep" / "scores"
ERA = ("2007-01-01", "2020-01-01")
WIN_PER_YEAR = 252.0 / 40.0

# --seed changes the claw projection, the rewiring AND the scramble permutation
# independently, so seeds are fresh draws of everything except the connectome
# and the data. Pooling across them is how an effect that lives in one
# particular 5-name draw gets separated from one that does not.
TEMPLATES = {
    "real/ordered":      "fly_mushroom_body_T20_s{s}",
    "real/scrambled":    "fly_mushroom_body_scram_T20_s{s}",
    "rewired/ordered":   "fly_mushroom_body_shuf_T20_s{s}",
    "rewired/scrambled": "fly_mushroom_body_shuf_scram_T20_s{s}",
    "baseline/no-net":   "fly_none_T20_s{s}",
}
# Reference cells with no seed dimension -- graded on the same statistics so the
# fly family can be read against what is actually deployed rather than against
# zero. A model that loses to the incumbent on every powered statistic is not a
# candidate however it compares to its own controls.
REFERENCE = {
    "deployed q75": "price_fund_h40_q75_trd_xgb_d3e01r100_expanding_cap500k_pit_s40",
    "candidate xrank": "price_fund_h40_xrank_trd_xgb_reg_d3e01r100_expanding_cap500k_pit_s40",
}
METRICS = ["ic", "decile_excess", "decile_volq_excess", "top5_excess"]


def per_window(cid, tab):
    sc = pd.read_parquet(SCORES / f"{cid}.parquet")
    prep = P.Prepared(sc, tab, 40, None)
    rows = []
    for tp, d in prep.g.items():
        t = pd.Timestamp(tp)
        if not (pd.Timestamp(ERA[0]) <= t < pd.Timestamp(ERA[1])):
            continue
        ok = np.isfinite(d["ret"]) & d["tradable"] & np.isfinite(d["score"])
        if ok.sum() < 100:
            continue
        ret, sco = d["ret"][ok], d["score"][ok]
        uni = float(ret.mean())

        # RAW decile: top 10% by score, no bucketing.
        k = max(1, int(0.10 * len(sco)))
        top = np.argpartition(-sco, k - 1)[:k]

        # BUCKET-MATCHED decile: top 10% WITHIN each volatility quintile.
        #
        # This exists because the earlier comparison was not like-for-like and
        # the conclusion drawn from it was therefore unsound. top5_excess goes
        # through _pick_idx(..., "volq") -- the best name in each of five
        # volatility buckets -- while the raw decile is the top 10% overall. If
        # ordered input sharpens the ranking WITHIN buckets, the bucketed
        # selection sees it and the raw decile does not, and "it appears at
        # top-5 but not at decile" is a selection-rule difference rather than
        # the power paradox it was read as.
        b = P._bucket_idx(d["vol"][ok], 5)
        sel = []
        for bi in range(5):
            m = np.flatnonzero(b == bi)
            if len(m) < 10:
                continue
            kk = max(1, int(0.10 * len(m)))
            sel.append(m[np.argpartition(-sco[m], kk - 1)[:kk]])
        volq_dec = (float(ret[np.concatenate(sel)].mean()) - uni
                    if sel else np.nan)

        i5 = P._pick_idx(d, 5, "volq")
        i5 = i5[d["tradable"][i5] & np.isfinite(d["ret"][i5])]
        rows.append({"tp": t,
                     "ic": _num.spearman(sco, ret),
                     "decile_excess": float(ret[top].mean()) - uni,
                     "decile_volq_excess": volq_dec,
                     "top5_excess": (float(d["ret"][i5].mean()) - uni
                                     if len(i5) else np.nan)})
    return pd.DataFrame(rows).set_index("tp")


def paired(v, label, unit, clusters=None):
    """Mean, t and 95% interval for a within-window difference.

    CLUSTERED BY WINDOW when `clusters` is given, and it must be given whenever
    seeds are pooled. Three seeds of the same window are not three independent
    observations: they share the returns, the names and the market, and differ
    only in the random projection and the scramble permutation. Treating 78
    windows x 3 seeds as 234 independent draws inflates every t by up to
    sqrt(3). Averaging within a window first and testing across windows is the
    correct unit of replication -- the window is what is sampled, the seed is
    not.
    """
    v = np.asarray(v, np.float64)
    ok = np.isfinite(v)
    v = v[ok]
    if clusters is not None:
        c = np.asarray(clusters)[ok]
        v = np.array([v[c == u].mean() for u in np.unique(c)])
    n = len(v)
    if n < 3:
        return None
    m, se = v.mean(), v.std(ddof=1) / np.sqrt(n)
    return {"label": label, "n": n, "mean": m, "t": m / se,
            "lo": m - 1.99 * se, "hi": m + 1.99 * se, "unit": unit}


def show(rows, scale, unit):
    print(f"{'effect':<34}{'estimate':>12}{'95% interval':>24}{'t':>8}")
    for r in rows:
        if r is None:
            continue
        print(f"{r['label']:<34}{r['mean']*scale:>+12.4f}"
              f"{f'[{r[chr(108)+chr(111)]*scale:+.4f}, {r[chr(104)+chr(105)]*scale:+.4f}]':>24}"
              f"{r['t']:>+8.2f}   {unit}")


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", default="0",
                    help="comma-separated seeds to POOL. Each seed is an "
                         "independent draw of the projection, the rewiring and "
                         "the scramble permutation.")
    args = ap.parse_args()
    seeds = [int(x) for x in args.seeds.split(",") if x.strip() != ""]

    tab = pd.read_parquet(OUT_DIR / "sweep" / "outcomes.parquet")
    tab["ticker"] = tab["ticker"].astype(str)

    frames, missing = {}, []
    for name, tmpl in TEMPLATES.items():
        parts = []
        for sd in seeds:
            cid = tmpl.format(s=sd)
            if not (SCORES / f"{cid}.parquet").exists():
                missing.append(cid)
                continue
            d = per_window(cid, tab)
            d["seed"] = sd
            parts.append(d.set_index("seed", append=True))
        if parts:
            frames[name] = pd.concat(parts)
    for name, cid in REFERENCE.items():
        if (SCORES / f"{cid}.parquet").exists():
            d = per_window(cid, tab)
            d["seed"] = 0
            frames[name] = d.set_index("seed", append=True)
    if missing:
        print(f"missing, skipped: {missing}")
    if not frames:
        raise SystemExit("no cells found")
    per = frames
    fly_keys = [k for k in per if k in TEMPLATES]
    common = None
    for k in fly_keys:
        ix = per[k].index
        common = ix if common is None else common.intersection(ix)
    print(f"pooling seeds {seeds}: {len(common)} (window, seed) blocks across "
          f"{len(fly_keys)} fly cells")
    for k in list(per):
        per[k] = per[k].loc[common] if k in fly_keys else per[k]

    for metric in METRICS:
        m = {k: d[metric].to_numpy(np.float64) for k, d in per.items()}
        # index is (timepoint, seed) -- cluster on the timepoint. Built PER
        # CELL: the fly cells carry 3 seeds x 78 windows while the reference
        # cells carry 82 windows and no seed dimension, so one shared cluster
        # vector cannot index both.
        winmap = {k: np.asarray([ix[0] for ix in d.index]) for k, d in per.items()}
        win = winmap[next(k for k in per if k in TEMPLATES)]
        scale = 1.0 if metric == "ic" else 100.0
        unit = "" if metric == "ic" else "pp/window"
        print("\n" + "=" * 86)
        print(f"{metric.upper()}")
        print("=" * 86)
        print(f"{'cell':<34}{'mean':>12}{'':>24}{'t':>8}")
        for k in per:
            r = paired(m[k], k, unit, clusters=winmap[k])
            print(f"{k:<34}{r['mean']*scale:>+12.4f}{'':>24}{r['t']:>+8.2f}")

        if not {"real/ordered", "real/scrambled", "rewired/ordered",
                "rewired/scrambled"} <= set(m):
            continue
        ro, rs = m["real/ordered"], m["real/scrambled"]
        wo, ws = m["rewired/ordered"], m["rewired/scrambled"]
        print()
        rows = [
            paired((ro + wo) / 2 - (rs + ws) / 2,
                   "ORDER  (ordered - scrambled)", unit, clusters=win),
            paired((ro + rs) / 2 - (wo + ws) / 2,
                   "TOPOLOGY  (real - rewired)", unit, clusters=win),
            paired((ro - rs) - (wo - ws),
                   "INTERACTION  order x topology", unit, clusters=win),
        ]
        if "baseline/no-net" in m:
            b = m["baseline/no-net"]
            rows.append(paired((ro + rs + wo + ws) / 4 - b,
                               "RESERVOIR  (any network - none)", unit,
                               clusters=win))
            rows.append(paired(ro - b, "  real/ordered - baseline", unit,
                               clusters=win))
        show(rows, scale, unit)
        if metric != "ic":
            best = max((r for r in rows if r), key=lambda r: abs(r["t"]))
            print(f"\n  annualised, {best['label'].strip()}: "
                  f"{best['mean']*100*WIN_PER_YEAR:+.2f} pp/yr "
                  f"[{best['lo']*100*WIN_PER_YEAR:+.2f}, "
                  f"{best['hi']*100*WIN_PER_YEAR:+.2f}]")

    # how much of the variation is the model at all, versus the window
    print("\n" + "=" * 86)
    print("VARIANCE DECOMPOSITION -- is any of this large next to the market?")
    print("=" * 86)
    for metric in METRICS:
        M = np.column_stack([per[k][metric].to_numpy(np.float64) for k in per])
        ok = np.isfinite(M).all(axis=1)
        M = M[ok]
        between_window = float(M.mean(axis=1).var(ddof=1))
        within_window = float(M.var(axis=1, ddof=1).mean())
        tot = between_window + within_window
        print(f"  {metric:<16} window (market) {between_window/tot:>6.1%}   "
              f"model choice {within_window/tot:>6.1%}")
    print("\n  'model choice' is the share of variance attributable to WHICH OF")
    print("  THESE FIVE MODELS you ran, holding the window fixed. It is the")
    print("  ceiling on what any of these design decisions could be worth.")


if __name__ == "__main__":
    main()
