"""
Step 0 of the fly-reservoir pilot: fetch MaleCNS, report what it actually is,
and MEASURE throughput on this machine so the pilot is sized from data rather
than from my arithmetic.

    python3 bench_connectome.py --data ~/malecns --download

WHAT THIS IS. The Janelia MaleCNS v1.0 connectome used as a RESERVOIR: a
recurrent network whose weights are fixed by biology and never trained. Input
is injected, the dynamics run for T steps, and a small ridge readout maps the
resulting state to a prediction. Only the readout learns.

WHAT THIS IS NOT. Not "the fly brain predicting stocks". A connectome is
connectivity, not a trained model; nothing in it has ever seen a price. The
honest hypothesis is narrow: does a large sparse recurrent operator with THIS
topology give a more useful nonlinear expansion of a price history than a
random operator with the same degree sequence, weights and signs? The
matched-shuffle control (--shuffle) is what makes that a question rather than
a light show.

Matrix construction, sign assignment, normalisation, region selection and the
shuffle all live in connectome.py and are IMPORTED here, not reimplemented. An
earlier version of this file carried its own copy -- the same drift that put
the live signal script on the wrong label basis for five days. A benchmark
that measures a different operator than the pilot runs is worse than none.

GETTING THE DATA (~1.15GB, no auth, primary source male-cns.janelia.org):
    body-annotations-*.feather        13 MB   bodyId, superclass, type, ...
    body-neurotransmitters-*.feather  42 MB   bodyId, consensus_nt
    connectome-weights-*.feather     1.1 GB   body_pre, body_post, weight
--download fetches exactly these three. NOT the HuggingFace mirror
(QuixiAI/MaleCNS), which packages the raw segmentation -- 88.4M bodies,
151.8M edges, fragments included -- and would need Janelia's proofreading
filter reproduced by hand first.
"""
import argparse
import time
import urllib.request
from pathlib import Path

import numpy as np

from connectome import (SIGN, DEFAULT_SIGN, load_tables, select, build,
                        populations, _col, schema_report)

DOWNLOAD_BASE = ("https://storage.googleapis.com/flyem-male-cns/v1.0/"
                 "connectome-data/flat-connectome")
DOWNLOAD_NAMES = ["body-annotations-male-cns-v1.0-minconf-0.5.feather",
                  "body-neurotransmitters-male-cns-v1.0.feather",
                  "connectome-weights-male-cns-v1.0-minconf-0.5.feather"]


def download(data_dir: Path):
    data_dir.mkdir(parents=True, exist_ok=True)
    for name in DOWNLOAD_NAMES:
        dst = data_dir / name
        if dst.exists():
            print(f"  have {name} ({dst.stat().st_size/1e6:.0f}MB)")
            continue
        print(f"  fetching {name} ...", flush=True)
        tmp = dst.with_suffix(".part")
        urllib.request.urlretrieve(f"{DOWNLOAD_BASE}/{name}", tmp)
        tmp.rename(dst)
        print(f"    -> {name} ({dst.stat().st_size/1e6:.0f}MB)")


def describe(ann, nt, w):
    schema_report(ann, nt, w)
    sc_col = _col(ann, ["superclass", "super_class", "class"], "annotations")
    nt_col = _col(nt, ["consensus_nt", "consensusNt", "nt", "predicted_nt"],
                  "neurotransmitters")
    print(f"\n--- what this connectome actually is ---")
    print(f"annotated bodies : {len(ann):,}")
    print(f"edges            : {len(w):,}")
    print(f"synapse weight   : median {w['weight'].median():.0f}, "
          f"mean {w['weight'].mean():.1f}, max {w['weight'].max():,.0f}")
    print(f"\nsuperclass breakdown (decides cost -- the optic lobes are most of")
    print(f"the network and take no direct input in a tabular-data run):")
    vc = ann[sc_col].fillna("<none>").value_counts()
    for k, v in vc.head(20).items():
        print(f"  {str(k):<34}{v:>8,}  ({v/len(ann):.1%})")
    if len(vc) > 20:
        print(f"  ... {len(vc)-20} more")
    print(f"\nneurotransmitter consensus -> sign:")
    for k, v in nt[nt_col].fillna("<none>").value_counts().head(12).items():
        print(f"  {str(k):<20}{v:>8,}   {SIGN.get(str(k).lower(), DEFAULT_SIGN):+.0f}")

    ty_col = _col(ann, ["type", "cellType", "cell_type", "instance"], "annotations")
    ty = ann[ty_col].fillna("").astype(str)
    print(f"\nmushroom body cell types (matched on '{ty_col}'):")
    for pre in ("KC", "MBON", "APL", "DPM", "PAM", "PPL"):
        n = int(ty.str.match(f"(?i)^{pre}").sum())
        print(f"  {pre:<6}{n:>8,}" + ("   <-- THIS BEING ~0 WOULD WRECK THE MB RUN"
                                       if pre in ("KC", "MBON") and n < 50 else ""))


def bench(W, batch, steps, device, n_in=None):
    """Time one window. Drive is injected on an input population of n_in cells,
    NOT on all N -- a dense (T, N, B) tensor is 19.4GB at full-CNS scale and is
    what made the first attempt at this die with 'Invalid buffer size'."""
    from reservoir import Reservoir
    res = Reservoir(W, device=device)
    n = W.shape[0]
    n_in = min(n_in or 4000, n)
    idx = np.arange(n_in)
    U = np.full((steps, n_in, batch), 0.01, dtype=np.float32)
    res.run(U, gain=1.0, in_idx=idx)                       # warm up
    t0 = time.time()
    h = res.run(U, gain=1.0, in_idx=idx)
    el = time.time() - t0
    assert np.isfinite(h).all(), "state went non-finite"
    return el, res.device


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True, type=Path)
    ap.add_argument("--download", action="store_true")
    ap.add_argument("--batch", type=int, default=1200, help="names per window")
    ap.add_argument("--steps", type=int, default=20, help="timesteps per sequence")
    ap.add_argument("--device", default=None)
    ap.add_argument("--min-synapses", type=int, default=5,
                    help="drop edges below this many synapses (median raw weight is 1)")
    ap.add_argument("--n-in", type=int, default=None,
                    help="size of the input population for the timing test")
    args = ap.parse_args()

    if args.download:
        download(args.data)
    ann, nt, w = load_tables(args.data)
    describe(ann, nt, w)

    for region in ("mushroom_body", "central", "full"):
        print(f"\n=== {region.upper()} ===")
        t0 = time.time()
        try:
            W, bodies, kc, mbon = build(args.data, region=region,
                                        min_synapses=args.min_synapses)
        except Exception as e:
            print(f"  BUILD FAILED: {type(e).__name__}: {e}")
            continue
        print(f"  built in {time.time()-t0:.0f}s, nnz = {W.nnz:,}")
        if W.shape[0] < 50:
            print("  too small to benchmark -- check the selection")
            continue
        try:
            el, dev = bench(W, args.batch, args.steps, args.device, args.n_in)
        except Exception as e:
            print(f"  BENCH FAILED: {type(e).__name__}: {e}")
            continue
        print(f"  one window ({args.batch} names x {args.steps} steps) on "
              f"{dev}: {el:.2f}s")
        print(f"  -> 82-window nomination era      : {el*82/60:>8.1f} min")
        print(f"  -> same + matched-shuffle control: {el*164/60:>8.1f} min")
        print(f"  -> full 124-window backtest      : {el*124/3600:>8.2f} h")
        del W

    print("\nPaste this back and I will size the run from it.")


if __name__ == "__main__":
    main()
