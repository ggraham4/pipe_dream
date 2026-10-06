# WO-46: per-stock state labels as factor interactions

2026-10-02. COO work order WO-46 (Gabe's idea: "GAM or something to classify
stocks… oversold / bull run… discrete variable"; launch approved 2026-10-02).
Code: `final/src/stateint/stateint.py`. Outputs: `final/out/stateint/`.
Nothing here changes live weights and nothing is promoted by this order.

## 1. Pre-registration (committed before any state-conditional number)

**Hypothesis.** A per-stock state label has no new payoff on its own
(oversold = the reversal family, closed; bull run = momentum_12_1, in the
book). A discrete state can only add value as an interaction: an existing
factor pays differently depending on the stock's state. Zero-fit test: no
classifier, no GAM, no fitted parameter.

**Era.** 2007-01-02..2019-12-31 only (3,272 rebalance dates, first
2007-01-03). No hold-out read. SEP is read through 2019-12-31 and the panel
through 2019-12-31; the code asserts both. The 40-day labels of the last
rebalance dates of 2019 end in early 2020. They come from `outcome_cache_v2`
unmasked, as in every prior screen (Gabe's WO-13 ruling); this is needed to
reconcile to the published book number.

**Universe and harness.** v2 grid column c, cap150, h=40, tradable label
close[t+40]/open[t+1] (`gross_return_40`, `outcome_cache_v2`), decile_volq,
15 bp turnover cost, 40 offsets. Loader `model_audit_wo23.load_theo("A")`
(9,756,141 rows, 6,508 tickers). Imported read-only:
`screen_insider_v2grid` (Book, shuffle_within_date, ic_gates, gate6,
reconcile), `screen_insider` (rank_z, composite_score),
`composite.pick_decile_volq`, `pool_read.picks_w`, `drag_decomp`,
`trailfilter` (chains2, picks_fullsize, cash_fill, diff_stats, book_stats),
`run_backtest.turnover_net_return`. The live book is icw9_seas with
`ICW.PRODUCTION_WEIGHTS_V9_SEAS`; factor signs are the signs of those weights.

The only new arithmetic is `fast_pick`, a numpy version of
`pick_decile_volq` + `Book.picks` (same `pd.qcut` and `argsort` calls) needed
to run 100 null draws. It is hard-asserted equal to `Book.picks` (same names,
gross within 1e-12) on 9,816 pooled dates and 26,176 state-subset dates.

**States** (prices up to and including t, the name's own SEP bars,
split-adjusted `close` on both sides):

- (a) `hi52` = close[t] / max(close over the 252 bars ending at t).
- (b) `vol60` = standard deviation of the last 60 daily close-to-close returns.
- State quintile: within date, ordinal rank among names with a finite value,
  ties broken by ticker order, five equal-count groups. Q1 = lowest value
  (a: furthest below the high; b: calmest), Q5 = highest. A name with fewer
  than 252 (a) or 61 (b) bars has no state and is in no quintile.

**Finding before any run: neither state is new to this project.** Measured in
the prep stage, with no returns involved:

| state | panel column already in the book | max abs difference | finite on the same rows |
|---|---|---|---|
| `hi52` | `pct_from_high_252` + 1 (icw9_seas weight +0.0105) | 1.5e-16 | yes, 95.6% |
| `vol60` | `volatility_60` (icw9_seas weight −0.0105, and the decile_volq bucketing variable) | 0 | yes, 99.1% |

Consequences, fixed here:

- The work order calls the 52-week-high effect "not previously tested here".
  It was: `pct_from_high_252` is one of the 8 original factors, full-era IC t
  +0.84 on the old grid (`ic_weighted_composite_report.json`), in the book at
  the floor weight. Test 3 is therefore a re-screen of an in-book factor, not
  a new family. It is run as ordered and labelled as such; the COO decides how
  to count it.
- Two of the 18 cells sort a factor inside quintiles of itself
  (`pct_from_high_252` × a, `volatility_60` × b). They stay in the count of 18
  as the order fixes it, and are flagged `self_conditioning_cell`.
- Inside a vol60 state quintile, decile_volq re-splits an already narrow
  volatility range into five buckets.
- The two states are strongly related: 10.2% of names are in hi52 Q1 and
  vol60 Q5 at once (4% expected if independent), 0.3% in hi52 Q1 and vol60 Q1.
- The states are not changed. They are runnable as specified.

**Test 1: interaction cells (9 factors × 2 states = 18 cells, trial 1 of a
new family).** For factor k, the score is sign_k × rank_z_k (full-universe
within-date rank). Within the names of one state quintile on date t:

- top leg = `pick_decile_volq` on the score, bottom leg = the same on the
  negated score; both inverse-vol weighted, NaN-label names dropped and
  renormalised as `Book.picks` does. A date with fewer than 20 valid names in
  the quintile is skipped (the picker's own rule).
- each leg is costed through `turnover_net_return` at 15 bp on its own
  turnover; long-short net per window = net_top − gross_bottom − cost_bottom.
- payoff = mean over windows × 252/40, per offset, then the mean of 40 offsets.
- pooled figure = the same with no state restriction.
- **Cell statistic S = payoff(Q5) − payoff(Q1)**, on the dates where all four
  legs exist. Also reported per cell: the payoff in each of the five
  quintiles and each minus pooled.

Null: the state value is shuffled within date among the names that have one
(`shuffle_within_date`, seeds 0..99 for state a, 1000..1099 for state b), then
quintiled the same way; S recomputed. Band: two-sided, **|S| > 80th
percentile of |S_null|** (p95 also reported). No sign is pre-specified.

A cell passes when all three hold:

1. |S| beyond the p80 band (or p95, counted separately);
2. the per-offset S has the sign of the 40-offset mean on ≥ 32 of 40 offsets;
3. no year carries more than 45% of the effect: share_y = sum of the per-window
   (Q5 − Q1) differences with rebalance date in year y ÷ the sum over all
   windows; max share ≤ 0.45. A zero total fails.

Leave-one-year-out S (each year dropped) is reported for every cell.

**Test 2: state-conditional book, one rule (R), no fitted parameter.**
Names in hi52 Q1 (the fifth of names furthest below their 52-week high) cannot
be picked. Vol quintiles and per-bucket slot counts come from the full
eligible set, and the next-ranked survivors fill each bucket's slots
(`trailfilter.picks_fullsize`), so the book keeps its size. A name with no
state is kept. Direction chosen from George-Hwang (2004): names far from the
high underperform. Prior: weak. WO-40 (trailing-40-day return filter, the same
refill construction) was a KILL, and hi52's own IC t is +0.84.
Metric: rule book minus icw9_seas, %/yr net, 40-offset mean, number of offsets
> 0 (`trailfilter.diff_stats`). Reported with it: drop-2008, per year, year
shares, turnover, and the same rule on the 100 shuffled-state draws (random
exclusion of a fifth of names), which is context, not a condition.

**Test 3: `hi52` standalone through the standard 7-gate stack**
(`screen_insider_v2grid`, as WO-18/io_gap): sign +1, pooled NW(39) IC
t ≥ +1.96, both year halves > 0, sector both-sides t ≥ 1.0, 0/40 offset
flips, max year share ≤ 0.45, gate 6 icw8+hi52 beats the p80 of 20 shuffles,
gate 7 weight rule reproduces production to 4 dp. Reported separately. Note
gate 6 adds a copy of a factor icw8 already holds.

**Success (all required).**

- cells: at least 2 of 18 cells pass at p80, or at least 1 passes at p95
  (conditions 1-3 above each time); and
- book: rule R minus icw9_seas > 0 on the 40-offset mean and on ≥ 32 of 40
  offsets.

**Kill:** anything else. A pass is evidence for WO-43 (trees would have
interactions to find); a kill is evidence against that rationale.

**A weakness of the cells condition, stated now.** With 18 cells and a p80
band, about 3.6 cells clear the band by chance, so "≥ 2 beyond p80" alone is
met about 9 times in 10 under the null (cells are correlated, so roughly).
Conditions 2 and 3 and the book condition carry the test. The count of cells
that clear the band alone is reported next to the count that pass all three.

**Checks before trusting a number.**

Done in prep (`final/out/stateint/parts/prep.json`), no state-conditional
return computed:

- PIT: 400 sampled (name, t) recomputed from the series truncated at t: max
  difference 0 (hi52), 1.5e-15 (vol60). Every bar after 2013-06-28 multiplied
  by 7: no state on or before that date changes (8.4M rows).
- Named company: AAPL 2013-04-19, hi52 = 0.5562 = 390.52/702.10, window max
  on 2012-09-19 (the known closing high and low). AAPL 2014-06-09, the first
  day after the 7:1 split, hi52 = 1.0, not 0.14.
- Delisted names: 4,001 of 6,508 tickers (61%) are delisted names, with 4.27M
  rows carrying a finite hi52 and 4.52M carrying a label. The panel's
  point-in-time build and survivorship fix are WO-6's
  (`2026-09-24-downcap-grid-rebuild.md`, check A2); every later screen used
  this same panel.
- Book reconcile: icw9_seas +0.0348652 and icw8 +0.0285416 vs SPY, exact
  against the committed WO-31 `pool_hedge_read.json` (difference 0.0).
- Picker oracle: above.

To be done in the run:

- Pooled factor payoffs. No prior screen reports a per-factor
  top-minus-bottom decile_volq payoff, so there is no number to reconcile to.
  What is checked instead: each factor's pooled payoff sign against its signed
  IC on this panel, with the IC t printed next to the stored
  `ic_weighted_composite_report.json` t.
- Shuffled state shows no effect: for each cell the mean of the 100 null S
  must be within 3 standard errors of zero.

**Trial count.** Interaction family NEW, 18 cells, trial 1. hi52 standalone:
ordered as new family k=1; in fact a re-screen (see above).
**Iteration cap.** 3 fix-and-rerun cycles, bugs only. States, rule and
thresholds do not change after a real number is seen.

## 1a. Amendment (2026-10-06, COO decision, made before any label was read)

The COO amended the work order on the prep findings above. The prep stage
(commit a5a4d05) computed no state-conditional return, no cell statistic and
no book difference, so this amendment is label-free. It supersedes section 1
where they differ. Gabe allowed the pre-registration push on 2026-10-06.

- **Correction.** The order called the 52-week-high effect "not previously
  tested here". That was the COO's error: hi52 = `pct_from_high_252` + 1, one
  of the original 8 factors and a live icw9_seas factor.
- **Test 3 dropped.** hi52 standalone through the 7-gate stack is not run. It
  is not a new family.
- **Self-cells dropped.** `pct_from_high_252` × hi52 and `volatility_60` ×
  vol60 are not computed. **16 cells**, interaction family NEW, trial 1.
- **Cell pass (all three):** |S| > the 95th percentile of |S_null| over the
  100 within-date state shuffles (two-sided); per-offset S with the sign of
  the mean on ≥ 32 of 40 offsets; max year share ≤ 0.45.
- **Success (all required):** at least 2 of the 16 cells pass, AND rule R
  (exclude hi52 Q1, refill via `trailfilter.picks_fullsize`) minus icw9_seas
  > 0 on the 40-offset mean and on ≥ 32 of 40 offsets. **Kill:** anything
  else.
- Counts at p80 are reported, descriptive only. The "weakness of the cells
  condition" paragraph above no longer applies to the decision: under p95,
  about 0.8 of 16 cells clear the band by chance.
- Unchanged: states, quintile rule, cell statistic, null, book rule, checks.
