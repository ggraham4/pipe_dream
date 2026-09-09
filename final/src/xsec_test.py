"""
Round 10 (2026-09-08): train on a CROSS-SECTIONAL label, and pin determinism.

Two findings from target_diag.py drive this script.

1. THE LABEL WAS A TIMING TARGET.
   The walk-forward binarized at a percentile pooled over ALL dates, so the
   share of positive labels swung from 0.9% to 78.2% window to window and
   correlated 0.883 with that window's mean return. The model was trained
   mostly to predict WHEN, not WHICH. Cross-sectional selection has never
   been tested in this project.

   Fix: rank the forward return WITHIN each date and binarize at the 75th
   percentile OF THAT DATE. Every window then contributes exactly 25%
   positives, the market component is removed from the objective, and the
   question becomes "which of today's candidates beats today's alternatives"
   -- which is the decision actually being made.

2. TRAINING IS NOT REPRODUCIBLE.
   Two runs of nominally identical training disagreed on 1-2 of the top 5
   names in 67 of 117 windows, and the resulting terminal wealth differed by
   2x ($49,472 vs $24,041). Predicted scores are all distinct, so ties are
   NOT the cause; the remaining candidate is non-deterministic parallel
   histogram accumulation in XGBoost's `hist` builder (floating-point
   addition is not associative, so a different row partition across threads
   gives slightly different trees).

   This script pins `nthread` and verifies bit-identical predictions by
   training the first window twice before doing anything else. If run-to-run
   noise is larger than the effect being measured, no single backtest number
   from this project means anything -- so this check gates everything else.

Outputs the same depth/bucket/null tables as rank_depth.py so the two label
modes can be compared directly.

    python3 xsec_test.py [--label-mode xsec|pooled] [--nthread 1]
"""
import argparse
import gc
import json
import os

import numpy as np
import pandas as pd
import xgboost as xgb

from features import (FEATURE_COLS, FORWARD_WINDOW, TRADABLE_LABEL_COL,
                      OUT_DIR, DATA_DIR)
from fundamentals_features_beta import FUNDAMENTAL_FEATURE_COLS
from execution import SegmentedOHLCPanel, realize_position, apply_turnover_costs
import continuous_walkforward_pit as cw

TRADING_DAYS = 252.0
SIZES = [5, 10, 20, 30, 50]
BUCKETS = [(0, 5), (5, 10), (10, 20), (20, 50)]


def cross_sectional_rank(labels, dates_arr):
    """Percentile rank of the forward return WITHIN each date, in [0, 1].

    The panel is date-sorted by load_panel_prepared, so each date occupies a
    contiguous block and this is a cheap pass rather than a groupby.
    """
    out = np.full(len(labels), np.nan, dtype=np.float32)
    _, starts = np.unique(dates_arr, return_index=True)
    starts = np.append(starts, len(dates_arr))
    for i in range(len(starts) - 1):
        a, b = starts[i], starts[i + 1]
        v = labels[a:b]
        m = np.isfinite(v)
        k = int(m.sum())
        if k < 20:
            continue
        r = np.empty(k, dtype=np.float32)
        r[np.argsort(v[m], kind="stable")] = np.arange(k, dtype=np.float32) / (k - 1)
        blk = np.full(b - a, np.nan, dtype=np.float32)
        blk[m] = r
        out[a:b] = blk
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--label-mode", choices=["xsec", "pooled"], default="xsec")
    ap.add_argument("--nthread", type=int, default=1,
                    help="Pinned for reproducibility. 1 is the safest; raise it "
                         "only after the determinism check passes at that value.")
    ap.add_argument("--cost-bps", type=float, default=5.0)
    ap.add_argument("--max-rank", type=int, default=50)
    ap.add_argument("--draws", type=int, default=2000)
    ap.add_argument("--start", default=cw.DEFAULT_START_DATE)
    ap.add_argument("--entry-at", default="open")
    ap.add_argument("--resume", action="store_true")
    args = ap.parse_args()

    params = dict(cw.XGB_PARAMS)
    params["nthread"] = args.nthread
    params["seed"] = 0
    ranks_path = OUT_DIR / f"xsec_ranks_{args.label_mode}.json"

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
    dates_arr = feat["date"].values

    raw = feat[TRADABLE_LABEL_COL].to_numpy(dtype=np.float32, copy=False)
    if args.label_mode == "xsec":
        print("Computing cross-sectional (within-date) rank of the forward return...")
        target = cross_sectional_rank(raw, dates_arr)
        fin_t = np.isfinite(target)
        print(f"  {int(fin_t.sum()):,} rows ranked; a within-date top-quartile cut "
              f"gives 25% positives in EVERY window by construction")
    else:
        target = raw

    import tempfile, atexit, shutil
    td = tempfile.mkdtemp(prefix="xsec_")
    atexit.register(lambda: shutil.rmtree(td, ignore_errors=True))
    mmp = os.path.join(td, "X.npy")
    arr = np.ascontiguousarray(feat[feature_cols].to_numpy(dtype=np.float32, copy=False))
    shape = arr.shape
    mm = np.memmap(mmp, dtype=np.float32, mode="w+", shape=shape)
    mm[:] = arr
    mm.flush()
    del arr, mm
    gc.collect()
    featmat = np.memmap(mmp, dtype=np.float32, mode="r", shape=shape)
    feat = feat[["ticker", "date", "close", "market_cap"]]
    gc.collect()
    print(f"feature matrix {shape} memmapped; nthread={args.nthread}")

    def fit(hi):
        lab = target[:hi]
        fin = np.isfinite(lab)
        if int(fin.sum()) < 300:
            return None
        cut = np.percentile(lab[fin], cw.CUTOFF_PERCENTILE)
        y = (lab > cut).astype(np.int8)
        dtr = xgb.QuantileDMatrix(cw._ChunkIter(featmat, y, hi, mask=fin), max_bin=256)
        b = xgb.train(params, dtr, num_boost_round=cw.XGB_ROUNDS)
        del dtr, y, lab, fin
        gc.collect()
        return b

    def eligible(tp):
        allowed = cw.allowed_universe_at(tp, current_universe, gap_earliest, "expanded")
        lo = int(np.searchsorted(dates_arr, np.datetime64(tp), "left"))
        hi = int(np.searchsorted(dates_arr, np.datetime64(tp), "right"))
        rows = feat.iloc[lo:hi]
        pos = np.arange(lo, hi)
        sel = rows["ticker"].isin(allowed).values
        rows, pos = rows[sel], pos[sel]
        is_gap = rows["ticker"].isin(gap_earliest.index)
        ok = (is_gap | ((rows["close"] > cw.MIN_PRICE) &
                        (rows["market_cap"] >= cw.MIN_MARKET_CAP))).values
        return rows[ok], pos[ok]

    # ---- determinism gate --------------------------------------------------
    print("\n" + "=" * 70)
    print("DETERMINISM CHECK -- train the same window twice, compare predictions")
    print("=" * 70)
    probe = None
    for tp in step_dates:
        idx = all_dates[all_dates == tp].index[0]
        if idx < FORWARD_WINDOW:
            continue
        hi = int(np.searchsorted(dates_arr,
                                 np.datetime64(all_dates.iloc[idx - FORWARD_WINDOW]),
                                 "right"))
        rows, pos = eligible(tp)
        if len(pos) >= 100 and fit(hi) is not None:
            probe = (tp, hi, pos)
            break
    if probe is None:
        raise SystemExit("no usable probe window")
    tp, hi, pos = probe
    p1 = fit(hi).inplace_predict(featmat[pos])
    p2 = fit(hi).inplace_predict(featmat[pos])
    same = bool(np.array_equal(p1, p2))
    top1 = np.argsort(-p1)[:5]
    top2 = np.argsort(-p2)[:5]
    print(f"  window {tp.date()}, {len(pos)} candidates")
    print(f"  predictions bit-identical : {same}")
    print(f"  max abs difference        : {np.abs(p1 - p2).max():.3e}")
    print(f"  top-5 identical           : {bool(np.array_equal(top1, top2))}")
    if not same:
        print("\n  *** NOT REPRODUCIBLE at this nthread. Every backtest number from")
        print("  *** this pipeline carries run-to-run noise. Lower --nthread and")
        print("  *** rerun before trusting anything downstream.")
    else:
        print("\n  reproducible -- results below are stable run to run.")

    # ---- ranks -------------------------------------------------------------
    ranks = {}
    if args.resume and ranks_path.exists():
        ranks = json.load(open(ranks_path))
        print(f"\nresuming: {len(ranks)} windows ranked")
    print(f"\nRanking ({args.label_mode} label)...")
    for i, tp in enumerate(step_dates, 1):
        key = str(tp.date())
        if key in ranks:
            continue
        idx = all_dates[all_dates == tp].index[0]
        if idx < FORWARD_WINDOW:
            continue
        hi = int(np.searchsorted(dates_arr,
                                 np.datetime64(all_dates.iloc[idx - FORWARD_WINDOW]),
                                 "right"))
        rows, pos = eligible(tp)
        if len(pos) < args.max_rank:
            continue
        b = fit(hi)
        if b is None:
            continue
        p = b.inplace_predict(featmat[pos])
        order = np.argsort(-p, kind="stable")[:args.max_rank]
        ranks[key] = list(rows["ticker"].astype(str).values[order])
        del b, p
        gc.collect()
        if i % 10 == 0:
            print(f"  step {i}/{len(step_dates)} {key} ({len(ranks)} ranked)", flush=True)
            json.dump(ranks, open(ranks_path, "w"))
    json.dump(ranks, open(ranks_path, "w"))
    print(f"ranked {len(ranks)} windows -> {ranks_path}")

    # ---- realize and evaluate ---------------------------------------------
    segs = feat.groupby("ticker", observed=True)["date"].agg(["min", "max"])
    panel = SegmentedOHLCPanel(cw.PRICE_DIRS,
        {t: (str(t).split("__post")[0], r["min"], r["max"]) for t, r in segs.iterrows()})
    del segs
    gc.collect()
    spy = pd.read_csv(DATA_DIR / "SPY.csv", parse_dates=["date"]).sort_values("date")
    spy = spy.reset_index(drop=True)

    W = []
    for key in sorted(ranks):
        tp = pd.Timestamp(key)
        rows, _ = eligible(tp)
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
        if len(W) % 25 == 0:
            print(f"  realized {len(W)}", flush=True)

    n = len(W)
    per = TRADING_DAYS / FORWARD_WINDOW
    s = np.array([w["spy"] for w in W])
    h = (args.cost_bps / 1e4) / 2.0
    rt = (1 - h) / (1 + h)
    univ = np.array([np.mean(list(w["lut"].values())) for w in W])
    print(f"\n{n} windows | label={args.label_mode} | SPY ${np.prod(1+s)*10000:,.0f} "
          f"| universe arith {univ.mean()*100:.2f}%/window\n")

    rng = np.random.default_rng(0)
    print(f"{'N':>4}{'arith%':>9}{'terminal':>11}{'vol':>8}{'Sharpe':>8}"
          f"{'rand p50':>11}{'pctile':>8}")
    print("-" * 59)
    out = {}
    for N in SIZES:
        recs = []
        for w in W:
            pk = [t for t in w["rank"][:N] if t in w["lut"]]
            if not pk:
                continue
            recs.append({"timepoint": w["tp"], "picks": pk,
                         "spy_return_pct": w["spy"] * 100,
                         "execution": {
                             "gross_return_pct": float(np.mean([w["lut"][t] for t in pk])) * 100,
                             "per_ticker_gross": {t: w["lut"][t] for t in pk}}})
        recs = apply_turnover_costs(recs, args.cost_bps)
        r = np.array([x["model_return_pct"] / 100
                      for x in sorted(recs, key=lambda q: q["timepoint"])])
        term = float(np.prod(1 + r) * 10000)
        vol = float(r.std(ddof=1) * np.sqrt(per))
        d = np.zeros(args.draws)
        for w in W:
            v = np.array(list(w["lut"].values()))
            idx = rng.integers(0, len(v), size=(args.draws, N))
            d += np.log1p((1 + v[idx].mean(axis=1)) * rt - 1)
        d = 10000 * np.exp(d)
        pct = float((d < term).mean() * 100)
        print(f"{N:>4}{r.mean()*100:>9.2f}${term:>10,.0f}{vol:>8.1%}"
              f"{r.mean()*per/vol:>8.2f}${np.percentile(d,50):>10,.0f}{pct:>8.1f}")
        out[N] = {"arith": float(r.mean()), "terminal": term, "vol": vol,
                  "sharpe": float(r.mean() * per / vol), "percentile": pct}
    print("-" * 59)
    print(f"{'SPY':>4}{s.mean()*100:>9.2f}${np.prod(1+s)*10000:>10,.0f}")

    print("\nrank buckets (arith %/window, gross) -- monotone decline = real ranking")
    for a, b in BUCKETS:
        vals = [np.mean([w["lut"][t] for t in w["rank"][a:b] if t in w["lut"]]) for w in W]
        print(f"  rank {a+1:>2}-{b:<3} {np.mean(vals)*100:>7.2f}%")
    print(f"  universe   {univ.mean()*100:>7.2f}%")

    json.dump({"label_mode": args.label_mode, "nthread": args.nthread,
               "deterministic": same, "n_windows": n, "sizes": out,
               "spy_terminal": float(np.prod(1 + s) * 10000)},
              open(OUT_DIR / f"xsec_test_{args.label_mode}.json", "w"), indent=2)
    print(f"\nSaved -> {OUT_DIR / f'xsec_test_{args.label_mode}.json'}")


if __name__ == "__main__":
    main()
