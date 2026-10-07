"""
WO-43 Step 2 walk-forward runner: one q75-style fit per trading day
2007-01-02..2019-12-31 (all 40 grid offsets), per run.

Same procedure as sweep/scorecache.run_signal for the cached q75 cell:
  cutoff = calendar[score - 40]; train rows = finite label, date <= cutoff,
  last 500k rows (date-sorted order of load_panel_prepared); label = 1 if the
  tradable 40d return > 75th pct of those rows; xgboost binary:logistic via
  QuantileDMatrix(_ChunkIter, max_bin=256), hist, nthread 1, seed 0; score
  every panel row on the score date (the PIT-universe flag is stored; the
  cached cell scored only PIT rows).
Asserted per fit: no training row's label exit date is after the score date.

Runs (pre-registered in final/models/2026-10-06-xgb-batch-retrain.md):
  arm0             24 price_fund cols, q75 params            (reproduces the cache)
  arm1             24 + 5 new cols, q75 params
  arm2             24 + 5 new cols, ARM2_PARAMS (the one retune)
  arm1_null{s}     arm1 with the 5 new cols shuffled within date, seed s=1..5
  arm2_null{s}     arm2 with the same shuffled matrix
Shuffle: each of the 5 columns permuted within each date among that column's
own finite rows (NaN rows stay NaN), independent permutation per column, all
five in one draw; rng = default_rng(1000 + s), dates ascending, columns in order.

Output: final/out/xgbretrain/scores/<run>/chunk_<k>.parquet (+ .json fit stats).
Resumable: an existing chunk is skipped.
Usage: python run_arms.py --runs arm0 [arm1 ...] [--workers 7] [--dates cache82]
"""
import argparse
import gc
import json
import os
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
SRC = HERE.parent
sys.path.insert(0, str(SRC))
STORE = Path.home() / ".cache" / "wo43_xgbretrain"
OUTD = HERE.parents[1] / "out" / "xgbretrain"
SCORES = OUTD / "scores"
H = 40
CAP = 500_000
START, END = np.datetime64("2007-01-02"), np.datetime64("2019-12-31")
CHUNK = int(os.environ.get("WO43_CHUNK", "41"))
NEW_J = list(range(24, 29))

Q75_PARAMS = {"max_depth": 3, "eta": 0.1, "rounds": 100}
# The one pre-registered retune (first principles, not searched): keep depth 3
# so 2-3-way interactions stay expressible; colsample_bynode 0.5 so the
# dominant volatility columns are absent from half the split searches and the
# weak columns get split opportunities; min_child_weight 100 (~500 rows per
# leaf at p(1-p)~0.19) and L2 lambda 10 against noise-fitting leaves.
ARM2_PARAMS = {"max_depth": 3, "eta": 0.1, "rounds": 100, "colsample_bynode": 0.5,
               "min_child_weight": 100.0, "lambda": 10.0}


def run_spec(run):
    if run == "arm0":
        return "X24", Q75_PARAMS
    if run == "arm1":
        return "X29", Q75_PARAMS
    if run == "arm2":
        return "X29", ARM2_PARAMS
    if run.startswith("arm1_null"):
        return f"X29_shuf{int(run[9:])}", Q75_PARAMS
    if run.startswith("arm2_null"):
        return f"X29_shuf{int(run[9:])}", ARM2_PARAMS
    raise ValueError(run)


def make_shuffled(seed):
    path = STORE / f"X29_shuf{seed}.npy"
    if path.exists():
        return
    X = np.load(STORE / "X29.npy")
    d = np.load(STORE / "dates.npy")
    rng = np.random.default_rng(1000 + seed)
    cut = np.flatnonzero(np.r_[True, d[1:] != d[:-1], True])
    for a, b in zip(cut[:-1], cut[1:]):
        for j in NEW_J:
            v = X[a:b, j]
            fin = np.flatnonzero(np.isfinite(v))
            if len(fin) > 1:
                v = v.copy()
                v[fin] = v[fin][rng.permutation(len(fin))]
                X[a:b, j] = v
    tmp = path.with_suffix(".tmp.npy")
    np.save(tmp, X)
    os.replace(tmp, path)


G = {}


def _init():
    import continuous_walkforward_pit as W
    G["W"] = W
    G["y"] = np.load(STORE / "y.npy", mmap_mode="r")
    G["dates"] = np.load(STORE / "dates.npy")
    G["exit"] = np.load(STORE / "exit.npy", mmap_mode="r")
    G["codes"] = np.load(STORE / "codes.npy", mmap_mode="r")
    G["in_pit"] = np.load(STORE / "in_pit.npy", mmap_mode="r")
    G["cal"] = np.unique(G["dates"])
    G["X"] = {}


def _X(name):
    if name not in G["X"]:
        G["X"][name] = np.load(STORE / f"{name}.npy", mmap_mode="r")
    return G["X"][name]


def fit_predict(X, y, hi, mask, X_te, params, want_stats):
    import xgboost as xgb
    W = G["W"]
    p = {"max_depth": int(params["max_depth"]), "eta": float(params["eta"]), "tree_method": "hist",
         "verbosity": 0, "nthread": 1, "seed": 0, "objective": "binary:logistic", "eval_metric": "logloss"}
    for k in ("colsample_bynode", "min_child_weight", "lambda"):
        if k in params:
            p[k] = params[k]
    dtr = xgb.QuantileDMatrix(W._ChunkIter(X, y, hi, mask=mask), max_bin=256)
    bst = xgb.train(p, dtr, num_boost_round=int(params["rounds"]))
    del dtr
    Xt = np.asarray(X_te)
    score = bst.inplace_predict(Xt).astype(np.float32)
    stats = None
    if want_stats:
        nf = X.shape[1]
        gain = bst.get_score(importance_type="total_gain")
        stats = {"gain": [float(gain.get(f"f{i}", 0.0)) for i in range(nf)]}
        if nf == 29:
            tdf = bst.trees_to_dataframe()
            sp = tdf[tdf["Feature"] != "Leaf"].copy()
            sp["fi"] = sp["Feature"].str[1:].astype(int)
            fid = dict(zip(sp["ID"], sp["fi"]))
            pairs_new_old = pairs_new_new = pairs_total = 0
            trees_new = set()
            for _, r in sp.iterrows():
                for ch in (r["Yes"], r["No"]):
                    if ch in fid:
                        a, b = r["fi"], fid[ch]
                        pairs_total += 1
                        na, nb = a >= 24, b >= 24
                        if na and nb:
                            pairs_new_new += 1
                        elif na or nb:
                            pairs_new_old += 1
                if r["fi"] >= 24:
                    trees_new.add(r["Tree"])
            stats.update({"pairs_total": pairs_total, "pairs_new_old": pairs_new_old,
                          "pairs_new_new": pairs_new_new, "trees_using_new": len(trees_new),
                          "splits_by_feature": np.bincount(sp["fi"].to_numpy(), minlength=nf).tolist()})
            if want_stats == "shap":
                c = bst.predict(xgb.DMatrix(Xt), pred_contribs=True)
                stats["mean_abs_shap"] = np.abs(c[:, :nf]).mean(axis=0).astype(float).tolist()
    del bst
    return score, stats


def do_task(task):
    run, k, dlist = task
    out = SCORES / run / f"chunk_{k:04d}.parquet"
    if out.exists():
        return run, k, "skip", 0.0
    t0 = time.time()
    xname, params = run_spec(run)
    X = _X(xname)
    y_all, dates, ex, cal = G["y"], G["dates"], G["exit"], G["cal"]
    recs, stats_all = [], {}
    real = run in ("arm1", "arm2")
    for tp in dlist:
        tp = np.datetime64(tp, "ns").astype(np.int64)
        idx = int(np.searchsorted(cal, tp))
        assert cal[idx] == tp
        cutoff = cal[idx - H]
        hi = int(np.searchsorted(dates, cutoff, "right"))
        lab = np.asarray(y_all[:hi])
        mask = np.isfinite(lab)
        n_sel = int(mask.sum())
        if n_sel > CAP:
            sel = np.flatnonzero(mask)
            mask[sel[:-CAP]] = False
        used = np.flatnonzero(mask)
        assert int(np.asarray(ex[:hi])[used].max()) <= tp, f"LEAK {run} {tp}"
        cut = float(np.percentile(lab[mask], 75))
        yb = (lab > cut).astype(np.float32)
        te_lo = int(np.searchsorted(dates, tp, "left"))
        te_hi = int(np.searchsorted(dates, tp, "right"))
        want = False
        if real:
            want = "shap" if idx % 20 == 0 else True
        score, st = fit_predict(X, yb, hi, mask, X[te_lo:te_hi], params, want)
        recs.append(pd.DataFrame({"date": np.full(te_hi - te_lo, tp).astype("datetime64[ns]"),
                                  "code": np.asarray(G["codes"][te_lo:te_hi]), "score": score,
                                  "in_pit": np.asarray(G["in_pit"][te_lo:te_hi])}))
        if st is not None:
            stats_all[str(pd.Timestamp(tp).date())] = st
        del lab, mask, yb
        gc.collect()
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".tmp.parquet")
    pd.concat(recs, ignore_index=True).to_parquet(tmp, index=False)
    if stats_all:
        out.with_suffix(".json").write_text(json.dumps(stats_all))
    os.replace(tmp, out)
    return run, k, "done", time.time() - t0


def score_dates(which):
    d = np.unique(np.load(STORE / "dates.npy")).astype("datetime64[ns]")
    d = d[(d >= START) & (d <= END)]
    if which == "cache82":
        c = pd.read_parquet("/Users/ggraham/pipe_dream/final/out/sweep/scores/"
                            "price_fund_h40_q75_trd_xgb_d3e01r100_expanding_cap500k_pit_s40.parquet",
                            columns=["timepoint"])["timepoint"].unique()
        c = pd.to_datetime(pd.Series(c))
        c = c[c < pd.Timestamp("2020-01-01")]
        d = np.array(sorted(c.to_numpy().astype("datetime64[ns]")))
    return d


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", nargs="+", required=True)
    ap.add_argument("--workers", type=int, default=7)
    ap.add_argument("--dates", default="all")
    a = ap.parse_args()
    global SCORES
    if a.dates != "all":
        SCORES = OUTD / f"scores_{a.dates}"
    for r in a.runs:
        if "null" in r:
            make_shuffled(int(r[9:]))
    d = score_dates(a.dates)
    tasks = []
    for r in a.runs:
        for k in range(0, len(d), CHUNK):
            tasks.append((r, k // CHUNK, [str(x) for x in d[k:k + CHUNK]]))
    print(f"[{time.strftime('%H:%M:%S')}] {len(tasks)} tasks, {len(d)} dates/run, runs {a.runs}", flush=True)
    import multiprocessing as mp
    ctx = mp.get_context("spawn")
    with ctx.Pool(a.workers, initializer=_init_with_scores, initargs=(str(SCORES),)) as pool:
        n = 0
        for run, k, st, el in pool.imap_unordered(do_task, tasks):
            n += 1
            print(f"[{time.strftime('%H:%M:%S')}] {n}/{len(tasks)} {run} chunk {k} {st} {el:.0f}s", flush=True)


def _init_with_scores(scores):
    global SCORES
    SCORES = Path(scores)
    _init()


if __name__ == "__main__":
    main()
