"""
Test the thing IC cannot see: is the TOP of the score distribution better when
the input arrives in order?

    python3 tail_fly.py

WHY THIS EXISTS. grade_fly.py ranks on full-cross-section Spearman IC, which
is the right default -- it uses every eligible name in every window and is
therefore far better powered than a top-5 terminal value. But it is an average
over ~2,200 names, and the portfolio only ever holds the extreme tail. Two
cells can carry identical IC and quite different tails, and the tail is the
only part that is traded.

The four fly cells showed exactly that shape: ordered and scrambled differ by
0.0006 in IC (noise) and by ~10 percentage points a year in terminal value,
with the sign replicating across two independent topologies. Either the tail is
genuinely better under ordered input, or 78 top-5 windows produced the same
coin flip twice. This measures it at proper power.

THREE STATISTICS, INCREASING POWER, DECREASING RELEVANCE:

  top5_excess    mean return of the 5 held names minus the universe mean.
                 What is actually traded. 78 observations, very noisy.
  decile_excess  same for the top 10% by score (~220 names). Still the tail,
                 ~44x the names, so far better powered.
  ic             full cross-section, for reference.

Ordered vs scrambled is compared PAIRED BY WINDOW. The two runs see the same
names on the same dates with the same features -- only the within-window order
of the daily inputs differs -- so pairing removes essentially all the
market-wide variance and the difference is attributable to order alone.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from features import OUT_DIR                     # noqa: E402
from sweep import portfolio as P                 # noqa: E402

SCORES = OUT_DIR / "sweep" / "scores"
ERA = ("2007-01-01", "2020-01-01")
CELLS = {
    "real/ordered":      "fly_mushroom_body_T20_s0",
    "real/scrambled":    "fly_mushroom_body_scram_T20_s0",
    "rewired/ordered":   "fly_mushroom_body_shuf_T20_s0",
    "rewired/scrambled": "fly_mushroom_body_shuf_scram_T20_s0",
    "baseline/no-net":   "fly_none_T20_s0",
    "deployed q75":      "price_fund_h40_q75_trd_xgb_d3e01r100_expanding_cap500k_pit_s40",
}


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
        k = max(1, int(0.10 * len(sco)))
        top = np.argpartition(-sco, k - 1)[:k]
        idx5 = P._pick_idx(d, 5, "volq")
        ok5 = d["tradable"][idx5] & np.isfinite(d["ret"][idx5])
        idx5 = idx5[ok5]
        rows.append({
            "tp": t,
            "top5_excess": float(d["ret"][idx5].mean()) - uni if len(idx5) else np.nan,
            "decile_excess": float(ret[top].mean()) - uni,
            "n_decile": k,
        })
    return pd.DataFrame(rows).set_index("tp")


def tstat(v):
    v = np.asarray(v, dtype=np.float64)
    v = v[np.isfinite(v)]
    if len(v) < 3 or v.std(ddof=1) == 0:
        return np.nan, np.nan
    return float(v.mean()), float(v.mean() / (v.std(ddof=1) / np.sqrt(len(v))))


def main():
    tab = pd.read_parquet(OUT_DIR / "sweep" / "outcomes.parquet")
    tab["ticker"] = tab["ticker"].astype(str)
    per = {}
    for name, cid in CELLS.items():
        if not (SCORES / f"{cid}.parquet").exists():
            print(f"  [missing] {name}")
            continue
        per[name] = per_window(cid, tab)

    print("\n" + "=" * 86)
    print("TAIL BEHAVIOUR, nomination era 2007-2019 (excess over the universe mean)")
    print("=" * 86)
    print(f"{'cell':<20}{'n':>4}{'top5 pp':>10}{'t':>7}{'decile pp':>12}{'t':>7}"
          f"{'decile n':>10}")
    for name, d in per.items():
        m5, t5 = tstat(d["top5_excess"])
        md, td = tstat(d["decile_excess"])
        print(f"{name:<20}{len(d):>4}{m5*100:>10.2f}{t5:>7.2f}"
              f"{md*100:>12.3f}{td:>7.2f}{int(d['n_decile'].median()):>10}")

    print("\n" + "=" * 86)
    print("ORDERED minus SCRAMBLED, paired by window  (the question)")
    print("=" * 86)
    for topo, a, b in (("real topology", "real/ordered", "real/scrambled"),
                       ("rewired", "rewired/ordered", "rewired/scrambled")):
        if a not in per or b not in per:
            continue
        j = per[a].join(per[b], lsuffix="_o", rsuffix="_s", how="inner")
        for stat in ("top5_excess", "decile_excess"):
            m, t = tstat(j[f"{stat}_o"] - j[f"{stat}_s"])
            wins = float((j[f"{stat}_o"] > j[f"{stat}_s"]).mean())
            print(f"  {topo:<16}{stat:<16}{m*100:>+8.3f} pp/window   "
                  f"t {t:>+5.2f}   ordered ahead in {wins:.0%} of windows")

    print("\n  The decile statistic is the one to read. It is the same tail the")
    print("  portfolio draws from, at ~44x the names, so it is the only place a")
    print("  real 10-point-a-year effect could hide from a null IC and still be")
    print("  visible. If decile_excess shows nothing, the terminal-value split is")
    print("  78 windows of five names behaving like 78 windows of five names.")


if __name__ == "__main__":
    main()
