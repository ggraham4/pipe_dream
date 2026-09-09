"""
PRODUCTION -- live buy signal for the PIT/augmented/mid-cap-floor/stop-loss-
optimized model. Promoted to PRIMARY at Gabe's explicit request (2026-09-02):
"we are no longer using the HMM, augmented stoploss should be the primary
model displayed in the app." This replaces current_signal_gated.py (the
HMM-gated blend of two non-PIT models) as the app's headline "Today's Picks"
signal -- see backtest/survivorship-bias-correction-results.md, Round 7/8,
for the full backtest history behind this decision.

What this does, concretely: trains the augmented model (price + PIT
fundamentals, no_staleness) fresh on ALL available history through today
(training data is deliberately NOT restricted by the point-in-time mid-cap+
floor below -- same reasoning backtest_pit.py and continuous_walkforward_pit.
py's run_walkforward() already document for their own training sets: the
floor only constrains what the model is ALLOWED TO PICK today, not what it
learns from), applies the SAME point-in-time mid-cap+ eligibility floor used
in the backtest (market_cap >= MIN_MARKET_CAP and close > MIN_PRICE, Round
7) to today's candidates, takes the top-5 by predicted buy probability, and
reports each pick's entry price alongside the Round-8-optimized 15% stop-
loss level as guidance (not an automated order -- this app doesn't place
trades).

Deliberate simplification vs. the backtest's candidate-pool construction
(flagged, not silently done): the backtest's `allowed_universe_at()` also
admits validated point-in-time S&P 500 "gap tickers" (companies later
delisted/acquired/bankrupted) alongside current-universe tickers, because a
HISTORICAL step needs to know what was really investable back then. For a
LIVE "today" signal this distinction is close to moot -- "today" is exactly
the date the current-universe screen (scripts/local_data_pull.py) was last
applied, so gap tickers add essentially nothing (an already-delisted company
isn't buyable today regardless; a company that merely fell below the $2B
current-universe screen wouldn't be in today's pulled data at all unless it
happens to also be a historical S&P constituent still trading under the old
symbol). This script therefore restricts today's candidates to plain
current-universe tickers that clear the point-in-time mid-cap+ floor, and
does not attempt to fold in gap tickers. If that ever turns out to matter in
practice, it's a straightforward follow-up (import gap_tickers_asof /
members_asof from pit_universe_continuous.py the same way
continuous_walkforward_pit.py does).

Stop-loss guidance is informational only: simulate_stop_loss() in
continuous_walkforward_pit.py showed a 15% trigger (Round 8, off the daily
LOW -- a resting-stop-order assumption) roughly doubles the backtested
total vs. the original untuned 30%, so each pick's suggested stop price is
entry_close * (1 - OPTIMAL_STOP_PCT). Nothing in this script places or
monitors a real order -- Gabe (or a future automation layer) is responsible
for actually acting on it.

Usage:
    python3 current_signal_pit.py

Prerequisites: features_pit.py and fundamentals_features_pit.py must
already have been run (this script reads
out/features_with_fundamentals_pit.parquet).
"""
import numpy as np
import pandas as pd
from xgboost import XGBClassifier

from features import (FEATURE_COLS, FORWARD_WINDOW, LABEL_COL, OUT_DIR, MODELS_DIR,
                       atomic_to_csv, atomic_write_json)
from fundamentals_features_beta import FUNDAMENTAL_FEATURE_COLS
from continuous_walkforward_pit import MIN_MARKET_CAP, MIN_PRICE, load_gap_ticker_set

CUTOFF_PERCENTILE = 75
TOP_N = 5
NO_STALE_COLS = [c for c in FUNDAMENTAL_FEATURE_COLS if c != "fundamentals_age_days"]
AUGMENTED_FEATURE_COLS = FEATURE_COLS + NO_STALE_COLS

# Round 8 (2026-09-02): empirically optimized stop-loss percentage -- a fine
# sweep (10%-20%, 1% steps) over the augmented_stoploss backtest found a
# 12-17% plateau with a peak at 14% ($216,399 vs SPY's $53,306 over 123
# windows); 15% was chosen as the operating value over the raw peak (within
# noise of 14%, same plateau, slightly higher win rate, a rounder/less
# overfit number). See backtest/survivorship-bias-correction-results.md,
# Round 8, for the full sweep table.
OPTIMAL_STOP_PCT = 0.15

CONTEXT_COLS = ["close", "momentum_20", "momentum_60", "momentum_120",
                "relative_strength_20", "pct_from_high_252", "pct_from_low_252", "volatility_20",
                "market_cap"]


def latest_complete_date_pit(feat, gap_tickers, min_coverage=0.9):
    """features.latest_complete_date() picks the latest date where >=
    min_coverage of ALL tickers in the panel have a row -- a fine freshness
    check on features.parquet, where every ticker is actively, currently
    tracked. It silently breaks on features_with_fundamentals_pit.parquet:
    that panel ALSO carries ~260+ point-in-time gap tickers (companies
    delisted, bankrupt, or acquired -- some inactive since 2008), which by
    definition never have a row on any recent date. Confirmed the hard way
    (2026-09-02, Gabe's first real run of this script): calling the plain
    features.latest_complete_date() here silently returned NaT (no date
    ever reaches 90% coverage across current + permanently-delisted
    tickers combined), which cascaded into a 0-tickers-scored, 0-eligible
    RuntimeError further down. Fix: apply the identical 90%-coverage
    check, but against the CURRENT-UNIVERSE ticker count only (gap tickers
    excluded) -- the same current-universe/gap-ticker split
    continuous_walkforward_pit.py's own run_walkforward() already uses.
    Note (a known, pre-existing, documented limitation elsewhere in this
    project -- see price_discontinuity.py's module docstring): a gap
    ticker that also got split by the discontinuity check (e.g.
    "CHRD__post20201118") won't match load_gap_ticker_set()'s plain
    symbols, so its post-break segment counts as "current universe" here
    too -- narrow in practice (a handful of tickers), not fixed here."""
    current = feat[~feat["ticker"].isin(gap_tickers)]
    counts = current.groupby("date").size()
    total = current["ticker"].nunique()
    complete_dates = counts[counts >= min_coverage * total].index
    if len(complete_dates) == 0:
        raise RuntimeError(
            f"No date in features_with_fundamentals_pit.parquet reaches {min_coverage:.0%} coverage "
            f"of the {total} current-universe tickers (gap tickers excluded) -- check that "
            f"features_pit.py / fundamentals_features_pit.py ran against fresh price data."
        )
    return complete_dates.max()


def main():
    feat = pd.read_parquet(OUT_DIR / "features_with_fundamentals_pit.parquet")
    feat = feat.sort_values(["ticker", "date"]).reset_index(drop=True)

    gap_tickers = load_gap_ticker_set()
    latest_date = latest_complete_date_pit(feat, gap_tickers)
    print(f"Latest available trading date (>=90% CURRENT-UNIVERSE coverage, gap tickers excluded): "
          f"{latest_date.date()}")

    # Training data deliberately NOT restricted by the mid-cap+ floor below
    # (same reasoning as backtest_pit.py / continuous_walkforward_pit.py's
    # run_walkforward() -- the floor only constrains what's PICKABLE today).
    train = feat.dropna(subset=FEATURE_COLS + [LABEL_COL])
    cutoff_val = np.percentile(train[LABEL_COL], CUTOFF_PERCENTILE)
    print(f"Training on {len(train)} rows, label cutoff (75th pct {FORWARD_WINDOW}d fwd return) = {cutoff_val:.4f}")

    print("\nTraining AUGMENTED (PIT price + fundamentals, no_staleness) model...")
    y_train = (train[LABEL_COL] > cutoff_val).astype(int)
    model = XGBClassifier(n_estimators=100, max_depth=3, learning_rate=0.1,
                           eval_metric="logloss", verbosity=0)
    model.fit(train[AUGMENTED_FEATURE_COLS], y_train)

    today_rows = feat[feat["date"] == latest_date].dropna(subset=FEATURE_COLS).copy()
    print(f"{len(today_rows)} tickers with complete price features as of {latest_date.date()}")

    # Point-in-time mid-cap+ eligibility floor (Round 7), reapplied here so
    # today's live picks are held to the exact same standard the backtest
    # was: market_cap >= MIN_MARKET_CAP and close > MIN_PRICE ON TODAY'S
    # DATE. A ticker missing market_cap (no fundamentals filed) is treated
    # as ineligible, not assumed to pass -- same "flag/quarantine rather
    # than guess" philosophy as the rest of this project. See the module
    # docstring for why gap tickers aren't separately folded in here.
    n_before = len(today_rows)
    eligible = today_rows[(today_rows["close"] > MIN_PRICE) & (today_rows["market_cap"] >= MIN_MARKET_CAP)].copy()
    print(f"Point-in-time mid-cap+ floor (market_cap >= ${MIN_MARKET_CAP:,.0f}, close > ${MIN_PRICE:.0f}): "
          f"{len(eligible)}/{n_before} tickers eligible today")
    if eligible.empty:
        raise RuntimeError("No tickers cleared the point-in-time mid-cap+ eligibility floor today -- "
                            "check that fundamentals_features_pit.py ran recently enough to have "
                            "current market_cap data.")

    eligible["buy_proba"] = model.predict_proba(eligible[AUGMENTED_FEATURE_COLS])[:, 1]
    eligible["rank"] = eligible["buy_proba"].rank(ascending=False, method="min").astype(int)
    eligible["percentile"] = eligible["rank"] / len(eligible)

    picks = eligible.sort_values("buy_proba", ascending=False).head(TOP_N).copy()
    picks["stop_loss_price"] = picks["close"] * (1 - OPTIMAL_STOP_PCT)

    rows_out = []
    for _, d in picks.iterrows():
        rows_out.append({
            "ticker": d["ticker"],
            "allocation_pct": round(100.0 / TOP_N, 2),
            "buy_proba": round(float(d["buy_proba"]), 4),
            "rank": int(d["rank"]),
            "percentile": round(float(d["percentile"]), 4),
            "close": round(float(d["close"]), 2),
            "suggested_stop_loss_price": round(float(d["stop_loss_price"]), 2),
            "stop_loss_pct": OPTIMAL_STOP_PCT,
            "market_cap": round(float(d["market_cap"]), 0) if pd.notna(d["market_cap"]) else None,
            "momentum_20": round(float(d["momentum_20"]), 4) if pd.notna(d["momentum_20"]) else None,
            "momentum_60": round(float(d["momentum_60"]), 4) if pd.notna(d["momentum_60"]) else None,
            "relative_strength_20": round(float(d["relative_strength_20"]), 4) if pd.notna(d["relative_strength_20"]) else None,
            "pct_from_high_252": round(float(d["pct_from_high_252"]), 4) if pd.notna(d["pct_from_high_252"]) else None,
            "volatility_20": round(float(d["volatility_20"]), 4) if pd.notna(d["volatility_20"]) else None,
        })

    out_df = pd.DataFrame(rows_out)
    print(f"\n=== Augmented + stop-loss (PIT, primary model) top-{TOP_N} as of {latest_date.date()} ===")
    print(out_df.to_string(index=False))
    print(f"\nEach pick: equal-weight ({100.0/TOP_N:.1f}% of capital), suggested stop-loss "
          f"{OPTIMAL_STOP_PCT:.0%} below entry close (Round 8's backtested-optimal level -- "
          f"guidance only, not an automated order).")

    # Atomic writes: the dashboard's Today's Picks tab polls and re-reads
    # these exact files live while this script may still be running as a
    # background retrain job -- see current_signal_gated.py for why this
    # matters (a plain .to_csv()/json.dump() can hand a concurrent reader a
    # truncated file).
    atomic_to_csv(out_df, OUT_DIR / "current_signal_pit.csv", index=False)

    atomic_write_json({
        "as_of_date": str(latest_date.date()),
        "model": "augmented_stoploss (PIT, point-in-time mid-cap+ floor, Round 7/8)",
        "stop_loss_pct": OPTIMAL_STOP_PCT,
        "forward_window_trading_days": FORWARD_WINDOW,
        "train_rows": len(train),
        "label_cutoff_fwd_return": round(float(cutoff_val), 4),
        "min_market_cap": MIN_MARKET_CAP,
        "min_price": MIN_PRICE,
        "n_eligible_today": len(eligible),
        "picks": picks["ticker"].tolist(),
        "allocation": rows_out,
        "backtest_caveat": ("Backtested $10k -> $214,606 vs SPY's $53,306 over 123 non-overlapping "
                             "40-day windows, 2007-2026, expanded (mid-cap-floor-corrected) universe -- "
                             "see backtest/survivorship-bias-correction-results.md, Round 7 (universe "
                             "construction fix) and Round 8 (stop-loss optimization) for the full "
                             "methodology and caveats. Training data is not PIT-restricted (see module "
                             "docstring); this is a single as-of-today fit, not a walk-forward step."),
    }, OUT_DIR / "current_signal_pit_meta.json", indent=2)

    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    model.save_model(str(MODELS_DIR / "xgb_pit_augmented_model.json"))
    print("\nSaved -> out/current_signal_pit.csv, out/current_signal_pit_meta.json")
    print(f"Saved model -> out/models/xgb_pit_augmented_model.json (as_of {latest_date.date()})")


if __name__ == "__main__":
    main()
