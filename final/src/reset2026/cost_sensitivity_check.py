"""One-off follow-up: compare baseline vs. buffered turnover at 15bp and
50bp cost, same offset-0 simulation as turnover_realism.py's Part 2, to
make the "trading costs will be less of a concern" comparison concrete."""
import sys
import pandas as pd
import numpy as np

sys.path.insert(0, ".")
import composite as C
import run_backtest as RB
import ic_weighted_composite as ICW
import turnover_realism as TR


def main():
    by_date, all_dates, spy, usmv = RB.load_data("nominate")
    held = set()
    recs_buffered, recs_baseline = [], []
    prev_baseline = set()
    for tp in all_dates[0::RB.HORIZON]:
        df_date = by_date.get(tp)
        if df_date is None:
            continue
        elig = df_date[df_date["eligible_cap150"]]
        if len(elig) < C.N_VOL_QUINTILES * 4:
            continue
        elig = elig.reset_index(drop=True)
        scored = ICW.compute_composite_ic_weighted(elig)
        ret_lookup = dict(zip(elig["ticker"], elig["gross_return_40"]))

        picks_w = TR.pick_buffered(elig, scored, held)
        picks_w = {t: w for t, w in picks_w.items() if pd.notna(ret_lookup.get(t))}
        if picks_w:
            wsum = sum(picks_w.values())
            gross = sum((w / wsum) * (1.0 + ret_lookup[t]) for t, w in picks_w.items()) - 1.0
            cur = set(picks_w)
            f_new = sum(1 for t in cur if t not in held) / len(cur)
            held = cur
            recs_buffered.append({"date": tp, "gross": gross, "f_new": f_new, "spy": spy.get(tp, np.nan)})

        picks_b = C.pick_decile_volq(elig, scored)
        picks_b = [(t, w) for t, w in picks_b if pd.notna(ret_lookup.get(t))]
        if picks_b:
            wsum_b = sum(w for _, w in picks_b)
            gross_b = sum((w / wsum_b) * (1.0 + ret_lookup[t]) for t, w in picks_b) - 1.0
            cur_b = {t for t, _ in picks_b}
            f_new_b = sum(1 for t in cur_b if t not in prev_baseline) / len(cur_b)
            prev_baseline = cur_b
            recs_baseline.append({"date": tp, "gross": gross_b, "f_new": f_new_b, "spy": spy.get(tp, np.nan)})

    for cost in [15.0, 50.0]:
        sb = TR.terminal_wealth_and_excess(recs_baseline, cost_bps=cost)
        su = TR.terminal_wealth_and_excess(recs_buffered, cost_bps=cost)
        print(f"cost={cost}bp  BASELINE ann_excess={sb['annualized_excess_vs_spy']*100:+.2f}%  |  "
              f"BUFFERED ann_excess={su['annualized_excess_vs_spy']*100:+.2f}%")


if __name__ == "__main__":
    main()
