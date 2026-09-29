"""
WO-25 data-arrival integrity check for the Alpha Vantage HISTORICAL_OPTIONS
store copied from Gabe's Windows machine. Spec:
final/models/2026-09-29-options-readiness-wo25.md section 1.

    /opt/anaconda3/envs/pipe_dream/bin/python final/src/options_wo25/check_arrival.py \
        [--data-root .../final/data/alphavantage] [--out .../arrival_report.json]

Reads only. Never touches a parquet or the log. Exit code 1 on any FAIL.

Checks
  dates per pass on disk and in pull_log; first/last date
  missing monthly dates vs the pull's own plan (av_options_pull.build_dates),
    split into 2008-01..2019-01 and 2019-02 onward
  per monthly date: share of v2 cap2000-eligible names with a terminal log
    status (ok/no_data); a date is "complete" at >= 0.99
  error rows in pull_log
  half-written dates: leftover *.tmp; every parquet footer reads with > 0 rows;
    no exact duplicate rows within a date (resume re-append); tickers in the
    parquet == tickers logged ok for that date
  WARN only: (sharadar_ticker, contractID) keys that repeat with DIFFERENT
    quotes. AV returns adjusted-deliverable contracts (AIG 1:20 reverse split,
    CAH/CareFusion spin-off, ...) under the standard OCC id. Downstream WO-O1
    drops every such key (it cannot tell which row is the standard one).
  PRAGMA integrity_check on pull_log.sqlite
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sqlite3
import sys
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq

MAIN = Path("/Users/ggraham/pipe_dream/final")
HERE = Path(__file__).resolve().parent
OUT_DIR = HERE.parents[1] / "out" / "options_wo25"
SPLIT = pd.Timestamp("2019-02-01")
COMPLETE_SHARE = 0.99


def load_pull_module():
    """Import final/scripts/av_options_pull.py (build_dates) without running it."""
    for root in (HERE.parents[1], MAIN):
        p = root / "scripts" / "av_options_pull.py"
        if p.exists():
            spec = importlib.util.spec_from_file_location("av_options_pull", p)
            m = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(m)
            return m
    raise SystemExit("av_options_pull.py not found")


def plan_dates(universe: Path):
    P = load_pull_module()
    u = pd.read_parquet(universe, columns=["date", "ticker", "eligible_cap2000", "eligible_cap150"])
    u["date"] = pd.to_datetime(u["date"])
    u150 = u[u.eligible_cap150 & (u.date >= P.FIRST_DATE)]
    trading = pd.DatetimeIndex(sorted(u150.date.unique()))
    monthly, weekly = P.build_dates(trading)
    cap2000 = u[u.eligible_cap2000].groupby("date").ticker.apply(set)
    return [pd.Timestamp(d) for d in monthly], [pd.Timestamp(d) for d in weekly], cap2000


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-root", type=Path, default=MAIN / "data" / "alphavantage")
    ap.add_argument("--universe", type=Path, default=MAIN / "data" / "sharadar" / "downcap_universe_v2.parquet")
    ap.add_argument("--out", type=Path, default=OUT_DIR / "arrival_report.json")
    ap.add_argument("--skip-dup-scan", action="store_true", help="skip the per-file duplicate/ticker scan (fast mode)")
    a = ap.parse_args()
    root = a.data_root
    fails, rep = [], {"data_root": str(root)}

    # ---------------- sqlite
    dbp = root / "pull_log.sqlite"
    if not dbp.exists():
        raise SystemExit(f"FAIL: {dbp} missing")
    con = sqlite3.connect(f"file:{dbp}?mode=ro", uri=True)
    ic = con.execute("PRAGMA integrity_check").fetchall()
    rep["sqlite_integrity_check"] = [r[0] for r in ic]
    if [r[0] for r in ic] != ["ok"]:
        fails.append("sqlite integrity_check not ok")
    log = pd.read_sql("SELECT pass, date, ticker, status, symbol FROM calls", con)
    log["date"] = pd.to_datetime(log["date"])
    rep["log_rows"] = int(len(log))
    rep["log_status_by_pass"] = {p: g.status.value_counts().to_dict() for p, g in log.groupby("pass")}
    err = log[log.status == "error"]
    rep["error_rows"] = int(len(err))
    rep["error_rows_by_date"] = {str(d.date()): int(n) for d, n in err.groupby("date").size().items()}

    # ---------------- plan
    monthly_plan, weekly_plan, cap2000 = plan_dates(a.universe)
    rep["plan"] = {"monthly": len(monthly_plan), "weekly": len(weekly_plan),
                   "monthly_first": str(monthly_plan[0].date()), "monthly_last": str(monthly_plan[-1].date())}

    # ---------------- files
    per_pass = {}
    for pas in ["monthly", "weekly"]:
        d = root / "options" / pas
        files = sorted(d.glob("date=*.parquet")) if d.exists() else []
        tmps = sorted(d.glob("*.tmp")) if d.exists() else []
        if tmps:
            fails.append(f"{pas}: leftover .tmp files {[t.name for t in tmps]}")
        dates_disk = [pd.Timestamp(f.stem.split("=")[1]) for f in files]
        lg = log[log["pass"] == pas]
        dates_log = sorted(lg.date.unique())
        bad = []
        for f in files:
            try:
                md = pq.ParquetFile(f).metadata
                if md.num_rows == 0:
                    bad.append((f.name, "0 rows"))
            except Exception as e:  # noqa: BLE001
                bad.append((f.name, f"unreadable: {type(e).__name__}"))
        if bad:
            fails.append(f"{pas}: bad parquet files {bad}")
        dup, keydup, tick_mismatch = {}, {}, {}
        if not a.skip_dup_scan:
            ok_by_date = lg[lg.status == "ok"].groupby("date").ticker.apply(set)
            for f, dd in zip(files, dates_disk):
                if any(b[0] == f.name for b in bad):
                    continue
                t = pd.read_parquet(f)
                nd = int(t.duplicated().sum())        # exact duplicate rows = resume re-append
                if nd:
                    dup[str(dd.date())] = nd
                nk = int(t.duplicated(["sharadar_ticker", "contractID"]).sum())
                if nk:   # same OCC id, different quotes: AV adjusted-deliverable contracts (WARN)
                    keydup[str(dd.date())] = nk
                have = set(t.sharadar_ticker.unique())
                want = ok_by_date.get(dd, set())
                if have != want:
                    tick_mismatch[str(dd.date())] = {"in_parquet_not_logged_ok": len(have - want),
                                                     "logged_ok_not_in_parquet": len(want - have)}
            if dup:
                fails.append(f"{pas}: exact duplicate rows on {len(dup)} dates (resume re-append)")
            if tick_mismatch:
                fails.append(f"{pas}: parquet tickers != logged-ok tickers on {len(tick_mismatch)} dates")
        log_no_file = sorted(set(pd.DatetimeIndex(lg[lg.status == "ok"].date.unique())) - set(dates_disk))
        if log_no_file:
            fails.append(f"{pas}: {len(log_no_file)} dates logged ok but no parquet")
        per_pass[pas] = {
            "dates_on_disk": len(files), "dates_in_log": len(dates_log),
            "first": str(min(dates_disk).date()) if dates_disk else None,
            "last": str(max(dates_disk).date()) if dates_disk else None,
            "bad_files": bad, "tmp_files": [t.name for t in tmps],
            "exact_duplicate_rows_by_date": dup,
            "WARN_key_duplicates_differing_quotes_by_date": keydup,
            "ticker_mismatch_by_date": tick_mismatch,
            "logged_ok_without_parquet": [str(x.date()) for x in log_no_file],
        }
    rep["passes"] = per_pass

    # ---------------- monthly completeness vs plan, cap2000
    lm = log[log["pass"] == "monthly"]
    term = lm[lm.status.isin(["ok", "no_data"])].groupby("date").ticker.apply(set)
    rows = []
    for d in monthly_plan:
        el = cap2000.get(d, set())
        got = term.get(d, set())
        share = len(el & got) / len(el) if el else float("nan")
        rows.append({"date": d, "cap2000_eligible": len(el), "cap2000_terminal": len(el & got),
                     "share": share, "complete": bool(el) and share >= COMPLETE_SHARE})
    C = pd.DataFrame(rows)
    seg = {}
    for name, m in (("2008-01..2019-01", C.date < SPLIT), ("2019-02..", C.date >= SPLIT)):
        s = C[m]
        seg[name] = {"planned": int(len(s)), "complete": int(s.complete.sum()),
                     "missing_or_partial": [f"{r.date.date()} ({r.share:.3f})" for r in s[~s.complete].itertuples()]}
    rep["monthly_cap2000_completeness"] = seg
    rep["monthly_dates_complete"] = [str(d.date()) for d in C[C.complete].date]
    extra = sorted(set(pd.DatetimeIndex(lm.date.unique())) - set(monthly_plan))
    rep["monthly_dates_not_in_plan"] = [str(d.date()) for d in extra]
    rep["exp_b_nominate_dates_complete"] = int(C[(C.date < pd.Timestamp("2019-01-01")) & C.complete].shape[0])
    rep["exp_b_screen_ready"] = rep["exp_b_nominate_dates_complete"] >= 120
    rep["exp_b_confirm_ready"] = bool(C[(C.date >= pd.Timestamp("2019-01-01"))
                                        & (C.date <= pd.Timestamp("2026-08-31"))].complete.all())

    rep["fails"] = fails
    rep["overall"] = "PASS" if not fails else "FAIL"
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(rep, indent=2, default=str))
    print(f"monthly: {per_pass['monthly']['dates_on_disk']} dates on disk "
          f"({per_pass['monthly']['first']}..{per_pass['monthly']['last']}); plan {len(monthly_plan)}")
    for k, v in seg.items():
        print(f"  {k}: {v['complete']}/{v['planned']} complete at cap2000 (>= {COMPLETE_SHARE})")
    print(f"weekly: {per_pass['weekly']['dates_on_disk']} dates on disk")
    print(f"error rows in pull_log: {rep['error_rows']}")
    print(f"Exp B screen ready (>=120 nominate dates): {rep['exp_b_screen_ready']}; "
          f"confirm ready: {rep['exp_b_confirm_ready']}")
    for f in fails:
        print(f"FAIL: {f}")
    print(f"overall {rep['overall']} -> {a.out}")
    sys.exit(0 if not fails else 1)


if __name__ == "__main__":
    main()
