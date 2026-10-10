# WO-50 amendment (pre-outcome): the cap2000 population is a subset of cap150, not a superset

Written 2026-10-10 by the WO-50 outcome-run worker (branch `wo50-ind-mom-run`), BEFORE any
outcome statistic (no factor IC, placebo IC, null draw or icw6 book number has been computed).
It changes nothing in the frozen spec. The pre-registration
`final/models/2026-10-08-industry-momentum.md` is untouched (sha256 c686ad7e...cc16, asserted
at import by every WO-50 script).

## What the pre-reg assumed and what is true

Section 1.4 step 1 builds the group population from "ALL rows with `eligible_cap2000 == True`
... (not just cap150)". The parenthetical assumes cap150 sits inside cap2000. It is the other
way round: the tiers are market-cap floors.

| tier (v2 grid, 2014-06-30) | names | min market cap | median market cap |
|---|---|---|---|
| eligible_cap2000 | 1,382 | $2.00B | $5.75B |
| eligible_cap500 | 2,449 | $0.50B | $2.59B |
| eligible_cap150 | 3,213 | (floor $150M) | $1.54B |

On 2007-2019, 5.96M of 9.76M raw-panel cap150 rows are outside cap2000.

## What is executed (literal reading, no spec change)

- Population, group key, fallback and value exactly as in 1.4 steps 1-3 (cap2000, SPAC filter
  via `load_theo("A", "cap2000")`, industry, then sector below 5 members, then NaN).
- Step 4, "Assigned to each cap150 row by (ticker, date)", is done as a key join. A cap150 row
  that is not a cap2000 population member (or whose own `momentum_12_1` is NaN) gets NaN. It is
  not given its industry's mean. Giving it one, or widening the population to cap150, would
  change the spec, and only the pre-reg owner (COO / Gabe) can approve that as a new trial.
- Downstream code is unchanged. The composite is coverage-aware, so rows without a value get no
  ind_mom contribution. Gates 1-5 IC, the gate 3 residual and the gate 6 shuffle null all run
  on the rows that have a value.

The frozen descriptives agree with this construction, which shows it is the registered one:
2,789 of 2,789 cap2000 tickers found in tickers_master, 10.51% of cap2000 rows in industry
groups under 5 (pre-reg about 10.5%), and 0.0096% of rows missing `industry` (pre-reg 0.01%).

## Coverage (outcome-free; `final/out/indmom/parts/coverage.json`)

On the harness universe `D.load("A")` (cap150, SPAC-filtered, 9,756,141 rows, 3,272 dates):
- 37.9% of cap150 rows have a finite `ind_mom_12_1`. By year it rises from 28-32% in 2007-2010
  to 45-46% in 2018-2019.
- The median date has 1,147.5 names with a value, out of a median 3,008 cap150 names.

In practice, this screen tests industry momentum on the large-cap (>= $2B) part of the cap150
book.

## Other descriptive note (does not block)

The pre-reg (1.3) reported that 0.73% of 20,965 common tickers changed `industry` between
`tickers_master_through_2026-09-08.csv` and `tickers_master.csv`. Recomputed today, the share
is 0.00% on 20,964 common tickers. `tickers_master.csv` now has 21,014 stocks rows, last
updated 2026-09-25, and the old snapshot has one duplicated ticker. Either file may have been
refreshed since the pre-reg was written. The run uses `tickers_master.csv` as registered, with
sha256 recorded in `final/out/indmom/parts/build.json`. This number is descriptive only and
feeds no gate.

## Integrity work done before outcomes (gate 7 parts a and c, `final/out/indmom/indmom_integrity.json`)

- (a1) On 8 random dates, the factor rebuilt from rows dated <= t matched the cache exactly.
- (a2) Every panel close after 2013-06-28 was multiplied by 7. Momentum was recomputed from
  close (shift 21 / shift 252) and the factor rebuilt. All 1,577,859 rows on or before the cut
  were unchanged. 12.9% of later rows changed, which shows the test bites. The recomputed
  momentum matched the panel `momentum_12_1` on 100% of 3.70M overlapping rows.
- (a3) Nothing dated on or after 2020-01-01 was loaded.
- (c) Hand checks matched to 1e-12:
  - XOM, 2014-06-30: sector fallback (Energy, 141 members).
  - JPM, 2009-06-30: sector fallback (Financial Services, 102 members).
  - INTC, 2017-06-30: industry (Semiconductors, 29 members).
  All three are cap150-eligible.
- Gate 7(b) (the placebo) is an outcome-adjacent IC, so it runs with the real screen.
