"""
WO-37 data-arrival gate + named presence checks (doc section 5). No outcome is read.

    /opt/anaconda3/envs/pipe_dream/bin/python final/src/thinliq/check_arrival.py

Writes final/out/thinliq/arrival_gate.json and exits 1 while Phase 2 is not allowed.
"""
import sys

import tl_common as T

if __name__ == "__main__":
    r = T.arrival_gate(write=True)
    T.log(f"window dates on disk {r['window_dates_on_disk']}/{r['window_dates_expected']}; thin slice >=99% terminal on "
          f"{r['n_thin_complete']} (need {T.GATE_MIN_DATES}) -> gate {'PASS' if r['gate_pass'] else 'FAIL'}")
    for k, v in r["named_dead"].items():
        T.log(f"  {k}: thin dates {v['thin_dates_in_window']} ({v['first_thin']}..{v['last_thin']}), complete {v['thin_dates_complete']}, "
              f"kept chain {v['with_kept_chain']}, early {v['early9_present']}/{v['early9_thin']}, must {v['must_date']} "
              f"(thin={v['must_date_is_thin']}): {v['must_date_state']} -> {'PASS' if v['pass'] else 'FAIL'}")
    x = r["txg"]
    T.log(f"  TXG: cap2000 dates with chain {x['cap2000_with_chain']}/{x['cap2000_dates']}; thin dates {len(x['thin_dates'])}, "
          f"attempted {x['thin_attempted']}, with chain {x['thin_with_chain']}: {x['state']} -> {'PASS' if x['pass'] else 'FAIL'}")
    T.log(f"  pool integrity: {r['pool_integrity']}")
    T.log(f"  dead vs listed chain share: {r['dead_vs_listed_chain_share']}")
    T.log(f"phase2_allowed = {r['phase2_allowed']} -> {T.ARRIVAL}")
    sys.exit(0 if r["phase2_allowed"] else 1)
