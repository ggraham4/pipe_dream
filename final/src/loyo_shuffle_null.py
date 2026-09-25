"""
Leave-one-year-out on a shuffle-null winner.

    python3 loyo_shuffle_null.py --column days_to_next_filing_seasonal

WHY
---
Standing procedure since Round 14: any candidate that survives a gate gets the
leave-one-year-out concentration test before it is believed. Round 19c's
backlog screen produced exactly one pass out of fifteen candidates
(`days_to_next_filing_seasonal`, BH q 0.022). One pass in fifteen at q <= 0.20
carries a ~20% chance of being a false discovery, and the failure mode that
matters most here is the one BH cannot see: an edge that is real in the
arithmetic but lives entirely in one or two years.

WHAT IT DOES
------------
No refit. The scored cross-sections for the candidate cell and each of its
shuffle draws are already cached from the screen, and `decile_volq_excess` is a
mean over per-window observations -- so dropping a year is a subset of an
existing series, not a new experiment. That makes this seconds rather than
hours, and it means the LOYO numbers are computed from the identical fitted
models that produced the headline result.

For each year Y in the nomination era:

    gap(-Y) = mean(candidate windows not in Y) - mean(pooled null windows not in Y)

and a t on that gap using the paired per-window difference against the null's
window-matched mean. The candidate and every null draw score the SAME windows
(same cell, same dates, only the permuted column differs), so the difference is
paired and the pairing removes the market-wide component that dominates the
raw series variance.

READING IT
----------
  same sign on all years        the edge is not one year wearing a disguise
  min |t| across drops          the weakest the result gets when its best year
                                is removed; compare to the full-sample t
  worst single year's own gap   if one year is several times the others, the
                                column is an event detector for that year, not
                                a feature

A column that flips sign on any single-year drop has failed. A column whose
min |t| falls below ~2 has not failed outright but is a one-era result and the
hold-out will decide it.
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from features import OUT_DIR                                  # noqa: E402
from sweep import portfolio as P                              # noqa: E402

# Constants copied rather than imported from sweep.cli / sweep.scorecache: both
# of those pull in xgboost at module scope, and this script never fits a model.
# Same defect as the one that blocked the order screen (RUNBOOK bug ledger).
# If these three ever drift from their definitions there, this script is wrong.
CACHE_DIR = OUT_DIR / "sweep" / "scores"
OUTCOMES_PATH = OUT_DIR / "sweep" / "outcomes.parquet"
NOMINATE_ERA = ("2007-01-01", "2020-01-01")

RUNS = Path(__file__).resolve().parent / "sweep" / "runs"
BMANIFEST = RUNS / "backlog_manifest.json"
MANIFEST = RUNS / "shuffle_null_manifest.json"
PORTFOLIO = {"horizon": 40, "stop": None}


def _series(cell, tab, era):
    """decile_volq_excess per window for one cached cell, or None."""
    cpath = CACHE_DIR / f"{cell}.parquet"
    mpath = CACHE_DIR / f"{cell}.json"
    if not cpath.exists() or not mpath.exists():
        return None
    scores = pd.read_parquet(cpath)
    H = int(json.load(open(mpath))["config"]["horizon"])
    try:
        prep = P.Prepared(scores, tab, H, None)
    except KeyError:
        return None
    s = P.decile_series(prep, era=era)
    return s if len(s) >= 2 else None


def _manifest(column):
    for path in (BMANIFEST, MANIFEST):
        if not path.exists():
            continue
        man = json.loads(path.read_text())
        for c in man["candidates"]:
            if c["column"] == column:
                return path, man, c
    raise SystemExit(f"{column} is in neither backlog nor shuffle-null manifest")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--column", required=True)
    ap.add_argument("--era", default="nominate", choices=["nominate"])
    a = ap.parse_args()

    path, man, c = _manifest(a.column)
    era = NOMINATE_ERA
    print(f"manifest   {path.name}")
    print(f"column     {a.column}   panel {Path(c['panel']).stem}")
    print(f"era        {era[0]} .. {era[1]}\n", flush=True)

    tab = pd.read_parquet(OUTCOMES_PATH)
    tab["ticker"] = tab["ticker"].astype(str)

    real = _series(c["id"], tab, era)
    if real is None:
        raise SystemExit(f"no usable score cache for {c['id']}")
    print(f"candidate  {len(real)} windows", flush=True)

    nulls = []
    for nid in c["null"]:
        s = _series(nid, tab, era)
        if s is not None:
            nulls.append(s)
            print(f"  null {len(nulls):>2}  {len(s)} windows", flush=True)
    if len(nulls) < 3:
        raise SystemExit(f"only {len(nulls)} usable null draws; need >= 3")

    # Window-matched pairing. Every draw scores the same dates; intersect to be
    # certain, then the null's per-window mean is the counterfactual for that
    # window and the difference is what the column bought on that date.
    idx = real.index
    for s in nulls:
        idx = idx.intersection(s.index)
    idx = idx.sort_values()
    if len(idx) < 10:
        raise SystemExit(f"only {len(idx)} shared windows across draws")
    if len(idx) < len(real):
        print(f"\n  {len(real) - len(idx)} window(s) not present in every draw, dropped")

    nm = pd.concat([s.reindex(idx) for s in nulls], axis=1).mean(axis=1)
    diff = real.reindex(idx) - nm
    yrs = sorted(set(idx.year))

    def stat(d):
        sd = d.std(ddof=1)
        t = float(d.mean() / (sd / np.sqrt(len(d)))) if sd > 0 and len(d) > 1 else np.nan
        return float(d.mean()), t, len(d)

    g_all, t_all, n_all = stat(diff)
    print(f"\nfull sample   gap {g_all:+.5f}   t {t_all:+.2f}   "
          f"n {n_all} windows over {len(yrs)} years\n")

    print(f"{'drop year':<11}{'n dropped':>10}{'gap w/o it':>12}{'t':>8}"
          f"{'that year alone':>18}")
    rows = []
    for y in yrs:
        keep = diff[idx.year != y]
        only = diff[idx.year == y]
        if len(keep) < 5:
            continue
        g, t, n = stat(keep)
        rows.append({"year": y, "n_dropped": len(only), "gap_wo": g, "t_wo": t,
                     "gap_year": float(only.mean()), "n_kept": n})
        print(f"{y:<11}{len(only):>10}{g:>+12.5f}{t:>+8.2f}{only.mean():>+18.5f}")

    d = pd.DataFrame(rows)
    same = bool(len(set(np.sign(d["gap_wo"]))) == 1)
    min_t = float(np.abs(d["t_wo"]).min())
    worst = d.loc[d["gap_wo"].abs().idxmin()]
    hot = d.loc[d["gap_year"].abs().idxmax()]

    print(f"\nsame sign on every drop   {same}")
    print(f"min |t| across drops      {min_t:.2f}   "
          f"(full sample {abs(t_all):.2f}, dropping {int(worst['year'])})")
    print(f"largest single-year gap   {hot['gap_year']:+.5f} in {int(hot['year'])}"
          f"   ({abs(hot['gap_year']) / abs(g_all):.1f}x the full-sample gap)")

    if not same:
        print("\nFAIL -- the sign is not stable to dropping one year.")
    elif min_t < 2.0:
        print(f"\nWEAK -- sign is stable but min |t| {min_t:.2f} < 2.0. "
              f"A one-era result; the hold-out decides it.")
    else:
        print("\nPASS -- sign stable and min |t| >= 2.0 on every single-year drop.")

    out = OUT_DIR / "sweep" / f"loyo_{a.column}.csv"
    d.to_csv(out, index=False)
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
