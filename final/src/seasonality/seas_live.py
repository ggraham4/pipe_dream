"""
WO-20 (2026-09-27): LIVE `seas` (Heston-Sadka return seasonality) at any
date t, with the WO-18 definition exactly (build_seas.py; constants imported
from there so the definition lives in one place):

    target month  T = t + 28 calendar days;  m = T.month, Y = T.year
    r(i, y, m)    = ME(i, y, m) / ME(i, y, m-1) - 1, ME = ticker i's LAST
                    finite, positive SEP closeadj in that calendar month;
                    both months must exist for i, otherwise NaN
    seas(i, t)    = mean of r(i, y, m) over y = Y-10..Y-1 with finite r;
                    NaN when fewer than 5 are finite. Sign +1.

Prices: data/sharadar/panel/stocks/<YYYY-MM>.parquet, the SEP month files the
WO-14 refresh (refresh_working_panel.py / sharadar_pull_pit_panel.py) reads
and tops up. Only the 20 month files a date needs are opened (months
(y, m) and (y, m-1), y = Y-10..Y-1). Computed at SCORE TIME (current_signal_
composite.py, seas_forward.py): no panel column, no stored panel row changes.

PIT: the latest month used is (Y-1, m); its last calendar day is asserted
< t, and every row read is dated < t.

SPLIT/DIVIDEND BASIS: closeadj is re-based to its pull date. Both months of
one return must come from the same pull. Today every month a live date needs
(<= 2025-12) is in the one 2026-09-09 bulk pull; 2026-09 was re-pulled
2026-09-26. The first live date whose returns cross into re-pulled months is
around 2027-08 (target 2027-09 uses the 2026-08 -> 2026-09 return). The
`basis_mtime_span_days` field in the info dict reports the file-mtime spread
of the files used; > 2 days is flagged (`basis_flag`). See
final/models/2026-09-27-wo20-seas-live.md.

    python final/src/seasonality/seas_live.py selftest     # 2019 dates vs seas_factor_v2.parquet (1e-9)
    python final/src/seasonality/seas_live.py handcheck    # AAPL, independent code, latest panel date
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "reset2026"))
import build_seas as B  # noqa: E402  (TARGET_DAYS, N_YEARS, MIN_YEARS, SEP_MAIN)

SEP_DIR = B.SEP_MAIN
TARGET_DAYS, N_YEARS, MIN_YEARS = B.TARGET_DAYS, B.N_YEARS, B.MIN_YEARS
BASIS_FLAG_DAYS = 2.0


def _ym(y, m0):
    """(year, 0-based month) -> file stem."""
    return f"{y:04d}-{m0 + 1:02d}"


def target_ym(t):
    T = pd.Timestamp(t) + pd.Timedelta(days=TARGET_DAYS)
    return T.year * 12 + T.month - 1


def month_end(ym, t, sep_dir=SEP_DIR):
    """{ticker: last finite positive closeadj} for integer month index ym."""
    f = Path(sep_dir) / f"{_ym(ym // 12, ym % 12)}.parquet"
    if not f.exists():
        raise SystemExit(f"seas_live: SEP month file missing: {f}")
    d = pd.read_parquet(f, columns=["ticker", "date", "closeadj"])
    d["date"] = pd.to_datetime(d["date"])
    assert (d["date"].dt.strftime("%Y-%m") == f.stem).all(), f"{f} has rows outside its month"
    assert d["date"].max() < pd.Timestamp(t), f"PIT BREACH: {f} has rows dated >= {pd.Timestamp(t).date()}"
    d = d[np.isfinite(d["closeadj"]) & (d["closeadj"] > 0)]
    d = d.sort_values(["ticker", "date"]).drop_duplicates("ticker", keep="last")
    d["ticker"] = d["ticker"].astype(str)
    return d.set_index("ticker")["closeadj"], f


def seas_asof(tickers, t, sep_dir=SEP_DIR, spin_events_adj=None):
    """Returns (frame [ticker, seas, seas_nyears, target_ym] aligned to `tickers`, info).
    WO-57 (opt-in): `spin_events_adj` = (ticker, exdt, m) with m the closeadj-series factor
    (1 + r_closeadj) / (1 + r_CRSP); a monthly return whose calendar month contains exdt is divided by m,
    which equals build_seas with pre-exdt month-ends x m (spinfix.adjust.adjust_month_ends)."""
    t = pd.Timestamp(t)
    tym = target_ym(t)
    last_used = tym - 12
    last_day = pd.Timestamp(year=last_used // 12, month=last_used % 12 + 1, day=1) + pd.offsets.MonthEnd(0)
    assert last_day < t, f"PIT BREACH: month {_ym(last_used // 12, last_used % 12)} ends {last_day.date()} >= t {t.date()}"
    tick = pd.Index(pd.Series(list(tickers), dtype=str))
    S = np.zeros(len(tick)); N = np.zeros(len(tick))
    files = []
    for k in range(1, N_YEARS + 1):            # same order as build_seas.seas_table
        ym = tym - 12 * k
        cur, f1 = month_end(ym, t, sep_dir)
        prev, f0 = month_end(ym - 1, t, sep_dir)
        files += [f0, f1]
        r = (cur / prev.reindex(cur.index) - 1.0).reindex(tick).to_numpy(np.float64)
        if spin_events_adj is not None and len(spin_events_adj):
            ex = pd.to_datetime(spin_events_adj["exdt"])
            e = spin_events_adj[(ex.dt.year * 12 + ex.dt.month - 1) == ym]
            if len(e):
                div = e.groupby(e["ticker"].astype(str))["m"].prod().reindex(tick).fillna(1.0).to_numpy(np.float64)
                r = (1.0 + r) / div - 1.0
        f = np.isfinite(r)
        S += np.where(f, r, 0.0); N += f
    with np.errstate(invalid="ignore", divide="ignore"):
        seas = np.where(N >= MIN_YEARS, S / N, np.nan)
    mt = [p.stat().st_mtime for p in files]
    span = (max(mt) - min(mt)) / 86400.0
    info = {"t": t.date().isoformat(), "target_month": _ym(tym // 12, tym % 12),
            "months_used": f"{_ym((tym - 12 * N_YEARS - 1) // 12, (tym - 12 * N_YEARS - 1) % 12)}.."
                           f"{_ym(last_used // 12, last_used % 12)}",
            "files_used": len(set(files)), "basis_mtime_span_days": round(span, 3),
            "basis_flag": bool(span > BASIS_FLAG_DAYS),
            "n": int(len(tick)), "finite": int(np.isfinite(seas).sum()),
            "coverage": float(np.isfinite(seas).mean()) if len(tick) else float("nan")}
    out = pd.DataFrame({"ticker": tick.to_numpy(), "seas": seas, "seas_nyears": N.astype(int), "target_ym": tym})
    return out, info


# ------------------------------------------------------------------ checks
SELFTEST_DATES = ["2019-01-02", "2019-03-15", "2019-06-03", "2019-10-28", "2019-12-31"]


def selftest(ref=None):
    """Live function on in-era 2019 dates == WO-18 seas_factor_v2.parquet to 1e-9
    (all panel tickers on the date, NaN pattern and seas_nyears included).
    Dates cover: t+28 in the same month (01-02), the next month (03-15, 06-03, 10-28),
    and across the year boundary (12-31 -> 2020-01 target; months used <= 2019-01)."""
    ref = Path(ref) if ref else B.OUT / "seas_factor_v2.parquet"
    res = {}
    for d in SELFTEST_DATES:
        r = pd.read_parquet(ref, columns=["ticker", "date", "seas", "seas_nyears", "target_ym"],
                            filters=[("date", "==", pd.Timestamp(d))])
        assert len(r) > 1000, (d, len(r))
        live, info = seas_asof(r["ticker"], d)
        a, b = live["seas"].to_numpy(np.float64), r["seas"].to_numpy(np.float64)
        nan_eq = bool((np.isnan(a) == np.isnan(b)).all())
        diff = float(np.nanmax(np.abs(a - b))) if np.isfinite(a).any() else 0.0
        ny_eq = bool((live["seas_nyears"].to_numpy() == r["seas_nyears"].to_numpy()).all())
        tym_eq = bool((live["target_ym"].to_numpy() == r["target_ym"].to_numpy()).all())
        ok = nan_eq and diff <= 1e-9 and ny_eq and tym_eq
        res[d] = {"rows": int(len(r)), "finite": int(np.isfinite(b).sum()), "max_abs_diff": diff,
                  "nan_pattern_equal": nan_eq, "nyears_equal": ny_eq, "target_ym_equal": tym_eq,
                  "target_month": info["target_month"], "pass": ok}
        print(d, res[d], flush=True)
        assert ok, f"SELFTEST FAIL on {d}"
    return {"reference": str(ref), "dates": res, "pass": True}


def handcheck(ticker="AAPL", t=None):
    """Independent recomputation for one ticker from raw SEP closeadj (plain
    loops, no shared code with seas_asof beyond reading the files)."""
    sys.path.insert(0, str(HERE.parent / "reset2026"))
    import working_panel as W
    t = pd.Timestamp(t) if t else W.latest_date()
    T = t + pd.Timedelta(days=28)
    rows = []
    for y in range(T.year - 10, T.year):
        m, pm_y, pm = T.month, (y if T.month > 1 else y - 1), (T.month - 1 if T.month > 1 else 12)
        def last_px(yy, mm):
            d = pd.read_parquet(SEP_DIR / f"{yy:04d}-{mm:02d}.parquet", columns=["ticker", "date", "closeadj"])
            d = d[(d["ticker"] == ticker) & (d["closeadj"] > 0)].sort_values("date")
            return (None, None) if d.empty else (str(pd.Timestamp(d["date"].iloc[-1]).date()), float(d["closeadj"].iloc[-1]))
        d1, p1 = last_px(y, m)
        d0, p0 = last_px(pm_y, pm)
        r = (p1 / p0 - 1.0) if (p1 and p0) else None
        rows.append({"year": y, "month": m, "prev_me": [d0, p0], "me": [d1, p1], "ret": r})
    rets = [x["ret"] for x in rows if x["ret"] is not None]
    hand = sum(rets) / len(rets) if len(rets) >= MIN_YEARS else None
    live, info = seas_asof([ticker], t)
    got = float(live["seas"].iloc[0])
    ok = hand is not None and abs(hand - got) < 1e-12
    out = {"ticker": ticker, "t": t.date().isoformat(), "target": f"{T.year}-{T.month:02d}", "years": rows,
           "hand_seas": hand, "live_seas": got, "abs_diff": abs(hand - got) if hand is not None else None,
           "pass": bool(ok)}
    print(json.dumps(out, indent=1), flush=True)
    assert ok, "HANDCHECK FAIL"
    return out


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "selftest"
    res = selftest(sys.argv[2] if len(sys.argv) > 2 else None) if mode == "selftest" else handcheck(*sys.argv[2:])
    (B.OUT / f"seas_live_{mode}.json").write_text(json.dumps(res, indent=1, default=str))
