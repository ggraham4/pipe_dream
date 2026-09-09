"""
Round 10 (2026-09-08): cash as a position, and the bull/bear decomposition.

Why
---
The stated goal is to beat SPY on RAW RETURN in bull and bear markets alike.
That goal is unreachable by any static long-only equity portfolio: beating
SPY when it rises needs effective beta >= 1, beating it when it falls needs
beta < 1, and a fixed tilt has one beta. So exposure must vary, which makes
"hold cash" a required action rather than an optional one.

This script does two things.

1. BULL/BEAR DECOMPOSITION of the strategies already measured. Split the
   windows by the sign of SPY's own return and report each strategy's mean
   return in each bucket. This is the direct test of the stated goal and it
   has never been run -- every number in this project so far is a blend of
   both regimes.

2. CASH AS A POSITION, tested honestly. Each timing rule is computable from
   information available at the decision date only. Cash earns the risk-free
   rate (--cash-yield), NOT zero: over 2007-2026 T-bills paid ~5% at the
   start, ~0% through 2009-2015, and ~5% again from 2023, so treating cash as
   0% would flatter every timing rule.

The null hypothesis is the point
--------------------------------
A timing rule is NOT benchmarked against "always invested". It is benchmarked
against RANDOM CASH AT MATCHED FREQUENCY: if a rule is out of the market for
k of n windows, it is compared against N_DRAWS allocators that are out for k
randomly-chosen windows. Anything else scores luck as skill.

We already have a worked example of why. In universe_probe v1, the screen
`momentum_120 > 0` appeared to beat SPY by 14% -- entirely because it could
not fill its book in March 2009 and silently sat out the crash. That is an
accidental timing result. Under a matched-frequency null it has to prove the
crash windows were chosen, not stumbled into.

    python3 regime_probe.py [--cash-yield 2.0] [--draws 10000]
"""
import argparse
import gc
import json

import numpy as np
import pandas as pd

from features import FEATURE_COLS, FORWARD_WINDOW, OUT_DIR, DATA_DIR
from fundamentals_features_beta import FUNDAMENTAL_FEATURE_COLS
from execution import SegmentedOHLCPanel, realize_position
import continuous_walkforward_pit as cw

TRADING_DAYS = 252.0
MODEL_JSON = "continuous_walkforward_pit_augmented_realistic_tradable.json"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cost-bps", type=float, default=5.0)
    ap.add_argument("--cash-yield", type=float, default=2.0,
                     help="Annualized %% earned while in cash. 2%% is a rough "
                          "2007-2026 T-bill average; pass the real series if you "
                          "have it, the ZIRP years and 2023-25 differ a lot.")
    ap.add_argument("--draws", type=int, default=10000)
    ap.add_argument("--start", default=cw.DEFAULT_START_DATE)
    ap.add_argument("--entry-at", default="open")
    args = ap.parse_args()

    cash_ret = (1 + args.cash_yield / 100) ** (FORWARD_WINDOW / TRADING_DAYS) - 1
    print(f"cash earns {cash_ret*100:.3f}% per {FORWARD_WINDOW}-day window "
          f"({args.cash_yield:.1f}% annualized)")

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
    spy["ma200"] = spy["close"].rolling(200).mean()
    spy["mom120"] = spy["close"].pct_change(120)
    spy["rvol60"] = spy["close"].pct_change().rolling(60).std() * np.sqrt(TRADING_DAYS)

    model_picks = {}
    mp = OUT_DIR / MODEL_JSON
    if mp.exists():
        for r in json.load(open(mp))["results"]:
            model_picks[r["timepoint"]] = r["picks"]

    print("Realizing every eligible ticker, once per window...")
    W = []
    for tp in step_dates:
        idx = all_dates[all_dates == tp].index[0]
        if idx < FORWARD_WINDOW:
            continue
        allowed = cw.allowed_universe_at(tp, current_universe, gap_earliest, "expanded")
        lo = int(np.searchsorted(dates_arr, np.datetime64(tp), "left"))
        hi = int(np.searchsorted(dates_arr, np.datetime64(tp), "right"))
        rows = feat.iloc[lo:hi]
        rows = rows[rows["ticker"].isin(allowed)]
        if rows.empty:
            continue
        is_gap = rows["ticker"].isin(gap_earliest.index)
        rows = rows[is_gap | ((rows["close"] > cw.MIN_PRICE) &
                              (rows["market_cap"] >= cw.MIN_MARKET_CAP))]
        if len(rows) < 20:
            continue
        # SPY leg + the timing signals, all as of tp (decision-time only)
        sig = spy[spy["date"] <= tp]
        f = spy[spy["date"] > tp]
        if sig.empty or f.empty:
            continue
        e = float(f.iloc[0]["open" if args.entry_at == "open" else "close"])
        i0 = 0 if args.entry_at == "open" else 1
        win = f.iloc[i0:i0 + FORWARD_WINDOW]
        if win.empty or e <= 0:
            continue
        s = float(win["close"].iloc[-1]) / e - 1
        last = sig.iloc[-1]

        names, rets, mom = [], [], []
        for t, m120 in zip(rows["ticker"].astype(str).values,
                           rows["momentum_120"].values):
            g = panel.get(t)
            if g is None:
                continue
            pos = realize_position(g, tp, FORWARD_WINDOW, entry_lag=1,
                                   entry_at=args.entry_at, stop_pct=None, cost_bps=0.0)
            if pos is not None:
                names.append(t); rets.append(pos["gross_return"]); mom.append(m120)
        if len(names) < 20:
            continue
        W.append({"tp": str(tp.date()), "names": np.array(names),
                  "rets": np.array(rets, float), "mom": np.array(mom, float), "spy": s,
                  "above200": bool(np.isfinite(last["ma200"]) and
                                   last["close"] > last["ma200"]),
                  "spymom_pos": bool(np.isfinite(last["mom120"]) and last["mom120"] > 0),
                  "rvol": float(last["rvol60"]) if np.isfinite(last["rvol60"]) else np.nan})
        if len(W) % 20 == 0:
            print(f"  {len(W)} windows, last {tp.date()}", flush=True)

    n = len(W)
    per = TRADING_DAYS / FORWARD_WINDOW
    s_arr = np.array([w["spy"] for w in W])
    up = s_arr > 0
    h = (args.cost_bps / 1e4) / 2.0
    rt = (1 - h) / (1 + h)
    print(f"\n{n} windows: {up.sum()} SPY-up, {(~up).sum()} SPY-down")

    # ---------- base strategies, bull/bear split ---------------------------
    base = {}
    base["universe_ew"] = np.array([(1 + w["rets"].mean()) * rt - 1 for w in W])
    med_rvol = np.nanmedian([w["rvol"] for w in W])

    mr = []
    for w in W:
        pk = model_picks.get(w["tp"])
        lut = dict(zip(w["names"], w["rets"]))
        hit = [lut[t] for t in (pk or []) if t in lut]
        mr.append((1 + float(np.mean(hit))) * rt - 1 if hit else np.nan)
    base["model_5"] = np.array(mr)

    print("\n" + "=" * 78)
    print("BULL / BEAR DECOMPOSITION -- the direct test of 'beat SPY in both'")
    print("=" * 78)
    print(f"{'strategy':<16}{'all':>10}{'SPY-up':>12}{'SPY-down':>12}"
          f"{'up-capture':>12}{'down-capture':>14}")
    print("-" * 78)
    def show(name, r):
        m = np.isfinite(r)
        a, u, d = r[m].mean(), r[m & up].mean(), r[m & ~up].mean()
        uc = u / s_arr[m & up].mean()
        dc = d / s_arr[m & ~up].mean()
        print(f"{name:<16}{a*100:>9.2f}%{u*100:>11.2f}%{d*100:>11.2f}%"
              f"{uc:>11.2f}x{dc:>13.2f}x")
    for k, v in base.items():
        show(k, v)
    show("SPY", s_arr)
    print("-" * 78)
    print("up-capture >1 and down-capture <1 is what the goal requires.")
    print("down-capture >1 means it falls MORE than SPY in down windows.")

    # ---------- cash as a position ------------------------------------------
    breadth = np.array([float((w["mom"] > 0).mean()) for w in W])
    rules = {
        "spy_above_200dma": np.array([w["above200"] for w in W]),
        "spy_mom120_pos": np.array([w["spymom_pos"] for w in W]),
        "breadth_gt_50pct": breadth > 0.5,
        "rvol_below_median": np.array([(w["rvol"] <= med_rvol)
                                        if np.isfinite(w["rvol"]) else True for w in W]),
    }

    print("\n" + "=" * 78)
    print("CASH AS A POSITION -- vs a matched-frequency random-cash null")
    print("=" * 78)
    rng = np.random.default_rng(0)
    out = {}
    for bname, bret in base.items():
        b = np.where(np.isfinite(bret), bret, cash_ret)
        inv_term = float(np.prod(1 + b) * 10000)
        print(f"\nbase = {bname}   always-invested ${inv_term:,.0f}")
        print(f"  {'rule':<20}{'in mkt':>8}{'terminal':>11}{'CAGR':>8}"
              f"{'Sharpe':>8}{'null p50':>11}{'pctile':>8}")
        for rname, inmkt in rules.items():
            r = np.where(inmkt, b, cash_ret)
            term = float(np.prod(1 + r) * 10000)
            vol = float(r.std(ddof=1) * np.sqrt(per))
            k = int((~inmkt).sum())
            # matched-frequency null: k randomly chosen cash windows
            draws = np.empty(args.draws)
            for j in range(args.draws):
                idx = rng.choice(n, size=k, replace=False)
                rr = b.copy(); rr[idx] = cash_ret
                draws[j] = np.prod(1 + rr)
            draws *= 10000
            pct = float((draws < term).mean() * 100)
            print(f"  {rname:<20}{n-k:>8}${term:>10,.0f}"
                  f"{(term/10000)**(per/n)-1:>8.2%}{r.mean()*per/vol:>8.2f}"
                  f"${np.percentile(draws,50):>10,.0f}{pct:>7.1f}")
            out[f"{bname}|{rname}"] = {"terminal": term, "cash_windows": k,
                                        "null_p50": float(np.percentile(draws, 50)),
                                        "percentile": pct}
    print("\npctile is the rule's rank against random cash of the SAME frequency.")
    print("~50 means the timing added nothing; the exposure reduction did the work.")
    json.dump({"n_windows": n, "cash_yield": args.cash_yield,
                "spy_terminal": float(np.prod(1 + s_arr) * 10000), "rules": out},
              open(OUT_DIR / "regime_probe.json", "w"), indent=2)
    print(f"\nSaved -> {OUT_DIR/'regime_probe.json'}")


if __name__ == "__main__":
    main()
