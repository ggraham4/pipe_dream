"""
WO-20 (2026-09-27): reproduce the COO's frozen-rule weights and in-era
backtest for icw9_seas (8 production factors + seas) vs icw8, on the WO-18
harness (v2 col c, cap150, 40 offsets, net 15bp, 2007-01-02..2019-12-31).
Port of the COO's /tmp/coo_ew/seas_frozen.py, repointed at THIS worktree's
final/src. IN-ERA ONLY; the weights are IN-SAMPLE (same t's). Nothing
dated >= 2020-01-01 is scored (screen_seas.load_universe asserts it).

Checks
  1. SI.fit_weights over the 8 full-era t's + seas t reproduces
     ICW.PRODUCTION_WEIGHTS_V9_SEAS to 4dp.
  2. Scorer agreement: the live scorer (ICW.compute_composite_ic_weighted on a
     one-date cross-section) == the harness scorer (SI.composite_score over
     rz_ columns) to 1e-12, NaN pattern included, on sample in-era dates.
  3. Backtest: icw8 (PRODUCTION_WEIGHTS), icw9_seas at full precision (the
     COO's run) and icw9_seas at the frozen 4dp constant (the live model).

Needs final/out/seasonality/seas_factor_v2.parquet in this worktree
(python final/src/seasonality/build_seas.py; gitignored).
Output: final/out/seasonality/wo20_frozen_backtest.json
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import screen_seas as S  # noqa: E402

V, SI, ICW = S.V, S.SI, S.ICW
OUT = S.B.OUT / "wo20_frozen_backtest.json"
POST = pd.Timestamp("2011-10-01")
SAMPLE_DATES = ["2008-03-14", "2012-07-02", "2016-11-15", "2019-12-31"]


def main():
    rep = json.loads((S.B.OUT / "seas_screen_report.json").read_text())
    seas_t = rep["ic"]["pooled"]["t"]
    assert seas_t == ICW.SEAS_T, (seas_t, ICW.SEAS_T)
    t_full = json.loads(S.ICW_REPORT.read_text())["per_factor_t"]["full"]
    w9 = SI.fit_weights({**{k: v["t"] for k, v in t_full.items()}, "seas": seas_t}, V.SIGNS9)
    w9_4dp = {k: round(v, 4) for k, v in w9.items()}
    assert w9_4dp == ICW.PRODUCTION_WEIGHTS_V9_SEAS, (w9_4dp, ICW.PRODUCTION_WEIGHTS_V9_SEAS)
    assert list(w9) == list(ICW.PRODUCTION_WEIGHTS_V9_SEAS)
    assert {k: np.sign(v) for k, v in w9.items()} == {k: np.sign(v) for k, v in ICW.SIGNS_V9_SEAS.items()}
    print("w9", w9_4dp, "== ICW.PRODUCTION_WEIGHTS_V9_SEAS", flush=True)

    U, all_dates, spy = S.load_universe()
    V.add_ranks(U, V.FC8 + ["seas"])

    # 2. scorer agreement (live scorer vs harness scorer)
    agree = {}
    for d in SAMPLE_DATES:
        d = pd.Timestamp(d)
        if d not in set(U["date"]):
            d = U.loc[U["date"] <= d, "date"].max()
        g = U[U["date"] == d]
        a = SI.composite_score(g, ICW.PRODUCTION_WEIGHTS_V9_SEAS).to_numpy(np.float64)
        b = ICW.compute_composite_ic_weighted(g.reset_index(drop=True),
                                              weights=ICW.PRODUCTION_WEIGHTS_V9_SEAS)["composite"].to_numpy(np.float64)
        same_nan = bool((np.isnan(a) == np.isnan(b)).all())
        diff = float(np.nanmax(np.abs(a - b)))
        assert same_nan and diff < 1e-12, (d, same_nan, diff)
        agree[d.date().isoformat()] = {"rows": int(len(g)), "max_abs_diff": diff, "nan_pattern_equal": same_nan,
                                       "seas_coverage": float(g["seas"].notna().mean())}
    print("scorer agreement", agree, flush=True)

    book = V.Book(U, all_dates, spy)
    out = {"w9_full_precision": w9, "w9_frozen_4dp": ICW.PRODUCTION_WEIGHTS_V9_SEAS, "seas_t": seas_t,
           "scorer_agreement": agree, "in_sample_note": "weights fit on the same full-era t's the backtest is read on"}
    for name, w in (("icw8", ICW.PRODUCTION_WEIGHTS), ("icw9_seas_full_precision", w9),
                    ("icw9_seas_frozen_4dp", ICW.PRODUCTION_WEIGHTS_V9_SEAS)):
        s = SI.composite_score(U, w).to_numpy()
        r = book.run(s)
        pk = {d: v for d, v in book.picks(s).items() if d >= POST}
        r["post2011_10"] = S.DR.backtest(pk, [d for d in all_dates if d >= POST], spy)["excess_cagr_vs_spy_mean40"]
        out[name] = r
        print(name, {k: (round(v, 6) if isinstance(v, float) else v) for k, v in r.items()}, flush=True)
    assert abs(out["icw8"]["excess_cagr_vs_spy_mean40"] - 0.028541632641009042) < 1e-9
    assert abs(out["icw9_seas_full_precision"]["excess_cagr_vs_spy_mean40"] - 0.03487104914180321) < 1e-9
    d4 = out["icw9_seas_frozen_4dp"]["excess_cagr_vs_spy_mean40"] - 0.03487104914180321
    out["frozen_4dp_minus_coo_full_precision"] = d4
    print(f"frozen 4dp vs COO full precision: {d4:+.2e}", flush=True)
    OUT.write_text(json.dumps(out, indent=1, default=float))
    print(f"-> {OUT}")


if __name__ == "__main__":
    main()
