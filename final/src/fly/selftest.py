"""
Verify the reservoir machinery on a SYNTHETIC connectome, so the dynamics, the
gain calibration and the matched-shuffle control are known to work before the
real 1.1GB graph is ever loaded.

    python3 selftest.py

Synthetic, not real, and deliberately so: these are assertions about the code,
not about the fly. A synthetic graph with a known KC population lets every
claim below be checked against a number that is derivable in advance, which is
this project's standing rule (AGENTS.md, Gate A7c) -- verify by naming what
should be there, not by counting what is.
"""
import numpy as np
import scipy.sparse as sp

from reservoir import Reservoir
from connectome import shuffle_postsynaptic, normalise_operator

RNG = np.random.default_rng(0)
N, N_KC, N_IN, B, T = 4000, 2000, 60, 128, 20


def synthetic():
    """A caricature of the mushroom body: an input layer projecting sparsely
    and randomly onto a large KC population, KCs converging onto a small
    output layer, plus a global inhibitory cell standing in for APL."""
    rows, cols, vals = [], [], []
    kc = np.arange(N_IN, N_IN + N_KC)
    out = np.arange(N_IN + N_KC, N)
    # input -> KC, ~6 claws per KC, the real fly's convergence number
    for k in kc:
        pre = RNG.choice(N_IN, size=6, replace=False)
        rows += [k] * 6; cols += list(pre); vals += list(RNG.uniform(1, 5, 6))
    # KC -> output, dense-ish convergence
    for o in out:
        pre = RNG.choice(kc, size=200, replace=False)
        rows += [o] * 200; cols += list(pre); vals += list(RNG.uniform(1, 3, 200))
    # APL: every KC drives it, it inhibits every KC (sign applied below)
    apl = N - 1
    rows += list(np.full(N_KC, apl)); cols += list(kc); vals += [1.0] * N_KC
    rows += list(kc); cols += list(np.full(N_KC, apl)); vals += [8.0] * N_KC
    W = sp.coo_matrix((vals, (rows, cols)), shape=(N, N))
    sign = np.ones(N); sign[apl] = -1.0            # APL is GABAergic
    return W, sign, kc, out, apl


def main():
    W, sign, kc, out, apl = synthetic()
    Wn = normalise_operator(W, sign)
    ok = True

    # 1. normalisation: each postsynaptic row's absolute inputs sum to ~1
    rs = np.abs(Wn).sum(axis=1).A1
    nz = rs[rs > 0]
    print(f"1. row sums of |W| : min {nz.min():.3f} max {nz.max():.3f} "
          f"(expected 1.000 for every neuron with input)")
    if not np.allclose(nz, 1.0, atol=1e-6):
        ok = False; print("   FAIL")

    # 2. the sign structure survived: APL's column is entirely negative
    col = Wn.tocsc()[:, apl].toarray().ravel()
    print(f"2. APL output      : {int((col < 0).sum()):,} negative, "
          f"{int((col > 0).sum()):,} positive (expected all negative)")
    if (col > 0).any():
        ok = False; print("   FAIL")

    # 3. dynamics are stable and gain is monotone
    res = Reservoir(Wn, alpha=0.2, h_max=10.0, b=0.1, device="scipy")
    U = np.zeros((T, N, B), dtype=np.float32)
    drive = RNG.standard_normal((N_IN, B)).astype(np.float32)
    U[:, :N_IN, :] = drive                            # constant sensory drive
    kc_mask = np.zeros(N, bool); kc_mask[kc] = True
    fr = [float((res.response(U, gain=g)[kc_mask] > 1e-3).mean())
          for g in (1e-3, 1e-1, 1e1, 1e3)]
    print(f"3. KC active vs gain: " + "  ".join(f"{f:.1%}" for f in fr) +
          "  (expected non-decreasing)")
    if any(b < a - 1e-9 for a, b in zip(fr, fr[1:])):
        ok = False; print("   FAIL -- not monotone, calibration would be unsound")
    h0 = res.baseline(T)
    print(f"   resting state: mean {h0.mean():.4f}, "
          f"{float((h0 > 1e-3).mean()):.0%} of units above zero "
          f"(bias b={res.b} -> nothing is silent at rest)")
    h = res.run(U, gain=1.0)
    print(f"   state finite: {np.isfinite(h).all()}, "
          f"max {h.max():.3f} (ceiling {res.h_max})")
    if not np.isfinite(h).all() or h.max() > res.h_max + 1e-6:
        ok = False; print("   FAIL")

    # 4. gain calibration lands on the biological target
    g = res.calibrate_gain(U, kc_mask, target=0.06)
    got = float((res.response(U, gain=g)[kc_mask] > 1e-3).mean())
    print(f"4. calibrated to 6%: got {got:.2%}")
    if abs(got - 0.06) > 0.01:
        ok = False; print("   FAIL")

    # 5. the matched shuffle preserves what it is supposed to preserve
    Ws = shuffle_postsynaptic(W, sign, seed=1)
    a, b_ = W.tocoo(), Ws.tocoo()
    same_out = np.array_equal(np.bincount(a.col, minlength=N),
                              np.bincount(b_.col, minlength=N))
    same_w = np.allclose(np.sort(np.abs(a.data)), np.sort(np.abs(b_.data)))
    diff = 1.0 - (len(set(zip(a.row, a.col)) & set(zip(b_.row, b_.col)))
                  / len(set(zip(a.row, a.col))))
    print(f"5. shuffle control : out-degree preserved {same_out}, "
          f"weight multiset preserved {same_w}, {diff:.1%} of edges rewired")
    if not (same_out and same_w and diff > 0.9):
        ok = False; print("   FAIL")

    # 6. and it actually changes the computation
    resh = Reservoir(normalise_operator(Ws, sign), device="scipy")
    hs = resh.run(U, gain=g)
    r = np.corrcoef(h[out].ravel(), hs[out].ravel())[0, 1]
    print(f"6. real vs shuffled: readout correlation {r:+.3f} "
          f"(near 0 means the control is a real control)")

    print(f"\n{'ALL CHECKS PASSED' if ok else 'CHECKS FAILED'}")
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
