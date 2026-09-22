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

MAIN_ROOT = Path("/Users/ggraham/pipe_dream/final")
PANEL_PATH = MAIN_ROOT / "out" / "reset2026" / "composite_panel.parquet"
OUT_DIR = MAIN_ROOT / "out" / "reset2026"
LEDGER_CSV = OUT_DIR / "prediction_ledger.csv"
SCORES_CSV = OUT_DIR / "prediction_ledger_scores.csv"

NOMINATE_START = pd.Timestamp("2007-01-02")
NOMINATE_END = pd.Timestamp("2019-12-31")
LABEL = "forward_return_tradable_40"
MODEL_VERSION = "asset_growth_dropped_2026-09-22"  # composite.FACTOR_SIGNS as of this commit


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def load_panel(columns):
    df = pd.read_parquet(PANEL_PATH, columns=columns)
    df["date"] = pd.to_datetime(df["date"])
    df["ticker"] = df["ticker"].astype(str)
    return df


def fama_macbeth_slope_nomination():
    """Causal calibration: the average cross-sectional slope of realized
    return on composite score, nomination era only. Never touches 2020+."""
    need = list(dict.fromkeys(["ticker", "date", "sector", "volatility_60",
                                "eligible_cap150", LABEL] + C.FACTOR_COLS))
    df = load_panel(need)
    nom = df[(df["date"] >= NOMINATE_START) & (df["date"] <= NOMINATE_END) & df["eligible_cap150"]]
    slopes = []
    for d, g in nom.groupby("date"):
        gg = g.reset_index(drop=True)
        scored = C.compute_composite(gg, neutral=False)
        x = scored["composite"].to_numpy(np.float64)
        y = g[LABEL].to_numpy(np.float64)
        mask = np.isfinite(x) & np.isfinite(y)
        if mask.sum() < 30:
            continue
        X = np.column_stack([np.ones(mask.sum()), x[mask]])
        beta, *_ = np.linalg.lstsq(X, y[mask], rcond=None)
        slopes.append(beta[1])
    slope = float(np.mean(slopes))
    log(f"Fama-MacBeth slope (nomination era, adopted composite): {slope:.5f} (n={len(slopes)} dates)")
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

    slope = fama_macbeth_slope_nomination()
    scored = C.compute_composite(cross, neutral=False)
    s = scored["composite"].to_numpy(np.float64)
    valid = np.isfinite(s)
    rank_pct = pd.Series(s).rank(pct=True, na_option="keep").to_numpy()
    s_mean = np.nanmean(s)
    predicted_relative_return = slope * (s - s_mean)

    out = pd.DataFrame({
        "panel_date": latest_date.date().isoformat(),
        "recorded_at": pd.Timestamp.now().isoformat(),
        "model_version": MODEL_VERSION,
        "ticker": cross["ticker"],
        "composite_score": s,
        "rank_pct": rank_pct,
        "predicted_relative_return_40d": predicted_relative_return,
        "fm_slope_used": slope,
        "realized_return_40d": np.nan,   # filled in later by `score`
        "scored_at": "",
    })
    out = out[valid].reset_index(drop=True)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    write_header = not LEDGER_CSV.exists()
    out.to_csv(LEDGER_CSV, mode="a", header=write_header, index=False)
    log(f"appended {len(out)} rows to {LEDGER_CSV} for panel_date={latest_date.date()} "
        f"(blind -- outcome does not exist yet)")


def _score_frame(cross_ids, ledger_rows, label_lookup):
    """Shared scoring logic between `score` and `selftest`."""
    merged = ledger_rows.copy()
    merged["realized_return_40d"] = merged["ticker"].map(label_lookup)
    merged = merged.dropna(subset=["realized_return_40d"])
    if len(merged) < 20:
        return None
    ic = merged["composite_score"].corr(merged["realized_return_40d"], method="spearman")
    excess_pred = merged["predicted_relative_return_40d"]
    excess_real = merged["realized_return_40d"] - merged["realized_return_40d"].mean()
    X = np.column_stack([np.ones(len(merged)), excess_pred.to_numpy()])
    beta, *_ = np.linalg.lstsq(X, excess_real.to_numpy(), rcond=None)
    yhat = X @ beta
    ss_res = np.sum((excess_real.to_numpy() - yhat) ** 2)
    ss_tot = np.sum((excess_real.to_numpy() - excess_real.mean()) ** 2)
    r2 = 1 - ss_res / ss_tot if ss_tot > 0 else np.nan
    top_decile = merged.nlargest(max(1, len(merged) // 10), "composite_score")["realized_return_40d"].mean()
    bottom_decile = merged.nsmallest(max(1, len(merged) // 10), "composite_score")["realized_return_40d"].mean()
    return {
        "n_names": int(len(merged)),
        "rank_ic": float(ic),
        "magnitude_calibration_slope": float(beta[1]),
        "magnitude_calibration_intercept": float(beta[0]),
        "magnitude_r2": float(r2),
        "top_decile_mean_return": float(top_decile),
        "bottom_decile_mean_return": float(bottom_decile),
        "top_minus_bottom_decile_spread": float(top_decile - bottom_decile),
    }


def score():
    if not LEDGER_CSV.exists():
        raise SystemExit("No prediction_ledger.csv yet -- run `record` first.")
    ledger = pd.read_csv(LEDGER_CSV, parse_dates=["panel_date"])
    pending = ledger[ledger["realized_return_40d"].isna()]
    if pending.empty:
        log("no pending (unscored) ledger rows")
        return

    panel = load_panel(["ticker", "date", LABEL])
    results = []
    for panel_date, rows in pending.groupby("panel_date"):
        outcomes = panel[panel["date"] == pd.Timestamp(panel_date)]
        if outcomes[LABEL].notna().sum() == 0:
            log(f"{panel_date.date()}: still blind, {len(rows)} rows not yet scoreable")
            continue
        label_lookup = dict(zip(outcomes["ticker"], outcomes[LABEL]))
        stats = _score_frame(None, rows, label_lookup)
        if stats is None:
            log(f"{panel_date.date()}: too few matured names to score yet")
            continue
        stats["panel_date"] = panel_date.date().isoformat()
        stats["scored_at"] = pd.Timestamp.now().isoformat()
        stats["model_version"] = rows["model_version"].iloc[0]
        results.append(stats)
        log(f"{panel_date.date()}: n={stats['n_names']} rank_IC={stats['rank_ic']:+.4f} "
            f"mag_slope={stats['magnitude_calibration_slope']:+.4f} mag_R2={stats['magnitude_r2']:.4f} "
            f"top-bottom decile spread={stats['top_minus_bottom_decile_spread']*100:+.2f}%")

        # Fill the realized outcomes back into the ledger (idempotent -- only
        # touches rows for this now-matured panel_date).
        idx = ledger[ledger["panel_date"] == panel_date].index
        for i in idx:
            t = ledger.at[i, "ticker"]
            if t in label_lookup:
                ledger.at[i, "realized_return_40d"] = label_lookup[t]
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
    slope = fama_macbeth_slope_nomination()
    scored = C.compute_composite(cross, neutral=False)
    s = scored["composite"].to_numpy(np.float64)
    valid = np.isfinite(s)
    s_mean = np.nanmean(s)
    rows = pd.DataFrame({
        "ticker": cross["ticker"][valid].to_numpy(),
        "composite_score": s[valid],
        "predicted_relative_return_40d": (slope * (s - s_mean))[valid],
    })
    label_lookup = dict(zip(cross["ticker"], cross[LABEL]))
    stats = _score_frame(None, rows, label_lookup)
    log(f"SELF-TEST on {test_date.date()} (already-known nomination-era data, "
        f"validates scoring code only): {stats}")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "record"
    {"record": record, "score": score, "selftest": selftest}[cmd]()
