"""
Second hold-out spend for this pipeline, explicit, at Gabe's request -- see
PREREGISTRATION.md's "Second hold-out spend (2026-09-22, part 3)" section,
written before this ran. Scored ONLY `asset_growth_dropped` (never the
other three correction variants) to keep this one requested number rather
than a four-cell hold-out search. Descriptive, not a confirmation --
`asset_growth_dropped` remains an unadopted recommendation regardless of
what this shows.

Reports the same leave-one-year-out check the baseline's own hold-out
result was held to (main write-up section 3.2 / PREREGISTRATION.md's
hold-out section), not just an aggregate.

Usage: python3 holdout_check_asset_growth_dropped.py
Output: out/reset2026/holdout_asset_growth_dropped_report.json
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
import correction_variants as CV  # noqa: E402

OUT = Path("/Users/ggraham/pipe_dream/final/out/reset2026/holdout_asset_growth_dropped_report.json")
NULL_DRAWS = 50
COST_BPS = 15.0

CV.VARIANTS = {
    "asset_growth_dropped": {
        "compute": lambda g: CV.compute_composite_ablated(g, CV.ASSET_GROWTH_DROPPED_SIGNS, neutral=False),
        "pick": C.pick_decile_volq,
    },
}
CV.NULL_DRAWS = NULL_DRAWS


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def summarize_offset_with_yearly(records, method, cost_bps=COST_BPS):
    df = pd.DataFrame(records)
    sub = df[(df["method"] == method) & (df["draw"] == "real")].sort_values("date")
    if sub.empty:
        return None
    net = RB.turnover_net_return(sub.to_dict("records"), cost_bps)
    spy_arr = sub["spy"].to_numpy(np.float64)
    spy_ok = np.isfinite(spy_arr)
    excess = net[spy_ok] - spy_arr[spy_ok]
    dates = pd.to_datetime(sub["date"]).to_numpy()[spy_ok]
    years = pd.to_datetime(sub["date"]).dt.year.to_numpy()

    yearly = {}
    for y in np.unique(years):
        m = (years == y) & spy_ok
        if not m.any():
            continue
        port_y = float(np.prod(1 + net[m]) - 1)
        spy_y = float(np.prod(1 + spy_arr[m]) - 1)
        yearly[int(y)] = {"port": port_y, "spy": spy_y, "excess": port_y - spy_y}

    ann_factor = 252.0 / RB.HORIZON
    excess_cagr = float(np.mean(excess) * ann_factor) if len(excess) else float("nan")

    null_sub = df[(df["method"] == method) & (df["draw"] != "real")]
    null_pct = None
    if not null_sub.empty:
        null_by_draw = null_sub.groupby("draw").apply(
            lambda g: np.mean(RB.turnover_net_return(g.sort_values("date").to_dict("records"), cost_bps)
                               - g.sort_values("date")["spy"].to_numpy(np.float64)))
        null_pct = float((null_by_draw.to_numpy() < float(np.mean(excess))).mean())

    return {
        "n_windows": int(len(excess)),
        "excess_cagr_vs_spy": excess_cagr,
        "yearly": yearly,
        "null_percentile_of_real": null_pct,
        "window_dates": [str(pd.Timestamp(d).date()) for d in dates],
    }


def main():
    t0 = time.time()
    by_date, all_dates, spy, usmv = RB.load_data("holdout")
    per_offset = []
    for offset in range(40):
        rng = np.random.default_rng(1234 + offset)
        records = CV.run_offset(by_date, all_dates, offset, spy, usmv, rng)
        s = summarize_offset_with_yearly(records, "asset_growth_dropped")
        if s is not None:
            per_offset.append(s)
        log(f"offset {offset:02d} done ({time.time()-t0:.0f}s cum)")

    vals = [o["excess_cagr_vs_spy"] for o in per_offset if np.isfinite(o["excess_cagr_vs_spy"])]
    pcts = [o["null_percentile_of_real"] for o in per_offset if o["null_percentile_of_real"] is not None]

    # Pool every (offset, window) excess by calendar year -- the LOYO check.
    # Each offset contributes its own window(s) per year; pooling across
    # offsets gives a much larger per-year sample than any single offset's
    # ~1 window/year in a 7-year hold-out.
    by_year = {}
    for o in per_offset:
        for y, v in o["yearly"].items():
            by_year.setdefault(y, []).append(v["excess"])
    yearly_summary = {y: {"mean_excess": float(np.mean(vs)), "n_windows": len(vs)}
                      for y, vs in sorted(by_year.items())}

    full_mean = float(np.mean(vals)) if vals else float("nan")
    loyo = {}
    for y in yearly_summary:
        remaining = [v for o in per_offset for yy, v in o["yearly"].items() if yy != y]
        loyo[y] = float(np.mean([v["excess"] for v in remaining])) if remaining else None

    result = {
        "generated": pd.Timestamp.now().isoformat(),
        "era": "holdout_2020_2026",
        "variant": "asset_growth_dropped",
        "n_offsets": len(vals),
        "mean_excess_cagr_vs_spy": full_mean,
        "std_excess_cagr_vs_spy": float(np.std(vals)) if vals else None,
        "min": float(np.min(vals)) if vals else None,
        "max": float(np.max(vals)) if vals else None,
        "n_offsets_positive": int(sum(v > 0 for v in vals)) if vals else None,
        "mean_null_percentile": float(np.mean(pcts)) if pcts else None,
        "yearly_pooled_across_offsets": yearly_summary,
        "years_positive": sum(1 for y in yearly_summary if yearly_summary[y]["mean_excess"] > 0),
        "n_years": len(yearly_summary),
        "leave_one_year_out_mean_excess_per_window": loyo,
        "note": ("Second hold-out spend for this pipeline, explicit, at Gabe's request. "
                 "asset_growth_dropped only -- descriptive, not a confirmation. "
                 "Window count per offset is small (~1/offset over 7 years, per "
                 "PREREGISTRATION.md's caveat) -- sd across offsets here is not "
                 "comparable to the nomination era's 82-window-per-offset sd."),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w") as f:
        json.dump(result, f, indent=2, default=str)
    log(f"wrote {OUT} ({time.time()-t0:.0f}s total)")
    print(json.dumps({k: v for k, v in result.items() if k != "leave_one_year_out_mean_excess_per_window"},
                      indent=2, default=str))


if __name__ == "__main__":
    main()
