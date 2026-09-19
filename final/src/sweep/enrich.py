"""
Which industry groups is the model over-picking, and is it more than chance?

Gabe's question (2026-09-16): a hypergeometric enrichment test, exactly the
one used for GO terms -- given a universe of N names of which K are in group
g, and n picks of which x land in g, how surprising is x?

Two things had to be right before that test says anything true here.

--------------------------------------------------------------------------
1. THE NULL MUST BE SELECTION-MATCHED, WHICH MAKES IT NOT ONE HYPERGEOMETRIC
--------------------------------------------------------------------------
The deployed construction does NOT draw 5 names from the cross-section. It
splits the eligible universe into 5 trailing-volatility quintiles and takes the
single best-scoring name in EACH (portfolio._pick_idx, bucket="volq", per=1).

Because the quintiles are equal-sized by construction, the stratified and the
flat null have EXACTLY the same expectation -- 5K/N per window either way -- so
this is not a bias correction. It is a variance correction, and it runs in the
direction that is easy to get backwards:

    group of 100 names, 1,000-name universe, 12 windows, 60 draws
    all 100 inside ONE volatility quintile   strat sd 1.73   flat sd 2.25
    the same 100 spread evenly over five     strat sd 2.32   flat sd 2.25

    observing 12 (double the expected 6):    p_strat 0.00024   p_flat 0.0119

The flat hypergeometric lets up to 5 of a window's picks come from the same
quintile when the construction allows at most 1. For a volatility-concentrated
group -- utilities sit low, biotech sits high, and that is most of what a fine
taxonomy separates -- it is therefore OVER-dispersed, and it understates the
significance of a real concentration by an order of magnitude. For a group
spread evenly across the quintiles the two agree to three decimals, which is
the check that the correction is doing what it claims and nothing else.

This is the same lesson as `decile_volq_excess` in the 2026-09-16 fly work: if
the null is not matched to the selection, the result is partly a measurement of
the selection. There it made a metric too generous; here it makes one too shy.

With one draw per quintile, each pick is an independent draw from a DIFFERENT
population, so the count in group g is a sum of 5 independent hypergeometrics
with n=1 -- i.e. a sum of Bernoullis with p_b = K_b / N_b. Pooled over windows
it is a Poisson-binomial over (windows x quintiles) Bernoullis. That is an
exact, closed-form distribution, computed below by a length-x dynamic program;
no normal approximation is used anywhere, which matters because the interesting
groups are exactly the rare ones where a normal approximation is worst.

The unstratified hypergeometric is kept as `hypergeom_sf` and reported beside
the stratified p, so the size of the correction is visible rather than assumed.

--------------------------------------------------------------------------
2. MULTIPLE TESTING
--------------------------------------------------------------------------
There are up to 366 groups at sicindustry. Testing all of them at 0.05 yields
~18 "significant" groups from a model with no industry preference whatever.
Every p here is therefore reported beside a Benjamini-Hochberg q, and the app
must rank on q. This is the same correction Round 16 applied to the feature
screen, for the same reason.

Dependency-free by the same policy as `_num.py`: numpy only, no scipy.
"""
from __future__ import annotations

import numpy as np


def poisson_binomial_tail(ps, x: int) -> float:
    """P(X >= x) exactly, X = sum of independent Bernoulli(p_i).

    Dynamic program truncated at x: the full distribution needs O(T^2) but the
    upper tail only needs the first x+1 masses, so this is O(T*x). For the
    pooled test T is ~620 draws and x is rarely above 20.
    """
    ps = np.asarray([p for p in ps if p > 0.0], dtype=np.float64)
    x = int(x)
    if x <= 0:
        return 1.0
    if len(ps) < x:
        return 0.0
    # pmf[k] = P(X = k) for k = 0..x-1; anything at or above x is the answer.
    pmf = np.zeros(x, dtype=np.float64)
    pmf[0] = 1.0
    for p in ps:
        q = 1.0 - p
        # walk down so each update reads the previous iteration's values
        pmf[1:] = pmf[1:] * q + pmf[:-1] * p
        pmf[0] *= q
    return float(max(0.0, 1.0 - pmf.sum()))


def poisson_binomial_lower(ps, x: int) -> float:
    """P(X <= x) exactly -- the depletion tail, for under-picked groups."""
    ps = np.asarray([p for p in ps if p > 0.0], dtype=np.float64)
    x = int(x)
    if x < 0:
        return 0.0
    if len(ps) <= x:
        return 1.0
    pmf = np.zeros(x + 1, dtype=np.float64)
    pmf[0] = 1.0
    for p in ps:
        q = 1.0 - p
        pmf[1:] = pmf[1:] * q + pmf[:-1] * p
        pmf[0] *= q
    return float(min(1.0, pmf.sum()))


def poisson_binomial_moments(ps) -> tuple[float, float]:
    ps = np.asarray(list(ps), dtype=np.float64)
    return float(ps.sum()), float((ps * (1.0 - ps)).sum())


def hypergeom_sf(N: int, K: int, n: int, x: int) -> float:
    """P(X >= x) for the UNSTRATIFIED draw -- n names from N, K of them in the
    group. Kept for the side-by-side that shows what stratification buys."""
    from math import comb
    N, K, n, x = int(N), int(K), int(n), int(x)
    if x <= 0:
        return 1.0
    lo, hi = max(0, n - (N - K)), min(n, K)
    if x > hi:
        return 0.0
    denom = comb(N, n)
    if denom == 0:
        return 1.0
    tot = sum(comb(K, k) * comb(N - K, n - k) for k in range(max(x, lo), hi + 1))
    return float(tot / denom)


def bh_fdr(pvals) -> np.ndarray:
    """Benjamini-Hochberg q-values, order preserved, monotone-enforced."""
    p = np.asarray(list(pvals), dtype=np.float64)
    m = len(p)
    if m == 0:
        return p
    o = np.argsort(p)
    ranked = p[o] * m / np.arange(1, m + 1)
    ranked = np.minimum.accumulate(ranked[::-1])[::-1]
    q = np.empty(m, dtype=np.float64)
    q[o] = np.clip(ranked, 0.0, 1.0)
    return q


def enrich(draws: dict, min_expected: float = 0.0) -> list:
    """One enrichment table.

    `draws` maps group -> (observed_count, [p_1, p_2, ...]), where each p_i is
    that group's share of the population the i-th draw was taken from. The
    length of the p list is the total number of draws, so a group present in
    only some windows still gets every draw's probability -- otherwise the
    expectation would be conditioned on the outcome.

    Returns rows sorted by q, each with observed, expected, ratio, p_enrich,
    p_deplete, q_enrich, q_deplete.
    """
    rows = []
    for g, (obs, ps) in draws.items():
        mu, var = poisson_binomial_moments(ps)
        if mu < min_expected:
            continue
        rows.append({
            "group": g, "observed": int(obs), "expected": mu,
            "sd": float(np.sqrt(var)),
            "ratio": (obs / mu) if mu > 0 else float("nan"),
            "n_draws": len(ps),
            "p_enrich": poisson_binomial_tail(ps, obs),
            "p_deplete": poisson_binomial_lower(ps, obs),
        })
    if not rows:
        return rows
    qe = bh_fdr([r["p_enrich"] for r in rows])
    qd = bh_fdr([r["p_deplete"] for r in rows])
    for r, a, b in zip(rows, qe, qd):
        r["q_enrich"] = float(a)
        r["q_deplete"] = float(b)
    rows.sort(key=lambda r: (r["q_enrich"], -r["observed"]))
    return rows


def self_test():
    rng = np.random.default_rng(0)

    # 1. Poisson-binomial with identical p must equal the binomial.
    from math import comb
    p, T = 0.13, 30
    for x in (0, 1, 3, 7, 12):
        exact = sum(comb(T, k) * p**k * (1-p)**(T-k) for k in range(x, T+1))
        got = poisson_binomial_tail([p]*T, x)
        assert abs(got - exact) < 1e-12, f"binomial x={x}: {got} vs {exact}"
    print(f"poisson-binomial == binomial for identical p (T={T}, p={p})")

    # 2. tail + lower must overcount by exactly P(X = x).
    ps = rng.random(40) * 0.4
    for x in (1, 4, 9):
        over = poisson_binomial_tail(ps, x) + poisson_binomial_lower(ps, x) - 1.0
        # that overlap is P(X == x) >= 0
        assert -1e-12 <= over <= 1.0, f"tails inconsistent at x={x}: {over}"
    print("upper and lower tails overlap by exactly P(X=x) on heterogeneous p")

    # 3. Monte-Carlo the tail on heterogeneous p.
    ps = rng.random(25) * 0.5
    draws = (rng.random((200_000, 25)) < ps).sum(1)
    for x in (2, 5, 8, 11):
        mc = float((draws >= x).mean())
        ex = poisson_binomial_tail(ps, x)
        assert abs(mc - ex) < 0.004, f"x={x}: exact {ex:.5f} vs MC {mc:.5f}"
        print(f"  x>={x:>2}: exact {ex:.5f}  monte-carlo {mc:.5f}")

    # 4. Moments against Monte Carlo.
    mu, var = poisson_binomial_moments(ps)
    assert abs(mu - draws.mean()) < 0.02 and abs(var - draws.var()) < 0.05
    print(f"moments: mean {mu:.4f} (MC {draws.mean():.4f}), "
          f"var {var:.4f} (MC {draws.var():.4f})")

    # 5. Hypergeometric sanity: the whole universe drawn must give x == n.
    assert abs(hypergeom_sf(100, 30, 100, 30) - 1.0) < 1e-12
    assert hypergeom_sf(100, 30, 100, 31) == 0.0
    assert abs(hypergeom_sf(1000, 100, 5, 1) - (1 - comb(900, 5)/comb(1000, 5))) < 1e-12
    print("hypergeom_sf: boundary and closed-form cases agree")

    # 6. BH: uniform p under the null must yield almost no discoveries.
    q = bh_fdr(rng.random(400))
    assert (q < 0.05).sum() <= 4, f"BH let through {(q<0.05).sum()} nulls of 400"
    # and it must be monotone in p
    p6 = rng.random(50); q6 = bh_fdr(p6)
    assert np.all(np.diff(q6[np.argsort(p6)]) >= -1e-12), "BH not monotone"
    print(f"BH-FDR: {(q < 0.05).sum()} of 400 uniform nulls pass q<0.05, monotone")

    # 7. The stratification point, end to end, in both directions.
    #    Same group size, same expectation; only the dispersion differs, and
    #    only when the group sits inside one volatility quintile.
    Nn, W, Nb = 1000, 12, 200
    conc = [100, 0, 0, 0, 0]
    even = [20, 20, 20, 20, 20]
    for name, kq in (("concentrated", conc), ("even", even)):
        ps = [k / Nb for k in kq] * W
        mu, _ = poisson_binomial_moments(ps)
        assert abs(mu - 5 * sum(kq) / Nn * W) < 1e-9, "means must match the flat null"
    ps_c = [k / Nb for k in conc] * W
    ps_e = [k / Nb for k in even] * W
    p_c = poisson_binomial_tail(ps_c, 12)
    p_e = poisson_binomial_tail(ps_e, 12)
    p_f = hypergeom_sf(Nn, 100, 60, 12)
    assert p_c < p_f / 10, f"concentrated: strat {p_c:.3g} vs flat {p_f:.3g}"
    assert abs(p_e - p_f) < 0.01, f"even-spread must agree: {p_e:.4f} vs {p_f:.4f}"
    print(f"stratification: same mean either way; concentrated group "
          f"p_strat={p_c:.2e} vs p_flat={p_f:.2e} ({p_f/p_c:.0f}x), "
          f"evenly spread {p_e:.4f} vs {p_f:.4f} (agree)")
    print("PASSED")


if __name__ == "__main__":
    self_test()
