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

## 2. Results (run 2026-09-27; 1 run + 1 fix used)

**Run log.** `--validate` passed all 20 reconcile gates. The counted run
then crashed in the OLS section, after the decomposition and decision map
had been computed and logged. The crash was a pandas boolean-mask bug.
The one allowed fix was a numpy mask plus a `bool()` cast on the trigger
flags. The rerun reproduced the logged decomposition numbers exactly and
wrote `final/out/construction/drag_decomp.json` (log: `drag_decomp.log`,
reconcile: `drag_decomp_validate.json`, all under `final/out/construction/`.
The script writes them to the main checkout, and they are copied onto the
branch and committed. They are small and not gitignored.

### 2.1 Reconcile (all 1e-6)

| check | got | reference |
|---|---|---|
| icw8 full | +0.0285416 | +0.0285416 |
| icw8 pre / post | +0.0775258 / +0.0001218 | COO decomp.json, equal |
| 5 random draws, each of full / pre / post | 15 values | COO decomp.json null_draws, all equal |
| noscore full vs SPY | −0.002485035 | WO-7 noscore_control.json −0.002485035 |

### 2.2 Decomposition, %/yr vs SPY, net 15 bp (PRIMARY)

Random = mean of 5 draws. Draw range is in brackets.

| window | T = random net − SPY | (a) universe = noscore net − SPY | (b) construction = random net − noscore net | (c) costs = random net − gross |
|---|---|---|---|---|
| pre (< 2011-10) | **+1.94** [+1.79, +2.03] | +2.74 | −0.80 [−0.94, −0.71] | −0.86 |
| post (≥ 2011-10) | **−2.76** [−2.92, −2.70] | **−1.99** | −0.77 [−0.93, −0.71] | −0.87 |
| full | −1.04 | −0.25 | −0.79 | −0.86 |

**Post-window shares of T (signed):** (a) **0.720**, (b) 0.280, (c) 0.315.

Secondary gross three-way, post: (a_g) noscore gross − SPY −1.94 (0.703),
(b_g) random gross − noscore gross **+0.05** (−0.017), (c) −0.87 (0.315).
Pre: +2.80 / −0.00 / −0.86. It sums to T exactly.

**Mean name turnover f_new** (post): random 0.905, score 0.205,
noscore 0.048. Pre: 0.907 / 0.227 / 0.066.

### 2.3 Decision map outcome: **"universe bet"**

- (a) = 72.0 % of the post-2011 drag, which is ≥ 2/3 → universe bet.
- (b) = 28.0 % < 2/3 → no construction trial.
- (c) = 31.5 % < 1/3 → no turnover work order.
- The gross basis gives the same triggers (a_g 70.3 %, b_g −1.7 %,
  c 31.5 %), so there is no disagreement between the bases.

As expected in section 1.4:
- (c) sits just under the 1/3 line (analytic ≈ 31 %).
- The gross construction effect is zero (random gross = noscore gross
  within ±0.05).
- So the net (b) is almost entirely the null's own churn cost:
  f_new 0.905 vs the noscore book's 0.048.
- The live book's cost is −0.20 %/yr (f_new 0.205), not −0.87.

### 2.4 Same split for the score book (icw8), and selection

| window | score net − SPY | (a) universe | score net − noscore net | score costs (net − gross) | selection net (score − random) | selection gross |
|---|---|---|---|---|---|---|
| pre | +7.75 | +2.74 | +5.02 | −0.22 | +5.82 | +5.17 |
| post | **+0.01** | −1.99 | +2.00 | −0.20 | **+2.78** | +2.10 |
| full | +2.85 | −0.25 | +3.10 | −0.20 | +3.90 | +3.23 |

Net selection exceeds gross selection by about 0.67, because the random
book pays about 0.67 %/yr more in costs than the score book.

Reading of the map's forward formula (descriptive, not a forecast), post
window, net: universe −1.99 + score-book construction/selection over the
no-score book +2.00 = +0.01 vs SPY. Measured against the random null, the
selection of +2.78 sits on top of a −2.76 random book, and 0.77 of that
random book's drag is null-only churn.

### 2.5 COO addendum: icw8 selection (score − random, net) across offsets

| window | mean40 | sd40 | offsets positive | LOYO min (dropped yr) | LOYO max (dropped yr) |
|---|---|---|---|---|---|
| post 2011-10..2019 | +2.78 | 0.40 | 40/40 | +1.59 (2018) | +4.05 (2016) |
| pre | +5.82 | 0.52 | 40/40 | +4.38 (2011) | +8.53 (2007) |
| full | +3.90 | 0.31 | 40/40 | +3.28 (2018) | +4.76 (2016) |

icw9_seas is not reported (in-sample weights).

### 2.6 Per calendar year, %/yr

Full-calendar chains, rebalance-date year. These do not sum to the
sub-calendar pre/post numbers.

| year | T random | (a) universe | (b) constr. | (c) costs | (b_g) gross constr. | score net | selection net |
|---|---|---|---|---|---|---|---|
| 2007 | −7.46 | −6.66 | −0.80 | −0.85 | −0.13 | −11.90 | −4.44 |
| 2008 | +4.12 | +5.15 | −1.04 | −0.80 | −0.26 | +14.81 | +10.69 |
| 2009 | +8.08 | +8.91 | −0.84 | −0.91 | +0.03 | +16.54 | +8.46 |
| 2010 | +7.33 | +7.90 | −0.58 | −0.89 | +0.28 | +9.97 | +2.64 |
| 2011 | −1.61 | −0.72 | −0.89 | −0.86 | −0.06 | +8.58 | +10.19 |
| 2012 | −0.61 | +0.02 | −0.63 | −0.87 | +0.21 | −0.71 | −0.11 |
| 2013 | +3.09 | +3.90 | −0.81 | −0.89 | +0.04 | +4.40 | +1.31 |
| 2014 | −6.59 | −5.79 | −0.80 | −0.86 | +0.04 | −0.77 | +5.82 |
| 2015 | −7.40 | −6.68 | −0.72 | −0.83 | +0.09 | −5.67 | +1.73 |
| 2016 | +7.20 | +7.93 | −0.73 | −0.89 | +0.13 | +0.62 | −6.58 |
| 2017 | −7.92 | −6.88 | −1.04 | −0.87 | −0.19 | +1.50 | +9.41 |
| 2018 | −0.75 | −0.06 | −0.70 | −0.85 | +0.13 | +10.64 | +11.39 |
| 2019 | −11.24 | −10.44 | −0.79 | −0.87 | +0.05 | −11.28 | −0.04 |

The universe term drives the year-to-year swings, while (b) and (c) are
flat at about −0.8 %/yr every year. The post-2011 drag comes from the
universe losing to SPY in 2014, 2015, 2017 and 2019.

### 2.7 OLS of per-date 40d net excess (NW(39) t; alpha ×252/40)

Random book (5-draw mean), common sample where IWM is finite.

| window (n) | on SPY: slope (β−1), t | alpha, t | on IWM: slope, t | alpha, t | raw on IWM: β, R² | mean IWM − SPY |
|---|---|---|---|---|---|---|
| pre (1197) | +0.129, +3.40 | +2.07 %, +0.93 | +0.163, +7.87 | +1.72 %, +0.90 | 0.922, 0.982 | +2.37 %/yr |
| post (2035) | +0.037, +0.85 | **−2.95 %, −2.23** | +0.188, +7.67 | **−4.59 %, −4.15** | 0.819, 0.972 | −1.10 %/yr |
| full (3232) | +0.091, +2.68 | −1.52 %, −1.23 | +0.166, +9.00 | −2.10 %, −1.96 | 0.888, 0.976 | +0.18 %/yr |

- **SPY beta:** the random book's beta to SPY is ≈ 1.04 post and 1.13 pre.
  Post, the drag is not market beta. It is an intercept of −2.95 %/yr.
- **Excess on (IWM − SPY):** slope +0.64 post (t +27.6, R² 0.85), alpha
  −1.79 %/yr (t −4.06). Pre: slope +0.71, alpha +0.25 %/yr (t +0.27).
- **Raw return on IWM:** R² 0.97, alpha +0.60 %/yr post (t +1.19). The
  cap150 universe book behaves like about 0.8 × IWM.
- About −0.7 of the post drag is the small-cap spread (0.64 × −1.10). Most
  of the rest is the 0.87 null churn cost, plus a residual.

Score book, post: on SPY slope −0.045 (t −1.12), alpha +0.90 % (t +0.60);
on IWM slope +0.099, alpha −0.74 % (t −0.48).

### 2.8 Summary

The post-2011 random-book drag of −2.76 %/yr splits into three parts:
- **Universe (−1.99, 72 %):** the no-score, inverse-vol cap150 book losing
  to SPY. It is concentrated in 2014, 2015, 2017 and 2019, and tracks
  small caps (≈ 0.8 × IWM, R² 0.97).
- **Construction (−0.77, 28 %):** entirely trading cost from the null's
  0.9 name turnover. The gross construction effect is +0.05.
- **Costs (−0.87, 31.5 %):** overlaps with the above. It is a property of
  the reshuffled null, not of the live book, whose cost is −0.20.

Decision map: **"universe bet"**. Forward expectation vs SPY ≈ selection
− universe drag. The benchmark/hedge choice goes to Gabe.
