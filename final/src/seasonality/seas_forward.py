"""
WO-20: forward side ledgers for the two models that got `seas` on 2026-09-27
(monitoring of PROMOTED models, Gabe's decisions):

  seas        prediction_ledger_seas.csv        Theoretical model: icw9_seas vs icw8,
                                                on v3's cap150 rows (paired with v3)
  blend_seas  prediction_ledger_blend_seas.csv  Today's Picks blend: 10-factor (9 frozen
                                                + seas) blend vs the previous 9-factor
                                                blend, on the cap2000 names both legs score

Pre-registration (committed before any record):
    final/models/2026-09-27-wo20-seas-live.md

    python final/src/seasonality/seas_forward.py selftest  # code checks (no returns)
    python final/src/seasonality/seas_forward.py plan      # dates still to record
    python final/src/seasonality/seas_forward.py score     # blind until a record date matures
    python final/src/seasonality/seas_forward.py status    # counted dates / verdict state

Records are written ONLY through final/src/reset2026/record_weekly.py (the
WO-14 weekly path), after v3 and SUE. Isolated like WO-15 Addendum A, per
ledger: any failure skips only that ledger's record (logged to
ledger_seas_guard_log.csv) and never stops v3/ext/hedge/sue or the other side
ledger. This module does NOT import sue_forward.
"""
import importlib.util
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "reset2026"))
sys.path.insert(0, str(HERE))

import composite as C                      # noqa: E402
import ic_weighted_composite as ICW        # noqa: E402
import prediction_ledger as PL             # noqa: E402
import seas_live as SL                     # noqa: E402
import working_panel as W                  # noqa: E402

OUT_DIR = PL.OUT_DIR
SEAS_CSV = OUT_DIR / "prediction_ledger_seas.csv"
SEAS_SCORES_CSV = OUT_DIR / "prediction_ledger_seas_scores.csv"
BLEND_CSV = OUT_DIR / "prediction_ledger_blend_seas.csv"
BLEND_SCORES_CSV = OUT_DIR / "prediction_ledger_blend_seas_scores.csv"
LOG_CSV = OUT_DIR / "ledger_record_log.csv"
ANN_CSV = OUT_DIR / "ledger_record_annotations.csv"
GUARD_CSV = OUT_DIR / "ledger_seas_guard_log.csv"
SEAS_VERSION = "seas1_icw9seas_2026-09-27"
BLEND_VERSION = "blendseas1_ew10seas_2026-09-27"
WEIGHTS = ICW.PRODUCTION_WEIGHTS_V9_SEAS
SEAS_COLS = ["panel_date", "recorded_at", "seas_version", "ticker", "seas", "seas_nyears",
             "seas_target_month", "icw8_score", "icw9_seas_score", "icw9_seas_rank_pct"]
BLEND_COLS = ["panel_date", "recorded_at", "blend_version", "ticker", "sector", "q75_score", "seas",
              "composite_prev9", "composite_seas10", "blend_prev9_score", "blend_seas10_score",
              "blend_seas10_rank_pct", "seas_target_month"]
LABEL = PL.LABEL
BLEND_TIER = "cap2000"
# Frozen (doc sec. 4): the first record date of both ledgers is the first v3
# date AFTER this one (W40 onward). 2026-09-18 / 2026-09-24 are not
# backfilled: a record written now for them would be recorded_late (> 7 days)
# and never counted anyway.
START_AFTER = pd.Timestamp("2026-09-24")
COVERAGE_FLOOR = 0.70        # counted-date eligibility (live seas coverage 09-24: cap150 86.3%, cap2000 90.3%)
SEAS_MIN_COVERAGE = 0.60     # below this the SEP files look broken: the date is SKIPPED
MIN_COUNTED = 6
H = 40
TOL_ICW8 = 1e-12


def log(m):
    print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)


def iso_week(d):
    c = pd.Timestamp(d).isocalendar()
    return f"{c[0]}-W{c[1]:02d}"


def _append(csv, df):
    if csv.exists() and not csv.read_bytes().endswith(b"\n"):
        raise SystemExit(f"{csv.name} does not end in a newline; refusing to append")
    df.to_csv(csv, mode="a", header=not csv.exists(), index=False)


def _recorded(csv):
    if not csv.exists():
        return set()
    return set(pd.read_csv(csv, usecols=["panel_date"])["panel_date"].astype(str))


def _todo(csv, v3_new):
    """v3 panel dates after START_AFTER (existing + about to be written this
    run) with no record in `csv` yet."""
    have = set()
    if PL.LEDGER_CSV.exists():
        have = set(pd.read_csv(PL.LEDGER_CSV, usecols=["panel_date"])["panel_date"].astype(str))
    ds = {d for d in have if pd.Timestamp(d) > START_AFTER} | {
        pd.Timestamp(d).date().isoformat() for d in v3_new if pd.Timestamp(d) > START_AFTER}
    return sorted(pd.Timestamp(d) for d in ds - _recorded(csv))


# ================================================================== seas (Theoretical, cap150)
def v3_cross(t):
    """Exactly prediction_ledger.record()'s cross-section and v3 row mask
    (copied from sue_forward.v3_cross on purpose; see module docstring)."""
    need = list(dict.fromkeys(["ticker", "date", "sector", "volatility_60",
                               "eligible_cap150", LABEL] + C.FACTOR_COLS))
    df, _u = W.working_cross_section(need, date=t, path=PL.PANEL_PATH)
    latest = df.loc[df["eligible_cap150"], "date"].max()
    if latest != pd.Timestamp(t):
        raise SystemExit(f"no eligible cross-section on {pd.Timestamp(t).date()}")
    cross = df[(df["date"] == latest) & df["eligible_cap150"]].reset_index(drop=True)
    n_mat = int(cross[LABEL].notna().sum())
    if n_mat:
        raise SystemExit(f"REFUSING: {n_mat} eligible cap150 names on {latest.date()} have a matured "
                         f"{LABEL} -- not blind")
    s = C.compute_composite(cross, neutral=False)["composite"].to_numpy(np.float64)
    return cross, np.isfinite(s)


def build_seas_rows(t):
    t = pd.Timestamp(t)
    cross, valid = v3_cross(t)
    sf, info = SL.seas_asof(cross["ticker"], t)
    assert (sf["ticker"].to_numpy() == cross["ticker"].astype(str).to_numpy()).all()
    cross = cross.copy()
    cross["seas"] = sf["seas"].to_numpy(np.float64)
    if not info["coverage"] >= SEAS_MIN_COVERAGE:
        raise SystemExit(f"seas coverage {info['coverage']:.1%} < {SEAS_MIN_COVERAGE:.0%} on {t.date()} "
                         f"(SEP month files incomplete?)")
    s8 = ICW.compute_composite_ic_weighted(cross)["composite"].to_numpy(np.float64)
    s9 = ICW.compute_composite_ic_weighted(cross, weights=WEIGHTS)["composite"].to_numpy(np.float64)
    out = pd.DataFrame({
        "panel_date": t.date().isoformat(), "recorded_at": "", "seas_version": SEAS_VERSION,
        "ticker": cross["ticker"].to_numpy(), "seas": cross["seas"].to_numpy(),
        "seas_nyears": sf["seas_nyears"].to_numpy(), "seas_target_month": info["target_month"],
        "icw8_score": s8, "icw9_seas_score": s9,
    })[valid].reset_index(drop=True)
    out["icw9_seas_rank_pct"] = out["icw9_seas_score"].rank(pct=True, na_option="keep")
    fin = np.isfinite(out["seas"].to_numpy(np.float64))
    info.update({"rows": int(len(out)), "coverage_rows": float(fin.mean()) if len(out) else float("nan")})
    return out, info


def v3_rows(t):
    v3 = pd.read_csv(PL.LEDGER_CSV, usecols=["panel_date", "ticker", "ic_weighted_score"])
    return v3[v3["panel_date"].astype(str) == pd.Timestamp(t).date().isoformat()].reset_index(drop=True)


def check_pairing(rows, t):
    """tickers == v3's rows (same order); icw8 == v3 ic_weighted_score to 1e-12."""
    v = v3_rows(t)
    if len(v) == 0:
        raise SystemExit(f"pairing: v3 has no rows for {pd.Timestamp(t).date()}")
    if list(v["ticker"].astype(str)) != list(rows["ticker"].astype(str)):
        raise SystemExit(f"pairing: ticker list != v3 on {pd.Timestamp(t).date()} ({len(rows)} vs {len(v)})")
    a, b = rows["icw8_score"].to_numpy(np.float64), v["ic_weighted_score"].to_numpy(np.float64)
    nan_ok = np.isnan(a) == np.isnan(b)
    d = np.abs(np.where(np.isnan(a), 0, a) - np.where(np.isnan(b), 0, b))
    if not nan_ok.all() or d.max() > TOL_ICW8:
        raise SystemExit(f"pairing: icw8 != v3 ic_weighted_score on {pd.Timestamp(t).date()} "
                         f"(max |d| {d.max():.2e}, NaN mismatches {(~nan_ok).sum()})")
    return float(d.max())


def recorded_dates():
    return _recorded(SEAS_CSV)


def todo_dates(v3_new=()):
    return _todo(SEAS_CSV, v3_new)


def record_seas(t, rows):
    """Append one date. Duplicate-date guard + blindness re-check + pairing."""
    iso = pd.Timestamp(t).date().isoformat()
    if iso in recorded_dates():
        raise SystemExit(f"REFUSING: {SEAS_CSV.name} already has panel_date {iso} (duplicate-date guard)")
    v3_cross(t)                                  # blindness guard (raises)
    check_pairing(rows, t)
    out = rows.copy()
    out["recorded_at"] = pd.Timestamp.now().isoformat()
    out = out[SEAS_COLS]
    _append(SEAS_CSV, out)
    W.record_manifest(SEAS_CSV, pd.Timestamp(t), PL.PANEL_PATH)
    log(f"appended {len(out)} rows to {SEAS_CSV.name} for {iso}: finite seas "
        f"{np.isfinite(out['seas'].to_numpy(np.float64)).mean():.1%}")
    return out


# ================================================================== blend_seas (Today's Picks, cap2000)
_CSB = None


def csb():
    """current_signal_blend.py next to this package (loaded by path: it has no package)."""
    global _CSB
    if _CSB is None:
        spec = importlib.util.spec_from_file_location("current_signal_blend_wo20", HERE.parent / "current_signal_blend.py")
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        _CSB = m
    return _CSB


def blend_blind_guard(t):
    df, _u = W.working_cross_section([f"eligible_{BLEND_TIER}", LABEL], date=t, path=PL.PANEL_PATH)
    n = int(df.loc[df[f"eligible_{BLEND_TIER}"], LABEL].notna().sum())
    if n:
        raise SystemExit(f"REFUSING: {n} eligible {BLEND_TIER} names on {pd.Timestamp(t).date()} have a "
                         f"matured {LABEL} -- not blind")


def build_blend_rows(t):
    t = pd.Timestamp(t)
    blend_blind_guard(t)
    f, info = csb().blend_scores_at(t)
    ok = np.isfinite(f["blend_seas10_score"].to_numpy(np.float64)) | np.isfinite(f["blend_prev9_score"].to_numpy(np.float64))
    f = f[ok].reset_index(drop=True)
    f.insert(0, "panel_date", t.date().isoformat())
    f.insert(1, "recorded_at", "")
    f.insert(2, "blend_version", BLEND_VERSION)
    f["blend_seas10_rank_pct"] = f["blend_seas10_score"].rank(pct=True, na_option="keep")
    f["seas_target_month"] = info["target_month"]
    fin = np.isfinite(f["seas"].to_numpy(np.float64))
    info.update({"rows": int(len(f)), "coverage_rows": float(fin.mean()) if len(f) else float("nan")})
    return f[BLEND_COLS], info


def blend_recorded_dates():
    return _recorded(BLEND_CSV)


def blend_todo_dates(v3_new=()):
    return _todo(BLEND_CSV, v3_new)


def record_blend(t, rows):
    iso = pd.Timestamp(t).date().isoformat()
    if iso in blend_recorded_dates():
        raise SystemExit(f"REFUSING: {BLEND_CSV.name} already has panel_date {iso} (duplicate-date guard)")
    blend_blind_guard(t)
    out = rows.copy()
    out["recorded_at"] = pd.Timestamp.now().isoformat()
    out = out[BLEND_COLS]
    _append(BLEND_CSV, out)
    W.record_manifest(BLEND_CSV, pd.Timestamp(t), PL.PANEL_PATH)
    log(f"appended {len(out)} rows to {BLEND_CSV.name} for {iso}: finite seas "
        f"{np.isfinite(out['seas'].to_numpy(np.float64)).mean():.1%}")
    return out


# ================================================================== record_weekly interface
class Side:
    """One side ledger as record_weekly.py drives it (read at call time, so a
    test that repoints the module paths is honoured)."""

    def __init__(self, name, csv, todo, build, pair, record, incomplete_source):
        self.name, self._csv, self.todo, self.build = name, csv, todo, build
        self.pair, self.record, self.source = pair, record, incomplete_source

    @property
    def csv(self):
        return self._csv()


def side_ledgers():
    return [Side("seas", lambda: SEAS_CSV, todo_dates, build_seas_rows, check_pairing, record_seas, "WO-20"),
            Side("blend_seas", lambda: BLEND_CSV, blend_todo_dates, build_blend_rows, None, record_blend, "WO-20")]


def log_guard(panel_date, event, detail="", ledger="seas"):
    """Append-only sidecar: side-ledger skips (never a reason to stop v3/ext/hedge/sue)."""
    iso = pd.Timestamp(panel_date).date().isoformat() if panel_date else ""
    _append(GUARD_CSV, pd.DataFrame([[pd.Timestamp.now().isoformat(), ledger, iso, iso_week(iso) if iso else "",
                                      event, str(detail)[:500]]],
                                    columns=["logged_at", "ledger", "panel_date", "iso_week", "event", "detail"]))


# ================================================================== score / status (post-maturity only)
SPECS = {
    "seas": dict(csv=lambda: SEAS_CSV, scores=lambda: SEAS_SCORES_CSV, new="icw9_seas_score", old="icw8_score",
                 tag="icw9_seas", prev_tag="icw8", version="seas_version"),
    "blend_seas": dict(csv=lambda: BLEND_CSV, scores=lambda: BLEND_SCORES_CSV, new="blend_seas10_score",
                       old="blend_prev9_score", tag="blend_seas10", prev_tag="blend_prev9", version="blend_version"),
}


def _spear(a, b):
    return PL._spearman(np.asarray(a, np.float64), np.asarray(b, np.float64))


def score_frame(df, spy_fwd_40, new, old, tag, prev_tag):
    """df: one date; new/old score columns, realized, beta_252, sector."""
    r = df["realized"].to_numpy(np.float64)
    s9, s8 = df[new].to_numpy(np.float64), df[old].to_numpy(np.float64)
    m = np.isfinite(s9) & np.isfinite(s8) & np.isfinite(r)
    out = {"n_names": int(m.sum())}
    r9, r8 = _spear(s9[m], r[m]), _spear(s8[m], r[m])
    out.update({f"rho_{tag}_raw": r9, f"rho_{prev_tag}_raw": r8, "gain_raw": r9 - r8})
    if pd.notna(spy_fwd_40):
        ab = r - df["beta_252"].to_numpy(np.float64) * spy_fwd_40
        mb = m & np.isfinite(ab)
        a9, a8 = _spear(s9[mb], ab[mb]), _spear(s8[mb], ab[mb])
    else:
        a9 = a8 = np.nan
    out.update({f"rho_{tag}_beta_adj": a9, f"rho_{prev_tag}_beta_adj": a8, "gain_beta_adj": a9 - a8})
    g = df[m].copy()
    g["sector"] = g["sector"].fillna("Unknown")
    dm = lambda c: (g[c] - g.groupby("sector")[c].transform("mean")).to_numpy(np.float64)  # noqa: E731
    q9, q8 = _spear(dm(new), dm("realized")), _spear(dm(old), dm("realized"))
    out.update({f"rho_{tag}_sector_both": q9, f"rho_{prev_tag}_sector_both": q8, "gain_sector_both": q9 - q8})
    return out


def score(kind):
    sp = SPECS[kind]
    csv, scores = sp["csv"](), sp["scores"]()
    if not csv.exists():
        log(f"No {csv.name} yet -- nothing to score")
        return []
    led = pd.read_csv(csv)
    done = set(pd.read_csv(scores, usecols=["panel_date"])["panel_date"].astype(str)) if scores.exists() else set()
    results, beta, spy = [], None, None
    for pdate, rows in led.groupby(led["panel_date"].astype(str)):
        if pdate in done:
            continue
        cross, _u = W.working_cross_section(["sector", LABEL], date=pdate, path=PL.PANEL_PATH)
        if cross[LABEL].notna().sum() == 0:
            log(f"{kind} {pdate}: still blind (no matured {LABEL}) -- nothing scored")
            continue
        if spy is None:
            beta, spy = PL._load_beta_and_market()
        b = beta[beta["date"] == pd.Timestamp(pdate)][["ticker", "beta_252"]]
        df = (rows.drop(columns=[c for c in ("sector",) if c in rows.columns]).merge(b, on="ticker", how="left")
                  .merge(cross[["ticker", "sector", LABEL]].rename(columns={LABEL: "realized"}), on="ticker", how="left"))
        st = score_frame(df, spy.get(pd.Timestamp(pdate), np.nan), sp["new"], sp["old"], sp["tag"], sp["prev_tag"])
        st.update({"panel_date": pdate, "scored_at": pd.Timestamp.now().isoformat(),
                   "version": rows[sp["version"]].iloc[0],
                   "coverage": float(np.isfinite(rows["seas"].to_numpy(np.float64)).mean())})
        results.append(st)
        log(f"{kind} {pdate}: gain_raw {st['gain_raw']:+.4f} (n {st['n_names']})")
    if results:
        pd.DataFrame(results).to_csv(scores, mode="a", header=not scores.exists(), index=False)
    return results


def excluded_dates(csv):
    """recorded_late (log sidecar) or incomplete_week (annotations) for one ledger."""
    late, inc = set(), set()
    if LOG_CSV.exists():
        lg = pd.read_csv(LOG_CSV)
        lg = lg[(lg["ledger"] == csv.name) & lg["recorded_late"].astype(str).str.lower().eq("true")]
        late = set(lg["panel_date"].astype(str))
    if ANN_CSV.exists():
        an = pd.read_csv(ANN_CSV)
        an = an[(an["ledger"] == csv.name) & an["annotation"].astype(str).str.startswith("incomplete_week")]
        inc = set(an["panel_date"].astype(str))
    return late, inc


def counted_dates(records, late, inc, cal):
    """records: {panel_date: coverage}. Greedy from the first eligible record
    (not late, not incomplete_week, coverage >= floor); next counted date is
    the first eligible record >= 40 trading days after the previous one."""
    cal = pd.DatetimeIndex(sorted(cal))
    elig = sorted(pd.Timestamp(d) for d, cov in records.items()
                  if d not in late and d not in inc and cov >= COVERAGE_FLOOR)
    out, prev = [], None
    for d in elig:
        if prev is None or int(((cal > prev) & (cal <= d)).sum()) >= H:
            out.append(d)
            prev = d
    return out


def trading_calendar():
    import forward_hedge as FH
    t = pq.read_table(W.WORKING_PANEL, columns=["date"])
    panel = pd.DatetimeIndex(sorted(pd.to_datetime(pd.Series(t.column("date").unique().to_pylist()))))
    if not FH.IWM_LIVE_CSV.exists():
        return panel, "working panel dates (IWM_live.csv absent)"
    iwm = pd.DatetimeIndex(FH.load_iwm(FH.IWM_LIVE_CSV)["date"])
    lo, hi = max(iwm.min(), panel.min()), min(iwm.max(), panel.max())
    a, b = iwm[(iwm >= lo) & (iwm <= hi)], panel[(panel >= lo) & (panel <= hi)]
    if not a.equals(b):
        raise SystemExit("status: IWM_live.csv and working-panel calendars disagree on their overlap")
    return iwm, "IWM_live.csv dates (agree with working panel on overlap)"


def status(kind, quiet=False):
    sp = SPECS[kind]
    csv, scores = sp["csv"](), sp["scores"]()
    if not csv.exists():
        st = {"ledger": csv.name, "state": "NO RECORDS", "n_matured_counted": 0}
        log(f"status: {st}")
        return st
    led = pd.read_csv(csv, usecols=["panel_date", "seas"])
    cov = led.groupby(led["panel_date"].astype(str))["seas"].apply(lambda s: float(np.isfinite(s).mean())).to_dict()
    late, inc = excluded_dates(csv)
    cal, cal_src = trading_calendar()
    cd = [d.date().isoformat() for d in counted_dates(cov, late, inc, cal)]
    sc = pd.read_csv(scores) if scores.exists() else pd.DataFrame(columns=["panel_date", "gain_raw"])
    sc["panel_date"] = sc["panel_date"].astype(str)
    first6 = cd[:MIN_COUNTED]
    mat = sc[sc["panel_date"].isin(first6)]
    n, mean = len(mat), float(mat["gain_raw"].mean()) if len(mat) else float("nan")
    if len(first6) < MIN_COUNTED or n < MIN_COUNTED:
        state = f"INSUFFICIENT ({n} of {MIN_COUNTED} counted dates matured; blind)"
    elif mean > 0:
        state = "CONSISTENT (the seas version stays; report to Gabe)"
    else:
        state = "DEMOTION QUESTION to Gabe (mean paired gain <= 0)"
    st = {"ledger": csv.name,
          "records": {d: {"coverage": round(c, 4), "late": d in late, "incomplete_week": d in inc}
                      for d, c in sorted(cov.items())},
          "counted_dates": cd, "calendar": cal_src, "n_matured_counted": n,
          "mean_gain_raw_first6": mean, "state": state}
    if not quiet:
        log(f"status: {json.dumps(st, default=str)}")
    return st


# ================================================================== selftest (no returns)
def selftest():
    """Latest v3 date: seas rows build, pairing with v3 icw8 holds to 1e-12,
    icw9_seas equals an independent score over the same cross-section; blend
    rows build and equal blend_scores_at. Reads no label value (only the
    blindness count), writes nothing.
    Pairing is only meaningful against the panel the v3 record was made on:
    a later refresh can add tickers / revise rows of past dates (measured
    2026-09-27: the 09-26 refresh adds 5 names to 09-24). So the dated
    pre-refresh backup composite_panel_v2_through_<t>.parquet is used when it
    exists. In record_weekly, v3 and seas are built in the same run on the
    same panel, so this never arises there."""
    v3 = pd.read_csv(PL.LEDGER_CSV, usecols=["panel_date"])["panel_date"].astype(str)
    t = pd.Timestamp(v3.max())
    bk = W.R26 / f"composite_panel_v2_through_{t.date().isoformat()}.parquet"
    panel0 = PL.PANEL_PATH
    if bk.exists():
        PL.PANEL_PATH = bk
        log(f"selftest: pairing against the record-time panel {bk.name}")
    try:
        rows, info = build_seas_rows(t)
        d8 = check_pairing(rows, t)
        cross, valid = v3_cross(t)
        sf, _i = SL.seas_asof(cross["ticker"], t)
        cross["seas"] = sf["seas"].to_numpy()
        ref = ICW.compute_composite_ic_weighted(cross, weights=WEIGHTS)["composite"].to_numpy()[valid]
    finally:
        PL.PANEL_PATH = panel0
    got = rows["icw9_seas_score"].to_numpy(np.float64)
    assert ((np.isnan(ref) == np.isnan(got)).all()) and np.nanmax(np.abs(ref - got)) == 0.0
    assert list(rows.columns) == SEAS_COLS
    # blend: on the working panel's latest date (the base panel must have it)
    tb = W.latest_date()
    brows, binfo = build_blend_rows(tb)
    f, _ = csb().blend_scores_at(tb)
    x = brows.merge(f, on="ticker", suffixes=("", "_ref"))
    assert len(x) == len(brows) and np.nanmax(np.abs(x["blend_seas10_score"] - x["blend_seas10_score_ref"])) == 0.0
    assert list(brows.columns) == BLEND_COLS
    res = {"seas": {"date": t.date().isoformat(), "rows": int(len(rows)), "icw8_vs_v3_max_abs": d8,
                    "seas_info": info, "icw9_seas_equals_independent_score": True},
           "blend_seas": {"date": tb.date().isoformat(), "rows": int(len(brows)), "seas_info": binfo},
           "todo_now": {"seas": [d.date().isoformat() for d in todo_dates()],
                        "blend_seas": [d.date().isoformat() for d in blend_todo_dates()]}}
    log(f"selftest PASS: {json.dumps(res, default=str)}")
    return res


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "status"
    if mode == "selftest":
        r = selftest()
        (HERE.parent.parent / "out" / "seasonality" / "seas_forward_selftest.json").write_text(json.dumps(r, indent=1, default=str))
    elif mode == "plan":
        log(f"seas: {[d.date().isoformat() for d in todo_dates()]}; "
            f"blend_seas: {[d.date().isoformat() for d in blend_todo_dates()]}")
    elif mode == "score":
        for k in SPECS:
            score(k)
    elif mode == "status":
        for k in SPECS:
            status(k)
    else:
        raise SystemExit(f"unknown mode {mode}")
