"""
PRODUCTION -- live regime-gated buy signal, promoted from
regime_gate_compare_beta.py (validation #6 in models/fundamentals-beta-
results.md) at Gabe's explicit request ("push this HMM gate model to the
app ... I am not concerned about risk").

What this does, concretely: trains BOTH the baseline (price-only) model
and the augmented (price + fundamentals, no_staleness) model fresh on all
available history through today (same procedure as current_signal.py /
query_day.py -- no lookahead, no cached model), gets each model's top-5
picks for today, and computes today's HMM regime-gate weight `w` -- a
2-state Gaussian HMM fit on SPY's daily returns through today only, read
off as the posterior probability of the low-mean/high-variance ("stress")
state. `w` becomes the fraction of capital allocated to the augmented
model's 5 picks; `1-w` goes to the baseline model's 5 picks (equal-weight
within each side, combined if a ticker appears in both lists) -- exactly
the capital split that was backtested in validation #6, which beat both
source models on both return AND max drawdown over the one 41-window,
one-bear-cycle (2022) test run so far.

**What's genuinely new here vs. every other production script in this
repo:** this is the first script that trades on the fundamentals-beta
work (`fundamentals_features_beta.py`, `features_with_fundamentals_beta.
parquet`) and on the regime-gating work -- both still labeled BETA
elsewhere in this project, and both validated on exactly one real bear
market. Gabe has seen the validation-#6 caveats (one crisis in-sample, not
yet portfolio-construction-exact, not stress-tested on a second bear
cycle) and asked for this to go live anyway. `current_signal.py` (the
original price-only production script) is left untouched as a fallback /
comparison point -- this does not replace it, it sits alongside it.

Usage:
    python3 current_signal_gated.py
"""
import numpy as np
import pandas as pd
from xgboost import XGBClassifier

from features import (FEATURE_COLS, FORWARD_WINDOW, LABEL_COL, OUT_DIR, MODELS_DIR, latest_complete_date,
                       atomic_to_csv, atomic_write_json)
from fundamentals_features_beta import FUNDAMENTAL_FEATURE_COLS
from regime_signals_beta import build_spy_returns, hmm_weight

CUTOFF_PERCENTILE = 75
TOP_N = 5  # per side -- matches the $10k top-5 methodology this gate was validated against
NO_STALE_COLS = [c for c in FUNDAMENTAL_FEATURE_COLS if c != "fundamentals_age_days"]
AUGMENTED_FEATURE_COLS = FEATURE_COLS + NO_STALE_COLS

CONTEXT_COLS = ["close", "momentum_20", "momentum_60", "momentum_120",
                "relative_strength_20", "pct_from_high_252", "pct_from_low_252", "volatility_20"]


def train_and_pick(train, today_rows, feature_cols, cutoff_val, tag):
    y_train = (train[LABEL_COL] > cutoff_val).astype(int)
    model = XGBClassifier(n_estimators=100, max_depth=3, learning_rate=0.1,
                           eval_metric="logloss", verbosity=0)
    model.fit(train[feature_cols], y_train)
    today_rows = today_rows.copy()
    today_rows[f"{tag}_buy_proba"] = model.predict_proba(today_rows[feature_cols])[:, 1]
    picks = today_rows.sort_values(f"{tag}_buy_proba", ascending=False).head(TOP_N)
    return model, picks


def main():
    feat = pd.read_parquet(OUT_DIR / "features_with_fundamentals_beta.parquet")
    feat = feat.sort_values(["ticker", "date"]).reset_index(drop=True)

    latest_date = latest_complete_date(feat)
    print(f"Latest available trading date (>=90% universe coverage): {latest_date.date()}")

    # same restricted universe for both models -- requires complete PRICE
    # features + a resolved label; fundamentals columns are allowed to be
    # sparse (XGBoost's native missing-value handling), consistent with
    # every other fundamentals-beta script
    train = feat.dropna(subset=FEATURE_COLS + [LABEL_COL])
    cutoff_val = np.percentile(train[LABEL_COL], CUTOFF_PERCENTILE)
    print(f"Training on {len(train)} rows, label cutoff (75th pct {FORWARD_WINDOW}d fwd return) = {cutoff_val:.4f}")

    today_rows = feat[feat["date"] == latest_date].dropna(subset=FEATURE_COLS).copy()
    print(f"Scoring {len(today_rows)} tickers with complete features as of {latest_date.date()}")

    print("\nTraining BASELINE (price-only) model...")
    baseline_model, baseline_picks = train_and_pick(train, today_rows, FEATURE_COLS, cutoff_val, "baseline")

    print("Training AUGMENTED (price + fundamentals, no_staleness) model...")
    augmented_model, augmented_picks = train_and_pick(train, today_rows, AUGMENTED_FEATURE_COLS, cutoff_val, "augmented")

    print("\nComputing today's HMM regime-gate weight (SPY daily returns through today, causal)...")
    spy_rets, spy_dates = build_spy_returns()
    w = hmm_weight(spy_rets, spy_dates, latest_date)
    if w is None:
        print("WARNING: not enough SPY history for an HMM fit -- falling back to w=0.5 (even split)")
        w = 0.5
    print(f"w (fraction of capital -> augmented/defensive side) = {w:.4f}")
    print(f"  -> {w:.1%} augmented (no_staleness), {1-w:.1%} baseline (price-only)")

    # ---- build the combined allocation ----
    alloc = {}
    for _, row in augmented_picks.iterrows():
        alloc[row["ticker"]] = alloc.get(row["ticker"], 0.0) + w / TOP_N
    for _, row in baseline_picks.iterrows():
        alloc[row["ticker"]] = alloc.get(row["ticker"], 0.0) + (1 - w) / TOP_N

    detail_lookup = today_rows.set_index("ticker")
    rows_out = []
    for ticker, weight in sorted(alloc.items(), key=lambda kv: -kv[1]):
        d = detail_lookup.loc[ticker]
        source = []
        if ticker in augmented_picks["ticker"].values:
            source.append("augmented")
        if ticker in baseline_picks["ticker"].values:
            source.append("baseline")
        rows_out.append({
            "ticker": ticker,
            "allocation_pct": round(weight * 100, 2),
            "source": "+".join(source),
            "close": round(float(d["close"]), 2),
            "momentum_20": round(float(d["momentum_20"]), 4) if pd.notna(d["momentum_20"]) else None,
            "momentum_60": round(float(d["momentum_60"]), 4) if pd.notna(d["momentum_60"]) else None,
            "relative_strength_20": round(float(d["relative_strength_20"]), 4) if pd.notna(d["relative_strength_20"]) else None,
            "pct_from_high_252": round(float(d["pct_from_high_252"]), 4) if pd.notna(d["pct_from_high_252"]) else None,
            "volatility_20": round(float(d["volatility_20"]), 4) if pd.notna(d["volatility_20"]) else None,
        })

    out_df = pd.DataFrame(rows_out)
    print(f"\n=== Combined regime-gated allocation as of {latest_date.date()} ===")
    print(out_df.to_string(index=False))

    print(f"\nBaseline (price-only) top-{TOP_N}:  {baseline_picks['ticker'].tolist()}")
    print(f"Augmented (no_staleness) top-{TOP_N}: {augmented_picks['ticker'].tolist()}")

    # Atomic writes: the dashboard's Today's Picks tab polls and re-reads
    # these exact files live while this script is still running as a
    # background retrain job, so a direct .to_csv()/json.dump() -- which
    # writes `path` in place -- can hand a concurrent reader a truncated
    # file. atomic_to_csv/atomic_write_json write to a temp file and
    # os.replace() into place instead, so a reader always sees either the
    # complete previous file or the complete new one.
    atomic_to_csv(out_df, OUT_DIR / "current_signal_gated.csv", index=False)

    atomic_write_json({
        "as_of_date": str(latest_date.date()),
        "gate": "HMM (2-state Gaussian, SPY daily returns, expanding window, causal)",
        "hmm_weight_on_augmented": round(float(w), 4),
        "forward_window_trading_days": FORWARD_WINDOW,
        "train_rows": len(train),
        "label_cutoff_fwd_return": round(float(cutoff_val), 4),
        "baseline_picks": baseline_picks["ticker"].tolist(),
        "augmented_picks": augmented_picks["ticker"].tolist(),
        "allocation": rows_out,
        "beta_caveat": ("Uses the fundamentals-beta feature set and a regime gate validated on "
                         "exactly one real bear episode (2022) -- see models/fundamentals-beta-"
                         "results.md, validation #6, for the full caveat. Pushed to live use at "
                         "Gabe's explicit request."),
    }, OUT_DIR / "current_signal_gated_meta.json", indent=2)

    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    baseline_model.save_model(str(MODELS_DIR / "xgb_gated_baseline_model.json"))
    augmented_model.save_model(str(MODELS_DIR / "xgb_gated_augmented_model.json"))
    print(f"\nSaved -> out/current_signal_gated.csv, out/current_signal_gated_meta.json")
    print(f"Saved models -> out/models/xgb_gated_{{baseline,augmented}}_model.json (as_of {latest_date.date()})")


if __name__ == "__main__":
    main()
