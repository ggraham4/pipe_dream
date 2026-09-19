# Factor-composite reset -- holdout era report

Offset-averaged over all 40 grid offsets actually completed (see PREREGISTRATION.md section 5). Not offset-0.

## cap2000_raw: NO COMPLETED OFFSETS YET

## cap2000_neutral: NO COMPLETED OFFSETS YET

## cap500_raw: NO COMPLETED OFFSETS YET

## cap500_neutral: NO COMPLETED OFFSETS YET

## cap150_raw  (40/40 offsets completed)

### decile_volq, 15bp round-trip
- excess CAGR vs SPY: **+1.85%/yr** (sd across offsets 0.95%, range [-0.49%, +3.51%], 39/40 offsets positive)
- between-offset bootstrap 95% CI: [+1.54%, +2.14%]
- excess CAGR vs USMV: **+8.99%/yr**
- mean calendar years beaten: 3.0 of 7.0
- mean percentile vs matched shuffle null: 98%

### decile_volq, 50bp round-trip
- excess CAGR vs SPY: **+0.69%/yr** (sd across offsets 0.95%, range [-1.65%, +2.34%], 32/40 offsets positive)
- between-offset bootstrap 95% CI: [+0.38%, +0.98%]
- excess CAGR vs USMV: **+7.83%/yr**
- mean calendar years beaten: 2.9 of 7.0
- mean percentile vs matched shuffle null: 98%

### topn_ew, 15bp round-trip
- excess CAGR vs SPY: **-4.80%/yr** (sd across offsets 1.23%, range [-7.66%, -1.66%], 0/40 offsets positive)
- between-offset bootstrap 95% CI: [-5.17%, -4.40%]
- excess CAGR vs USMV: **+2.64%/yr**
- mean calendar years beaten: 1.8 of 7.0
- mean percentile vs matched shuffle null: 2%

### topn_ew, 50bp round-trip
- excess CAGR vs SPY: **-6.02%/yr** (sd across offsets 1.23%, range [-8.88%, -2.88%], 0/40 offsets positive)
- between-offset bootstrap 95% CI: [-6.39%, -5.62%]
- excess CAGR vs USMV: **+1.43%/yr**
- mean calendar years beaten: 1.8 of 7.0
- mean percentile vs matched shuffle null: 2%

## cap150_neutral: NO COMPLETED OFFSETS YET


## Nomination-era leader (15bp, excess vs SPY): **cap150_raw / decile_volq** at +1.85%/yr

Per PREREGISTRATION.md section 8, this is a candidate for the ONE hold-out confirmation, subject to LOYO and Gate A checks not yet run here.

## Leave-one-year-out on the hold-out itself -- READ BEFORE TRUSTING THE +1.85%/yr ABOVE

Per-calendar-year excess vs SPY, `cap150_raw`/`decile_volq`, 15bp, averaged over all 40 offsets:

| year | excess vs SPY | offsets positive |
|---|---|---|
| 2020 | +23.98% | 40/40 |
| 2021 | -5.60% | 2/40 |
| 2022 | +11.98% | 40/40 |
| 2023 | -9.91% | 0/40 |
| 2024 | -4.39% | 1/40 |
| 2025 | -7.32% | 0/40 |
| 2026 (partial) | +2.94% | 36/40 |

**Leave-one-year-out:**

| year dropped | remaining mean |
|---|---|
| 2020 | **-2.05%** |
| 2021 | +2.88% |
| 2022 | -0.05% |
| 2023 | +3.60% |
| 2024 | +2.68% |
| 2025 | +3.17% |
| 2026 | +1.46% |
| both 2020 and 2022 | **-4.86%** |

**This fails the same leave-one-year-out standard that already killed one
result in this project (Round 14's `rate_beta_x_move`, 45% of its effect from
a single year).** Here it is worse: exactly TWO of seven years (2020's
COVID-crash recovery, 2022's growth-factor unwind) are positive, the other
five are ALL negative, and dropping 2020 alone flips the seven-year mean
negative. The headline `+1.85%/yr, beats its null on 98% of offsets, 39/40
offsets positive` is a true description of the point estimate and its
within-sample stability across grid offsets -- it is NOT evidence the mean is
bounded away from zero across independent years, which is what
`years_won_vs_spy: 3.0 of 7.0` was already hinting at before this table made
it explicit.

**The honest read, not split the difference:** small-cap value/quality/low-vol
composites are known to concentrate their edge in market dislocations and
factor-rotation years (2020's crash-and-recovery, 2022's growth unwind are
textbook examples for exactly this factor mix) and go quiet or lose money in
calm, momentum/growth-led stretches (2021, 2023-2025 here) -- which is a
real, economically sensible PATTERN, not necessarily a coincidence to explain
away. But seven years is too few to distinguish "this composite structurally
outperforms in dislocation regimes and should be sized for that" from "two
lucky years happened to land in this hold-out." This project's own hold-out
discipline does not allow re-drawing a second hold-out to settle it. Nothing
here overturns the nomination-era result, which passed the identical LOYO
test cleanly across 13 years -- but the number to carry forward from THIS
package is "a real, sector-neutral-robust, monotonic-in-cap signal that has
NOT yet demonstrated year-to-year robustness out of sample," not "beats SPY,
confirmed."

**topn_ew's outright hold-out failure is the second finding that belongs
next to this one.** The exact same composite scores, same dates, same
tier -- only the portfolio construction changed (flat top-5% instead of
top-decile-within-each-volatility-quintile) -- and the result flips from
+1.85%/yr to **-4.80%/yr, 0/40 offsets positive, worse than 98% of its own
null**. The vol-quintile bucketing is not a cosmetic detail on top of a
robust stock-selection signal; it is load-bearing, and a meaningful share of
whatever this composite is capturing lives in HOW the picks are turned into
a portfolio, not only in WHICH names it ranks highest. That does not
disqualify `decile_volq` -- it was the pre-registered choice, chosen for a
reason (matches the deployed model's own construction) -- but a result this
sensitive to a portfolio-construction choice that was not itself
cross-validated is a second reason for measured confidence, not celebration.
