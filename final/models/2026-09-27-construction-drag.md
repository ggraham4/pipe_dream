# WO-21: what is the post-2011 random-book drag made of? (2026-09-27)

COO work order WO-21. **Descriptive; no trial counted; no kill.** icw8
frozen production weights, v2 grid column c, cap150, h = 40,
`forward_return_tradable_40` universe, decile_volq, 40 offsets, net 15 bp
(`run_backtest.turnover_net_return`). In-era only: 2007-01-02..2019-12-31.
Code: `final/src/construction/drag_decomp.py`. Output:
`final/out/construction/drag_decomp.json`.

## 0. Pre-fixed decision map (verbatim from the COO, frozen before any result)

 - (a) ≥ 2/3 of the post-2011 drag → "universe bet"; forward expectation vs SPY ≈ selection − universe drag; benchmark/hedge choice goes to Gabe.
 - (b) ≥ 2/3 → COO will write ONE pre-registered construction trial.
 - (c) ≥ 1/3 → turnover work order.
 - otherwise "mixed", report only.

Cap: 1 run + 1 fix. Report the numbers exactly; no new factors, no
construction search, no weight changes.

## 1. Pre-registration (frozen before the decomposition ran)

### 1.1 Books (all on the same universe U)

U = v2 column c, `eligible_cap150` rows, 2007-01-02..2019-12-31, built
exactly as WO-18 `screen_seas.load_universe` / COO `decomp.py` (minus the
seas merge, which is a left merge that changes neither rows nor order).
Ranks via `screen_insider_v2grid.add_ranks(U, FC8)`; score =
`screen_insider.composite_score(U, ic_weighted_composite.PRODUCTION_WEIGHTS)`.

- **score**: `composite.pick_decile_volq` on the icw8 score (the live book).
- **random**: the same construction on the icw8 score shuffled within date
  (`screen_insider_v2grid.shuffle_within_date`, seeds 2000..2004 = COO's 5
  draws). Shuffled ONCE on full U; pre/post picks are filtered by date,
  never reshuffled. Book value = mean over the 5 draws; spread (min, max,
  sd across draws) reported for every random number.
- **noscore**: WO-7 construction, `no_exclusion_control.pick_full_universe_volq`
  (every eligible name with finite vol, inverse-vol weighted, no score).
- All books: drop NaN-return picks and renormalise (as `Book.picks`).

### 1.2 Periods and backtest

pre = rebalance dates < 2011-10-01; post = dates >= 2011-10-01. Each period
is run on its own sub-calendar (`dates[off::40]` of the period's dates),
exactly as COO `decomp.py`, via `downcap_v2_readout.backtest` arithmetic
(per-offset mean excess × 252/40, averaged over 40 offsets). Gross = same
with cost 0 bp. Full era is also reported.

### 1.3 Decomposition and the trigger basis (PRIMARY = net basis)

Total drag T = random_net − SPY (post ≈ −2.76 %/yr per COO).

- **(a) universe** = noscore_net − SPY
- **(b) construction** = random_net − noscore_net
- (a) + (b) = T exactly.
- **(c) costs** = random_net − random_gross (≤ 0; a separate, overlapping
  measure of how much of T is trading cost; it is part of (b) and (a)).

Share of a component = signed component / T, **post window only** (pre is
descriptive). The decision map above is read on these net-basis shares.

Secondary (reported, not used for the trigger): the exact gross three-way
T = (noscore_gross − SPY) + (random_gross − noscore_gross) +
(random_net − random_gross). If the secondary basis would put a component
on the other side of its threshold, that is reported as a disagreement, not
resolved after the fact.

The same split is reported for the **score** book (score_net − SPY =
(a) + (score_net − noscore_net); costs = score_net − score_gross), and
selection = score − random on each basis (net, gross).

### 1.4 Expectations stated before the run (so the reading is not rationalised afterwards)

- The random book is redrawn every rebalance, so its name turnover f_new
  should be ≈ 0.9. Under `turnover_net_return`, cost ≈ 15 bp × f × 252/40
  ≈ 0.85 %/yr, about 31 % of a −2.76 drag: (c) is mechanically near the
  1/3 line, and most of that churn is a property of the null, not of the
  live book. Mean f_new is reported for random, score and noscore next to
  each (c), and the score book's (c) sits beside the random one.
- A random subset with the same per-quintile inverse-vol weighting should
  have about the no-score book's expected GROSS return, so a gross-basis
  (b) near zero is expected by construction. A net-basis (b) is then
  roughly the random book's extra cost over the no-score book's.

### 1.5 Also reported

- Per-calendar-year table of (a), (b), (c) (and the score book's split),
  on full-calendar offset chains grouped by rebalance-date year. These do
  not sum to the sub-calendar pre/post numbers (chain starts differ).
- OLS of the random book's (5-draw mean) per-date 40d NET excess vs SPY on
  SPY 40d return, and separately on IWM 40d return (IWM from
  `final/data/benchmarks/IWM.csv`, `hedged_composite.ret40` basis:
  close[i+40]/open[i+1]−1, price-only, same basis as SPY), pre vs post.
  Per-date net = each date's value on its own full-calendar offset chain.
  Common sample where IWM is finite (IWM.csv ends 2019-12-31, so the last
  ~40 dates are NaN). NW(39) t-stats for overlap. Regressing excess on
  SPY, the slope is β − 1. Alpha annualised × 252/40.
- **COO addendum:** for icw8, post window: selection (score − random)
  per-offset sd across the 40 offsets, offsets positive, and LOYO within
  2011-10..2019 (min and dropped year). icw9_seas is not computed here
  (its post-2011 selection is in-sample and is not evidence).

### 1.6 Reconcile gates (`--validate` mode; not the counted run)

`--validate` prints reconcile numbers only, no decomposition:

1. icw8 score book full era = +0.0285416 (1e-6), and pre/post equal COO
   `decomp.json` score_book pre/post (1e-6).
2. Each of the 5 random draws' full/pre/post equal COO `decomp.json`
   null_draws (1e-6).
3. noscore full era vs SPY equals WO-7 `noscore_control.json` cap150
   vs_spy_full noscore mean40 = −0.002485035 (1e-6; WO-7 removed 0 dates in
   alignment, so the date sets match).

Any failure: stop and report, no decomposition.

### 1.7 Hold-out

Every frame asserts max(date) < 2020-01-01 on rebalance dates (SPY, IWM
and U). As in every v2-grid number since WO-13, late-2019 rows whose 40d
label ends in early 2020 are kept (Gabe's ruling); this is needed for the
reconcile. No 2020+ rebalance date is read.

## 2. Results

(to be filled after the run)
