"""
Runs concentration_monitor.py against the CONFIRMED nomination-era result
for both the current baseline (all FACTOR_SIGNS) and the asset_growth_dropped
ablation -- never checked before this. No null draws needed (concentration
is a property of the REAL picks only), so this is much cheaper than a full
backtest run: cap150, decile_volq, 40 offsets, real picks only.

Usage: python3 concentration_check_nominate.py
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
from concentration_monitor import concentration_report, print_report  # noqa: E402


def collect_picks(by_date, all_dates, compute_fn, pick_fn=C.pick_decile_volq):
    records = []
    for offset in range(40):
        rebal_dates = all_dates[offset::RB.HORIZON]
        for tp in rebal_dates:
            df_date = by_date.get(tp)
            if df_date is None:
                continue
            elig = df_date[df_date["eligible_cap150"]]
            if len(elig) < C.N_VOL_QUINTILES * 4:
                continue
            elig = elig.reset_index(drop=True)
            scored = compute_fn(elig)
            picks = pick_fn(elig, scored)
            ret_lookup = dict(zip(elig["ticker"], elig["gross_return_40"]))
            for t, w in picks:
                r = ret_lookup.get(t)
                if pd.notna(r):
                    records.append({"date": tp, "ticker": t, "weight": w, "gross_return_40": r})
    return records


def main():
    t0 = time.time()
    by_date, all_dates, spy, usmv = RB.load_data("nominate")

    print("\n=== BASELINE (confirmed, all FACTOR_SIGNS incl. asset_growth) ===")
    recs_baseline = collect_picks(by_date, all_dates, lambda g: C.compute_composite(g, neutral=False))
    rep_baseline = concentration_report(recs_baseline, group_by="year")
    print_report(rep_baseline)
    max_share_baseline = max(abs(r["top_ticker_share_of_gross"]) for r in rep_baseline.values())
    print(f"  max single-year top-ticker share: {max_share_baseline*100:.1f}%")

    print(f"\n=== asset_growth_dropped ({time.time()-t0:.0f}s so far) ===")
    recs_agd = collect_picks(
        by_date, all_dates,
        lambda g: CV.compute_composite_ablated(g, CV.ASSET_GROWTH_DROPPED_SIGNS, neutral=False))
    rep_agd = concentration_report(recs_agd, group_by="year")
    print_report(rep_agd)
    max_share_agd = max(abs(r["top_ticker_share_of_gross"]) for r in rep_agd.values())
    print(f"  max single-year top-ticker share: {max_share_agd*100:.1f}%")

    print(f"\ndone ({time.time()-t0:.0f}s total)")


if __name__ == "__main__":
    main()
