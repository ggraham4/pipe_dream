"""
WO-35 descriptive add-on to the Exp B screen (nominate era 2008-01..2018-12 ONLY;
never reads 2019+). It changes no decision: admission is taken from
expB_screen.json as written by run_expB.py. This file only reports the three
breakdowns the WO-35 results doc asks for, from the same rows and helpers:

  - NW lag-2 t next to the binding lag-39 t (labelled descriptive)
  - grid-offset sign flips: mean IC on each of the 2 interleaved date offsets
  - per-year mean IC and the largest single-year share of the summed IC

    /opt/anaconda3/envs/pipe_dream/bin/python final/src/options_wo25/expB_descriptive.py
"""
from __future__ import annotations

import json

import numpy as np

import run_expB as R

ET = R.ET


def describe(s, sign):
    """s: per-date IC series. Sign-aligned so a positive number = the pre-registered direction."""
    a = s * sign
    offs = [float(a.iloc[o::R.N_OFFSETS].mean()) for o in range(R.N_OFFSETS)]
    full = float(a.mean())
    by_year_sum = a.groupby(a.index.year).sum()
    by_year_mean = a.groupby(a.index.year).mean()
    tot = float(a.sum())
    share = (by_year_sum / tot) if tot != 0 else by_year_sum * np.nan
    top = share.idxmax()
    return {"mean_ic_sign_aligned": full,
            "nw39": ET.newey_west_mean_t(s.to_numpy(), lag=39), "nw2_DESCRIPTIVE": ET.newey_west_mean_t(s.to_numpy(), lag=2),
            "per_offset_mean_ic_sign_aligned": offs,
            "offset_sign_flips": int(sum(np.sign(x) != np.sign(full) for x in offs)),
            "by_year_mean_ic_sign_aligned": {int(y): float(v) for y, v in by_year_mean.items()},
            "years_against_sign": int((by_year_mean < 0).sum()), "n_years": int(len(by_year_mean)),
            "largest_single_year_share": {"year": int(top), "share_of_summed_ic": float(share.max())}}


def main():
    m, spy, cov = R.load(*R.NOMINATE_B, R.FEATS)
    assert m.date.max() <= R.NOMINATE_B[1]
    neu = ET.neutralise(m, list(R.OPTION_SIGNS) + list(R.BASE_SIGNS))
    scr = json.loads((R.OUT / "expB_screen.json").read_text())
    out = {"window": [str(m.date.min().date()), str(m.date.max().date())], "n_dates": int(m.date.nunique()), "factors": {}}
    for c, sgn in R.OPTION_SIGNS.items():
        comp = scr["factors"][c]["companion"]
        d_off = [p - b for p, b in zip(comp["composite_plus"]["per_offset"], comp["composite"]["per_offset"])]
        out["factors"][c] = {"sign": sgn,
                             "raw": describe(ET.per_date_ic(m, c), sgn),
                             "sector_neutral": describe(ET.per_date_ic(neu, c), sgn),
                             "companion_plus_minus_base_per_offset": d_off,
                             "companion_offset_sign_flips": int(len({np.sign(x) for x in d_off}) > 1)}
    p = R.OUT / "expB_screen_descriptive.json"
    p.write_text(json.dumps(out, indent=2, default=float))
    for c, v in out["factors"].items():
        n = v["sector_neutral"]
        print(c, "neutral IC(sign-aligned) %.4f" % n["mean_ic_sign_aligned"], "t39 %.2f" % n["nw39"]["t"], "t2 %.2f" % n["nw2_DESCRIPTIVE"]["t"],
              "| raw t39 %.2f t2 %.2f" % (v["raw"]["nw39"]["t"], v["raw"]["nw2_DESCRIPTIVE"]["t"]),
              "| offs", [round(x, 4) for x in n["per_offset_mean_ic_sign_aligned"]], "flips", n["offset_sign_flips"],
              "| top year", n["largest_single_year_share"], "yrs against", n["years_against_sign"], "/", n["n_years"],
              "| comp d/off", [round(x, 4) for x in v["companion_plus_minus_base_per_offset"]])
    print("wrote", p)


if __name__ == "__main__":
    main()
