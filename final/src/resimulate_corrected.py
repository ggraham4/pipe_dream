"""
Round 9 (2026-09-07): re-simulate the committed walk-forward picks under
progressively more realistic execution, so the contribution of each
review finding is measured separately instead of all at once.

This does NOT retrain anything. It reuses the EXACT picks and timepoints
already recorded in out/continuous_walkforward_pit_<mode>.json and only
changes how those positions are realized. Any difference between the
ladder rungs is therefore purely an execution-assumption effect.

    python3 resimulate_corrected.py [--mode augmented] [--stop 0.15]
"""
import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from execution import realize_portfolio, load_ohlc_panel

SRC_DIR = Path(__file__).resolve().parent
FINAL_DIR = SRC_DIR.parent
OUT_DIR = FINAL_DIR / "out"
# Repaired delisted panel first (see repair_ohlc_coherence.py) -- falls back
# to the raw one if the repair has not been run.
PRICE_DIRS = [FINAL_DIR / "scripts" / "td_data_local",
              FINAL_DIR / "scripts" / "td_data_delisted_repaired",
              FINAL_DIR / "scripts" / "td_data_delisted"]
HORIZON = 40
TRADING_DAYS = 252.0


def spy_return(spy, tp, horizon, entry_lag, entry_at, cost_bps=0.0):
    """SPY realized the same way as the model leg, so the comparison is
    apples-to-apples (the benchmark eats the same lag; a buy-and-hold
    benchmark is not charged per-window turnover)."""
    fut = spy[spy["date"] > tp]
    if entry_lag == 0:
        sig = spy[spy["date"] == tp]
        if sig.empty:
            return None
        entry = float(sig["close"].iloc[0])
        win = fut.iloc[:horizon]
    else:
        if len(fut) < entry_lag:
            return None
        row = fut.iloc[entry_lag - 1]
        entry = float(row["open"] if entry_at == "open" else row["close"])
        first = entry_lag - 1 if entry_at == "open" else entry_lag
        win = fut.iloc[first:first + horizon]
    if win.empty or entry <= 0:
        return None
    return float(win["close"].iloc[-1]) / entry - 1.0


def summarize(name, rets, spy_rets):
    r = np.asarray(rets, dtype=float)
    s = np.asarray(spy_rets, dtype=float)
    n = len(r)
    term = float(np.prod(1.0 + r) * 10000.0)
    spy_term = float(np.prod(1.0 + s) * 10000.0)
    yrs = n * HORIZON / TRADING_DAYS
    cagr = (term / 10000.0) ** (1.0 / yrs) - 1.0
    spy_cagr = (spy_term / 10000.0) ** (1.0 / yrs) - 1.0
    per_yr = TRADING_DAYS / HORIZON
    vol = float(np.std(r, ddof=1) * np.sqrt(per_yr))
    sharpe = float(np.mean(r) * per_yr / vol) if vol > 0 else float("nan")
    spy_vol = float(np.std(s, ddof=1) * np.sqrt(per_yr))
    spy_sharpe = float(np.mean(s) * per_yr / spy_vol) if spy_vol > 0 else float("nan")
    ex = r - s
    t = float(np.mean(ex) / (np.std(ex, ddof=1) / np.sqrt(n))) if n > 1 else float("nan")
    # CAPM on window returns
    beta, alpha = np.polyfit(s, r, 1)
    resid = r - (alpha + beta * s)
    se_a = float(np.std(resid, ddof=2) / np.sqrt(n))
    t_alpha = float(alpha / se_a) if se_a > 0 else float("nan")
    curve = np.cumprod(1.0 + r) * 10000.0
    dd = float(np.min(curve / np.maximum.accumulate(curve)) - 1.0)
    return {
        "name": name, "n": n, "terminal": term, "spy_terminal": spy_term,
        "cagr": cagr, "spy_cagr": spy_cagr, "vol": vol, "sharpe": sharpe,
        "spy_sharpe": spy_sharpe, "t_excess": t, "alpha": float(alpha),
        "t_alpha": t_alpha, "beta": float(beta), "max_dd": dd,
        "win_rate": float(np.mean(r > s)),
    }


def fmt(m):
    return (f"{m['name']:<44} ${m['terminal']:>10,.0f}  {m['cagr']*100:>6.2f}%  "
            f"{m['sharpe']:>5.2f}  {m['t_excess']:>6.2f}  {m['t_alpha']:>6.2f}  "
            f"{m['max_dd']*100:>7.1f}%  {m['win_rate']*100:>5.1f}%")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", default="augmented")
    ap.add_argument("--stop", type=float, default=0.15)
    ap.add_argument("--cost-bps", type=float, default=50.0)
    ap.add_argument("--json-out", default="resimulation_corrected.json")
    args = ap.parse_args()

    src = OUT_DIR / f"continuous_walkforward_pit_{args.mode}.json"
    base = json.load(open(src))
    results = base["results"]

    tickers = set()
    for r in results:
        tickers.update(r["picks"])
    print(f"Loaded {len(results)} windows, {len(tickers)} distinct picked tickers from {src.name}")

    panel = load_ohlc_panel(PRICE_DIRS, tickers=tickers | {"SPY"})
    spy = panel.get("SPY")
    if spy is None:
        spy = pd.read_csv(FINAL_DIR / "scripts" / "td_data_local" / "SPY.csv",
                          parse_dates=["date"]).sort_values("date").reset_index(drop=True)
    print(f"Price panel: {len(panel)} tickers loaded")

    # The ladder. Each rung adds ONE review finding to the rung above it.
    rungs = [
        ("A. as-published: same-bar entry, exact stop, no cost",
         dict(entry_lag=0, entry_at="close", stop_pct=args.stop, cost_bps=0.0, exact_stop=True)),
        ("B. + next-open entry (one-bar lag)",
         dict(entry_lag=1, entry_at="open", stop_pct=args.stop, cost_bps=0.0, exact_stop=True)),
        ("C. + realistic stop fills (gap-through)",
         dict(entry_lag=1, entry_at="open", stop_pct=args.stop, cost_bps=0.0, exact_stop=False)),
        (f"D. + transaction costs ({args.cost_bps:.0f}bp round trip)",
         dict(entry_lag=1, entry_at="open", stop_pct=args.stop, cost_bps=args.cost_bps, exact_stop=False)),
        ("E. no stop at all (corrected execution + costs)",
         dict(entry_lag=1, entry_at="open", stop_pct=None, cost_bps=args.cost_bps, exact_stop=False)),
    ]

    all_metrics = []
    stop_stats = {}
    for name, cfg in rungs:
        rets, spys = [], []
        n_stop = n_gap = n_trunc = 0
        for r in results:
            tp = pd.Timestamp(r["timepoint"])
            port, per = realize_portfolio(
                r["picks"], panel, tp, HORIZON, entry_lag=cfg["entry_lag"],
                entry_at=cfg["entry_at"], stop_pct=cfg["stop_pct"], cost_bps=cfg["cost_bps"])
            sret = spy_return(spy, tp, HORIZON, cfg["entry_lag"], cfg["entry_at"])
            if port is None or sret is None:
                continue
            ret = port["net_return"]
            if cfg["exact_stop"] and cfg["stop_pct"] is not None:
                # As-published behaviour: every stop books exactly -stop_pct.
                w = 1.0 / port["n_positions"]
                ret = sum(w * (1.0 + (-cfg["stop_pct"] if p["stopped"] else p["net_return"]))
                          for p in per.values()) - 1.0
            rets.append(ret)
            spys.append(sret)
            n_stop += port["n_stopped"]; n_gap += port["n_gap_through"]; n_trunc += port["n_truncated"]
        m = summarize(name, rets, spys)
        all_metrics.append(m)
        stop_stats[name] = dict(stopped=n_stop, gap_through=n_gap, truncated=n_trunc)

    hdr = (f"{'configuration':<44} {'terminal':>11}  {'CAGR':>6}  {'Shrp':>5}  "
           f"{'t_exc':>6}  {'t_alp':>6}  {'maxDD':>8}  {'win':>6}")
    print("\n" + hdr); print("-" * len(hdr))
    for m in all_metrics:
        print(fmt(m))
    print("-" * len(hdr))
    b = all_metrics[0]
    print(f"{'SPY buy & hold (same windows)':<44} ${b['spy_terminal']:>10,.0f}  "
          f"{b['spy_cagr']*100:>6.2f}%  {b['spy_sharpe']:>5.2f}")

    print("\nstop / exit diagnostics")
    for k, v in stop_stats.items():
        print(f"  {k:<44} stopped={v['stopped']:>4}  gap-through={v['gap_through']:>4}  "
              f"series-end exits={v['truncated']:>3}")

    out = OUT_DIR / args.json_out
    json.dump({"mode": args.mode, "stop_pct": args.stop, "cost_bps": args.cost_bps,
               "horizon": HORIZON, "ladder": all_metrics, "stop_stats": stop_stats},
              open(out, "w"), indent=2)
    print(f"\nSaved -> {out}")


if __name__ == "__main__":
    main()
