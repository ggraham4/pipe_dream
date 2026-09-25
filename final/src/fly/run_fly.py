"""
Run the connectome reservoir over the backtest and emit a score cache the
existing sweep machinery can grade.

    python3 run_fly.py --data ~/malecns --region mushroom_body
    python3 run_fly.py --data ~/malecns --region mushroom_body --shuffle
    python3 run_fly.py --data ~/malecns --region full

Writes out/sweep/scores/<cell_id>.parquet in EXACTLY the schema every other
cell uses, so `feature_ic`, the construction-matched nulls, leave-one-year-out
and cmd_live all work on it unchanged. That is deliberate: a new model that
brings its own evaluation code is a model grading its own homework. Also writes
out/fly/<cell_id>_pca.parquet -- the reservoir state compressed to a handful of
components, for feeding the existing XGBoost as extra columns.

THE READOUT IS THE ONLY THING THAT LEARNS, AND IT IS FIT WALK-FORWARD.
Fixed recurrent weights do not make this safe on their own. A linear readout
over hundreds or thousands of neurons is a regression with enormous p, and
fitting it once over all history would be look-ahead -- a Gate A failure, not a
Gate B one. At each rebalance date the readout sees only windows whose forward
return had already RESOLVED by that date (timepoint + horizon <= now), which is
strictly stronger than "earlier windows": a window from 20 trading days ago has
not finished yet and its label does not exist.

The reservoir itself is computed ONCE and reused by every fold, because nothing
about it depends on the data. That is what makes doing this correctly nearly
free.
"""
import argparse
import json
import time
from pathlib import Path

import numpy as np
import pandas as pd

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from features import FEATURE_COLS, TRADABLE_LABEL_COL, OUT_DIR   # noqa: E402
from fundamentals_features_beta import FUNDAMENTAL_FEATURE_COLS  # noqa: E402
from connectome import build, _col, load_tables, select           # noqa: E402
from encode import PanelEncoder, ClawProjection                   # noqa: E402
from reservoir import Reservoir                                   # noqa: E402

PANEL = OUT_DIR / "features_with_fundamentals_sharadar_pit.parquet"
SCORES_DIR = OUT_DIR / "sweep" / "scores"
FLY_DIR = OUT_DIR / "fly"
CARRY = ["close", "market_cap", "volatility_20", "volatility_60"]
HORIZON = 40


def readout_mask(data_dir, region, mbon):
    """Which neurons the ridge sees.

    Mushroom body -> MBONs. Not a convenience: MBONs are the mushroom body's
    entire output, ~97 cells carrying the learned valence the circuit computes,
    so reading there is reading where the animal reads.

    Full/central -> descending and motor neurons, following nfly. A far larger
    readout (~2,100), which is why the ridge penalty matters more there.
    """
    if region == "mushroom_body":
        return mbon
    ann, _, _ = load_tables(data_dir)
    keep = select(ann, region)
    st = ann[_col(ann, ["status", "statusLabel"], "annotations")].astype(str)
    keep = keep & st.str.contains("raced", case=False, na=False).to_numpy()
    sc = ann.loc[keep, _col(ann, ["superclass", "super_class", "class"],
                            "annotations")].fillna("").astype(str).str.lower()
    return (sc.str.contains("descending") | sc.str.contains("motor")).to_numpy()


def input_mask(data_dir, region, kc):
    """Where drive is injected. MB -> Kenyon cells, standing in for the
    projection-neuron input that lives outside the selection. Otherwise the
    sensory populations."""
    if region == "mushroom_body":
        return kc
    ann, _, _ = load_tables(data_dir)
    keep = select(ann, region)
    st = ann[_col(ann, ["status", "statusLabel"], "annotations")].astype(str)
    keep = keep & st.str.contains("raced", case=False, na=False).to_numpy()
    sc = ann.loc[keep, _col(ann, ["superclass", "super_class", "class"],
                            "annotations")].fillna("").astype(str).str.lower()
    return sc.str.contains("sensory").to_numpy()


def ridge_fit_predict(Xtr, ytr, Xte, alpha):
    """Closed-form ridge with training-only standardisation.

    Standardising on training rows only is not fussiness. The readout
    population's scale drifts with market volatility, so using all-sample
    statistics would leak the test period's volatility regime into the fit
    through the back door, which is the sort of leak that shows up as a
    suspiciously good result and no obvious bug.
    """
    mu, sd = Xtr.mean(0), Xtr.std(0)
    sd = np.where(sd > 1e-9, sd, 1.0)
    A = (Xtr - mu) / sd
    B = (Xte - mu) / sd
    ym = ytr.mean()
    G = A.T @ A + alpha * np.eye(A.shape[1], dtype=np.float64)
    w = np.linalg.solve(G, A.T @ (ytr - ym))
    return B @ w + ym


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True, type=Path)
    ap.add_argument("--region", default="mushroom_body",
                    choices=["mushroom_body", "central", "full"])
    ap.add_argument("--shuffle", action="store_true",
                    help="matched-shuffle control: same degrees, weights and "
                         "signs, rewired targets")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--steps", type=int, default=20)
    ap.add_argument("--leak", type=float, default=0.1,
                    help="alpha. State is an EMA with time constant ~1/alpha "
                         "steps; 0.1 gives tau=10 over a 20-day window, 0.2 "
                         "discards most of the first half")
    ap.add_argument("--taps", default="9,14,19",
                    help="timesteps (0-based) to read the state at. Reading "
                         "only the endpoint throws away the trajectory the "
                         "recurrence was built to capture")
    ap.add_argument("--no-reservoir", action="store_true",
                    help="BASELINE CONTROL: skip the connectome entirely and "
                         "hand the 24 z-scored features straight to the same "
                         "walk-forward ridge. If this matches the fly's IC, "
                         "the whole reservoir contributes nothing and what is "
                         "being measured is the readout, not the network")
    ap.add_argument("--scramble-time", action="store_true",
                    help="ORDER CONTROL: independently permute each name's "
                         "timesteps. Preserves the multiset of daily values "
                         "exactly, destroys their order. If this scores the "
                         "same as the ordered run, the network is not using "
                         "sequence information and the whole premise fails")
    ap.add_argument("--claws", type=int, default=6)
    ap.add_argument("--kc-target", type=float, default=0.06,
                    help="fraction of Kenyon cells responding above rest")
    ap.add_argument("--alpha", type=float, default=100.0, help="ridge penalty")
    ap.add_argument("--min-synapses", type=int, default=5)
    ap.add_argument("--chunk", type=int, default=400, help="names per forward pass")
    ap.add_argument("--n-pca", type=int, default=20)
    ap.add_argument("--device", default=None)
    ap.add_argument("--limit-windows", type=int, default=0)
    args = ap.parse_args()

    bits = ["none"] if args.no_reservoir else [args.region]
    if args.shuffle and not args.no_reservoir:
        bits.append("shuf")
    if args.scramble_time:
        bits.append("scram")
    tag = f"fly_{'_'.join(bits)}_T{args.steps}_s{args.seed}"
    print(f"cell id: {tag}")

    # ---- connectome -----------------------------------------------------
    if args.no_reservoir:
        # No network at all. The features go to the ridge exactly as the
        # reservoir would have received them -- same z-scoring, same window
        # assembly, same walk-forward fit, same target. The ONLY thing removed
        # is the nonlinear recurrent expansion, which is precisely what makes
        # this the right control: any IC it retains is IC the fly never earned.
        print("  BASELINE: no reservoir, ridge on the z-scored features")
        W = kc = mbon = None
        in_idx = out_idx = None
        res = gain = None
    else:
        W, bodies, kc, mbon = build(args.data, region=args.region,
                                    shuffle=args.shuffle, seed=args.seed,
                                    min_synapses=args.min_synapses)
        in_mask = input_mask(args.data, args.region, kc)
        out_mask = readout_mask(args.data, args.region, mbon)
        in_idx = np.flatnonzero(in_mask)
        out_idx = np.flatnonzero(out_mask)
        print(f"  input population {len(in_idx):,}   readout "
              f"population {len(out_idx):,}")
        if len(out_idx) < 5:
            raise SystemExit("readout population too small -- check selection")
        res = Reservoir(W, alpha=args.leak, device=args.device)
    taps = sorted({int(t) for t in args.taps.split(",") if t.strip() != ""})
    taps = [t for t in taps if 0 <= t < args.steps] or [args.steps - 1]
    if res is not None:
        print(f"  device {res.device}, leak {args.leak} "
              f"(tau~{1/args.leak:.0f} of {args.steps} steps), taps at {taps}")

    # ---- panel + windows -------------------------------------------------
    print(f"loading {PANEL.name} ...", flush=True)
    t0 = time.time()
    # FEATURE_COLS is the 12 PRICE columns only. The fundamentals live in
    # FUNDAMENTAL_FEATURE_COLS, and the first run silently dropped all six the
    # encoder wanted (pe/pb/ps ratios, debt_to_equity, roe, roa) because they
    # were never read off disk -- the encoder reported it, which is the only
    # reason it was caught. Without them the fly is a price-only model being
    # compared against a price+fundamentals one.
    fund = [c for c in FUNDAMENTAL_FEATURE_COLS if c != "fundamentals_age_days"]
    cols = list(dict.fromkeys(["ticker", "date", TRADABLE_LABEL_COL]
                              + FEATURE_COLS + fund + CARRY))
    have = set(pd.read_parquet(PANEL, columns=["ticker"]).columns) if False else None
    import pyarrow.parquet as _pq
    present = set(_pq.ParquetFile(PANEL).schema_arrow.names)
    missing = [c for c in cols if c not in present]
    if missing:
        print(f"  NOT IN PANEL, dropped: {missing}")
    panel = pd.read_parquet(PANEL, columns=[c for c in cols if c in present])
    # The pipeline's own filter: COMPLETE PRICE FEATURES only. Fundamentals are
    # allowed to be NaN -- they are for a large minority of names, and the
    # deployed model lets XGBoost handle that natively. Here a NaN fundamental
    # z-scores to 0.0, i.e. "typical", which is the honest encoding of "not
    # reported" for a cell that has to receive some number.
    panel = panel.dropna(subset=FEATURE_COLS)
    print(f"  {len(panel):,} complete-feature rows in {time.time()-t0:.0f}s")

    ref = sorted(SCORES_DIR.glob("price_fund_h40_q75_*.parquet"))
    if not ref:
        raise SystemExit(f"no reference score cache in {SCORES_DIR} to take the "
                          f"window grid from")
    tps = np.sort(pd.read_parquet(ref[0], columns=["timepoint"])
                  ["timepoint"].unique())
    if args.limit_windows:
        tps = tps[:args.limit_windows]
    print(f"  {len(tps)} windows, {pd.Timestamp(tps[0]).date()} .. "
          f"{pd.Timestamp(tps[-1]).date()}  (grid from {ref[0].name})")

    enc = PanelEncoder(panel)
    proj = None
    if not args.no_reservoir:
        proj = ClawProjection(len(in_idx), enc.n_seq, enc.n_static,
                              claws=args.claws, seed=args.seed)
        print(f"  projection: {proj.claws} claws of {enc.n_seq + enc.n_static}, "
              f"{proj.n_no_seq:,} cells ({proj.n_no_seq/proj.n_in:.1%}) slow-only")

    by_date = {d: g for d, g in panel.groupby("date", observed=True)}

    # ---- gain calibration, on the EARLIEST window only -------------------
    # Calibrating on the whole sample would fit a parameter against data the
    # model is later scored on. One number, an activity statistic rather than a
    # return -- but Gate A does not have a size exemption.
    if args.no_reservoir:
        gain = 0.0
    else:
        d0 = by_date[pd.Timestamp(tps[0])]
        names0, Z0, S0 = enc.window(d0["ticker"].tolist(), tps[0], args.steps)
        if not len(names0):
            raise SystemExit("no names with a full history at the first window")
        U0 = proj.drive(Z0[:, :min(200, len(names0))], S0[:min(200, len(names0))])
        kc_local = kc if args.region == "mushroom_body" else in_mask
        gain = res.calibrate_gain(U0, kc_local, target=args.kc_target,
                                  in_idx=in_idx)

    # ---- run the reservoir ------------------------------------------------
    recs, t0 = [], time.time()
    for i, tp in enumerate(tps, 1):
        d = by_date.get(pd.Timestamp(tp))
        if d is None:
            continue
        names, Z, S = enc.window(d["ticker"].tolist(), tp, args.steps)
        if len(names) < 50:
            continue
        if args.scramble_time:
            # Permute timesteps independently per name. The multiset of daily
            # values each name contributes is untouched -- only their order
            # changes -- so any performance difference is attributable to
            # sequence structure and to nothing else.
            rng_s = np.random.default_rng(abs(hash((str(tp), args.seed))) % 2**32)
            perm = np.argsort(rng_s.random((Z.shape[1], Z.shape[0])), axis=1)
            Z = np.take_along_axis(Z.transpose(1, 0, 2),
                                   perm[:, :, None], axis=1).transpose(1, 0, 2)
        if args.no_reservoir:
            # The same information the reservoir is handed, flattened: each
            # name's sequence at the readout taps plus its static block. Not
            # the full 20-day history -- the taps, so the ridge sees exactly
            # the timesteps the fly's readout sees and no more.
            R = np.concatenate([Z[taps].transpose(1, 0, 2).reshape(len(names), -1),
                                S], axis=1).astype(np.float32)
        else:
            R = np.empty((len(names), len(out_idx) * len(taps)), dtype=np.float32)
            for lo in range(0, len(names), args.chunk):
                hi = min(lo + args.chunk, len(names))
                U = proj.drive(Z[:, lo:hi], S[lo:hi])
                r = res.response(U, gain=gain, in_idx=in_idx, taps=taps)
                R[lo:hi] = r[:, out_idx, :].transpose(2, 0, 1).reshape(hi - lo, -1)
        sub = d[d["ticker"].isin(names)].set_index("ticker").reindex(names)
        recs.append({"tp": pd.Timestamp(tp), "names": np.asarray(names), "R": R,
                     "y": sub[TRADABLE_LABEL_COL].to_numpy(np.float64),
                     "carry": {c: sub[c].to_numpy(np.float32) for c in CARRY}})
        if i % 10 == 0 or i == len(tps):
            print(f"  [{i}/{len(tps)}] {pd.Timestamp(tp).date()} "
                  f"{len(names)} names, {time.time()-t0:.0f}s", flush=True)
    print(f"reservoir done in {time.time()-t0:.0f}s over {len(recs)} windows")

    # ---- walk-forward ridge ----------------------------------------------
    # Target is the within-date percentile rank of the tradable forward return:
    # continuous (a ridge wants that), cross-sectional (the only thing a name
    # picker can act on), and bounded (so one 2008 window cannot dominate the
    # normal equations).
    for r in recs:
        y = r["y"]
        ok = np.isfinite(y)
        rk = np.full(len(y), np.nan)
        if ok.sum() > 1:
            rk[ok] = pd.Series(y[ok]).rank(pct=True).to_numpy()
        r["rank"] = rk

    out = []
    n_fit = 0
    for i, r in enumerate(recs):
        cutoff = r["tp"] - pd.Timedelta(days=int(HORIZON * 1.4523))
        tr = [q for q in recs[:i] if q["tp"] <= cutoff and np.isfinite(q["rank"]).any()]
        if len(tr) < 3:
            continue
        Xtr = np.concatenate([q["R"][np.isfinite(q["rank"])] for q in tr])
        ytr = np.concatenate([q["rank"][np.isfinite(q["rank"])] for q in tr])
        s = ridge_fit_predict(Xtr.astype(np.float64), ytr,
                              r["R"].astype(np.float64), args.alpha)
        n_fit += 1
        rec = pd.DataFrame({"timepoint": r["tp"], "ticker": r["names"],
                            "score": s.astype(np.float32)})
        for c, v in r["carry"].items():
            rec[c] = v
        out.append(rec)
    if not out:
        raise SystemExit("no window had enough resolved history to fit a readout")
    scores = pd.concat(out, ignore_index=True)
    SCORES_DIR.mkdir(parents=True, exist_ok=True)
    scores.to_parquet(SCORES_DIR / f"{tag}.parquet", index=False)
    meta = {"cell_id": tag,
            "config": {"features": f"fly_{args.region}", "horizon": HORIZON,
                       "label": "xrank", "label_basis": "tradable",
                       "model": "reservoir_ridge", "depth": 0, "eta": 0.0,
                       "rounds": 0, "train": "expanding", "train_cap": 0,
                       "universe": "pit", "cap_tier": "all", "step": HORIZON,
                       "seed": args.seed},
            "n_timepoints": int(scores["timepoint"].nunique()),
            "n_rows": int(len(scores)),
            "feature_cols": ([f"seq_t{t}_{c}" for t in taps for c in enc.seq_cols]
                             + list(enc.static_cols)) if args.no_reservoir else
                            [f"readout_t{t}_{i}" for t in taps
                             for i in range(len(out_idx))],
            "fly": {"region": "none" if args.no_reservoir else args.region,
                    "no_reservoir": bool(args.no_reservoir),
                    "shuffled": bool(args.shuffle) and not args.no_reservoir,
                    "n_neurons": 0 if W is None else int(W.shape[0]),
                    "nnz": 0 if W is None else int(W.nnz),
                    "min_synapses": args.min_synapses,
                    "n_input": 0 if in_idx is None else int(len(in_idx)),
                    "n_readout": 0 if out_idx is None else int(len(out_idx)),
                    "steps": args.steps,
                    "claws": 0 if proj is None else proj.claws,
                    "leak": args.leak, "taps": taps,
                    "scrambled_time": bool(args.scramble_time),
                    "gain": float(gain or 0.0), "kc_target": args.kc_target,
                    "ridge_alpha": args.alpha, "windows_fit": n_fit}}
    (SCORES_DIR / f"{tag}.json").write_text(json.dumps(meta, indent=2))
    print(f"\nwrote {SCORES_DIR / f'{tag}.parquet'} "
          f"({len(scores):,} rows, {n_fit} fitted windows)")

    # ---- readout B: state compressed for the existing XGBoost -------------
    # PCA basis is fit on the FIRST THIRD of windows only and then frozen, for
    # the same reason the ridge is walk-forward: a basis fit on all windows is
    # a projection chosen with knowledge of the whole sample.
    n_pca = min(args.n_pca, recs[0]["R"].shape[1] - 1)
    k = max(3, len(recs) // 3)
    basis_rows = np.concatenate([r["R"] for r in recs[:k]]).astype(np.float64)
    mu = basis_rows.mean(0)
    _, _, Vt = np.linalg.svd(basis_rows - mu, full_matrices=False)
    V = Vt[:n_pca].T
    FLY_DIR.mkdir(parents=True, exist_ok=True)
    pca = pd.concat([pd.DataFrame(
        (r["R"].astype(np.float64) - mu) @ V,
        columns=[f"fly_pc{j}" for j in range(V.shape[1])]).assign(
            timepoint=r["tp"], ticker=r["names"]) for r in recs],
        ignore_index=True)
    pca.to_parquet(FLY_DIR / f"{tag}_pca.parquet", index=False)
    print(f"wrote {FLY_DIR / f'{tag}_pca.parquet'} "
          f"({V.shape[1]} components, basis from the first {k} windows)")

    print(f"\nGrade it with the machinery that already exists, e.g.\n"
          f"  cd {Path(__file__).resolve().parents[1]}\n"
          f"  python3 -m sweep.cli live --cells <grid-with-{tag}> --era nominate")


if __name__ == "__main__":
    main()
