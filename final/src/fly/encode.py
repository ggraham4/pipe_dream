"""
Turn a name's price history into drive on the input population.

THE PROJECTION IS SPARSE, AND THAT IS THE POINT. Each input cell samples a
handful of features rather than all of them, mirroring the ~6 claws through
which a Kenyon cell samples projection-neuron input. A dense random projection
would work as a reservoir input too, but sparse random sampling into a large
layer is precisely the motif the mushroom body uses to make an expanded,
decorrelated code, and it is the part of the circuit worth borrowing. It is
also better conditioned: dense projection into 4,000 cells makes every cell a
near-copy of the population mean.

WHAT VARIES OVER TIME AND WHAT DOES NOT. A recurrent network earns its cost
only if the input is a sequence, so the daily quantities arrive one trading day
per timestep and the slow ones are held as a constant bias:

    u[t] = P_seq @ z[t]  +  P_static @ s

z[t] is day t's return/volume/volatility; s is fundamentals and the 252-day
positional features, which do not meaningfully move within a 20-day window.

EVERY INPUT IS CROSS-SECTIONALLY Z-SCORED PER DATE before projection. Two
reasons, and the second matters more. It keeps the drive in a fixed range so a
single gain calibration holds across two decades of changing volatility. And it
makes the drive a RELATIVE quantity -- "how does this name compare to the
others today" -- which is the only thing a cross-sectional selector can act on
anyway, and which strips the market-wide component that the model has no way to
trade. Clipping at +/-5 sd stops one 2008 outlier from setting the gain for the
whole run.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import scipy.sparse as sp

# ---------------------------------------------------------------------------
# WHICH COLUMNS GO IN, AND WHY THIS IS DERIVED RATHER THAN TYPED OUT.
#
# The fly must see the SAME 24 columns the deployed model sees, or a comparison
# between them is measuring the feature set, not the architecture. The first
# version of this file hand-listed 18 of them and silently dropped six
# fundamentals -- including rnd_intensity, the strongest single feature Round 13
# found before sector-neutralisation removed it. Nothing failed; the encoder
# printed a line about absent columns and the run continued.
#
# So the split is now DERIVED from the same constants the production model
# imports. SEQ_COLS is the only judgement call: which features carry meaningful
# day-to-day variation and therefore deserve a timestep of their own. Everything
# else in the deployed feature set is slow -- quarterly fundamentals, 252-day
# positional measures -- and enters as a constant bias across the window.
# Add a column to features.py or fundamentals_features_beta.py and it arrives
# here automatically, on the static side unless it is named below.
# ---------------------------------------------------------------------------
SEQ_COLS = ["daily_return", "momentum_5", "volatility_20",
            "volume_ratio_20", "relative_strength_20"]


def _deployed_cols():
    """The deployed model's feature set, from its own constants."""
    try:
        from features import FEATURE_COLS
        from fundamentals_features_beta import FUNDAMENTAL_FEATURE_COLS
    except ImportError:          # standalone use (tests); caller supplies cols
        return None
    fund = [c for c in FUNDAMENTAL_FEATURE_COLS if c != "fundamentals_age_days"]
    return list(dict.fromkeys(list(FEATURE_COLS) + fund))


_ALL = _deployed_cols()
STATIC_COLS = ([c for c in _ALL if c not in SEQ_COLS] if _ALL is not None else
               ["momentum_20", "momentum_60", "momentum_120", "volatility_60",
                "pct_from_high_252", "pct_from_low_252", "market_cap",
                "pe_ratio", "pb_ratio", "ps_ratio", "debt_to_equity",
                "roe", "roa"])

CLIP = 5.0


def zscore_by_date(df, cols):
    """Cross-sectional z-score within each date, clipped. Median/MAD rather
    than mean/sd: fundamentals like pe_ratio have tails that would otherwise
    put the whole cross-section inside one standard deviation of a handful of
    extreme names."""
    out = df[cols].astype(np.float64).copy()
    g = df.groupby("date", observed=True)
    med = g[cols].transform("median")
    mad = g[cols].transform(lambda s: (s - s.median()).abs().median())
    scale = 1.4826 * mad
    # a column with zero spread on a date carries no cross-sectional
    # information that day; leave it at zero rather than dividing by ~0
    scale = scale.where(scale > 1e-12, np.nan)
    z = ((out - med) / scale).clip(-CLIP, CLIP)
    return z.fillna(0.0).to_numpy(np.float32)


class ClawProjection:
    """Fixed sparse random projection onto the input population.

    Each input cell draws `claws` weights from the CONCATENATED feature space
    (sequence + static), not from each block separately. That detail is load-
    bearing: with only 5 daily features, sampling "6 of 5" hands every cell the
    whole vector and the sparse-coding motif silently becomes a dense
    projection -- which is what the first version did. Sampling 6 of 18 gives
    genuine claw-like sparsity, and lets a cell mix fast and slow inputs the
    way a Kenyon cell samples across modalities rather than within one. About
    9% of cells draw no sequence claw at all and see only slow context; that is
    a feature, not a defect.

    Signs are balanced +/-1 with a magnitude jitter. The SAME projection must
    be used for the real connectome and the matched-shuffle control, or the
    comparison confounds topology with input wiring -- hence the explicit seed.
    """

    def __init__(self, n_in, n_seq, n_static, claws=6, seed=0):
        rng = np.random.default_rng(seed)
        n_feat = n_seq + n_static
        k = min(claws, n_feat)
        if k < claws:
            print(f"  projection: only {n_feat} features, using {k} claws")
        rows = np.repeat(np.arange(n_in), k)
        cols = np.concatenate([rng.choice(n_feat, size=k, replace=False)
                               for _ in range(n_in)])
        vals = (rng.choice([-1.0, 1.0], size=n_in * k)
                * rng.uniform(0.5, 1.5, n_in * k)).astype(np.float32)
        P = sp.csr_matrix((vals, (rows, cols)), shape=(n_in, n_feat),
                          dtype=np.float32)
        self.P_seq = P[:, :n_seq].tocsr()
        self.P_static = P[:, n_seq:].tocsr()
        self.n_in, self.claws = n_in, k
        self.n_no_seq = int((self.P_seq.getnnz(axis=1) == 0).sum())

    def drive(self, Z, S):
        """Z : (T, B, n_seq)   S : (B, n_static)  ->  (T, n_in, B)"""
        T, B, _ = Z.shape
        static = np.asarray(self.P_static @ S.T, dtype=np.float32)     # (n_in, B)
        U = np.empty((T, self.n_in, B), dtype=np.float32)
        for t in range(T):
            U[t] = self.P_seq @ Z[t].T
        U += static[None]
        return U


class PanelEncoder:
    """Z-scores the whole panel once, then serves (Z, S) per rebalance date.

    The panel is sorted by (ticker, date) and kept positional, so a name's
    trailing T days are CONTIGUOUS rows ending at its row for `as_of`. That
    turns per-window assembly into one integer-array index instead of a
    groupby, which matters when it runs 124 times over 12M rows.

    The contiguity assumption is checked, not trusted: a window is only
    accepted if all T rows carry the same ticker code. Without that check a
    name with fewer than T rows of history would silently borrow the tail of
    the previous ticker in the sort order -- a wrong-rows bug of exactly the
    kind merge_asof produced in Round 16, and one no distribution check would
    catch, because the borrowed rows are perfectly well-formed.
    """

    def __init__(self, panel, seq_cols=SEQ_COLS, static_cols=STATIC_COLS):
        self.seq_cols = [c for c in seq_cols if c in panel.columns]
        self.static_cols = [c for c in static_cols if c in panel.columns]
        missing = (set(seq_cols) | set(static_cols)) - set(panel.columns)
        if missing:
            print(f"  encoder: {len(missing)} column(s) absent from the panel "
                  f"and dropped: {sorted(missing)}")
        df = panel.sort_values(["ticker", "date"]).reset_index(drop=True)
        self.tick = df["ticker"].astype("category").cat.codes.to_numpy(np.int32)
        self.date = df["date"].to_numpy("datetime64[ns]")
        print(f"  encoder: z-scoring {len(df):,} rows "
              f"({len(self.seq_cols)} sequence + {len(self.static_cols)} static cols)")
        self.Z = zscore_by_date(df, self.seq_cols)
        self.S = zscore_by_date(df, self.static_cols)
        # (ticker_code, date) -> row position
        self.pos = pd.Series(np.arange(len(df), dtype=np.int64),
                             index=pd.MultiIndex.from_arrays([self.tick, self.date]))
        self.codes = dict(zip(df["ticker"].astype("category").cat.categories,
                              range(len(df["ticker"].astype("category").cat.categories))))
        self.n_seq = len(self.seq_cols)
        self.n_static = len(self.static_cols)

    def window(self, tickers, as_of, T):
        """Returns (kept_tickers, Z (T,B,n_seq), S (B,n_static))."""
        as_of = np.datetime64(pd.Timestamp(as_of), "ns")
        codes = np.array([self.codes.get(t, -1) for t in tickers], dtype=np.int64)
        ok = codes >= 0
        keys = pd.MultiIndex.from_arrays([codes[ok], np.full(ok.sum(), as_of)])
        pos = self.pos.reindex(keys).to_numpy()
        have = np.isfinite(pos.astype(np.float64)) & (pos >= T - 1)
        pos = pos[have].astype(np.int64)
        names = np.asarray(tickers)[ok][have]
        if not len(pos):
            return [], None, None

        rows = pos[None, :] - np.arange(T - 1, -1, -1)[:, None]        # (T, B)
        same = (self.tick[rows] == self.tick[pos][None, :]).all(axis=0)
        if not same.all():
            rows, pos, names = rows[:, same], pos[same], names[same]
        if not len(pos):
            return [], None, None
        return list(names), self.Z[rows], self.S[pos]
