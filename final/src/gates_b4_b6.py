"""
Gates B4 (IC magnitude) and B6 (ablation robustness), in screen mode.

Why this run exists
-------------------
tail_null.py --gap-mode screen passed Gate B2 decisively: five consecutive
portfolio sizes at >= p95 against 10,000 matched random draws, on BOTH the
full sample and the 2020-2026 hold-out. Buckets are monotone (B3) and the
hold-out is stronger than the in-sample era (B5).

Implied IC from the tail excess is 0.02-0.05 in both eras, which is where a
working equity signal lives. But implied is not measured. Two gates are still
open and they are the two most capable of killing this:

  B4  measured IC must sit in [0.02, 0.10] with t > 3.
      Below 0.02 is noise dressed up by a handful of tail winners. Above 0.10
      is what the gap-ticker group artifact looked like before it was screened
      out (+0.135, which collapsed to -0.001 once those names were removed).

  B6  no single subgroup may carry more than ~60% of the effect.
      A result that evaporates when one cohort is removed is that cohort's
      artifact. This is exactly the test that killed the cross-sectional IC
      claim yesterday, so it gets applied to the surviving claim too.

Method
------
One retrain pass in screen mode, saving the FULL score vector per window
(~850 names x 117 windows) alongside each name's realized return, true
within-date rank, market cap, trailing volatility and gap flag. Everything
after that is arithmetic on the saved arrays, so the ablations and the
year-jackknife are free.

Ablations run post-hoc: a subgroup is removed from the candidate pool, the
top-N is re-taken from the surviving scores, and excess is measured against
the surviving universe. That answers "is the effect concentrated here"
without retraining once per cohort.

    python3 gates_b4_b6.py --gap-mode screen
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
from execution import SegmentedOHLCPanel, realize_position
import continuous_walkforward_pit as cw

TRADING_DAYS = 252.0
SPLIT = "2020-01-01"
SIZES = [5, 10, 20]
IC_LO, IC_HI, IC_T = 0.02, 0.10, 3.0
B6_RETAIN = 0.60


def xsec_rank(labels, dates_arr):
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
    ap.add_argument("--gap-mode", choices=["screen", "exclude", "exempt"], default="screen")
    ap.add_argument("--nthread", type=int, default=1)
    ap.add_argument("--start", default=cw.DEFAULT_START_DATE)
    ap.add_argument("--entry-at", default="open")
    args = ap.parse_args()

    params = dict(cw.XGB_PARAMS); params["nthread"] = args.nthread; params["seed"] = 0
    cols = [c for c in FUNDAMENTAL_FEATURE_COLS if c != "fundamentals_age_days"]
    numeric = ["close", "open", "market_cap"] + FEATURE_COLS + cols
    print(f"Loading panel...  [gap-mode={args.gap_mode}]")
    feat, n_before = cw.load_panel_prepared(
        OUT_DIR / "features_with_fundamentals_pit.parquet",
        numeric, FEATURE_COLS, FORWARD_WINDOW)
    print(f"  {len(feat):,} of {n_before:,} rows")
    feature_cols = FEATURE_COLS + cols
    gap_tickers = cw.load_gap_ticker_set()
    current_universe = set(map(str, feat["ticker"].unique())) - gap_tickers
    gap_earliest = cw.build_gap_validity(feat, gap_tickers)
    all_dates = feat["date"].drop_duplicates().sort_values().reset_index(drop=True)
    step_dates = cw.build_step_dates(all_dates, args.start, FORWARD_WINDOW)
    dates_arr = feat["date"].values
    target = xsec_rank(feat[TRADABLE_LABEL_COL].to_numpy(np.float32, copy=False), dates_arr)

    import tempfile, atexit, shutil
    td = tempfile.mkdtemp(prefix="gates_")
    atexit.register(lambda: shutil.rmtree(td, ignore_errors=True))
    mmp = os.path.join(td, "X.npy")
    arr = np.ascontiguousarray(feat[feature_cols].to_numpy(dtype=np.float32, copy=False))
    shape = arr.shape
    mm = np.memmap(mmp, dtype=np.float32, mode="w+", shape=shape)
    mm[:] = arr; mm.flush(); del arr, mm; gc.collect()
    featmat = np.memmap(mmp, dtype=np.float32, mode="r", shape=shape)
    keep = feat[["ticker", "date", "close", "market_cap", "volatility_60"]]
    del feat; gc.collect()

    def eligible(tp):
        allowed = cw.allowed_universe_at(tp, current_universe, gap_earliest, "expanded")
        lo = int(np.searchsorted(dates_arr, np.datetime64(tp), "left"))
        hi = int(np.searchsorted(dates_arr, np.datetime64(tp), "right"))
        rows = keep.iloc[lo:hi]; pos = np.arange(lo, hi)
        sel = rows["ticker"].isin(allowed).values
        rows, pos = rows[sel], pos[sel]
        is_gap = rows["ticker"].isin(gap_earliest.index)
        floor = (rows["close"] > cw.MIN_PRICE) & (rows["market_cap"] >= cw.MIN_MARKET_CAP)
        if args.gap_mode == "screen":
            k = floor.values
        elif args.gap_mode == "exclude":
            k = (~is_gap & floor).values
        else:
            k = (is_gap | floor).values
        return rows[k], pos[k], is_gap.values[k]

    segs = keep.groupby("ticker", observed=True)["date"].agg(["min", "max"])
    panel = SegmentedOHLCPanel(cw.PRICE_DIRS,
        {t: (str(t).split("__post")[0], r["min"], r["max"]) for t, r in segs.iterrows()})
    del segs; gc.collect()
    spy = pd.read_csv(DATA_DIR / "SPY.csv", parse_dates=["date"]).sort_values("date")
    spy = spy.reset_index(drop=True)

    W = []
    for i, tp in enumerate(step_dates, 1):
        idx = all_dates[all_dates == tp].index[0]
        if idx < FORWARD_WINDOW:
            continue
        hi = int(np.searchsorted(dates_arr,
                                 np.datetime64(all_dates.iloc[idx - FORWARD_WINDOW]), "right"))
        lab = target[:hi]; fin = np.isfinite(lab)
        if int(fin.sum()) < 300:
            continue
        rows, pos, isgap = eligible(tp)
        if len(pos) < 50:
            continue
        f = spy[spy["date"] > tp]
        if f.empty:
            continue
        e = float(f.iloc[0]["open" if args.entry_at == "open" else "close"])
        i0 = 0 if args.entry_at == "open" else 1
        win = f.iloc[i0:i0 + FORWARD_WINDOW]
        if win.empty or e <= 0:
            continue
        cut = np.percentile(lab[fin], cw.CUTOFF_PERCENTILE)
        y = (lab > cut).astype(np.int8)
        dtr = xgb.QuantileDMatrix(cw._ChunkIter(featmat, y, hi, mask=fin), max_bin=256)
        bst = xgb.train(params, dtr, num_boost_round=cw.XGB_ROUNDS)
        del dtr, y, lab, fin; gc.collect()
        score = bst.inplace_predict(featmat[pos])
        del bst; gc.collect()

        tk = rows["ticker"].astype(str).values
        rr, sc, mc, vol, gp, tr = [], [], [], [], [], []
        tru = target[pos]
        for j, t in enumerate(tk):
            g = panel.get(t)
            if g is None:
                continue
            p = realize_position(g, tp, FORWARD_WINDOW, entry_lag=1,
                                 entry_at=args.entry_at, stop_pct=None, cost_bps=0.0)
            if p is None or not np.isfinite(tru[j]):
                continue
            rr.append(p["gross_return"]); sc.append(score[j])
            mc.append(rows["market_cap"].values[j]); vol.append(rows["volatility_60"].values[j])
            gp.append(isgap[j]); tr.append(tru[j])
        if len(rr) < 50:
            continue
        W.append({"tp": str(tp.date()), "ret": np.array(rr), "score": np.array(sc),
                  "mcap": np.array(mc), "vol": np.array(vol),
                  "gap": np.array(gp, bool), "truth": np.array(tr),
                  "spy": float(win["close"].iloc[-1]) / e - 1})
        if i % 15 == 0:
            print(f"  step {i}/{len(step_dates)} {tp.date()} ({len(W)} kept)", flush=True)

    n = len(W)
    print(f"\n{n} windows retained; median pool {int(np.median([len(w['ret']) for w in W]))}")

    # ---------------- B4 : measured IC -------------------------------------
    ics = np.array([spearman(w["score"], w["truth"]) for w in W])
    ics = ics[np.isfinite(ics)]
    t_ic = ics.mean() / (ics.std(ddof=1) / np.sqrt(len(ics)))
    early = np.array([spearman(w["score"], w["truth"]) for w in W if w["tp"] < SPLIT])
    late = np.array([spearman(w["score"], w["truth"]) for w in W if w["tp"] >= SPLIT])
    early, late = early[np.isfinite(early)], late[np.isfinite(late)]
    print("\n" + "=" * 70)
    print("GATE B4 — measured information coefficient")
    print("=" * 70)
    print(f"  mean IC   {ics.mean():+.4f}   t {t_ic:+.2f}   "
          f"windows IC>0 {(ics > 0).mean():.1%}")
    print(f"  2007-2019 {early.mean():+.4f}      2020-2026 {late.mean():+.4f}")
    b4 = (IC_LO <= ics.mean() <= IC_HI) and t_ic > IC_T
    print(f"  требование: {IC_LO}-{IC_HI} and t>{IC_T}  ->  "
          f"{'PASS' if b4 else 'FAIL'}")
    if ics.mean() > IC_HI:
        print("  IC above the ceiling means a group artifact, not better skill --")
        print("  that is what +0.135 was before gap tickers were screened.")

    # ---------------- B6 : ablations ---------------------------------------
    def excess(sub, mask_fn=None):
        """mean top-N excess over the surviving universe, per window."""
        out = {N: [] for N in SIZES}
        for w in sub:
            m = np.ones(len(w["ret"]), bool) if mask_fn is None else mask_fn(w)
            if m.sum() < max(SIZES) + 5:
                continue
            r, s = w["ret"][m], w["score"][m]
            u = r.mean()
            order = np.argsort(-s, kind="stable")
            for N in SIZES:
                out[N].append(r[order[:N]].mean() - u)
        return {N: float(np.mean(v)) if v else float("nan") for N, v in out.items()}

    base = excess(W)
    print("\n" + "=" * 70)
    print("GATE B6 — ablation robustness (excess over surviving universe)")
    print("=" * 70)
    print(f"  {'ablation':<26}" + "".join(f"{'N='+str(N):>10}" for N in SIZES)
          + f"{'retained':>11}")
    print(f"  {'(baseline)':<26}" + "".join(f"{base[N]*100:>9.2f}%" for N in SIZES))

    def mcap_hi(w):
        return w["mcap"] < np.nanpercentile(w["mcap"], 90)

    def mcap_lo(w):
        return w["mcap"] > np.nanpercentile(w["mcap"], 10)

    def vol_hi(w):
        return w["vol"] < np.nanpercentile(w["vol"], 90)

    ablations = [("drop gap tickers", lambda w: ~w["gap"]),
                 ("drop top-decile mktcap", mcap_hi),
                 ("drop bottom-decile mktcap", mcap_lo),
                 ("drop top-decile vol", vol_hi)]
    b6_min = 1.0
    rows_out = {}
    for name, fn in ablations:
        e = excess(W, fn)
        ret = np.mean([e[N] / base[N] for N in SIZES if base[N] > 0])
        b6_min = min(b6_min, ret)
        rows_out[name] = {"excess": e, "retained": float(ret)}
        print(f"  {name:<26}" + "".join(f"{e[N]*100:>9.2f}%" for N in SIZES)
              + f"{ret*100:>10.0f}%")

    # year jackknife
    years = sorted({w["tp"][:4] for w in W})
    jk = []
    for y in years:
        sub = [w for w in W if not w["tp"].startswith(y)]
        if len(sub) < 20:
            continue
        e = excess(sub)
        jk.append((y, np.mean([e[N] / base[N] for N in SIZES if base[N] > 0])))
    worst_y, worst_v = min(jk, key=lambda kv: kv[1])
    print(f"\n  year jackknife: worst single year to drop is {worst_y}, "
          f"leaving {worst_v*100:.0f}% of the effect")
    b6 = (b6_min >= B6_RETAIN) and (worst_v >= B6_RETAIN)
    print(f"  требование: every ablation retains >= {B6_RETAIN*100:.0f}%  ->  "
          f"{'PASS' if b6 else 'FAIL'}")

    print("\n" + "-" * 70)
    print(f"  B4 {'PASS' if b4 else 'FAIL'}    B6 {'PASS' if b6 else 'FAIL'}")
    print("  With B1/B2/B3/B5 already passed, these two decide whether the")
    print("  cross-sectional result is believed. See claude/validation-gates.md.")
    print("-" * 70)

    json.dump({"gap_mode": args.gap_mode, "n_windows": n,
               "mean_ic": float(ics.mean()), "ic_t": float(t_ic),
               "ic_early": float(early.mean()), "ic_late": float(late.mean()),
               "b4_pass": bool(b4), "baseline_excess": base,
               "ablations": rows_out, "jackknife_worst": [worst_y, float(worst_v)],
               "b6_pass": bool(b6)},
              open(OUT_DIR / f"gates_b4_b6_{args.gap_mode}.json", "w"), indent=2)
    print(f"\nSaved -> {OUT_DIR / f'gates_b4_b6_{args.gap_mode}.json'}")


if __name__ == "__main__":
    main()
