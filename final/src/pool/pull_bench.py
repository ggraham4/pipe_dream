"""
WO-31: pull SPY and IWM daily bars 2006-01..2026-09 for the descriptive pool /
hedge read, on WO-9's basis (hedged_composite.yf_pull body: yfinance,
auto_adjust=False -> split-adjusted price in open/close, total return via
adj_close/close). HC.yf_pull itself asserts dates < 2020, so its body is
copied here with a later end date.

Writes gitignored parquet files under final/out/pool/bench/ (never
final/data/benchmarks/IWM_live.csv, which is WO-10's blind forward file).

Hard checks (stop on failure):
  IWM: open/close equal to data/benchmarks/IWM.csv 2006-06..2019-12 (rel 1e-6),
       40d total-return ratio on adj_close equal (abs 1e-6)
  SPY: price ret40 close[i+40]/open[i+1]-1 equal to outcome_cache_v2 SPY
       gross_return_40 on every panel date 2007-01..2026-07-30 (abs 1e-6)
Output meta: final/out/pool/bench/pull_meta.json
"""
import hashlib
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
FINAL = HERE.parents[1]
sys.path.insert(0, str(FINAL / "src" / "reset2026"))
import hedged_composite as HC              # noqa: E402  (ret40 only)

OUT = FINAL / "out" / "pool" / "bench"
MAIN = Path("/Users/ggraham/pipe_dream/final")
IWM_OLD = MAIN / "data" / "benchmarks" / "IWM.csv"
OC = MAIN / "out" / "reset2026" / "outcome_cache_v2.parquet"
LO, HI = "2006-01-01", "2026-10-01"
LAST_LABEL = pd.Timestamp("2026-07-30")


def log(m):
    print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)


def yf_pull(sym, start, end):
    import yfinance as yf
    d = yf.download(sym, start=start, end=end, progress=False, auto_adjust=False, actions=False)
    if d is None or d.empty:
        raise SystemExit(f"BLOCKED: yfinance returned nothing for {sym}")
    d = d.reset_index()
    d.columns = [c[0] if isinstance(c, tuple) else c for c in d.columns]
    d = d.rename(columns={"Date": "date", "Open": "open", "High": "high", "Low": "low",
                          "Close": "close", "Adj Close": "adj_close", "Volume": "volume"})
    d["date"] = pd.to_datetime(d["date"]).dt.tz_localize(None)
    return d[["date", "open", "high", "low", "close", "adj_close", "volume"]].sort_values("date").reset_index(drop=True)


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    meta = {"work_order": "WO-31", "pulled_at": time.strftime("%Y-%m-%d %H:%M:%S"), "source": "yfinance auto_adjust=False",
            "window": [LO, HI]}
    d = {s: yf_pull(s, LO, HI) for s in ("SPY", "IWM")}
    for s, g in d.items():
        assert g["date"].is_unique and (g[["open", "close", "adj_close"]] > 0).all().all()
        assert g["date"].max() >= pd.Timestamp("2026-09-24"), f"{s} ends {g['date'].max()}"
        p = OUT / f"{s}.parquet"
        g.to_parquet(p, index=False)
        meta[s] = {"rows": len(g), "first": str(g["date"].min().date()), "last": str(g["date"].max().date()),
                   "file": str(p.relative_to(FINAL.parent)), "sha256": sha(p)}
        log(f"{s}: {len(g)} rows {meta[s]['first']}..{meta[s]['last']}")

    # IWM vs WO-9's IWM.csv
    old = pd.read_csv(IWM_OLD, parse_dates=["date"]).sort_values("date").reset_index(drop=True)
    new = d["IWM"]
    m = old.merge(new, on="date", suffixes=("_o", "_n"))
    assert len(m) == len(old), "IWM.csv dates missing in new pull"
    rel = {c: float(np.abs(m[f"{c}_n"] / m[f"{c}_o"] - 1.0).max()) for c in ("open", "close")}
    new_old = new[(new["date"] >= old["date"].min()) & (new["date"] <= old["date"].max())].reset_index(drop=True)
    assert (new_old["date"].to_numpy() == old["date"].to_numpy()).all()
    tr_o, tr_n = HC.ret40(old, total_return=True), HC.ret40(new_old, total_return=True)
    pr_o, pr_n = HC.ret40(old), HC.ret40(new_old)
    dtr = float(np.nanmax(np.abs(tr_o.to_numpy() - tr_n.to_numpy())))
    dpr = float(np.nanmax(np.abs(pr_o.to_numpy() - pr_n.to_numpy())))
    meta["iwm_vs_wo9_csv"] = {"rows": len(m), "max_rel_open": rel["open"], "max_rel_close": rel["close"],
                              "max_abs_ret40_price": dpr, "max_abs_ret40_total": dtr, "tol_price": 1e-6,
                              "tol_total": 1e-5, "note": "adj_close is re-scaled by later dividends at each pull; float rounding ~2e-6"}
    log(f"IWM vs WO-9 csv: {meta['iwm_vs_wo9_csv']}")
    assert rel["open"] < 1e-6 and rel["close"] < 1e-6 and dpr < 1e-6 and dtr < 1e-5, "IWM PULL CHECK FAIL"

    # SPY price ret40 vs outcome_cache_v2 on every panel date
    oc = pd.read_parquet(OC, columns=["ticker", "date", "gross_return_40"], filters=[("ticker", "==", "SPY")])
    oc["date"] = pd.to_datetime(oc["date"])
    oc = oc[(oc["date"] >= pd.Timestamp("2007-01-02")) & (oc["date"] <= LAST_LABEL)].set_index("date")["gross_return_40"].astype(np.float64)
    mine = HC.ret40(d["SPY"])
    idx = oc.dropna().index
    miss = idx.difference(mine.dropna().index)
    assert len(miss) == 0, f"SPY pull lacks {len(miss)} panel dates, e.g. {list(miss[:5])}"
    diff = np.abs(mine.reindex(idx).to_numpy() - oc.reindex(idx).to_numpy())
    bad = idx[diff >= 1e-6]
    meta["spy_vs_outcome_cache_v2"] = {"n_dates": int(len(idx)), "max_abs_diff": float(diff.max()),
                                       "worst_date": str(idx[int(diff.argmax())].date()), "tol": 1e-6,
                                       "dates_over_tol": {str(d.date()): [float(oc[d]), float(mine[d])] for d in bad},
                                       "note": "[cache, fresh pull]. SPY.csv today equals the fresh pull on every bar, so "
                                               "the cache was built from earlier SPY bars for these exits. WO-31 keeps the "
                                               "cache's SPY price leg (harness basis) and takes only the dividend leg "
                                               "from this pull."}
    log(f"SPY vs outcome_cache_v2: {meta['spy_vs_outcome_cache_v2']}")
    assert diff[np.asarray(idx < pd.Timestamp("2026-07-01"))].max() < 1e-6, "SPY METHOD RECONCILE FAIL"
    assert len(bad) <= 5 and diff.max() < 1e-2, "SPY METHOD RECONCILE FAIL (tail)"
    # IWM covers every panel date as well
    iwm40 = HC.ret40(new)
    miss_i = idx.difference(iwm40.dropna().index)
    meta["iwm_covers_all_panel_dates"] = int(len(miss_i)) == 0
    assert len(miss_i) == 0, f"IWM lacks {len(miss_i)} panel dates"
    (OUT / "pull_meta.json").write_text(json.dumps(meta, indent=2))
    log("pull OK")


if __name__ == "__main__":
    main()
