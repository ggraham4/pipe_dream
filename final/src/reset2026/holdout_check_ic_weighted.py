"""
Third hold-out spend for this pipeline, explicit, at Gabe's request -- see
PREREGISTRATION.md's "Turnover realism + third hold-out spend (2026-09-22)"
section, written before this ran. Purpose stated in advance: data-quality/
generalization robustness for the IC-weighted composite (frozen weights,
never re-fit to this data), NOT discovery. LOYO applied immediately, in
the same breath as the headline, not only if the headline looks good.

Usage: python3 holdout_check_ic_weighted.py
"""
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import composite as C            # noqa: E402
import run_backtest as RB         # noqa: E402
import ic_weighted_composite as ICW  # noqa: E402

OUT = Path("/Users/ggraham/pipe_dream/final/out/reset2026/holdout_ic_weighted_report.json")
COST_BPS = 15.0


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def run_offset(by_date, all_dates, offset, spy):
    rebal_dates = all_dates[offset::RB.HORIZON]
    prev = set()
    records = []
    for tp in rebal_dates:
        df_date = by_date.get(tp)
        if df_date is None:
            continue
        elig = df_date[df_date["eligible_cap150"]]
        if len(elig) < C.N_VOL_QUINTILES * 4:
            continue
        elig = elig.reset_index(drop=True)
        scored = ICW.compute_composite_ic_weighted(elig)
        picks = C.pick_decile_volq(elig, scored)
        ret_lookup = dict(zip(elig["ticker"], elig["gross_return_40"]))
        picks = [(t, w) for t, w in picks if pd.notna(ret_lookup.get(t))]
        if not picks:
            continue
        wsum = sum(w for _, w in picks)
        gross = sum((w / wsum) * (1.0 + ret_lookup[t]) for t, w in picks) - 1.0
        cur = {t for t, _ in picks}
        f_new = sum(1 for t in cur if t not in prev) / len(cur)
        prev = cur
        records.append({"date": tp, "gross": gross, "f_new": f_new, "spy": spy.get(tp, np.nan)})
    return records


def main():
    t0 = time.time()
    by_date, all_dates, spy, usmv = RB.load_data("holdout")
    per_offset_excess = []
    yearly_by_offset = []
    for offset in range(40):
        recs = run_offset(by_date, all_dates, offset, spy)
        df = pd.DataFrame(recs).sort_values("date")
        if df.empty:
            continue
        net = RB.turnover_net_return(df.to_dict("records"), COST_BPS)
        spy_arr = df["spy"].to_numpy(np.float64)
        ok = np.isfinite(spy_arr)
        excess = net[ok] - spy_arr[ok]
        ann_factor = 252.0 / RB.HORIZON
        per_offset_excess.append(float(np.mean(excess) * ann_factor))
        years = pd.to_datetime(df["date"]).dt.year.to_numpy()[ok]
        yearly = {}
        for y in np.unique(years):
            m = years == y
            yearly[int(y)] = float(np.prod(1 + net[ok][m]) - np.prod(1 + spy_arr[ok][m]))
        yearly_by_offset.append(yearly)
        if offset % 10 == 0:
            log(f"offset {offset:02d} done ({time.time()-t0:.0f}s)")

    mean_excess = float(np.mean(per_offset_excess))
    n_pos = int(sum(1 for v in per_offset_excess if v > 0))

    by_year = {}
    for yb in yearly_by_offset:
        for y, v in yb.items():
            by_year.setdefault(y, []).append(v)
    yearly_summary = {y: float(np.mean(vs)) for y, vs in sorted(by_year.items())}

    loyo = {}
    for y in yearly_summary:
        remaining = [v for yb in yearly_by_offset for yy, v in yb.items() if yy != y]
        loyo[y] = float(np.mean(remaining)) if remaining else None

    log(f"\nmean excess CAGR vs SPY (40 offsets): {mean_excess*100:+.2f}%/yr, {n_pos}/40 positive")
    log("yearly (pooled across offsets):")
    for y, v in yearly_summary.items():
        log(f"  {y}: {v*100:+.2f}%")
    log("leave-one-year-out (mean excess/window dropping each year):")
    for y, v in loyo.items():
        log(f"  drop {y}: {v*100:+.2f}%")

    report = {
        "mean_excess_cagr_vs_spy": mean_excess, "n_offsets_positive": n_pos,
        "yearly_pooled": yearly_summary, "leave_one_year_out": loyo,
        "note": "Third hold-out spend, IC-weighted composite, frozen weights not re-fit here. "
                "Purpose: data-quality/generalization robustness, not discovery.",
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w") as f:
        json.dump(report, f, indent=2, default=str)
    log(f"\nwrote {OUT} ({time.time()-t0:.0f}s total)")


if __name__ == "__main__":
    main()
