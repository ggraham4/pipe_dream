"""
Standing safeguard: flags when a single ticker dominates a backtest period's
return, regardless of whether the cause turns out to be a real extreme event
(GME, 2020 -- checked, genuine) or a data defect (the LCID false alarm,
2026-09-22 -- checked, turned out to be a real, SEC-filed reverse split, not
a bug either, see `models/2026-09-22-composite-model-corrections.md` section
6d). The point of this module is NOT to classify which one a flag is -- it
is to make sure a number never reaches a report without that question having
been asked, instead of being asked by hand only when a human happens to
notice the year looks too good (as happened here).

Import and call `concentration_report(records)` on the same per-(offset,
date, ticker) pick records `correction_variants.run_offset` /
`investigate_2020.py` already produce -- no new data, no re-run of anything.

Usage as a library:
    from concentration_monitor import concentration_report
    report = concentration_report(records, group_by="year")
    if report["max_single_ticker_share"] > FLAG_THRESHOLD:
        ... print/log a warning before trusting the aggregate ...

Usage standalone (recomputes the reset2026 confirmed baseline's nomination-
era picks and reports concentration per calendar year, as a worked example /
smoke test):
    python3 concentration_monitor.py
"""
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

# Any single ticker contributing more than this share of a period's total
# (weight x return) contribution is flagged for manual review before the
# period's number is trusted. 10% is a starting point, not a validated
# statistical threshold -- tune with Gabe once this has been run a few times
# and its false-positive rate on ordinary years is known.
FLAG_THRESHOLD = 0.10


def concentration_report(records, group_by="year", contribution_col=None):
    """
    records: list of dicts (or DataFrame) with at minimum
        {date, ticker, weight, gross_return_40} or a precomputed
        `contribution` column (weight * return).
    group_by: "year" (default) groups by calendar year of `date`; "all"
        treats every record as one group.
    Returns a dict: {group -> {total_contribution, top_ticker, top_ticker_share,
                                top5_share, flagged}}.
    """
    df = pd.DataFrame(records) if not isinstance(records, pd.DataFrame) else records.copy()
    if contribution_col is None:
        if "contribution" not in df.columns:
            df["contribution"] = df["weight"] * df["gross_return_40"]
        contribution_col = "contribution"

    df["date"] = pd.to_datetime(df["date"])
    if group_by == "year":
        df["_group"] = df["date"].dt.year
    else:
        df["_group"] = "all"

    out = {}
    for grp, g in df.groupby("_group"):
        total = g[contribution_col].sum()
        by_ticker = g.groupby("ticker")[contribution_col].sum().sort_values(ascending=False)
        if total == 0 or len(by_ticker) == 0:
            continue
        top_ticker = by_ticker.index[0]
        top_share = by_ticker.iloc[0] / total if total != 0 else np.nan
        top5_share = by_ticker.iloc[:5].sum() / total if total != 0 else np.nan
        out[str(grp)] = {
            "total_contribution": float(total),
            "n_distinct_tickers": int(by_ticker.shape[0]),
            "top_ticker": str(top_ticker),
            "top_ticker_share": float(top_share),
            "top5_share": float(top5_share),
            "flagged": bool(abs(top_share) >= FLAG_THRESHOLD),
        }
    return out


def print_report(report):
    for grp, r in sorted(report.items()):
        flag = " <== FLAGGED, review before trusting this period" if r["flagged"] else ""
        print(f"  {grp}: top ticker {r['top_ticker']:8s} "
              f"share={r['top_ticker_share']*100:+.1f}%  "
              f"top5_share={r['top5_share']*100:+.1f}%  "
              f"n_tickers={r['n_distinct_tickers']}{flag}")


def _self_test_worked_example():
    """Reproduces the 2020 finding this module generalizes, as a smoke test
    that the library function agrees with the hand-computed investigation."""
    import composite as C
    import run_backtest as RB
    import correction_variants as CV

    by_date, all_dates, spy, usmv = RB.load_data("holdout")
    records = []
    for offset in range(40):
        rebal_dates = [d for d in all_dates[offset::RB.HORIZON] if d.year == 2020]
        for tp in rebal_dates:
            df_date = by_date.get(tp)
            if df_date is None:
                continue
            elig = df_date[df_date["eligible_cap150"]]
            if len(elig) < C.N_VOL_QUINTILES * 4:
                continue
            elig = elig.reset_index(drop=True)
            scored = CV.compute_composite_ablated(elig, CV.ASSET_GROWTH_DROPPED_SIGNS, neutral=False)
            picks = C.pick_decile_volq(elig, scored)
            ret_lookup = dict(zip(elig["ticker"], elig["gross_return_40"]))
            for t, w in picks:
                r = ret_lookup.get(t)
                if pd.notna(r):
                    records.append({"date": tp, "ticker": t, "weight": w, "gross_return_40": r})
    report = concentration_report(records, group_by="year")
    print("Self-test (asset_growth_dropped, 2020 only, should flag with top ticker LCID or GME):")
    print_report(report)


if __name__ == "__main__":
    _self_test_worked_example()
