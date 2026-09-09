"""
Round 10 (2026-09-08): does the model's ranking have skill BELOW the top 5?

The question this settles
-------------------------
The bull/bear run produced the most informative number of the project:

    strategy      arith/window   per-window vol   variance drag   geometric
    model_5           2.93%          18.2%           1.65pp         1.28%
    SPY               1.58%           6.7%           0.22pp         1.36%

The model earns nearly TWICE SPY's arithmetic return and finishes in a dead
heat, because holding 5 names costs it 1.65pp per window in variance drag
against SPY's 0.22pp. The edge is not missing. It is being spent on
concentration.

That yields a clean, falsifiable prediction. Take the model's OWN ranking and
build portfolios of increasing size:

  * If the ranking carries real skill, the arithmetic mean should decay only
    slowly as N grows (rank 6-20 should still beat the universe average),
    while portfolio volatility falls fast. Geometric return and terminal
    wealth should RISE substantially, peaking somewhere well above N=5.

  * If the top 5 were noise, the arithmetic mean collapses toward the
    universe average (1.49%/window) as soon as you go deeper, and terminal
    wealth converges to universe_ew (~$38,700) from below.

Those two outcomes look nothing alike, which is what makes this worth running.
It also directly prices Gabe's own observation that position count and
allocation are unoptimized parameters -- except that here N is not being
tuned for performance, it is being used as a diagnostic of whether the
ranking means anything.

Every portfolio size is scored against a RANDOM DRAW OF THE SAME SIZE, so
each N clears its own null. A model top-20 that beats random-20 is skill; a
model top-20 that merely beats model-top-5 is just diversification, which we
already know is free.

Also reports rank-bucket returns (1-5, 6-10, 11-20, 21-50) -- if the ranking
is real, these should decline monotonically.

    python3 rank_depth.py [--cost-bps 5] [--max-rank 50] [--resume]

Writes out/rank_depth_ranks.json (the rankings, reusable) and
out/rank_depth.json (the evaluation).
"""
import argparse, gc, json, os
import numpy as np
import pandas as pd
import xgboost as xgb

from features import (FEATURE_COLS, FORWARD_WINDOW, TRADABLE_LABEL_COL,
                       OUT_DIR, DATA_DIR)
from fundamentals_features_beta import FUNDAMENTAL_FEATURE_COLS
from execution import SegmentedOHLCPanel, realize_position, apply_turnover_costs
import continuous_walkforward_pit as cw

TRADING_DAYS = 252.0
SIZES = [1, 3, 5, 10, 20, 30, 50]
BUCKETS = [(0, 5), (5, 10), (10, 20), (20, 50)]


def build_ranks(args):
    ckpt = OUT_DIR / "rank_depth_ranks.json"
    ranks = {}
    if args.resume and ckpt.exists():
        ranks = json.load(open(ckpt))
        print(f"resuming: {len(ranks)} windows already ranked")

    cols = [c for c in FUNDAMENTAL_FEATURE_COLS if c != "fundamentals_age_days"]
    numeric = ["close", "open", "market_cap"] + FEATURE_COLS + cols
    print("Loading panel...")
    feat, _ = cw.load_panel_prepared(OUT_DIR / "features_with_fundamentals_pit.parquet",
                                      numeric, FEATURE_COLS, FORWARD_WINDOW)
    feature_cols = FEATURE_COLS + cols
    gap_tickers = cw.load_gap_ticker_set()
    current_universe = set(map(str, feat["ticker"].unique())) - gap_tickers
    gap_earliest = cw.build_gap_validity(feat, gap_tickers)
    all_dates = feat["date"].drop_duplicates().sort_values().reset_index(drop=True)
    step_dates = cw.build_step_dates(all_dates, args.start, FORWARD_WINDOW)

    import tempfile, atexit, shutil
    td = tempfile.mkdtemp(prefix="rank_depth_")
    atexit.register(lambda: shutil.rmtree(td, ignore_errors=True))
    mm = os.path.join(td, "X.npy")
    arr = np.ascontiguousarray(feat[feature_cols].to_numpy(dtype=np.float32, copy=False))
    shape = arr.shape
    m = np.memmap(mm, dtype=np.float32, mode="w+", shape=shape)
    m[:] = arr; m.flush(); del arr, m; gc.collect()
    featmat = np.memmap(mm, dtype=np.float32, mode="r", shape=shape)
    labels = feat[TRADABLE_LABEL_COL].to_numpy(dtype=np.float32, copy=False)
    dates_arr = feat["date"].values
    feat = feat[["ticker", "date", "close", "market_cap"]]
    gc.collect()
    print(f"feature matrix {shape} memmapped")

    for i, tp in enumerate(step_dates, 1):
        key = str(tp.date())
        if key in ranks:
            continue
        idx = all_dates[all_dates == tp].index[0]
        if idx < FORWARD_WINDOW:
            continue
        cutoff = all_dates.iloc[idx - FORWARD_WINDOW]
        hi = int(np.searchsorted(dates_arr, np.datetime64(cutoff), "right"))
        lab = labels[:hi]
        fin = np.isfinite(lab)
        if int(fin.sum()) < 300:
            continue
        cut = np.percentile(lab[fin], cw.CUTOFF_PERCENTILE)
        y = (lab > cut).astype(np.int8)
        dtrain = xgb.QuantileDMatrix(cw._ChunkIter(featmat, y, hi, mask=fin), max_bin=256)
        del y, lab, fin; gc.collect()
        booster = xgb.train(cw.XGB_PARAMS, dtrain, num_boost_round=cw.XGB_ROUNDS)
        del dtrain; gc.collect()

        allowed = cw.allowed_universe_at(tp, current_universe, gap_earliest, "expanded")
        lo = int(np.searchsorted(dates_arr, np.datetime64(tp), "left"))
        hi2 = int(np.searchsorted(dates_arr, np.datetime64(tp), "right"))
        rows = feat.iloc[lo:hi2]
        pos = np.arange(lo, hi2)
        sel = rows["ticker"].isin(allowed).values
        rows, pos = rows[sel], pos[sel]
        if rows.empty:
            del booster; gc.collect(); continue
        is_gap = rows["ticker"].isin(gap_earliest.index)
        ok = (is_gap | ((rows["close"] > cw.MIN_PRICE) &
                        (rows["market_cap"] >= cw.MIN_MARKET_CAP))).values
        rows, pos = rows[ok], pos[ok]
        if len(rows) < args.max_rank:
            del booster; gc.collect(); continue
        proba = booster.inplace_predict(featmat[pos])
        order = np.argsort(-proba)[:args.max_rank]
        ranks[key] = list(rows["ticker"].astype(str).values[order])
        del booster, proba; gc.collect()
        if i % 5 == 0:
            print(f"  step {i}/{len(step_dates)} {key} ({len(ranks)} ranked)", flush=True)
            json.dump(ranks, open(ckpt, "w"))
    json.dump(ranks, open(ckpt, "w"))
    print(f"ranked {len(ranks)} windows -> {ckpt}")
    return ranks


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cost-bps", type=float, default=5.0)
    ap.add_argument("--max-rank", type=int, default=50)
    ap.add_argument("--draws", type=int, default=2000)
    ap.add_argument("--start", default=cw.DEFAULT_START_DATE)
    ap.add_argument("--entry-at", default="open")
    ap.add_argument("--resume", action="store_true")
    args = ap.parse_args()

    ranks = build_ranks(args)

    # ---- realize everything -------------------------------------------------
    cols = [c for c in FUNDAMENTAL_FEATURE_COLS if c != "fundamentals_age_days"]
    numeric = ["close", "open", "market_cap"] + FEATURE_COLS + cols
    feat, _ = cw.load_panel_prepared(OUT_DIR / "features_with_fundamentals_pit.parquet",
                                      numeric, FEATURE_COLS, FORWARD_WINDOW)
    gap_tickers = cw.load_gap_ticker_set()
    current_universe = set(map(str, feat["ticker"].unique())) - gap_tickers
    gap_earliest = cw.build_gap_validity(feat, gap_tickers)
    dates_arr = feat["date"].values
    segs = feat.groupby("ticker", observed=True)["date"].agg(["min", "max"])
    panel = SegmentedOHLCPanel(cw.PRICE_DIRS,
        {t: (str(t).split("__post")[0], r["min"], r["max"]) for t, r in segs.iterrows()})
    del segs; gc.collect()

    spy = pd.read_csv(DATA_DIR / "SPY.csv", parse_dates=["date"]).sort_values("date")
    spy = spy.reset_index(drop=True)

    W = []
    for key in sorted(ranks):
        tp = pd.Timestamp(key)
        allowed = cw.allowed_universe_at(tp, current_universe, gap_earliest, "expanded")
        lo = int(np.searchsorted(dates_arr, np.datetime64(tp), "left"))
        hi = int(np.searchsorted(dates_arr, np.datetime64(tp), "right"))
        rows = feat.iloc[lo:hi]
        rows = rows[rows["ticker"].isin(allowed)]
        is_gap = rows["ticker"].isin(gap_earliest.index)
        rows = rows[is_gap | ((rows["close"] > cw.MIN_PRICE) &
                              (rows["market_cap"] >= cw.MIN_MARKET_CAP))]
        f = spy[spy["date"] > tp]
        if rows.empty or f.empty:
            continue
        e = float(f.iloc[0]["open" if args.entry_at == "open" else "close"])
        i0 = 0 if args.entry_at == "open" else 1
        win = f.iloc[i0:i0 + FORWARD_WINDOW]
        if win.empty or e <= 0:
            continue
        lut = {}
        for t in rows["ticker"].astype(str).values:
            g = panel.get(t)
            if g is None:
                continue
            p = realize_position(g, tp, FORWARD_WINDOW, entry_lag=1,
                                 entry_at=args.entry_at, stop_pct=None, cost_bps=0.0)
            if p is not None:
                lut[t] = p["gross_return"]
        if len(lut) < args.max_rank:
            continue
        W.append({"tp": key, "lut": lut, "rank": ranks[key],
                  "spy": float(win["close"].iloc[-1]) / e - 1})
        if len(W) % 20 == 0:
            print(f"  realized {len(W)} windows", flush=True)

    n = len(W)
    per = TRADING_DAYS / FORWARD_WINDOW
    s = np.array([w["spy"] for w in W])
    h = (args.cost_bps / 1e4) / 2.0
    rt = (1 - h) / (1 + h)
    univ = np.array([np.mean(list(w["lut"].values())) for w in W])
    print(f"\n{n} windows. SPY ${np.prod(1+s)*10000:,.0f}. "
          f"universe arith {univ.mean()*100:.2f}%/window\n")

    rng = np.random.default_rng(0)
    print(f"{'N':>4}{'arith%':>9}{'geo%':>8}{'terminal':>11}{'vol':>8}{'Sharpe':>8}"
          f"{'rand p50':>11}{'pctile':>8}")
    print("-" * 68)
    out = {}
    for N in SIZES:
        recs = []
        for w in W:
            pk = [t for t in w["rank"][:N] if t in w["lut"]]
            if not pk:
                continue
            recs.append({"timepoint": w["tp"], "picks": pk, "spy_return_pct": w["spy"]*100,
                          "execution": {"gross_return_pct": float(np.mean([w["lut"][t] for t in pk]))*100,
                                         "per_ticker_gross": {t: w["lut"][t] for t in pk}}})
        recs = apply_turnover_costs(recs, args.cost_bps)
        r = np.array([x["model_return_pct"]/100 for x in sorted(recs, key=lambda q: q["timepoint"])])
        term = float(np.prod(1+r)*10000); vol = float(r.std(ddof=1)*np.sqrt(per))
        # matched null: random N from the same eligible pool
        d = np.zeros(args.draws)
        for i, w in enumerate(W):
            v = np.array(list(w["lut"].values()))
            idx = rng.integers(0, len(v), size=(args.draws, N))
            d += np.log1p((1+v[idx].mean(axis=1))*rt - 1)
        d = 10000*np.exp(d)
        pct = float((d < term).mean()*100)
        print(f"{N:>4}{r.mean()*100:>9.2f}{((term/10000)**(per/n)-1)*100/per:>8.2f}"
              f"${term:>10,.0f}{vol:>8.1%}{r.mean()*per/vol:>8.2f}"
              f"${np.percentile(d,50):>10,.0f}{pct:>8.1f}")
        out[N] = {"arith": float(r.mean()), "terminal": term, "vol": vol,
                  "sharpe": float(r.mean()*per/vol), "null_p50": float(np.percentile(d,50)),
                  "percentile": pct}
    print("-" * 68)
    print(f"{'univ':>4}{univ.mean()*100:>9.2f}{'':>8}${np.prod(1+(1+univ)*rt-1)*10000:>10,.0f}")
    print(f"{'SPY':>4}{s.mean()*100:>9.2f}{'':>8}${np.prod(1+s)*10000:>10,.0f}")

    print("\nrank buckets (arith %/window, gross) -- monotone decline = real ranking")
    for a, b in BUCKETS:
        vals = [np.mean([w["lut"][t] for t in w["rank"][a:b] if t in w["lut"]]) for w in W]
        print(f"  rank {a+1:>2}-{b:<3} {np.mean(vals)*100:>7.2f}%")
    print(f"  universe   {univ.mean()*100:>7.2f}%")

    json.dump({"n_windows": n, "cost_bps": args.cost_bps, "sizes": out,
                "spy_terminal": float(np.prod(1+s)*10000)},
              open(OUT_DIR / "rank_depth.json", "w"), indent=2)
    print(f"\nSaved -> {OUT_DIR/'rank_depth.json'}")


if __name__ == "__main__":
    main()
