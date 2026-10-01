"""
WO-34 Part B (COO, 2026-09-30): forward side ledger for `icw9_r252` -- the
live icw9_seas factor set with WO-33's R252 weights (trailing 252 matured
label dates, refit every 21 trading days, embargo idx(d) + 41 <= idx(refit)),
recorded next to the seas ledger on the same cap150 v3 rows.
RECORDING ONLY: live picks, live weights and the app do not change.
Doc (review rule fixed before any record): final/models/2026-09-30-r252-forward.md

  r252   prediction_ledger_r252.csv   icw9_r252 vs icw9_seas on v3's cap150 rows,
                                      paired with v3 (icw8) AND the seas ledger
  path   r252_weight_path.csv         append-only R252 weight path (refits from
                                      idx 4935 = WO-33's last R252 refit + 21)

IC source (frozen, doc sec. B2):
  dates <= SEAM (2026-07-13)  WO-33's own per-date ICs, pinned verbatim in
                              final/out/rollweights/r252_ic_pinned.csv (with the
                              WO-33 combined-calendar index); last date on which
                              all 9 WO-33 ICs are finite
  dates  > SEAM               recomputed from the live working panel with WO-33's
                              frames: 8 factors on eligible_cap150_v1 & v1 tickers,
                              seas on eligible_cap150 (load_B SPAC rule) with seas
                              from seas_live (the WO-18 definition)
Weight rule = screen_insider.fit_weights on NW(39) t's (WO-33 window_t exactly).

    python final/src/rollweights/r252_forward.py pin       # one-time: write r252_ic_pinned.csv (WO-33 parquet)
    python final/src/rollweights/r252_forward.py selftest  # reproduce WO-33 R252 path (1e-9); seam; scorer
    python final/src/rollweights/r252_forward.py plan      # dates still to record
    python final/src/rollweights/r252_forward.py score     # blind until a record date matures
    python final/src/rollweights/r252_forward.py status    # counted records / review state
    python final/src/rollweights/r252_forward.py picks     # WO-34b: write current_signal_r252.csv + _meta.json
    python final/src/rollweights/r252_forward.py weekly    # WO-34b: score + picks (what record_weekly runs)

WO-34b (2026-10-01): two outputs for the app's rolling-weights tab, both
TRACKING ONLY. (1) final/out/current_signal_r252.csv + _meta.json: the
Theoretical scorer's picks (same panel date, v2 cap150 universe, seas, and
composite.pick_decile_volq, all imported from current_signal_composite /
its modules) with the current R252 weights instead of the frozen icw9_seas
weights. (2) record_weekly.py calls score() and write_picks() after every
non-dry run, each in its own try; a failure is a logged skip in
ledger_r252_guard_log.csv (r252_score_skipped / r252_picks_skipped).

Records are written ONLY through final/src/reset2026/record_weekly.py, after
the seas (and io) ledgers. Isolated like WO-27 io: any r252 failure skips only
the r252 record for that date, is logged to ledger_r252_guard_log.csv, and never
stops v3/ext/hedge/sue/seas/blend_seas/io.
"""
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

HERE = Path(__file__).resolve().parent
SRC = HERE.parent
sys.path.insert(0, str(SRC / "reset2026"))
sys.path.insert(0, str(SRC / "seasonality"))
sys.path.insert(0, str(SRC / "insider"))

import ic_weighted_composite as ICW        # noqa: E402
import prediction_ledger as PL             # noqa: E402
import screen_insider as SI                # noqa: E402  (daily_corr, newey_west_mean_t, fit_weights)
import seas_forward as SS                  # noqa: E402
import seas_live as SL                     # noqa: E402
import working_panel as W                  # noqa: E402

OUT_DIR = PL.OUT_DIR
R252_CSV = OUT_DIR / "prediction_ledger_r252.csv"
R252_SCORES_CSV = OUT_DIR / "prediction_ledger_r252_scores.csv"
PATH_CSV = OUT_DIR / "r252_weight_path.csv"
LOG_CSV = OUT_DIR / "ledger_record_log.csv"
ANN_CSV = OUT_DIR / "ledger_record_annotations.csv"
GUARD_CSV = OUT_DIR / "ledger_r252_guard_log.csv"
PINNED_CSV = HERE.parents[1] / "out" / "rollweights" / "r252_ic_pinned.csv"
WO33_PATH2_CSV = HERE.parents[1] / "out" / "rollweights" / "weight_paths_step2.csv"
WO33_IC2_PARQ = Path("/Users/ggraham/pipe_dream/.claude/worktrees/agent-ae2ebd3a1386cb352/"
                     "final/out/rollweights/ic_series_step2.parquet")          # gitignored; `pin` + optional selftest only
R252_VERSION = "r252v1_wo33rule_2026-09-30"
# WO-34b: picks files next to the Theoretical ones (main checkout's final/out, like current_signal_composite.py)
PICKS_CSV = Path("/Users/ggraham/pipe_dream/final/out/current_signal_r252.csv")
PICKS_META = Path("/Users/ggraham/pipe_dream/final/out/current_signal_r252_meta.json")
PICKS_COLS = ["ticker", "sector", "close", "market_cap", "volatility_60", "composite_score", "weight", "seas"]
INCOMPLETE_NOTE = ("incomplete_week: paired with the v3 record for this date, which is annotated "
                   "incomplete_week; descriptive only, never a counted record; WO-34 2026-09-30")

LABEL = PL.LABEL
FT = list(ICW.PRODUCTION_WEIGHTS_V9_SEAS)     # 9 factors, live order
FC8 = [c for c in FT if c != "seas"]
SIGNS = dict(ICW.SIGNS_V9_SEAS)
WINDOW = 252
EMBARGO = 41
REFIT_EVERY = 21
SEAM = pd.Timestamp("2026-07-13")             # last date with all 9 WO-33 ICs finite
PIN_FROM = pd.Timestamp("2022-01-03")
WO33_LAST_R252_REFIT_IDX = 4914               # 2026-07-17 in weight_paths_step2.csv
FIRST_FWD_REFIT_IDX = WO33_LAST_R252_REFIT_IDX + REFIT_EVERY
LABEL_MIN_COVERAGE = 0.90                     # matured post-seam IC date: finite-label share of its v1 frame
MIN_IC_NAMES = 20                             # SI.daily_corr default
TOL_REPRO = 1e-9

COLS = ["panel_date", "recorded_at", "r252_version", "refit_date", "refit_idx", "ticker", "sector", "seas",
        "icw8_score", "icw9_seas_score", "icw9_r252_score", "icw9_r252_rank_pct"]
PATH_COLS = (["refit_date", "refit_idx", "first_used", "last_used", "n_min", "n_seas", "n_si", "n_live_dates"]
             + [f"w_{c}" for c in FT] + [f"t_{c}" for c in FT]
             + ["r252_version", "computed_at", "computed_for_panel_date"])
START_AFTER = SS.START_AFTER                  # 2026-09-24, as seas / io
MIN_ROWS = SS.MIN_ROWS
H = 40
FIRST_REVIEW, DROP_REVIEW = 26, 52
NW_LAG = 8


def log(m):
    print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)


def iso_week(d):
    c = pd.Timestamp(d).isocalendar()
    return f"{c[0]}-W{c[1]:02d}"


# ================================================================== pinned WO-33 ICs + calendar
def pin():
    """One-time: copy WO-33's ic_series_step2 (dates PIN_FROM..SEAM) with its
    combined-calendar index into r252_ic_pinned.csv. The IC index IS the WO-33
    calendar (asserted on every WO-33 refit: ic.index[refit_idx] == refit_date)."""
    ic = pd.read_parquet(WO33_IC2_PARQ)[FT]
    P = pd.read_csv(WO33_PATH2_CSV, parse_dates=["refit_date"])
    idx = pd.DatetimeIndex(ic.index)
    for _, r in P[["refit_idx", "refit_date"]].drop_duplicates().iterrows():
        assert idx[int(r["refit_idx"])] == r["refit_date"], f"IC index != WO-33 calendar at {r['refit_idx']}"
    out = ic.copy()
    out.insert(0, "cal_idx", np.arange(len(ic)))
    out = out[(out.index >= PIN_FROM) & (out.index <= SEAM)]
    assert np.isfinite(out[FT].to_numpy()).all(), "pinned range has a non-finite WO-33 IC"
    nxt = ic[ic.index > SEAM].iloc[0]
    assert not np.isfinite(nxt[FC8].to_numpy()).all(), "SEAM is not the last all-finite date"
    out.index.name = "date"
    out.reset_index().assign(date=lambda d: d["date"].dt.date.astype(str)).to_csv(PINNED_CSV, index=False)
    back = load_pinned()
    assert (back[FT].to_numpy() == out[FT].to_numpy()).all(), "pinned CSV round trip not exact"
    log(f"pinned {len(out)} dates {out.index.min().date()}..{out.index.max().date()} "
        f"idx {out['cal_idx'].min()}..{out['cal_idx'].max()} -> {PINNED_CSV}")
    return out


def load_pinned():
    p = pd.read_csv(PINNED_CSV, float_precision="round_trip")
    p["date"] = pd.to_datetime(p["date"])
    p = p.set_index("date")
    ci = p["cal_idx"].to_numpy()
    assert (np.diff(ci) == 1).all(), "pinned calendar not contiguous"
    assert p.index.max() == SEAM
    return p


def calendar(pinned, through=None):
    """Combined calendar from the pinned start: pinned dates (WO-33 idx) then
    working-panel dates after SEAM, idx continuing. Asserts the working panel's
    dates on the pinned range equal the pinned calendar exactly."""
    t = pq.read_table(W.WORKING_PANEL, columns=["date"],
                      filters=[("date", ">=", pinned.index.min().date().isoformat())])
    wd = pd.DatetimeIndex(sorted(pd.to_datetime(pd.Series(t.column("date").unique().to_pylist()))))
    ov = wd[wd <= SEAM]
    if not ov.equals(pd.DatetimeIndex(pinned.index)):
        raise SystemExit("r252: working-panel calendar != WO-33 pinned calendar on the pinned range")
    post = wd[wd > SEAM]
    if through is not None:
        post = post[post <= pd.Timestamp(through)]
    i0 = int(pinned["cal_idx"].iloc[-1]) + 1
    dates = list(pinned.index) + list(post)
    idx = list(pinned["cal_idx"].astype(int)) + list(range(i0, i0 + len(post)))
    return pd.Series(idx, index=pd.DatetimeIndex(dates), name="cal_idx")


# ================================================================== live ICs (dates > SEAM)
_V1T = None


def v1_tickers():
    global _V1T
    if _V1T is None:
        _V1T = set(pq.read_table(W.V1_PANEL, columns=["ticker"]).column("ticker").to_pandas().astype(str).unique())
    return _V1T


def spac_tickers():
    tm = pd.read_csv(W.TICKERS_MASTER, dtype=str, usecols=["ticker", "sicindustry"]).drop_duplicates("ticker")
    return set(tm.loc[tm["sicindustry"].fillna("").str.contains("Blank Check"), "ticker"])


def live_ic(dates, panel=None):
    """Per-date Spearman IC (SI.daily_corr, min 20 names) for each factor on
    the given (matured) dates, WO-33 frames on the live working panel."""
    dates = sorted(pd.Timestamp(d) for d in dates)
    if not dates:
        return pd.DataFrame(columns=FT, dtype=float)
    panel = panel or W.WORKING_PANEL
    need = list(dict.fromkeys(["ticker", "date", "eligible_cap150", "eligible_cap150_v1", LABEL] + FC8))
    p = pd.read_parquet(panel, columns=need, filters=[("date", ">=", dates[0].date().isoformat()),
                                                      ("date", "<=", dates[-1].date().isoformat())])
    p["date"] = pd.to_datetime(p["date"]); p["ticker"] = p["ticker"].astype(str)
    p = p[p["date"].isin(dates)]
    old_t, spac = v1_tickers(), spac_tickers()
    a = p[p["eligible_cap150_v1"].astype(bool) & p["ticker"].isin(old_t)]
    b = p[(p["ticker"].isin(old_t) | ~p["ticker"].isin(spac)) & p["eligible_cap150"].astype(bool)].copy()
    cov = a.groupby("date")[LABEL].apply(lambda s: float(np.isfinite(s.to_numpy(np.float64)).mean()))
    cov = cov.reindex(dates)
    bad = cov[~(cov >= LABEL_MIN_COVERAGE)]
    if len(bad):
        raise SystemExit(f"r252: matured IC date(s) with label coverage < {LABEL_MIN_COVERAGE:.0%}: "
                         f"{[(d.date().isoformat(), None if pd.isna(v) else round(v, 3)) for d, v in bad.items()][:5]}")
    # seas: the WO-18 value depends only on the target month (seas_live), so compute once per target month
    b["tym"] = [SL.target_ym(d) for d in b["date"]]
    parts = []
    for tym, g in b.groupby("tym"):
        t0 = g["date"].min()
        sf, _info = SL.seas_asof(sorted(g["ticker"].unique()), t0)
        parts.append(g.merge(sf[["ticker", "seas"]], on="ticker", how="left"))
    b = pd.concat(parts, ignore_index=True)
    cols = {c: SI.daily_corr(a[["date", c, LABEL]], c, LABEL) for c in FC8}
    cols["seas"] = SI.daily_corr(b[["date", "seas", LABEL]], "seas", LABEL)
    ic = pd.DataFrame(cols).reindex(pd.DatetimeIndex(dates))[FT]
    return ic


# ================================================================== R252 weights
def window_fit(ic, idx_of, i):
    """WO-33 window_t for R252 at refit calendar index i: matured IC dates
    idx in [i-41-251, i-41]; NW(39) t per factor; fit_weights."""
    hi = i - EMBARGO
    lo = hi - WINDOW + 1
    m = (idx_of >= lo) & (idx_of <= hi)
    ts, n = {}, {}
    for c in FT:
        x = ic[c].to_numpy()[m]
        x = x[np.isfinite(x)]
        ts[c] = SI.newey_west_mean_t(x)["t"]
        n[c] = int(len(x))
    used = idx_of[m]
    if len(used):
        assert used.max() + EMBARGO <= i, "GATE A: immature label used"
    w = SI.fit_weights(ts, SIGNS)
    return w, ts, n, (int(used.min()) if len(used) else None, int(used.max()) if len(used) else None)


def ic_table(pinned, cal, hi_idx, panel=None):
    """Pinned ICs (<= SEAM) + live ICs for calendar dates in (SEAM, hi_idx]."""
    post = cal[(cal.index > SEAM) & (cal.to_numpy() <= hi_idx)]
    live = live_ic(list(post.index), panel=panel)
    ic = pd.concat([pinned[FT], live[FT]])
    idx_of = cal.reindex(ic.index).to_numpy()
    assert np.isfinite(idx_of.astype(float)).all(), "IC date off the combined calendar"
    return ic, idx_of.astype(int), int(len(post))


def load_path():
    if not PATH_CSV.exists():
        return pd.DataFrame(columns=PATH_COLS)
    p = pd.read_csv(PATH_CSV, float_precision="round_trip", parse_dates=["refit_date"])
    return p


def refits_for(t, panel=None):
    """(stored path, new refit rows due by t, calendar). New rows: every refit
    idx FIRST_FWD_REFIT_IDX + 21k <= idx(t) not yet in the path CSV."""
    t = pd.Timestamp(t)
    pinned = load_pinned()
    cal = calendar(pinned, through=t)
    if t not in cal.index:
        raise SystemExit(f"r252: {t.date()} not on the working-panel calendar")
    it = int(cal[t])
    stored = load_path()
    have = set(stored["refit_idx"].astype(int)) if len(stored) else set()
    due = [i for i in range(FIRST_FWD_REFIT_IDX, it + 1, REFIT_EVERY) if i not in have]
    new = []
    if due:
        ic, idx_of, n_live = ic_table(pinned, cal, max(due) - EMBARGO, panel=panel)
        inv = pd.Series(cal.index, index=cal.to_numpy())
        for i in due:
            w, ts, n, (lo, hi) = window_fit(ic, idx_of, i)
            if lo is None or lo < int(pinned["cal_idx"].iloc[0]):
                raise SystemExit(f"r252: refit {i} window starts before the pinned range")
            r = {"refit_date": inv[i].date().isoformat(), "refit_idx": i,
                 "first_used": inv[lo].date().isoformat(), "last_used": inv[hi].date().isoformat(),
                 "n_min": min(n.values()), "n_seas": n["seas"], "n_si": n["short_interest_days_to_cover"],
                 "n_live_dates": int(((idx_of >= lo) & (idx_of <= hi) & (idx_of > int(pinned['cal_idx'].iloc[-1]))).sum())}
            if r["n_min"] < WINDOW:
                raise SystemExit(f"r252: refit {i} has only {r['n_min']} finite IC dates (< {WINDOW})")
            r.update({f"w_{c}": w[c] for c in FT}); r.update({f"t_{c}": ts[c] for c in FT})
            r.update({"r252_version": R252_VERSION, "computed_at": "", "computed_for_panel_date": t.date().isoformat()})
            new.append(r)
    return stored, pd.DataFrame(new, columns=PATH_COLS), cal


def weights_at(t, stored, new):
    allp = pd.concat([stored, new], ignore_index=True) if len(new) else stored
    allp = allp.assign(refit_date=pd.to_datetime(allp["refit_date"]))
    allp = allp[allp["refit_date"] <= pd.Timestamp(t)].sort_values("refit_idx")
    if not len(allp):
        raise SystemExit(f"r252: no refit on or before {pd.Timestamp(t).date()}")
    r = allp.iloc[-1]
    return {c: float(r[f"w_{c}"]) for c in FT}, r


# ================================================================== rows
def _recorded(csv):
    if not csv.exists():
        return set()
    return set(pd.read_csv(csv, usecols=["panel_date"])["panel_date"].astype(str))


def recorded_dates():
    return _recorded(R252_CSV)


def todo_dates(v3_new=()):
    """v3 panel dates after START_AFTER (existing + this run's) with no r252 record."""
    have = set()
    if PL.LEDGER_CSV.exists():
        have = set(pd.read_csv(PL.LEDGER_CSV, usecols=["panel_date"])["panel_date"].astype(str))
    ds = {d for d in have if pd.Timestamp(d) > START_AFTER} | {
        pd.Timestamp(d).date().isoformat() for d in v3_new if pd.Timestamp(d) > START_AFTER}
    return sorted(pd.Timestamp(d) for d in ds - recorded_dates())


_PENDING = {}     # iso -> new refit rows computed at build (appended at record)


def build_r252_rows(t):
    """v3's cap150 cross-section (blindness guard inside), seas at score time,
    icw8 / icw9_seas / icw9_r252 over the WHOLE eligible cross-section, then
    v3's row mask. Writes nothing."""
    t = pd.Timestamp(t)
    stored, new, _cal = refits_for(t)
    w, r = weights_at(t, stored, new)
    cross, valid = SS.v3_cross(t)
    sf, sinfo = SL.seas_asof(cross["ticker"], t)
    assert (sf["ticker"].to_numpy() == cross["ticker"].astype(str).to_numpy()).all()
    if not sinfo["coverage"] >= SS.SEAS_MIN_COVERAGE:
        raise SystemExit(f"r252: seas coverage {sinfo['coverage']:.1%} < {SS.SEAS_MIN_COVERAGE:.0%} on {t.date()}")
    cross = cross.copy()
    cross["seas"] = sf["seas"].to_numpy(np.float64)
    s8 = ICW.compute_composite_ic_weighted(cross)["composite"].to_numpy(np.float64)
    s9 = ICW.compute_composite_ic_weighted(cross, weights=SS.WEIGHTS)["composite"].to_numpy(np.float64)
    sr = ICW.compute_composite_ic_weighted(cross, weights=w)["composite"].to_numpy(np.float64)
    out = pd.DataFrame({
        "panel_date": t.date().isoformat(), "recorded_at": "", "r252_version": R252_VERSION,
        "refit_date": pd.Timestamp(r["refit_date"]).date().isoformat(), "refit_idx": int(r["refit_idx"]),
        "ticker": cross["ticker"].to_numpy(), "sector": cross["sector"].to_numpy(),
        "seas": cross["seas"].to_numpy(), "icw8_score": s8, "icw9_seas_score": s9, "icw9_r252_score": sr,
    })[valid].reset_index(drop=True)
    if len(out) < MIN_ROWS:
        raise SystemExit(f"r252: only {len(out)} rows on {t.date()} (< {MIN_ROWS}); skipped")
    out["icw9_r252_rank_pct"] = out["icw9_r252_score"].rank(pct=True, na_option="keep")
    _PENDING[t.date().isoformat()] = new
    info = {"rows": int(len(out)), "refit_date": out["refit_date"].iloc[0], "refit_idx": int(r["refit_idx"]),
            "new_refits": [int(x) for x in new["refit_idx"]], "weights": {c: round(v, 4) for c, v in w.items()},
            "seas_target_month": sinfo["target_month"]}
    return out[COLS], info


def check_v3_pairing(rows, t):
    return SS.check_pairing(rows, t)


def seas_rows(t):
    if not SS.SEAS_CSV.exists():
        return pd.DataFrame(columns=["panel_date", "ticker", "icw9_seas_score"])
    s = pd.read_csv(SS.SEAS_CSV, usecols=["panel_date", "ticker", "icw9_seas_score"], float_precision="round_trip")
    return s[s["panel_date"].astype(str) == pd.Timestamp(t).date().isoformat()].reset_index(drop=True)


def check_seas_pairing(rows, t):
    v = seas_rows(t)
    if len(v) == 0:
        raise SystemExit(f"r252 pairing: seas ledger has no rows for {pd.Timestamp(t).date()} (seas skipped?)")
    if list(v["ticker"].astype(str)) != list(rows["ticker"].astype(str)):
        raise SystemExit(f"r252 pairing: ticker list != seas on {pd.Timestamp(t).date()} ({len(rows)} vs {len(v)})")
    a, b = rows["icw9_seas_score"].to_numpy(np.float64), v["icw9_seas_score"].to_numpy(np.float64)
    nan_ok = np.isnan(a) == np.isnan(b)
    d = np.abs(np.where(np.isnan(a), 0, a) - np.where(np.isnan(b), 0, b))
    if not nan_ok.all() or d.max() != 0.0:
        raise SystemExit(f"r252 pairing: icw9_seas != seas ledger on {pd.Timestamp(t).date()} "
                         f"(max |d| {d.max():.2e}, NaN mismatches {(~nan_ok).sum()})")
    return 0.0


def pair(rows, t):
    d8 = check_v3_pairing(rows, t)
    if len(seas_rows(t)):
        check_seas_pairing(rows, t)
    return d8


def _append(csv, df):
    if csv.exists() and not csv.read_bytes().endswith(b"\n"):
        raise SystemExit(f"{csv.name} does not end in a newline; refusing to append")
    df.to_csv(csv, mode="a", header=not csv.exists(), index=False)


def record_r252(t, rows):
    """Append one date. Duplicate-date guard + blindness re-check + v3 pairing +
    MANDATORY seas pairing; then the new refits (append-only weight path),
    then the ledger rows."""
    iso = pd.Timestamp(t).date().isoformat()
    if iso in recorded_dates():
        raise SystemExit(f"REFUSING: {R252_CSV.name} already has panel_date {iso} (duplicate-date guard)")
    SS.v3_cross(t)
    check_v3_pairing(rows, t)
    check_seas_pairing(rows, t)
    new = _PENDING.get(iso)
    if new is None:
        raise SystemExit(f"r252: no build for {iso} in this run")
    stored = load_path()
    have = set(stored["refit_idx"].astype(int)) if len(stored) else set()
    add = new[~new["refit_idx"].astype(int).isin(have)].copy()
    ri = int(rows["refit_idx"].iloc[0])
    if ri not in have | set(add["refit_idx"].astype(int)):
        raise SystemExit(f"r252: refit {ri} used by the rows is neither stored nor new")
    if len(add):
        add["computed_at"] = pd.Timestamp.now().isoformat()
        _append(PATH_CSV, add[PATH_COLS])
        log(f"appended refits {list(add['refit_idx'].astype(int))} to {PATH_CSV.name}")
    out = rows.copy()
    out["recorded_at"] = pd.Timestamp.now().isoformat()
    out = out[COLS]
    _append(R252_CSV, out)
    W.record_manifest(R252_CSV, pd.Timestamp(t), PL.PANEL_PATH)
    log(f"appended {len(out)} rows to {R252_CSV.name} for {iso} (refit {ri})")
    return out


def log_guard(panel_date, event, detail="", ledger="r252"):
    iso = pd.Timestamp(panel_date).date().isoformat() if panel_date else ""
    row = pd.DataFrame([[pd.Timestamp.now().isoformat(), ledger, iso, iso_week(iso) if iso else "",
                         event, str(detail)[:500]]],
                       columns=["logged_at", "ledger", "panel_date", "iso_week", "event", "detail"])
    _append(GUARD_CSV, row)


class Side:
    """The r252 side ledger as record_weekly.py drives it (seas_forward.Side /
    io_forward.Side interface). Attributes read at call time."""
    name, source, incomplete_note = "r252", "WO-34", INCOMPLETE_NOTE

    @property
    def csv(self):
        return R252_CSV

    def todo(self, v3_new=()):
        return todo_dates(v3_new)

    def build(self, t):
        return build_r252_rows(t)

    def pair(self, rows, t):
        return pair(rows, t)

    def record(self, t, rows):
        return record_r252(t, rows)

    def log_guard(self, iso, event, detail):
        return log_guard(iso, event, detail, ledger="r252")


def side_ledgers():
    if not PINNED_CSV.exists():
        raise SystemExit(f"r252: pinned IC file missing: {PINNED_CSV}")
    return [Side()]


# ================================================================== WO-34b: picks file (Theoretical schema)
def _csc():
    """The live Theoretical scorer, imported lazily so that a problem there can
    only ever skip the picks file, never the r252 ledger record."""
    if str(SRC) not in sys.path:
        sys.path.insert(0, str(SRC))
    import current_signal_composite as CSC
    return CSC


def build_picks(t=None, weights=None):
    """current_signal_composite.main()'s steps, by import, with other weights:
    W.working_cross_section (v2 universe rule) -> eligible_cap150 -> seas for
    the whole eligible cross-section (coverage floor) ->
    ICW.compute_composite_ic_weighted -> C.pick_decile_volq. `t` None = the
    working panel's latest date (the Theoretical file's as-of). `weights`
    None = the R252 weights in force at t (stored path + refits due by t; the
    weight path is NOT appended here -- only a ledger record appends it).
    Reads no label. Writes nothing. Returns (picks frame, meta)."""
    CSC = _csc()
    C, tier = CSC.C, CSC.TIER
    needed = list(dict.fromkeys(["ticker", "date", "sector", "close", "market_cap", "volatility_60",
                                 f"eligible_{tier}"] + C.FACTOR_COLS))
    df_date, uinfo = W.working_cross_section(needed, date=t, path=CSC.PANEL)
    if not len(df_date):
        raise SystemExit(f"r252 picks: no panel rows for {t}")
    as_of = df_date["date"].max()
    elig = df_date[df_date[f"eligible_{tier}"]].reset_index(drop=True)
    if len(elig) < 20:
        raise SystemExit(f"r252 picks: only {len(elig)} eligible names on {as_of.date()}")
    sf, seas_info = SL.seas_asof(elig["ticker"], as_of)
    assert (sf["ticker"].to_numpy() == elig["ticker"].astype(str).to_numpy()).all()
    elig = elig.copy()
    elig["seas"] = sf["seas"].to_numpy(np.float64)
    if not seas_info["coverage"] >= CSC.SEAS_MIN_COVERAGE:
        raise SystemExit(f"r252 picks: seas coverage {seas_info['coverage']:.1%} on {as_of.date()} < "
                         f"{CSC.SEAS_MIN_COVERAGE:.0%}")
    if weights is None:
        stored, new, _cal = refits_for(as_of)
        w, r = weights_at(as_of, stored, new)
        have = set(stored["refit_idx"].astype(int)) if len(stored) else set()
        winfo = {"source": "R252 rolling weights (r252_weight_path.csv rule)", "r252_version": R252_VERSION,
                 "refit_date": pd.Timestamp(r["refit_date"]).date().isoformat(), "refit_idx": int(r["refit_idx"]),
                 "refit_in_weight_path": int(r["refit_idx"]) in have,
                 "window_first_used": str(r["first_used"]), "window_last_used": str(r["last_used"])}
    else:
        w = {c: float(weights[c]) for c in FT}
        winfo = {"source": "weights passed by the caller (test)", "r252_version": None, "refit_date": None,
                 "refit_idx": None, "refit_in_weight_path": None, "window_first_used": None, "window_last_used": None}
    scored = ICW.compute_composite_ic_weighted(elig, weights=w)
    picks = C.pick_decile_volq(elig, scored)
    if not picks:
        raise SystemExit(f"r252 picks: pick_decile_volq returned no picks on {as_of.date()}")
    picks8 = C.pick_decile_volq(elig, ICW.compute_composite_ic_weighted(elig, weights=ICW.PRODUCTION_WEIGHTS))
    picks9 = C.pick_decile_volq(elig, ICW.compute_composite_ic_weighted(elig, weights=SS.WEIGHTS))
    a, b = dict(picks), dict(picks9)
    shared = set(a) & set(b)
    tickers = [tk for tk, _ in picks]
    out = elig[elig["ticker"].isin(tickers)][["ticker", "sector", "close", "market_cap", "volatility_60"]].copy()
    out["composite_score"] = out["ticker"].map(dict(zip(scored["ticker"], scored["composite"])))
    out["weight"] = out["ticker"].map(a)
    out = out.sort_values("weight", ascending=False).reset_index(drop=True)
    out["seas"] = out["ticker"].map(dict(zip(elig["ticker"], elig["seas"])))
    out = out[PICKS_COLS]
    meta = {      # the Theoretical meta's keys, in its order, then one extra block "r252"
        "as_of_date": as_of.strftime("%Y-%m-%d"),
        "tier": tier,
        "n_eligible_universe": int(len(elig)),
        "n_picks": int(len(out)),
        "model_version": f"icw9_r252 ({R252_VERSION})" if weights is None else "caller weights (test)",
        "n_factors": len(w),
        "construction": "decile_volq: top decile by IC-weighted composite score "
                        "within each of 5 trailing-volatility quintiles, "
                        "inverse-vol weighted, 40-trading-day hold, no stop-loss",
        "factor_signs": {k: SIGNS[k] for k in w},
        "factor_weights": {k: round(v, 4) for k, v in w.items()},
        "seas": {"definition": "Heston-Sadka: mean same-calendar-month return over the prior 10 years "
                               "(target month = month of t+28 calendar days; >= 5 years; SEP closeadj)",
                 "coverage": round(seas_info["coverage"], 4), "target_month": seas_info["target_month"],
                 "months_used": seas_info["months_used"], "basis_flag": seas_info["basis_flag"],
                 "code": "final/src/seasonality/seas_live.py"},
        "picks_overlap_vs_icw8": CSC.overlap(picks, picks8),
        "backtest_summary": {
            "model_version": f"icw9_r252 ({R252_VERSION})",
            "note": "No backtest number is carried in this file. R252 = the live icw9_seas factor set with "
                    "rolling weights (trailing 252 matured label dates, refit every 21 trading days). "
                    "Its walk-forward results and caveats are in the docs below; the forward record is "
                    "the only evidence that counts from here.",
            "docs": ["final/models/2026-09-30-rolling-weights.md", "final/models/2026-09-30-r252-forward.md"],
            "forward_record": "prediction_ledger_r252.csv / prediction_ledger_r252_scores.csv (weekly; paired "
                              "rho(icw9_r252) - rho(icw9_seas); first review at 26 counted matured records)",
        },
        "writeup": "final/models/2026-09-30-r252-forward.md",
        "preregistration": "final/models/2026-09-30-r252-forward.md (sec. B5, review rule)",
        "panel_source": W.WORKING_PANEL_SOURCE,
        "universe_rule": "v2 eligible_cap150, SPACs excluded unless in the old 4,011-ticker grid "
                         f"({uinfo.get('spac_rows_dropped_eligible_' + tier, 0)} eligible SPAC rows dropped)",
        "role": "candidate",
        "note": "TRACKING ONLY, NOT ACTED ON. Same universe, date, seas and decile_volq construction as the "
                "Theoretical picks (current_signal_composite.csv); only the factor weights differ (current "
                "R252 rolling weights). Unverified on new data; no live weight or pick change follows from "
                "this file without a decision by Gabe.",
        "r252": dict(winfo, factor_weights_full={k: float(v) for k, v in w.items()},
                     picks_overlap_vs_icw9_seas={
                         "n_icw9_r252": len(a), "n_icw9_seas": len(b), "shared": len(shared),
                         "share_of_icw9_r252": round(len(shared) / max(len(a), 1), 4),
                         "weight_overlap": round(float(sum(min(a[x], b[x]) for x in shared)), 4)},
                     written_at=pd.Timestamp.now().isoformat()),
    }
    return out, meta


def write_picks(t=None, weights=None, out_dir=None):
    """Write current_signal_r252.csv + _meta.json (each via a temp file +
    replace, so a failure never leaves a half-written file). `out_dir` writes
    both into that directory instead (tests)."""
    out, meta = build_picks(t=t, weights=weights)
    csv, mj = PICKS_CSV, PICKS_META
    if out_dir is not None:
        od = Path(out_dir)
        od.mkdir(parents=True, exist_ok=True)
        csv, mj = od / PICKS_CSV.name, od / PICKS_META.name
    tc, tm = csv.with_name(csv.name + ".tmp"), mj.with_name(mj.name + ".tmp")
    try:
        out.to_csv(tc, index=False)
        tm.write_text(json.dumps(meta, indent=2))
        tc.replace(csv)
        tm.replace(mj)
    finally:
        for x in (tc, tm):
            if x.exists():
                x.unlink()
    log(f"r252 picks as of {meta['as_of_date']}: {meta['n_picks']} picks from {meta['n_eligible_universe']} eligible "
        f"(refit {meta['r252']['refit_idx']}, overlap vs icw9_seas {meta['r252']['picks_overlap_vs_icw9_seas']['shared']}) "
        f"-> {csv}")
    return out, meta


# ================================================================== score / status (post-maturity only)
def matured(pdate, cal):
    return int((cal > pd.Timestamp(pdate)).sum()) >= H + 1


def score_frame(df):
    r = df["realized"].to_numpy(np.float64)
    sr, s9 = df["icw9_r252_score"].to_numpy(np.float64), df["icw9_seas_score"].to_numpy(np.float64)
    m = np.isfinite(sr) & np.isfinite(s9) & np.isfinite(r)
    sp = lambda a, b: PL._spearman(np.asarray(a, np.float64), np.asarray(b, np.float64))  # noqa: E731
    rr, r9 = sp(sr[m], r[m]), sp(s9[m], r[m])
    return {"n_names": int(m.sum()), "rho_icw9_r252": rr, "rho_icw9_seas": r9, "gain": rr - r9}


def score():
    if not R252_CSV.exists():
        log(f"No {R252_CSV.name} yet -- nothing to score")
        return []
    led = pd.read_csv(R252_CSV, float_precision="round_trip")
    done = set(pd.read_csv(R252_SCORES_CSV, usecols=["panel_date"])["panel_date"].astype(str)) \
        if R252_SCORES_CSV.exists() else set()
    cal, _src = SS.trading_calendar()
    results = []
    for pdate, rows in led.groupby(led["panel_date"].astype(str)):
        if pdate in done:
            continue
        if not matured(pdate, cal):
            log(f"r252 {pdate}: not matured (blind) -- nothing scored")
            continue
        cross, _u = W.working_cross_section([LABEL], date=pdate, path=PL.PANEL_PATH)
        df = rows.merge(cross[["ticker", LABEL]].rename(columns={LABEL: "realized"}), on="ticker", how="left")
        if int(np.isfinite(df["realized"].to_numpy(np.float64)).sum()) < 20:
            log(f"r252 {pdate}: < 20 finite labels -- not scored yet")
            continue
        st = score_frame(df)
        st.update({"panel_date": pdate, "scored_at": pd.Timestamp.now().isoformat(),
                   "version": rows["r252_version"].iloc[0], "refit_idx": int(rows["refit_idx"].iloc[0])})
        results.append(st)
        log(f"r252 {pdate}: gain {st['gain']:+.4f} (n {st['n_names']})")
    if results:
        _append(R252_SCORES_CSV, pd.DataFrame(results))
    return results


def excluded_dates():
    late, inc = set(), set()
    if LOG_CSV.exists():
        lg = pd.read_csv(LOG_CSV)
        lg = lg[(lg["ledger"] == R252_CSV.name) & lg["recorded_late"].astype(str).str.lower().eq("true")]
        late = set(lg["panel_date"].astype(str))
    if ANN_CSV.exists():
        an = pd.read_csv(ANN_CSV)
        an = an[(an["ledger"] == R252_CSV.name) & an["annotation"].astype(str).str.startswith("incomplete_week")]
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
    if not R252_CSV.exists():
        st = {"ledger": R252_CSV.name, "state": "NO RECORDS", "n_counted_matured": 0}
        log(f"status: {st}")
        return st
    ds = sorted(set(pd.read_csv(R252_CSV, usecols=["panel_date"])["panel_date"].astype(str)))
    late, inc = excluded_dates()
    elig = [d for d in ds if d not in late and d not in inc]
    sc = pd.read_csv(R252_SCORES_CSV) if R252_SCORES_CSV.exists() else pd.DataFrame(columns=["panel_date", "gain"])
    sc["panel_date"] = sc["panel_date"].astype(str)
    g = sc.set_index("panel_date")["gain"] if len(sc) else pd.Series(dtype=float)
    counted = [d for d in elig if d in g.index]
    n = len(counted)
    gains = [float(g[d]) for d in counted]
    m26 = float(np.mean(gains[:FIRST_REVIEW])) if n >= FIRST_REVIEW else float("nan")
    m52 = float(np.mean(gains[:DROP_REVIEW])) if n >= DROP_REVIEW else float("nan")
    if n < FIRST_REVIEW:
        state = f"INSUFFICIENT ({n} of {FIRST_REVIEW} counted matured records)"
    elif n < DROP_REVIEW:
        state = ("FIRST REVIEW: mean > 0 -> KEEP TRACKING, bring to Gabe (drop check at 52 still applies)"
                 if m26 > 0 else "FIRST REVIEW: mean <= 0 -> CONTINUE to the drop check at 52")
    else:
        state = ("DROP (paired mean over the first 52 <= 0)" if m52 <= 0
                 else "KEEP at the drop check (paired mean over the first 52 > 0; bring to Gabe)")
    st = {"ledger": R252_CSV.name, "records": ds, "late": sorted(late), "incomplete_week": sorted(inc),
          "n_counted_matured": n, "mean_gain_first26": m26, "mean_gain_first52": m52,
          "mean_gain_all_counted": float(np.mean(gains)) if gains else float("nan"),
          "nw_t_all_counted_descriptive": _nw_t(gains), "state": state}
    if not quiet:
        log(f"status: {json.dumps(st, default=str)}")
    return st


# ================================================================== selftest (no returns, no ledger write)
def selftest(seam_from="2026-01-02"):
    """(1) r252_forward's window_fit on the pinned ICs reproduces every WO-33
    R252 refit whose window lies in the pinned range (w and t, 1e-9); (2) the
    full WO-33 R252 path from WO-33's own IC parquet when it exists; (3) seam:
    live-recomputed ICs vs the pinned WO-33 ICs on seam_from..SEAM (descriptive);
    (4) refits due today (writes nothing); (5) scorer on the latest v3 date:
    icw9_seas == seas_forward (diff 0), icw8 pairs with v3, icw9_r252 == an
    independent SI.composite_score-style computation. Reads no label value on
    or after any record date; appends to nothing."""
    res = {}
    pinned = load_pinned()
    P = pd.read_csv(WO33_PATH2_CSV, float_precision="round_trip", parse_dates=["refit_date"])
    R = P[P["arm"] == "R252"].reset_index(drop=True)
    ic = pinned[FT]; idx_of = pinned["cal_idx"].to_numpy().astype(int)
    lo0, hi0 = int(idx_of[0]), int(idx_of[-1])
    wd, td, n = 0.0, 0.0, 0
    for _, r in R.iterrows():
        i = int(r["refit_idx"])
        if i - EMBARGO - WINDOW + 1 < lo0 or i - EMBARGO > hi0:
            continue
        w, ts, _n, _ = window_fit(ic, idx_of, i)
        wd = max(wd, max(abs(w[c] - r[f"w_{c}"]) for c in FT))
        td = max(td, max(abs(ts[c] - r[f"t_{c}"]) for c in FT if np.isfinite(ts[c])))
        n += 1
    assert n >= 10 and wd < TOL_REPRO and td < TOL_REPRO, f"pinned reproduction FAIL: n {n} w {wd} t {td}"
    res["pinned_reproduction"] = {"n_refits": n, "max_abs_w": wd, "max_abs_t": td, "tol": TOL_REPRO, "pass": True}
    log(f"selftest (1): {n} WO-33 R252 refits reproduced from the pinned ICs, max |dw| {wd:.2e}, |dt| {td:.2e}")
    if WO33_IC2_PARQ.exists():
        full = pd.read_parquet(WO33_IC2_PARQ)[FT]
        fi = np.arange(len(full))
        wd2 = 0.0
        for _, r in R.iterrows():
            i = int(r["refit_idx"])
            if i - EMBARGO < 0:
                continue
            w, _ts, _n, _ = window_fit(full, fi, i)
            wd2 = max(wd2, max(abs(w[c] - r[f"w_{c}"]) for c in FT))
        assert wd2 < TOL_REPRO, f"full-path reproduction FAIL {wd2}"
        res["full_path_reproduction"] = {"n_refits": int(len(R)), "max_abs_w": wd2, "pass": True}
        log(f"selftest (2): full WO-33 R252 path ({len(R)} refits) reproduced, max |dw| {wd2:.2e}")
    else:
        res["full_path_reproduction"] = "skipped (WO-33 IC parquet absent)"
    # (3) seam
    cal = calendar(pinned)
    ov = [d for d in pinned.index if d >= pd.Timestamp(seam_from)]
    liv = live_ic(ov)
    d = (liv[FT] - pinned.loc[ov, FT]).abs()
    res["seam_check"] = {"dates": f"{ov[0].date()}..{ov[-1].date()}", "n_dates": len(ov),
                         "max_abs_ic_diff": {c: float(d[c].max()) for c in FT},
                         "mean_abs_ic_diff": {c: float(d[c].mean()) for c in FT},
                         "live_nan_dates": {c: int(liv[c].isna().sum()) for c in FT}}
    # weights on the last pinned-only refit, pinned vs live ICs (same window)
    i = WO33_LAST_R252_REFIT_IDX
    w_p, _, _, _ = window_fit(pinned[FT], idx_of, i)
    alt = pinned[FT].copy(); alt.loc[ov, FT] = liv[FT].to_numpy()
    w_l, _, _, _ = window_fit(alt, idx_of, i)
    res["seam_check"]["refit_4914_weights_pinned_vs_liveIC_max_abs"] = max(abs(w_p[c] - w_l[c]) for c in FT)
    log(f"selftest (3): seam {json.dumps(res['seam_check'], default=float)}")
    # (4) refits due as of the latest panel date (no write)
    tmax = cal.index.max()
    stored, new, _ = refits_for(tmax)
    res["refits_due_now"] = {"as_of": tmax.date().isoformat(), "stored": int(len(stored)),
                             "new": new[["refit_date", "refit_idx", "first_used", "last_used", "n_min", "n_live_dates"]
                                        + [f"w_{c}" for c in FT]].to_dict("records")}
    log(f"selftest (4): refits due as of {tmax.date()}: {[r['refit_idx'] for r in res['refits_due_now']['new']]}")
    # (5) scorer on the latest v3 date (record-time panel backup when it exists)
    v3 = pd.read_csv(PL.LEDGER_CSV, usecols=["panel_date"])["panel_date"].astype(str)
    t = pd.Timestamp(v3.max())
    bk = W.R26 / f"composite_panel_v2_through_{t.date().isoformat()}.parquet"
    panel0 = PL.PANEL_PATH
    if bk.exists():
        PL.PANEL_PATH = bk
    try:
        stored, new, _ = refits_for(t)
        w, rr = weights_at(t, stored, new)
        cross, valid = SS.v3_cross(t)
        cross = cross.copy()
        cross["seas"] = SL.seas_asof(cross["ticker"], t)[0]["seas"].to_numpy()
        rows, info = build_r252_rows(t)
        d8 = check_v3_pairing(rows, t)
        srows, _si = SS.build_seas_rows(t)
    finally:
        PL.PANEL_PATH = panel0
    assert list(srows["ticker"]) == list(rows["ticker"])
    a, b = rows["icw9_seas_score"].to_numpy(np.float64), srows["icw9_seas_score"].to_numpy(np.float64)
    assert (np.isnan(a) == np.isnan(b)).all() and np.nanmax(np.abs(a - b)) == 0.0, "icw9_seas != seas_forward"
    # independent score: SI.composite_score arithmetic on this cross-section
    cc = cross.assign(date=t)
    for c in FT:
        cc[f"rz_{c}"] = SI.rank_z(cc, c)
    ref = SI.composite_score(cc, w).to_numpy(np.float64)[valid]
    got = rows["icw9_r252_score"].to_numpy(np.float64)
    assert (np.isnan(ref) == np.isnan(got)).all() and np.nanmax(np.abs(ref - got)) < 1e-12, "icw9_r252 != independent"
    assert list(rows.columns) == COLS
    _PENDING.clear()
    res["scorer"] = {"date": t.date().isoformat(), "panel": (bk.name if bk.exists() else PL.PANEL_PATH.name),
                     "rows": int(len(rows)), "icw8_vs_v3_max_abs": d8, "icw9_seas_equals_seas_forward": True,
                     "icw9_r252_equals_independent_1e-12": True, "refit_used": info["refit_idx"],
                     "weights_used": info["weights"],
                     "spearman_r252_vs_icw9_seas": float(rows["icw9_r252_score"].rank().corr(rows["icw9_seas_score"].rank())),
                     "top300_overlap_r252_vs_icw9_seas": int(len(set(rows.nlargest(300, "icw9_r252_score")["ticker"])
                                                                 & set(rows.nlargest(300, "icw9_seas_score")["ticker"])))}
    res["todo_now"] = [x.date().isoformat() for x in todo_dates()]
    log(f"selftest PASS: {json.dumps(res['scorer'], default=str)}")
    return res


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "status"
    if mode == "pin":
        pin()
    elif mode == "selftest":
        r = selftest()
        (HERE.parents[1] / "out" / "rollweights" / "r252_forward_selftest.json").write_text(
            json.dumps(r, indent=1, default=str))
    elif mode == "plan":
        log(f"r252: {[d.date().isoformat() for d in todo_dates()]}")
    elif mode == "score":
        score()
    elif mode == "status":
        status()
    elif mode == "picks":
        write_picks()
    elif mode == "weekly":
        score()
        write_picks()
    else:
        raise SystemExit(f"unknown mode {mode}")
