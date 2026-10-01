# WO-37: thin-liquidity options probe (pre-registration)

Date: 2026-10-01 (written 2026-09-30). Commissioned by COO. Branch
`worktree-agent-ae91a1ed433cbce2d`. Status: **pre-registration**. This doc is
committed before any real-label number exists. The real run waits for the
small-cap chains (expected 2026-10-04 to 10-08) and for the arrival gate in
section 5.

The hypothesis is Gabe's (2026-09-17): prices and fundamentals are heavily
mined, so real edge is more likely in the options of thinly traded small and
mid-cap names, where fewer market makers compete. The cost of the same
thinness is wide spreads and stale quotes.

## 0. What this order computed, and what it did not

**No statistic relating an option quantity to a realized return on real labels
was computed.** That rules out any return spread, IC, t or put P&L on real
outcomes.

- Arm 1's runner was exercised only on labels permuted within each date, or on
  pure noise labels.
- Arm 2's runner was exercised only on noise settlement prices (lognormal draws
  at each contract's own IV). A within-date shuffle is not used for Arm 2,
  because it would keep each date's market move.
- Every file those runs wrote carries `_SHUFFLED_TEST` in its name.
- Coverage facts (section 6.1) use quotes, volume, open interest and the pull
  log only.
- No single-contract real settlement was computed either. Once the thin dates
  arrive, even the noise mode settles the named contracts of section 4 on real
  prices (those contracts only, never an aggregate), as WO-25 did.

**Correction to the order.** The order says thin-slice chains exist on the
first 33 dates. They exist on the **first 9** (2008-01-02 to 2008-08-20). From
2008-09-17 on, the pull log has no attempt for any thin-slice name. WO-25's
Amendment 1 says the same: "the Windows pull was cap2000-only from
2008-09-17". All 9 dates are in 2008, so they can't exercise the year-based
checks. Section 6.2 calibrates those on cap2000 with null labels instead.

## 1. Prior knowledge (stated so the trial count is honest)

- Median quoted option spread at the cap150 tier is about 26% of mid. On
  cap2000 the at-the-money spread by tier measured 8.4%, 15.0% and 22.4%.
- The stock composite shows no small-cap premium on the survivorship-safe
  grid: cap2000 +2.84, cap500 +2.66, cap150 +2.85 %/yr vs SPY. Any edge here
  has to come from the options information, not from a down-cap tilt.
- On cap2000, 2008-2018, `opt_cw_spread` (Cremers-Weinbaum call-minus-put
  implied volatility) has a sector-neutral rank IC with 40-day forward stock
  returns of +0.016 (Newey-West lag-39 t +3.54).
  - A descriptive decile split puts almost all of it in the bottom decile:
    -1.03% vs the date mean over 40 days, against +0.33% for the top decile.
    In this doc's metric (rest minus bottom) that is about +1.14% per 40 days.
  - As a weighted long-book factor it lowered the book, so it was not admitted.
  - The option-to-stock volume ratio has a neutral t of -4.77.
  - All of this is in-sample for 2008-2018 on cap2000, on the panel label
    `forward_return_tradable_40`.
- Options dead-end tally before this order: **18** (7 earlier, 5 option
  factors, 6 put-selling cells). Long calls and long puts on liquid names are
  certified dead ends.
- The choice of signal, of the bottom decile and of the 40-day horizon was made
  after seeing the cap2000 result. The thin slice is a disjoint set of names on
  every date, so it is out of sample in names. It is not out of sample in time.

## 2. Universe, window and labels (both arms)

- **Thin slice on date d:** `eligible_cap150 AND NOT eligible_cap2000` in
  `downcap_universe_v2.parquet` on d. About 2,060 names per date in 2008 and
  1,640 in 2018.
  - cap2000 is market cap >= $2B and price > $10. So the slice also holds
    fallen large caps under $10 (WaMu at $4.10 on 2008-08-20 is in it). It is
    "not cap2000", which is wider than "small cap".
- **Window: the 133 monthly dates from 2008-01-02 to 2018-12.** Nothing is fit.
  **No date from 2019 on is read, so this order uses no hold-out read.**
  - The run uses every window date on which the thin slice is at least 99%
    terminal in the pull log (section 5). The gate needs at least 120.
  - A later read of 2019-2026 would be a separate order. If it happens it is an
    unfitted hold-out read with **number to be assigned by COO**.
- **Arm 1 label:** `gross_return_40` from `outcome_cache_v2.parquet`. Entry at
  open[d+1], exit at close[d+40], and if the series ends first, exit at the
  last close (`build_outcome_cache.py`, checked in its code).
  - This differs from the cap2000 prior, which used the panel column
    `forward_return_tradable_40`. That column is NaN when a name delists inside
    40 days, which would drop exactly the names an avoid screen is meant to
    catch.
- **Point in time.**
  - The chain is the end-of-day snapshot of d. Open interest on row d is the
    prior close. Volume is d's own, complete at the close.
  - The universe flags use market cap, price and trailing 20-day dollar volume
    on d.
  - Entry is the next open (Arm 1) or the bid of d's closing quote (Arm 2, the
    WO-O1 convention).
- **Survivorship.** The universe includes delisted names, and the pull maps
  each to the symbol it traded under on d. Checks, all in `check_arrival.py`:
  - at least 99% of thin name-dates with a chain are in the panel and in the
    outcome cache (measured on the 9 dates: 100% and 100%);
  - later-delisted thin names have a chain at least as often as still-listed
    ones, within 5 points (measured: 64.1% vs 62.1%);
  - the named names of section 5.

## 3. Arm 1 (primary): avoid the bottom decile of `opt_cw_spread`, stock side

**Question.** Is option-implied information stronger where options are thin?
Trading the options at these spreads is very likely dead on arrival, so the
tradeable expression is in the stock.

**Mechanism.** Informed and short-constrained traders buy puts when shorting
the stock is costly. That pushes put implied volatility above call implied
volatility at the same strike (a low `opt_cw_spread`) before the stock price
adjusts. Thin names have fewer arbitrageurs to close that gap, so the stock
should lag by more. The counter-mechanism is that thin quotes are wide and
stale, so the mid-quote spread is mostly noise there. The test separates the
two. An avoid screen needs no shorting, so a hard-to-borrow name is not a
problem for it.

**Signal.** `opt_cw_spread`, sign +1, as built by
`build_av_options_features.py` (unchanged, imported): all expiries, matched
strikes, call IV minus put IV from Black-Scholes on mids, weighted by open
interest.

**Construction, per date d.**
- Pool: thin-slice names with a chain that passes the identity filter
  (`av_keep`), a non-missing signal and a non-missing label. A date needs at
  least 100 such names.
- Bottom decile: the lowest `round(0.10 x n)` names by signal. Ties break by
  ticker order.
- **M_d = mean label of the rest of the pool minus mean label of the bottom
  decile**, equal-weighted. Positive means the screen helps.
- Headline: M = mean of M_d over dates, in % per 40 days.
- Binding t: Newey-West with lag 39 on the M_d series, as the order specifies.
  On about 133 monthly dates this t is **not** conservative: under null labels
  its standard deviation is about 1.5, not 1 (section 6.2). The t thresholds
  below are therefore the intended 2.5 and 2.0 multiplied by 1.5. A lag-2 t is
  reported as descriptive.

**Null.** 100 within-date shuffles of the signal across the same pool, same
construction. The null level is the 80th percentile of the 100 shuffled M.

**Required checks.**
- Sector-neutral, both sides: the signal's within-date percentile rank and the
  label are each demeaned by sector within date, then the decile is cut on the
  demeaned rank.
- Halves: odd years, even years, chronological first half and second half.
- Leave one year out, and the share of sum(M_d) carried by the largest year.
- Two grid offsets: even-indexed and odd-indexed dates in time order.
- Size and volatility removed: within date, the signal rank and the label are
  each residualised on an intercept, the rank of log market cap and the rank of
  `volatility_60`. The decile is cut on the residual.

**Liquidity buckets are descriptive only.** Within each date the pool is cut
into terciles by total option open interest (prior close). M is reported per
tercile. No tercile can create a pass, so the buckets add no trial.

**Success: PASS needs all eight.**

| # | Criterion | Number |
|---|---|---|
| S1 | M above the shuffle null | M > null p80 and M > 0 |
| S2 | Newey-West lag-39 t | >= 3.75 |
| S3 | Economic floor | M >= +1.0% per 40 days |
| S4 | Sector-neutral | M > 0 and t >= 3.0 |
| S5 | Halves | odd, even, first and second all > 0 |
| S6 | Leave one year out | min > 0, and largest year share <= 45% |
| S7 | Offsets | both > 0 |
| S8 | Size and volatility removed | M > 0 and t >= 3.0 |

The S3 floor is close to the cap2000 in-sample figure (+1.14%). "Stronger
where thin" needs at least that. An avoid screen lifts the remaining
equal-weight book by one tenth of M, so +1.0% is worth about +0.6%/yr.
The same-date cap2000 M is computed by the same code in the real run and
reported as descriptive.

**Kill: any one.**

| # | Trigger |
|---|---|
| K1 | M <= null p80, or M <= 0 |
| K2 | The two offsets have opposite signs |
| K3 | Odd and even years have opposite signs |
| K4 | One year carries more than 45% of sum(M_d) |
| K5 | Sector-neutral M <= 0 |
| K6 | Size-and-volatility-removed M <= 0 |

Anything else is MIDDLE, and the COO decides. A PASS is a nomination, not an
admission: the next step would be a pre-registered test of the screen on the
live composite's own long book.

## 4. Arm 2 (secondary): cash-secured puts in the thin slice

**It cannot create a pass.** The order's verdict is Arm 1's. Arm 2 answers one
question: does the quoted premium in thin names survive honest fills?

**Mechanism.** With few market makers, option sellers should be paid more per
unit of risk. The cost is the half-spread, paid on every entry.

**Rules.** The WO-O1 backtester's, unchanged. `run_arm2.py` imports its
functions from `options_wo25/run_wo_o1.py`:
- first standard monthly expiry at least 14 days out;
- the quote filter F0 to F6 with Amendment 1's scoping of F2;
- the listed put nearest delta -0.30, within 0.075;
- sell 1 contract per name at the bid; collateral 100 x strike earning the
  3-month bill;
- settlement on Sharadar `closeunadj` with the split ratio and the delisting
  floor; assigned shares liquidated at 7.5bp;
- benchmark SPY price return plus 2.0%/yr; equal collateral weight per
  contract; annualised excess per cycle.

**What Arm 2 changes:** the universe (thin slice), one bucket only (0.30), no
score arm and no null, plus the fillable rule and capacity below.

**Fillable entry (verdict set).** An entry counts when all hold:
- the chosen put passes F0 to F6;
- its open interest is at least **50 contracts** (prior close);
- its bid size is at least **5 contracts**, on name-dates where AV populates
  sizes (WO-25's rule: at least 90% of the name's bid>0 contracts carry a
  size). Where sizes are not populated, size is unknown and is not held
  against the entry. Otherwise 2008-2009, where most sizes are missing, would
  drop out of a short-put book, which flatters it.
- Two variants are reported as descriptive: strict (size must be populated)
  and open-interest only.

**Capacity (verdict figure, volume-capped).** Per fillable entry, contracts =
min(bid size where populated, 10% of open interest rounded down, the
contract's own volume on the entry day). Dollars = contracts x 100 x strike.
The run reports the median and minimum monthly sum, and the premium dollars.
The same figure without the volume cap is reported as an upper bound only.

On the 9 early dates the volume-capped median is $19.2M a month, so **the
capacity thresholds below are not expected to bind. Arm 2's outcome will rest
on the return.** They stay in as a floor.

**Outcome wording.**
- SURVIVES: on the fillable set, annualised net excess vs SPY > 0, odd years
  > 0, even years > 0, leave-one-year-out min > 0, and median monthly capacity
  >= $250,000 of collateral.
- DEAD: net excess <= 0, or median monthly capacity < $100,000.
- MIDDLE otherwise.

**Named contracts (hard fail if filtered out).** A named name that is in the
thin slice with a kept chain on the date must be in the quoted pool whenever a
put inside the delta tolerance exists, and its payoff must equal
100 x max(K - r x S_T, 0) exactly.
- WAMUQ, entries 2008-08-20 and 2008-09-17.
- ATPAQ, entry 2012-07-18 (ATP Oil & Gas; its last Sharadar price is 2012-09-13).
- Measured now: WAMUQ on 2008-08-20 has a kept chain but **no put within the
  delta tolerance on the target expiry**. At $4.10 the listed strikes are too
  coarse. That is the general case (section 6.1): the put book reaches only
  23% of thin name-dates, and it under-reaches the cheapest, most distressed
  names. Read any Arm 2 result with that in mind.

## 5. Data-arrival gate and named presence checks

`check_arrival.py` writes `final/out/thinliq/arrival_gate.json`. The real run
recomputes it and refuses unless all hold:

1. **Gate.** The thin slice is at least 99% terminal in the pull log on at
   least 120 of the 133 window dates. Terminal is `ok` or `no_data`. The log's
   `pass` label is not filtered, in case the thin pull is logged under another
   name. Today: 9 of 133.
2. **Dead names** (Sharadar `isdelisted = Y`, both thin with a kept chain on
   all 9 early dates today):
   - **ATPAQ** (ATP Oil & Gas): thin on 54 window dates, 2008-01-02 to
     2012-07-18. Must have a kept chain on **2012-06-20**.
   - **SIGM** (Sigma Designs, liquidated 2018): thin on 123 window dates,
     2008-01-02 to 2018-07-18. Must have a kept chain on **2018-06-20**.
   - Each must also have a kept chain on at least 90% of its thin dates that
     are complete, and on all 9 early dates. `no_data` is terminal but is not a
     chain.
3. **TXG.** Sharadar's first price is 2019-09; the pull log shows `no_data` on
   2019-10-16 and 2019-11-20 and the first chain on **2019-12-18** (options
   list some weeks after an IPO).
   - It is cap2000 from then to 2024-09 and again in 2026, and has a chain in
     the store on all 66 of those dates.
   - It is in the thin slice only on the 15 dates from **2024-10-16 to
     2025-12-17**. Those are outside the window, so TXG is a data check, not
     part of either arm. It must have a chain on every one of those dates the
     thin pull has attempted. Until they are pulled it shows "pending" and does
     not block.
   - Its 2026-03-18 chain is in the store but 8% off parity, so the 5%
     identity filter drops it. That is the filter working, not a gap.
4. **Pool integrity** and **dead vs listed chain share** (section 2).
5. The pre-registration doc is tracked in git, the chain and features are
   newer than the store, and no earlier result file exists.

## 6. Plumbing results (null labels and quote-side facts only)

### 6.1 Coverage on the 9 thin dates (`coverage_thin_early_dates.json`)

| Fact | Thin slice | cap2000, same dates |
|---|---|---|
| Names per date (median) | 2,061 | 986 |
| Share with a chain in the store | 63.4% | 94.5% |
| Share `no_data` (no listed options) | 36.6% | 5.2% |
| Names with a kept chain per date | 1,299 | 929 |
| Of those: any option volume that day | 84.7% | 96.9% |
| Of those: median option volume, contracts | 70 | 888 |
| Of those: median total open interest, contracts | 5,314 | 37,530 |
| Of those: median spread near the money, share of mid | 17.6% | 8.2% |
| Of those: share with `opt_cw_spread` | 98.9% | 99.8% |
| Share of all names with any option volume | 52.9% | 91.0% |

Arm 2's chosen put (delta 0.30, about 30 days):

| Fact | Thin slice | cap2000, same dates |
|---|---|---|
| Name-dates with a put inside the tolerance | 23.0% of all | 51.4% of all |
| Of those: passes the quote filter | 96.4% | 98.5% |
| Median spread of the chosen put, share of mid | 34.0% | 14.0% |
| Median open interest of the chosen put | 100 | 815 |
| Chosen put had zero volume that day | 57.8% | 21.4% |
| Quoted entries with sizes populated | 26.4% | 21.3% |
| Of those: bid size >= 5 | 99.3% | 98.4% |
| Of those: fillable (size and open interest) | 47.3% | 66.9% |
| Open interest >= 50, all quoted entries | 60.1% | 88.8% |
| **Fillable under the rule, share of quoted** | **60.0%** | 88.5% |
| Fillable, share of all name-dates | 13.3% | 44.9% |
| Fillable entries per month (median) | 286 | 448 |
| Fillable entries whose put traded that day | 58.6% | 85.2% |
| Entries with capacity per month (median) | 159 | 375 |
| **Capacity, volume-capped: collateral per month (median)** | **$19.2M** | $430M |
| Capacity, volume-capped: collateral per month (minimum) | $14.6M | $289M |
| Capacity, volume-capped: premium per month (median) | $0.98M | $12.1M |
| Upper bound, open-interest rule only: collateral per month | $49.7M | $663M |

What this says for the subscription decision:
- **Capacity is not the constraint, even capped at each contract's own daily
  volume.** About 159 puts a month both pass the rule and traded that day,
  for about $19M of collateral and $1M of premium. The open-interest rule
  alone gives $50M, but 41% of those entries did not trade that day, so read
  the $19M figure. The fillable share is not tiny.
- Volume on the day is not a promise of a fill at the bid. It is the best
  quote-side bound the data allows.
- **The spread is the constraint.** The chosen put's median spread is 34% of
  mid. On noise labels the fillable set loses about 3 to 5%/yr to the
  half-spread alone (section 6.3). Real premium has to clear that first.
- **The evidence is weak in two ways.** It is 9 dates, all in 2008. And AV
  populates bid sizes on only 26% of these entries, so the size leg of the rule
  is mostly unmeasured here. Where it is measured, size is almost never the
  binding leg; open interest is.
- These spreads are a little below the prior 26% figure because the slice pools
  the cap500 and cap150 tiers.

### 6.2 Arm 1 on null labels

The 9 thin dates are all in 2008, so the calibration runs on **cap2000,
2008-01 to 2018-12** (133 dates, median 1,137 names with a signal, 96% of the
tier), where the store is complete. 100 label seeds each, every seed through
the full decision rule with its own 100-draw shuffle null. The metric is a
within-date difference, so permuted labels carry no market path.

| Rate over 100 seeds | Labels permuted within date | Noise labels |
|---|---|---|
| **PASS (all eight)** | **0%** | **0%** |
| KILL | 95% | 93% |
| MIDDLE | 5% | 7% |
| S1 M above null p80 (design rate 20%) | 19% | 23% |
| S2 t >= 3.75 | 1% | 1% |
| S3 M >= +1.0% | 0% | 0% |
| S4 sector-neutral | 0% | 1% |
| S5 halves all positive | 15% | 17% |
| S6 leave one year out and year share | 7% | 14% |
| S7 both offsets positive | 23% | 25% |
| S8 size and volatility removed | 2% | 2% |

- Null-label M has mean -0.02% and standard deviation 0.11% per 40 days
  (permuted), so the +1.0% floor is about 9 standard deviations out on cap2000.
  The thin slice is noisier, and its null spread is unknown until the run.
- **The lag-39 t is oversized.** Under null labels its standard deviation is
  1.53 (permuted) and 1.49 (noise). A threshold of 2.5 was crossed by 4% and
  6% of seeds, against a nominal 0.6%. With 3.75 it is 1% and 1%. This
  contradicts WO-25's note that lag 39 is "very conservative", and it applies
  to any lag-39 t on these monthly dates, including the cap2000 prior of +3.54.
- Thin slice, 9 dates, 100 seeds (smoke test only): PASS 0%, KILL 100%. S1
  fires on 25% (permuted) and 30% (noise) of seeds. The t is undefined below
  10 dates, so a pass is impossible there by construction.
- Files: `arm1_nullcal_SHUFFLED_TEST_{cap2000,thin}_labels-{shuffled,noise}.json`.

### 6.3 Arm 2 on noise labels (`arm2_results_SHUFFLED_TEST_labels-noise_seed{7,8}.json`)

- 9 entry dates, 4,164 quoted positions, 2,497 fillable.
- **Hand-checked contracts** (`run_arm2.hand_check`, runs in every mode and
  aborts on a mismatch):

  | Case | By hand | Code |
  |---|---|---|
  | K 10, bid 0.50, S_T 8, bill 2%, 30 days: 50 - 200 - 0.60 + 1.629 | -148.971 | -148.971 |
  | Same with a 2:1 split, unadjusted S_T 4.5: 50 - 100 - 0.675 + 1.629 | -49.046 | -49.046 |
  | Same, S_T 12, expires worthless: 50 + 1.629 | +51.629 | +51.629 |

  `settle()` returns split ratio 2.0 from the adjusted and unadjusted closes,
  and the last close with status `delisted_floor` when the series ends early.
- **Noise unit test.** Mean cycle excess vs the analytic expectation:
  -0.40% vs -0.50% (seed 7, z +0.62) and -0.59% vs -0.50% (seed 8, z -0.76).
  The arithmetic reproduces the expected loss of about one half-spread.
- Annualised, the fillable set on noise loses 3.4%/yr (seed 7) and 4.8%/yr
  (seed 8). These are noise-label numbers, not results.

### 6.4 Guard (`guard_test.json`)

`--phase2` refuses on each ground separately: doc not tracked in git; arrival
gate (9 of 133 dates); a result file already exists.

## 7. Decision rules, tally, iteration cap

- **Verdict = Arm 1's** PASS, KILL or MIDDLE. Arm 2 is reported next to it.
- **Trial tally.** 18 before this order. Arm 1 adds 1. Arm 2 adds 1 (one
  bucket, one arm). **Running total after the real run: 20.** The liquidity
  terciles, the cap2000 comparison and Arm 2's two variants are descriptive and
  can't pass, so they add none.
- **Iteration cap: 3.** Any change to this spec after a real-label number
  exists is an iteration. It is written into this doc and committed before it
  runs, and each one past the first is an extra look in the tally.
- **Hold-out reads: none.**

## 8. Commands for the real run

Run from a checkout that has this branch or `integration` after landing. The
scripts read data from the main checkout by absolute path and write to
`final/out/thinliq/` of the checkout they run from. Parquet outputs are
gitignored.

    PY=/opt/anaconda3/envs/pipe_dream/bin/python
    # 0. arrival gate and presence checks (exit 0 only when Phase 2 is allowed)
    $PY final/src/thinliq/check_arrival.py
    # 1. rebuild chain and features from the merged store (incremental)
    $PY final/src/thinliq/build_chain.py
    # 2. Arm 1, real labels, one shot
    $PY final/src/thinliq/run_arm1.py --phase2
    # 3. Arm 2, real settlement, one shot
    $PY final/src/thinliq/run_arm2.py --phase2

Plumbing commands used for section 6:

    $PY final/src/thinliq/coverage.py
    $PY final/src/thinliq/run_arm1.py --labels shuffled --universe cap2000 --seeds 100
    $PY final/src/thinliq/run_arm1.py --labels noise --universe cap2000 --seeds 100
    $PY final/src/thinliq/run_arm1.py --labels shuffled --universe thin --seeds 100
    $PY final/src/thinliq/run_arm2.py --labels noise --seed 7
    $PY final/src/thinliq/test_guard.py

## 9. Files

- `final/src/thinliq/tl_common.py`: constants, thin slice, arrival gate, guard.
- `final/src/thinliq/build_chain.py`: chain and features into `final/out/thinliq/`.
- `final/src/thinliq/check_arrival.py`: gate and presence checks.
- `final/src/thinliq/coverage.py`: quote-side coverage facts.
- `final/src/thinliq/run_arm1.py`, `run_arm2.py`: the two arms.
- `final/src/thinliq/test_guard.py`: guard refusal test.
- `final/out/thinliq/*.json`: gate, coverage, null-label and guard outputs.

## 10. What changed from the COO's design, and why

1. **9 plumbing dates, not 33** (section 0).
2. **Label is `gross_return_40`, with the delisting floor,** not the panel
   column the cap2000 prior used (section 2).
3. **Metric sign:** rest minus bottom decile, so every threshold sits on the
   same side.
4. **Liquidity bucketing is descriptive.** A bucket that could pass would
   multiply the trials.
5. **Null calibration runs on cap2000 with null labels,** because 9 dates in
   one year can't exercise the checks.
6. **TXG is outside the window** and is a data check from 2019-12-18, not from
   its 2019-09 listing (section 5).
7. **Unknown bid size is not held against an Arm 2 entry** (section 4).
8. **An economic floor (S3) and capacity thresholds were added,** so success
   and kill are numbers.
9. **A dead-versus-listed chain-share check was added** to the arrival gate.
10. **The t thresholds are 3.75 and 3.0, not 2.5 and 2.0,** because the lag-39
    t is oversized by about 1.5 under the null (section 6.2). Lag 39 itself is
    kept, as ordered.
