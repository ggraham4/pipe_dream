"""
Rate-coded reservoir dynamics on a fixed connectome, plus the gain calibration
that puts Kenyon-cell activity where the animal runs it.

    h[t+1] = (1 - alpha) * h[t] + alpha * min( ReLU( W h[t] + b + g * u[t] ), h_max )

W is fixed by biology and never trained. Only a downstream ridge readout learns.

BACKENDS. scipy.sparse on CPU, or torch (MPS/CUDA/CPU) when available. The
maths is identical; torch exists because a 10.5M-nnz operator against a
1,200-column state is the whole cost of this pilot. The scipy path is what
makes the self-test runnable anywhere, including environments without torch,
which is how the dynamics below were actually verified.

GAIN. `g` is the one free scalar in the forward model and it matters more than
it looks: too low and the network never leaves baseline, too high and every
unit pins at h_max and the state carries one bit. Rather than tune it for
downstream performance -- which would quietly turn a "fixed" network into a
fitted one -- it is calibrated to a BIOLOGICAL target: the fraction of Kenyon
cells active. An odour drives roughly 5-10% of KCs in Drosophila; the default
target of 6% sits in that band. Calibration is a bisection on g against input
drawn ONLY from the earliest training windows, then frozen for the whole run.

That last clause is the part that would otherwise be look-ahead. Calibrating
gain on the full sample would be fitting a parameter on data the model is later
scored against, which is exactly the thing Gate A exists to catch, even though
the parameter is one number and the fit is to an activity statistic rather than
to returns.
"""
from __future__ import annotations

import numpy as np

try:
    import torch
    _HAVE_TORCH = True
except ImportError:                                            # scipy fallback
    _HAVE_TORCH = False


def pick_device(prefer: str | None = None) -> str:
    if prefer:
        return prefer
    if not _HAVE_TORCH:
        return "scipy"
    if torch.backends.mps.is_available():
        return "mps"
    if torch.cuda.is_available():
        return "cuda"
    return "cpu"


class Reservoir:
    """A fixed recurrent operator plus its dynamics.

    Parameters
    ----------
    W : scipy.sparse CSR, (N, N), row = postsynaptic, col = presynaptic.
        Already signed and normalised by postsynaptic input -- see
        connectome.build_operator.
    alpha : leak. The state is an exponential moving average with time constant
        ~1/alpha steps, so alpha=0.2 over a 20-step sequence means the final
        state is dominated by the last ~5 days and the first ten have largely
        decayed away. If the point of the exercise is that ORDER over the whole
        window matters, alpha=0.2 quietly discards most of it: use a smaller
        leak (0.05 gives tau~20, matching the sequence length), or read the
        trajectory via `taps` instead of only the endpoint, or both.
    h_max : saturation ceiling; the min() is what keeps a recurrent network with
        positive feedback loops from running away.
    b : resting bias. 0.1 matches nfly's published default.
    """

    def __init__(self, W, alpha=0.2, h_max=10.0, b=0.1, device=None):
        self.alpha = float(alpha)
        self.h_max = float(h_max)
        self.b = float(b)
        self.n = W.shape[0]
        self.device = pick_device(device)
        if self.device == "scipy":
            self.W = W.tocsr()
        else:
            W = W.tocoo()
            idx = torch.from_numpy(np.stack([W.row, W.col])).long()
            val = torch.from_numpy(W.data).float()
            self.W = torch.sparse_coo_tensor(
                idx, val, (self.n, self.n)).coalesce().to(self.device)

    # -- one sequence of drive -------------------------------------------
    def run(self, U, gain=1.0, in_idx=None, taps=None):
        """Run T steps and return the final state (N, B).

        U : (T, n_in, B) drive on the input population named by `in_idx`, or
            (T, N, B) drive on every neuron when `in_idx` is None.

        THE in_idx PATH IS NOT AN OPTIMISATION, IT IS THE ONLY VIABLE PATH AT
        SCALE. Drive is nonzero on a few thousand input cells, but a dense
        (T, N, B) tensor is sized by the whole network: at T=20, N=201,811,
        B=1,200 that is 19.4 GB, which is exactly the "Invalid buffer size:
        18.04 GiB" that killed the first central/full benchmark. Passing the
        input population instead makes it (20, 4064, 1200) = 390 MB for the
        mushroom body and scales with the sensory population, not the brain.
        """
        T, B = U.shape[0], U.shape[2]
        taps = None if taps is None else sorted({int(t) % T for t in taps})
        if self.device == "scipy":
            return self._run_scipy(U, gain, T, B, in_idx, taps)
        return self._run_torch(U, gain, T, B, in_idx, taps)

    def _run_scipy(self, U, gain, T, B, in_idx, taps=None):
        h = np.zeros((self.n, B), dtype=np.float32)
        got = []
        for t in range(T):
            pre = self.W @ h
            pre += self.b
            if in_idx is None:
                pre += gain * U[t]
            else:
                pre[in_idx] += gain * U[t]
            np.maximum(pre, 0.0, out=pre)
            np.minimum(pre, self.h_max, out=pre)
            h = (1.0 - self.alpha) * h + self.alpha * pre
            if taps is not None and t in taps:
                got.append(h.copy())
        return np.stack(got) if taps is not None else h

    def _run_torch(self, U, gain, T, B, in_idx, taps=None):
        dev = self.device
        h = torch.zeros((self.n, B), device=dev)
        Ut = U if torch.is_tensor(U) else torch.from_numpy(np.asarray(U)).float()
        Ut = Ut.to(dev)
        ii = None if in_idx is None else torch.as_tensor(
            np.asarray(in_idx), device=dev, dtype=torch.long)
        got = []
        for t in range(T):
            pre = torch.sparse.mm(self.W, h) + self.b
            if ii is None:
                pre = pre + gain * Ut[t]
            else:
                pre = pre.index_add(0, ii, gain * Ut[t])
            pre = torch.clamp(torch.relu(pre), max=self.h_max)
            h = (1.0 - self.alpha) * h + self.alpha * pre
            if taps is not None and t in taps:
                got.append(h)
        if taps is not None:
            return torch.stack(got).cpu().numpy()
        return h.cpu().numpy()

    # -- resting state -----------------------------------------------------
    def baseline(self, T, B=1, n_in=None, taps=None):
        """State after T steps with NO external drive.

        This is not a formality. The resting bias b is added to every neuron at
        every timestep, so ReLU pins nothing to zero and every unit sits at a
        positive spontaneous level. Any activity measure taken against an
        absolute floor therefore reports 100% of cells active at every gain,
        including zero -- which is how the first version of calibrate_gain
        silently became a no-op. "Active" has to mean ABOVE SPONTANEOUS, the
        way it does in the animal.

        Cached: it depends only on (W, alpha, b, h_max, T), none of which vary
        within a run.
        """
        key = (int(T), tuple(taps) if taps is not None else None)
        if getattr(self, "_h0_key", None) != key:
            U0 = np.zeros((T, 1, 1), dtype=np.float32)
            self._h0 = self.run(U0, gain=0.0, in_idx=np.zeros(1, np.int64),
                                taps=taps)
            self._h0_key = key
        return self._h0

    def response(self, U, gain=1.0, in_idx=None, taps=None):
        """Deviation of the final state from rest -- the quantity that carries
        the input. Downstream readouts consume this, not the raw state, so a
        neuron's spontaneous level cannot masquerade as a feature."""
        h = self.run(U, gain=gain, in_idx=in_idx, taps=taps)
        return h - self.baseline(U.shape[0], taps=taps)

    # -- gain calibration --------------------------------------------------
    def calibrate_gain(self, U, active_mask, target=0.06, thresh=1e-3,
                       lo=1e-4, hi=1e4, iters=28, verbose=True, in_idx=None):
        # Calibration always uses the FINAL state (taps=None) regardless of how
        # the readout is tapped, so the biological target means one thing.
        """Bisect the global input gain so that `target` of the neurons in
        `active_mask` are active at the end of the sequence.

        `active_mask` is the Kenyon-cell population: the sparse-coding layer
        whose activity fraction is the thing measured in the animal. Activity
        is `h - h_rest > thresh` -- a response ABOVE the spontaneous level, not
        an absolute level. See baseline() for why that distinction is the whole
        ballgame here.

        Monotonicity is assumed (more drive -> more active cells) and checked:
        if the bracket does not straddle the target the function says so rather
        than returning an endpoint that happens to be closest.
        """
        def frac(g):
            r = self.response(U, gain=g, in_idx=in_idx)
            return float((r[active_mask] > thresh).mean())

        f_lo, f_hi = frac(lo), frac(hi)
        if verbose:
            print(f"  gain bracket: g={lo:.1e} -> {f_lo:.3%} active, "
                  f"g={hi:.1e} -> {f_hi:.3%} active (target {target:.1%})")
        if not (f_lo <= target <= f_hi):
            raise RuntimeError(
                f"target {target:.1%} is outside the achievable range "
                f"[{f_lo:.3%}, {f_hi:.3%}]. Widen the bracket, or the operator "
                f"is not behaving monotonically in gain -- check that W is "
                f"normalised and that the input actually reaches the mask.")
        for _ in range(iters):
            mid = np.sqrt(lo * hi)                     # geometric bisection
            if frac(mid) < target:
                lo = mid
            else:
                hi = mid
        g = float(np.sqrt(lo * hi))
        if verbose:
            print(f"  calibrated gain = {g:.4g}  ->  {frac(g):.2%} of "
                  f"{int(active_mask.sum()):,} KCs responding above rest")
        return g


def static_drive(u, T):
    """Broadcast a constant (N, B) drive across T timesteps without
    materialising T copies where the backend allows it."""
    return np.broadcast_to(u[None], (T,) + u.shape)
