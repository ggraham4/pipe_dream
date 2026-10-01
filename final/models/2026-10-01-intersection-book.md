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

Pre-registration commit: `89120fd` (pushed before the score stage ran).
Run: 2026-10-01, `intersect.py --stage score`, one pass, no iteration used.
Numbers: `final/out/intersect/intersect_eval.json`. Hold-out read #20 is spent.

### Verdict: MIDDLE (report, no action)

INT − L is positive in both eras, but it fails two of the pre-registered
checks: B has 29/40 offsets (needs 30), and A's leave-one-year-out minimum is
negative (−0.10%/yr with 2017 dropped). No forward column is earned.

### Primary: INT − L, net %/yr, 40-offset mean

| era | INT − L | offsets > 0 | drop-year check | NW(39) t | pass? |
|---|---|---|---|---|---|
| A 2010-19 | +0.31 | 32/40 | LOYO min −0.10 (drop 2017) | 0.60 | fails LOYO |
| B 2020-26 | +0.74 | 29/40 | ex-2020 +0.25 | 0.51 | fails offsets |

Gross of costs the gap is +0.49 (A) and +0.91 (B). INT turns over more than L
(63% new names per rebalance vs 43-45%), which costs about 0.18%/yr extra.

The edge is small and not steady by year. INT − L by rebalance year, %/yr:
A: 2010 −1.3, 2011 −0.5, 2012 +0.7, 2013 +1.0, 2014 +1.3, 2015 +1.6,
2016 −2.9, 2017 +4.0, 2018 −1.2, 2019 +0.2.
B: 2020 +3.4, 2021 −2.7, 2022 +2.8, 2023 +2.2, 2024 +2.2, 2025 −4.0,
2026 +1.8. In A, 2017 alone carries the result.

### Size-matched null (key control)

| era | INT − L | null mean (net) | null sd | null max | share of null below INT (net) | (gross) |
|---|---|---|---|---|---|---|
| A | +0.31 | −0.26 | 0.09 | −0.04 | 100/100 | 100/100 |
| B | +0.74 | −0.20 | 0.30 | +0.48 | 100/100 | 100/100 |

INT beats every one of 100 random same-size thinnings of L in both eras, net
and gross (gross null mean +0.02 A, +0.13 B; max +0.25 A, +0.81 B vs INT
+0.49, +0.91). So agreeing with R252 does pick a better half of the live book
than chance. Two limits on that reading. The null only varies which names are
kept; it holds the realised return history fixed, so it does not say the gap
would repeat in new years, and the time-series t (0.5 to 0.6) says it is not
distinguishable from zero. And in B the gross margin over the best null draw
is thin (+0.91 vs +0.81).

One more limit. R252 uses L's own factors with the same signs, so the shared
names are probably the ones L itself scores highest within each vol quintile.
A random-thinning null cannot tell "agreeing with R252" apart from
"concentrating L on its own best-scored half". A top-half-of-L control was not
pre-registered and was not run; running it now would be the top-k variant
this work order rules out.

### Overlap and name count

| era | mean L | mean INT | min INT | INT / L | fallback dates |
|---|---|---|---|---|---|
| A | 296.5 | 142.9 | 37 | 48% | 0 of 2516 |
| B | 312.8 | 124.4 | 38 | 40% | 0 of 1652 |

The fewer-than-10 fallback never fired.

### Books vs SPY and vs L (net %/yr)

| book | A vs SPY | A − L | B vs SPY | B − L |
|---|---|---|---|---|
| L | +2.40 | 0 | −2.02 | 0 |
| R (R252) | +0.55 | −1.84 (0/40) | +1.02 | +3.03 (40/40) |
| INT | +2.70 | +0.31 (32/40) | −1.28 | +0.74 (29/40) |
| L_only | +1.62 | −0.78 (0/40) | −3.24 | −1.22 (10/40) |
| R_only | −1.41 | −3.81 (0/40) | +1.96 | +3.97 (39/40) |
| UNION | +1.17 | −1.22 (0/40) | −0.27 | +1.75 (40/40) |

The two eras tell different stories. In A the shared names are the best part
of either book and R's own names are the worst. In B the names only R picks
are the best (+1.96 vs SPY) and the shared names still lose to SPY (−1.28).
The intersection does not capture what made R252 work after 2020; that sat in
the names the live book did not hold. INT still loses to SPY in B, at 12/40
offsets.

### Concentration cost (INT vs L)

| | A INT | A L | B INT | B L |
|---|---|---|---|---|
| sd across offsets, %/yr | 0.34 | 0.24 | 2.01 | 1.03 |
| max drawdown, mean over offsets | −15.0% | −15.3% | −26.2% | −28.1% |
| max drawdown, worst offset | −19.9% | −19.3% | −34.0% | −33.9% |
| worst 40d window, net | −15.6% | −15.2% | −33.8% | −33.9% |
| worst 40d window, vs SPY | −7.0% | −7.5% | −15.1% | −10.5% |
| sd of 40d net return | 5.0% | 5.1% | 8.3% | 8.5% |
| new names per rebalance | 63% | 43% | 63% | 45% |
| cost drag, %/yr | 0.61 | 0.42 | 0.60 | 0.43 |

Halving the book did not deepen drawdowns. It did double the spread across
offsets in B (start-date luck matters more) and worsened the worst
SPY-relative window in B.

### Trial count and what follows

Trial 4 of the time-varying-weights family (R252, R756, SA252 KILL; INT
MIDDLE). No variants were run and none should be: no top-k, no other
weighting, no other minimum count. Per the rule a MIDDLE means report and no
action. The app tab already records both pick sets, so the overlap can be
re-read on new data later without a new build.
