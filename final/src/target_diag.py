"""
Round 10 (2026-09-08): two diagnostics on HOW the model is trained.

(1) TIES -- why two runs of the same model disagree
---------------------------------------------------
reconcile_ranks.py showed the walk-forward and rank_depth agree on only
4.42/5 names per window despite identical data, params and windows. No seed
is set anywhere and XGBoost defaults to a fixed one with no subsampling, so
randomness is not the explanation. The suspect is TIES: depth-3 trees over 24
features emit a small number of distinct leaf-value sums, so among ~850
candidates many share an identical predicted probability. np.argsort and
pandas.sort_values break those ties differently, and the top-5 changes.

If true, the top-5 is not a selection -- it is an arbitrary draw from a tied
group, and the two tie-breaks we happened to run returned $49,472 and $24,041.

(2) THE LABEL IS POOLED, NOT CROSS-SECTIONAL -- the bigger problem
------------------------------------------------------------------
continuous_walkforward_pit.py trains on:

    cutoff_val = np.percentile(train[label_col], CUTOFF_PERCENTILE)
    y_train    = (train[label_col] > cutoff_val).astype(int)

`train` is every (ticker, date) row up to the cutoff, so that percentile is
POOLED ACROSS ALL DATES. The label therefore asks:

    "is this stock's forward return in the top quartile of ALL stock-dates
     in history?"

In a rising 40-day window most names clear a pooled bar; in a falling one
almost none do. So the label is dominated by WHEN, not WHICH -- the model is
being trained largely to predict market direction, and only incidentally to
choose between contemporaneous names.

That single fact would explain most of what this project has measured:
beta 1.16, volatility_60 at 57% importance (realized vol is a regime proxy),
respectable AUC alongside MCC ~ 0, and a portfolio that behaves like levered
beta with up/down capture of 1.48x/1.16x.

The fix is to compute the label CROSS-SECTIONALLY -- rank or z-score forward
returns WITHIN each date -- so the target is "which of today's candidates will
outperform today's alternatives", which is the decision actually being made.

This script measures both. It needs no retraining for (2), and trains a
handful of windows for (1).

    python3 target_diag.py [--train-windows 6]
"""
import argparse
import gc

import numpy as np
import pandas as pd
import xgboost as xgb

from features import (FEATURE_COLS, FORWARD_WINDOW, TRADABLE_LABEL_COL, OUT_DIR)
from fundamentals_features_beta import FUNDAMENTAL_FEATURE_COLS
import continuous_walkforward_pit as cw


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--train-windows", type=int, default=6)
    ap.add_argument("--start", default=cw.DEFAULT_START_DATE)
    args = ap.parse_args()

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
    labels = feat[TRADABLE_LABEL_COL].to_numpy(dtype=np.float32, copy=False)

    # ---------------- (2) pooled vs cross-sectional label ------------------
    print("\n" + "=" * 74)
    print("(2) IS THE TRAINING LABEL POOLED OR CROSS-SECTIONAL?")
    print("=" * 74)
    fin_all = np.isfinite(labels)
    global_cut = np.percentile(labels[fin_all], cw.CUTOFF_PERCENTILE)
    print(f"pooled {cw.CUTOFF_PERCENTILE}th-percentile cutoff over the whole panel: "
          f"{global_cut*100:.2f}%")
    print("\nfraction of names clearing that POOLED bar, per window:")
    print(f"  {'window':<12}{'n':>7}{'% positive':>12}{'window mean ret':>18}")
    fracs, means = [], []
    for tp in step_dates:
        lo = int(np.searchsorted(dates_arr, np.datetime64(tp), "left"))
        hi = int(np.searchsorted(dates_arr, np.datetime64(tp), "right"))
        lab = labels[lo:hi]
        lab = lab[np.isfinite(lab)]
        if len(lab) < 50:
            continue
        fracs.append(float((lab > global_cut).mean()))
        means.append(float(lab.mean()))
    fracs, means = np.array(fracs), np.array(means)
    order = np.argsort(means)
    for i in list(order[:4]) + list(order[-4:]):
        pass
    print(f"  {'worst 4 windows':<12}{'':>7}{fracs[order[:4]].mean()*100:>11.1f}%"
          f"{means[order[:4]].mean()*100:>17.1f}%")
    print(f"  {'best 4 windows':<12}{'':>7}{fracs[order[-4:]].mean()*100:>11.1f}%"
          f"{means[order[-4:]].mean()*100:>17.1f}%")
    print(f"\n  across {len(fracs)} windows: %positive ranges "
          f"{fracs.min()*100:.1f}% to {fracs.max()*100:.1f}% "
          f"(a cross-sectional label would be ~25% every window)")
    print(f"  correlation(% positive, window mean return) = "
          f"{np.corrcoef(fracs, means)[0,1]:.3f}")
    print("\n  A correlation near 1.0 means the label is answering WHEN, not WHICH:")
    print("  the model is being trained mostly to predict market direction.")

    # ---------------- (1) ties in predicted probability --------------------
    print("\n" + "=" * 74)
    print("(1) HOW MANY DISTINCT SCORES DOES THE MODEL ACTUALLY EMIT?")
    print("=" * 74)
    import tempfile, atexit, shutil, os
    td = tempfile.mkdtemp(prefix="target_diag_")
    atexit.register(lambda: shutil.rmtree(td, ignore_errors=True))
    mm = os.path.join(td, "X.npy")
    arr = np.ascontiguousarray(feat[feature_cols].to_numpy(dtype=np.float32, copy=False))
    shape = arr.shape
    m = np.memmap(mm, dtype=np.float32, mode="w+", shape=shape)
    m[:] = arr; m.flush(); del arr, m; gc.collect()
    featmat = np.memmap(mm, dtype=np.float32, mode="r", shape=shape)
    feat = feat[["ticker", "date", "close", "market_cap"]]
    gc.collect()

    picked = [tp for i, tp in enumerate(step_dates)
              if i >= FORWARD_WINDOW][::max(1, len(step_dates)//args.train_windows)]
    picked = picked[:args.train_windows]
    print(f"  {'window':<12}{'cands':>7}{'distinct':>10}{'top5 tied?':>12}"
          f"{'#tied at 5th':>14}")
    for tp in picked:
        idx = all_dates[all_dates == tp].index[0]
        cutoff = all_dates.iloc[idx - FORWARD_WINDOW]
        hi = int(np.searchsorted(dates_arr, np.datetime64(cutoff), "right"))
        lab = labels[:hi]
        fin = np.isfinite(lab)
        if int(fin.sum()) < 300:
            continue
        cut = np.percentile(lab[fin], cw.CUTOFF_PERCENTILE)
        y = (lab > cut).astype(np.int8)
        dtr = xgb.QuantileDMatrix(cw._ChunkIter(featmat, y, hi, mask=fin), max_bin=256)
        bst = xgb.train(cw.XGB_PARAMS, dtr, num_boost_round=cw.XGB_ROUNDS)
        del dtr, y, lab, fin; gc.collect()

        allowed = cw.allowed_universe_at(tp, current_universe, gap_earliest, "expanded")
        lo2 = int(np.searchsorted(dates_arr, np.datetime64(tp), "left"))
        hi2 = int(np.searchsorted(dates_arr, np.datetime64(tp), "right"))
        rows = feat.iloc[lo2:hi2]
        pos = np.arange(lo2, hi2)
        sel = rows["ticker"].isin(allowed).values
        rows, pos = rows[sel], pos[sel]
        is_gap = rows["ticker"].isin(gap_earliest.index)
        ok = (is_gap | ((rows["close"] > cw.MIN_PRICE) &
                        (rows["market_cap"] >= cw.MIN_MARKET_CAP))).values
        pos = pos[ok]
        if len(pos) < 50:
            del bst; gc.collect(); continue
        p = bst.inplace_predict(featmat[pos])
        srt = np.sort(p)[::-1]
        fifth = srt[4]
        n_tied = int((p == fifth).sum())
        print(f"  {str(tp.date()):<12}{len(p):>7}{len(np.unique(p)):>10}"
              f"{('YES' if n_tied > 1 else 'no'):>12}{n_tied:>14}")
        del bst, p; gc.collect()
    print("\n  'distinct' far below 'cands' means most candidates share a score,")
    print("  so which 5 land on top is decided by the sort's tie-breaking, not")
    print("  by the model. A continuous model (GAM/ridge/rank objective) emits a")
    print("  distinct score per name and does not have this failure mode.")


if __name__ == "__main__":
    main()
