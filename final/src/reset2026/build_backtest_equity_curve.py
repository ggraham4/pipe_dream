"""
Full-history equity curve for the app's Theoretical Model tab -- nomination
(2007-2019) + hold-out (2020-2026) stitched into one continuous compounding
series, IC-weighted composite, decile_volq, offset 0, 15bp turnover cost.

NOT a new hold-out spend: every number here reproduces a cell already
computed and reported (ic_weighted_composite.py's nomination-era validation,
holdout_check_ic_weighted.py's hold-out run) -- this script only re-runs the
same single-offset simulation to get a plottable date-indexed series instead
of a single summary number, and stitches the two eras end to end so the
2019/2020 boundary is visible on one chart. Per Gabe's framing (2026-09-22):
plotting an already-reported result is not a new spend.

Usage: python3 build_backtest_equity_curve.py
Output: out/reset2026/backtest_equity_curve.csv
    columns: date, era, composite_gross, composite_net, spy, f_new,
             composite_cum, composite_net_cum, spy_cum
"""
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import composite as C            # noqa: E402
import run_backtest as RB         # noqa: E402
import ic_weighted_composite as ICW  # noqa: E402

OUT = Path("/Users/ggraham/pipe_dream/final/out/reset2026/backtest_equity_curve.csv")
COST_BPS = 15.0
OFFSET = 0


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def run_era(era):
    by_date, all_dates, spy, usmv = RB.load_data(era)
    rebal_dates = all_dates[OFFSET::RB.HORIZON]
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
        records.append({"date": tp, "era": era, "gross": gross, "f_new": f_new,
                         "spy": spy.get(tp, np.nan)})
    return records


def main():
    t0 = time.time()
    all_records = []
    for era in ("nominate", "holdout"):
        recs = run_era(era)
        log(f"{era}: {len(recs)} windows")
        all_records.extend(recs)

    df = pd.DataFrame(all_records).sort_values("date").reset_index(drop=True)
    net = RB.turnover_net_return(df.to_dict("records"), COST_BPS)
    df["composite_gross"] = df["gross"]
    df["composite_net"] = net
    ok = df["spy"].notna()
    df = df[ok].reset_index(drop=True)

    df["composite_cum"] = (1.0 + df["composite_gross"]).cumprod()
    df["composite_net_cum"] = (1.0 + df["composite_net"]).cumprod()
    df["spy_cum"] = (1.0 + df["spy"]).cumprod()
    df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")

    out_cols = ["date", "era", "composite_gross", "composite_net", "spy", "f_new",
                "composite_cum", "composite_net_cum", "spy_cum"]
    df[out_cols].to_csv(OUT, index=False)

    term_composite = df["composite_net_cum"].iloc[-1]
    term_spy = df["spy_cum"].iloc[-1]
    log(f"terminal (net of {COST_BPS:.0f}bp): composite {term_composite:.2f}x vs SPY {term_spy:.2f}x, "
        f"{len(df)} windows, {(pd.to_datetime(df['date']).iloc[0]).date()} -> "
        f"{(pd.to_datetime(df['date']).iloc[-1]).date()}")
    log(f"-> {OUT} ({time.time()-t0:.0f}s total)")


if __name__ == "__main__":
    main()
