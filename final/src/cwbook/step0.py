"""WO-58 Step 0: label-free power check on the Stage-1 dates (no forward return is read).

    caffeinate -i /opt/anaconda3/envs/pipe_dream/bin/python final/src/cwbook/step0.py
"""
from __future__ import annotations

import json

import numpy as np

import cb_core as B

POOL_EFFECT_PCT_40D = 2.7    # WO-52 thin M, rounded as in the work order
ANN = 6.3
BAR_PCT_YR = 0.20


def main():
    b, pool, dates, info = B.load_book(1)
    D, _ = B.prep(b)
    rows = []
    for dd in D:
        idx, w = B.picks_for(dd)
        if len(idx) == 0:
            continue
        bot = dd["bottom"][idx]
        rows.append({"date": str(dd["date"].date()), "n_pool": dd["n"], "n_picks": len(idx),
                     "w_bottom": float(w[bot].sum()), "n_bottom": int(bot.sum()),
                     "w_chain": float(w[dd["has_chain"][idx]].sum()), "share_chain": float(dd["has_chain"][idx].mean()),
                     "share_sig": float(dd["has_sig"][idx].mean()),
                     "pool_bottom_removed": int(dd["bottom"].sum()), "pool_with_sig": int(dd["has_sig"].sum())})
    wb = np.array([r["w_bottom"] for r in rows])
    nb = np.array([r["n_bottom"] / r["n_picks"] for r in rows])
    overlap = float(wb.mean())
    implied = overlap * POOL_EFFECT_PCT_40D * ANN
    out = {"NOT_A_RESULT": "label-free: no forward return read", "load_info": info,
           "n_dates_with_picks": len(rows),
           "base_mean_weight_in_bottom_decile": overlap,
           "base_mean_count_share_in_bottom_decile": float(nb.mean()),
           "base_share_of_picks_with_kept_chain": float(np.mean([r["share_chain"] for r in rows])),
           "base_weight_share_with_kept_chain": float(np.mean([r["w_chain"] for r in rows])),
           "base_share_of_picks_with_signal": float(np.mean([r["share_sig"] for r in rows])),
           "base_median_names_held": float(np.median([r["n_picks"] for r in rows])),
           "book_pool_median_names": float(np.median([r["n_pool"] for r in rows])),
           "book_pool_median_with_signal": float(np.median([r["pool_with_sig"] for r in rows])),
           "median_names_removed_by_screen": float(np.median([r["pool_bottom_removed"] for r in rows])),
           "chance_share_of_bottom_decile_among_signal_names": 0.10,
           "implied_max_delta_pct_yr": implied, "bar_pct_yr": BAR_PCT_YR,
           "uninformative": bool(implied < BAR_PCT_YR), "per_date": rows}
    B.OUT.mkdir(parents=True, exist_ok=True)
    (B.OUT / "step0_power.json").write_text(json.dumps(out, indent=1, default=float))
    print(json.dumps({k: v for k, v in out.items() if k != "per_date"}, indent=1, default=float))


if __name__ == "__main__":
    main()
