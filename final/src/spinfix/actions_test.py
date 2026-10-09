"""WO-57 Phase 1b: Sharadar ACTIONS as the forward spin-off event source, tested on 2007-2019 vs CRSP.

Pre-registration: final/models/2026-10-09-spinfix-builder-prereg.md (hash asserted), "Event source rule" 3.
Pulls ACTIONS (spinoff, spinoffdividend, spunofffrom; 2006-12-01..2020-01-10, metadata only) with a filtered
Sharadar API call into final/out/spinfix_builder/actions_spin_2007_2019.parquet (gitignored). The local
final/data/sharadar/actions.csv is never touched. Writes final/out/spinfix_builder/actions_test.json.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
SRC = HERE.parent
FINAL = HERE.parents[1]
PREREG = FINAL / "models" / "2026-10-09-spinfix-builder-prereg.md"
PREREG_SHA = "a4c44e9b813a7e656f42da8cbba56da64cc22c9e02f009336a1ca33de1d85d56"
assert hashlib.sha256(PREREG.read_bytes()).hexdigest() == PREREG_SHA, "PRE-REG CHANGED SINCE FREEZE: STOP"
sys.path.insert(0, str(SRC))
sys.path.insert(0, str(SRC / "wrds_crsp"))
sys.path.insert(0, str(HERE))
import adjust as SA  # noqa: E402
import common as K  # noqa: E402

OUT = FINAL / "out" / "spinfix_builder"
ACT_PQ = OUT / "actions_spin_2007_2019.parquet"
LO, CUT = pd.Timestamp("2007-01-01"), pd.Timestamp("2019-12-31")
PARENT = ("spinoff", "spinoffdividend")
KNOWN_MISSES = [("SWY", "2014-04-15"), ("TWX", "2014-06-09"), ("NEBLQ", "2014-08-04")]


def scrub(s):
    k = os.environ.get("SHARADAR_API_KEY") or ""
    s = str(s).replace(k, "***") if k else str(s)
    return re.sub(r"api_key=[^&\s'\"]+", "api_key=***", s)


def pull():
    if ACT_PQ.exists():
        return pd.read_parquet(ACT_PQ)
    import sharadar_build_identity_map as SB
    rows = []
    for a in ("spinoff", "spinoffdividend", "spunofffrom"):
        try:
            r = SB.get_all("actions", {"action": a, "date.gte": "2006-12-01", "date.lte": "2020-01-10"})
        except Exception as e:  # never print the key
            raise RuntimeError(f"actions pull failed: {scrub(e)}") from None
        rows += r
    a = pd.DataFrame(rows)
    a["date"] = pd.to_datetime(a["date"]).astype("datetime64[ns]")
    a["value"] = pd.to_numeric(a["value"], errors="coerce")
    OUT.mkdir(parents=True, exist_ok=True)
    a.to_parquet(ACT_PQ, index=False)
    return a


def main():
    t0 = time.time()
    act = pull()
    cal = K.market_calendar(pd.Timestamp("2020-01-10"))
    pos = {d: i for i, d in enumerate(cal.astype("datetime64[ns]"))}

    def tpos(d):
        d = np.datetime64(pd.Timestamp(d), "ns")
        return int(np.searchsorted(cal, d))           # trading-day index (next trading day if not one)

    act = act[(act["date"] >= LO) & (act["date"] <= CUT)].copy()
    act["ticker"] = act["ticker"].astype(str)
    act["tp"] = act["date"].map(tpos)
    par = act[act["action"].isin(PARENT)].drop_duplicates(["ticker", "date"])
    rep = {"actions_rows_2007_2019": {k: int(v) for k, v in act["action"].value_counts().items()},
           "parent_ticker_dates": int(len(par))}
    by_t = {t: g["tp"].to_numpy() for t, g in par.groupby("ticker")}

    ev = pd.read_parquet(SA.EVENTS_PQ)
    ev["exdt"] = pd.to_datetime(ev["exdt"]).astype("datetime64[ns]")
    ev["base"] = ev["ticker"].astype(str).str.split("__post").str[0]
    ev["tp"] = ev["exdt"].map(tpos)

    def match(t, tp, tol):
        x = by_t.get(t)
        if x is None:
            return "ticker_absent"
        return "hit" if np.any(np.abs(x - tp) <= tol) else "no_row_near_date"

    for name, sub in (("applied_242", ev[ev["applied"].fillna(False).astype(bool)]),
                      ("candidates_274", ev[ev["status"].fillna("") == ""])):
        r = {}
        for tol, lab in ((0, "exact"), (1, "pm1")):
            res = [match(t, tp, tol) for t, tp in zip(sub["base"], sub["tp"])]
            vc = pd.Series(res).value_counts()
            r[lab] = {"n": int(len(sub)), "hit": int(vc.get("hit", 0)), "recall": float(vc.get("hit", 0) / len(sub)),
                      "ticker_absent": int(vc.get("ticker_absent", 0)),
                      "no_row_near_date": int(vc.get("no_row_near_date", 0))}
        if name == "applied_242":
            miss = sub[[match(t, tp, 1) != "hit" for t, tp in zip(sub["base"], sub["tp"])]]
            r["misses_pm1_by_year"] = {int(k): int(v) for k, v in miss["exdt"].dt.year.value_counts().sort_index().items()}
            r["misses_pm1_sample"] = [f"{t} {d.date()}" for t, d in zip(miss["base"].head(25), miss["exdt"].head(25))]
            r["misses_pm1_abs_log_m_median"] = float(np.abs(miss["log_m"]).median()) if len(miss) else None
        rep[f"recall_{name}"] = r

    # post-hoc, not judged: also accept a child-side `spunofffrom` row whose contraticker is the parent
    ch = act[act["action"] == "spunofffrom"].dropna(subset=["contraticker"])
    by_c = {t: g["tp"].to_numpy() for t, g in ch.groupby(ch["contraticker"].astype(str))}
    sub = ev[ev["applied"].fillna(False).astype(bool)]
    h2 = [match(t, tp, 1) == "hit" or (t in by_c and np.any(np.abs(by_c[t] - tp) <= 1))
          for t, tp in zip(sub["base"], sub["tp"])]
    rep["posthoc_not_judged_recall_242_pm1_with_spunofffrom"] = float(np.mean(h2))

    # precision: ACTIONS parent rows on v2-grid tickers vs any CRSP 3xxx record with a ticker
    grid = set(pd.read_parquet(K.R26 / "composite_panel_v2.parquet", columns=["ticker"],
                               filters=[("date", ">=", "2007-01-02"), ("date", "<=", "2019-12-31")])["ticker"].astype(str).unique())
    crsp_by_t = {t: g["tp"].to_numpy() for t, g in ev[ev["ticker"].notna()].groupby("base")}
    pg = par[par["ticker"].isin(grid)]
    hit = np.array([t in crsp_by_t and np.any(np.abs(crsp_by_t[t] - tp) <= 1) for t, tp in zip(pg["ticker"], pg["tp"])])
    hit0 = np.array([t in crsp_by_t and np.any(crsp_by_t[t] == tp) for t, tp in zip(pg["ticker"], pg["tp"])])
    rep["precision_pm1"] = {"actions_parent_rows_on_grid": int(len(pg)), "matched": int(hit.sum()),
                            "precision": float(hit.mean()) if len(pg) else None,
                            "matched_exact": int(hit0.sum()),
                            "unmatched_sample": [f"{t} {d.date()}" for t, d in zip(pg.loc[~hit, "ticker"].head(20), pg.loc[~hit, "date"].head(20))]}

    # known early-drop misses
    km = []
    for t, d in KNOWN_MISSES:
        rows = act[(act["ticker"] == t) & (act["date"] >= pd.Timestamp(d) - pd.Timedelta(days=6)) &
                   (act["date"] <= pd.Timestamp(d) + pd.Timedelta(days=6))]
        km.append({"ticker": t, "wo54_date": d, "actions_rows": [f"{r.action} {r.date.date()} {r.value}" for r in rows.itertuples()],
                   "within_pm1_of_drop": bool(len(rows) and np.any(np.abs(rows["tp"].to_numpy() - tpos(d)) <= 1))})
    rep["known_misses"] = km

    # descriptive: ACTIONS-implied m vs CRSP m on matched applied events
    app = ev[ev["applied"].fillna(False).astype(bool)]
    sd = act[act["action"] == "spinoffdividend"]
    so = act[act["action"] == "spinoff"]
    ohl = K.load_ohlc(sorted(set(app["base"]) | set(so["contraticker"].dropna().astype(str))), CUT, cols=("date", "close"))
    cmpA, cmpB = [], []
    for e in app.itertuples():
        g = ohl.get(e.base)
        if g is None:
            continue
        d = g["date"].to_numpy("datetime64[ns]")
        k = np.searchsorted(d, np.datetime64(e.exdt, "ns"))
        if k >= len(d) or d[k] != np.datetime64(e.exdt, "ns"):
            continue
        cx = float(g["close"].iloc[k])
        a1 = sd[(sd["ticker"] == e.base) & (np.abs(sd["tp"] - e.tp) <= 1)]
        if len(a1) and np.isfinite(a1["value"]).all():
            mA = cx / (cx + float(a1["value"].sum()))
            cmpA.append(abs(np.log(mA) - e.log_m))
        a2 = so[(so["ticker"] == e.base) & (np.abs(so["tp"] - e.tp) <= 1)]
        tot, okb = 0.0, len(a2) > 0
        for r in a2.itertuples():
            gs = ohl.get(str(r.contraticker))
            if gs is None or not np.isfinite(r.value):
                okb = False
                break
            ds = gs["date"].to_numpy("datetime64[ns]")
            j = np.searchsorted(ds, np.datetime64(e.exdt, "ns"))
            if j >= len(ds) or ds[j] != np.datetime64(e.exdt, "ns"):
                okb = False
                break
            tot += r.value * float(gs["close"].iloc[j])
        if okb:
            cmpB.append(abs(np.log(cx / (cx + tot)) - e.log_m))

    def summ(v):
        v = np.array(v)
        return {"n": int(len(v)), "median_abs_log_diff": float(np.median(v)) if len(v) else None,
                "share_within_2pct": float((v < 0.02).mean()) if len(v) else None}
    rep["descriptive_m_from_actions"] = {"spinoffdividend_value": summ(cmpA), "ratio_x_spinco_close": summ(cmpB),
                                         "note": "not judged; m_A = close_ex/(close_ex + D), m_B = close_ex/(close_ex + ratio x spinco close_ex)"}
    rep["runtime_s"] = round(time.time() - t0, 1)
    (OUT / "actions_test.json").write_text(json.dumps(rep, indent=1, default=str))
    r = rep["recall_applied_242"]["pm1"]
    print(f"recall(242,±1) {r['recall']:.3f} hit {r['hit']} absent {r['ticker_absent']} no_row {r['no_row_near_date']}; "
          f"precision {rep['precision_pm1']['precision']}; known misses {[k['within_pm1_of_drop'] for k in km]}")


if __name__ == "__main__":
    main()
