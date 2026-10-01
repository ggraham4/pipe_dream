# WO-39: sign-aware rolling weights (rule SA252)

Commissioned by the COO on 2026-10-01. Gabe approved the test on 2026-10-01 ("make it so"), including the
2020+ walk-forward. Branch `worktree-agent-a086ed9cc62b1ee11`. Code:
`final/src/rollweights/signaware_rollweights.py`. Outputs: `final/out/rollweights/signaware/`.

**Numbering note.** The order was issued as "WO-35" with the 2020+ part as hold-out read #14. Another
session had already used both labels (options Phase 2), so the COO renumbered it on 2026-10-01, before the
pre-registration commit: this is **WO-39**, and its 2020+ walk-forward is **hold-out read #17**
(Gabe-approved, fits on 2020+ data). The spec did not change.

Status: **PRE-REGISTERED, no SA252-vs-control statistic computed yet.** Results go in §3.

---

## 1. Pre-registration (spec as issued by the COO, pinned before results)

**Background.** WO-33 (`final/models/2026-09-30-rolling-weights.md`) refit the live icw9_seas weights on the
trailing 252 matured label dates every 21 trading days (arm R252) and compared it with an expanding-window
control (EXP). R252 minus EXP was −1.11%/yr on 2010–2019 (0/40 offsets, KILL) and +2.60%/yr on 2020–26
(38/40). WO-34 (`final/models/2026-09-30-r252-forward.md`) found that the rule sizes a weight by |t| and keeps
the factor's pre-set sign. A factor whose trailing-year IC is large and wrong-signed therefore gets a large
weight in its original direction. Example, the 2026-09-16 refit: short interest weight −0.270 with t +1.72;
seas weight +0.364 with t −1.97.

**Question.** Does R252 beat the expanding control once a factor with a wrong-signed trailing t is held at
the floor weight instead of being given a large weight in its pre-set direction?

**Rule SA252 (fixed now, no variants).** The same as WO-33's R252 in every respect: window of the 252 most
recent matured label dates, refit every 21 trading days, embargo (only labels matured by the refit date,
idx(d) + 41 ≤ idx(refit)), 9 factors, the live shrinkage formula, floor and renormalization:

`w_k = s_k * max(0.1, |t_k| − 1) / sum_j max(0.1, |t_j| − 1)`

with one exception. Let `s_k` be the factor's pre-set sign (`ic_weighted_composite.SIGNS_V9_SEAS`) and `t_k`
its trailing-window NW(39) t.

- If `sign(t_k) == s_k`: the raw weight is computed exactly as in R252.
- If `sign(t_k) != s_k`: the factor gets the **floor** raw weight (0.1) in its **pre-set** direction. This is
  the weight the live rule gives a factor whose t cannot be estimated. The sign is never flipped.

Details fixed here, before results:

- A t of exactly 0 counts as opposed. It is at the floor under both rules, so this changes nothing.
- A NaN t (factor not estimable in the window) is at the floor under both rules, as in R252. This is the
  state of `short_interest_days_to_cover` for all of 2010–2019.
- Renormalization is the live one, taken over the SA252 raw set. A factor that agrees keeps its R252 raw
  magnitude `|t| − 1`, but its final weight can differ from R252's because the denominator loses the opposed
  factors' raw magnitudes.
- Implementation: the opposed t is set to NaN and `screen_insider.fit_weights` is called unchanged.
- The trailing t's are WO-33's own, read from its committed weight paths (`weight_paths.csv`,
  `weight_paths_step2.csv`). No IC is recomputed.

**Hard asserts (build stage).**

- `fit_weights` on the stored R252 t's reproduces the stored R252 weights to 1e-12 on every refit.
- On every refit where no finite t opposes its pre-set sign, SA252 == R252 to 1e-12. The order's wording is
  "all 9 trailing t's have the pre-set sign". Short interest has a NaN t before 2020, so the literal case
  cannot occur in Step 1; the assert is run on the wider set and the count of refits it ran on is reported
  per era, with the literal all-9-finite count beside it.
- No weight has a flipped sign; every opposed factor sits at the row's minimum |weight|.
- The pre-2020 rows of the Step 2 SA252 path equal the Step 1 path.

**Control and references.** Primary comparison: SA252 vs EXP (WO-33's expanding control, its weight path
reused as committed). References, descriptive only: SA252 vs R252; SA252 vs the frozen live icw9_seas.

**Data and harness.** Exactly WO-33's: v2 col c cap150, `decile_volq`, net 15 bp, 40 offsets, h=40, label
`close[t+40]/open[t+1]`. WO-33's `rollweights.py` is imported read-only (`load_v2`, `load_B`, `score_path`,
`compare`, `hold`, `hold2`); none of its stages is run.

**Reconcile first (hard asserts, tolerance 0.01%/yr and exact offset count).** R252 − EXP = −1.109%/yr
(0/40) on 2010–2019 and +2.603%/yr (38/40) on 2020–26. Frozen live on 2020–26 = −2.016%/yr vs SPY (1e-6).

**Step 1 (2010-01-04..2019-12-31).** Hard `< 2020-01-01` assert on this code path (`RW.hold` on the
universe, calendar, SPY, weight paths, fit windows and picks).

- **Success:** per-date difference NW(39) t ≥ 2.39 AND ≥ 30/40 offsets > 0 AND leave-one-year-out (LOYO)
  minimum > 0.
- **Kill:** mean difference ≤ 0 OR LOYO minimum ≤ 0.
- **Middle:** positive, below the bar.

**Step 2 (2020-01-02..2026-07-30, last matured 40d label; walk-forward; hold-out read #17).** Fits on 2020+ data. Runs
regardless of Step 1 and **cannot rescue a Step 1 kill**. Promote-candidate only if Step 1 is a success AND
the Step 2 mean difference is > 0 with ≥ 30/40 offsets > 0 AND the difference is > 0 with 2020 dropped.
Report book vs SPY for SA252, R252, EXP and live (live = −2.02).

**Also reported (descriptive, no verdict).**

- Share of refits × factors where the sign rule bound, per factor and per era. Two counts: "opposed" (finite
  t with the wrong sign) and "weight changed" (opposed and |t| > 1.1, the cases where the raw weight differs
  from R252's).
- Turnover (mean new-name fraction per rebalance) and cost drag, against EXP and R252.
- Mean L1 weight change per refit.
- The swap-one table for `momentum_12_1` and `net_issuance_pct` only. WO-34 found those two swap-ins
  positive in both eras; that finding is post hoc, so the table is descriptive. Swap-in = EXP path with the
  factor's weight column replaced by SA252's, rows rescaled to sum|w| = 1, minus EXP. Swap-out = SA252 path
  with the factor's column replaced by EXP's, rescaled; loss = (SA252 − EXP) − (swap-out − EXP).

**Trial count.** Family "time-varying weights": R252 and R756 are spent (k=2, both KILL). SA252 is trial 3,
so the t bar is 2.39 (k=3 Bonferroni). **No further variants after results.**

**Process.** This section is committed through the integrator before any SA252-vs-control statistic is
computed. The build stage (weight paths, asserts, binding shares, weight stability, R252 − EXP reconcile)
builds no SA252 book. Iteration cap 3, bug fixes only.

---

## 2. Build-stage facts (no SA252-vs-control statistic)

From `final/out/rollweights/signaware/signaware_build.json`, written before the pre-registration commit. No
SA252 book was built in this stage.

- **Asserts passed.** Stored R252 weights reproduced from stored t's (1e-12) on every refit. No flipped
  sign. Every opposed factor at the floor. Step 2 path equals the Step 1 path before 2020 (max diff 0).
- **SA252 == R252 assert** ran on 14 of 120 refits in 2010–2019 and 1 of 79 in 2020–26 (refits where no
  finite t opposes its sign). The literal "all 9 finite and agreeing" case occurred on 0 and 1 refits.
- **Reconciles passed.** R252 − EXP: −1.1094%/yr (0/40) on 2010–2019; +2.6025%/yr (38/40) on 2020–26.
  Frozen live on 2020–26: −2.0164%/yr vs SPY.

**How often the sign rule binds** (refits in the evaluation window; "opposed" = finite t with the wrong
sign; "changed" = opposed and |t| > 1.1, so the raw weight differs from R252's):

| factor | 2010–19 opposed | 2010–19 changed | 2020–26 opposed | 2020–26 changed |
|---|---|---|---|---|
| momentum_12_1 | 23% | 13% | 16% | 10% |
| pct_from_high_252 | 43% | 15% | 30% | 6% |
| volatility_60 | 53% | 25% | 38% | 15% |
| gross_profitability | 12% | 5% | 19% | 8% |
| accruals | 38% | 21% | 65% | 25% |
| net_issuance_pct | 22% | 2% | 30% | 9% |
| days_to_next_filing_seasonal | 49% | 25% | 52% | 16% |
| short_interest_days_to_cover | 0% (t is NaN) | 0% | 18% | 11% |
| seas | 40% | 12% | 44% | 6% |
| **all refit × factor cells** | **31%** | **13%** | **35%** | **12%** |

- Refits with at least one opposed factor: 88% (2010–19), 99% (2020–26).
- Refits where SA252 weights differ from R252's: 62.5% (2010–19), 55.7% (2020–26).
- Mean L1 weight change per refit: SA252 0.278 vs R252 0.346 (2010–19); 0.268 vs 0.348 (2020–26).

## 3. Results

Pending.
