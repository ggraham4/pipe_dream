"""
WO-27-io-fwd (2026-09-29): forward side ledger for icw10_io = icw9_seas + io_gap
(frozen weights), recorded next to the seas ledger on the same cap150 v3 rows.
Gabe (D-IO, 2026-09-29): "push it this is very good" -- RECORDING only; live
picks, live weights and the app's primary view do not change.

  io   prediction_ledger_io.csv   icw10_io vs icw9_seas, on v3's cap150 rows,
                                  paired with v3 (icw8) AND with the seas ledger
                                  (icw9_seas recomputed here == seas CSV, diff 0)

Pre-registration (committed before any record):
    final/models/2026-09-29-wo27-io-forward-ledger.md

    python final/src/overnight/io_forward.py selftest  # code checks (no returns, writes no ledger)
    python final/src/overnight/io_forward.py plan      # dates still to record
    python final/src/overnight/io_forward.py score     # blind until a record date matures
    python final/src/overnight/io_forward.py status    # counted records / review state

Records are written ONLY through final/src/reset2026/record_weekly.py, after
the seas ledger. Isolated like WO-15 Addendum A / WO-20: any io failure
(import, plan, missing SEP file, exception, coverage < floor, pairing, record,
sidecar) skips only the io record for that date, is logged to
ledger_io_guard_log.csv, and never stops v3/ext/hedge/sue/seas/blend_seas.
"""
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "reset2026"))
sys.path.insert(0, str(HERE.parent / "seasonality"))
sys.path.insert(0, str(HERE))

import composite as C                      # noqa: E402
import ic_weighted_composite as ICW        # noqa: E402
import prediction_ledger as PL             # noqa: E402
import seas_forward as SS                  # noqa: E402
import seas_live as SL                     # noqa: E402
import working_panel as W                  # noqa: E402
import io_gap_live as IL                   # noqa: E402

OUT_DIR = PL.OUT_DIR
IO_CSV = OUT_DIR / "prediction_ledger_io.csv"
IO_SCORES_CSV = OUT_DIR / "prediction_ledger_io_scores.csv"
LOG_CSV = OUT_DIR / "ledger_record_log.csv"
ANN_CSV = OUT_DIR / "ledger_record_annotations.csv"
GUARD_CSV = OUT_DIR / "ledger_io_guard_log.csv"
IO_VERSION = "io1_icw10io_2026-09-29"
LABEL = PL.LABEL
INCOMPLETE_NOTE = ("incomplete_week: paired with the v3 record for this date, which is annotated "
                   "incomplete_week; descriptive only, never a counted record; WO-27 2026-09-29")

# Frozen (doc sec. 2): verbatim from integration's
# final/out/overnight/io_gap_holdout_report.json -> weight_rule_check.icw10.
ICW10_IO_WEIGHTS = {
    "momentum_12_1": 0.0305,
    "pct_from_high_252": 0.008,
    "volatility_60": -0.008,
    "gross_profitability": 0.3657,
    "accruals": -0.0999,
    "net_issuance_pct": -0.0859,
    "days_to_next_filing_seasonal": -0.008,
    "short_interest_days_to_cover": -0.008,
    "seas": 0.1467,
    "io_gap": 0.2393,
}
IO_T = 3.9953088782434265            # io_gap_screen_report.json ic.pooled.t (in-era)
RENORM_TOL = 2e-4                    # rounded-dict renormalization bound (doc sec. 2)

IO_COLS = ["panel_date", "recorded_at", "io_version", "ticker", "sector", "seas", "io_gap", "io_nvalid",
           "icw8_score", "icw9_seas_score", "icw10_io_score", "icw10_io_rank_pct"]
START_AFTER = SS.START_AFTER         # 2026-09-24: first record = first v3 date after it (W40), as seas
COVERAGE_FLOOR = 0.70                # io_gap finite share of the date's rows: below -> SKIPPED (and never counted)
MIN_ROWS = SS.MIN_ROWS
H = 40
FIRST_REVIEW, DROP_REVIEW = 26, 52
NW_LAG = 8                           # ~40 trading days / 5 (overlapping weekly records); descriptive only


def log(m):
    print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)


def iso_week(d):
    c = pd.Timestamp(d).isocalendar()
    return f"{c[0]}-W{c[1]:02d}"


# ================================================================== weights check
def weight_checks():
    """(a) the frozen rule on the unrounded in-era t's reproduces ICW10_IO_WEIGHTS
    to 4 dp; (b) the same rule without io_gap reproduces PRODUCTION_WEIGHTS_V9_SEAS
    to 4 dp; (c) exact: renormalizing the UNROUNDED icw10 without io_gap equals the
    unrounded icw9_seas rule to 1e-12; (d) the ROUNDED icw10 without io_gap,
    renormalized, is within RENORM_TOL of the live PRODUCTION_WEIGHTS_V9_SEAS."""
    t8 = {k: PL.ICW9_T_USED[k] for k in C.FACTOR_COLS}
    signs10 = {**ICW.SIGNS_V9_SEAS, "io_gap": +1}
    w10 = PL.icw_rule({**t8, "seas": ICW.SEAS_T, "io_gap": IO_T}, signs10)
    w9 = PL.icw_rule({**t8, "seas": ICW.SEAS_T}, ICW.SIGNS_V9_SEAS)
    a = max(abs(round(w10[k], 4) - ICW10_IO_WEIGHTS[k]) for k in ICW10_IO_WEIGHTS)
    b = max(abs(round(w9[k], 4) - ICW.PRODUCTION_WEIGHTS_V9_SEAS[k]) for k in ICW.PRODUCTION_WEIGHTS_V9_SEAS)
    tot = sum(abs(w10[k]) for k in w9)
    c = max(abs(w10[k] / tot - w9[k]) for k in w9)
    rtot = sum(abs(ICW10_IO_WEIGHTS[k]) for k in w9)
    ren = {k: ICW10_IO_WEIGHTS[k] / rtot for k in w9}
    d = max(abs(ren[k] - ICW.PRODUCTION_WEIGHTS_V9_SEAS[k]) for k in w9)
    assert list(ICW10_IO_WEIGHTS)[:9] == list(ICW.PRODUCTION_WEIGHTS_V9_SEAS), "factor order != icw9_seas"
    ok = a < 1e-9 and b < 1e-9 and c < 1e-12 and d <= RENORM_TOL
    res = {"icw10_rule_vs_frozen_4dp_max": a, "icw9seas_rule_vs_live_4dp_max": b,
           "unrounded_renorm_vs_icw9seas_max": c, "rounded_renorm_vs_live_icw9seas_max": d,
           "renorm_tol": RENORM_TOL, "renormalized": {k: round(v, 6) for k, v in ren.items()},
           "sum_abs_icw10": round(sum(abs(v) for v in ICW10_IO_WEIGHTS.values()), 6), "pass": bool(ok)}
    if not ok:
        raise SystemExit(f"io weights check FAILED: {res}")
    return res


# ================================================================== rows
def _recorded(csv):
    if not csv.exists():
        return set()
    return set(pd.read_csv(csv, usecols=["panel_date"])["panel_date"].astype(str))


def recorded_dates():
    return _recorded(IO_CSV)


def todo_dates(v3_new=()):
    """v3 panel dates after START_AFTER (existing + this run's) with no io record."""
    have = set()
    if PL.LEDGER_CSV.exists():
        have = set(pd.read_csv(PL.LEDGER_CSV, usecols=["panel_date"])["panel_date"].astype(str))
    ds = {d for d in have if pd.Timestamp(d) > START_AFTER} | {
        pd.Timestamp(d).date().isoformat() for d in v3_new if pd.Timestamp(d) > START_AFTER}
    return sorted(pd.Timestamp(d) for d in ds - recorded_dates())


def build_io_rows(t):
    """v3's cap150 cross-section (blindness guard inside), seas + io_gap at score
    time, icw8 / icw9_seas / icw10_io over the WHOLE eligible cross-section
    (rank_z as in v3), then v3's row mask."""
    t = pd.Timestamp(t)
    cross, valid = SS.v3_cross(t)
    sf, sinfo = SL.seas_asof(cross["ticker"], t)
    assert (sf["ticker"].to_numpy() == cross["ticker"].astype(str).to_numpy()).all()
    if not sinfo["coverage"] >= SS.SEAS_MIN_COVERAGE:
        raise SystemExit(f"io: seas coverage {sinfo['coverage']:.1%} < {SS.SEAS_MIN_COVERAGE:.0%} on {t.date()}")
    iof, iinfo = IL.io_gap_asof(cross["ticker"], t)
    assert (iof["ticker"].to_numpy() == cross["ticker"].astype(str).to_numpy()).all()
    cross = cross.copy()
    cross["seas"] = sf["seas"].to_numpy(np.float64)
    cross["io_gap"] = iof["io_gap"].to_numpy(np.float64)
    s8 = ICW.compute_composite_ic_weighted(cross)["composite"].to_numpy(np.float64)
    s9 = ICW.compute_composite_ic_weighted(cross, weights=SS.WEIGHTS)["composite"].to_numpy(np.float64)
    s10 = ICW.compute_composite_ic_weighted(cross, weights=ICW10_IO_WEIGHTS)["composite"].to_numpy(np.float64)
    out = pd.DataFrame({
        "panel_date": t.date().isoformat(), "recorded_at": "", "io_version": IO_VERSION,
        "ticker": cross["ticker"].to_numpy(), "sector": cross["sector"].to_numpy(),
        "seas": cross["seas"].to_numpy(), "io_gap": cross["io_gap"].to_numpy(),
        "io_nvalid": iof["io_nvalid"].to_numpy(),
        "icw8_score": s8, "icw9_seas_score": s9, "icw10_io_score": s10,
    })[valid].reset_index(drop=True)
    if len(out) < MIN_ROWS:
        raise SystemExit(f"io: only {len(out)} rows on {t.date()} (< {MIN_ROWS}); skipped")
    cov = float(np.isfinite(out["io_gap"].to_numpy(np.float64)).mean())
    if not cov >= COVERAGE_FLOOR:
        raise SystemExit(f"io: io_gap coverage {cov:.1%} < {COVERAGE_FLOOR:.0%} of {len(out)} rows on {t.date()}")
    out["icw10_io_rank_pct"] = out["icw10_io_score"].rank(pct=True, na_option="keep")
    info = {k: iinfo[k] for k in ("files", "file_mtimes", "spliced_rows_in_window",
                                  "dropped_splitlike_rows_in_window", "dropped_splitlike_tickers",
                                  "window_first_day", "sep_max_date_used")}
    info.update({"rows": int(len(out)), "io_coverage_rows": cov, "seas_target_month": sinfo["target_month"]})
    return out[IO_COLS], info


def check_v3_pairing(rows, t):
    return SS.check_pairing(rows, t)


def seas_rows(t):
    if not SS.SEAS_CSV.exists():
        return pd.DataFrame(columns=["panel_date", "ticker", "icw9_seas_score"])
    s = pd.read_csv(SS.SEAS_CSV, usecols=["panel_date", "ticker", "icw9_seas_score"], float_precision="round_trip")
    return s[s["panel_date"].astype(str) == pd.Timestamp(t).date().isoformat()].reset_index(drop=True)


def check_seas_pairing(rows, t):
    """tickers == the seas ledger's rows for t (same order), icw9_seas identical
    (diff 0.0, NaN pattern equal). Raises when the seas ledger has no t."""
    v = seas_rows(t)
    if len(v) == 0:
        raise SystemExit(f"io pairing: seas ledger has no rows for {pd.Timestamp(t).date()} (seas skipped?)")
    if list(v["ticker"].astype(str)) != list(rows["ticker"].astype(str)):
        raise SystemExit(f"io pairing: ticker list != seas on {pd.Timestamp(t).date()} ({len(rows)} vs {len(v)})")
    a, b = rows["icw9_seas_score"].to_numpy(np.float64), v["icw9_seas_score"].to_numpy(np.float64)
    nan_ok = np.isnan(a) == np.isnan(b)
    d = np.abs(np.where(np.isnan(a), 0, a) - np.where(np.isnan(b), 0, b))
    if not nan_ok.all() or d.max() != 0.0:
        raise SystemExit(f"io pairing: icw9_seas != seas ledger on {pd.Timestamp(t).date()} "
                         f"(max |d| {d.max():.2e}, NaN mismatches {(~nan_ok).sum()})")
    return 0.0


def pair(rows, t):
    """Preflight pairing (record_weekly calls it when v3 already has t): v3 icw8
    always; seas icw9_seas too when the seas ledger already has t."""
    d8 = check_v3_pairing(rows, t)
    if len(seas_rows(t)):
        check_seas_pairing(rows, t)
    return d8


def record_io(t, rows):
    """Append one date. Duplicate-date guard + blindness re-check + v3 pairing +
    MANDATORY seas pairing (so the seas record for t must already exist)."""
    iso = pd.Timestamp(t).date().isoformat()
    if iso in recorded_dates():
        raise SystemExit(f"REFUSING: {IO_CSV.name} already has panel_date {iso} (duplicate-date guard)")
    SS.v3_cross(t)
    check_v3_pairing(rows, t)
    check_seas_pairing(rows, t)
    out = rows.copy()
    out["recorded_at"] = pd.Timestamp.now().isoformat()
    out = out[IO_COLS]
    if IO_CSV.exists() and not IO_CSV.read_bytes().endswith(b"\n"):
        raise SystemExit(f"{IO_CSV.name} does not end in a newline; refusing to append")
    out.to_csv(IO_CSV, mode="a", header=not IO_CSV.exists(), index=False)
    W.record_manifest(IO_CSV, pd.Timestamp(t), PL.PANEL_PATH)
    log(f"appended {len(out)} rows to {IO_CSV.name} for {iso}: finite io_gap "
        f"{np.isfinite(out['io_gap'].to_numpy(np.float64)).mean():.1%}")
    return out


def log_guard(panel_date, event, detail="", ledger="io"):
    iso = pd.Timestamp(panel_date).date().isoformat() if panel_date else ""
    row = pd.DataFrame([[pd.Timestamp.now().isoformat(), ledger, iso, iso_week(iso) if iso else "",
                         event, str(detail)[:500]]],
                       columns=["logged_at", "ledger", "panel_date", "iso_week", "event", "detail"])
    if GUARD_CSV.exists() and not GUARD_CSV.read_bytes().endswith(b"\n"):
        raise SystemExit(f"{GUARD_CSV.name} does not end in a newline; refusing to append")
    row.to_csv(GUARD_CSV, mode="a", header=not GUARD_CSV.exists(), index=False)


class Side:
    """The io side ledger as record_weekly.py drives it (same interface as
    seas_forward.Side, plus its own guard log and incomplete_week note).
    Attributes are read at call time so a test that repoints them is honoured."""
    name, source, incomplete_note = "io", "WO-27", INCOMPLETE_NOTE

    @property
    def csv(self):
        return IO_CSV

    def todo(self, v3_new=()):
        return todo_dates(v3_new)

    def build(self, t):
        return build_io_rows(t)

    def pair(self, rows, t):
        return pair(rows, t)

    def record(self, t, rows):
        return record_io(t, rows)

    def log_guard(self, iso, event, detail):
        return log_guard(iso, event, detail, ledger="io")


def side_ledgers():
    weight_checks()                    # a failed weight check skips io (isolated), never v3/.../seas
    return [Side()]


# ================================================================== score / status (post-maturity only)
def trading_calendar():
    return SS.trading_calendar()


def matured(pdate, cal):
    """A record is MATURED when the calendar has >= 41 trading dates after
    panel_date (open[t+1] .. close[t+40]) AND the working panel carries a finite
    label for >= 20 of its rows."""
    return int((cal > pd.Timestamp(pdate)).sum()) >= H + 1


def score_frame(df):
    r = df["realized"].to_numpy(np.float64)
    s10, s9 = df["icw10_io_score"].to_numpy(np.float64), df["icw9_seas_score"].to_numpy(np.float64)
    m = np.isfinite(s10) & np.isfinite(s9) & np.isfinite(r)
    sp = lambda a, b: PL._spearman(np.asarray(a, np.float64), np.asarray(b, np.float64))  # noqa: E731
    out = {"n_names": int(m.sum())}
    r10, r9 = sp(s10[m], r[m]), sp(s9[m], r[m])
    out.update({"rho_icw10_io": r10, "rho_icw9_seas": r9, "gain": r10 - r9})
    g = df[m].copy()
    g["sector"] = g["sector"].fillna("Unknown")
    dm = lambda c: (g[c] - g.groupby("sector")[c].transform("mean")).to_numpy(np.float64)  # noqa: E731
    q10, q9 = sp(dm("icw10_io_score"), dm("realized")), sp(dm("icw9_seas_score"), dm("realized"))
    out.update({"rho_icw10_io_sector_both": q10, "rho_icw9_seas_sector_both": q9, "gain_sector_both": q10 - q9})
    return out


def score():
    if not IO_CSV.exists():
        log(f"No {IO_CSV.name} yet -- nothing to score")
        return []
    led = pd.read_csv(IO_CSV, float_precision="round_trip")
    done = set(pd.read_csv(IO_SCORES_CSV, usecols=["panel_date"])["panel_date"].astype(str)) if IO_SCORES_CSV.exists() else set()
    cal, _src = trading_calendar()
    results = []
    for pdate, rows in led.groupby(led["panel_date"].astype(str)):
        if pdate in done:
            continue
        if not matured(pdate, cal):
            log(f"io {pdate}: not matured (blind) -- nothing scored")
            continue
        cross, _u = W.working_cross_section([LABEL], date=pdate, path=PL.PANEL_PATH)
        df = rows.merge(cross[["ticker", LABEL]].rename(columns={LABEL: "realized"}), on="ticker", how="left")
        if int(np.isfinite(df["realized"].to_numpy(np.float64)).sum()) < 20:
            log(f"io {pdate}: < 20 finite labels -- not scored yet")
            continue
        st = score_frame(df)
        st.update({"panel_date": pdate, "scored_at": pd.Timestamp.now().isoformat(),
                   "version": rows["io_version"].iloc[0],
                   "coverage": float(np.isfinite(rows["io_gap"].to_numpy(np.float64)).mean())})
        results.append(st)
        log(f"io {pdate}: gain {st['gain']:+.4f} (n {st['n_names']})")
    if results:
        pd.DataFrame(results).to_csv(IO_SCORES_CSV, mode="a", header=not IO_SCORES_CSV.exists(), index=False)
    return results


def excluded_dates():
    late, inc = set(), set()
    if LOG_CSV.exists():
        lg = pd.read_csv(LOG_CSV)
        lg = lg[(lg["ledger"] == IO_CSV.name) & lg["recorded_late"].astype(str).str.lower().eq("true")]
        late = set(lg["panel_date"].astype(str))
    if ANN_CSV.exists():
        an = pd.read_csv(ANN_CSV)
        an = an[(an["ledger"] == IO_CSV.name) & an["annotation"].astype(str).str.startswith("incomplete_week")]
        inc = set(an["panel_date"].astype(str))
    return late, inc


def _nw_t(x, lag=NW_LAG):
    x = np.asarray(x, np.float64)
    n = len(x)
    if n < 3:
        return float("nan")
    e = x - x.mean()
    v = e @ e / n
    for k in range(1, min(lag, n - 1) + 1):
        v += 2 * (1 - k / (lag + 1)) * (e[k:] @ e[:-k]) / n
    return float(x.mean() / np.sqrt(v / n)) if v > 0 else float("nan")


def status(quiet=False):
    if not IO_CSV.exists():
        st = {"ledger": IO_CSV.name, "state": "NO RECORDS", "n_counted_matured": 0}
        log(f"status: {st}")
        return st
    led = pd.read_csv(IO_CSV, usecols=["panel_date", "io_gap"])
    cov = led.groupby(led["panel_date"].astype(str))["io_gap"].apply(lambda s: float(np.isfinite(s).mean())).to_dict()
    late, inc = excluded_dates()
    elig = sorted(d for d, c in cov.items() if d not in late and d not in inc and c >= COVERAGE_FLOOR)
    sc = pd.read_csv(IO_SCORES_CSV) if IO_SCORES_CSV.exists() else pd.DataFrame(columns=["panel_date", "gain"])
    sc["panel_date"] = sc["panel_date"].astype(str)
    g = sc.set_index("panel_date")["gain"] if len(sc) else pd.Series(dtype=float)
    counted = [d for d in elig if d in g.index]          # eligible AND matured+scored, in record order
    n = len(counted)
    gains = [float(g[d]) for d in counted]
    first26 = float(np.mean(gains[:FIRST_REVIEW])) if n >= FIRST_REVIEW else float("nan")
    first52 = float(np.mean(gains[:DROP_REVIEW])) if n >= DROP_REVIEW else float("nan")
    if n < FIRST_REVIEW:
        state = f"INSUFFICIENT ({n} of {FIRST_REVIEW} counted matured records)"
    elif n < DROP_REVIEW:
        state = ("FIRST REVIEW: KEEP (paired mean over the first 26 > 0; report to Gabe; drop check at 52 still applies)"
                 if first26 > 0 else "FIRST REVIEW: mean <= 0 -> CONTINUE to the drop check at 52")
    else:
        state = ("DROP (paired mean over the first 52 <= 0)" if first52 <= 0
                 else "KEEP at the drop check (paired mean over the first 52 > 0; report to Gabe)")
    st = {"ledger": IO_CSV.name,
          "records": {d: {"coverage": round(c, 4), "late": d in late, "incomplete_week": d in inc}
                      for d, c in sorted(cov.items())},
          "n_counted_matured": n, "mean_gain_first26": first26, "mean_gain_first52": first52,
          "mean_gain_all_counted": float(np.mean(gains)) if gains else float("nan"),
          "nw_t_all_counted_descriptive": _nw_t(gains), "state": state}
    if not quiet:
        log(f"status: {json.dumps(st, default=str)}")
    return st


# ================================================================== selftest (no returns, no ledger write)
def selftest():
    """Weights check; on the latest v3 date (record-time panel backup when it
    exists, as seas_forward.selftest): io rows build, v3 pairing (icw8 to 1e-12),
    icw9_seas here == seas_forward.build_seas_rows (diff 0, same rows), icw10_io
    == an independent score. Reads no label value; appends to no ledger."""
    wc = weight_checks()
    v3 = pd.read_csv(PL.LEDGER_CSV, usecols=["panel_date"])["panel_date"].astype(str)
    t = pd.Timestamp(v3.max())
    bk = W.R26 / f"composite_panel_v2_through_{t.date().isoformat()}.parquet"
    panel0 = PL.PANEL_PATH
    if bk.exists():
        PL.PANEL_PATH = bk
        log(f"selftest: pairing against the record-time panel {bk.name}")
    try:
        rows, info = build_io_rows(t)
        d8 = check_v3_pairing(rows, t)
        srows, _si = SS.build_seas_rows(t)
        cross, valid = SS.v3_cross(t)
        cross["seas"] = SL.seas_asof(cross["ticker"], t)[0]["seas"].to_numpy()
        cross["io_gap"] = IL.io_gap_asof(cross["ticker"], t)[0]["io_gap"].to_numpy()
        ref = ICW.compute_composite_ic_weighted(cross, weights=dict(ICW10_IO_WEIGHTS))["composite"].to_numpy()[valid]
    finally:
        PL.PANEL_PATH = panel0
    assert list(srows["ticker"]) == list(rows["ticker"])
    a, b = rows["icw9_seas_score"].to_numpy(np.float64), srows["icw9_seas_score"].to_numpy(np.float64)
    assert (np.isnan(a) == np.isnan(b)).all() and np.nanmax(np.abs(a - b)) == 0.0, "icw9_seas != seas_forward"
    got = rows["icw10_io_score"].to_numpy(np.float64)
    assert (np.isnan(ref) == np.isnan(got)).all() and np.nanmax(np.abs(ref - got)) == 0.0
    assert list(rows.columns) == IO_COLS
    # CSV round trip of icw9_seas is exact (the record-time seas pairing reads it back)
    import io as _io
    buf = _io.StringIO()
    srows[["ticker", "icw9_seas_score"]].to_csv(buf, index=False)
    buf.seek(0)
    back = pd.read_csv(buf, float_precision="round_trip")["icw9_seas_score"].to_numpy(np.float64)
    rt = bool(((np.isnan(back) == np.isnan(b)) & (np.where(np.isnan(b), 0, back) == np.where(np.isnan(b), 0, b))).all())
    assert rt, "CSV round trip of icw9_seas not exact"
    s10, s9 = rows["icw10_io_score"], rows["icw9_seas_score"]
    res = {"weights": wc, "date": t.date().isoformat(), "rows": int(len(rows)), "icw8_vs_v3_max_abs": d8,
           "icw9_seas_equals_seas_forward": True, "icw10_equals_independent_score": True,
           "csv_round_trip_exact": rt, "io_info": info,
           "spearman_icw10_vs_icw9_seas": float(s10.rank().corr(s9.rank())),
           "top300_overlap_icw10_vs_icw9_seas": int(len(set(rows.nlargest(300, "icw10_io_score")["ticker"])
                                                       & set(rows.nlargest(300, "icw9_seas_score")["ticker"]))),
           "todo_now": [d.date().isoformat() for d in todo_dates()]}
    log(f"selftest PASS: {json.dumps(res, default=str)}")
    return res


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "status"
    if mode == "selftest":
        r = selftest()
        od = HERE.parents[1] / "out" / "overnight"
        od.mkdir(parents=True, exist_ok=True)
        (od / "io_forward_selftest.json").write_text(json.dumps(r, indent=1, default=str))
    elif mode == "plan":
        log(f"io: {[d.date().isoformat() for d in todo_dates()]}")
    elif mode == "score":
        score()
    elif mode == "status":
        status()
    else:
        raise SystemExit(f"unknown mode {mode}")
