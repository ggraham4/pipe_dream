"""
Round 10 (2026-09-08): is the model better than chance at picking 5 names?

`factor_probe.py` refuted the "it's just a long-volatility bet" hypothesis --
selecting the highest-volatility_60 names returns -9.48% CAGR while the
trained model returns +8.87%, and the model's beta (1.16) is nowhere near
vol_high's (1.79). Whatever the model does with volatility_60, it is not
"buy the most volatile thing".

It also showed that a 5-name portfolio is expensive on its own terms: random
5-name draws averaged $34,403 against $41,010 for holding the whole eligible
universe equal-weighted. Same names, same universe -- concentration alone
costs ~16% of terminal wealth to volatility drag, before any selection skill.

So the right null hypothesis is NOT "beat SPY" and NOT "beat the universe".
It is: **given that you are going to hold 5 names from this universe on
these dates, does the model choose better than a coin flip?** That is the
only question whose answer is the model's own contribution.

Method
------
1. For every window, realize EVERY eligible ticker once and cache it. All
   selection rules then become index operations on that cache, which makes
   10,000 random draws cheap instead of impossible.
2. Draw N_DRAWS random 5-name portfolios per window, compound each draw
   across all windows, and build the empirical null distribution of terminal
   wealth and Sharpe.
3. Place the trained model's actual picks in that distribution and report
   its percentile.

Costing note: random draws have essentially zero carry-over between windows,
so they correctly pay a full round trip every window. The model carries ~25%
of its book, so turnover-aware costing is correct for it. Both are reported
for the model so the comparison cannot be accused of being flattered by the
cost convention.

A percentile near 50 means the model adds nothing. Near 95+ means it is
picking better than chance. Anything in between is the honest answer.

    python3 null_test.py [--cost-bps 5] [--draws 10000]
"""
import argparse
import gc
import json

import numpy as np
import pandas as pd

from features import FEATURE_COLS, FORWARD_WINDOW, OUT_DIR, DATA_DIR
from fundamentals_features_beta import FUNDAMENTAL_FEATURE_COLS
from execution import SegmentedOHLCPanel, realize_position, apply_turnover_costs
import continuous_walkforward_pit as cw

TRADING_DAYS = 252.0
MODEL_JSON = "continuous_walkforward_pit_augmented_realistic_tradable.json"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cost-bps", type=float, default=5.0)
    ap.add_argument("--draws", type=int, default=10000)
    ap.add_argument("--top-n", type=int, default=5)
    ap.add_argument("--start", default=cw.DEFAULT_START_DATE)
    ap.add_argument("--entry-at", default="open")
    args = ap.parse_args()

    cols = [c for c in FUNDAMENTAL_FEATURE_COLS if c != "fundamentals_age_days"]
    numeric = ["close", "open", "market_cap"] + FEATURE_COLS + cols
    print("Loading panel...")
    feat, _ = cw.load_panel_prepared(OUT_DIR / "features_with_fundamentals_pit.parquet",
                                      numeric, FEATURE_COLS, FORWARD_WINDOW)

    gap_tickers = cw.load_gap_ticker_set()
    current_universe = set(map(str, feat["ticker"].unique())) - gap_tickers
    gap_earliest = cw.build_gap_validity(feat, gap_tickers)
    all_dates = feat["date"].drop_duplicates().sort_values().reset_index(drop=True)
    step_dates = cw.build_step_dates(all_dates, args.start, FORWARD_WINDOW)
    dates_arr = feat["date"].values

    segs = feat.groupby("ticker", observed=True)["date"].agg(["min", "max"])
    panel = SegmentedOHLCPanel(
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

    model_picks = {}
    mp = OUT_DIR / MODEL_JSON
    if mp.exists():
        for r in json.load(open(mp))["results"]:
            model_picks[r["timepoint"]] = r["picks"]
        print(f"  model picks loaded for {len(model_picks)} windows")

    print("Realizing every eligible ticker, once per window...")
    windows = []
    embargo = FORWARD_WINDOW
    for tp in step_dates:
        idx = all_dates[all_dates == tp].index[0]
        if idx < embargo:
            continue
        allowed = cw.allowed_universe_at(tp, current_universe, gap_earliest, "expanded")
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
        s = spy_leg(tp)
        if s is None:
            continue

        names, rets = [], []
        for t in rows["ticker"].astype(str).values:
            g = panel.get(t)
            if g is None:
                continue
            pos = realize_position(g, tp, FORWARD_WINDOW, entry_lag=1,
                                   entry_at=args.entry_at, stop_pct=None, cost_bps=0.0)
            if pos is not None:
                names.append(t)
                rets.append(pos["gross_return"])
        if len(names) < args.top_n:
            continue
        windows.append({"tp": str(tp.date()), "names": np.array(names),
                        "rets": np.array(rets, dtype=np.float64), "spy": s})
        if len(windows) % 20 == 0:
            print(f"  {len(windows)} windows, last {tp.date()} "
                  f"({len(names)} eligible)", flush=True)

    n = len(windows)
    print(f"\n{n} windows; median eligible per window: "
          f"{int(np.median([len(w['names']) for w in windows]))}")

    per = TRADING_DAYS / FORWARD_WINDOW
    s_arr = np.array([w["spy"] for w in windows])
    spy_term = float(np.prod(1 + s_arr) * 10000)

    h = (args.cost_bps / 1e4) / 2.0
    full_rt = (1 - h) / (1 + h)   # a position opened and closed this window

    # ---- null distribution -------------------------------------------------
    rng = np.random.default_rng(0)
    D = args.draws
    logs = np.zeros(D)
    per_window = np.zeros((n, D))
    for i, w in enumerate(windows):
        r = w["rets"]
        idx = rng.integers(0, len(r), size=(D, args.top_n))
        g = r[idx].mean(axis=1)
        net = (1 + g) * full_rt - 1
        per_window[i] = net
        logs += np.log1p(net)
    null_term = 10000 * np.exp(logs)
    null_vol = per_window.std(axis=0, ddof=1) * np.sqrt(per)
    null_sharpe = per_window.mean(axis=0) * per / null_vol

    # ---- the model on the same windows ------------------------------------
    model_rows = []
    for w in windows:
        pk = model_picks.get(w["tp"])
        if not pk:
            continue
        lut = {t: r for t, r in zip(w["names"], w["rets"])}
        hits = [t for t in pk if t in lut]
        if not hits:
            continue
        g = float(np.mean([lut[t] for t in hits]))
        model_rows.append({"timepoint": w["tp"], "picks": hits,
                            "spy_return_pct": w["spy"] * 100,
                            "execution": {"gross_return_pct": g * 100,
                                           "per_ticker_gross": {t: lut[t] for t in hits}}})
    print(f"model matched on {len(model_rows)} of {n} windows")

    def summarize(rets, label):
        r = np.asarray(rets)
        term = float(np.prod(1 + r) * 10000)
        vol = float(r.std(ddof=1) * np.sqrt(per))
        return {"label": label, "terminal": term, "sharpe": float(r.mean() * per / vol),
                "cagr": float((term / 10000) ** (per / len(r)) - 1), "vol": vol}

    mt = sorted(model_rows, key=lambda x: x["timepoint"])
    m_gross = np.array([x["execution"]["gross_return_pct"] / 100 for x in mt])
    m_perwin = (1 + m_gross) * full_rt - 1
    m_turn = apply_turnover_costs([dict(x, execution=dict(x["execution"])) for x in mt],
                                  args.cost_bps)
    m_turn_r = np.array([x["model_return_pct"] / 100
                          for x in sorted(m_turn, key=lambda q: q["timepoint"])])

    A = summarize(m_perwin, "model (per-window costs, same as random)")
    B = summarize(m_turn_r, "model (turnover-aware costs)")

    # model windows are a subset; rebuild the null on exactly those windows
    keep = [i for i, w in enumerate(windows) if w["tp"] in {x["timepoint"] for x in mt}]
    sub = per_window[keep]
    sub_term = 10000 * np.exp(np.log1p(sub).sum(axis=0))
    sub_sharpe = sub.mean(axis=0) * per / (sub.std(axis=0, ddof=1) * np.sqrt(per))
    sub_spy = float(np.prod(1 + s_arr[keep]) * 10000)

    print("\n" + "=" * 74)
    print(f"NULL: {D:,} random {args.top_n}-name portfolios over the model's "
          f"{len(keep)} windows")
    print("=" * 74)
    for p in [5, 10, 25, 50, 75, 90, 95, 99]:
        print(f"  p{p:<3} terminal ${np.percentile(sub_term, p):>10,.0f}   "
              f"Sharpe {np.percentile(sub_sharpe, p):>5.2f}")
    print(f"  mean  terminal ${sub_term.mean():>10,.0f}   "
          f"Sharpe {sub_sharpe.mean():>5.2f}")
    print(f"\n  SPY over the same windows: ${sub_spy:,.0f}")
    print(f"  share of random draws that beat SPY: "
          f"{(sub_term > sub_spy).mean():.1%}")
    print("\n" + "-" * 74)
    for m in (A, B):
        pt = float((sub_term < m["terminal"]).mean() * 100)
        ps = float((sub_sharpe < m["sharpe"]).mean() * 100)
        print(f"{m['label']}")
        print(f"   terminal ${m['terminal']:>10,.0f}  CAGR {m['cagr']:>6.2%}  "
              f"Sharpe {m['sharpe']:>5.2f}")
        print(f"   percentile vs null:  terminal p{pt:.1f}   Sharpe p{ps:.1f}")
    print("-" * 74)

    # ---- how much does concentration itself cost? --------------------------
    print("\nconcentration sweep (random draws, per-window costs):")
    print(f"{'top_n':>7}{'mean terminal':>15}{'median':>12}{'mean Sharpe':>13}")
    for k in [1, 3, 5, 10, 20, 50]:
        lg = np.zeros(2000)
        pw = np.zeros((len(keep), 2000))
        for j, i in enumerate(keep):
            r = windows[i]["rets"]
            kk = min(k, len(r))
            idx = rng.integers(0, len(r), size=(2000, kk))
            net = (1 + r[idx].mean(axis=1)) * full_rt - 1
            pw[j] = net
            lg += np.log1p(net)
        t = 10000 * np.exp(lg)
        sh = pw.mean(axis=0) * per / (pw.std(axis=0, ddof=1) * np.sqrt(per))
        print(f"{k:>7}{np.mean(t):>15,.0f}{np.median(t):>12,.0f}{np.mean(sh):>13.2f}")

    json.dump({"n_windows": len(keep), "draws": D, "cost_bps": args.cost_bps,
                "spy_terminal": sub_spy,
                "null": {f"p{p}": float(np.percentile(sub_term, p))
                          for p in [5, 25, 50, 75, 95]},
                "model_per_window": A, "model_turnover_aware": B},
              open(OUT_DIR / "null_test.json", "w"), indent=2)
    print(f"\nSaved -> {OUT_DIR/'null_test.json'}")


if __name__ == "__main__":
    main()
