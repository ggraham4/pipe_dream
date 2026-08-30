"""
Regenerate out/backtest_chart.png (grouped bar chart: XGBoost vs LSTM vs SPY,
per-timepoint returns at the current FORWARD_WINDOW horizon) from the current
contents of out/backtest_results.json and out/lstm_backtest_results.json.

Not part of the point-in-time pipeline -- just a plotting convenience, kept
in src/ so it's easy to re-run after any backtest re-run (horizon change,
TRAIN_CAP change, etc.) instead of hand-writing a one-off script each time.

Usage: python3 make_chart.py
"""
import json

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from features import FORWARD_WINDOW, OUT_DIR


def main():
    with open(OUT_DIR / "backtest_results.json") as f:
        xgb = json.load(f)
    with open(OUT_DIR / "lstm_backtest_results.json") as f:
        lstm = json.load(f)

    timepoints = [r["timepoint"] for r in xgb]
    xgb_ret = [r["model_return_pct"] for r in xgb]
    lstm_ret = [r["model_return_pct"] for r in lstm]
    spy_ret = [r["spy_return_pct"] for r in xgb]

    x = np.arange(len(timepoints))
    width = 0.26

    fig, ax = plt.subplots(figsize=(12, 6))
    b1 = ax.bar(x - width, xgb_ret, width, label="XGBoost", color="#2563eb")
    b2 = ax.bar(x, lstm_ret, width, label="LSTM", color="#7c3aed")
    b3 = ax.bar(x + width, spy_ret, width, label="SPY", color="#9ca3af")

    ax.axhline(0, color="black", linewidth=0.8)
    ax.set_ylabel(f"{FORWARD_WINDOW}-trading-day return (%)")
    ax.set_title(f"Walk-forward backtest: XGBoost vs LSTM vs SPY ({FORWARD_WINDOW}-trading-day horizon)")
    ax.set_xticks(x)
    ax.set_xticklabels(timepoints, rotation=30, ha="right")
    ax.legend()
    ax.grid(axis="y", alpha=0.3)

    for bars in (b1, b2, b3):
        for bar in bars:
            h = bar.get_height()
            ax.annotate(f"{h:.1f}", (bar.get_x() + bar.get_width() / 2, h),
                        textcoords="offset points", xytext=(0, 3 if h >= 0 else -12),
                        ha="center", fontsize=7)

    fig.tight_layout()
    out_path = OUT_DIR / "backtest_chart.png"
    fig.savefig(out_path, dpi=150)
    print(f"Saved -> {out_path}")

    xgb_total = sum(r["ending_value_model"] for r in xgb) / len(xgb)
    lstm_total = sum(r["ending_value_model"] for r in lstm) / len(lstm)
    spy_total = sum(r["ending_value_spy"] for r in xgb) / len(xgb)
    print(f"Avg ending value per trial ($10k start) -- XGBoost: {xgb_total:,.2f}  "
          f"LSTM: {lstm_total:,.2f}  SPY: {spy_total:,.2f}")


if __name__ == "__main__":
    main()
