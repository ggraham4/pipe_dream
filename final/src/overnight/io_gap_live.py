"""
WO-27-io-fwd (2026-09-29): LIVE `io_gap` at any date t, computed at SCORE TIME
from the live SEP month files (data/sharadar/panel/stocks/<YYYY-MM>.parquet,
the files the WO-14 refresh / Retrain top-up writes). No panel column, no
stored row changes. Pre-registration: final/models/2026-09-29-wo27-io-forward-ledger.md.

Definition = the FROZEN one in build_io_gap.py (b451e52), imported, not
re-implemented: `daily_components` (validity filters, r_id, r_on),
`market_calendar` (SEP dates with >= 1000 tickers), `io_gap_for` (252 market
days ending at t inclusive, >= 200 valid, 252 * mean(r_id - r_on)), and the
constants WINDOW / MIN_VALID / MAX_ABS_LOG / MAX_GAP_DAYS / CAL_MIN_TICKERS.
Sign +1. Only the loader is local, because the frozen `load_sep` is bound to
2005-01..2019-12 and asserts every row < 2020-01-01: it reads the month files
t-14 .. t with the same columns / dtype / sort / dedup, and keeps only rows
dated <= t (the frozen definition uses close_t, known before the label's
entry at open[t+1]). PIT asserted on the materialized frame and on every
finite value's last price date.

BASIS GUARD (pre-registered, sec. 3 of the doc). A month file is written
whole by one pull (sharadar_pull_pit_panel.write_month), and closeadj / open /
close are re-based to that pull's date. The Retrain top-up re-pulls only from
the resume month, so adjacent month files can be on different bases (today:
2005-01..2026-08 from the 2026-09-09 bulk pull, 2026-09 re-pulled later). The
one cross-row quantity in io_gap is closeadj_prev in r_on. So, for a row d
whose ticker's previous SEP row sits in a DIFFERENT month file whose mtime
differs from d's file by more than BASIS_TOL_HOURS (a "mismatched boundary"):
  R_un  = log(closeunadj_d / closeunadj_prev)   (raw prices: basis-free)
  R_adj = log(closeadj_d / closeadj_prev)       (as stored: mixed basis)
  - if R_adj - R_un lies inside [log 0.8, log 1.25] (WO-14's split band;
    dividend-scale basis drift), r_tot(d) := R_un ("splice"), so
    r_on = R_un - r_id, and the frozen validity rules are re-applied with it;
  - otherwise (split-like / ADR-ratio-like, or closeunadj missing) row d is
    NOT VALID ("drop"), like `no_prev`.
The splice is exact unless a dividend goes ex on d itself (then that
dividend is missed for that one day). Every other row is within one file,
hence one basis. In-era all files come from one bulk pull, so the guard
changes nothing there (selftest).

    python final/src/overnight/io_gap_live.py selftest     # in-era dates vs io_gap_factor_v2.parquet (1e-9)
    python final/src/overnight/io_gap_live.py handcheck    # AAPL, independent loop code on raw SEP
    python final/src/overnight/io_gap_live.py steady       # in-era: guard at EVERY month boundary (worst case)
    python final/src/overnight/io_gap_live.py gate_a [t]   # live basis diagnostics (+ fresh per-ticker pulls, <= 10 API calls)
"""
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "reset2026"))
import build_io_gap as B  # noqa: E402  (frozen definition)

SEP_DIR = B.SEP_MAIN
WINDOW, MIN_VALID, COL = B.WINDOW, B.MIN_VALID, B.COL
LOAD_MONTHS = 14                 # month files t-14 .. t (>= 13 full months before t's month)
BASIS_TOL_HOURS = 6.0            # files written > 6 h apart = different pulls = different basis
SEP_COLS = ["ticker", "date", "open", "high", "low", "close", "volume", "closeadj"]
EXTRA_COLS = ("closeunadj",)     # basis guard only
SPLIT_BAND = (float(np.log(0.8)), float(np.log(1.25)))
OUT = HERE.parents[1] / "out" / "overnight"
REF = Path("/Users/ggraham/pipe_dream/.claude/worktrees/overnight-intraday/final/out/overnight/io_gap_factor_v2.parquet")


def log(m):
    print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)


def _stems(t, n=LOAD_MONTHS):
    p = pd.Period(pd.Timestamp(t), freq="M")
    return [(p - k).strftime("%Y-%m") for k in range(n, -1, -1)]


def load_live(t, sep_dir=SEP_DIR, extra_cols=()):
    """SEP rows dated <= t from month files t-14..t, frozen dtype/sort/dedup
    (build_io_gap.load_sep), plus `_file` (index into the returned file list).
    Raises SystemExit when a month file is missing."""
    t = pd.Timestamp(t)
    iso = t.date().isoformat()
    files, frames = [], []
    for k, stem in enumerate(_stems(t)):
        f = Path(sep_dir) / f"{stem}.parquet"
        if not f.exists():
            raise SystemExit(f"io_gap_live: SEP month file missing: {f}")
        d = pq.read_table(f, columns=SEP_COLS + list(extra_cols), filters=[("date", "<=", iso)]).to_pandas()
        d["date"] = pd.to_datetime(d["date"])
        assert (d["date"].dt.strftime("%Y-%m") == f.stem).all(), f"{f} has rows outside its month"
        assert (d["date"] <= t).all(), f"PIT BREACH: {f} rows dated > {iso} survived the filter"
        d["_file"] = k
        files.append(f)
        frames.append(d)
    s = pd.concat(frames, ignore_index=True)
    s["ticker"] = s["ticker"].astype(str)
    s = s.sort_values(["ticker", "date"]).drop_duplicates(["ticker", "date"], keep="last").reset_index(drop=True)
    assert s["date"].max() <= t, "PIT BREACH"
    return s, files


def basis_groups(files):
    """mtime (s) per loaded file; two files share a basis iff |mtime diff| <= BASIS_TOL_HOURS."""
    return np.array([p.stat().st_mtime for p in files], dtype=np.float64)


def apply_basis_guard(s, flags, mtimes, tol_hours=BASIS_TOL_HOURS, every_boundary=False):
    """Splice / drop rows on a mismatched-basis month boundary (module doc).
    every_boundary=True treats every month boundary as mismatched (the
    steady-state worst case, for the in-era cost check). Adds column
    `basis_action`: 0 untouched, 1 spliced, 2 dropped."""
    first = s["ticker"].ne(s["ticker"].shift()).to_numpy()
    f = s["_file"].to_numpy()
    pf = np.where(first, -1, np.roll(f, 1))
    cross = (~first) & (pf != f)
    if every_boundary:
        mism = cross
    else:
        mism = cross & (np.abs(mtimes[f] - mtimes[np.maximum(pf, 0)]) / 3600.0 > tol_hours)
    pos = lambda x: np.isfinite(x) & (x > 0)  # noqa: E731
    cu = s["closeunadj"].to_numpy(np.float64)
    pcu = np.where(first, np.nan, np.roll(cu, 1))
    a = s["closeadj"].to_numpy(np.float64)
    pa = np.where(first, np.nan, np.roll(a, 1))
    o, c = s["open"].to_numpy(np.float64), s["close"].to_numpy(np.float64)
    with np.errstate(divide="ignore", invalid="ignore"):
        r_un, r_adj, r_id = np.log(cu / pcu), np.log(a / pa), np.log(c / o)
        r_on = r_un - r_id
    disc = r_adj - r_un
    splitlike = ~(pos(cu) & pos(pcu)) | ~((disc >= SPLIT_BAND[0]) & (disc <= SPLIT_BAND[1]))
    base = ~flags[["bad_open", "bad_close", "no_prev", "zero_volume", "open_outside_range"]].any(axis=1).to_numpy()
    new_valid = base & ~splitlike & (np.abs(r_id) <= B.MAX_ABS_LOG) & (np.abs(r_on) <= B.MAX_ABS_LOG)
    was_valid = s["valid"].to_numpy().copy()
    v = np.where(mism, new_valid, was_valid)
    s["valid"] = v
    s["r_id"] = np.where(mism, np.where(new_valid, r_id, 0.0), s["r_id"].to_numpy())
    s["r_on"] = np.where(mism, np.where(new_valid, r_on, 0.0), s["r_on"].to_numpy())
    act = np.zeros(len(s), np.int8)
    act[mism & new_valid] = 1
    act[mism & ~new_valid & base & splitlike] = 2
    s["basis_action"] = act
    return s, mism, was_valid


def io_gap_asof(tickers, t, sep_dir=SEP_DIR, guard=True, every_boundary=False, return_inputs=False):
    """Returns (frame [ticker, io_gap, io_nvalid] aligned to `tickers`, info)."""
    t = pd.Timestamp(t)
    s, files = load_live(t, sep_dir, extra_cols=EXTRA_COLS)
    s, flags = B.daily_components(s)
    mt = basis_groups(files)
    if guard:
        s, mism, _was = apply_basis_guard(s, flags, mt, every_boundary=every_boundary)
    else:
        mism = np.zeros(len(s), bool)
        s["basis_action"] = np.zeros(len(s), np.int8)
    cal = B.market_calendar(s)
    qi = int(cal.searchsorted(t))
    if not (qi < len(cal) and cal[qi] == t):
        raise SystemExit(f"io_gap_live: {t.date()} is not a market date (< {B.CAL_MIN_TICKERS} SEP tickers)")
    if qi < WINDOW + 1:
        raise SystemExit(f"io_gap_live: only {qi} market days before {t.date()} loaded (< {WINDOW + 1})")
    # the prev row of the first in-window day must be loadable (<= MAX_GAP_DAYS back)
    first_in = cal[qi - WINDOW + 1]
    assert (first_in - s["date"].min()).days > B.MAX_GAP_DAYS, "load span too short for closeadj_prev"
    tick = pd.Series(list(tickers), dtype=str)
    q = pd.DataFrame({"ticker": tick.to_numpy(), "date": t})
    v, nv, first_used, last_used, _vid = B.io_gap_for(s[["ticker", "date", "r_id", "r_on", "valid"]], cal, q)
    fin = np.isfinite(v)
    assert (last_used[fin] <= np.datetime64(t)).all(), "PIT FAIL: price after t"
    win_lo = cal[qi - WINDOW]
    in_win = (s["date"] > win_lo).to_numpy() & s["ticker"].isin(set(tick)).to_numpy()
    info = {"t": t.date().isoformat(), "files": f"{files[0].stem}..{files[-1].stem}",
            "file_mtimes": {p.stem: pd.Timestamp(m, unit="s").strftime("%Y-%m-%d %H:%M") for p, m in zip(files, mt)},
            "guard": bool(guard), "every_boundary": bool(every_boundary),
            "guarded_rows_all": int(mism.sum()),
            "spliced_rows_in_window": int(((s["basis_action"] == 1).to_numpy() & in_win).sum()),
            "dropped_splitlike_rows_in_window": int(((s["basis_action"] == 2).to_numpy() & in_win).sum()),
            "dropped_splitlike_tickers": sorted(set(s.loc[(s["basis_action"] == 2).to_numpy() & in_win, "ticker"])),
            "guarded_boundaries": sorted({f"{files[a].stem}|{files[b].stem}" for a, b in
                                          zip(np.roll(s['_file'].to_numpy(), 1)[mism], s['_file'].to_numpy()[mism])}),
            "window_first_day": str(cal[qi - WINDOW + 1].date()), "market_days_loaded_before_t": qi,
            "sep_max_date_used": str(pd.Timestamp(last_used[fin].max()).date()) if fin.any() else None,
            "n": int(len(tick)), "finite": int(fin.sum()),
            "coverage": float(fin.mean()) if len(tick) else float("nan")}
    out = pd.DataFrame({"ticker": tick.to_numpy(), COL: v, "io_nvalid": nv})
    if return_inputs:
        return out, info, s, cal
    return out, info


# ------------------------------------------------------------------ checks
SELFTEST_DATES = ["2008-01-02", "2012-12-31", "2015-06-15", "2019-01-02", "2019-12-31"]


def _ref(d):
    r = pd.read_parquet(REF, columns=["ticker", "date", COL, "io_nvalid"], filters=[("date", "==", pd.Timestamp(d))])
    assert len(r) > 1000, (d, len(r))
    return r


def selftest():
    """Live function (guard ON) on in-era dates == frozen io_gap_factor_v2.parquet:
    every panel ticker on the date, io_gap to 1e-9, NaN pattern, io_nvalid exact.
    2008-01-02 / 2019-01-02 windows cross a year boundary; 2012-12-31 / 2019-12-31
    end on a year-end. Also: the local loader == frozen B.load_sep row for row on
    one date's files, and the guard fires 0 times in-era (one bulk pull)."""
    res = {}
    for d in SELFTEST_DATES:
        r = _ref(d)
        live, info = io_gap_asof(r["ticker"], d)
        a, b = live[COL].to_numpy(np.float64), r[COL].to_numpy(np.float64)
        nan_eq = bool((np.isnan(a) == np.isnan(b)).all())
        diff = float(np.nanmax(np.abs(a - b))) if np.isfinite(b).any() else 0.0
        nv_eq = bool((live["io_nvalid"].to_numpy() == r["io_nvalid"].to_numpy()).all())
        ok = nan_eq and diff <= 1e-9 and nv_eq and info["guarded_rows_all"] == 0
        res[d] = {"rows": int(len(r)), "finite": int(np.isfinite(b).sum()), "max_abs_diff": diff,
                  "nan_pattern_equal": nan_eq, "nvalid_equal": nv_eq, "guarded_rows": info["guarded_rows_all"],
                  "files": info["files"], "pass": ok}
        log(f"{d} {res[d]}")
        assert ok, f"SELFTEST FAIL on {d}"
    # loader identity vs the frozen loader, on the 2019-12-31 file set
    d = pd.Timestamp("2019-12-31")
    s, files = load_live(d)
    fz = B.load_sep(files)
    s2 = s.drop(columns=["_file"])
    same = bool(s2.reset_index(drop=True).equals(fz.reset_index(drop=True)))
    assert same, "loader != frozen load_sep"
    res["loader_equals_frozen_load_sep"] = {"date": str(d.date()), "rows": int(len(fz)), "equal": same}
    return {"reference": str(REF), "dates": res, "pass": True}


def handcheck(ticker="AAPL", t=None):
    """Independent plain-loop recomputation for one ticker from raw SEP (no
    shared code with build_io_gap / io_gap_asof beyond reading the files)."""
    import math
    import working_panel as W
    t = pd.Timestamp(t) if t else W.latest_date()
    iso = t.date().isoformat()
    per = pd.Period(t, freq="M")
    stems = [(per - k).strftime("%Y-%m") for k in range(14, -1, -1)]
    counts, rows, mtime = {}, [], {}
    for k, st in enumerate(stems):
        f = SEP_DIR / f"{st}.parquet"
        mtime[k] = f.stat().st_mtime
        d = pd.read_parquet(f)
        d = d[d["date"].astype(str) <= iso]
        for dt, n in d.groupby(d["date"].astype(str))["ticker"].nunique().items():
            counts[dt] = counts.get(dt, 0) + n
        for x in d[d["ticker"] == ticker].itertuples(index=False):
            rows.append((str(x.date), float(x.open), float(x.high), float(x.low), float(x.close),
                         float(x.volume), float(x.closeadj), float(x.closeunadj), k))
    rows.sort()
    cal = sorted(dt for dt, n in counts.items() if n >= 1000)
    assert cal[-1] == iso, (cal[-1], iso)
    win = set(cal[-252:])
    tot_g = {True: 0.0, False: 0.0}; nval = {True: 0, False: 0}
    guarded_days = []
    lo_b, hi_b = math.log(0.8), math.log(1.25)
    for i, (dt, o, h, lo, c, vol, a, cu, k) in enumerate(rows):
        if dt not in win or i == 0:
            continue
        pdt, pa, pcu, pk = rows[i - 1][0], rows[i - 1][6], rows[i - 1][7], rows[i - 1][8]
        base = all(math.isfinite(x) and x > 0 for x in (o, c, a, pa)) and vol > 0
        base = base and (pd.Timestamp(dt) - pd.Timestamp(pdt)).days <= 7
        base = base and lo * (1 - 1e-6) <= o <= h * (1 + 1e-6)
        if not base:
            continue
        rid = math.log(c / o)
        mism = pk != k and abs(mtime[pk] - mtime[k]) / 3600.0 > BASIS_TOL_HOURS
        for g in (True, False):
            if g and mism:                       # splice on a mismatched-basis boundary
                if not (math.isfinite(cu) and cu > 0 and math.isfinite(pcu) and pcu > 0):
                    continue
                run = math.log(cu / pcu)
                if not (lo_b <= math.log(a / pa) - run <= hi_b):
                    guarded_days.append((dt, "drop"))
                    continue
                ron = run - rid
                guarded_days.append((dt, "splice"))
            else:
                ron = math.log(a / pa) - rid
            if abs(rid) <= 0.7 and abs(ron) <= 0.7:
                tot_g[g] += rid - ron; nval[g] += 1
    hand = {g: (252.0 * tot_g[g] / nval[g] if nval[g] >= 200 else None) for g in (True, False)}
    live, info = io_gap_asof([ticker], t)
    raw, _ = io_gap_asof([ticker], t, guard=False)
    got, got_raw = float(live[COL].iloc[0]), float(raw[COL].iloc[0])
    ok = hand[True] is not None and abs(hand[True] - got) < 1e-12 and abs(hand[False] - got_raw) < 1e-12
    out = {"ticker": ticker, "t": iso, "window": f"{sorted(win)[0]}..{sorted(win)[-1]}",
           "hand_nvalid_guarded": nval[True], "hand_io_gap_guarded": hand[True], "live_io_gap": got,
           "abs_diff": abs(hand[True] - got) if hand[True] is not None else None,
           "hand_io_gap_unguarded": hand[False], "live_io_gap_unguarded": got_raw,
           "abs_diff_unguarded": abs(hand[False] - got_raw) if hand[False] is not None else None,
           "guarded_days": guarded_days, "pass": bool(ok)}
    log(json.dumps(out, indent=1))
    assert ok, "HANDCHECK FAIL"
    return out


def steady(dates=SELFTEST_DATES):
    """In-era, no labels: the guard applied at EVERY month boundary (the state
    the live store drifts to as each Retrain re-pulls only recent months) vs
    the frozen values. Coverage change and rank correlation per date."""
    res = {}
    for d in dates:
        r = _ref(d)
        live, info = io_gap_asof(r["ticker"], d, every_boundary=True)
        a, b = live[COL].to_numpy(np.float64), r[COL].to_numpy(np.float64)
        m = np.isfinite(a) & np.isfinite(b)
        rho = float(pd.Series(a[m]).rank().corr(pd.Series(b[m]).rank()))
        res[d] = {"rows": int(len(r)), "coverage_frozen": float(np.isfinite(b).mean()),
                  "coverage_every_boundary": float(np.isfinite(a).mean()), "spearman_vs_frozen": rho,
                  "max_abs_diff": float(np.max(np.abs(a[m] - b[m]))),
                  "median_abs_diff": float(np.median(np.abs(a[m] - b[m]))),
                  "spliced_rows_in_window": info["spliced_rows_in_window"],
                  "dropped_splitlike_rows_in_window": info["dropped_splitlike_rows_in_window"]}
        log(f"steady {d}: {res[d]}")
    return res


# ------------------------------------------------------------------ Gate A (live basis)
FRESH_MAX_CALLS = 10


def _fresh_pull(tickers, t, calls):
    """Fresh single-pull SEP history for a few tickers (one consistent basis),
    via the existing redacting fetch of sharadar_pull_pit_panel (WO-19)."""
    sys.path.insert(0, str(HERE.parent))
    import sharadar_pull_pit_panel as SP
    if not SP.API_KEY:
        raise SystemExit("gate_a: SHARADAR_API_KEY not set (source ~/.config/pipe_dream/secrets.env)")
    lo = (pd.Period(pd.Timestamp(t), freq="M") - LOAD_MONTHS).strftime("%Y-%m-01")
    out = {}
    for tk in tickers:
        if calls[0] >= FRESH_MAX_CALLS:
            raise SystemExit("gate_a: API call cap reached")
        rows = SP.fetch("stocks", {"ticker": tk, "date.gte": lo, "date.lte": pd.Timestamp(t).date().isoformat(),
                                   "limit": 10000})
        calls[0] += 1
        d = pd.DataFrame(rows)
        for c in ("open", "high", "low", "close", "volume", "closeadj", "closeunadj"):
            d[c] = pd.to_numeric(d[c], errors="coerce")
        d["date"] = pd.to_datetime(d["date"])
        d["ticker"] = d["ticker"].astype(str)
        out[tk] = d.sort_values("date").reset_index(drop=True)
    return out


def gate_a(t=None, fresh=("STSM", "WHLR", "HUBC"), n_div=3):
    import working_panel as W
    t = pd.Timestamp(t) if t else W.latest_date()
    res = {"t": t.date().isoformat()}
    # 0. open populated in recent live files
    op = {}
    for st in _stems(t, 4):
        d = pd.read_parquet(SEP_DIR / f"{st}.parquet", columns=["open", "close"])
        op[st] = {"rows": int(len(d)), "open_nan": float(d["open"].isna().mean()),
                  "open_nonpos": float((d["open"] <= 0).mean())}
    res["open_populated"] = op
    # 1. cross-section: eligible cap150 on t (SPAC rule), raw vs guarded
    df, _u = W.working_cross_section(["ticker", "date", "eligible_cap150"], date=t)
    cross = df[(df["date"] == t) & df["eligible_cap150"]].reset_index(drop=True)
    g, info, s, cal = io_gap_asof(cross["ticker"], t, return_inputs=True)
    r, info_r = io_gap_asof(cross["ticker"], t, guard=False)
    a, b = g[COL].to_numpy(np.float64), r[COL].to_numpy(np.float64)
    m = np.isfinite(a) & np.isfinite(b)
    dif = pd.DataFrame({"ticker": g["ticker"], "guarded": a, "raw": b, "d": a - b})
    act = pd.read_csv(W.SH / "actions.csv", parse_dates=["date"])
    act_s = act[(act["date"] > "2026-09-08") & act["action"].isin(["dividend", "split", "adrratiosplit"])]
    top = dif[m].reindex(dif[m]["d"].abs().sort_values(ascending=False).index).head(12)
    top = top.assign(actions_after_0908=[";".join(f"{x.action}:{x.date.date()}:{x.value}" for x in
                                                  act_s[act_s["ticker"] == tk].itertuples()) for tk in top["ticker"]])
    res["cross_section"] = {"n": int(len(cross)), "coverage_guarded": info["coverage"],
                            "coverage_raw": info_r["coverage"], "guarded_boundaries": info["guarded_boundaries"],
                            "file_mtimes_used": info["file_mtimes"],
                            "spliced_rows_in_window": info["spliced_rows_in_window"],
                            "dropped_splitlike_rows_in_window": info["dropped_splitlike_rows_in_window"],
                            "dropped_splitlike_tickers": info["dropped_splitlike_tickers"],
                            "spearman_guarded_vs_raw": float(pd.Series(a[m]).rank().corr(pd.Series(b[m]).rank())),
                            "n_changed_gt_1e-12": int((np.abs(a[m] - b[m]) > 1e-12).sum()),
                            "max_abs_change": float(np.max(np.abs(a[m] - b[m]))),
                            "median_abs_change": float(np.median(np.abs(a[m] - b[m]))),
                            "top_changes": top.to_dict("records")}
    # 2. outlier audit: valid days in the cross-section's windows with |exp(r_on)-1| > 50%
    win_lo = cal[cal.searchsorted(t) - WINDOW]
    w = s[(s["date"] > win_lo) & s["ticker"].isin(set(cross["ticker"])) & s["valid"]].copy()
    w["on_ret"] = np.expm1(w["r_on"])
    out_ = w[w["on_ret"].abs() > 0.5]
    res["outliers_gt_50pct"] = {"valid_days_checked": int(len(w)), "n": int(len(out_)),
                                "rows": [{"ticker": x.ticker, "date": str(x.date.date()), "on_ret": float(x.on_ret),
                                          "close": float(x.close), "open": float(x.open),
                                          "actions": ";".join(f"{y.action}:{y.date.date()}:{y.value}" for y in
                                                              act[(act["ticker"] == x.ticker) &
                                                                  ((act["date"] - x.date).abs().dt.days <= 3)].itertuples())}
                                         for x in out_.itertuples()]}
    # 3. fresh consistent-basis recompute for split names + cap150 dividend payers
    divs = act[(act["action"] == "dividend") & (act["date"] > "2026-09-09") & (act["date"] <= t)]
    cand = dif[m & dif["ticker"].isin(set(divs["ticker"]))].copy()
    cand = cand.reindex(cand["d"].abs().sort_values(ascending=False).index)
    div_names = list(cand["ticker"].head(n_div))
    names = list(fresh) + div_names + ["AAPL"]
    calls = [0]
    fr = _fresh_pull(names, t, calls)
    cmp_ = {}
    for tk in names:
        fs = fr[tk]
        if fs.empty:
            cmp_[tk] = {"fresh_rows": 0}
            continue
        # the fresh pull is ONE basis: the frozen definition applies to it as is
        f0 = fs[SEP_COLS].copy()
        f0, _ = B.daily_components(f0)
        q = pd.DataFrame({"ticker": [tk], "date": t})
        ref_all = B.io_gap_for(f0[["ticker", "date", "r_id", "r_on", "valid"]].copy(), cal, q)[0][0]
        # like-for-like: the same rows the live guard DROPPED (split-like) made invalid
        st = s[s["ticker"] == tk]
        dropped = set(st.loc[st["basis_action"] == 2, "date"])
        f1 = f0.copy()
        dm = f1["date"].isin(dropped).to_numpy()
        f1.loc[dm, "valid"] = False
        f1.loc[dm, ["r_id", "r_on"]] = 0.0
        ref_like = B.io_gap_for(f1[["ticker", "date", "r_id", "r_on", "valid"]].copy(), cal, q)[0][0]
        lg, _ = io_gap_asof([tk], t)
        lr, _ = io_gap_asof([tk], t, guard=False)
        vg, vr = float(lg[COL].iloc[0]), float(lr[COL].iloc[0])
        cmp_[tk] = {"fresh_rows": int(len(fs)), "store_rows": int(len(st)), "median_close": float(fs["close"].median()),
                    "min_close_store_window": float(st["close"].min()),
                    "spliced_days": [str(d.date()) for d in st.loc[st["basis_action"] == 1, "date"]][-3:],
                    "dropped_days": [str(d.date()) for d in sorted(dropped)],
                    "live_guarded": vg, "live_raw": vr,
                    "fresh_consistent": float(ref_all), "fresh_consistent_same_drops": float(ref_like),
                    "abs_diff_live_guarded_vs_fresh_same_drops": float(abs(vg - ref_like)),
                    "abs_diff_live_raw_vs_fresh": float(abs(vr - ref_all)),
                    "abs_diff_live_guarded_vs_fresh": float(abs(vg - ref_all)),
                    "actions_after_0908": ";".join(f"{x.action}:{x.date.date()}:{x.value}" for x in
                                                   act_s[act_s["ticker"] == tk].itertuples()),
                    "in_cap150_cross": bool(tk in set(cross["ticker"]))}
        log(f"fresh {tk}: {cmp_[tk]}")
    res["fresh_consistent_basis"] = cmp_
    res["api_calls"] = calls[0]
    return res


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "selftest"
    args = sys.argv[2:]
    fn = {"selftest": selftest, "handcheck": handcheck, "steady": steady, "gate_a": gate_a}[mode]
    res = fn(*args) if mode in ("handcheck", "gate_a") else fn()
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"io_gap_live_{mode}.json").write_text(json.dumps(res, indent=1, default=str))
    log(f"{mode} done -> {OUT / f'io_gap_live_{mode}.json'}")
