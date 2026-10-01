# WO-39: sign-aware rolling weights (rule SA252)

Commissioned by the COO on 2026-10-01. Gabe approved the test on 2026-10-01 ("make it so"), including the
2020+ walk-forward. Branch `worktree-agent-a086ed9cc62b1ee11`. Code:
`final/src/rollweights/signaware_rollweights.py`. Outputs: `final/out/rollweights/signaware/`.

**Numbering note.** The order was issued as "WO-35" with the 2020+ part as hold-out read #14. Another
session had already used both labels (options Phase 2), so the COO renumbered it on 2026-10-01, before the
pre-registration commit: this is **WO-39**, and its 2020+ walk-forward is **hold-out read #17**
(Gabe-approved, fits on 2020+ data). The spec did not change.

Status: **DONE. Step 1 KILL.** SA252 minus EXP on 2010–2019 is −0.44%/yr (t −0.78, 7/40 offsets, LOYO
minimum −0.79). Step 2 on 2020–26 is +1.76%/yr (t +1.04, 33/40) and cannot rescue the kill. SA252 is not a
promote candidate and nothing changes in the live weights. Pre-registration committed in df9d2eb before any
SA252-vs-control statistic; results checkpoint d652d16. Results are in §3.

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

Files: `signaware_eval.json` (Step 1), `signaware_eval_step2.json` (Step 2), `signaware_swap.json`, all in
`final/out/rollweights/signaware/`. All differences are annualized, net of 15 bp, mean over 40 offsets.
Both stages re-ran the R252 − EXP reconcile and it passed (−1.1094, 0/40; +2.6025, 38/40). Each scoring
stage was run once. The only rerun was the build stage, for a wrong Python interpreter, before any number
existed.

### 3.1 Step 1 (2010-01-04..2019-12-31): KILL

| comparison | diff %/yr | NW(39) t | offsets > 0 | LOYO min |
|---|---|---|---|---|
| **SA252 − EXP (primary)** | **−0.44** | **−0.78** | **7/40** | **−0.79 (drop 2012)** |
| SA252 − R252 (reference) | +0.67 | +1.66 | 40/40 | +0.15 |
| SA252 − live icw9_seas (reference) | −1.18 | −1.92 | 0/40 | −1.54 |
| R252 − EXP (WO-33, reconcile) | −1.11 | −1.76 | 0/40 | −1.53 |

- **Verdict: KILL.** The mean difference is negative and the LOYO minimum is negative, so both kill
  conditions hold. The difference is negative with every single year dropped (−0.02 to −0.79).
- Against R252 the sign rule helped in this era: it recovered +0.67 of R252's −1.11 shortfall, on all 40
  offsets. That is 60% of the gap; the rest remains.

### 3.2 Step 2 (2020-01-02..2026-07-30, hold-out read #17, fitting on 2020+)

| comparison | diff %/yr | NW(39) t | offsets > 0 | LOYO min | 2020 dropped |
|---|---|---|---|---|---|
| **SA252 − EXP (primary)** | **+1.76** | **+1.04** | **33/40** | **+1.04 (drop 2025)** | **+2.09** |
| SA252 − R252 (reference) | −0.84 | −0.81 | 5/40 | −1.31 | |
| SA252 − live icw9_seas (reference) | +2.19 | +1.16 | 39/40 | +0.94 | |
| R252 − EXP (WO-33, reconcile) | +2.60 | +1.70 | 38/40 | +2.09 | |

- The Step 2 conditions on their own are met (mean > 0, 33/40 ≥ 30, positive with 2020 dropped).
  **Promote-candidate: NO**, because Step 1 is a KILL and Step 2 cannot rescue it.
- The t is +1.04 on about 6.5 years, well under the 2.39 bar.
- In this era the sign rule made R252 worse: SA252 is 0.84 below R252, and below it on 35 of 40 offsets.
  Flooring the wrong-signed factors (about 3 per refit) cost 0.84 against R252 in 2020–26.

**Book vs SPY, 2020–26 (net, mean of 40 offsets):**

| book | vs SPY %/yr | offsets beating SPY |
|---|---|---|
| SA252 | +0.17 | 20/40 |
| R252 | +1.02 | 35/40 |
| EXP | −1.59 | 4/40 |
| live icw9_seas (frozen) | −2.02 | 0/40 |

For 2010–2019 the same four books are +1.22 (SA252), +0.55 (R252), +1.66 (EXP) and +2.40 (live).

### 3.3 SA252 lands between R252 and EXP in both eras

In 2010–2019 EXP beats R252, and SA252 is in between (−0.44 vs EXP). In 2020–26 R252 beats EXP, and SA252
is again in between (+1.76 vs EXP). Flooring the wrong-signed factors moves the rolling rule part of the way
toward the slow rule. It is never the best of the three.

### 3.4 Turnover and cost (descriptive)

| era | book | new-name share per rebalance | cost drag %/yr |
|---|---|---|---|
| 2010–19 | SA252 | 0.573 | 0.55 |
| 2010–19 | R252 | 0.615 | 0.59 |
| 2010–19 | EXP | 0.490 | 0.47 |
| 2010–19 | live | 0.431 | 0.42 |
| 2020–26 | SA252 | 0.536 | 0.51 |
| 2020–26 | R252 | 0.565 | 0.54 |
| 2020–26 | EXP | 0.397 | 0.38 |
| 2020–26 | live | 0.446 | 0.43 |

- SA252 costs 0.08 (2010–19) and 0.13 (2020–26) more per year than EXP, and 0.04 and 0.03 less than R252.
- Cost is a small part of the Step 1 result: gross of cost, SA252 − EXP is −0.37, against −0.44 net.
- Mean L1 weight change per refit: SA252 0.278, R252 0.346, EXP 0.039 (2010–19); 0.268, 0.348, 0.054
  (2020–26).

Sign-rule binding shares are in §2.

### 3.5 Swap-one table, momentum_12_1 and net_issuance_pct only (descriptive, post hoc, no verdict)

Swap-in gain = (EXP with the factor's SA252 weight path) − EXP. Swap-out loss = (SA252 − EXP) − (SA252 with
the factor on EXP's path − EXP). The last column is WO-34's swap-in with R252's path (`r252_attrib.json`).

| era | factor | swap-in gain | offsets > 0 | t | swap-out loss | WO-34 swap-in (R252) |
|---|---|---|---|---|---|---|
| 2010–19 | momentum_12_1 | +0.07 | 26/40 | +0.28 | +0.40 | +0.41 (38/40) |
| 2010–19 | net_issuance_pct | +0.34 | 39/40 | +1.40 | +0.06 | +0.32 (37/40) |
| 2020–26 | momentum_12_1 | +0.05 | 23/40 | +0.11 | +0.68 | +0.39 (34/40) |
| 2020–26 | net_issuance_pct | +0.29 | 34/40 | +0.89 | +0.40 | +0.40 (34/40) |

- All four swap-ins are still positive.
- Momentum's swap-in gain mostly disappears under SA252 (+0.41 to +0.07; +0.39 to +0.05). Net issuance's is
  about the same as under R252.
- None is close to significant, and the two factors were picked after seeing WO-34's table. This is not
  evidence for a two-factor rolling rule.

### 3.6 Verdict

- **SA252: KILL at Step 1.** No change to the live weights, no forward ledger, no deploy.
- Family "time-varying weights" now stands at three trials and three kills (R252, R756, SA252). Per the
  pre-registration there are no further variants.
- On 2010–2019, weights fitted on more history beat weights fitted on the last year, with or without the
  sign rule. The frozen live weights beat EXP there too (+0.73, t +2.61, 40/40), but they were fitted on
  2007–2019, so that comparison is in-sample for them.
- On 2020–26 the rolling rules beat EXP on most offsets (33 to 38 of 40) with small t's (1.0 to 1.7), and
  the sign-aware version has less of the gain than plain R252.

**Caveats.**

- Step 2 fits on 2020+ data (hold-out read #17). Three rules from this family have now been read on 2020–26,
  so the window is not a clean out-of-sample test for any follow-up.
- The fitting frame (v1 cap150 for 8 factors) differs from the evaluation frame (v2 col c cap150), as in
  WO-33 and in the live rule.
- Short interest has no t before 2020, so it sits at the floor through Step 1 under every rule. Step 1 says
  nothing about sign-aware handling of short interest.
