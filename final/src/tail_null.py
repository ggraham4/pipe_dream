"""
Gate B2 — does the top of the book beat a matched random draw?

Where this sits
---------------
validate2.py established:
  * placebo clean (IC -0.0047) -- the pipeline does not manufacture signal
  * causal vs centered repair identical -- that look-ahead was immaterial
  * excluding gap tickers drops IC from +0.1350 to -0.0013

That last one killed the cross-sectional IC claim: gap tickers are, by
construction, names that later left the index, they underperform, AND they
were exempt from the $2B/$10 floor every other candidate had to clear. The
model learned that group split. A large full-cross-section Spearman followed
from an eligibility asymmetry we built into the pool, not from skill.

One claim survived. With gap tickers removed, IC ~= 0 but the rank buckets
still fall 5.70 / 3.72 / 2.06 / 2.07 against a 1.88% universe. That is not a
contradiction -- Spearman over ~850 names is blind to whether the top 5 (0.6%
of the pool) are right. A tail effect is a legitimate thing to have. It just
needs a TAIL null, which is what this script is.

Gate B2: model top-N must reach >= p95 against 10,000 random draws of the SAME
N from the SAME eligible pool, at THREE OR MORE consecutive N. One N at p95
out of several tested is chance -- the expected maximum of 7 uniform draws is
about p87, which is how rank_depth.py's N=50 result got its shine.

Universe handling (--gap-mode)
------------------------------
  screen  (default) gap tickers face the SAME market_cap/price floor as
          everyone else. Names without fundamentals drop out rather than
          being waved through. This is the Gate A5 fix and the universe we
          would actually trade.
  exclude gap tickers dropped entirely. Cleanest ablation, but it throws away
          the survivorship correction, so it understates realistic risk.
  exempt  the legacy Round 7 behaviour, kept only to reproduce old numbers.

Reports ALL / 2007-2019 / 2020-2026 separately; the hold-out is what Gate B7
reads. Prints an explicit PASS/FAIL against B2 rather than leaving it to
interpretation.

    python3 tail_null.py --gap-mode screen --resume
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
SPLIT = "2020-01-01"
GATE_PCT = 95.0
GATE_RUN = 3          # consecutive sizes required


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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gap-mode", choices=["screen", "exclude", "exempt"],
                    default="screen")
    ap.add_argument("--draws", type=int, default=10000)
    ap.add_argument("--nthread", type=int, default=1)
    ap.add_argument("--cost-bps", type=float, default=5.0)
    ap.add_argument("--max-rank", type=int, default=50)
    ap.add_argument("--start", default=cw.DEFAULT_START_DATE)
    ap.add_argument("--entry-at", default="open")
    ap.add_argument("--resume", action="store_true")
    args = ap.parse_args()

    tag = f"tailnull_{args.gap_mode}"
    ranks_path = OUT_DIR / f"{tag}_ranks.json"
    params = dict(cw.XGB_PARAMS); params["nthread"] = args.nthread; params["seed"] = 0

    cols = [c for c in FUNDAMENTAL_FEATURE_COLS if c != "fundamentals_age_days"]
    numeric = ["close", "open", "market_cap"] + FEATURE_COLS + cols
    print(f"Loading panel...  [gap-mode={args.gap_mode}]")
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
    target = xsec_rank(raw, dates_arr)

    import tempfile, atexit, shutil
    td = tempfile.mkdtemp(prefix="tailnull_")
    atexit.register(lambda: shutil.rmtree(td, ignore_errors=True))
    mmp = os.path.join(td, "X.npy")
    arr = np.ascontiguousarray(feat[feature_cols].to_numpy(dtype=np.float32, copy=False))
    shape = arr.shape
    mm = np.memmap(mmp, dtype=np.float32, mode="w+", shape=shape)
    mm[:] = arr; mm.flush(); del arr, mm; gc.collect()
    featmat = np.memmap(mmp, dtype=np.float32, mode="r", shape=shape)
    feat = feat[["ticker", "date", "close", "market_cap"]]
    gc.collect()

    def eligible(tp):
        """Gate A5: in 'screen' mode EVERY candidate faces the same floor."""
        allowed = cw.allowed_universe_at(tp, current_universe, gap_earliest, "expanded")
        lo = int(np.searchsorted(dates_arr, np.datetime64(tp), "left"))
        hi = int(np.searchsorted(dates_arr, np.datetime64(tp), "right"))
        rows = feat.iloc[lo:hi]; pos = np.arange(lo, hi)
        sel = rows["ticker"].isin(allowed).values
        rows, pos = rows[sel], pos[sel]
        is_gap = rows["ticker"].isin(gap_earliest.index)
        floor = (rows["close"] > cw.MIN_PRICE) & (rows["market_cap"] >= cw.MIN_MARKET_CAP)
        if args.gap_mode == "screen":
            keep = floor.values
        elif args.gap_mode == "exclude":
            keep = (~is_gap & floor).values
        else:
            keep = (is_gap | floor).values
        return rows[keep], pos[keep]

    # ---- rank ---------------------------------------------------------------
    ranks = {}
    if args.resume and ranks_path.exists():
        ranks = json.load(open(ranks_path))
        print(f"resuming: {len(ranks)} windows ranked")
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
        lab = target[:hi]
        fin = np.isfinite(lab)
        if int(fin.sum()) < 300:
            continue
        rows, pos = eligible(tp)
        if len(pos) < args.max_rank:
            continue
        cut = np.percentile(lab[fin], cw.CUTOFF_PERCENTILE)
        y = (lab > cut).astype(np.int8)
        dtr = xgb.QuantileDMatrix(cw._ChunkIter(featmat, y, hi, mask=fin), max_bin=256)
        bst = xgb.train(params, dtr, num_boost_round=cw.XGB_ROUNDS)
        del dtr, y, lab, fin; gc.collect()
        score = bst.inplace_predict(featmat[pos])
        order = np.argsort(-score, kind="stable")[:args.max_rank]
        ranks[key] = list(rows["ticker"].astype(str).values[order])
        del bst, score; gc.collect()
        if i % 10 == 0:
            print(f"  step {i}/{len(step_dates)} {key} ({len(ranks)} ranked)", flush=True)
            json.dump(ranks, open(ranks_path, "w"))
    json.dump(ranks, open(ranks_path, "w"))
    print(f"ranked {len(ranks)} windows")

    # ---- realize ------------------------------------------------------------
    segs = feat.groupby("ticker", observed=True)["date"].agg(["min", "max"])
    panel = SegmentedOHLCPanel(cw.PRICE_DIRS,
        {t: (str(t).split("__post")[0], r["min"], r["max"]) for t, r in segs.iterrows()})
    del segs; gc.collect()
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

    per = TRADING_DAYS / FORWARD_WINDOW
    h = (args.cost_bps / 1e4) / 2.0
    rt = (1 - h) / (1 + h)
    rng = np.random.default_rng(0)

    def evaluate(sub, name):
        if len(sub) < 10:
            return {}
        s = np.array([w["spy"] for w in sub])
        univ = np.array([np.mean(list(w["lut"].values())) for w in sub])
        spy_t = float(np.prod(1 + s) * 10000)
        print(f"\n  {name}   {len(sub)} windows | SPY ${spy_t:,.0f} | "
              f"universe {univ.mean()*100:.2f}%/window | "
              f"median pool {int(np.median([len(w['lut']) for w in sub]))}")
        print(f"    {'N':>4}{'arith%':>9}{'terminal':>11}{'Sharpe':>8}"
              f"{'null p50':>11}{'pctile':>8}{'':>6}")
        res = {}
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
            d = np.zeros(args.draws)
            for w in sub:
                v = np.array(list(w["lut"].values()))
                idx = rng.integers(0, len(v), size=(args.draws, N))
                d += np.log1p((1 + v[idx].mean(axis=1)) * rt - 1)
            d = 10000 * np.exp(d)
            pct = float((d < term).mean() * 100)
            flag = "  <-p95" if pct >= GATE_PCT else ""
            print(f"    {N:>4}{r.mean()*100:>9.2f}${term:>10,.0f}"
                  f"{r.mean()*per/vol:>8.2f}${np.percentile(d,50):>10,.0f}"
                  f"{pct:>8.1f}{flag}")
            res[N] = {"arith": float(r.mean()), "terminal": term,
                      "sharpe": float(r.mean() * per / vol), "percentile": pct}
        return res

    print("\n" + "=" * 74)
    print(f"GATE B2 — TAIL NULL   [{tag}]   {args.draws:,} draws per size")
    print("=" * 74)
    all_r = evaluate(W, "ALL")
    evaluate([w for w in W if w["tp"] < SPLIT], "2007-2019")
    hold_r = evaluate([w for w in W if w["tp"] >= SPLIT], "2020-2026 HOLD-OUT")

    def longest_run(res):
        best = run = 0
        for N in SIZES:
            if res.get(N, {}).get("percentile", 0) >= GATE_PCT:
                run += 1; best = max(best, run)
            else:
                run = 0
        return best

    print("\n" + "-" * 74)
    for label, res in (("ALL", all_r), ("HOLD-OUT", hold_r)):
        if not res:
            continue
        run = longest_run(res)
        verdict = "PASS" if run >= GATE_RUN else "FAIL"
        print(f"  Gate B2 [{label:<8}]: longest run of consecutive N at >=p{GATE_PCT:.0f} "
              f"= {run}  (need {GATE_RUN})   -> {verdict}")
    print("-" * 74)
    print("  A tail effect that appears at one N and not its neighbours is noise.")
    print("  Buckets, IC magnitude, era stability and ablation are gates B3-B6;")
    print("  see claude/validation-gates.md.")

    print("\n  rank buckets, arith %/window (gross)")
    for a, b in [(0, 5), (5, 10), (10, 20), (20, 50)]:
        vals = [np.mean([w["lut"][t] for t in w["rank"][a:b] if t in w["lut"]]) for w in W]
        print(f"    rank {a+1:>2}-{b:<3} {np.mean(vals)*100:>7.2f}%")
    uu = np.mean([np.mean(list(w["lut"].values())) for w in W])
    print(f"    universe   {uu*100:>7.2f}%")

    json.dump({"tag": tag, "gap_mode": args.gap_mode, "draws": args.draws,
               "n_windows": len(W), "all": all_r, "holdout": hold_r},
              open(OUT_DIR / f"{tag}.json", "w"), indent=2)
    print(f"\nSaved -> {OUT_DIR / f'{tag}.json'}")


if __name__ == "__main__":
    main()
