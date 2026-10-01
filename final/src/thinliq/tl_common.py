"""
WO-37 thin-liquidity options probe: shared paths, pre-registered constants,
the thin-slice definition, the data-arrival gate and the --phase2 guard.
Spec: final/models/2026-10-01-thin-liquidity-prereg.md (every constant below
is fixed there before any real-label number exists).

Nothing in this module reads a forward return.
"""
from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
SRC = HERE.parent
REPO = HERE.parents[2]
sys.path.insert(0, str(SRC))
sys.path.insert(0, str(SRC / "options_wo25"))
from wo25_io import read_on_dates  # noqa: E402  (imported, never edited)

MAIN = Path("/Users/ggraham/pipe_dream/final")
DATA = MAIN / "data"
# Read-only merged store. AV_DATA_ROOT overrides the path only (same convention as WO-35).
AV = Path(os.environ.get("AV_DATA_ROOT", str(DATA / "alphavantage_full")))
PULL_LOG = AV / "pull_log.sqlite"
AV_MONTHLY = AV / "options" / "monthly"
UNIVERSE = DATA / "sharadar" / "downcap_universe_v2.parquet"
PANEL_V2 = MAIN / "out" / "reset2026" / "composite_panel_v2.parquet"
OUTCOME_V2 = MAIN / "out" / "reset2026" / "outcome_cache_v2.parquet"
SEP = DATA / "sharadar" / "panel" / "stocks"
OUT = HERE.parents[1] / "out" / "thinliq"
CHAIN = OUT / "chain" / "source=av_monthly"
FCACHE = OUT / "features_cache"
FEATS = OUT / "av_options_features_thinliq.parquet"
ARRIVAL = OUT / "arrival_gate.json"
PREREG_DOC = "final/models/2026-10-01-thin-liquidity-prereg.md"

# ---- pre-registered constants (doc sections 2, 3, 5)
WINDOW = (pd.Timestamp("2008-01-01"), pd.Timestamp("2018-12-31"))   # no date from 2019 on is read
N_WINDOW_DATES = 133
TERMINAL = ("ok", "no_data")
GATE_SHARE = 0.99          # thin slice >= 99% terminal on a date ...
GATE_MIN_DATES = 120       # ... on at least 120 of the 133 window dates
POOL_MIN = 0.99            # >= 99% of thin name-dates present in panel and outcome cache
NAMED_DEAD = {             # Sharadar isdelisted=Y, thin on all 9 early dates with a kept chain
    "ATPAQ": {"name": "ATP Oil & Gas (bankrupt 2012)", "must_date": "2012-06-20"},
    "SIGM": {"name": "Sigma Designs (liquidated 2018)", "must_date": "2018-06-20"},
}
NAMED_DEAD_MIN_SHARE = 0.90
TXG_FIRST_CHAIN = "2019-12-18"
DEAD_GAP_MAX = 0.05        # later-delisted thin names may trail still-listed ones in chain share by at most 5 points


def log(m):
    print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)


def monthly_dates(window=True):
    ds = sorted(pd.Timestamp(p.stem.split("=")[1]) for p in AV_MONTHLY.glob("date=*.parquet"))
    if window:
        ds = [d for d in ds if WINDOW[0] <= d <= WINDOW[1]]
    return ds


def read_log():
    """Every row of the pull log. `pass` is NOT filtered: the merged log may label
    the thin pull differently from 'monthly'. One row per (date, ticker) is kept,
    preferring ok > no_data > anything else."""
    L = pd.read_sql("SELECT pass, date, ticker, status, symbol, identity, spot_parity, closeunadj, n FROM calls",
                    sqlite3.connect(f"file:{PULL_LOG}?mode=ro", uri=True))
    L["_o"] = L.status.map({"ok": 0, "no_data": 1}).fillna(2)
    return L.sort_values("_o").drop_duplicates(["date", "ticker"], keep="first").drop(columns="_o")


def universe_on(dates, cols=()):
    u = read_on_dates(UNIVERSE, ["date", "ticker", "marketcap", "closeunadj", "eligible_cap2000",
                                 "eligible_cap500", "eligible_cap150", *cols], dates)
    u["ticker"] = u.ticker.astype(str)
    u["thin"] = u.eligible_cap150 & ~u.eligible_cap2000
    return u


def kept_pairs(L):
    """(date, ticker) pairs whose chain passes the identity filter (U.av_keep), per date."""
    import build_option_chain_unified as U
    out = set()
    for d, g in L[L.status == "ok"].groupby("date"):
        for tk, _sym in U.av_keep(g):
            out.add((d, tk))
    return out


def arrival_gate(write=True):
    """Thin slice terminal share per window date, the named presence checks and
    the pool-integrity check. No outcome value is read (presence only)."""
    dates = monthly_dates()
    L = read_log()
    u = universe_on(dates)
    thin = u[u.thin].copy()
    thin["ds"] = thin.date.dt.strftime("%Y-%m-%d")
    m = thin.merge(L[["date", "ticker", "status"]].rename(columns={"date": "ds"}), on=["ds", "ticker"], how="left")
    m["terminal"] = m.status.isin(TERMINAL)
    per = m.groupby("ds").agg(n=("ticker", "size"), terminal=("terminal", "mean"), ok=("status", lambda s: (s == "ok").mean()))
    complete = per.index[per.terminal >= GATE_SHARE].tolist()
    gate_ok = len(dates) == N_WINDOW_DATES and len(complete) >= GATE_MIN_DATES

    kept = kept_pairs(L)
    # named dead thin-slice names
    named = {}
    for tk, spec in NAMED_DEAD.items():
        td = sorted(thin.ds[thin.ticker == tk])
        td_c = [d for d in td if d in complete]
        have = [d for d in td_c if (d, tk) in kept]
        share = len(have) / len(td_c) if td_c else float("nan")
        must = spec["must_date"]
        must_state = ("pending (date not thin-complete)" if must not in complete
                      else "present" if (must, tk) in kept else "MISSING")
        early = [d for d in td if d <= "2008-08-20"]
        named[tk] = {"name": spec["name"], "thin_dates_in_window": len(td), "first_thin": td[0] if td else None,
                     "last_thin": td[-1] if td else None, "must_date": must, "must_date_is_thin": must in td,
                     "must_date_state": must_state, "thin_dates_complete": len(td_c), "with_kept_chain": len(have),
                     "share": share, "early9_present": sum((d, tk) in kept for d in early), "early9_thin": len(early),
                     "pass": bool(td_c and share >= NAMED_DEAD_MIN_SHARE and must_state != "MISSING"
                                  and all((d, tk) in kept for d in early))}
    # TXG (outside the window: a data check only)
    alld = monthly_dates(window=False)
    ut = universe_on(alld)
    ut = ut[(ut.ticker == "TXG") & ut.eligible_cap150 & (ut.date >= pd.Timestamp(TXG_FIRST_CHAIN))]
    ut["ds"] = ut.date.dt.strftime("%Y-%m-%d")
    lt = L[L.ticker == "TXG"].set_index("date").status.to_dict()
    # "chain" = status ok in the pull log (the chain is in the store). Whether it also passes the 5% identity
    # filter is reported separately: 2026-03-18 is ok but 8% off parity, so av_keep drops it (a filter fact, not a gap).
    txg_rows = [{"date": r.ds, "thin": bool(r.thin), "status": lt.get(r.ds, "not attempted"),
                 "kept_chain": lt.get(r.ds) == "ok", "passes_identity": (r.ds, "TXG") in kept} for r in ut.itertuples()]
    c2 = [x for x in txg_rows if not x["thin"]]
    th = [x for x in txg_rows if x["thin"]]
    th_att = [x for x in th if x["status"] != "not attempted"]
    txg = {"cap2000_dates": len(c2), "cap2000_with_chain": sum(x["kept_chain"] for x in c2),
           "thin_dates": [x["date"] for x in th], "thin_attempted": len(th_att),
           "thin_with_chain": sum(x["kept_chain"] for x in th_att),
           "dates_failing_identity_filter": [x["date"] for x in txg_rows if x["kept_chain"] and not x["passes_identity"]],
           "state": ("pending: thin dates not pulled yet" if not th_att else
                     "present" if all(x["kept_chain"] for x in th_att) else "MISSING on an attempted thin date"),
           "pass": bool(all(x["kept_chain"] for x in c2) and all(x["kept_chain"] for x in th_att))}

    # survivorship: later-delisted thin names must have chains about as often as survivors (presence only)
    tmf = sorted((DATA / "sharadar").glob("tickers_master*.csv"))[-1]
    tm = pd.read_csv(tmf, usecols=["ticker", "isdelisted", "lastpricedate"], low_memory=False)
    tm = tm.sort_values("lastpricedate").drop_duplicates("ticker", keep="last")
    mc = m[m.ds.isin(complete)].merge(tm[["ticker", "isdelisted"]], on="ticker", how="left")
    okd = float((mc.status[mc.isdelisted == "Y"] == "ok").mean()) if (mc.isdelisted == "Y").any() else float("nan")
    oka = float((mc.status[mc.isdelisted == "N"] == "ok").mean()) if (mc.isdelisted == "N").any() else float("nan")
    dead_cov = {"chain_share_later_delisted": okd, "chain_share_still_listed": oka,
                "n_later_delisted": int((mc.isdelisted == "Y").sum()), "n_still_listed": int((mc.isdelisted == "N").sum()),
                "rule": f"delisted share >= listed share - {DEAD_GAP_MAX}", "pass": bool(okd >= oka - DEAD_GAP_MAX)}

    # pool integrity (presence only): thin name-dates with a kept chain that are in the panel and the outcome cache
    kd = pd.DataFrame([(d, t) for d, t in kept], columns=["ds", "ticker"])
    tk_ = thin.merge(kd, on=["ds", "ticker"])
    pool = {"thin_name_dates_with_chain": int(len(tk_))}
    if len(tk_):
        dd = sorted(tk_.date.unique())
        p = read_on_dates(PANEL_V2, ["ticker", "date"], dd)
        p["ticker"] = p.ticker.astype(str)
        o = pd.read_parquet(OUTCOME_V2, columns=["ticker", "date"], filters=[("date", "in", [pd.Timestamp(x).to_pydatetime() for x in dd])])
        o["ticker"] = o.ticker.astype(str); o["date"] = pd.to_datetime(o.date)
        pool["share_in_panel"] = float(tk_.merge(p.assign(a=1), on=["date", "ticker"], how="left").a.notna().mean())
        pool["share_in_outcome_cache"] = float(tk_.merge(o.assign(a=1), on=["date", "ticker"], how="left").a.notna().mean())
        pool["pass"] = bool(min(pool["share_in_panel"], pool["share_in_outcome_cache"]) >= POOL_MIN)
    else:
        pool["pass"] = False

    rep = {"store": str(AV), "window": [str(WINDOW[0].date()), str(WINDOW[1].date())],
           "window_dates_on_disk": len(dates), "window_dates_expected": N_WINDOW_DATES,
           "log_pass_labels": sorted(L["pass"].unique().tolist()),
           "thin_complete_dates": complete, "n_thin_complete": len(complete),
           "rule": f"thin slice >= {GATE_SHARE:.0%} terminal (ok/no_data) on >= {GATE_MIN_DATES} of {N_WINDOW_DATES} dates",
           "gate_pass": bool(gate_ok), "named_dead": named, "txg": txg, "pool_integrity": pool, "dead_vs_listed_chain_share": dead_cov,
           "per_date": {d: {"thin_names": int(r.n), "terminal_share": float(r.terminal), "ok_share": float(r.ok)}
                        for d, r in per.iterrows()},
           "phase2_allowed": bool(gate_ok and all(v["pass"] for v in named.values()) and txg["pass"] and pool["pass"] and dead_cov["pass"])}
    if write:
        OUT.mkdir(parents=True, exist_ok=True)
        ARRIVAL.write_text(json.dumps(rep, indent=1, default=str))
    return rep


def phase2_guard(result_path: Path):
    """Real labels are refused unless ALL hold: the pre-reg doc is tracked in git,
    the arrival gate + presence checks pass (recomputed now, not read from a file),
    the chain partitions cover the complete dates, and no earlier result exists."""
    try:
        subprocess.run(["git", "-C", str(REPO), "ls-files", "--error-unmatch", PREREG_DOC], check=True, capture_output=True)
    except subprocess.CalledProcessError:
        raise SystemExit(f"--phase2 refused: {PREREG_DOC} is not tracked in git")
    rep = arrival_gate(write=True)
    if not rep["gate_pass"]:
        raise SystemExit(f"--phase2 refused: arrival gate FAIL: thin slice is >= {GATE_SHARE:.0%} terminal on "
                         f"{rep['n_thin_complete']} of {rep['window_dates_on_disk']} window dates (need >= {GATE_MIN_DATES} of {N_WINDOW_DATES})")
    if not rep["phase2_allowed"]:
        bad = [k for k, v in rep["named_dead"].items() if not v["pass"]] + ([] if rep["txg"]["pass"] else ["TXG"]) + \
              ([] if rep["pool_integrity"]["pass"] else ["pool_integrity"]) + \
              ([] if rep["dead_vs_listed_chain_share"]["pass"] else ["dead_vs_listed_chain_share"])
        raise SystemExit(f"--phase2 refused: presence checks FAIL: {bad} (see {ARRIVAL})")
    on_disk = {p.stem.split("=")[1] for p in CHAIN.glob("date=*.parquet")}
    miss = [d for d in rep["thin_complete_dates"] if d not in on_disk]
    stale = [d for d in rep["thin_complete_dates"] if d in on_disk and
             (CHAIN / f"date={d}.parquet").stat().st_mtime < (AV_MONTHLY / f"date={d}.parquet").stat().st_mtime]
    if miss or stale or not FEATS.exists():
        raise SystemExit(f"--phase2 refused: chain/features missing or older than the store ({len(miss)} missing, "
                         f"{len(stale)} stale); run build_chain.py first")
    if result_path.exists():
        raise SystemExit(f"--phase2 refused: {result_path.name} exists; a re-run is an iteration (cap 3) and must be written "
                         "into the doc and committed first, then the old file moved aside by hand")
    return [pd.Timestamp(d) for d in rep["thin_complete_dates"]]


def newey_west_mean_t(x, lag=39):
    """Verbatim reset2026/era_transfer.newey_west_mean_t (Bartlett kernel)."""
    x = np.asarray(x, dtype=np.float64)
    x = x[np.isfinite(x)]
    n = len(x)
    if n < 10:
        return {"mean": float(x.mean()) if n else np.nan, "t": np.nan, "n": n}
    xc = x - x.mean()
    L = min(lag, n - 1)
    var = np.dot(xc, xc) / n
    for l in range(1, L + 1):
        w = 1.0 - l / (L + 1.0)
        var += 2.0 * w * (np.dot(xc[l:], xc[:-l]) / n)
    var = max(var, 1e-12)
    return {"mean": float(x.mean()), "t": float(x.mean() / np.sqrt(var / n)), "n": int(n)}
