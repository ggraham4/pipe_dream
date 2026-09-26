"""
A genuinely forward, un-spent test of the composite's predictions -- per
Gabe's request for a theoretical model whose predictions "can be tested"
without spending the 2020-2026 hold-out again. Every date in that window has
already been analyzed multiple times today; the only clean test left is real
calendar time that has not happened yet.

Two commands:

  record  -- Uses the MOST RECENT available cross-section in
             the WORKING panel, working_panel.WORKING_PANEL (v2 since WO-11;
             the 2026-09-08 records were made on composite_panel.parquet -- verified
             `forward_return_tradable_40` is 100% NaN for every eligible name
             on this date and every date after late July 2026: the 40-trading
             -day-forward outcome genuinely does not exist yet). Computes,
             for EVERY eligible cap150 name (not one ticker -- a single
             prediction has no statistical power; ~1,000+ names does),
             (a) the composite RANK/percentile -- the primary, robust
             prediction, per Gabe's own instinct that ranking beats a noisy
             point estimate -- and (b) a calibrated RELATIVE return forecast,
             `slope * (S_i - mean(S))`, using the Fama-MacBeth slope
             estimated on nomination-era data only (2007-2019, causal, never
             touches 2020-2026). Deliberately de-meaned: the model has no
             view on the market's absolute return (that's an unconditional
             average with no signal in it -- the physics audit's own finding
             that IC is a within-date, market-neutral quantity), so the
             point forecast is scoped to what the model actually claims to
             know: relative performance within the cross-section. Appends
             one immutable row per ticker to `prediction_ledger.csv`, with
             both the panel date and the real wall-clock time this was
             written, before any outcome exists to peek at.

  score   -- Re-reads the working panel for any ledger dates whose
             40-day-forward outcome has since matured (non-NaN), fills in
             realized returns, and computes the actual test: cross-sectional
             Spearman IC (rank prediction) and a Fama-MacBeth-style
             regression of realized excess return on predicted excess return
             (magnitude prediction) -- FOR THAT DATE ONLY, appended to
             `prediction_ledger_scores.csv` as one more row in a growing,
             genuinely out-of-sample track record. Run again every so often
             as new data is pulled and time passes.

Usage:
    python3 prediction_ledger.py record
    python3 prediction_ledger.py score
    python3 prediction_ledger.py selftest   # validates the SCORING logic
                                             # only, on an already-known
                                             # nomination-era date -- draws
                                             # no new conclusion about the
                                             # model, exists purely to check
                                             # the ledger/scoring code is
                                             # correct before trusting it on
                                             # real future data, the same
                                             # discipline used to validate
                                             # price_adjustment_scanner.py
                                             # against AAPL before trusting
                                             # it on LCID.
"""
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import composite as C  # noqa: E402
import ic_weighted_composite as ICW  # noqa: E402
import build_new_factors as NF  # noqa: E402
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "insider"))
import opportunistic as OPP  # noqa: E402
sys.path.insert(0, str(Path(__file__).resolve().parent))
import working_panel as W  # noqa: E402

MAIN_ROOT = Path("/Users/ggraham/pipe_dream/final")
# WO-11 (2026-09-25, Gabe: "all models should use it"): records from the
# next record date on read the WORKING panel (composite_panel_v2) with the
# v2 universe rule applied before scoring (working_panel.py). The records
# already made (panel_date 2026-09-08, all on composite_panel.parquet) are
# never rewritten; ledger_panel_manifest.json maps every (ledger, panel_date)
# to the panel it was recorded on. beta_feature / outcome_cache follow the
# panel (their v2 files equal v1 on every common (ticker, date) checked,
# pre-2020; outcome_cache SPY differs only at v1's series-end truncation,
# dates >= 2026-07-13). `selftest` stays on V1_PANEL: it reproduces
# new_factors.parquet and insider_features.parquet, which are v1-grid files.
PANEL_PATH = W.WORKING_PANEL
V1_PANEL_PATH = W.V1_PANEL
BETA_PATH = W.WORKING_BETA
OUTCOME_PATH = W.WORKING_OUTCOME
OUT_DIR = MAIN_ROOT / "out" / "reset2026"
# v1 (`prediction_ledger.csv`) and v2 (`prediction_ledger_v2.csv`, both
# panel_date=2026-09-08) are FROZEN -- immutable commitments already made
# under their own scoring specs, never rewritten. v3 adds the IC-weighted
# model's score/rank alongside the existing equal-weight ones (schema
# change again, same reason as v1->v2), but going forward this schema is
# meant to be EXTENSIBLE -- add a new model's columns here rather than
# versioning the whole ledger again for every future variant, unless a
# change also alters the meaning of an existing column.
LEDGER_CSV = OUT_DIR / "prediction_ledger_v3.csv"
SCORES_CSV = OUT_DIR / "prediction_ledger_v3_scores.csv"

NOMINATE_START = pd.Timestamp("2007-01-02")
NOMINATE_END = pd.Timestamp("2019-12-31")
LABEL = "forward_return_tradable_40"
# "asset_growth_dropped" -> "beta_adjusted" 2026-09-22: theoretical model
# addition #1 (Gabe's direction). See beta_diagnostic.py -- the composite
# correlates -0.293 (t=-17.1) with mechanically-estimated beta_252, and
# scoring against beta-adjusted (market-model abnormal) returns instead of
# raw returns SHARPENS the measured IC (+0.032 t=2.53 -> +0.045 t=4.25):
# removing each stock's beta-driven component removes noise the raw-return
# IC was carrying, not signal. The point forecast below is now calibrated
# on abnormal returns for this reason -- not a fitted improvement, a
# mechanical decomposition (Sharpe 1964 / Fama-Fisher-Jensen-Roll 1969's
# market-model methodology, no different parameterization chosen for fit).
MODEL_VERSION = "beta_adjusted_2026-09-22"
# FROZEN (WO-11, 2026-09-25): the nomination-era Fama-MacBeth slope that the
# v3 record on 2026-09-08 used (its fm_slope_used column). record() no longer
# re-fits it: a re-fit on the v2 panel would re-derive a calibration constant
# on a different cross-section, which the frozen-weights rule forbids.
# fama_macbeth_slope_nomination() is kept for reference only.
FM_SLOPE_FROZEN = 0.016276464738787338

# ---------------------------------------------------------------------------
# Side ledger (WO-2 + WO-3, 2026-09-23). Pre-registration:
# models/2026-09-23-forward-ledger-leverage-opportunistic-buyers.md. A
# SEPARATE CSV so the v3 append-mode schema is never touched.
EXT_CSV = OUT_DIR / "prediction_ledger_ext.csv"
EXT_SCORES_CSV = OUT_DIR / "prediction_ledger_ext_scores.csv"
EXT_VERSION = "ext1_icw9lev_oppbuy_2026-09-23"
EXT_COLS = ["panel_date", "recorded_at", "ext_version", "ticker", "icw9_leverage_score",
            "icw9_leverage_rank_pct", "leverage", "opp_buyers_90", "ins_buyers_90",
            "unclass_buyers_90", "insider_data_max_filing_date"]
INSIDER_MAX_STALE_DAYS = 7
MIN_OPP_FIRING = 10  # registered minimum firing count for a WO-3 date to count

# FROZEN (2026-09-23, before any ext record). The ICW8 rule
# w_k = s_k*max(0.1,|t_k|-1)/sum, with leverage (sign -1) added. The t values
# are the full nomination-era pooled NW t's already on disk:
# ic_weighted_composite_report.json per_factor_t.full (8 production factors),
# new_factor_screens_report.json leverage.pooled (leverage). No new screen.
ICW9_T_USED = {
    "momentum_12_1": 1.3823405236334954,
    "pct_from_high_252": 0.836261428518942,
    "volatility_60": -0.2095936566027876,
    "gross_profitability": 5.5775328355615095,
    "accruals": -2.2508107695974884,
    "net_issuance_pct": -2.0749393150150004,
    "days_to_next_filing_seasonal": -0.7703417716508143,
    "short_interest_days_to_cover": float("nan"),   # no pre-2020 data -> floor
    "leverage": -2.4441941591730885,
}
ICW9_SIGNS = {**C.FACTOR_SIGNS, "leverage": -1}   # leverage NOT added to C.FACTOR_SIGNS
ICW9_WEIGHTS = {
    "momentum_12_1": 0.0419,
    "pct_from_high_252": 0.0110,
    "volatility_60": -0.0110,
    "gross_profitability": 0.5014,
    "accruals": -0.1370,
    "net_issuance_pct": -0.1177,
    "days_to_next_filing_seasonal": -0.0110,
    "short_interest_days_to_cover": -0.0110,
    "leverage": -0.1582,
}


def icw_rule(t_used, signs, floor=0.1):
    """The frozen ICW rule, for the selftest's reproduction check only."""
    raw = {k: signs[k] * (max(floor, abs(t) - 1.0) if np.isfinite(t) else floor) for k, t in t_used.items()}
    tot = sum(abs(v) for v in raw.values())
    return {k: v / tot for k, v in raw.items()}


def compute_leverage(tickers, date):
    """debtnc/assets from the latest SF1 filing as of `date` -- exactly
    build_new_factors.py's definition, recomputed here so a panel refresh
    does not depend on a stale new_factors.parquet."""
    facts = NF.load_sf1_facts()
    frame = pd.DataFrame({"ticker": pd.Series(list(tickers), dtype=str), "date": pd.Timestamp(date)})
    assets = NF._asof_value(frame, facts["assets"], "date")
    debtnc = NF._asof_value(frame, facts["debtnc"], "date")
    with np.errstate(divide="ignore", invalid="ignore"):
        lev = np.where((assets > 0) & np.isfinite(debtnc), debtnc / assets, np.nan)
    lev[~np.isfinite(lev)] = np.nan
    return lev


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def load_panel(columns, path=None):
    df = pd.read_parquet(PANEL_PATH if path is None else path, columns=columns)
    df["date"] = pd.to_datetime(df["date"])
    df["ticker"] = df["ticker"].astype(str)
    return df


def _load_beta_and_market():
    beta = pd.read_parquet(BETA_PATH, columns=["ticker", "date", "beta_252"])
    beta["date"] = pd.to_datetime(beta["date"])
    beta["ticker"] = beta["ticker"].astype(str)
    outcomes = pd.read_parquet(OUTCOME_PATH, columns=["ticker", "date", "gross_return_40"])
    outcomes["date"] = pd.to_datetime(outcomes["date"])
    spy = outcomes[outcomes["ticker"] == "SPY"].set_index("date")["gross_return_40"]
    return beta, spy


def fama_macbeth_slope_nomination():
    """Causal calibration: the average cross-sectional slope of BETA-
    ADJUSTED (market-model abnormal) return on composite score, nomination
    era only. Never touches 2020+. See MODEL_VERSION's comment above for
    why abnormal return, not raw return, is the calibration target."""
    need = list(dict.fromkeys(["ticker", "date", "sector", "volatility_60",
                                "eligible_cap150", LABEL] + C.FACTOR_COLS))
    df = load_panel(need)
    beta, spy = _load_beta_and_market()
    df = df.merge(beta, on=["ticker", "date"], how="left")
    df["spy_fwd_40"] = df["date"].map(spy)
    df["abnormal_return"] = df[LABEL] - df["beta_252"] * df["spy_fwd_40"]

    nom = df[(df["date"] >= NOMINATE_START) & (df["date"] <= NOMINATE_END) & df["eligible_cap150"]]
    slopes = []
    for d, g in nom.groupby("date"):
        gg = g.reset_index(drop=True)
        scored = C.compute_composite(gg, neutral=False)
        x = scored["composite"].to_numpy(np.float64)
        y = g["abnormal_return"].to_numpy(np.float64)
        mask = np.isfinite(x) & np.isfinite(y)
        if mask.sum() < 30:
            continue
        X = np.column_stack([np.ones(mask.sum()), x[mask]])
        beta_coef, *_ = np.linalg.lstsq(X, y[mask], rcond=None)
        slopes.append(beta_coef[1])
    slope = float(np.mean(slopes))
    log(f"Fama-MacBeth slope on BETA-ADJUSTED returns (nomination era): {slope:.5f} (n={len(slopes)} dates)")
    return slope


def record(date=None):
    """date=None: the working panel's latest date (unchanged behaviour).
    date=YYYY-MM-DD: that panel date (WO-14 weekly catch-up, record_weekly.py);
    the blindness guard below applies to it exactly the same way."""
    need = list(dict.fromkeys(["ticker", "date", "sector", "volatility_60",
                                "eligible_cap150", LABEL] + C.FACTOR_COLS))
    # latest (or the requested) date of the working panel, universe rule applied BEFORE scoring
    df, uinfo = W.working_cross_section(need, date=date, path=PANEL_PATH)
    latest_date = df.loc[df["eligible_cap150"], "date"].max()
    cross = df[(df["date"] == latest_date) & df["eligible_cap150"]].reset_index(drop=True)
    log(f"working panel {PANEL_PATH.name}: {uinfo}")
    n_matured = cross[LABEL].notna().sum()
    log(f"most recent eligible cross-section: {latest_date.date()}, {len(cross)} names, "
        f"{n_matured} already have a realized 40-day outcome (should be 0 for a genuinely blind record)")
    if n_matured > 0:
        raise SystemExit(f"REFUSING: {n_matured} names on {latest_date.date()} already have a realized "
                          f"outcome -- this date is not blind. Pick a more recent panel refresh.")

    beta, _spy = _load_beta_and_market()
    cross = cross.merge(beta[beta["date"] == latest_date][["ticker", "beta_252"]], on="ticker", how="left")
    log(f"beta_252 coverage on this cross-section: {cross['beta_252'].notna().mean():.1%}")

    slope = FM_SLOPE_FROZEN
    scored = C.compute_composite(cross, neutral=False)
    s = scored["composite"].to_numpy(np.float64)
    valid = np.isfinite(s)
    rank_pct = pd.Series(s).rank(pct=True, na_option="keep").to_numpy()
    s_mean = np.nanmean(s)
    # The idiosyncratic (beta-adjusted) prediction -- what the composite
    # claims about a name's return NET of its mechanical market exposure.
    predicted_idiosyncratic_return = slope * (s - s_mean)

    # IC-shrinkage-weighted model (2026-09-22, corrections doc section 12)
    # -- a second, independent prediction on the SAME cross-section, using
    # the frozen production weights. Recorded alongside, not instead of,
    # the equal-weight model, so the live ledger can compare them going
    # forward on genuinely new data (the one test neither has had yet).
    scored_icw = ICW.compute_composite_ic_weighted(cross)
    s_icw = scored_icw["composite"].to_numpy(np.float64)
    rank_pct_icw = pd.Series(s_icw).rank(pct=True, na_option="keep").to_numpy()

    out = pd.DataFrame({
        "panel_date": latest_date.date().isoformat(),
        "recorded_at": pd.Timestamp.now().isoformat(),
        "model_version": MODEL_VERSION,
        "ticker": cross["ticker"],
        "composite_score": s,
        "rank_pct": rank_pct,
        "beta_252": cross["beta_252"].to_numpy(),
        "predicted_idiosyncratic_return_40d": predicted_idiosyncratic_return,
        "fm_slope_used": slope,
        "ic_weighted_score": s_icw,
        "ic_weighted_rank_pct": rank_pct_icw,
        "realized_return_40d": np.nan,      # raw, filled in later by `score`
        "realized_abnormal_return_40d": np.nan,  # beta-adjusted, also filled in later
        "scored_at": "",
    })
    out = out[valid].reset_index(drop=True)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    n_v3_before = _v3_rows_for(latest_date)
    if n_v3_before > 0:
        # Guard (2026-09-23): re-running `record` on an unrefreshed panel used
        # to append a duplicate copy of the whole cross-section.
        log(f"v3 ledger already has {n_v3_before} rows for {latest_date.date()} -- NOT re-appending")
    else:
        write_header = not LEDGER_CSV.exists()
        out.to_csv(LEDGER_CSV, mode="a", header=write_header, index=False)
        log(f"appended {len(out)} rows to {LEDGER_CSV} for panel_date={latest_date.date()} "
            f"(blind -- outcome does not exist yet)")
        W.record_manifest(LEDGER_CSV, latest_date, PANEL_PATH)
    n_v3_after = _v3_rows_for(latest_date)

    record_ext(cross, latest_date, valid)
    if n_v3_before > 0 and n_v3_after != n_v3_before:
        raise SystemExit(f"v3 row count for {latest_date.date()} changed {n_v3_before} -> {n_v3_after}")


def _v3_rows_for(panel_date):
    if not LEDGER_CSV.exists():
        return 0
    pdates = pd.read_csv(LEDGER_CSV, usecols=["panel_date"])["panel_date"].astype(str)
    return int((pdates == pd.Timestamp(panel_date).date().isoformat()).sum())


def insider_columns(tickers, panel_date):
    """(frame of opp/ins/unclass counts, max filing date, stale flag)."""
    ev = OPP.load_events()
    maxf = OPP.max_filing_date(ev)
    stale = (pd.Timestamp(panel_date) - maxf).days > INSIDER_MAX_STALE_DAYS
    counts, _w = OPP.cross_section_counts(ev, tickers, panel_date)
    if stale:
        log(f"INSIDER DATA STALE: newest filing {maxf.date()} is > {INSIDER_MAX_STALE_DAYS} days before "
            f"{pd.Timestamp(panel_date).date()} -- insider columns written as NaN. "
            f"Run final/scripts/edgar_form4_refresh.py first.")
        for c in ("opp_buyers_90", "ins_buyers_90", "unclass_buyers_90"):
            counts[c] = np.nan
    return counts, maxf, stale


def build_ext_rows(cross, panel_date, valid):
    cross = cross.copy()
    cross["leverage"] = compute_leverage(cross["ticker"], panel_date)
    s9 = ICW.compute_composite_ic_weighted(cross, weights=ICW9_WEIGHTS)["composite"].to_numpy(np.float64)
    counts, maxf, stale = insider_columns(cross["ticker"], panel_date)
    assert (counts["ticker"].to_numpy() == cross["ticker"].to_numpy()).all(), "insider rows misaligned"
    ext = pd.DataFrame({
        "panel_date": pd.Timestamp(panel_date).date().isoformat(),
        "recorded_at": pd.Timestamp.now().isoformat(),
        "ext_version": EXT_VERSION,
        "ticker": cross["ticker"].to_numpy(),
        "icw9_leverage_score": s9,
        "icw9_leverage_rank_pct": pd.Series(s9).rank(pct=True, na_option="keep").to_numpy(),
        "leverage": cross["leverage"].to_numpy(),
        "opp_buyers_90": counts["opp_buyers_90"].to_numpy(),
        "ins_buyers_90": counts["ins_buyers_90"].to_numpy(),
        "unclass_buyers_90": counts["unclass_buyers_90"].to_numpy(),
        "insider_data_max_filing_date": maxf.date().isoformat(),
    })[EXT_COLS]
    # same row set as the v3 ledger (finite equal-weight composite)
    return ext[np.asarray(valid)].reset_index(drop=True), stale


def record_ext(cross, panel_date, valid):
    pd_iso = pd.Timestamp(panel_date).date().isoformat()
    if EXT_CSV.exists() and (pd.read_csv(EXT_CSV, usecols=["panel_date"])["panel_date"].astype(str) == pd_iso).any():
        log(f"ext ledger already has {pd_iso} -- NOT re-appending")
        return
    ext, stale = build_ext_rows(cross, panel_date, valid)
    write_header = not EXT_CSV.exists()
    ext.to_csv(EXT_CSV, mode="a", header=write_header, index=False)
    W.record_manifest(EXT_CSV, panel_date, PANEL_PATH)
    fire = (ext["opp_buyers_90"] >= 1).mean() if not stale else float("nan")
    log(f"appended {len(ext)} rows to {EXT_CSV} for {pd_iso}: leverage coverage "
        f"{ext['leverage'].notna().mean():.1%}, icw9 finite {ext['icw9_leverage_score'].notna().mean():.1%}, "
        f"insider max filing {ext['insider_data_max_filing_date'].iloc[0]} "
        f"({'STALE, insider NaN' if stale else f'opp fire rate {fire:.2%}'})")




def _score_frame(cross_ids, ledger_rows, label_lookup, spy_fwd_40=None):
    """Shared scoring logic between `score` and `selftest`. Reports BOTH
    the raw-return test (what you would have actually made) and the
    beta-adjusted test (isolates genuine stock-selection skill from
    market-direction luck) -- see beta_diagnostic.py for why both matter:
    the raw number is the real-world one, the abnormal number is the
    cleaner read on whether the composite itself is working."""
    merged = ledger_rows.copy()
    merged["realized_return_40d"] = merged["ticker"].map(label_lookup)
    merged = merged.dropna(subset=["realized_return_40d"])
    if len(merged) < 20:
        return None

    def _calib(excess_pred, excess_real):
        X = np.column_stack([np.ones(len(excess_real)), excess_pred])
        b, *_ = np.linalg.lstsq(X, excess_real, rcond=None)
        yhat = X @ b
        ss_res = np.sum((excess_real - yhat) ** 2)
        ss_tot = np.sum((excess_real - excess_real.mean()) ** 2)
        r2 = 1 - ss_res / ss_tot if ss_tot > 0 else np.nan
        return float(b[1]), float(b[0]), float(r2)

    rank_ic_raw = merged["composite_score"].corr(merged["realized_return_40d"], method="spearman")
    excess_real_raw = merged["realized_return_40d"].to_numpy() - merged["realized_return_40d"].mean()
    slope_raw, intercept_raw, r2_raw = _calib(merged["predicted_idiosyncratic_return_40d"].to_numpy(),
                                               excess_real_raw)

    result = {
        "n_names": int(len(merged)),
        "rank_ic_raw": float(rank_ic_raw),
        "magnitude_calibration_slope_raw": slope_raw,
        "magnitude_r2_raw": r2_raw,
    }

    # Second model (2026-09-22 addition): the IC-shrinkage-weighted score,
    # same cross-section, same date -- directly comparable rank IC, the
    # actual test of the out-of-sample claim in corrections doc section 12.
    if "ic_weighted_score" in merged.columns:
        icw_valid = merged.dropna(subset=["ic_weighted_score"])
        if len(icw_valid) >= 20:
            result["rank_ic_raw_ic_weighted"] = float(
                icw_valid["ic_weighted_score"].corr(icw_valid["realized_return_40d"], method="spearman"))

    if spy_fwd_40 is not None and pd.notna(spy_fwd_40) and "beta_252" in merged.columns:
        merged["abnormal_return"] = merged["realized_return_40d"] - merged["beta_252"] * spy_fwd_40
        ab = merged.dropna(subset=["abnormal_return"])  # beta_252 coverage is ~98%, not 100%
        if len(ab) >= 20:
            rank_ic_ab = ab["composite_score"].corr(ab["abnormal_return"], method="spearman")
            excess_real_ab = ab["abnormal_return"].to_numpy() - ab["abnormal_return"].mean()
            slope_ab, intercept_ab, r2_ab = _calib(ab["predicted_idiosyncratic_return_40d"].to_numpy(),
                                                    excess_real_ab)
            result.update({
                "rank_ic_beta_adjusted": float(rank_ic_ab),
                "magnitude_calibration_slope_beta_adjusted": slope_ab,
                "magnitude_r2_beta_adjusted": r2_ab,
            })

    top_decile = merged.nlargest(max(1, len(merged) // 10), "composite_score")["realized_return_40d"].mean()
    bottom_decile = merged.nsmallest(max(1, len(merged) // 10), "composite_score")["realized_return_40d"].mean()
    result.update({
        "top_decile_mean_return": float(top_decile),
        "bottom_decile_mean_return": float(bottom_decile),
        "top_minus_bottom_decile_spread": float(top_decile - bottom_decile),
    })
    return result


def _score_v3():
    if not LEDGER_CSV.exists():
        raise SystemExit(f"No {LEDGER_CSV.name} yet -- run `record` first.")
    ledger = pd.read_csv(LEDGER_CSV, parse_dates=["panel_date"])
    pending = ledger[ledger["realized_return_40d"].isna()]
    if pending.empty:
        log("no pending (unscored) ledger rows")
        return

    panel = load_panel(["ticker", "date", LABEL])
    _beta, spy = _load_beta_and_market()
    results = []
    for panel_date, rows in pending.groupby("panel_date"):
        outcomes = panel[panel["date"] == pd.Timestamp(panel_date)]
        if outcomes[LABEL].notna().sum() == 0:
            log(f"{panel_date.date()}: still blind, {len(rows)} rows not yet scoreable")
            continue
        label_lookup = dict(zip(outcomes["ticker"], outcomes[LABEL]))
        spy_fwd_40 = spy.get(pd.Timestamp(panel_date), np.nan)
        stats = _score_frame(None, rows, label_lookup, spy_fwd_40=spy_fwd_40)
        if stats is None:
            log(f"{panel_date.date()}: too few matured names to score yet")
            continue
        stats["panel_date"] = panel_date.date().isoformat()
        stats["scored_at"] = pd.Timestamp.now().isoformat()
        stats["model_version"] = rows["model_version"].iloc[0]
        results.append(stats)
        log(f"{panel_date.date()}: n={stats['n_names']} "
            f"rank_IC equal-weight={stats['rank_ic_raw']:+.4f} "
            f"IC-weighted={stats.get('rank_ic_raw_ic_weighted', float('nan')):+.4f}  "
            f"beta-adj={stats.get('rank_ic_beta_adjusted', float('nan')):+.4f}  "
            f"mag_R2 raw={stats['magnitude_r2_raw']:.4f} beta-adj={stats.get('magnitude_r2_beta_adjusted', float('nan')):.4f}  "
            f"top-bottom decile spread={stats['top_minus_bottom_decile_spread']*100:+.2f}%")

        idx = ledger[ledger["panel_date"] == panel_date].index
        for i in idx:
            t = ledger.at[i, "ticker"]
            if t in label_lookup:
                ledger.at[i, "realized_return_40d"] = label_lookup[t]
                if pd.notna(spy_fwd_40) and "beta_252" in ledger.columns and pd.notna(ledger.at[i, "beta_252"]):
                    ledger.at[i, "realized_abnormal_return_40d"] = (
                        label_lookup[t] - ledger.at[i, "beta_252"] * spy_fwd_40)
                ledger.at[i, "scored_at"] = pd.Timestamp.now().isoformat()

    if results:
        ledger.to_csv(LEDGER_CSV, index=False)
        write_header = not SCORES_CSV.exists()
        pd.DataFrame(results).to_csv(SCORES_CSV, mode="a", header=write_header, index=False)
        log(f"wrote {len(results)} new scored date(s) to {SCORES_CSV}")


def score():
    """v3 scoring (unchanged) and then, independently, the side ledger."""
    if LEDGER_CSV.exists():
        _score_v3()
    else:
        log(f"No {LEDGER_CSV.name} yet")
    score_ext()


def _spearman(a, b):
    m = np.isfinite(a) & np.isfinite(b)
    if m.sum() < 20:
        return np.nan
    return float(pd.Series(a[m]).corr(pd.Series(b[m]), method="spearman"))


def ext_score_frame(df, spy_fwd_40):
    """df: one panel date; columns icw9_leverage_score, ic_weighted_score,
    realized (40d tradable return), beta_252, sector, opp_buyers_90,
    ins_buyers_90. Returns the registered per-date statistics (doc sec. 3)."""
    r = df["realized"].to_numpy(np.float64)
    s9 = df["icw9_leverage_score"].to_numpy(np.float64)
    s8 = df["ic_weighted_score"].to_numpy(np.float64)
    both = np.isfinite(s9) & np.isfinite(s8)
    out = {"n_names": int((both & np.isfinite(r)).sum())}
    ab = r - df["beta_252"].to_numpy(np.float64) * spy_fwd_40 if pd.notna(spy_fwd_40) else np.full_like(r, np.nan)
    for tag, y in (("raw", r), ("beta_adj", ab)):
        yy = np.where(both, y, np.nan)
        r9, r8 = _spearman(s9, yy), _spearman(s8, yy)
        out[f"rho_icw9_{tag}"], out[f"rho_icw8_{tag}"], out[f"diff_{tag}"] = r9, r8, r9 - r8

    g = df[np.isfinite(r)].copy()
    g["sector"] = g["sector"].fillna("Unknown")
    g["ys"] = g["realized"] - g.groupby("sector")["realized"].transform("mean")
    for tag, col in (("opp", "opp_buyers_90"), ("ins", "ins_buyers_90")):
        h = g[g[col].notna()]
        if h.empty:
            out.update({f"{tag}_n_fire": np.nan, f"{tag}_fire_rate": np.nan,
                        f"{tag}_spread": np.nan, f"{tag}_rho": np.nan})
            continue
        xs = h[col] - h.groupby("sector")[col].transform("mean")
        fire = h[col] >= 1
        out[f"{tag}_n_fire"] = int(fire.sum())
        out[f"{tag}_fire_rate"] = float(fire.mean())
        out[f"{tag}_spread"] = float(h.loc[fire, "ys"].mean() - h.loc[~fire, "ys"].mean()) if 0 < fire.sum() < len(h) else np.nan
        out[f"{tag}_rho"] = _spearman(xs.to_numpy(np.float64), h["ys"].to_numpy(np.float64))
    out["opp_counts_for_wo3"] = bool(np.isfinite(out.get("opp_n_fire", np.nan))
                                     and out["opp_n_fire"] >= MIN_OPP_FIRING)
    return out


def score_ext():
    if not EXT_CSV.exists():
        log(f"No {EXT_CSV.name} yet -- nothing to score on the side ledger")
        return
    ext = pd.read_csv(EXT_CSV)
    done = set()
    if EXT_SCORES_CSV.exists():
        done = set(pd.read_csv(EXT_SCORES_CSV, usecols=["panel_date"])["panel_date"].astype(str))
    v3 = pd.read_csv(LEDGER_CSV, usecols=["panel_date", "ticker", "ic_weighted_score", "beta_252"])
    v3["panel_date"] = v3["panel_date"].astype(str)
    panel = load_panel(["ticker", "date", "sector", LABEL])
    _beta, spy = _load_beta_and_market()
    results = []
    for pdate, rows in ext.groupby(ext["panel_date"].astype(str)):
        if pdate in done:
            continue
        outcomes = panel[panel["date"] == pd.Timestamp(pdate)]
        if outcomes[LABEL].notna().sum() == 0:
            log(f"ext {pdate}: still blind")
            continue
        df = (rows.merge(v3[v3["panel_date"] == pdate].drop(columns="panel_date"), on="ticker", how="left")
                  .merge(outcomes[["ticker", "sector", LABEL]].rename(columns={LABEL: "realized"}),
                         on="ticker", how="left"))
        stats = ext_score_frame(df, spy.get(pd.Timestamp(pdate), np.nan))
        stats.update({"panel_date": pdate, "scored_at": pd.Timestamp.now().isoformat(),
                      "ext_version": rows["ext_version"].iloc[0],
                      "insider_data_max_filing_date": rows["insider_data_max_filing_date"].iloc[0]})
        results.append(stats)
        log(f"ext {pdate}: diff_raw={stats['diff_raw']:+.4f} diff_beta_adj={stats['diff_beta_adj']:+.4f} "
            f"opp_spread={stats['opp_spread']:+.4f} ins_spread={stats['ins_spread']:+.4f}")
    if results:
        write_header = not EXT_SCORES_CSV.exists()
        pd.DataFrame(results).to_csv(EXT_SCORES_CSV, mode="a", header=write_header, index=False)
        log(f"wrote {len(results)} ext scored date(s) to {EXT_SCORES_CSV}")


def selftest():
    """Validates the scoring logic only, on an ALREADY-KNOWN nomination-era
    date (2015-06-15, arbitrary, mid-era). Draws no conclusion about the
    model -- this only checks the ledger/scoring arithmetic is correct
    before trusting it on real future data."""
    need = list(dict.fromkeys(["ticker", "date", "sector", "volatility_60",
                                "eligible_cap150", LABEL] + C.FACTOR_COLS))
    df = load_panel(need, path=V1_PANEL_PATH)   # v1-grid reference files below
    test_date = pd.Timestamp(sys.argv[2]) if len(sys.argv) > 2 else pd.Timestamp("2015-06-15")
    cross = df[(df["date"] == test_date) & df["eligible_cap150"]].reset_index(drop=True)
    if cross.empty:
        raise SystemExit(f"No eligible cross-section on {test_date.date()} -- pick another self-test date.")
    beta, spy = _load_beta_and_market()
    cross = cross.merge(beta[beta["date"] == test_date][["ticker", "beta_252"]], on="ticker", how="left")
    slope = FM_SLOPE_FROZEN
    scored = C.compute_composite(cross, neutral=False)
    s = scored["composite"].to_numpy(np.float64)
    valid = np.isfinite(s)
    s_mean = np.nanmean(s)
    scored_icw = ICW.compute_composite_ic_weighted(cross)
    s_icw = scored_icw["composite"].to_numpy(np.float64)
    rows = pd.DataFrame({
        "ticker": cross["ticker"][valid].to_numpy(),
        "composite_score": s[valid],
        "beta_252": cross["beta_252"].to_numpy()[valid],
        "predicted_idiosyncratic_return_40d": (slope * (s - s_mean))[valid],
        "ic_weighted_score": s_icw[valid],
    })
    label_lookup = dict(zip(cross["ticker"], cross[LABEL]))
    spy_fwd_40 = spy.get(test_date, np.nan)
    stats = _score_frame(None, rows, label_lookup, spy_fwd_40=spy_fwd_40)
    log(f"SELF-TEST on {test_date.date()} (already-known nomination-era data, "
        f"validates scoring code only): {stats}")
    if test_date >= pd.Timestamp("2020-01-01"):
        raise SystemExit("selftest ext checks refuse hold-out dates (2020+)")
    selftest_ext(cross, test_date, valid, stats, label_lookup, spy_fwd_40)


def _raw_zip_od_buys(issuer_cik, through):
    """Independent path for the hand count: straight from the SEC zips'
    TSVs, no insider_events.parquet, no opportunistic.py."""
    import glob
    import zipfile
    rows = []
    for path in sorted(glob.glob(str(OPP.MAIN_ROOT / "data" / "edgar" / "form345" / "*_form345.zip"))):
        if int(Path(path).name[:4]) > through.year:
            continue
        with zipfile.ZipFile(path) as zf:
            rd = lambda n, c: pd.read_csv(zf.open(n), sep="\t", usecols=c, dtype=str, quoting=3, on_bad_lines="skip")
            sub = rd("SUBMISSION.tsv", ["ACCESSION_NUMBER", "FILING_DATE", "DOCUMENT_TYPE", "ISSUERCIK"])
            sub = sub[(sub["DOCUMENT_TYPE"] == "4") & (pd.to_numeric(sub["ISSUERCIK"], errors="coerce") == issuer_cik)]
            if sub.empty:
                continue
            own = rd("REPORTINGOWNER.tsv", ["ACCESSION_NUMBER", "RPTOWNERCIK", "RPTOWNER_RELATIONSHIP"])
            tr = rd("NONDERIV_TRANS.tsv", ["ACCESSION_NUMBER", "TRANS_DATE", "TRANS_CODE"])
        tr = tr[tr["TRANS_CODE"] == "P"]
        m = sub.merge(own, on="ACCESSION_NUMBER").merge(tr, on="ACCESSION_NUMBER")
        m = m[m["RPTOWNER_RELATIONSHIP"].fillna("").str.contains("Officer|Director")]
        rows.append(m)
    m = pd.concat(rows, ignore_index=True)
    m["filing_date"] = pd.to_datetime(m["FILING_DATE"], format="%d-%b-%Y")
    m["trans_date"] = pd.to_datetime(m["TRANS_DATE"], format="%d-%b-%Y", errors="coerce")
    m = m[m["filing_date"] <= through]
    # one row per (accession, owner): earliest P trans date in the filing
    return (m.groupby(["ACCESSION_NUMBER", "RPTOWNERCIK"], as_index=False)
             .agg(filing_date=("filing_date", "first"), trans_date=("trans_date", "min")))


def hand_count_opp(issuer_cik, t):
    m = _raw_zip_od_buys(issuer_cik, t)
    lines, opp, ins, unc = [], set(), set(), set()
    for _, r in m[m["filing_date"] > t - pd.Timedelta(days=90)].iterrows():
        o, td = r["RPTOWNERCIK"], r["trans_date"]
        hist = m[m["RPTOWNERCIK"] == o]
        yrs = set(zip(hist["trans_date"].dt.year, hist["trans_date"].dt.month))
        first = hist["trans_date"].dt.year.min()
        classifiable = pd.notna(td) and td.year - first >= 3
        routine = pd.notna(td) and all((td.year - k, td.month) in yrs for k in (1, 2, 3))
        ins.add(o)
        if not classifiable:
            unc.add(o); kind = "UNCLASSIFIABLE"
        elif routine:
            kind = "routine"
        else:
            opp.add(o); kind = "OPPORTUNISTIC"
        lines.append(f"    {r['ACCESSION_NUMBER']} owner {o} filed {r['filing_date'].date()} "
                     f"trans {td.date() if pd.notna(td) else 'NaT'} first-buy-year {first} -> {kind}")
    return len(opp), len(ins), len(unc), lines


def selftest_ext(cross, test_date, valid, v3_stats, label_lookup, spy_fwd_40):
    from scipy.stats import spearmanr
    ok = True

    def check(name, cond, detail=""):
        nonlocal ok
        ok &= bool(cond)
        log(f"  [{'PASS' if cond else 'FAIL'}] {name} {detail}")

    log("=== ext selftest (scoring logic only; nomination-era date) ===")
    w9 = icw_rule(ICW9_T_USED, ICW9_SIGNS)
    check("icw9 weights reproduce from frozen rule+t",
          all(abs(round(w9[k], 4) - ICW9_WEIGHTS[k]) < 1e-9 for k in w9))
    w8 = icw_rule({k: ICW9_T_USED[k] for k in C.FACTOR_COLS}, C.FACTOR_SIGNS)
    check("same rule reproduces production icw8", all(abs(round(w8[k], 4) - ICW.PRODUCTION_WEIGHTS[k]) < 1e-9 for k in w8))
    check("leverage not in C.FACTOR_COLS", "leverage" not in C.FACTOR_COLS)

    lev = compute_leverage(cross["ticker"], test_date)
    nf = pd.read_parquet(NF.OUT, columns=["ticker", "date", "leverage"])
    nf = nf[nf["date"] == test_date.date().isoformat()].set_index("ticker")["leverage"]
    ref = cross["ticker"].map(nf).to_numpy(np.float64)
    same = (np.isnan(ref) == np.isnan(lev)) & (np.isnan(ref) | (np.abs(ref - lev.astype(np.float32)) < 1e-5))
    check("leverage == new_factors.parquet", same.all(), f"({same.mean():.4%} of {len(lev)}, coverage {np.isfinite(lev).mean():.1%})")

    ext, _stale = build_ext_rows(cross, test_date, valid)
    df = ext.merge(pd.DataFrame({"ticker": cross["ticker"],
                                 "ic_weighted_score": ICW.compute_composite_ic_weighted(cross)["composite"].to_numpy(),
                                 "beta_252": cross["beta_252"], "sector": cross["sector"]}), on="ticker", how="left")
    df["realized"] = df["ticker"].map(label_lookup)
    st = ext_score_frame(df, spy_fwd_40)
    log(f"  ext stats: {st}")
    check("icw8 rho == v3 _score_frame rank_ic_raw_ic_weighted",
          abs(st["rho_icw8_raw"] - v3_stats["rank_ic_raw_ic_weighted"]) < 1e-12,
          f"({st['rho_icw8_raw']:+.6f} vs {v3_stats['rank_ic_raw_ic_weighted']:+.6f})")
    m = df[["ic_weighted_score", "realized"]].dropna()
    rho_sp = spearmanr(m["ic_weighted_score"], m["realized"]).statistic
    check("icw8 rho == scipy.spearmanr", abs(st["rho_icw8_raw"] - rho_sp) < 1e-12)
    shuf = df.copy()
    shuf["realized"] = np.random.default_rng(0).permutation(shuf["realized"].to_numpy())
    check("canary: shuffled returns move rho", abs(ext_score_frame(shuf, spy_fwd_40)["rho_icw8_raw"] - st["rho_icw8_raw"]) > 1e-3)

    feat = pd.read_parquet(OPP.MAIN_ROOT / "out" / "insider" / "insider_features.parquet",
                           columns=["ticker", "date", "ins_buyers_90"])
    feat = feat[pd.to_datetime(feat["date"]) == test_date].drop_duplicates("ticker").set_index("ticker")["ins_buyers_90"]
    ref = ext["ticker"].map(feat).to_numpy(np.float64)
    got = ext["ins_buyers_90"].to_numpy(np.float64)
    eq = (np.isnan(ref) == np.isnan(got)) & (np.isnan(ref) | (ref == got))
    check("ins_buyers_90 == insider_features.parquet (whole cross-section)", eq.all(),
          f"({eq.sum()}/{len(eq)}; fire {np.nanmean(got >= 1):.2%})")

    # hand counts: one name where the routine/unclassifiable exclusion bites
    cm = OPP.cik_map().set_index("ticker")["cik"]
    e2 = ext.assign(cik=ext["ticker"].map(cm))
    pick1 = e2[(e2["ins_buyers_90"] > e2["opp_buyers_90"]) & (e2["opp_buyers_90"] >= 1)]
    pick2 = e2[(e2["opp_buyers_90"] >= 1) & ~e2["ticker"].isin(pick1["ticker"][:1])]
    picks = list(pick1["ticker"][:1]) + list(pick2.sort_values("opp_buyers_90", ascending=False)["ticker"][:1])
    if len(picks) < 2:
        picks = list(e2[e2["opp_buyers_90"] >= 1]["ticker"][:2])
    for tk in picks:
        cik = int(cm[tk])
        h_opp, h_ins, h_unc, lines = hand_count_opp(cik, test_date)
        row = ext[ext["ticker"] == tk].iloc[0]
        log(f"  hand count {tk} (CIK {cik}) on {test_date.date()}:")
        for ln in lines:
            log(ln)
        check(f"hand count {tk}", (h_opp, h_ins, h_unc) == (row["opp_buyers_90"], row["ins_buyers_90"], row["unclass_buyers_90"]),
              f"hand opp/ins/unclass={h_opp}/{h_ins}/{h_unc} ledger={row['opp_buyers_90']:.0f}/"
              f"{row['ins_buyers_90']:.0f}/{row['unclass_buyers_90']:.0f}")
    log(f"=== ext selftest {'PASSED' if ok else 'FAILED'} ===")
    if not ok:
        raise SystemExit(1)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "record"
    {"record": record, "score": score, "selftest": selftest}[cmd]()
