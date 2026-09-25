"""
Grade the fly cells against the deployed model, on the nomination era only.

    python3 grade_fly.py

The 2x2 is the whole experiment:

    real topology   + ordered time     the fly
    real topology   + scrambled time   does ORDER carry anything?
    rewired         + ordered time     does DROSOPHILA topology carry anything?
    rewired         + scrambled time   floor: a random operator on a bag of days

IC is the metric, not terminal value. Round 17's lesson stands: IC uses every
eligible name in every window (~2,200 x 82 = 180,000 observations) where a
portfolio result is 82 numbers dominated by which five names happened to be
held. Terminal value is reported, never ranked on.

NOMINATION ERA ONLY. The 2020-2026 hold-out has been spent twice and these are
new models; scoring them there would be exactly the search this project keeps
refusing. The score caches cover it because computing a score is not looking at
one -- this script simply does not read those windows.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from features import OUT_DIR                     # noqa: E402
from sweep import portfolio as P                 # noqa: E402
from sweep import _num                           # noqa: E402

SCORES = OUT_DIR / "sweep" / "scores"
ERA = ("2007-01-01", "2020-01-01")
CELLS = [
    ("fly (real, ordered)",      "fly_mushroom_body_T20_s0"),
    ("fly (real, SCRAMBLED)",    "fly_mushroom_body_scram_T20_s0"),
    ("fly (rewired, ordered)",   "fly_mushroom_body_shuf_T20_s0"),
    ("fly (rewired, SCRAMBLED)", "fly_mushroom_body_shuf_scram_T20_s0"),
    ("BASELINE ridge, no network", "fly_none_T20_s0"),
    ("deployed q75 (reference)",
     "price_fund_h40_q75_trd_xgb_d3e01r100_expanding_cap500k_pit_s40"),
]


def main():
    tab = pd.read_parquet(OUT_DIR / "sweep" / "outcomes.parquet")
    tab["ticker"] = tab["ticker"].astype(str)
    spy = pd.read_csv(Path(__file__).resolve().parents[2] / "scripts" /
                      "td_data_local" / "SPY.csv", parse_dates=["date"])

    rows = []
    for label, cid in CELLS:
        path = SCORES / f"{cid}.parquet"
        if not path.exists():
            print(f"  [missing] {cid}")
            continue
        sc = pd.read_parquet(path)
        prep = P.Prepared(sc, tab, 40, None)
        spy_ret = P.spy_windows(spy, np.sort(sc["timepoint"].unique()), 40)

        ics, tps = [], []
        for tp, d in prep.g.items():
            t = pd.Timestamp(tp)
            if not (pd.Timestamp(ERA[0]) <= t < pd.Timestamp(ERA[1])):
                continue
            m = np.isfinite(d["ret"]) & np.isfinite(d["score"])
            if m.sum() < 40:
                continue
            r = _num.spearman(d["score"][m], d["ret"][m])
            if np.isfinite(r):
                ics.append(r); tps.append(t)
        ics = np.asarray(ics); tps = pd.DatetimeIndex(tps)
        ic = float(ics.mean())
        tstat = float(ic / (ics.std(ddof=1) / np.sqrt(len(ics))))

        # leave-one-year-out: standing procedure since Round 14
        loyo = []
        for y in sorted(set(tps.year)):
            v = ics[np.asarray(tps.year != y)]
            loyo.append(float(v.mean() / (v.std(ddof=1) / np.sqrt(len(v)))))
        pw = P.simulate(prep, horizon=40, top_n=5, weighting="invvol",
                        bucket="volq", cost_bps=15.0)
        m = P.score_run(pw, spy_ret, 40, era=ERA)
        rows.append({"cell": label, "n_win": len(ics), "IC": ic, "t": tstat,
                     "LOYO_min_t": min(loyo, key=abs) if loyo else np.nan,
                     "same_sign": len(set(np.sign(loyo))) == 1 if loyo else False,
                     "excess_cagr": (m or {}).get("excess_cagr", np.nan) * 100,
                     "mult_ratio": (m or {}).get("mult_ratio", np.nan)})

    res = pd.DataFrame(rows)
    print("\n" + "=" * 96)
    print("NOMINATION ERA 2007-2019 -- ranked on IC, terminal value reported only")
    print("=" * 96)
    print(res.to_string(index=False, float_format=lambda v: f"{v:9.4f}"))

    def get(name, col):
        r = res[res.cell == name]
        return float(r[col].iloc[0]) if len(r) else np.nan

    print("\n--- the two contrasts this was built to measure ---")
    d_ord = get("fly (real, ordered)", "IC") - get("fly (real, SCRAMBLED)", "IC")
    d_top = get("fly (real, ordered)", "IC") - get("fly (rewired, ordered)", "IC")
    print(f"  ordered  minus scrambled (real topology) : {d_ord:+.5f} IC")
    print(f"  real     minus rewired   (ordered time)  : {d_top:+.5f} IC")
    print("\n  An IC difference is only worth reading against the sampling noise")
    print("  on IC itself, which at ~82 windows is roughly")
    a = res[res.cell.str.startswith('fly')]["IC"]
    print(f"  +/-{a.std(ddof=1):.5f} across these four cells alone.")


if __name__ == "__main__":
    main()
