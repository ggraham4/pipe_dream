"""
A genuinely forward, un-spent test of the composite's predictions -- per
Gabe's request for a theoretical model whose predictions "can be tested"
without spending the 2020-2026 hold-out again. Every date in that window has
already been analyzed multiple times today; the only clean test left is real
calendar time that has not happened yet.

Two commands:

  record  -- Uses the MOST RECENT available cross-section in
             `composite_panel.parquet` (currently 2026-09-08 -- verified
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

  score   -- Re-reads `composite_panel.parquet` for any ledger dates whose
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

MAIN_ROOT = Path("/Users/ggraham/pipe_dream/final")
PANEL_PATH = MAIN_ROOT / "out" / "reset2026" / "composite_panel.parquet"
BETA_PATH = MAIN_ROOT / "out" / "reset2026" / "beta_feature.parquet"
OUTCOME_PATH = MAIN_ROOT / "out" / "reset2026" / "outcome_cache.parquet"
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


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def load_panel(columns):
    df = pd.read_parquet(PANEL_PATH, columns=columns)
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


def record():
    need = list(dict.fromkeys(["ticker", "date", "sector", "volatility_60",
                                "eligible_cap150", LABEL] + C.FACTOR_COLS))
    df = load_panel(need)
    latest_date = df.loc[df["eligible_cap150"], "date"].max()
    cross = df[(df["date"] == latest_date) & df["eligible_cap150"]].reset_index(drop=True)
    n_matured = cross[LABEL].notna().sum()
    log(f"most recent eligible cross-section: {latest_date.date()}, {len(cross)} names, "
        f"{n_matured} already have a realized 40-day outcome (should be 0 for a genuinely blind record)")
    if n_matured > 0:
        raise SystemExit(f"REFUSING: {n_matured} names on {latest_date.date()} already have a realized "
                          f"outcome -- this date is not blind. Pick a more recent panel refresh.")

    beta, _spy = _load_beta_and_market()
    cross = cross.merge(beta[beta["date"] == latest_date][["ticker", "beta_252"]], on="ticker", how="left")
    log(f"beta_252 coverage on this cross-section: {cross['beta_252'].notna().mean():.1%}")

    slope = fama_macbeth_slope_nomination()
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
    write_header = not LEDGER_CSV.exists()
    out.to_csv(LEDGER_CSV, mode="a", header=write_header, index=False)
    log(f"appended {len(out)} rows to {LEDGER_CSV} for panel_date={latest_date.date()} "
        f"(blind -- outcome does not exist yet)")


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


def score():
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


def selftest():
    """Validates the scoring logic only, on an ALREADY-KNOWN nomination-era
    date (2015-06-15, arbitrary, mid-era). Draws no conclusion about the
    model -- this only checks the ledger/scoring arithmetic is correct
    before trusting it on real future data."""
    need = list(dict.fromkeys(["ticker", "date", "sector", "volatility_60",
                                "eligible_cap150", LABEL] + C.FACTOR_COLS))
    df = load_panel(need)
    test_date = pd.Timestamp(sys.argv[2]) if len(sys.argv) > 2 else pd.Timestamp("2015-06-15")
    cross = df[(df["date"] == test_date) & df["eligible_cap150"]].reset_index(drop=True)
    if cross.empty:
        raise SystemExit(f"No eligible cross-section on {test_date.date()} -- pick another self-test date.")
    beta, spy = _load_beta_and_market()
    cross = cross.merge(beta[beta["date"] == test_date][["ticker", "beta_252"]], on="ticker", how="left")
    slope = fama_macbeth_slope_nomination()
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


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "record"
    {"record": record, "score": score, "selftest": selftest}[cmd]()
