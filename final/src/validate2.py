"""
Round 10 (2026-09-08): does the cross-sectional result survive falsification?

The result to be attacked
-------------------------
Training on a within-date rank instead of a pooled percentile produced:

    rank  1-5   4.43%/window      N=5  terminal $298,528   (SPY $48,077)
    rank  6-10  3.05%             N=10          $205,207
    rank 11-20  1.96%             N=20          $103,657
    rank 21-50  1.61%             N=50           $54,078
    universe    1.53%

Perfectly monotone, converging on the universe mean, every size at p96+.
Implied IC is ~0.04, which is an ordinary number for a working equity signal
rather than a leakage signature (leakage looks like IC 0.2+).

That is exactly the profile of a real cross-sectional signal. It is ALSO 6.2x
SPY, and this project's standing rule is that anything beating SPY by more
than ~2% annualized is presumed to be a bug until a mechanism is named. Eight
spectacular results have already dissolved on inspection. So this one gets
attacked properly before it is believed.

Three tests, each capable of killing it
---------------------------------------
1. PLACEBO (--mode placebo). Permute the target WITHIN each date. Every
   structure is preserved -- same rows, same dates, same features, same
   25%-positive-per-window design, same walk-forward, same execution -- and
   only the feature->label link is destroyed. A real signal must collapse to
   the universe mean (~1.53%/window, ~$38k). If the placebo still prints a
   big number, the edge is plumbing, not signal, and it is coming from
   somewhere other than the features.

2. INFORMATION COEFFICIENT. Spearman rank correlation between the predicted
   score and the realized within-date rank, computed across ALL eligible
   candidates each window. This measures the signal directly instead of
   inferring it from a 5-name portfolio, which is dominated by tail luck.
   Reported with a t-stat and split by era. Expect ~0.03-0.06 if real;
   >0.15 means look-ahead somewhere.

3. EMBARGO SENSITIVITY (--embargo-mult 2). The label for a training row at
   date t resolves at t+40, and the cutoff sits exactly 40 trading days
   before the decision date, so the last training label resolves ON the
   decision date. That is the tightest legal setting. Doubling the embargo
   throws away real data and must cost a little; if it destroys the edge
   entirely, the edge was living on the boundary.

Also reports 2007-2019 vs 2020-2026 separately, since a signal that exists
only in one era is a different (and weaker) claim than one that persists.

    python3 validate_xsec.py --mode real
    python3 validate_xsec.py --mode placebo
    python3 validate_xsec.py --mode real --embargo-mult 2
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
SIZES = [5, 10, 20, 50]
SPLIT = "2020-01-01"


def cross_sectional_rank(labels, dates_arr, rng=None):
    """Within-date percentile rank in [0,1]. With rng, the finite values are
    PERMUTED within each date -- the placebo. Structure identical, link cut."""
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
        if rng is not None:
            rng.shuffle(r)
        blk = np.full(b - a, np.nan, dtype=np.float32)
        blk[m] = r
        out[a:b] = blk
    return out


def spearman(a, b):
    if len(a) < 10:
        return np.nan
    ra = np.empty(len(a)); ra[np.argsort(a, kind="stable")] = np.arange(len(a))
    rb = np.empty(len(b)); rb[np.argsort(b, kind="stable")] = np.arange(len(b))
    ra -= ra.mean(); rb -= rb.mean()
    d = np.sqrt((ra ** 2).sum() * (rb ** 2).sum())
    return float((ra * rb).sum() / d) if d > 0 else np.nan


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["real", "placebo"], default="real")
    ap.add_argument("--embargo-mult", type=int, default=1)
    ap.add_argument("--nthread", type=int, default=1)
    ap.add_argument("--cost-bps", type=float, default=5.0)
    ap.add_argument("--max-rank", type=int, default=50)
    ap.add_argument("--start", default=cw.DEFAULT_START_DATE)
    ap.add_argument("--entry-at", default="open")
    ap.add_argument("--causal-prices", action="store_true",
                    help="Use scripts/td_data_delisted_repaired_causal/ (trailing "
                         "window) instead of the centered-window repair. The "
                         "centered estimator used ~10 future bars to set each "
                         "bar's adjustment factor, and that factor multiplies "
                         "open/high/low -- which sit inside both the tradable "
                         "label (close[t+H]/open[t+1]) and the realized entry "
                         "price. Run with and without to price that contamination.")
    ap.add_argument("--exclude-gap", action="store_true",
                    help="Drop gap (delisted / index-leaver) tickers from the "
                         "CANDIDATE pool. Round 10 ablation: gap names are exempt "
                         "from the cap/price floor, are concentrated early in the "
                         "sample, and are the only names touched by "
                         "repair_ohlc_coherence.py -- whose factor estimate used a "
                         "CENTERED rolling window, i.e. future bars. If the IC "
                         "collapses with these excluded, the edge lives in them "
                         "and is contamination, not signal.")
    args = ap.parse_args()

    tag = (f"{args.mode}_emb{args.embargo_mult}"
           + ("_nogap" if args.exclude_gap else "")
           + ("_causal" if args.causal_prices else ""))
    if args.causal_prices:
        base = cw.DATA_DIR.parent
        cw.PRICE_DIRS = [cw.DATA_DIR,
                         base / "td_data_delisted_repaired_causal",
                         base / "td_data_delisted"]
        print(f"  price dirs -> causal repair: {[str(d.name) for d in cw.PRICE_DIRS]}")
    params = dict(cw.XGB_PARAMS); params["nthread"] = args.nthread; params["seed"] = 0

    cols = [c for c in FUNDAMENTAL_FEATURE_COLS if c != "fundamentals_age_days"]
    numeric = ["close", "open", "market_cap"] + FEATURE_COLS + cols
    print(f"Loading panel...  [mode={args.mode}, embargo={args.embargo_mult}x]")
    feat, n_before = cw.load_panel_prepared(
        OUT_DIR / "features_with_fundamentals_pit.parquet",
        numeric, FEATURE_COLS, FORWARD_WINDOW)
    print(f"  {len(feat):,} of {n_before:,} rows carry complete features")
    feature_cols = FEATURE_COLS + cols
    gap_tickers = cw.load_gap_ticker_set()
    current_universe = set(map(str, feat["ticker"].unique())) - gap_tickers
    gap_earliest = cw.build_gap_validity(feat, gap_tickers)
    all_dates = feat["date"].drop_duplicates().sort_values().reset_index(drop=True)
    step_dates = cw.build_step_dates(all_dates, args.start, FORWARD_WINDOW)
    dates_arr = feat["date"].values

    raw = feat[TRADABLE_LABEL_COL].to_numpy(dtype=np.float32, copy=False)
    truth = cross_sectional_rank(raw, dates_arr)          # always the REAL rank
    rng0 = np.random.default_rng(12345) if args.mode == "placebo" else None
    target = truth if rng0 is None else cross_sectional_rank(raw, dates_arr, rng0)
    if rng0 is not None:
        ok = np.isfinite(truth) & np.isfinite(target)
        print(f"  PLACEBO: target permuted within date; corr(target, truth) = "
              f"{np.corrcoef(target[ok], truth[ok])[0,1]:+.4f} (should be ~0)")

    import tempfile, atexit, shutil
    td = tempfile.mkdtemp(prefix="valxsec_")
    atexit.register(lambda: shutil.rmtree(td, ignore_errors=True))
    mmp = os.path.join(td, "X.npy")
    arr = np.ascontiguousarray(feat[feature_cols].to_numpy(dtype=np.float32, copy=False))
    shape = arr.shape
    mm = np.memmap(mmp, dtype=np.float32, mode="w+", shape=shape)
    mm[:] = arr; mm.flush(); del arr, mm; gc.collect()
    featmat = np.memmap(mmp, dtype=np.float32, mode="r", shape=shape)
    feat = feat[["ticker", "date", "close", "market_cap"]]
    gc.collect()

    emb = FORWARD_WINDOW * args.embargo_mult
    rows_out = []
    for i, tp in enumerate(step_dates, 1):
        idx = all_dates[all_dates == tp].index[0]
        if idx < emb:
            continue
        hi = int(np.searchsorted(dates_arr,
                                 np.datetime64(all_dates.iloc[idx - emb]), "right"))
        lab = target[:hi]
        fin = np.isfinite(lab)
        if int(fin.sum()) < 300:
            continue
        cut = np.percentile(lab[fin], cw.CUTOFF_PERCENTILE)
        y = (lab > cut).astype(np.int8)
        dtr = xgb.QuantileDMatrix(cw._ChunkIter(featmat, y, hi, mask=fin), max_bin=256)
        bst = xgb.train(params, dtr, num_boost_round=cw.XGB_ROUNDS)
        del dtr, y, lab, fin; gc.collect()

        allowed = cw.allowed_universe_at(tp, current_universe, gap_earliest, "expanded")
        lo2 = int(np.searchsorted(dates_arr, np.datetime64(tp), "left"))
        hi2 = int(np.searchsorted(dates_arr, np.datetime64(tp), "right"))
        r_ = feat.iloc[lo2:hi2]; p_ = np.arange(lo2, hi2)
        sel = r_["ticker"].isin(allowed).values
        r_, p_ = r_[sel], p_[sel]
        is_gap = r_["ticker"].isin(gap_earliest.index)
        if args.exclude_gap:
            okm = (~is_gap & (r_["close"] > cw.MIN_PRICE) &
                   (r_["market_cap"] >= cw.MIN_MARKET_CAP)).values
        else:
            okm = (is_gap | ((r_["close"] > cw.MIN_PRICE) &
                             (r_["market_cap"] >= cw.MIN_MARKET_CAP))).values
        r_, p_ = r_[okm], p_[okm]
        if len(p_) < args.max_rank:
            del bst; gc.collect(); continue
        score = bst.inplace_predict(featmat[p_])
        tr = truth[p_]                       # realized within-date rank
        good = np.isfinite(tr)
        ic = spearman(score[good], tr[good])
        order = np.argsort(-score, kind="stable")[:args.max_rank]
        rows_out.append({"tp": str(tp.date()), "ic": ic,
                         "n_cand": int(len(p_)),
                         "rank": list(r_["ticker"].astype(str).values[order])})
        del bst, score; gc.collect()
        if i % 15 == 0:
            print(f"  step {i}/{len(step_dates)} {tp.date()} "
                  f"({len(rows_out)} done)", flush=True)

    ics = np.array([r["ic"] for r in rows_out if np.isfinite(r["ic"])])
    print("\n" + "=" * 70)
    print(f"INFORMATION COEFFICIENT  [{tag}]")
    print("=" * 70)
    print(f"  windows                 : {len(ics)}")
    print(f"  mean IC                 : {ics.mean():+.4f}")
    print(f"  std / t-stat            : {ics.std(ddof=1):.4f} / "
          f"{ics.mean()/(ics.std(ddof=1)/np.sqrt(len(ics))):+.2f}")
    print(f"  share of windows IC > 0 : {(ics>0).mean():.1%}")
    early = np.array([r["ic"] for r in rows_out if r["tp"] < SPLIT and np.isfinite(r["ic"])])
    late = np.array([r["ic"] for r in rows_out if r["tp"] >= SPLIT and np.isfinite(r["ic"])])
    if len(early) > 5 and len(late) > 5:
        print(f"  2007-2019 ({len(early):>3} win)     : {early.mean():+.4f}")
        print(f"  2020-2026 ({len(late):>3} win)     : {late.mean():+.4f}")
    print("\n  ~0.03-0.06 is a normal working signal. >0.15 means look-ahead.")
    print("  For --mode placebo this MUST be ~0.000.")

    # ---- realize -----------------------------------------------------------
    segs = feat.groupby("ticker", observed=True)["date"].agg(["min", "max"])
    panel = SegmentedOHLCPanel(cw.PRICE_DIRS,
        {t: (str(t).split("__post")[0], r["min"], r["max"]) for t, r in segs.iterrows()})
    del segs; gc.collect()
    spy = pd.read_csv(DATA_DIR / "SPY.csv", parse_dates=["date"]).sort_values("date")
    spy = spy.reset_index(drop=True)

    W = []
    for rec in rows_out:
        tp = pd.Timestamp(rec["tp"])
        allowed = cw.allowed_universe_at(tp, current_universe, gap_earliest, "expanded")
        lo2 = int(np.searchsorted(dates_arr, np.datetime64(tp), "left"))
        hi2 = int(np.searchsorted(dates_arr, np.datetime64(tp), "right"))
        r_ = feat.iloc[lo2:hi2]
        r_ = r_[r_["ticker"].isin(allowed)]
        is_gap = r_["ticker"].isin(gap_earliest.index)
        if args.exclude_gap:
            r_ = r_[~is_gap & (r_["close"] > cw.MIN_PRICE) &
                    (r_["market_cap"] >= cw.MIN_MARKET_CAP)]
        else:
            r_ = r_[is_gap | ((r_["close"] > cw.MIN_PRICE) &
                              (r_["market_cap"] >= cw.MIN_MARKET_CAP))]
        f = spy[spy["date"] > tp]
        if r_.empty or f.empty:
            continue
        e = float(f.iloc[0]["open" if args.entry_at == "open" else "close"])
        i0 = 0 if args.entry_at == "open" else 1
        win = f.iloc[i0:i0 + FORWARD_WINDOW]
        if win.empty or e <= 0:
            continue
        lut = {}
        for t in r_["ticker"].astype(str).values:
            g = panel.get(t)
            if g is None:
                continue
            p = realize_position(g, tp, FORWARD_WINDOW, entry_lag=1,
                                 entry_at=args.entry_at, stop_pct=None, cost_bps=0.0)
            if p is not None:
                lut[t] = p["gross_return"]
        if len(lut) < args.max_rank:
            continue
        W.append({"tp": rec["tp"], "lut": lut, "rank": rec["rank"],
                  "spy": float(win["close"].iloc[-1]) / e - 1})

    per = TRADING_DAYS / FORWARD_WINDOW
    h = (args.cost_bps / 1e4) / 2.0
    rt = (1 - h) / (1 + h)

    def block(sub, name):
        if len(sub) < 10:
            return
        s = np.array([w["spy"] for w in sub])
        univ = np.array([np.mean(list(w["lut"].values())) for w in sub])
        print(f"\n  {name}  ({len(sub)} windows)   SPY ${np.prod(1+s)*10000:,.0f}   "
              f"universe {univ.mean()*100:.2f}%/window")
        print(f"    {'N':>4}{'arith%':>9}{'terminal':>11}{'Sharpe':>8}")
        for N in SIZES:
            recs = []
            for w in sub:
                pk = [t for t in w["rank"][:N] if t in w["lut"]]
                if not pk:
                    continue
                recs.append({"timepoint": w["tp"], "picks": pk,
                             "spy_return_pct": w["spy"] * 100,
                             "execution": {"gross_return_pct":
                                 float(np.mean([w["lut"][t] for t in pk])) * 100,
                                 "per_ticker_gross": {t: w["lut"][t] for t in pk}}})
            recs = apply_turnover_costs(recs, args.cost_bps)
            r = np.array([x["model_return_pct"] / 100
                          for x in sorted(recs, key=lambda q: q["timepoint"])])
            term = float(np.prod(1 + r) * 10000)
            vol = float(r.std(ddof=1) * np.sqrt(per))
            print(f"    {N:>4}{r.mean()*100:>9.2f}${term:>10,.0f}"
                  f"{r.mean()*per/vol:>8.2f}")

    print("\n" + "=" * 70)
    print(f"PORTFOLIOS  [{tag}]")
    print("=" * 70)
    block(W, "ALL")
    block([w for w in W if w["tp"] < SPLIT], "2007-2019")
    block([w for w in W if w["tp"] >= SPLIT], "2020-2026 (hold-out)")

    print("\nrank buckets, arith %/window (gross)")
    for a, b in [(0, 5), (5, 10), (10, 20), (20, 50)]:
        vals = [np.mean([w["lut"][t] for t in w["rank"][a:b] if t in w["lut"]]) for w in W]
        print(f"  rank {a+1:>2}-{b:<3} {np.mean(vals)*100:>7.2f}%")
    uu = np.mean([np.mean(list(w["lut"].values())) for w in W])
    print(f"  universe   {uu*100:>7.2f}%")

    json.dump({"tag": tag, "mode": args.mode, "embargo_mult": args.embargo_mult,
               "mean_ic": float(ics.mean()), "ic_t": float(
                   ics.mean() / (ics.std(ddof=1) / np.sqrt(len(ics)))),
               "n_windows": len(W)},
              open(OUT_DIR / f"validate_xsec_{tag}.json", "w"), indent=2)
    print(f"\nSaved -> {OUT_DIR / f'validate_xsec_{tag}.json'}")


if __name__ == "__main__":
    main()
