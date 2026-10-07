# WO-48b: drop the floor-weight factors? (parsimony test)

2026-10-07. Follow-up to WO-48 (`2026-10-07-factor-sign-construction.md`),
requested by Gabe: "Test first, also include short interest days to cover in
that assessment." Code: `final/src/signcheck/dropcheck.py`. Outputs:
`final/out/signcheck/drop/`. No live deploy, no weight change. A DROP is a
recommendation for the next batch retune; the decision is Gabe's.

## 1. Pre-registration (committed and pushed before any number below is computed)

**Why a new test.** WO-48's gate compared a one-factor change with base sd40
(0.223 pp/yr, the offset-to-offset spread of the whole book). A factor at
~1% of |w| cannot clear that, so WO-48 could not fail to CLOSE. Gabe: "you
should lower your bar for what counts as a result because you cant have both
many small weights and then only a big weight can disprove them". He also
wants the most parsimonious model. So this test asks the parsimony question
directly, with a bar that scales with the weight: do the floor-weight
factors beat noise of the same weight? If not, drop them.

**Disclosure.** Before this pre-registration, one descriptive number was
computed (2026-10-07, `$CLAUDE_JOB_DIR/tmp/drop3.py`, not committed) and shown
to Gabe: arm D3 (below) in 2007-2019, D3 − base = +0.16 pp/yr, 35/40, LOYO
min > 0, jackknife t 1.10; from 2011-10-01 −0.02, 20/40. The gain sits in
2008-2010. No 2020+ number, no D4 number and no null has been computed for
either arm. Because 2007-2019 for D3 is already seen, **2020-2026 is the
deciding era**; 2007-2019 is descriptive for both arms.

**Factors at the floor weight |w| = 0.0105 in icw9_seas**
(`ICW.PRODUCTION_WEIGHTS_V9_SEAS`):
`pct_from_high_252` (+), `volatility_60` (−),
`days_to_next_filing_seasonal` (−), `short_interest_days_to_cover` (−).

**Arms (2 trials).**
- **D3:** drop `pct_from_high_252`, `volatility_60`,
  `days_to_next_filing_seasonal`.
- **D4:** D3 plus `short_interest_days_to_cover`.

In each arm the dropped weights are set to 0 and the remaining weights are scaled to the same total
|w|. There is no refit. `composite_score` divides by the covered |w|, so the
rescale does not change ranks.

**Harness.** This is the WO-48 path (`signcheck.score`, `picks_fast` = `stateint.fast_pick`,
`drag_decomp.chains`):
- v2 grid column c, cap150, decile_volq;
- label `gross_return_40`, 40 offsets;
- 15 bp cost, excess vs SPY.

The eras come from `model_audit_wo23.PERIODS`:
- **A** = 2007-01-02..2019-12-31 (the `stateint.load_all` frame);
- **B** = 2020-01-02..2026-07-30, loaded with `MA.load_theo("B", "cap150")`, the same
  SEAS_EXT that WO-40 used. **This is hold-out read #21**: unfitted, frozen weights,
  nothing chosen on 2020+.

**Statistic.** K = base − arm, the value of keeping the dropped factors, as the 40-offset
mean of annualised net excess vs SPY.

**Null (paired, weight-scaled).** There are 100 draws, s = 0..99. In draw s, each dropped
column of the arm is permuted within date, independently. The permutation uses
`screen_insider_v2grid.shuffle_within_date` on the raw column, then
`rank_z`. The seed is 48000 + 1000·i + s, where i is the factor's position in the
list above, so D3 and D4 share the shuffles for their common columns. The
shuffled columns are kept at their live weights. Each draw gives
K_null = shuffled-book − arm: what noise at the same weight "earns" over
dropping. **p80 = 80th percentile of K_null** (40-offset means).

**Outcome rule (fixed now, era B only, per arm).**
- **KEEP** if K_B > 0 **and** K_B > p80_B. The real factors beat the drop book and beat at least 80% of
  same-weight noise books.
- **DROP** otherwise. Parsimony is the default.

The offsets-positive, LOYO, year-share and jackknife statistics are reported
for both eras. They are **not** in the gate, which is deliberately lower than WO-48's.

**Recommendation mapping (fixed now).**
- D3 DROP and D4 DROP → recommend dropping all four at the next batch retune.
- D3 DROP and D4 KEEP → recommend dropping the three and keeping
  `short_interest_days_to_cover`.
- D3 KEEP → keep all four. D4 is reported only.

**Descriptive (no gate).**
- Era A: K and null for both arms, plus K and offsets from 2011-10-01.
- Era B: offsets, LOYO by dropped year (2020 included), per year.
- `short_interest_days_to_cover` alone, era A: WO-48-style LOO (K for dropping it
  alone) and a 100-draw single-column null (seeds 3000 + s).

**Checks before trusting a number.**
- Era A base reconciles to +0.0348652 (WO-31 exact < 1e-10).
- Era B base icw9_seas reconciles to `rollweights.REF_B_LIVE` = −0.02016365566661011
  (< 1e-6).
- In both eras the fast picker equals `pool_read.picks_w` on every date.
- The identity book gives K = 0 exactly.
- Era A hold-out assert (< 2020-01-01); era B dates ≤ 2026-07-30.
- Null draw 0 of each arm in each era, re-run, gives an identical number.

**Logging.** Hold-out read #21 is logged in COO.md Hold-out status before any era B
number is computed. Era B numbers are always shown next to era A.

## 2. Results (computed 2026-10-07, after the pre-registration was pushed as 9d3b891)

Report: `final/out/signcheck/drop/dropcheck_report.json`; logs:
`final/out/signcheck/drop/logs/`. K = base − arm, the value of keeping the factors, in pp/yr.
K < 0 means the book without them did better.

**Verdict (pre-registered rule, era B): D3 DROP, D4 DROP → recommend
dropping all four floor-weight factors at the next batch retune.** No live
change; Gabe decides.

| | era | K | K > 0 offsets | null p50 | null p80 | real vs null (pct of null below K) | jackknife t | verdict |
|---|---|---|---|---|---|---|---|---|
| D3 | B 2020-26 | −0.065 | 18/40 | −0.028 | +0.035 | 0.31 | −0.04 | **DROP** (K < 0) |
| D4 | B 2020-26 | −0.045 | 19/40 | −0.175 | −0.103 | 0.93 | −0.03 | **DROP** (K < 0) |
| D3 | A 2007-19 | −0.158 | 5/40 | −0.083 | −0.066 | 0.00 | −1.10 | descriptive |
| D4 | A 2007-19 | −0.158 | 5/40 | (same as D3, see below) | | | | descriptive |

**Checks:**
- Era A base +0.0348652 and era B base −0.0201636 both reconcile, to < 1e-6 against the stated refs.
- The fast picker equals `picks_w` on all 3,272 and 1,652 dates.
- The identity book gives K = 0.
- The hold-out assert passed.
- Null draw 0, re-run, is identical for every arm in both eras.

**What it says.**
- **2007-2019:** the three factors cost 0.16 pp/yr. That is worse than
  replacing them with noise of the same weight: all 100 noise books did
  better than the real factors. Most of the cost is in 2008-2010 (K −0.45,
  −0.84, −1.44). From 2011-10 on, K is +0.02, which is flat.
- **2020-2026:** K is close to zero for both arms and very noisy. sd40 is 0.70-0.82 pp,
  against 0.13 in era A, and the jackknife t is about 0. Two years swing hard
  and cancel: 2020 K +5.9 pp, 2021 K −7.1 pp, with picks still 96% the same as
  base. 2022-2026 is small (D3: +0.11, +0.07, −0.05, +0.64, −0.30). Era B
  neither shows nor rules out a small benefit. Under the parsimony default
  that means DROP, which is the rule Gabe asked for.
- **Short interest:**
  - **No data before 2020:** `short_interest_days_to_cover` has 0% coverage in cap150
    for 2005-2019, so before 2020 it never entered the score. In era A, D4 = D3 exactly, the
    SI-alone LOO is 0 and its null is all zeros. The pre-registered era A
    SI-alone test is therefore empty. Coverage in 2020-26 is 61%, 86%, 91%, 95%, 96%, 98% and 99% by year.
  - **2020-2026 increment over D3:** SI adds +0.02 pp/yr of K (D4 −0.045 vs D3 −0.065).
    The real columns beat 93% of same-weight noise books in D4, against 31% in D3.
    That is a weak hint that SI carries some information. It is not enough to pass the gate,
    because the book without it still did slightly better.

**Caveat for the decision.** This is a parsimony verdict. It is not evidence that the
factors hurt in 2020-2026. The deciding era is dominated by 2020-2021
noise. The verdict says there is no detectable benefit from keeping them. Dropping is a
weight change (live |w| total unchanged, remaining six scaled up by about 4%), for the next batch retune.

### Docs for README
This doc (WO-48b). Recommendation: drop the four floor-weight factors at the
next batch retune (Gabe's call); SI has no pre-2020 data.
