"""
One-off harness cross-check, not part of the correction package's normal
reproduction path: runs the UNMODIFIED confirmed composite (all FACTOR_SIGNS,
pick_decile_volq) through correction_variants.py's own backtest loop, to
verify it reproduces run_backtest.py's REPORT_nominate.md number for
cap150_raw/decile_volq/15bp (+3.75%/yr, sd 0.37%, 40/40 positive, 10.8/13.0
years beaten) before trusting asset_growth_dropped's +4.32%/yr as a real
ablation effect rather than a cross-harness artifact.
"""
import sys
import time
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import numpy as np
import composite as C
import run_backtest as RB
import correction_variants as CV

CV.VARIANTS = {
    "baseline_harness_check": {
        "compute": lambda g: C.compute_composite(g, neutral=False),
        "pick": C.pick_decile_volq,
    },
}

OUT = Path("/Users/ggraham/pipe_dream/final/out/reset2026/harness_check_report.json")


def main():
    by_date, all_dates, spy, usmv = RB.load_data("nominate")
    per_offset = []
    t0 = time.time()
    for offset in range(40):
        rng = np.random.default_rng(1234 + offset)
        records = CV.run_offset(by_date, all_dates, offset, spy, usmv, rng)
        s = CV.summarize_offset(records, "baseline_harness_check")
        if s is not None:
            per_offset.append(s)
        print(f"offset {offset:02d} done ({time.time()-t0:.0f}s cum)", flush=True)

    vals = [o["excess_cagr_vs_spy"] for o in per_offset]
    years_won = [o["years_won"] for o in per_offset]
    n_years = [o["n_years"] for o in per_offset]
    result = {
        "n_offsets": len(vals),
        "mean_excess_cagr_vs_spy": float(np.mean(vals)),
        "std_excess_cagr_vs_spy": float(np.std(vals)),
        "min": float(np.min(vals)), "max": float(np.max(vals)),
        "n_offsets_positive": int(sum(v > 0 for v in vals)),
        "mean_years_won": float(np.mean(years_won)),
        "mean_n_years": float(np.mean(n_years)),
    }
    print(json.dumps(result, indent=2))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w") as f:
        json.dump(result, f, indent=2)


if __name__ == "__main__":
    main()
