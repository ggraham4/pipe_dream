"""
WO-35 presence scan for WO-O1 (no outcomes, no prices after t, no P&L).
For every chain entry date: the number of v2 cap2000-eligible names with at
least one put listed at the selected standard monthly expiry, using
run_wo_o1.target_expiry / accepted_expiries (the runner's own selection).
A date fails when its count is below half the median over all dates.

    cd final/src/options_wo25 && /opt/anaconda3/envs/pipe_dream/bin/python presence_scan.py
"""
from __future__ import annotations

import json
import sys

import pandas as pd

import run_wo_o1 as W


def main():
    entry = sorted(pd.Timestamp(p.stem.split("=")[1]) for p in W.CHAIN.glob("date=*.parquet"))
    u = W.read_on_dates(W.UNIVERSE_V2, ["date", "ticker", "eligible_cap2000"], entry)
    elig = u[u.eligible_cap2000].groupby("date").ticker.apply(set).to_dict()
    days = pd.DatetimeIndex(pd.read_csv(W.SPY_CSV, usecols=["date"], parse_dates=["date"]).date.sort_values())
    rows = []
    for t in entry:
        ch = pd.read_parquet(W.CHAIN / f"date={t.date()}.parquet", columns=["sharadar_ticker", "call_put", "expiration"])
        ch = ch[(ch.call_put == "Put") & ch.sharadar_ticker.isin(elig.get(t, set()))]
        exp = W.target_expiry(t)
        acc = W.accepted_expiries(exp, days)
        e = pd.to_datetime(ch.expiration)
        m = ch[e.isin(acc)]
        rows.append({"date": str(t.date()), "target_expiry": str(exp.date()),
                     "accepted": [str(pd.Timestamp(x).date()) for x in acc],
                     "matched_listed_expiries": sorted({str(pd.Timestamp(x).date()) for x in e[e.isin(acc)].unique()}),
                     "names_with_put": int(m.sharadar_ticker.nunique()),
                     "eligible_cap2000": len(elig.get(t, set()))})
    D = pd.DataFrame(rows)
    med = float(D.names_with_put.median())
    low = D[D.names_with_put < 0.5 * med]
    i = D.names_with_put.idxmin()
    out = {"n_dates": len(D), "median": med, "min": {"date": D.date[i], "names_with_put": int(D.names_with_put[i])},
           "below_half_median": low.to_dict("records"), "holiday_rule_dates": [r for r in rows if len(r["accepted"]) == 3],
           "pass": bool(low.empty), "by_date": rows}
    (W.OUT / "wo_o1_presence_scan.json").write_text(json.dumps(out, indent=2))
    print(f"{len(D)} dates; median {med:.0f}; min {out['min']}; below half median: {len(low)}")
    D["ratio_prev"] = D.names_with_put / D.names_with_put.shift(1)
    D["share_of_eligible"] = D.names_with_put / D.eligible_cap2000
    print("largest drops vs previous date:")
    print(D.nsmallest(5, "ratio_prev")[["date", "names_with_put", "ratio_prev", "share_of_eligible"]].to_string(index=False))
    print("lowest share of eligible:")
    print(D.nsmallest(5, "share_of_eligible")[["date", "names_with_put", "eligible_cap2000", "share_of_eligible"]].to_string(index=False))
    for r in out["holiday_rule_dates"]:
        print("holiday rule:", r["date"], r["accepted"], r["matched_listed_expiries"], r["names_with_put"])
    sys.exit(0 if low.empty else 1)


if __name__ == "__main__":
    main()
