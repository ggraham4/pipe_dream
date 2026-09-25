"""
What is |t| = 2.0 actually worth for this screen? An exact permutation null.

    python3 calibrate_path_order.py

Gabe, 2026-09-16: "It seems to me like both accel_20 and slope_20 are promising?
... even if both barely miss the mark, they do carry information."

That is the right question to ask of a pre-registered threshold, and it has a
checkable answer. The screen already computes, for each order-aware feature, 5
matched shuffles whose paired statistic contains NO order information by
construction. Those shuffles can be made to stand in for the candidate:

    observed  = candidate - mean(4 of the 5 shuffles)      5 leave-one-out combos
    null draw = shuffle_k - mean(the other 4 shuffles)     5 draws per feature

Both sides subtract the mean of exactly four series, so the two are distributed
identically under the null and the comparison is exact. Ten valid null draws
come out of it (effratio_20's shuffles are numerically identical to each other,
being permutation-invariant, so its leave-one-out differences are exactly zero
and contribute nothing).

WHAT IT ANSWERS
---------------
Whether |t| = 2.0 was a reasonable bar. It was not: the order-free null reaches
2.47 at the IC statistic and 2.18 at the decile, so a threshold of 2.0 is one
the null clears on its own a fifth of the time. "Barely missing 2.0" therefore
does not mean "barely missing significance" -- the null-calibrated bar is HIGHER
than the registered one, not lower.

RESOLUTION
----------
Ten draws puts a floor of 1/11 = 0.091 on any empirical p. That is enough to
separate "indistinguishable from the null" from "the strongest thing here", and
not enough to separate 0.18 from 0.05. Raising N_SHUF in screen_path_order.py
and rerunning the slices is what would sharpen it.
"""
import glob
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from screen_path_order import (DAILY_DIR, HORIZON, N_SHUF,   # noqa: E402
                               newey_west_t)

# The null is built only from features whose shuffles actually differ.
NULLFEAT = ["slope_20", "accel_20"]
STATS = [("cond__", "Amendment A  (conditional IC)"),
         ("decc__", "Amendment B  (conditional decile_volq_excess)")]


def _load():
    days, D = [], {}
    files = sorted(glob.glob(str(DAILY_DIR / "path_order_daily_*.npz")))
    if not files:
        raise SystemExit("no slices -- run screen_path_order.py first")
    for f in files:
        z = np.load(f)
        days.append(pd.DatetimeIndex(z["days"]))
        for k in z.files:
            if k != "days":
                D.setdefault(k, []).append(z[k])
    d = pd.DatetimeIndex(np.concatenate([x.values for x in days]))
    o = np.argsort(d.values)
    return d[o], {k: np.concatenate(v)[o] for k, v in D.items()}


def _t(v):
    return newey_west_t(v, HORIZON)[1]


def _loo(D, pre, c):
    """(observed |t| per leave-one-out combo, null |t| per held-out shuffle)."""
    S = [D[f"{pre}{c}__s{k}"] for k in range(N_SHUF)]
    obs, null = [], []
    for k in range(N_SHUF):
        oth = np.nanmean([S[j] for j in range(N_SHUF) if j != k], axis=0)
        obs.append(abs(_t(D[f"{pre}{c}"] - oth)))
        t = _t(S[k] - oth)
        if np.isfinite(t):
            null.append(abs(t))
    return obs, null


def main():
    days, D = _load()
    print(f"{len(days):,} daily cross-sections, "
          f"{days.min().date()} .. {days.max().date()}")
    for pre, name in STATS:
        nulls = np.array([t for c in NULLFEAT for t in _loo(D, pre, c)[1]])
        print(f"\n{'=' * 78}\n{name}\n{'=' * 78}")
        print(f"exact leave-one-out null, {len(nulls)} order-free draws: "
              f"median |t| {np.median(nulls):.2f}, max {nulls.max():.2f}")
        print(f"  {' '.join(f'{x:.2f}' for x in np.sort(nulls))}")
        print(f"  the registered PASS bar was 2.0; the null reaches "
              f"{nulls.max():.2f} on its own.")
        print(f"\n{'feature':<12}{'obs |t|':>9}{'null >= obs':>14}{'emp p':>8}")
        for c in NULLFEAT:
            obs, _ = _loo(D, pre, c)
            ob = float(np.mean(obs))
            ge = int((nulls >= ob).sum())
            print(f"{c:<12}{ob:>9.2f}{ge:>10} /{len(nulls):>3}"
                  f"{(ge + 1) / (len(nulls) + 1):>8.3f}")

    # Are the two candidates one effect seen twice, or two effects?
    print(f"\n{'=' * 78}\nare slope_20 and accel_20 measuring the same thing?\n{'=' * 78}")
    for pre, nm in (("cond__", "IC"), ("decc__", "decile")):
        v = {}
        for c in NULLFEAT:
            S = np.nanmean([D[f"{pre}{c}__s{k}"] for k in range(N_SHUF)], axis=0)
            v[c] = D[f"{pre}{c}"] - S
        m = np.isfinite(v["slope_20"]) & np.isfinite(v["accel_20"])
        r = float(np.corrcoef(v["slope_20"][m], v["accel_20"][m])[0, 1])
        print(f"  corr(paired daily series) at {nm:<7}{r:>+7.3f}")
    print("  Near-independent. A combined test of \"is there ANY order effect\"\n"
          "  would therefore be legitimate in principle -- and is NOT run here:\n"
          "  choosing it after seeing both candidates near-miss is the search\n"
          "  Amendment B's stop rule exists to prevent, and at the traded tail\n"
          "  it would be carried entirely by accel_20 anyway.")


if __name__ == "__main__":
    main()
