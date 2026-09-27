"""
WO-15: icw9-with-SUE forward side ledger (forward confirmation #1 of WO-13).
Pre-registration (committed before any record):
    final/models/2026-09-26-sue-forward-ledger.md

    python final/src/sue/sue_forward.py selftest   # code reproduction only (no IC)
    python final/src/sue/sue_forward.py score      # blind until a record date matures
    python final/src/sue/sue_forward.py status     # counted dates / verdict state
    python final/src/sue/sue_forward.py plan       # SUE dates still to record

Records are written ONLY through final/src/reset2026/record_weekly.py (the
WO-14 weekly path), right after v3, on the v3 row set of each date.

Live `sue` = WO-13's frozen definition (build_sue.load_arq / build_filings /
factor_asof, imported), on data/sharadar/sf1_arq_eps_live.parquet (one pull,
one split basis; sf1_eps_live_pull.py) after two point-in-time row filters:
datekey <= prev_td(t) and lastupdated <= t.
"""
import json
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "reset2026"))
sys.path.insert(0, str(HERE))

import build_sue as B                      # noqa: E402
import composite as C                      # noqa: E402
import ic_weighted_composite as ICW        # noqa: E402
import prediction_ledger as PL             # noqa: E402
import working_panel as W                  # noqa: E402

LIVE = W.SH / "sf1_arq_eps_live.parquet"
PULL_SCRIPT = HERE / "sf1_eps_live_pull.py"
# The literal 2026-09-08 SF1 file. B.SF1 (sf1_fundamentals.parquet) is topped
# up live by WO-16 since 2026-09-26; its pre-top-up copy is kept as
# sf1_fundamentals_through_2026-09-08.parquet (631,185 rows, date max 09-08).
SF1_BASIS = W.SH / "sf1_fundamentals_through_2026-09-08.parquet"
SF1_BASIS_ROWS = 631185
BASIS_DATE = pd.Timestamp("2026-09-08")
ACTIONS = W.SH / "actions.csv"
WO14_REPORT = W.R26 / "downcap_v2" / "refresh_report_2026-09-24.json"

OUT_DIR = PL.OUT_DIR
SUE_CSV = OUT_DIR / "prediction_ledger_sue.csv"
SUE_SCORES_CSV = OUT_DIR / "prediction_ledger_sue_scores.csv"
LOG_CSV = OUT_DIR / "ledger_record_log.csv"
ANN_CSV = OUT_DIR / "ledger_record_annotations.csv"
SUE_VERSION = "sue1_icw9sue_2026-09-26"
SUE_COLS = ["panel_date", "recorded_at", "sue_version", "ticker", "sue", "sue_filing_date",
            "sue_reportperiod", "sue_age_days", "icw8_score", "icw9_sue_score", "icw9_sue_rank_pct",
            "sf1_live_pulled_at", "sf1_rows_excluded_lastupdated"]
LABEL = PL.LABEL
START_AFTER = pd.Timestamp("2026-09-08")
BACKFILL_DATES = {"2026-09-18", "2026-09-24"}   # v3 dates that predate WO-15 (doc sec. 7)
BACKFILL_MAX_CHANGED_SHARE = 0.05
COVERAGE_FLOOR = 0.70
MIN_COUNTED = 6
H = 40
TOL_ICW8 = 1e-12

# PIT MODE (doc sec. 2, pre-registered fallback). Decided ONCE at the first
# live pull (pulled_at 2026-09-26T21:58:25, 10 API calls, 91,310 rows), before any record, from the sec. 7 (b) metric on W38/W39:
# W38 2026-09-18: 2 of 3,053 v3 tickers change sue (0.066%), 435 rows excluded;
# W39 2026-09-24: 0 of 3,048 (0.000%), 120 rows excluded. <= 5% -> NO fallback.
# True = datekey <= prev_td(t) AND lastupdated <= t; False = the fallback:
# datekey <= prev_td(t) + first-reported row (build_filings); lastupdated is a
# diagnostic only (sf1_rows_excluded_lastupdated = rows the filter WOULD drop).
USE_LASTUPDATED_FILTER = True
# BACKFILL (doc sec. 7): DECLINED 2026-09-26 at the first live pull. (a) passed
# (icw8 max|d| 1.0e-16 both dates) and (b) passed, but (c) basis validation
# FAILED: 176 eps mismatches on 15 names not on the split lists (see doc Results). "declined" drops BACKFILL_DATES from the SUE dates, so
# the ledger starts at the next complete week and a failed gate cannot block
# later weekly runs. "attempt" = the gate passed at measurement; the dates are
# recorded through record_weekly (gate re-checked in preflight).
BACKFILL_DECISION = "declined"

# FROZEN (2026-09-26, pre-registered before any record). The ICW rule on the
# 8 production t's (ICW9_T_USED) plus sue's WO-13 pooled NW t, sign +1.
SUE_T = 2.169917640299337
ICW9_SUE_T_USED = {**{k: PL.ICW9_T_USED[k] for k in C.FACTOR_COLS}, "sue": SUE_T}
ICW9_SUE_SIGNS = {**C.FACTOR_SIGNS, "sue": +1}      # sue NOT added to C.FACTOR_SIGNS
ICW9_SUE_WEIGHTS = {
    "momentum_12_1": 0.0432,
    "pct_from_high_252": 0.0113,
    "volatility_60": -0.0113,
    "gross_profitability": 0.5169,
    "accruals": -0.1412,
    "net_issuance_pct": -0.1214,
    "days_to_next_filing_seasonal": -0.0113,
    "short_interest_days_to_cover": -0.0113,
    "sue": 0.1321,
}


def log(m):
    print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)


# ------------------------------------------------------------------ calendar / live data
def panel_calendar(path=None):
    t = pq.read_table(path or W.WORKING_PANEL, columns=["date"])
    return np.sort(pd.to_datetime(pd.Series(t.column("date").unique().to_pylist())).to_numpy())


def prev_td(t, cal):
    t64 = np.datetime64(pd.Timestamp(t))
    i = int(np.searchsorted(cal, t64)) - 1
    if i < 0:
        raise SystemExit(f"no trading date before {pd.Timestamp(t).date()}")
    return pd.Timestamp(cal[i])


def load_live():
    if not LIVE.exists():
        raise SystemExit(f"{LIVE} does not exist. Run: python final/src/sue/sf1_eps_live_pull.py")
    df = pd.read_parquet(LIVE)
    for c in ("date", "reportperiod", "lastupdated"):
        df[c] = pd.to_datetime(df[c])
    df["ticker"] = df["ticker"].astype(str)
    return df, pd.Timestamp(df["pulled_at"].iloc[0])


def fresh_for(live, pulled_at, t, cal):
    """Freshness rule (doc sec. 4): pulled after t, and covers prev_td(t)."""
    t = pd.Timestamp(t)
    ok = pulled_at.normalize() > t.normalize() and live["date"].max() >= prev_td(t, cal)
    return ok, (f"pulled_at {pulled_at} (must be after {t.date()}), live max date "
                f"{live['date'].max().date()} (must be >= prev_td {prev_td(t, cal).date()})")


def ensure_live(targets, cal):
    """record_weekly path: pull once iff there is something to record and the
    live file does not postdate the latest target."""
    if not targets:
        return None
    worst = max(pd.Timestamp(d) for d in targets)
    need = not LIVE.exists()
    if not need:
        _l, pa = load_live()
        need = pa.normalize() <= worst.normalize()
    if need:
        log(f"SF1 live file missing or not newer than {worst.date()}: running {PULL_SCRIPT.name}")
        rc = subprocess.run([sys.executable, str(PULL_SCRIPT)]).returncode
        if rc != 0:
            raise SystemExit(f"SF1 live pull failed (rc {rc}); nothing recorded. "
                             f"Command: python final/src/sue/sf1_eps_live_pull.py")
    live, pa = load_live()
    for d in targets:
        ok, why = fresh_for(live, pa, d, cal)
        if not ok:
            raise SystemExit(f"preflight: SF1 live not fresh for {pd.Timestamp(d).date()}: {why}")
    return live, pa


def pit_rows(live, t, cal, use_lastupdated=True):
    """Live ARQ rows visible at t: datekey <= prev_td(t) [and lastupdated <= t]."""
    t = pd.Timestamp(t)
    by_date = live[live["date"] <= prev_td(t, cal)]
    if not use_lastupdated:
        return by_date, 0
    keep = by_date["lastupdated"] <= t
    return by_date[keep], int((~keep).sum())


def sue_asof(rows, tickers, t, cal):
    """build_sue's own functions on `rows`: returns frame aligned to `tickers`."""
    arq, _info = B.load_arq(raw=rows)
    with np.errstate(all="ignore"):
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            fil = B.build_filings(arq)
    p = pd.DataFrame({"ticker": pd.Series(list(tickers), dtype=str), "date": pd.Timestamp(t)})
    out = B.factor_asof(fil, p, cal)
    assert (out["ticker"].to_numpy() == p["ticker"].to_numpy()).all()
    return out


# ------------------------------------------------------------------ basis validation
def load_basis():
    old = pd.read_parquet(SF1_BASIS, columns=["ticker", "dimension", "date", "reportperiod", "eps"])
    if len(old) != SF1_BASIS_ROWS or pd.to_datetime(old["date"]).max() != BASIS_DATE:
        raise SystemExit(f"{SF1_BASIS.name} is not the 2026-09-08 file ({len(old)} rows, "
                         f"max date {pd.to_datetime(old['date']).max().date()})")
    return old


def split_names_since_basis():
    a = pd.read_csv(ACTIONS, usecols=["date", "action", "ticker"])
    s = set(a.loc[(a["action"] == "split") & (pd.to_datetime(a["date"]) > BASIS_DATE), "ticker"].astype(str))
    wo14 = set(json.loads(WO14_REPORT.read_text()).get("split_like_blocked", []))
    return s | wo14, {"actions_csv_splits_after_basis": sorted(s), "wo14_split_like_blocked": sorted(wo14)}


def basis_validation(live):
    """Doc sec. 4: overlapping (ticker, date, reportperiod) keys must agree on
    eps except for names with a split since 2026-09-08. Raises on any other."""
    old = load_basis()
    old = old[old["dimension"] == "ARQ"].drop(columns="dimension")
    old["date"] = pd.to_datetime(old["date"])
    old["reportperiod"] = pd.to_datetime(old["reportperiod"])
    old["ticker"] = old["ticker"].astype(str)
    key = ["ticker", "date", "reportperiod"]
    o = old.drop_duplicates(key, keep="first")
    n = live[key + ["eps"]].drop_duplicates(key, keep="first")
    m = o.merge(n, on=key, how="inner", suffixes=("_old", "_live"))
    a, b = m["eps_old"].to_numpy(np.float64), m["eps_live"].to_numpy(np.float64)
    with np.errstate(divide="ignore", invalid="ignore"):
        same = ((np.isnan(a) & np.isnan(b)) | ((a == 0) & (b == 0))
                | (np.abs(b / a - 1.0) <= 1e-9))
    bad = m[~same]
    allowed, src = split_names_since_basis()
    unexplained = bad[~bad["ticker"].isin(allowed)]
    live_win = live[live["date"] <= BASIS_DATE]
    rep = {"overlap_keys": int(len(m)), "mismatch_rows": int(len(bad)),
           "mismatch_tickers": sorted(bad["ticker"].unique().tolist()),
           "unexplained_rows": int(len(unexplained)),
           "unexplained_tickers": sorted(unexplained["ticker"].unique().tolist()),
           "old_keys_in_live_window_not_in_live": int(len(
               o[(o["date"] >= live["date"].min())].merge(n[key], on=key, how="left", indicator=True)
               .query("_merge == 'left_only'"))),
           "live_keys_to_basis_date_not_in_old": int(len(
               live_win[key].drop_duplicates().merge(o[key], on=key, how="left", indicator=True)
               .query("_merge == 'left_only'"))),
           "split_sources": src}
    if len(bad):
        ratios = (bad["eps_live"] / bad["eps_old"]).groupby(bad["ticker"]).agg(["min", "max", "size"])
        rep["mismatch_ratio_by_ticker"] = {t: [float(r["min"]), float(r["max"]), int(r["size"])]
                                          for t, r in ratios.iterrows()}
    if len(unexplained):
        raise SystemExit(f"BASIS VALIDATION FAILED (STOP): {len(unexplained)} eps mismatches on "
                         f"non-split names {rep['unexplained_tickers'][:30]}")
    return rep


# ------------------------------------------------------------------ rows
def v3_cross(t):
    """Exactly prediction_ledger.record()'s cross-section and v3 row mask."""
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


def build_sue_rows(t, live, pulled_at, cal):
    t = pd.Timestamp(t)
    cross, valid = v3_cross(t)
    _lu_rows, n_excl = pit_rows(live, t, cal, use_lastupdated=True)
    rows_pit = _lu_rows if USE_LASTUPDATED_FILTER else pit_rows(live, t, cal, use_lastupdated=False)[0]
    sf = sue_asof(rows_pit, cross["ticker"], t, cal)
    cross = cross.copy()
    cross["sue"] = sf["sue"].to_numpy(np.float64)
    s8 = ICW.compute_composite_ic_weighted(cross)["composite"].to_numpy(np.float64)
    s9 = ICW.compute_composite_ic_weighted(cross, weights=ICW9_SUE_WEIGHTS)["composite"].to_numpy(np.float64)
    out = pd.DataFrame({
        "panel_date": t.date().isoformat(),
        "recorded_at": "",
        "sue_version": SUE_VERSION,
        "ticker": cross["ticker"].to_numpy(),
        "sue": cross["sue"].to_numpy(),
        "sue_filing_date": sf["sue_filing_date"].dt.date.astype(str).where(sf["sue_filing_date"].notna(), "").to_numpy(),
        "sue_reportperiod": sf["sue_reportperiod"].dt.date.astype(str).where(sf["sue_reportperiod"].notna(), "").to_numpy(),
        "sue_age_days": sf["sue_age_days"].to_numpy(np.float64),
        "icw8_score": s8,
        "icw9_sue_score": s9,
    })[valid].reset_index(drop=True)
    out["icw9_sue_rank_pct"] = out["icw9_sue_score"].rank(pct=True, na_option="keep")
    out["sf1_live_pulled_at"] = pulled_at.isoformat()
    out["sf1_rows_excluded_lastupdated"] = n_excl
    # gate (b) diagnostic: the same without the lastupdated filter
    rows_nolu, _ = pit_rows(live, t, cal, use_lastupdated=False)
    sf0 = sue_asof(rows_nolu, cross["ticker"], t, cal)["sue"].to_numpy(np.float64)[valid]
    s1 = sue_asof(_lu_rows, cross["ticker"], t, cal)["sue"].to_numpy(np.float64)[valid]
    changed = (np.isfinite(s1) != np.isfinite(sf0)) | (np.isfinite(s1) & np.isfinite(sf0) & (np.abs(s1 - sf0) > 1e-12))
    info = {"panel_date": t.date().isoformat(), "rows": int(len(out)),
            "finite_sue": int(np.isfinite(out["sue"].to_numpy(np.float64)).sum()),
            "coverage": float(np.isfinite(out["sue"].to_numpy(np.float64)).mean()),
            "coverage_with_lastupdated_filter": float(np.isfinite(s1).mean()),
            "coverage_without_lastupdated_filter": float(np.isfinite(sf0).mean()),
            "use_lastupdated_filter": USE_LASTUPDATED_FILTER,
            "rows_excluded_lastupdated": n_excl, "rows_datekey_eligible": int(len(rows_nolu)),
            "tickers_sue_changed_by_lastupdated": int(changed.sum()),
            "share_sue_changed_by_lastupdated": float(changed.mean()),
            "prev_td": prev_td(t, cal).date().isoformat()}
    return out, info


def v3_rows(t):
    v3 = pd.read_csv(PL.LEDGER_CSV, usecols=["panel_date", "ticker", "ic_weighted_score"])
    return v3[v3["panel_date"].astype(str) == pd.Timestamp(t).date().isoformat()].reset_index(drop=True)


def check_pairing(rows, t):
    """Doc sec. 3: tickers == v3's rows (same order); icw8 == v3 to 1e-12."""
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


def backfill_gate(rows, info, t, basis_ok):
    """Doc sec. 7, for BACKFILL_DATES only. Raises (nothing written) if any fails."""
    d = check_pairing(rows, t)                                            # (a)
    if info["share_sue_changed_by_lastupdated"] > BACKFILL_MAX_CHANGED_SHARE:   # (b)
        raise SystemExit(f"backfill gate (b) FAILED on {pd.Timestamp(t).date()}: "
                         f"{info['share_sue_changed_by_lastupdated']:.2%} of v3 tickers change sue "
                         f"under the lastupdated filter (> {BACKFILL_MAX_CHANGED_SHARE:.0%})")
    if not basis_ok:                                                      # (c)
        raise SystemExit("backfill gate (c) FAILED: basis validation")
    return {"a_icw8_max_abs_diff": d, "b_share_changed": info["share_sue_changed_by_lastupdated"],
            "b_rows_excluded": info["rows_excluded_lastupdated"], "c_basis": True}


def recorded_dates():
    if not SUE_CSV.exists():
        return set()
    return set(pd.read_csv(SUE_CSV, usecols=["panel_date"])["panel_date"].astype(str))


def record_sue(t, rows):
    """Append one date. Duplicate-date guard + blindness re-check + pairing."""
    iso = pd.Timestamp(t).date().isoformat()
    if iso in recorded_dates():
        raise SystemExit(f"REFUSING: {SUE_CSV.name} already has panel_date {iso} (duplicate-date guard)")
    v3_cross(t)                                  # blindness guard (raises)
    check_pairing(rows, t)
    out = rows.copy()
    out["recorded_at"] = pd.Timestamp.now().isoformat()
    out = out[SUE_COLS]
    out.to_csv(SUE_CSV, mode="a", header=not SUE_CSV.exists(), index=False)
    W.record_manifest(SUE_CSV, pd.Timestamp(t), PL.PANEL_PATH)
    log(f"appended {len(out)} rows to {SUE_CSV.name} for {iso}: finite sue "
        f"{np.isfinite(out['sue'].to_numpy(np.float64)).mean():.1%}")
    return out


# ------------------------------------------------------------------ score / status
def _spear(a, b):
    return PL._spearman(np.asarray(a, np.float64), np.asarray(b, np.float64))


def score_frame(df, spy_fwd_40):
    """df: one date; icw9_sue_score, icw8_score, realized, beta_252, sector."""
    r = df["realized"].to_numpy(np.float64)
    s9, s8 = df["icw9_sue_score"].to_numpy(np.float64), df["icw8_score"].to_numpy(np.float64)
    m = np.isfinite(s9) & np.isfinite(s8) & np.isfinite(r)
    out = {"n_names": int(m.sum())}
    r9, r8 = _spear(s9[m], r[m]), _spear(s8[m], r[m])
    out.update({"rho_icw9_sue_raw": r9, "rho_icw8_raw": r8, "gain_raw": r9 - r8})
    if pd.notna(spy_fwd_40):
        ab = r - df["beta_252"].to_numpy(np.float64) * spy_fwd_40
        mb = m & np.isfinite(ab)
        a9, a8 = _spear(s9[mb], ab[mb]), _spear(s8[mb], ab[mb])
    else:
        a9 = a8 = np.nan
    out.update({"rho_icw9_sue_beta_adj": a9, "rho_icw8_beta_adj": a8, "gain_beta_adj": a9 - a8})
    g = df[m].copy()
    g["sector"] = g["sector"].fillna("Unknown")
    dm = lambda c: (g[c] - g.groupby("sector")[c].transform("mean")).to_numpy(np.float64)  # noqa: E731
    s9d, s8d, rd = dm("icw9_sue_score"), dm("icw8_score"), dm("realized")
    q9, q8 = _spear(s9d, rd), _spear(s8d, rd)
    out.update({"rho_icw9_sue_sector_both": q9, "rho_icw8_sector_both": q8, "gain_sector_both": q9 - q8})
    return out


def score_sue():
    if not SUE_CSV.exists():
        log(f"No {SUE_CSV.name} yet -- nothing to score")
        return []
    led = pd.read_csv(SUE_CSV)
    done = set()
    if SUE_SCORES_CSV.exists():
        done = set(pd.read_csv(SUE_SCORES_CSV, usecols=["panel_date"])["panel_date"].astype(str))
    v3 = pd.read_csv(PL.LEDGER_CSV, usecols=["panel_date", "ticker", "beta_252"])
    v3["panel_date"] = v3["panel_date"].astype(str)
    results = []
    spy = None
    for pdate, rows in led.groupby(led["panel_date"].astype(str)):
        if pdate in done:
            continue
        cross, _u = W.working_cross_section(["sector", LABEL], date=pdate, path=PL.PANEL_PATH)
        if cross[LABEL].notna().sum() == 0:
            log(f"sue {pdate}: still blind (no matured {LABEL}) -- nothing scored")
            continue
        if spy is None:
            _b, spy = PL._load_beta_and_market()
        df = (rows.merge(v3[v3["panel_date"] == pdate].drop(columns="panel_date"), on="ticker", how="left")
                  .merge(cross[["ticker", "sector", LABEL]].rename(columns={LABEL: "realized"}),
                         on="ticker", how="left"))
        st = score_frame(df, spy.get(pd.Timestamp(pdate), np.nan))
        st.update({"panel_date": pdate, "scored_at": pd.Timestamp.now().isoformat(),
                   "sue_version": rows["sue_version"].iloc[0],
                   "coverage": float(np.isfinite(rows["sue"].to_numpy(np.float64)).mean())})
        results.append(st)
        log(f"sue {pdate}: gain_raw {st['gain_raw']:+.4f} (n {st['n_names']})")
    if results:
        pd.DataFrame(results).to_csv(SUE_SCORES_CSV, mode="a", header=not SUE_SCORES_CSV.exists(), index=False)
    return results


def trading_calendar():
    """forward_hedge's calendar (IWM_live.csv dates) when it exists, else the
    working panel's; both must agree where they overlap."""
    import forward_hedge as FH
    panel = pd.DatetimeIndex(panel_calendar())
    if not FH.IWM_LIVE_CSV.exists():
        return panel, "working panel dates (IWM_live.csv absent)"
    iwm = pd.DatetimeIndex(FH.load_iwm(FH.IWM_LIVE_CSV)["date"])
    lo, hi = max(iwm.min(), panel.min()), min(iwm.max(), panel.max())
    a, b = iwm[(iwm >= lo) & (iwm <= hi)], panel[(panel >= lo) & (panel <= hi)]
    if not a.equals(b):
        raise SystemExit("status: IWM_live.csv and working-panel calendars disagree on their overlap")
    return iwm, "IWM_live.csv dates (agree with working panel on overlap)"


def excluded_dates():
    """recorded_late (log sidecar) or incomplete_week (annotations) for the sue ledger."""
    late, inc = set(), set()
    if LOG_CSV.exists():
        lg = pd.read_csv(LOG_CSV)
        lg = lg[(lg["ledger"] == SUE_CSV.name) & lg["recorded_late"].astype(str).str.lower().eq("true")]
        late = set(lg["panel_date"].astype(str))
    if ANN_CSV.exists():
        an = pd.read_csv(ANN_CSV)
        an = an[(an["ledger"] == SUE_CSV.name) & an["annotation"].astype(str).str.startswith("incomplete_week")]
        inc = set(an["panel_date"].astype(str))
    return late, inc


def counted_dates(records, late, inc, cal):
    """records: {panel_date: coverage}. Anchor = first record not late, not
    incomplete, coverage >= floor; then greedy >= 40 trading days apart over
    eligible records only."""
    cal = pd.DatetimeIndex(sorted(cal))
    elig = sorted(pd.Timestamp(d) for d, cov in records.items()
                  if d not in late and d not in inc and cov >= COVERAGE_FLOOR)
    out, prev = [], None
    for d in elig:
        if prev is None or int(((cal > prev) & (cal <= d)).sum()) >= H:
            out.append(d)
            prev = d
    return out


def status_sue(quiet=False):
    if not SUE_CSV.exists():
        st = {"state": "NO RECORDS", "n_matured_counted": 0}
        log(f"status: {st}")
        return st
    led = pd.read_csv(SUE_CSV, usecols=["panel_date", "sue"])
    cov = led.groupby(led["panel_date"].astype(str))["sue"].apply(lambda s: float(np.isfinite(s).mean())).to_dict()
    late, inc = excluded_dates()
    cal, cal_src = trading_calendar()
    cd = [d.date().isoformat() for d in counted_dates(cov, late, inc, cal)]
    sc = pd.read_csv(SUE_SCORES_CSV) if SUE_SCORES_CSV.exists() else pd.DataFrame(columns=["panel_date", "gain_raw"])
    sc["panel_date"] = sc["panel_date"].astype(str)
    first6 = cd[:MIN_COUNTED]
    mat = sc[sc["panel_date"].isin(first6)]
    n, mean = len(mat), float(mat["gain_raw"].mean()) if len(mat) else float("nan")
    if len(first6) < MIN_COUNTED or n < MIN_COUNTED:
        state = f"INSUFFICIENT ({n} of {MIN_COUNTED} counted dates matured; blind)"
    elif mean > 0:
        state = "PROMOTE-CANDIDATE question to Gabe"
    else:
        state = "KILL / DEAD"
    st = {"records": {d: {"coverage": round(c, 4), "late": d in late, "incomplete_week": d in inc}
                      for d, c in sorted(cov.items())},
          "counted_dates": cd, "calendar": cal_src, "n_matured_counted": n,
          "mean_gain_raw_first6": mean, "state": state}
    if not quiet:
        log(f"status: {json.dumps(st, default=str)}")
    return st


# ------------------------------------------------------------------ plan / selftest
def todo_dates(v3_new=()):
    """SUE dates to record: v3 panel dates after START_AFTER (existing + about
    to be written this run) with no SUE record yet."""
    have = set()
    if PL.LEDGER_CSV.exists():
        have = set(pd.read_csv(PL.LEDGER_CSV, usecols=["panel_date"])["panel_date"].astype(str))
    ds = {d for d in have if pd.Timestamp(d) > START_AFTER} | {pd.Timestamp(d).date().isoformat() for d in v3_new}
    if BACKFILL_DECISION == "declined":
        ds -= BACKFILL_DATES
    return sorted(pd.Timestamp(d) for d in ds - recorded_dates())


def selftest(test_date="2015-06-15"):
    """Code reproduction ONLY on a nomination-era date: no IC, no return."""
    ok = True

    def check(name, cond, detail=""):
        nonlocal ok
        ok &= bool(cond)
        log(f"  [{'PASS' if cond else 'FAIL'}] {name} {detail}")

    w8 = PL.icw_rule({k: PL.ICW9_T_USED[k] for k in C.FACTOR_COLS}, C.FACTOR_SIGNS)
    check("ICW rule reproduces PRODUCTION_WEIGHTS (4 dp)",
          all(abs(round(w8[k], 4) - ICW.PRODUCTION_WEIGHTS[k]) < 1e-9 for k in w8))
    w9 = PL.icw_rule(ICW9_SUE_T_USED, ICW9_SUE_SIGNS)
    check("ICW9_SUE_WEIGHTS == rule (4 dp)", all(abs(round(w9[k], 4) - ICW9_SUE_WEIGHTS[k]) < 1e-9 for k in w9),
          f"(sue {w9['sue']:.6f})")
    check("sue not in C.FACTOR_COLS", "sue" not in C.FACTOR_COLS)
    rep_t = json.loads((B.OUT / "sue_screen_report.json").read_text())["ic"]["pooled"]["t"]
    check("SUE_T == sue_screen_report ic.pooled.t", rep_t == SUE_T, f"({rep_t!r})")

    t = pd.Timestamp(test_date)
    assert t < pd.Timestamp("2020-01-01")
    ref = pd.read_parquet(B.OUT / "sue_factor_v2.parquet", filters=[("date", "==", t)])
    cal = panel_calendar()
    old = load_basis()
    old = old[old["dimension"] == "ARQ"].copy()
    old["date"] = pd.to_datetime(old["date"])
    rows = old[old["date"] <= prev_td(t, cal)]           # the live path's datekey filter (no lastupdated col)
    got = sue_asof(rows, ref["ticker"], t, cal)
    a, b = got["sue"].to_numpy(np.float64), ref["sue"].to_numpy(np.float64)
    same_nan = np.isnan(a) == np.isnan(b)
    mad = float(np.nanmax(np.abs(a - b))) if np.isfinite(a).any() else 0.0
    check(f"live path on {t.date()} (09-08 SF1, datekey filter) == sue_factor_v2 sue",
          same_nan.all() and mad == 0.0, f"({len(ref)} rows, NaN mismatches {(~same_nan).sum()}, max|d| {mad:.3g})")
    check("  filing date / reportperiod / age identical",
          got["sue_filing_date"].equals(ref["sue_filing_date"]) and got["sue_reportperiod"].equals(ref["sue_reportperiod"])
          and np.array_equal(got["sue_age_days"].to_numpy(np.float64), ref["sue_age_days"].to_numpy(np.float64), equal_nan=True))

    if LIVE.exists():
        live, pa = load_live()
        aapl = live[live["ticker"] == "AAPL"].sort_values("date").tail(6)
        log(f"  AAPL live ARQ (pulled {pa}):\n{aapl[['date', 'reportperiod', 'eps', 'lastupdated']].to_string(index=False)}")
        gaps = aapl["date"].diff().dt.days.dropna()
        lags = (aapl["date"] - aapl["reportperiod"]).dt.days
        check("AAPL live: quarterly filing cadence (gaps 70-110d, lag 20-45d)",
              gaps.between(70, 110).all() and lags.between(20, 45).all(),
              f"(gaps {gaps.astype(int).tolist()}, lags {lags.astype(int).tolist()})")
    log(f"=== sue_forward selftest {'PASSED' if ok else 'FAILED'} ===")
    return ok


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    if cmd == "selftest":
        sys.exit(0 if selftest(*sys.argv[2:3]) else 1)
    elif cmd == "score":
        score_sue()
        status_sue()
    elif cmd == "status":
        status_sue()
    elif cmd == "measure":
        # read-only: the sec. 2 fallback / sec. 7 gate metrics for W38/W39 (no writes)
        cal = panel_calendar()
        live, pa = load_live()
        try:
            print(json.dumps({k: v for k, v in basis_validation(live).items() if k != "mismatch_ratio_by_ticker"}, default=str))
        except SystemExit as e:
            print(f"basis validation: {e}")
        for d in sorted(BACKFILL_DATES):
            ok, why = fresh_for(live, pa, d, cal)
            rows, info = build_sue_rows(d, live, pa, cal)
            try:
                info["pairing_icw8_max_abs_diff"] = check_pairing(rows, d)
            except SystemExit as e:
                info["pairing_FAILED"] = str(e)
            info["fresh"] = [ok, why]
            print(json.dumps(info, default=str))
    elif cmd == "plan":
        print([d.date().isoformat() for d in todo_dates()])
    else:
        raise SystemExit(f"unknown command {cmd}")
