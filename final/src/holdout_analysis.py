"""
Round 9 (2026-09-07): honest out-of-sample test of the stop level.

The review's central statistical objection is that the 15% stop was
chosen on the same 122 windows it is reported on, and that the stop-level
sweep is a sawtooth rather than a smooth basin -- the signature of a
parameter fitted to a handful of specific price paths.

This script settles it the only way it can be settled: pick the stop
level using 2007-2019 windows ONLY, freeze it, and then look at
2020-2026 exactly once. Everything runs through execution.py, so the
out-of-sample number already carries the one-bar entry lag, realistic
gap-through stop fills, the delisting exit floor and transaction costs.

    python3 holdout_analysis.py [--cost-bps 50]
"""
import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from execution import load_ohlc_panel, realize_portfolio

SRC_DIR = Path(__file__).resolve().parent
FINAL_DIR = SRC_DIR.parent
OUT_DIR = FINAL_DIR / "out"
PRICE_DIRS = [FINAL_DIR / "scripts" / "td_data_local",
              FINAL_DIR / "scripts" / "td_data_delisted_repaired",
              FINAL_DIR / "scripts" / "td_data_delisted"]
HORIZON = 40
TRADING_DAYS = 252.0
SPLIT_DATE = "2020-01-01"
GRID = [None, 0.05, 0.08, 0.10, 0.12, 0.13, 0.14, 0.15, 0.16, 0.17, 0.18,
        0.20, 0.22, 0.25, 0.30, 0.35, 0.40, 0.50]


def spy_leg(spy, tp, lag, at):
    fut = spy[spy["date"] > tp]
    if len(fut) < lag:
        return None
    row = fut.iloc[lag - 1]
    e = float(row["open"] if at == "open" else row["close"])
    first = lag - 1 if at == "open" else lag
    w = fut.iloc[first:first + HORIZON]
    if w.empty or e <= 0:
        return None
    return float(w["close"].iloc[-1]) / e - 1.0


def stats(r, s):
    r, s = np.asarray(r), np.asarray(s)
    n = len(r)
    per_yr = TRADING_DAYS / HORIZON
    term = float(np.prod(1 + r) * 10000)
    spy_term = float(np.prod(1 + s) * 10000)
    vol = float(np.std(r, ddof=1) * np.sqrt(per_yr))
    ex = r - s
    return {
        "n": n, "terminal": term, "spy_terminal": spy_term,
        "cagr": float((term / 10000) ** (per_yr / n) - 1),
        "spy_cagr": float((spy_term / 10000) ** (per_yr / n) - 1),
        "sharpe": float(np.mean(r) * per_yr / vol) if vol > 0 else float("nan"),
        "t_excess": float(np.mean(ex) / (np.std(ex, ddof=1) / np.sqrt(n))) if n > 1 else float("nan"),
        "mean_excess": float(np.mean(ex)),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", default="augmented")
    ap.add_argument("--cost-bps", type=float, default=50.0)
    ap.add_argument("--entry-at", default="open")
    args = ap.parse_args()

    base = json.load(open(OUT_DIR / f"continuous_walkforward_pit_{args.mode}.json"))["results"]
    tick = set(t for r in base for t in r["picks"])
    panel = load_ohlc_panel(PRICE_DIRS, tickers=tick | {"SPY"})
    spy = panel["SPY"]

    train, test = [], []
    for r in base:
        (train if r["timepoint"] < SPLIT_DATE else test).append(r)
    print(f"in-sample  2007-2019 : {len(train)} windows")
    print(f"hold-out   2020-2026 : {len(test)} windows  (looked at ONCE, after the choice)\n")

    def evaluate(rows, stop):
        R, S = [], []
        for r in rows:
            tp = pd.Timestamp(r["timepoint"])
            p, _ = realize_portfolio(r["picks"], panel, tp, HORIZON, entry_lag=1,
                                     entry_at=args.entry_at, stop_pct=stop,
                                     cost_bps=args.cost_bps)
            s = spy_leg(spy, tp, 1, args.entry_at)
            if p is None or s is None:
                continue
            R.append(p["net_return"]); S.append(s)
        return stats(R, S)

    print(f"{'stop':>6}  {'IS terminal':>12} {'IS CAGR':>8} {'IS t':>6}   "
          f"{'OOS terminal':>12} {'OOS CAGR':>9} {'OOS t':>6}")
    print("-" * 76)
    is_rows = {}
    grid_out = []
    for stop in GRID:
        a, b = evaluate(train, stop), evaluate(test, stop)
        is_rows[stop] = a
        lbl = "none" if stop is None else f"{stop:.0%}"
        grid_out.append({"stop": stop, "in_sample": a, "holdout": b})
        print(f"{lbl:>6}  ${a['terminal']:>11,.0f} {a['cagr']*100:>7.2f}% {a['t_excess']:>6.2f}   "
              f"${b['terminal']:>11,.0f} {b['cagr']*100:>8.2f}% {b['t_excess']:>6.2f}")

    best = max((s for s in GRID), key=lambda s: is_rows[s]["terminal"])
    chosen = next(g for g in grid_out if g["stop"] == best)
    a, b = chosen["in_sample"], chosen["holdout"]
    lbl = "none" if best is None else f"{best:.0%}"
    print("\n" + "=" * 76)
    print(f"CHOSEN ON 2007-2019 ONLY: stop = {lbl}")
    print(f"  in-sample   ${a['terminal']:>11,.0f} vs SPY ${a['spy_terminal']:>11,.0f}   "
          f"CAGR {a['cagr']*100:5.2f}% vs {a['spy_cagr']*100:5.2f}%   t={a['t_excess']:.2f}")
    print(f"  HOLD-OUT    ${b['terminal']:>11,.0f} vs SPY ${b['spy_terminal']:>11,.0f}   "
          f"CAGR {b['cagr']*100:5.2f}% vs {b['spy_cagr']*100:5.2f}%   t={b['t_excess']:.2f}")
    print("=" * 76)

    # Smoothness: a real risk-management effect varies continuously with the
    # threshold. Measure the sawtooth directly on the in-sample curve.
    fin = [(s, is_rows[s]["terminal"]) for s in GRID if s is not None]
    jumps = [abs(fin[i + 1][1] - fin[i][1]) / fin[i][1] for i in range(len(fin) - 1)]
    print(f"\nin-sample stop curve: max step-to-step change {max(jumps)*100:.1f}%, "
          f"median {np.median(jumps)*100:.1f}%")

    json.dump({"mode": args.mode, "cost_bps": args.cost_bps, "entry_at": args.entry_at,
               "split_date": SPLIT_DATE, "chosen_stop": best, "grid": grid_out},
              open(OUT_DIR / "holdout_analysis.json", "w"), indent=2, default=str)
    print(f"Saved -> {OUT_DIR/'holdout_analysis.json'}")


if __name__ == "__main__":
    main()
