"""
BETA -- chart comparing baseline (price-only) vs augmented (price+fundamentals)
XGBoost across the 10/20/40/60-day horizon sweep, from horizon_sweep_
fundamentals_beta_summary.json. Companion to make_chart.py, kept separate
since this is beta output, not production.

Usage: python3 make_chart_fundamentals_beta.py
"""
import json

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from features import OUT_DIR


def main():
    with open(OUT_DIR / "horizon_sweep_fundamentals_beta_summary.json") as f:
        summary = json.load(f)

    horizons = sorted(int(h) for h in summary["horizons"].keys())
    baseline_ret = [summary["horizons"][str(h)]["baseline"]["avg_return_pct"] for h in horizons]
    augmented_ret = [summary["horizons"][str(h)]["augmented"]["avg_return_pct"] for h in horizons]
    spy_ret = [summary["horizons"][str(h)]["baseline"]["avg_spy_pct"] for h in horizons]
    baseline_win = [summary["horizons"][str(h)]["baseline"]["win_rate"] for h in horizons]
    augmented_win = [summary["horizons"][str(h)]["augmented"]["win_rate"] for h in horizons]

    x = np.arange(len(horizons))
    width = 0.26

    fig, ax = plt.subplots(figsize=(10, 6))
    b1 = ax.bar(x - width, baseline_ret, width, label="Baseline (price-only)", color="#2563eb")
    b2 = ax.bar(x, augmented_ret, width, label="Augmented (+ fundamentals)", color="#dc2626")
    b3 = ax.bar(x + width, spy_ret, width, label="SPY", color="#9ca3af")

    ax.axhline(0, color="black", linewidth=0.8)
    ax.set_ylabel("Avg return per trial (%)")
    ax.set_title("BETA: fundamentals vs price-only, across forward-return horizons (XGBoost)")
    ax.set_xticks(x)
    ax.set_xticklabels([f"{h}d\n(base {baseline_win[i]}, aug {augmented_win[i]})" for i, h in enumerate(horizons)])
    ax.legend()
    ax.grid(axis="y", alpha=0.3)

    for bars in (b1, b2, b3):
        for bar in bars:
            h = bar.get_height()
            ax.annotate(f"{h:.1f}", (bar.get_x() + bar.get_width() / 2, h),
                        textcoords="offset points", xytext=(0, 3 if h >= 0 else -12),
                        ha="center", fontsize=8)

    fig.tight_layout()
    out_path = OUT_DIR / "fundamentals_beta_horizon_chart.png"
    fig.savefig(out_path, dpi=150)
    print(f"Saved -> {out_path}")


if __name__ == "__main__":
    main()
