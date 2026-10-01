"""
WO-37 coverage facts for the thin slice on the dates where it has been pulled
(doc section 6.1). Quote-side only: no settlement price and no forward return
is read anywhere in this file.

    /opt/anaconda3/envs/pipe_dream/bin/python final/src/thinliq/coverage.py
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

import tl_common as T
import run_arm2 as A2


def tier_facts(tier, dates, L, kept):
    u = T.universe_on(dates)
    u = u[u.thin] if tier == "thin" else u[u.eligible_cap2000]
    u = u.assign(ds=u.date.dt.strftime("%Y-%m-%d"))
    u = u.merge(L[["date", "ticker", "status"]].rename(columns={"date": "ds"}), on=["ds", "ticker"], how="left")
    u["kept"] = [(d, t) in kept for d, t in zip(u.ds, u.ticker)]
    f = pd.read_parquet(T.FEATS)
    f["date"] = pd.to_datetime(f.date); f["ticker"] = f.ticker.astype(str)
    m = u.merge(f, on=["date", "ticker"], how="left")
    c = m[m.kept]
    E, _ = A2.build_entries(dates, tier)
    q = E[E.quoted]
    pop = q[q.sizes_populated]
    n_nd = len(u)
    by_date = E.groupby("date").agg(entries=("ticker", "size"), quoted=("quoted", "sum"), fillable=("fillable", "sum"))
    return {
        "name_dates": int(n_nd), "names_per_date_median": float(u.groupby("ds").size().median()),
        "pull_status_share": u.status.fillna("not attempted").value_counts(normalize=True).round(4).to_dict(),
        "share_with_chain_in_store(status ok)": float((u.status == "ok").mean()),
        "share_with_chain_passing_identity_filter": float(u.kept.mean()),
        "names_with_chain_per_date_median": float(c.groupby("ds").size().median()),
        "of_names_with_chain": {
            "share_any_option_volume_that_day": float((c.opt_volume > 0).mean()),
            "median_total_option_volume_contracts": float(c.opt_volume.median()),
            "share_volume_ge_100_contracts": float((c.opt_volume >= 100).mean()),
            "median_total_open_interest_contracts": float(np.expm1(c.opt_log_oi).median()),
            "median_rel_spread_atm(|delta| .3-.7)": float(c.opt_spread_atm.median()),
            "share_with_opt_cw_spread": float(c.opt_cw_spread.notna().mean()),
        },
        "share_of_all_names_with_any_option_volume": float((m.opt_volume > 0).sum() / n_nd),
        "arm1_signal_names_per_date_median": float(c[c.opt_cw_spread.notna()].groupby("ds").size().median()),
        "arm2_030_delta_put": {
            "name_dates_with_put_in_tolerance": int(len(E)), "share_of_all_name_dates": float(len(E) / n_nd),
            "share_quoted(passes WO-O1 F0-F6)": float(E.quoted.mean()),
            "quoted_entries": int(len(q)),
            "median_rel_spread_of_chosen_put": float(q.rel_spread.median()),
            "median_bid_usd": float(q.bid.median()),
            "median_open_interest_of_chosen_put": float(q.open_interest.median()),
            "share_chosen_put_zero_volume_that_day": float((q.volume == 0).mean()),
            "share_of_quoted_with_sizes_populated(>=90% rule)": float(q.sizes_populated.mean()),
            "among_sizes_populated": {"entries": int(len(pop)), "median_bid_size": float(pop.bid_size.median()) if len(pop) else None,
                                      "share_bid_size_ge_5": float((pop.bid_size >= A2.MIN_BID_SIZE).mean()) if len(pop) else None,
                                      "fillable_strict_share": float(pop.fillable_strict.mean()) if len(pop) else None},
            "share_quoted_OI_ge_50(oi-only fillable)": float(q.fillable_oi_only.mean()),
            "fillable_share_of_quoted(pre-registered rule)": float(q.fillable.mean()),
            "fillable_share_of_all_name_dates": float(q.fillable.sum() / n_nd),
            "fillable_entries_per_date": {str(d.date()): int(v) for d, v in by_date.fillable.items()},
            "capacity": A2.capacity(E),
        },
    }


def main():
    L = T.read_log()
    kept = T.kept_pairs(L)
    g = T.arrival_gate(write=True)
    dates = [pd.Timestamp(d) for d in g["thin_complete_dates"] if (T.CHAIN / f"date={d}.parquet").exists()]
    out = {"NO_OUTCOME_DATA": "quote-side facts only; nothing here uses a forward return or a settlement price",
           "dates": [str(d.date()) for d in dates],
           "note_sizes": "AV leaves bid_size/ask_size unpopulated for most 2008-2009 chains (WO-25 Amendment 1), so the size "
                         "leg of the fillable rule is close to unmeasurable on these dates; see among_sizes_populated",
           "thin": tier_facts("thin", dates, L, kept), "cap2000_same_dates": tier_facts("cap2000", dates, L, kept)}
    p = T.OUT / "coverage_thin_early_dates.json"
    p.write_text(json.dumps(out, indent=1, default=str))
    T.log(f"wrote {p}")
    print(json.dumps({k: out[k] for k in ["thin", "cap2000_same_dates"]}, indent=1, default=str))


if __name__ == "__main__":
    main()
