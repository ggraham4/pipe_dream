"""
WO-55: the WO-37 Arm 1 screen (avoid the bottom decile of opt_cw_spread), run UNCHANGED on the
OptionMetrics 2019-01-16 .. 2025-08-20 store. Unfitted out-of-era read = hold-out read #22.
Spec: final/models/2026-10-09-cwspread-outofera-prereg.md. Only paths, the window, the date count,
the gate's date minimum (90% of 80 = 72) and the in-window named dead names are repointed in
tl_common; every rule function of thinliq/run_arm1.py is imported and called unchanged.

    PY=/opt/anaconda3/envs/pipe_dream/bin/python
    $PY final/src/cwspread_oos/run_oos.py gate     # arrival/coverage gate + presence checks (no outcome)
    $PY final/src/cwspread_oos/run_oos.py chain    # chain + features (thinliq/build_chain.py)
    $PY final/src/cwspread_oos/run_oos.py read     # THE one guarded run (real labels, 2019+)
"""
from __future__ import annotations

import hashlib
import json
import math
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import oos_paths as P  # noqa: E402
import tl_common as T  # noqa: E402

# ---- repoint the harness: paths, window, gate size, named names (pre-reg section 4)
T.AV = P.STORE
T.PULL_LOG = P.CALLS
T.AV_MONTHLY = P.MONTHLY
T.OUT = P.OUT
T.CHAIN = P.OUT / "chain" / "source=om_monthly"
T.FCACHE = P.OUT / "features_cache"
T.FEATS = P.OUT / "om_options_features_oos.parquet"
T.ARRIVAL = P.OUT / "arrival_gate.json"
T.WINDOW = (pd.Timestamp(P.LO), pd.Timestamp(P.HI))
T.N_WINDOW_DATES = P.N_DATES
T.GATE_MIN_DATES = math.ceil(0.90 * P.N_DATES)       # 72 of 80 (WO-55: < 90% of dates passing = BLOCKED)
T.NAMED_DEAD = {                                      # ATPAQ/SIGM have no thin date in 2019-2025
    "BBBYQ": {"name": "Bed Bath & Beyond (bankrupt 2023)", "must_date": "2022-08-17"},
    "RADCQ": {"name": "Rite Aid (bankrupt 2023)", "must_date": "2022-06-15"},
}

PREREG_SHA256 = "72b066536ecd6433fc738f68b1c5a41cd8540e804b4653f8556a2dcefbebc7cc"
RESULT = P.OUT / "wo55_read_results.json"
NULL_SEED = 20261001          # the WO-52 Arm 1 shuffle-null seed
NULL_LABEL_SEEDS = 100        # null-seed sd: labels permuted within date, seeds 1000..1099 (run_arm1 convention)
# WO-55 bars (bind on the thin slice; cap2000 is reported against the same bars, descriptive)
PASS_M, PASS_T = 0.5, 3.0     # % per 40d, NW lag-39 t


def read_log_parquet():
    """Same contract as tl_common.read_log, reading calls.parquet (as WO-52's run_thinliq_om)."""
    L = pd.read_parquet(P.CALLS, columns=["pass", "date", "ticker", "status", "symbol", "identity", "spot_parity", "closeunadj", "n"])
    L["_o"] = L.status.map({"ok": 0, "no_data": 1}).fillna(2)
    return L.sort_values("_o").drop_duplicates(["date", "ticker"], keep="first").drop(columns="_o")


T.read_log = read_log_parquet
P.OUT.mkdir(parents=True, exist_ok=True)


def frozen_chain_gate():
    """The gate under the WO-52 chain with the WO-51 crosswalk unmodified (status_frozen), for the record."""
    L = pd.read_parquet(P.CALLS, columns=["date", "ticker", "status_frozen"])
    u = T.universe_on(T.monthly_dates())
    thin = u[u.thin].assign(ds=lambda x: x.date.dt.strftime("%Y-%m-%d"))
    m = thin.merge(L.rename(columns={"date": "ds"}), on=["ds", "ticker"], how="left")
    per = m.assign(t=m.status_frozen.isin(T.TERMINAL)).groupby("ds").t.mean()
    return {"n_dates_ge_99pct_terminal": int((per >= T.GATE_SHARE).sum()), "of": int(len(per)),
            "terminal_share_min": float(per.min()), "terminal_share_median": float(per.median())}


def gate():
    rep = T.arrival_gate(write=True)
    ts = sorted(v["terminal_share"] for v in rep["per_date"].values())
    fz = frozen_chain_gate()
    failing = sorted(d for d, v in rep["per_date"].items() if v["terminal_share"] < T.GATE_SHARE)
    out = {"n_dates": rep["window_dates_on_disk"], "n_thin_complete": rep["n_thin_complete"], "need": T.GATE_MIN_DATES,
           "share_of_dates_passing": rep["n_thin_complete"] / max(rep["window_dates_on_disk"], 1),
           "gate_pass": rep["gate_pass"], "phase2_allowed": rep["phase2_allowed"],
           "verdict_if_fail": None if rep["gate_pass"] else "BLOCKED",
           "terminal_share_min": ts[0], "terminal_share_median": ts[len(ts) // 2], "failing_dates": failing,
           "frozen_chain_gate_DESCRIPTIVE": fz,
           "named_dead": {k: {kk: v[kk] for kk in ("must_date_state", "share", "thin_dates_complete", "with_kept_chain", "pass")}
                          for k, v in rep["named_dead"].items()},
           "txg": {k: rep["txg"][k] for k in ("state", "cap2000_dates", "cap2000_with_chain", "thin_attempted", "thin_with_chain", "pass")},
           "pool_integrity": rep["pool_integrity"], "dead_vs_listed": rep["dead_vs_listed_chain_share"]}
    (P.OUT / "gate_summary.json").write_text(json.dumps(out, indent=1, default=str))
    print(json.dumps(out, indent=1, default=str))
    return out


def guard():
    doc = Path(__file__).resolve().parents[3] / P.PREREG_DOC
    got = hashlib.sha256(doc.read_bytes()).hexdigest()
    if got != PREREG_SHA256:
        raise SystemExit(f"read refused: {P.PREREG_DOC} sha256 {got} != frozen {PREREG_SHA256}")
    # WO-37 guard, unchanged: WO-37 doc tracked, gate + presence checks recomputed, chain fresh, no earlier result
    return T.phase2_guard(RESULT)


def labels_complete(dates):
    """Entry d is used only if close[d+40] exists on the Sharadar trading calendar (presence only)."""
    import pyarrow.parquet as pq
    cal = pd.DatetimeIndex(sorted(pd.to_datetime(pq.read_table(T.UNIVERSE, columns=["date"]).column("date").to_pandas()).unique()))
    keep = []
    for d in dates:
        i = cal.searchsorted(d)
        if i + 41 <= len(cal) - 1:
            keep.append(d)
    return keep, str(cal[-1].date())


def wo55_bars(e):
    M, t, off = e["M_pct_per_40d"], e["nw39_t"], e["offsets_pct"]
    both_pos = off[0] is not None and off[1] is not None and off[0] > 0 and off[1] > 0
    opposite = off[0] is not None and off[1] is not None and off[0] * off[1] < 0
    if M is not None and t is not None and M >= PASS_M and t >= PASS_T and both_pos:
        return "PASS"
    if M is None or M <= 0 or opposite:
        return "KILL"
    return "MIDDLE"


def read():
    import run_arm1 as A
    t0 = time.time()
    dates = guard()
    dates, cal_end = labels_complete(dates)
    out = {"wo": "WO-55", "holdout_read": "#22 (unfitted, fixed rule; 2019-01..2025-08 entry dates)",
           "label": "outcome_cache_v2.gross_return_40", "calendar_end": cal_end,
           "window": [str(dates[0].date()), str(dates[-1].date())], "n_entry_dates": len(dates)}
    res = {}
    for uni in ("thin", "cap2000"):
        m, nu = A.load_frame(uni, dates)
        m["y"] = A.attach_labels(m, "real", 0)
        D = A.prep(m)
        e = A.evaluate(D, m.y.to_numpy(float), null_seed=NULL_SEED)
        e["wo55_verdict"] = wo55_bars(e)
        e["coverage"] = A.coverage_note(m, nu, D)
        e["loyo_ex2020_pct"] = e["loyo_pct"].get(2020)
        # median spread (descriptive): opt_spread_atm (% of mid) over the pool and the bottom decile
        f = pd.read_parquet(T.FEATS, columns=["date", "ticker", "opt_spread_atm"])
        f["date"] = pd.to_datetime(f.date); f["ticker"] = f.ticker.astype(str)
        sp = m[["date", "ticker"]].merge(f, on=["date", "ticker"], how="left").opt_spread_atm.to_numpy(float)
        pool_ix = np.concatenate([x["idx"] for x in D]); bot_ix = np.concatenate([x["idx"][x["b_raw"]] for x in D])
        e["median_spread_atm_pct_DESCRIPTIVE"] = {"pool": float(np.nanmedian(sp[pool_ix]) * 100), "bottom_decile": float(np.nanmedian(sp[bot_ix]) * 100)}
        res[uni] = (m, D, e)
        out[uni] = e
    # null-seed sd (thin): labels permuted within date, same construction (run_arm1 --labels shuffled convention)
    m, D, _ = res["thin"]
    base = m.y.to_numpy(float)
    Ms, ts, ver = [], [], []
    for s in range(NULL_LABEL_SEEDS):
        rng = np.random.default_rng(1000 + s)
        y = np.full(len(m), np.nan)
        for x in D:
            y[x["idx"]] = rng.permutation(base[x["idx"]])
        r = A.evaluate(D, y, null_seed=s)
        Ms.append(r["M_pct_per_40d"]); ts.append(r["nw39_t"]); ver.append(wo55_bars(r))
    Ms, ts = np.array(Ms, float), np.array(ts, float)
    out["thin_null_labels"] = {"seeds": NULL_LABEL_SEEDS, "M_pct": {"mean": float(Ms.mean()), "sd": float(Ms.std())},
                               "nw39_t": {"mean": float(np.nanmean(ts)), "sd": float(np.nanstd(ts))},
                               "wo55_verdict_rates": pd.Series(ver).value_counts(normalize=True).to_dict()}
    out["verdict"] = out["thin"]["wo55_verdict"]
    out["runtime_s"] = time.time() - t0
    RESULT.write_text(json.dumps(out, indent=1, default=str))
    T.log(f"WO-55 verdict {out['verdict']} -> {RESULT}")


def main():
    cmd = sys.argv[1]
    sys.argv = [cmd]
    if cmd == "gate":
        gate()
    elif cmd == "chain":
        import build_chain
        build_chain.main()
    elif cmd == "read":
        read()
    else:
        raise SystemExit(f"unknown command {cmd}")


if __name__ == "__main__":
    main()
