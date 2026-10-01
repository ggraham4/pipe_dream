# WO-44: does the intersection of the live picks and the rolling-weights picks outperform?

Date: 2026-10-01. Owner: Gabe (his question, 2026-10-01). Issued by the COO.
Code: `final/src/intersect/intersect.py`. Outputs: `final/out/intersect/`.

Research backtest only. Nothing here places, or can place, a trade.

## 1. Pre-registration (written and committed before any INT-vs-L number)

### Background

WO-33 built R252: the live icw9_seas factors, with weights refit every 21
trading days on the trailing 252 matured label dates (41-day embargo). Against
its expanding-window control it was −1.11%/yr in 2010-19 (0/40 offsets) and
+2.60%/yr in 2020-26 (38/40). The live frozen icw9_seas book is −2.02%/yr vs
SPY in 2020-26. R252 is a tracking-only tab in the app, next to the live
Theoretical picks, with a marker on names in both lists. The question: is the
set of names both models pick better than the live book?

### Books (fixed now)

At each rebalance date and offset:

- **L**: the live icw9_seas decile_volq picks, frozen live weights
  (`ICW.PRODUCTION_WEIGHTS_V9_SEAS`).
- **R**: the R252 decile_volq picks from WO-33's weight path
  (`weight_paths.csv` for 2010-19, `weight_paths_step2.csv` for 2020-26).
- **INT**: names in both L and R. Weights follow the live construction rule.
  That rule is inverse-volatility (`1/max(vol_60, 1e-4)`), normalised over the
  whole pick set after dropping names with no 40-day return
  (`composite.pick_decile_volq` + `Book.picks`). INT keeps each surviving
  name's inverse-vol weight and renormalises over INT.
- **Fallback**: if INT has fewer than 10 names on a date, the book holds L for
  that window. The count of such dates is reported.
- Descriptive only: **L_only** (in L, not R), **R_only** (in R, not L),
  **UNION** (inverse-vol over all names in either).

### Harness

WO-33's, imported read-only from `final/src/rollweights/rollweights.py`: v2
column c, cap150, decile_volq, 40 offsets, h=40, label
close[t+40]/open[t+1], net of 15 bp (`DD.chains`, `RB.turnover_net_return`).

Reconcile gates, hard asserts in `--stage build`, before any INT number:

| check | reference |
|---|---|
| my weighted picks reproduce `Book.picks` (names and gross, every date, 1e-12) | exact |
| L vs SPY, 2020-26 | −2.016%/yr (`REF_B_LIVE`, tol 1e-6) |
| R252 − EXP, 2010-19 | −1.109%/yr, 0/40 (WO-33 eval JSON, tol 1e-9) |
| R252 − EXP, 2020-26 | +2.603%/yr, 38/40 (WO-33 step-2 JSON, tol 1e-9) |

Build result (2026-10-01, before the score stage existed as output): all
gates pass. L holds about 297 names per date in A (min 266) and 313 in B
(min 269), so the fewer-than-10 fallback should be rare.

### Eras

- **A** = 2010-01-04..2019-12-31 (R252 needs burn-in from 2007).
- **B** = 2020-01-02..2026-07-30 (last matured 40-day label).

R252's 2020+ weights are a Gabe-approved walk-forward fit (hold-out read #13).
This construction's B read is **hold-out read #20**. Nothing new is fitted.

### Primary metric

INT − L, net %/yr, mean over 40 offsets, and the count of offsets > 0, per
era.

### Decision rule

- **Success**: > 0 in both eras with ≥ 30/40 offsets in each, and still > 0 in
  B with 2020 dropped, and in A under leave-one-year-out (min over dropped
  years > 0).
- **Kill**: ≤ 0 in either era.
- **Middle**: positive in both but fails an offsets or drop-year check. Report,
  no action.

A success earns only a forward-tracked column (the tab already records both
pick sets). It does not change the live book.

### Also reported (descriptive, no verdict weight)

- Mean names in INT and overlap share |INT|/|L| per era; fallback dates.
- INT vs SPY; L_only, R_only and UNION vs L.
- Concentration cost: INT's sd across offsets, max drawdown and worst 40-day
  window, each next to L's.
- Turnover (mean share of new names per rebalance) and cost drag of INT.
- **Size-matched null (the key control)**: 100 draws, seeds 4400..4499. Each
  draw picks, independently on every date, a random subset of L with the same
  count as INT on that date, inverse-vol weighted over the subset. On fallback
  dates the null holds L, as INT does. Reported: the share of null draws whose
  (subset − L) is below INT − L. The net percentile is the headline. The gross
  percentile is reported beside it, because independent random subsets turn
  over far more than INT does and so pay more cost; the gross figure removes
  that handicap. The question it answers: does agreeing with R252 beat randomly
  thinning the live book?

### Trial count

Time-varying-weights family: R252, R756 and SA252 are all KILL as weight
rules. INT is a new construction on top of R252, **trial 4 of the family**.
No variants after results: no top-k, no alternative weighting, no other
minimum count.

### Process

Iteration cap 2, bug fixes only.

## 2. Results

(Filled in after the pre-registration commit.)
