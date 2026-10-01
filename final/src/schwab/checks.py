"""WO-41 acceptance tests, fixed on 2026-10-01 before any data existed.

    T1  5 consecutive trading days with >= 99% of the target universe pulled.
    T2  Schwab daily close vs Sharadar SEP close within 1bp on >= 99.5% of
        name-days; mismatches listed by name.
    T3  Option chains for AAPL, SPY, MSFT, NVDA, JPM contain every listed
        monthly expiry, and bid <= ask on >= 99.9% of rows.
    T4  Quote timestamps within the session on >= 99% of rows; stale-quote
        rate reported separately for non-cap2000 names.

Each test returns dict(name, status, detail, ...) with status PASS, FAIL or
NOT_EVALUABLE (not enough data yet). Offline: reads only the parquet/csv
files under the Schwab data root and the Sharadar working panel.
"""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from . import store
from .parse import default_session_bounds

N_DAYS = 5
COVERAGE_MIN = 0.99
CLOSE_TOL = 1e-4            # 1bp
CLOSE_SHARE_MIN = 0.995
BID_ASK_MIN = 0.999
SESSION_SHARE_MIN = 0.99
SESSION_GRACE = timedelta(minutes=15)   # some ETF options quote until 16:15 ET


def _res(name, status, detail, **extra):
    return dict(name=name, status=status, detail=detail, **extra)


TARGET_UNIVERSE = "cap150"      # the acceptance denominator; a custom/smoke-test list never counts


def _universe_for(root, d, target_only=True):
    part = Path(root) / "universe" / f"date={d}"
    target = part / f"universe_{TARGET_UNIVERSE}.csv"
    if target.exists():
        return pd.read_csv(target, dtype={"ticker": str}, keep_default_na=False,
                           na_values=[""])
    files = [] if target_only or not part.exists() else sorted(part.glob("universe_*.csv"))
    if not files:
        return None
    return max((pd.read_csv(f, dtype={"ticker": str}) for f in files), key=len)


def target_dates(root):
    base = Path(root) / "universe"
    return sorted(p.parent.name[5:] for p in base.glob(f"date=*/universe_{TARGET_UNIVERSE}.csv"))


def latest_consecutive_days(dates, n=N_DAYS):
    """Last n dates of `dates` if they are n consecutive NYSE trading days, else None."""
    dates = sorted(d for d in dates if store.is_trading_day(d))
    if len(dates) < n:
        return None
    last = dates[-n:]
    expected = store.trading_days_between(last[0], last[-1])
    return last if [str(x) for x in expected] == last else None


def t1_coverage(root, log=None):
    dates = target_dates(root)
    last = latest_consecutive_days(dates)
    if last is None:
        return _res("T1 coverage", "NOT_EVALUABLE",
                    f"need {N_DAYS} consecutive trading days pulled on the {TARGET_UNIVERSE} universe; "
                    f"have {dates[-N_DAYS:]}")
    per_day, ok = [], True
    for d in last:
        uni = _universe_for(root, d)
        n = len(uni)
        target = set(uni["ticker"])
        cov = {}
        q = store.read_kind(root, "quotes", d, ["ticker"])
        cov["quotes"] = len(target & set(q["ticker"])) / n if len(q) else 0.0
        p = store.read_kind(root, "pricehistory", d, ["ticker"])
        cov["pricehistory"] = len(target & set(p["ticker"])) / n if len(p) else 0.0
        c = store.read_kind(root, "chains", d, ["ticker"])
        with_chain = target & set(c["ticker"]) if len(c) else set()
        answered = set(with_chain)
        if log is not None:      # a name with no listed options is an answer, not a miss
            answered |= {t for t, s in log.best_status(d, "chains").items()
                         if s in ("ok", "empty")} & target
        cov["chains_answered"] = len(answered) / n
        cov["chains_with_contracts"] = len(with_chain) / n
        day_ok = all(cov[k] >= COVERAGE_MIN for k in ("quotes", "pricehistory", "chains_answered"))
        ok &= day_ok
        per_day.append({"date": d, "n_universe": n, **{k: round(v, 4) for k, v in cov.items()},
                        "pass": day_ok})
    detail = "; ".join(
        f"{r['date']}: quotes {r['quotes']:.2%}, pricehistory {r['pricehistory']:.2%}, "
        f"chains answered {r['chains_answered']:.2%} (with contracts "
        f"{r['chains_with_contracts']:.2%}) of {r['n_universe']}" for r in per_day)
    return _res("T1 coverage", "PASS" if ok else "FAIL", detail, per_day=per_day)


def schwab_closes(root):
    """Final daily candles, latest pull per (ticker, candle_date)."""
    frames = []
    for d in store.partition_dates(root, "pricehistory"):
        frames.append(store.read_kind(root, "pricehistory", d,
                                      ["ticker", "candle_date", "close", "is_final",
                                       "pulled_at_utc"]))
    if not frames:
        return pd.DataFrame(columns=["ticker", "candle_date", "close"])
    df = pd.concat(frames, ignore_index=True)
    df = df[df["is_final"] & df["close"].notna()]
    df = df.sort_values("pulled_at_utc").drop_duplicates(["ticker", "candle_date"], keep="last")
    return df[["ticker", "candle_date", "close"]]


def t2_close_vs_sep(root, panel_path=store.WORKING_PANEL, out_dir=None):
    sc = schwab_closes(root)
    if sc.empty:
        return _res("T2 close vs Sharadar SEP", "NOT_EVALUABLE", "no final Schwab daily candles yet")
    if not Path(panel_path).exists():
        return _res("T2 close vs Sharadar SEP", "NOT_EVALUABLE", f"panel not found: {panel_path}")
    dates = sorted(sc["candle_date"].unique())
    sep = pd.read_parquet(panel_path, columns=["ticker", "date", "close"],
                          filters=[("date", ">=", dates[0]), ("date", "<=", dates[-1])])
    sep["ticker"] = sep["ticker"].astype(str)
    sep["candle_date"] = sep["date"].astype(str).str[:10]
    m = sc.merge(sep[["ticker", "candle_date", "close"]], on=["ticker", "candle_date"],
                 suffixes=("_schwab", "_sep"))
    m = m[m["close_sep"].notna() & (m["close_sep"] > 0)]
    if m.empty:
        return _res("T2 close vs Sharadar SEP", "NOT_EVALUABLE",
                    f"no overlapping name-days (Schwab {dates[0]}..{dates[-1]}; the Sharadar "
                    "panel may not have those days yet)")
    m["rel_diff"] = (m["close_schwab"] - m["close_sep"]) / m["close_sep"]
    bad = m[m["rel_diff"].abs() > CLOSE_TOL].sort_values("rel_diff", key=abs, ascending=False)
    share = 1 - len(bad) / len(m)
    path = None
    if out_dir is not None and len(bad):
        Path(out_dir).mkdir(parents=True, exist_ok=True)
        path = Path(out_dir) / f"close_mismatches_{dates[0]}_{dates[-1]}.csv"
        bad.to_csv(path, index=False)
    names = ", ".join(f"{r.ticker} {r.candle_date} {r.rel_diff:+.2%}"
                      for r in bad.head(25).itertuples())
    detail = (f"{share:.3%} of {len(m)} name-days within 1bp ({m['candle_date'].nunique()} days, "
              f"{m['ticker'].nunique()} names); {len(bad)} mismatches"
              + (f": {names}" + (" ..." if len(bad) > 25 else "") if len(bad) else "")
              + (f"; full list {path}" if path else ""))
    return _res("T2 close vs Sharadar SEP", "PASS" if share >= CLOSE_SHARE_MIN else "FAIL", detail,
                share=share, n=len(m), mismatches=bad)


def t3_chains(root, session_date=None):
    dates = store.partition_dates(root, "chains")
    if not dates:
        return _res("T3 reference chains", "NOT_EVALUABLE", "no chain snapshots yet")
    d = session_date or dates[-1]
    ch = store.read_kind(root, "chains", d, ["ticker", "expiry", "bid", "ask", "snapshot"])
    ex = store.read_kind(root, "expirations", d)
    ch = ch[ch["ticker"].isin(store.REFERENCE_NAMES)] if len(ch) else ch
    problems, lines = [], []
    for t in store.REFERENCE_NAMES:
        c = ch[ch["ticker"] == t] if len(ch) else ch
        if not len(c):
            problems.append(f"{t}: no chain")
            continue
        c = c[c["snapshot"] == c["snapshot"].max()]
        have = set(c["expiry"])
        listed = set()
        if len(ex):
            e = ex[(ex["ticker"] == t) & (ex["expiration_type"].astype(str) == "S")]
            listed = set(e["expiry"])
        if not listed:
            problems.append(f"{t}: no listed-expiry file (expirationchain) to compare with")
        # independent calendar check: 3rd Fridays out to the furthest listed monthly.
        # Far-dated months (LEAPS) are listed only for some months, so the calendar
        # check covers the next 3 months, which are always listed.
        cal = {str(x) for x in store.monthly_expiries(d, date.fromisoformat(d) + timedelta(days=92))
               if str(x) > d}
        missing = sorted((listed | cal) - have)
        if missing:
            problems.append(f"{t}: missing monthly expiries {missing}")
        lines.append(f"{t} {len(listed)} listed monthlies, {len(have)} expiries in chain")
    both = ch[ch["bid"].notna() & ch["ask"].notna()] if len(ch) else ch
    share = float((both["bid"] <= both["ask"]).mean()) if len(both) else float("nan")
    if len(both) and share < BID_ASK_MIN:
        problems.append(f"bid <= ask on only {share:.3%} of rows")
    if not len(both):
        problems.append("no rows with both bid and ask")
    detail = f"{d}: " + "; ".join(lines) + f"; bid<=ask {share:.3%} of {len(both)} rows"
    if problems:
        detail += " | PROBLEMS: " + "; ".join(problems)
    return _res("T3 reference chains", "FAIL" if problems else "PASS", detail, bid_le_ask=share)


def t4_quote_times(root, session_date=None):
    dates = store.partition_dates(root, "quotes")
    if not dates:
        return _res("T4 quote timestamps", "NOT_EVALUABLE", "no quote snapshots yet")
    d = session_date or dates[-1]
    q = store.read_kind(root, "quotes", d, ["ticker", "quote_time_utc", "snapshot"])
    start, end = default_session_bounds(d)
    hrs = store.read_kind(root, "hours", d)
    src = "default 09:30-16:00 ET"
    if len(hrs):
        eq = hrs[(hrs["market"] == "equity") & hrs["regular_start_utc"].notna()]
        if len(eq):
            start, end = eq["regular_start_utc"].iloc[-1], eq["regular_end_utc"].iloc[-1]
            src = "stored market hours"
    qt = pd.to_datetime(q["quote_time_utc"], utc=True)
    start, end = pd.Timestamp(start), pd.Timestamp(end) + SESSION_GRACE
    q = q.assign(in_session=(qt >= start) & (qt <= end), stale=qt.isna() | (qt < start))
    share = float(q["in_session"].mean())
    uni = _universe_for(root, d, target_only=False)
    non2000 = "universe file missing"
    if uni is not None and "in_cap2000" in uni:
        cap = set(uni.loc[uni["in_cap2000"].astype(bool), "ticker"])
        a, b = q[q["ticker"].isin(cap)], q[~q["ticker"].isin(cap)]
        non2000 = (f"stale-quote rate cap2000 {a['stale'].mean():.3%} of {len(a)}, "
                   f"non-cap2000 {b['stale'].mean():.3%} of {len(b)}")
    detail = (f"{d}: {share:.3%} of {len(q)} quote rows inside the session ({src}, +15 min); "
              f"{non2000}")
    return _res("T4 quote timestamps", "PASS" if share >= SESSION_SHARE_MIN else "FAIL", detail,
                share=share)


def run_all(root, panel_path=store.WORKING_PANEL, log=None):
    return [t1_coverage(root, log), t2_close_vs_sep(root, panel_path, Path(root) / "checks"),
            t3_chains(root), t4_quote_times(root)]
