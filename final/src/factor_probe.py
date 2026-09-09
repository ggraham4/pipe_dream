"""
Round 10 (2026-09-08): what is the buy/no-buy model actually betting on, and
is the bet the right way round?

Motivation
----------
Feature importances on the production model:

    volatility_60        57.2%
    volatility_20         8.9%
    pct_from_high_252     7.6%
    pct_from_low_252      6.0%
    (everything else)    <=5.4% each

Two thirds of the model is trailing realized volatility, and it selects HIGH
volatility. Meanwhile the classifier's own discrimination is ~nil: MCC across
timepoints is 0.027, 0.011, -0.018, 0.025, 0.053, 0.047, -0.015, and AUC in
the two most recent periods is 0.454 and 0.416 -- below random.

Read together, the hypothesis is that this was never a stock-picking model:
it is a long-volatility factor bet wearing an XGBoost costume. That would
explain beta 1.16, portfolio vol 45.8% against SPY's 17.4%, the return
concentration in a handful of windows, and why the stop-loss dominated
everything (stop placement matters most on a high-vol book).

If the hypothesis holds, the model is also loading the LOSING side of the
low-volatility anomaly -- one of the more replicated findings in empirical
asset pricing is that high-volatility, high-beta names underperform on a
risk-adjusted basis.

This script tests it directly, with NO model at all. Same universe, same
point-in-time eligibility screen, same corrected execution, same costs --
only the selection rule changes:

    vol_high        top 5 by volatility_60 (what the model approximates)
    vol_low         bottom 5 by volatility_60 (the inversion)
    mom_high        top 5 by momentum_20
    mom_low         bottom 5 by momentum_20
    drawdown_deep   top 5 by most-negative pct_from_high_252
    random          5 at random (N_RANDOM draws, mean and spread reported)
    universe_ew     equal-weight EVERY eligible name (the naive benchmark)

Reading the output
------------------
- If vol_high roughly reproduces the trained model's numbers, the model is
  the factor and nothing more.
- vol_low is the interesting one, and the two goals pull apart here: the
  low-volatility anomaly predicts BETTER RISK-ADJUSTED return (Sharpe), not
  necessarily better RAW return. Over a sample dominated by a long bull
  market in high-beta names, low-vol may well trail SPY outright. Read the
  Sharpe column and the raw column as separate questions.
- universe_ew is the most important line and the easiest to overlook: if the
  eligible mid-cap universe itself beats SPY equal-weighted, then any
  "edge" a selector shows may just be that universe tilt.

    python3 factor_probe.py [--cost-bps 5] [--top-n 5]

No training, so this runs in a couple of minutes.
"""
import argparse
import copy
import gc
import json

import numpy as np
import pandas as pd

from features import FEATURE_COLS, FORWARD_WINDOW, OUT_DIR, DATA_DIR
from fundamentals_features_beta import FUNDAMENTAL_FEATURE_COLS
from execution import (SegmentedOHLCPanel, realize_portfolio,
                        apply_turnover_costs, DEFAULT_COST_BPS)
import continuous_walkforward_pit as cw

TRADING_DAYS = 252.0
N_RANDOM = 20


def stats(rets, spy_rets, label):
    r = np.asarray(rets, float)
    s = np.asarray(spy_rets, float)
    n = len(r)
    per = TRADING_DAYS / FORWARD_WINDOW
    term = float(np.prod(1 + r) * 10000)
    vol = float(np.std(r, ddof=1) * np.sqrt(per))
    ex = r - s
    t = float(np.mean(ex) / (np.std(ex, ddof=1) / np.sqrt(n))) if n > 1 else float("nan")
    beta, alpha = np.polyfit(s, r, 1)
    curve = np.cumprod(1 + r) * 10000
    dd = float(np.min(curve / np.maximum.accumulate(curve)) - 1)
    return {"label": label, "n": n, "terminal": term,
            "cagr": float((term / 10000) ** (per / n) - 1),
            "vol": vol, "sharpe": float(np.mean(r) * per / vol) if vol > 0 else float("nan"),
            "t_excess": t, "beta": float(beta), "max_dd": dd,
            "win_rate": float(np.mean(r > s))}


def fmt(m):
    return (f"{m['label']:<16}${m['terminal']:>10,.0f} {m['cagr']:>7.2%} {m['vol']:>7.1%} "
            f"{m['sharpe']:>6.2f} {m['t_excess']:>6.2f} {m['beta']:>6.2f} "
            f"{m['max_dd']:>7.1%} {m['win_rate']:>6.1%}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cost-bps", type=float, default=DEFAULT_COST_BPS)
    ap.add_argument("--top-n", type=int, default=cw.TOP_N)
    ap.add_argument("--start", default=cw.DEFAULT_START_DATE)
    ap.add_argument("--universe", choices=["expanded", "sp500"], default="expanded")
    ap.add_argument("--entry-at", choices=["open", "close"], default="open")
    args = ap.parse_args()

    panel_path = OUT_DIR / "features_with_fundamentals_pit.parquet"
    cols = [c for c in FUNDAMENTAL_FEATURE_COLS if c != "fundamentals_age_days"]
    numeric = ["close", "open", "market_cap"] + FEATURE_COLS + cols
    print("Loading panel...")
    feat, n_before = cw.load_panel_prepared(panel_path, numeric, FEATURE_COLS, FORWARD_WINDOW)
    print(f"  {len(feat):,} of {n_before:,} rows carry complete features")

    gap_tickers = cw.load_gap_ticker_set()
    current_universe = set(map(str, feat["ticker"].unique())) - gap_tickers
    gap_earliest = cw.build_gap_validity(feat, gap_tickers)
    if len(gap_earliest) > len(set(gap_tickers)):
        raise AssertionError("gap set leaked -- see build_gap_validity")

    all_dates = feat["date"].drop_duplicates().sort_values().reset_index(drop=True)
    step_dates = cw.build_step_dates(all_dates, args.start, FORWARD_WINDOW)
    dates_arr = feat["date"].values

    segs = feat.groupby("ticker", observed=True)["date"].agg(["min", "max"])
    price_panel = SegmentedOHLCPanel(
        cw.PRICE_DIRS,
        {t: (str(t).split("__post")[0], r["min"], r["max"]) for t, r in segs.iterrows()})
    del segs
    gc.collect()

    spy = pd.read_csv(DATA_DIR / "SPY.csv", parse_dates=["date"]).sort_values("date")
    spy = spy.reset_index(drop=True)

    def spy_leg(tp):
        f = spy[spy["date"] > tp]
        if f.empty:
            return None
        e = float(f.iloc[0]["open" if args.entry_at == "open" else "close"])
        i = 0 if args.entry_at == "open" else 1
        w = f.iloc[i:i + FORWARD_WINDOW]
        return None if w.empty or e <= 0 else float(w["close"].iloc[-1]) / e - 1

    rules = ["vol_high", "vol_low", "mom_high", "mom_low", "drawdown_deep",
             "universe_ew"] + [f"random{i}" for i in range(N_RANDOM)]
    picks_by_rule = {k: [] for k in rules}
    rng = np.random.default_rng(0)

    embargo = FORWARD_WINDOW
    for tp in step_dates:
        idx = all_dates[all_dates == tp].index[0]
        if idx < embargo:
            continue
        allowed = cw.allowed_universe_at(tp, current_universe, gap_earliest, args.universe)
        lo = int(np.searchsorted(dates_arr, np.datetime64(tp), "left"))
        hi = int(np.searchsorted(dates_arr, np.datetime64(tp), "right"))
        rows = feat.iloc[lo:hi]
        rows = rows[rows["ticker"].isin(allowed)]
        if rows.empty:
            continue
        is_gap = rows["ticker"].isin(gap_earliest.index)
        ok = is_gap | ((rows["close"] > cw.MIN_PRICE) &
                       (rows["market_cap"] >= cw.MIN_MARKET_CAP))
        rows = rows[ok]
        if len(rows) < args.top_n:
            continue

        tick = rows["ticker"].astype(str).values
        sel = {
            "vol_high": tick[np.argsort(-rows["volatility_60"].values)[:args.top_n]],
            "vol_low": tick[np.argsort(rows["volatility_60"].values)[:args.top_n]],
            "mom_high": tick[np.argsort(-rows["momentum_20"].values)[:args.top_n]],
            "mom_low": tick[np.argsort(rows["momentum_20"].values)[:args.top_n]],
            "drawdown_deep": tick[np.argsort(rows["pct_from_high_252"].values)[:args.top_n]],
            "universe_ew": tick,
        }
        for i in range(N_RANDOM):
            sel[f"random{i}"] = rng.choice(tick, size=args.top_n, replace=False)
        for k, v in sel.items():
            picks_by_rule[k].append({"timepoint": str(tp.date()), "picks": list(v)})

    print(f"{len(picks_by_rule['vol_high'])} timepoints selected; realizing positions...")

    out = {}
    for rule in rules:
        recs = []
        for w in picks_by_rule[rule]:
            tp = pd.Timestamp(w["timepoint"])
            port, per_t = realize_portfolio(w["picks"], price_panel, tp, FORWARD_WINDOW,
                                            entry_lag=1, entry_at=args.entry_at,
                                            stop_pct=None, cost_bps=0.0)
            s = spy_leg(tp)
            if port is None or s is None:
                continue
            recs.append({"timepoint": w["timepoint"], "picks": w["picks"],
                          "spy_return_pct": s * 100,
                          "model_return_pct": port["gross_return"] * 100,
                          "execution": {"gross_return_pct": port["gross_return"] * 100,
                                         "per_ticker_gross": {k: v["gross_return"]
                                                               for k, v in per_t.items()}}})
        # universe_ew is a hold-the-whole-universe benchmark; charging it
        # 5-name turnover would be wrong, so it is left gross.
        if rule != "universe_ew":
            recs = apply_turnover_costs(recs, args.cost_bps)
        recs = sorted(recs, key=lambda r: r["timepoint"])
        out[rule] = stats([r["model_return_pct"] / 100 for r in recs],
                          [r["spy_return_pct"] / 100 for r in recs], rule)
        out[rule]["_recs"] = recs

    ref = out["vol_high"]["_recs"]
    s = np.array([r["spy_return_pct"] / 100 for r in ref])
    per = TRADING_DAYS / FORWARD_WINDOW
    spy_term = float(np.prod(1 + s) * 10000)
    spy_vol = float(np.std(s, ddof=1) * np.sqrt(per))

    hdr = (f"{'rule':<16}{'terminal':>11} {'CAGR':>7} {'vol':>7} {'Sharpe':>6} "
           f"{'t_exc':>6} {'beta':>6} {'maxDD':>7} {'win':>6}")
    print(f"\ncosts {args.cost_bps:.0f}bp turnover-aware, top-{args.top_n}, "
          f"{len(ref)} windows\n")
    print(hdr); print("-" * len(hdr))
    for rule in ["vol_high", "vol_low", "mom_high", "mom_low", "drawdown_deep", "universe_ew"]:
        print(fmt(out[rule]))
    rt = [out[f"random{i}"]["terminal"] for i in range(N_RANDOM)]
    rs = [out[f"random{i}"]["sharpe"] for i in range(N_RANDOM)]
    print(f"{'random (x%d)' % N_RANDOM:<16}${np.mean(rt):>10,.0f} {'':>7} {'':>7} "
          f"{np.mean(rs):>6.2f}   [terminal p10 ${np.percentile(rt,10):,.0f} "
          f"p90 ${np.percentile(rt,90):,.0f}]")
    print("-" * len(hdr))
    print(f"{'SPY':<16}${spy_term:>10,.0f} {(spy_term/10000)**(per/len(s))-1:>7.2%} "
          f"{spy_vol:>7.1%} {s.mean()*per/spy_vol:>6.2f}")

    for v in out.values():
        v.pop("_recs", None)
    path = OUT_DIR / "factor_probe.json"
    json.dump({"cost_bps": args.cost_bps, "top_n": args.top_n,
                "universe": args.universe, "results": out,
                "spy": {"terminal": spy_term, "vol": spy_vol}},
              open(path, "w"), indent=2)
    print(f"\nSaved -> {path}")


if __name__ == "__main__":
    main()
