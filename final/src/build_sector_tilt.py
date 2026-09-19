"""
Realised industry tilt of the deployed model, window by window.

    python3 build_sector_tilt.py

Writes out/sector_tilt_history.json for the app's Sector Bets tab.

Today's allocation on its own cannot tell you whether a 43-point healthcare
overweight is what this model always does or something unusual about this
week. That question needs the history, and the history is cheap: the score
cache already holds every pick the model would have made at every rebalance
date since 2007.

For each window: reconstruct the top-5 volq/invvol selection, label each pick
at each taxonomy level, and compute ACTIVE weight against the equal-weighted
eligible universe on that same date. Then summarise across windows.

Two things reported per group, and the second matters more:

    mean_active   average overweight across all windows. A persistent tilt.
    frequency     share of windows with ANY position in the group. A group can
                  carry a large mean_active from three enormous bets, which is
                  a different animal from a standing allocation, and the app
                  should not show one as the other.

ERA. All windows 2007-2026 are included. This is descriptive -- it reports what
the model did, it does not select anything -- so the hold-out rule does not
bind. The output is split by era anyway so nobody has to take that on trust.
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from features import OUT_DIR                          # noqa: E402
from sweep import portfolio as P                      # noqa: E402
from sweep import taxonomy as T                       # noqa: E402
from sweep.factors import _base_ticker                # noqa: E402

SCORES = OUT_DIR / "sweep" / "scores"
CELL = "price_fund_h40_q75_trd_xgb_d3e01r100_expanding_cap500k_pit_s40"
DST = OUT_DIR / "sector_tilt_history.json"
LEVELS = ["sector", "famaindustry", "industry", "sicindustry"]
ERAS = {"nominate": ("2007-01-01", "2020-01-01"),
        "holdout": ("2020-01-01", "2027-01-01")}


def main():
    tab = pd.read_parquet(OUT_DIR / "sweep" / "outcomes.parquet")
    tab["ticker"] = tab["ticker"].astype(str)
    sc = pd.read_parquet(SCORES / f"{CELL}.parquet")
    prep = P.Prepared(sc, tab, 40, None)
    from continuous_walkforward_pit import load_pit_universe
    pit = load_pit_universe()
    maps = {lvl: T.load(lvl) for lvl in LEVELS}
    print(f"{len(prep.tps)} windows, {len(LEVELS)} levels")

    per_window = []
    for tp in prep.tps:
        d = prep.g.get(np.datetime64(tp))
        if d is None or not len(d["score"]):
            continue
        idx = P._pick_idx(d, 5, "volq")
        ok = d["tradable"][idx] & np.isfinite(d["ret"][idx])
        idx = idx[ok]
        if not len(idx):
            continue
        w = P._weights(d, idx, "invvol") * 100.0
        picks = [str(t) for t in d["ticker"][idx]]
        uni = pit.get(str(pd.Timestamp(tp).date()), set())
        row = {"timepoint": str(pd.Timestamp(tp).date()), "picks": picks,
               "levels": {}}
        for lvl, m in maps.items():
            pl = [m.get(_base_ticker(t), "(unclassified)") for t in picks]
            port = pd.Series(w).groupby(pl).sum()
            if uni:
                ul = pd.Series([m.get(_base_ticker(t), "(unclassified)")
                                for t in uni])
                uw = ul.value_counts(normalize=True) * 100.0
            else:
                uw = pd.Series(dtype=float)
            act = port.subtract(uw.reindex(port.index).fillna(0.0))
            row["levels"][lvl] = {str(k): float(v) for k, v in act.items()}
        per_window.append(row)
    print(f"  reconstructed {len(per_window)} windows of picks")

    out = {"cell_id": CELL, "n_windows": len(per_window), "levels": {}}
    for lvl in LEVELS:
        out["levels"][lvl] = {}
        for era, (lo, hi) in ERAS.items():
            rows = [r for r in per_window if lo <= r["timepoint"] < hi]
            agg, freq = {}, {}
            for r in rows:
                for g, v in r["levels"][lvl].items():
                    agg.setdefault(g, []).append(v)
                    freq[g] = freq.get(g, 0) + 1
            summ = []
            for g, vals in agg.items():
                # mean over ALL windows, not just windows holding the group:
                # a group held once at +40pp has a mean_active of +40/n, which
                # is the honest description of a standing allocation. The
                # frequency column separates "always a bit" from "rarely, a lot".
                summ.append({"group": g,
                             "mean_active": float(np.sum(vals) / max(len(rows), 1)),
                             "frequency": freq[g] / max(len(rows), 1),
                             "max_active": float(np.max(vals)),
                             "n_windows_held": freq[g]})
            summ.sort(key=lambda r: -r["mean_active"])
            out["levels"][lvl][era] = {"n_windows": len(rows), "groups": summ}
    out["per_window"] = per_window
    DST.write_text(json.dumps(out, indent=1))

    print(f"\ntop standing tilts, nomination era (2007-2019):")
    for lvl in LEVELS:
        g = out["levels"][lvl]["nominate"]["groups"][:3]
        print(f"  {lvl}:")
        for r in g:
            print(f"    {r['group'][:44]:<46}{r['mean_active']:>+7.2f}pp mean, "
                  f"held in {r['frequency']:.0%} of windows")
    print(f"\nwritten {DST} ({DST.stat().st_size/1e3:.0f}KB)")


if __name__ == "__main__":
    main()
