"""
Build a fixed recurrent operator from the MaleCNS connectome, and the
degree-matched control it has to be compared against.

Two functions carry the load:

  normalise_operator(W, sign)   signed, input-normalised sparse operator
  shuffle_postsynaptic(W, sign) the matched rewiring control

Everything else is selection: which bodies are in, which are Kenyon cells,
which are MBONs.

WHY NORMALISE BY POSTSYNAPTIC INPUT. Raw synapse counts span four orders of
magnitude and a neuron with 5,000 input synapses would otherwise dominate the
spectrum, saturating the network on the first timestep regardless of gain.
Dividing each incoming weight by the total input onto that neuron makes every
row of |W| sum to 1, so the operator's scale is set by topology rather than by
segmentation volume. This is nfly's convention and keeps results comparable to
other work on this graph.

WHY THE SHUFFLE IS THE ONLY CONTROL THAT MATTERS. A large sparse recurrent
operator is a good nonlinear feature expansion almost regardless of its
structure -- that is the whole premise of reservoir computing, and it is why
"the fly brain produced a signal" would be an uninteresting result on its own.
The question with content is whether THIS topology beats a random one with the
same degree sequence, the same weights and the same signs. shuffle_postsynaptic
permutes the postsynaptic endpoint of every edge: each neuron keeps its exact
out-degree, its outgoing weights and its transmitter sign, and only its targets
change. In-degree is preserved in distribution but not per-neuron, which is the
standard cheap-rewiring trade; if the pilot ever shows signal worth defending,
upgrade to a full degree-preserving double-edge swap before believing it.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import scipy.sparse as sp

# Excitatory / inhibitory from the presynaptic transmitter consensus. Matches
# nfly. Glutamate is the contestable one -- inhibitory here because the fly's
# GluCl receptors are chloride channels, but that is a modelling choice.
SIGN = {"acetylcholine": +1.0, "dopamine": +1.0, "serotonin": +1.0,
        "octopamine": +1.0, "tyramine": +1.0,
        "gaba": -1.0, "glutamate": -1.0, "histamine": -1.0}
DEFAULT_SIGN = +1.0

# Mushroom body cell classes, matched on type-name prefix. KC = Kenyon cells
# (the sparse expansion layer), MBON = output neurons (the readout), PAM/PPL =
# the dopaminergic clusters that teach it, APL/DPM = the large modulatory cells
# whose feedback inhibition is what enforces KC sparse coding. APL matters here
# for a mechanical reason as well as a biological one: it gives the network its
# own gain control, so calibration has something to push against.
MB_PREFIXES = r"(?i)^(KC|MBON|APL|DPM|PAM|PPL)"
KC_PREFIX = r"(?i)^KC"
MBON_PREFIX = r"(?i)^MBON"


def normalise_operator(W, sign_per_pre):
    """Signed, input-normalised CSR operator. row = post, col = pre."""
    W = W.tocoo()
    val = np.abs(W.data.astype(np.float64)) * sign_per_pre[W.col]
    tot = np.bincount(W.row, weights=np.abs(val), minlength=W.shape[0])
    val = val / np.maximum(tot[W.row], 1e-12)
    return sp.csr_matrix((val.astype(np.float32), (W.row, W.col)), shape=W.shape)


def shuffle_postsynaptic(W, sign_per_pre, seed=0):
    """Rewire targets, preserving each neuron's out-degree, outgoing weights
    and sign. Returns an UNNORMALISED matrix -- normalise it afterwards, so the
    control gets the same treatment the real graph does."""
    W = W.tocoo()
    rng = np.random.default_rng(seed)
    row = rng.permutation(W.row)
    return sp.coo_matrix((W.data.copy(), (row, W.col.copy())), shape=W.shape)


# ----------------------------------------------------------------------
# loading
# ----------------------------------------------------------------------
FILE_PREFIX = {"ann": "body-annotations", "nt": "body-neurotransmitters",
               "w": "connectome-weights"}


def _find(data_dir: Path, prefix: str) -> Path:
    hits = sorted(Path(data_dir).glob(f"{prefix}*.feather"))
    if not hits:
        raise SystemExit(f"no {prefix}*.feather in {data_dir} -- see "
                          f"bench_connectome.py --download")
    return hits[0]


def _col(df, names, what):
    for c in names:
        if c in df.columns:
            return c
    raise SystemExit(f"{what}: none of {names} present. Columns: {list(df.columns)}")


# The Janelia release is not internally consistent about what the body
# identifier is called: body-annotations uses `bodyId`, body-neurotransmitters
# uses `body`. Resolve it per table rather than assuming, and say which one was
# used -- a silently-wrong join key here would produce a fully populated,
# entirely wrong sign vector, which is the exact shape of bug this project
# keeps finding (every distribution check would pass).
BODY_COLS = ["bodyId", "body", "body_id", "bodyid", "bodyID"]


def body_col(df, what):
    return _col(df, BODY_COLS, what)


def load_tables(data_dir):
    data_dir = Path(data_dir)
    ann = pd.read_feather(_find(data_dir, FILE_PREFIX["ann"]))
    nt = pd.read_feather(_find(data_dir, FILE_PREFIX["nt"]))
    w = pd.read_feather(_find(data_dir, FILE_PREFIX["w"]))
    body_col(ann, "annotations")          # resolve or die, with the real list
    body_col(nt, "neurotransmitters")
    miss = [c for c in ("body_pre", "body_post", "weight") if c not in w.columns]
    if miss:
        raise SystemExit(f"weights: missing {miss}. Columns: {list(w.columns)}")
    return ann, nt, w


def schema_report(ann, nt, w):
    """Print every column of all three tables. Cheap, and it is the difference
    between fixing three name mismatches in one pass and finding them one crash
    at a time."""
    for name, df in (("body-annotations", ann), ("body-neurotransmitters", nt),
                     ("connectome-weights", w)):
        print(f"\n{name}  ({len(df):,} rows)")
        for c in df.columns:
            ex = df[c].dropna()
            ex = repr(ex.iloc[0])[:44] if len(ex) else "<all null>"
            print(f"    {c:<32} {str(df[c].dtype):<12} e.g. {ex}")


def select(ann, region="mushroom_body"):
    """Boolean mask over `ann` rows. BILATERAL -- no side filter, both
    hemispheres are kept, which roughly doubles the KC population for free and
    gives a built-in bug detector: two hemispheres receiving identical drive
    should produce near-identical MBON readouts."""
    sc = ann[_col(ann, ["superclass", "super_class", "class"], "annotations")] \
        .fillna("").astype(str).str.lower()
    if region == "full":
        return np.ones(len(ann), bool)
    if region == "central":
        return ~(sc.str.contains("optic") | sc.str.contains("visual")).to_numpy()
    if region == "mushroom_body":
        ty = ann[_col(ann, ["type", "cellType", "cell_type", "instance"],
                      "annotations")].fillna("").astype(str)
        return ty.str.match(MB_PREFIXES).to_numpy()
    raise ValueError(region)


def populations(ann, keep):
    """KC and MBON masks, indexed within the kept subgraph."""
    ty = ann.loc[keep, _col(ann, ["type", "cellType", "cell_type", "instance"],
                            "annotations")].fillna("").astype(str)
    return ty.str.match(KC_PREFIX).to_numpy(), ty.str.match(MBON_PREFIX).to_numpy()


# Minimum synapse count for an edge to be believed.
#
# The v1.0 flat connectome ships 151.8M body-to-body edges with a MEDIAN WEIGHT
# OF 1. A single detected synaptic contact between two segments is at or below
# the noise floor of automated synapse detection plus segmentation, and the
# published MaleCNS figure everyone quotes (~10.5M connections) is a thresholded
# graph, not this one. Connectomics convention is to trust edges from ~5
# synapses up; nothing below is a claim about the animal.
#
# This is the single most consequential knob in the whole build, because it
# changes what the operator IS -- at threshold 1 the mushroom body has ~226
# edges per neuron, which is not a sparse-coding layer, it is a dense one. Set
# it deliberately and report what it removes.
MIN_SYNAPSES = 5


def build(data_dir, region="mushroom_body", shuffle=False, seed=0, verbose=True,
          min_synapses=MIN_SYNAPSES, traced_only=True):
    """Returns (W_normalised, bodies, kc_mask, mbon_mask)."""
    ann, nt, w = load_tables(data_dir)
    keep = select(ann, region)
    if traced_only:
        # 44,877 of 211,577 bodies carry no superclass at all -- fragments and
        # unproofread segments. The 166,700-neuron figure in the literature is
        # the proofread set. Keeping fragments would pad the operator with
        # neurons that have no identity and, being poorly traced, mostly
        # spurious connectivity.
        st = ann[_col(ann, ["status", "statusLabel"], "annotations")].astype(str)
        traced = st.str.contains("raced", case=False, na=False).to_numpy()
        if verbose:
            print(f"  proofreading filter: {int((keep & traced).sum()):,} of "
                  f"{int(keep.sum()):,} selected bodies are traced")
        keep = keep & traced
    ann_body = body_col(ann, "annotations")
    bodies = ann.loc[keep, ann_body].to_numpy()
    if verbose:
        print(f"{region}: {len(bodies):,} of {len(ann):,} bodies")

    idx = pd.Series(np.arange(len(bodies)), index=bodies)
    e = w[w["body_pre"].isin(idx.index) & w["body_post"].isin(idx.index)]
    n_raw = len(e)
    if min_synapses > 1:
        e = e[e["weight"] >= min_synapses]
    pre = idx.reindex(e["body_pre"]).to_numpy()
    post = idx.reindex(e["body_post"]).to_numpy()
    if verbose:
        print(f"  edges: {n_raw:,} raw -> {len(e):,} at >={min_synapses} "
              f"synapses ({len(e)/max(n_raw,1):.1%} kept), "
              f"{len(e)/max(len(bodies),1):.0f} per neuron")

    nt_col = _col(nt, ["consensus_nt", "consensusNt", "nt", "predicted_nt"],
                  "neurotransmitters")
    nt_body = body_col(nt, "neurotransmitters")
    sgn_body = (nt.drop_duplicates(nt_body).set_index(nt_body)[nt_col]
                .astype(str).str.lower().map(SIGN).fillna(DEFAULT_SIGN))
    sign_per_node = sgn_body.reindex(bodies).fillna(DEFAULT_SIGN).to_numpy()
    if verbose:
        matched = int(sgn_body.reindex(bodies).notna().sum())
        print(f"  transmitter join: '{nt_body}' -> '{ann_body}', "
              f"{matched:,}/{len(bodies):,} bodies matched ({matched/len(bodies):.1%})")
        if matched < 0.5 * len(bodies):
            print("    WARNING: fewer than half the neurons got a transmitter "
                  "call. Every unmatched one defaults to EXCITATORY, so a bad "
                  "join key here silently removes most of the inhibition.")
        print(f"  inhibitory neurons: {int((sign_per_node < 0).sum()):,} "
              f"({(sign_per_node < 0).mean():.1%})")

    W = sp.coo_matrix((e["weight"].to_numpy(np.float64), (post, pre)),
                      shape=(len(bodies), len(bodies)))
    if shuffle:
        W = shuffle_postsynaptic(W, sign_per_node, seed=seed)
        if verbose:
            print(f"  MATCHED-SHUFFLE CONTROL (seed {seed})")
    Wn = normalise_operator(W, sign_per_node)
    kc, mbon = populations(ann, keep)
    if verbose:
        print(f"  Kenyon cells: {int(kc.sum()):,}   MBONs: {int(mbon.sum()):,}")
    return Wn, bodies, kc, mbon
