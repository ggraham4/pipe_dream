"""
The missing control flagged in `2026-09-22-composite-model-corrections.md`
section 2: `exclude_bottom_decile` (hold ~90% of the eligible universe,
excluding only the bottom composite-score decile within each vol quintile)
beat its own matched null 40/40 offsets, but nobody checked it against
"hold the WHOLE eligible universe, zero score-based exclusion at all" --
same vol-quintile bucketing, same inverse-vol weighting, just no score
input whatsoever. If that no-exclusion control performs similarly,
`exclude_bottom_decile`'s edge is mostly construction/universe beta, not
the score identifying a bad decile to avoid.

No score computation, no null draws needed -- there is nothing to shuffle
when nothing is being selected by score. Nomination era only, cap150,
15bp cost, all 40 offsets, same turnover-cost/CAGR machinery as every
other variant in this package.

Usage: python3 no_exclusion_control.py
"""
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import composite as C            # noqa: E402
import run_backtest as RB         # noqa: E402
import correction_variants as CV  # noqa: E402


def pick_full_universe_volq(df_date, scored=None, book_frac=None):
    """Every eligible name, inverse-vol weighted, vol-quintile bucketing
    kept only so the weighting scheme matches decile_volq/exclude_bottom_
    decile exactly -- no score input, no exclusion, book_frac unused
    (kept for call-signature compatibility with the other pick_* fns)."""
    vol = df_date["volatility_60"].to_numpy(np.float64)
    valid = np.isfinite(vol)
    if valid.sum() < C.N_VOL_QUINTILES * 4:
        return []
    idx = np.flatnonzero(valid)
    vol_v = vol[idx]
    tick_v = df_date["ticker"].to_numpy()[idx]
    inv_vol = 1.0 / np.maximum(vol_v, 1e-4)
    w = inv_vol / inv_vol.sum()
    return [(t, float(wi)) for t, wi in zip(tick_v, w)]


def main():
    t0 = time.time()
    by_date, all_dates, spy, usmv = RB.load_data("nominate")

    records = []
    for offset in range(40):
        rebal_dates = all_dates[offset::RB.HORIZON]
        prev_picks = set()
        for tp in rebal_dates:
            df_date = by_date.get(tp)
            if df_date is None:
                continue
            elig = df_date[df_date["eligible_cap150"]]
            if len(elig) < C.N_VOL_QUINTILES * 4:
                continue
            elig = elig.reset_index(drop=True)
            picks = pick_full_universe_volq(elig)
            ret_lookup = dict(zip(elig["ticker"], elig["gross_return_40"]))
            picks = [(t, w) for t, w in picks if pd.notna(ret_lookup.get(t))]
            if not picks:
                continue
            wsum = sum(w for _, w in picks)
            gross = sum((w / wsum) * (1.0 + ret_lookup[t]) for t, w in picks) - 1.0
            cur_set = {t for t, _ in picks}
            f_new = sum(1 for t in cur_set if t not in prev_picks) / len(cur_set)
            prev_picks = cur_set
            records.append({"date": tp, "method": "no_exclusion", "draw": "real",
                             "gross": gross, "f_new": f_new, "n_picks": len(picks),
                             "spy": spy.get(tp, np.nan), "usmv": usmv.get(tp, np.nan)})
        if offset % 10 == 0:
            print(f"offset {offset:02d} done ({time.time()-t0:.0f}s)", flush=True)

    df = pd.DataFrame(records)

    # Regroup per offset using the same date partition used to generate records
    df["offset"] = -1
    for offset in range(40):
        rebal_dates = set(all_dates[offset::RB.HORIZON])
        df.loc[df["date"].isin(rebal_dates), "offset"] = offset

    vals = []
    years_won_list = []
    n_years_list = []
    for offset, g in df.groupby("offset"):
        g = g.sort_values("date")
        net = RB.turnover_net_return(g.to_dict("records"), 15.0)
        spy_arr = g["spy"].to_numpy(np.float64)
        ok = np.isfinite(spy_arr)
        excess = net[ok] - spy_arr[ok]
        ann_factor = 252.0 / RB.HORIZON
        vals.append(float(np.mean(excess) * ann_factor))
        years = pd.to_datetime(g["date"]).dt.year.to_numpy()[ok]
        yearly = {}
        for y in np.unique(years):
            m = years == y
            yearly[y] = float(np.prod(1 + net[ok][m]) - np.prod(1 + spy_arr[ok][m]))
        years_won_list.append(sum(1 for v in yearly.values() if v > 0))
        n_years_list.append(len(yearly))

    print(f"\n=== no_exclusion control (cap150, nomination era, 15bp, 40 offsets) ===")
    print(f"mean excess CAGR vs SPY: {np.mean(vals)*100:+.2f}%/yr")
    print(f"sd across offsets: {np.std(vals)*100:.2f}%")
    print(f"range: [{np.min(vals)*100:+.2f}%, {np.max(vals)*100:+.2f}%]")
    print(f"offsets positive: {sum(1 for v in vals if v > 0)}/40")
    print(f"mean years won: {np.mean(years_won_list):.1f}/{np.mean(n_years_list):.1f}")
    print(f"\ndone ({time.time()-t0:.0f}s total)")


if __name__ == "__main__":
    main()
