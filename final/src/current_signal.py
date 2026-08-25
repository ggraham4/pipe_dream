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

from features import FEATURE_COLS

LABEL_COL = "forward_return_20"
CUTOFF_PERCENTILE = 75
TOP_N = 10


def main():
    feat = pd.read_parquet("/root/pipe_dream_final/out/features.parquet")
    feat = feat.sort_values(["ticker", "date"]).reset_index(drop=True)

    latest_date = feat["date"].max()
    print(f"Latest available trading date: {latest_date.date()}")

    # train on every row that HAS a realized label (i.e. its own +20
    # trading day close already happened) -- this naturally excludes
    # only the most recent ~20 trading days per ticker, no leakage
    train = feat.dropna(subset=FEATURE_COLS + [LABEL_COL])
    cutoff_val = np.percentile(train[LABEL_COL], CUTOFF_PERCENTILE)
    y_train = (train[LABEL_COL] > cutoff_val).astype(int)
    X_train = train[FEATURE_COLS]

    print(f"Training on {len(train)} rows, label cutoff (75th pct 20d fwd return) = {cutoff_val:.4f}")

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

    top10.to_csv("/root/pipe_dream_final/out/current_top10.csv", index=False)
    importances.to_csv("/root/pipe_dream_final/out/feature_importances.csv")

    with open("/root/pipe_dream_final/out/current_signal_meta.json", "w") as f:
        json.dump({
            "as_of_date": str(latest_date.date()),
            "train_rows": len(train),
            "label_cutoff_20d_return": round(float(cutoff_val), 4),
            "universe_size": int(today_rows.shape[0]),
        }, f, indent=2)


if __name__ == "__main__":
    main()
