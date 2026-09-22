"""
One-off diagnostic: how much of asset_growth_dropped's 2020 hold-out excess
(+30.72%/yr, section 6b of the corrections doc) is attributable to the
single ticker LCID, whose price series does not match its real, documented
trading history (pipeline shows $573.70 on 2021-02-22 vs. the real CCIV/
Lucid close of $64.86 that day -- ~8.85x off). Excludes LCID from the
eligible universe entirely (not a "fix" of its price data -- a clean
exclude-and-recompute, same pattern as this project's own richness-ratio
cleaning in the options work) and reports the full-2020, all-40-offset
result again for direct comparison. Descriptive only.
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
from holdout_check_asset_growth_dropped import summarize_offset_with_yearly  # noqa: E402


def main():
    t0 = time.time()
    by_date, all_dates, spy, usmv = RB.load_data("holdout")

    per_offset_with = []
    per_offset_without = []
    for offset in range(40):
        rng1 = np.random.default_rng(1234 + offset)
        rng2 = np.random.default_rng(1234 + offset)
        recs_with = CV.run_offset(by_date, all_dates, offset, spy, usmv, rng1)

        # Exclude LCID entirely from the eligible pool for this offset's run.
        by_date_ex = {d: g[g["ticker"] != "LCID"] for d, g in by_date.items()}
        recs_without = CV.run_offset(by_date_ex, all_dates, offset, spy, usmv, rng2)

        s1 = summarize_offset_with_yearly(recs_with, "asset_growth_dropped")
        s2 = summarize_offset_with_yearly(recs_without, "asset_growth_dropped")
        if s1: per_offset_with.append(s1)
        if s2: per_offset_without.append(s2)
        print(f"offset {offset:02d} done ({time.time()-t0:.0f}s cum)", flush=True)

    def yearly_2020(per_offset):
        vals = [o["yearly"].get(2020, {}).get("excess") for o in per_offset]
        vals = [v for v in vals if v is not None]
        return float(np.mean(vals)), len(vals)

    m_with, n_with = yearly_2020(per_offset_with)
    m_without, n_without = yearly_2020(per_offset_without)

    full_with = float(np.mean([o["excess_cagr_vs_spy"] for o in per_offset_with]))
    full_without = float(np.mean([o["excess_cagr_vs_spy"] for o in per_offset_without]))

    print("\n=== 2020 calendar-year excess (mean across offsets that touch 2020) ===")
    print(f"WITH LCID:    {m_with*100:+.2f}%   (n={n_with} offsets)")
    print(f"WITHOUT LCID: {m_without*100:+.2f}%   (n={n_without} offsets)")
    print(f"delta: {(m_with-m_without)*100:+.2f}pp")

    print("\n=== Full 7-year hold-out mean excess CAGR vs SPY (all 40 offsets) ===")
    print(f"WITH LCID:    {full_with*100:+.2f}%/yr")
    print(f"WITHOUT LCID: {full_without*100:+.2f}%/yr")
    print(f"delta: {(full_with-full_without)*100:+.2f}pp/yr")


if __name__ == "__main__":
    main()
