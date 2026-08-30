"""
Final step: train the buy/no-buy classifier on ALL available history
through the most recent trading day, then score today's cross-section
to produce the current top-10 buy list.

This mirrors the project's own stated end-state for a production model
("once you're satisfied [with holdout evaluation], retrain a final
version on all available data... more data straightforwardly helps a
production model that isn't being scored anymore").
"""
import pandas as pd
import numpy as np
from xgboost import XGBClassifier
import json

from features import FEATURE_COLS, FORWARD_WINDOW, LABEL_COL, OUT_DIR, MODELS_DIR, latest_complete_date

CUTOFF_PERCENTILE = 75
TOP_N = 10


def main():
    feat = pd.read_parquet(OUT_DIR / "features.parquet")
    feat = feat.sort_values(["ticker", "date"]).reset_index(drop=True)

    latest_date = latest_complete_date(feat)
    print(f"Latest available trading date (>=90% universe coverage): {latest_date.date()}")

    # train on every row that HAS a realized label (i.e. its own
    # +FORWARD_WINDOW trading day close already happened) -- this naturally
    # excludes only the most recent ~FORWARD_WINDOW trading days per ticker,
    # no leakage
    train = feat.dropna(subset=FEATURE_COLS + [LABEL_COL])
    cutoff_val = np.percentile(train[LABEL_COL], CUTOFF_PERCENTILE)
    y_train = (train[LABEL_COL] > cutoff_val).astype(int)
    X_train = train[FEATURE_COLS]

    print(f"Training on {len(train)} rows, label cutoff (75th pct {FORWARD_WINDOW}d fwd return) = {cutoff_val:.4f}")

    model = XGBClassifier(n_estimators=100, max_depth=3, learning_rate=0.1,
                           eval_metric="logloss", verbosity=0)
    model.fit(X_train, y_train)

    importances = pd.Series(model.feature_importances_, index=FEATURE_COLS).sort_values(ascending=False)
    print("\nFeature importances:")
    print(importances)

    # score TODAY (latest available date) for every ticker with complete features
    today_rows = feat[feat["date"] == latest_date].dropna(subset=FEATURE_COLS).copy()
    today_rows["buy_proba"] = model.predict_proba(today_rows[FEATURE_COLS])[:, 1]
    today_rows = today_rows.sort_values("buy_proba", ascending=False)

    top10 = today_rows.head(TOP_N)[
        ["ticker", "close", "buy_proba", "momentum_20", "momentum_60", "momentum_120",
         "relative_strength_20", "pct_from_high_252", "pct_from_low_252", "volatility_20"]
    ].copy()

    print(f"\nTop {TOP_N} buy candidates as of {latest_date.date()}:")
    print(top10.to_string(index=False))

    top10.to_csv(OUT_DIR / "current_top10.csv", index=False)
    importances.to_csv(OUT_DIR / "feature_importances.csv")

    with open(OUT_DIR / "current_signal_meta.json", "w") as f:
        json.dump({
            "as_of_date": str(latest_date.date()),
            "forward_window_trading_days": FORWARD_WINDOW,
            "train_rows": len(train),
            "label_cutoff_fwd_return": round(float(cutoff_val), 4),
            "universe_size": int(today_rows.shape[0]),
        }, f, indent=2)

    # Persist the trained model so a future session can score new tickers or
    # regenerate this list without retraining from scratch. This is a
    # same-day fallback/cache keyed to as_of_date -- retrain when the data
    # actually moves forward (new trading day), not a permanent artifact.
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    model.save_model(str(MODELS_DIR / "xgb_current_model.json"))
    with open(MODELS_DIR / "xgb_current_model_meta.json", "w") as f:
        json.dump({
            "as_of_date": str(latest_date.date()),
            "feature_cols": FEATURE_COLS,
            "forward_window_trading_days": FORWARD_WINDOW,
            "label_cutoff_fwd_return": round(float(cutoff_val), 4),
            "train_rows": len(train),
        }, f, indent=2)
    print(f"\nSaved model -> out/models/xgb_current_model.json (as_of {latest_date.date()})")


if __name__ == "__main__":
    main()
