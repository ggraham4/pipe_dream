# WO-24: the 2020s loss vs SPY, decomposed (period B, 2026-09-28)

COO work order WO-24. **Descriptive; no trial counted; no kill.** Hold-out
read **#6** under Gabe's standing OK (2026-09-27) for unfitted 2020-2026
reads: frozen live weights only; nothing is fit, chosen or tuned on 2020+.

Reruns WO-21's decomposition (`final/src/construction/drag_decomp.py`, doc
`final/models/2026-09-27-construction-drag.md`) on **period B =
2020-01-02 .. 2026-07-30** (the last matured 40-day label, same as WO-23).
Code: `final/src/construction/drag_decomp_b.py`. Output:
`final/out/construction/drag_decomp_b.json`.

## 0. Pre-fixed decision map (same as WO-21, frozen before any B number)

Read on the period-B window, net basis, T = random_net − SPY:

- (a) universe ≥ 2/3 of the B drag → "universe bet"; forward expectation
  vs SPY ≈ selection − universe drag; benchmark/hedge choice goes to Gabe.
- (b) construction ≥ 2/3 → COO writes ONE pre-registered construction trial.
- (c) costs ≥ 1/3 → turnover work order.
- otherwise "mixed", report only.

Pre-stated reading rules for B (fixed before the run, since B has no
pre/post split):

1. The trigger model is **icw8** (as in WO-21). icw9_seas gets the same
   split and triggers, reported alongside; if its triggers differ from
   icw8's, that is reported as a disagreement, not resolved after the fact.
2. If T ≥ 0 on B (no drag), shares are undefined; outcome = "no drag,
   report only".
3. Secondary gross basis reported as in WO-21; a basis disagreement is
   reported, not resolved.
4. The COO's question for WO-24 ("pool drag or lost selection?") is
   answered descriptively from the score-book split: score − SPY =
   (a) universe + (score − noscore); and selection (score − random) with
   sd40, offsets positive and LOYO. No threshold is attached to that
   reading beyond the map above.

Cap: 1 run + 1 fix. No new factors, no construction search, no weight
changes.

## 1. Pre-registration

### 1.1 Books (same universe U per period)

- U(B) = WO-23's period-B loader, `final/src/audit/model_audit_wo23.load_theo("B", "cap150")`
  (v2 column c, `eligible_cap150`, `forward_return_tradable_40` label
  panel, SPAC filter, outcome_cache_v2 `gross_return_40`, seas from the
  WO-23 extension). Ranks `V.add_ranks(U, FT)` with WO-23's 9 factors;
  scores `SI.composite_score` with **frozen** `ICW.PRODUCTION_WEIGHTS`
  (icw8) and `ICW.PRODUCTION_WEIGHTS_V9_SEAS` (icw9_seas, live 4-dp).
- **score**: `pick_decile_volq` on the model score.
- **random**: same construction on the model's score shuffled within date
  (`shuffle_within_date`, seeds 2000..2004, 5 draws, same as WO-21). Each
  model gets its own random book (its own score's finite pattern). Mean over
  draws; min/max/sd across draws reported.
- **noscore**: WO-7 construction (`no_exclusion_control.pick_full_universe_volq`),
  model-independent.
- All books: NaN-return picks dropped, weights renormalised.

### 1.2 Backtest

B window on its own calendar (all B panel dates, `dates[off::40]`), 40
offsets, `downcap_v2_readout.backtest` arithmetic, net 15 bp
(`turnover_net_return`); gross = 0 bp.

### 1.3 Decomposition (WO-21 definitions)

- (a) universe = noscore_net − SPY
- (b) construction = random_net − noscore_net;  (a) + (b) = T
- (c) costs = random_net − random_gross (overlapping measure)
- Secondary gross three-way as WO-21.
- Score book: score_net − SPY = (a) + (score_net − noscore_net);
  score costs = score_net − score_gross.
- Selection vs random (net, gross) and **selection vs no-score**
  (score_net − noscore_net): mean40, sd40, offsets positive, LOYO min/max
  over B calendar years (2020..2026), for both models.
- Mean name turnover f_new per book.

### 1.4 Expectations stated before the run (so a borderline read is not rationalised afterwards)

- The random book is redrawn every rebalance (f_new ≈ 0.9), so its cost
  (c) is mechanical: ≈ 15 bp × 0.9 × 252/40 ≈ −0.85..−0.87 %/yr, as in
  WO-21 pre and post. The (c) share ≈ 0.87 / |T| therefore crosses the 1/3
  line whenever |T| < ≈ 2.6 %/yr. If B's T is smaller than that, a
  "turnover work order" trigger would fire on a property of the reshuffled
  null, not of the live book (live cost ≈ −0.2 %/yr, f_new ≈ 0.2). The map
  is NOT changed for this; the reading is reported with the live book's
  cost and f_new next to it.
- Gross construction (b_g = random_gross − noscore_gross) ≈ 0 is expected
  by construction (same per-quintile inverse-vol weighting on a random
  subset), so net (b) ≈ (c) − noscore's small cost, again a null property.
- 2026 is a partial year (rebalance dates through 2026-07-30 only). It
  counts as its own year in the LOYO and per-year tables.

### 1.5 Also reported

- Per-calendar-year table on B (rebalance-date year), both models.
- OLS (NW(39)) of the no-score book on IWM for B **if IWM data covers B**.
  Pre-run check: `final/data/benchmarks/IWM.csv` ends 2019-12-31, IWM is
  not in `outcome_cache_v2` (only SPY, USMV), and the Sharadar panel is
  stocks only. So **IWM does not cover B**; no IWM OLS is run and no IWM
  data is pulled under this WO. The SPY OLS (no-score and random excess on
  SPY 40d) is reported instead, descriptive.

### 1.6 Reconcile gates (must pass before any decomposition number)

1. Period A: WO-21's `drag_decomp.main()` rerun unmodified (outputs
   redirected to /tmp) reproduces the committed
   `final/out/construction/drag_decomp.json`: every numeric leaf within
   1e-9 (runtime excluded), all 20 WO-21 reconciles pass.
2. Period B: icw8 score book = WO-23 `model_audit_wo23.json` B icw8
   −0.01991796370 and icw9_seas = −0.02016365567, within 1e-6 of the
   full-precision JSON values.
3. Oracle: per-offset chains equal `DR.backtest` on every net book
   (1e-12), as WO-21.

Any failure: stop and report, no decomposition.

### 1.7 Hold-out

Unfitted read #6. The script asserts every U(B) date ∈ [2020-01-02,
2026-07-30] and uses only the frozen weight constants.

## 2. Results (run 2026-09-29; 1 run + 1 fix used)

Pre-registration committed as b63582d (2026-09-29 10:46:55) before any
period-B decomposition number existed.

**Run log.** Stage A (period-A reproduction) passed on its first run.
Stage B, run 1, passed both reconcile gates and logged the full
decomposition and decision map. It then crashed on the IWM coverage
check: `final/data/` is gitignored, so it is absent in the worktree. The
one allowed fix pointed that check at `hedged_composite.IWM_CSV`, the
main-checkout file. The rerun logged numbers identical to run 1. Logs are
in `/tmp/wo24_drag_decomp_b/` and are not committed.

### 2.1 Reconcile

| check | got | reference | diff |
|---|---|---|---|
| Period A: WO-21 `drag_decomp.main()` rerun vs committed `drag_decomp.json` | 574 numeric leaves; all 20 WO-21 reconciles pass | — | max 0.0 |
| B icw8 | −0.019917964 | WO-23 `model_audit_wo23.json` −0.019917964 | 0.0 |
| B icw9_seas | −0.020163656 | WO-23 −0.020163656 | 0.0 |
| oracle: chains = `DR.backtest`, every net book | — | — | < 1e-12 |

### 2.2 Decomposition, %/yr vs SPY, net 15 bp (PRIMARY), next to WO-21

The random book is the mean of 5 draws, with the draw range in brackets.
B = 2020-01-02..2026-07-30, 1,652 dates, U = 5.22 M rows.

| window | T = random net − SPY | (a) universe = noscore net − SPY | (b) construction = random net − noscore net | (c) costs = random net − gross |
|---|---|---|---|---|
| WO-21 post 2011-10..2019 (icw8) | −2.76 [−2.92, −2.70] | −1.99 | −0.77 | −0.87 |
| **B 2020-01..2026-07, icw8** | **−5.55** [−5.80, −5.43] | **−4.85** | −0.71 [−0.95, −0.59] | −0.87 |
| B, icw9_seas | −5.58 [−5.95, −5.21] | −4.85 | −0.73 [−1.10, −0.37] | −0.87 |

**Shares of T (signed):**

| | (a) | (b) | (c) |
|---|---|---|---|
| WO-21 post | 0.720 | 0.280 | 0.315 |
| B icw8 | **0.872** | 0.128 | 0.156 |
| B icw9_seas | 0.869 | 0.131 | 0.156 |

- **Secondary gross basis, B icw8:** a_g −4.80 (0.864), b_g **+0.11** (−0.020),
  c −0.87 (0.156). icw9_seas: a_g 0.860, b_g +0.09 (−0.016), c 0.156.
- **Mean f_new, B:** random 0.906, icw8 score 0.228, icw9_seas score
  **0.446**, noscore 0.056.

### 2.3 Decision map outcome: **"universe bet"** (icw8; icw9_seas agrees)

- (a) = 87.2 % ≥ 2/3, so the map reads universe bet.
- (b) = 12.8 % < 2/3, so no construction trial.
- (c) = 15.6 % < 1/3, so no turnover work order.
- The gross basis gives the same triggers, and icw9_seas gives the same
  triggers. There is no disagreement on either.
- All 5 draws of both models give "universe bet". The (a) share ranges
  0.84–0.89 for icw8 and 0.82–0.93 for icw9_seas.
- The §1.4 borderline case did not arise. |T| = 5.55 is far above
  ≈ 2.6, so (c) sits well under 1/3.
- As expected, gross construction is ≈ 0 (+0.11). Net (b) is the null's
  own churn cost.

### 2.4 Score book split and selection, %/yr

| | score net − SPY | (a) universe | score net − noscore net | score costs | selection net vs random | selection gross vs random | score gross − noscore gross |
|---|---|---|---|---|---|---|---|
| WO-21 post, icw8 | +0.01 | −1.99 | +2.00 | −0.20 | +2.78 | +2.10 | — |
| **B icw8** | **−1.99** | **−4.85** | **+2.85** | −0.22 | **+3.56** | +2.91 | +3.02 |
| B icw9_seas | −2.02 | −4.85 | +2.83 | −0.43 | +3.56 | +3.12 | +3.21 |

Selection detail, per offset (40 offsets), LOYO over B calendar years
2020..2026:

| | mean40 | sd40 | offsets > 0 | LOYO min (dropped yr) | LOYO max (dropped yr) |
|---|---|---|---|---|---|
| WO-21 post, icw8, vs random | +2.78 | 0.40 | 40/40 | +1.59 (2018) | +4.05 (2016) |
| B icw8 vs random | +3.56 | 0.91 | 40/40 | **−0.17 (2020)** | +6.10 (2025) |
| B icw8 vs noscore | +2.85 | 0.78 | 40/40 | **−0.87 (2020)** | +5.43 (2025) |
| B icw9_seas vs random | +3.56 | 1.08 | 40/40 | −0.18 (2020) | +5.93 (2025) |
| B icw9_seas vs noscore | +2.83 | 0.77 | 40/40 | −0.94 (2020) | +5.27 (2025) |

LOYO by dropped year, icw8 vs random: 2020 −0.17, 2021 +4.23, 2022 +4.13,
2023 +3.12, 2024 +4.07, 2025 +6.10, 2026 +3.46.

**Reading, descriptive.**
- The 2020s loss vs SPY is not lost selection on average. Score over the
  no-score pool is +2.85 %/yr, larger than post-2011's +2.00. The pool
  itself lost 4.85 %/yr to SPY, more than twice post-2011's 1.99.
- Selection in B is **carried by 2020**. Dropping 2020 takes it to about
  zero: −0.17 vs random, −0.87 vs noscore. Every other single-year drop
  leaves +2.3 or more.
- 2025 was a large negative selection year (−10.6), which is why dropping
  it gives the LOYO max.
- So "selection held up in the 2020s" rests on one year. In the other
  six it nets to about zero.
- Unlike post-2011 (LOYO min +1.59), B does not survive the LOYO drop.

**Map's forward formula, taken literally** (B, net, descriptive, not a
forecast): selection − universe drag = +3.56 − 4.85 = −1.29 %/yr vs SPY.
The realised score book was −1.99. As in WO-21, the gap is the null's
churn cost (−0.87 vs live −0.22). Which formula to use going forward is
for the COO and Gabe to decide.

### 2.5 Per calendar year, %/yr (rebalance-date year; 2026 partial, through 07-30)

icw8 (icw9_seas in the JSON; the pattern is the same):

| year | T random | (a) universe | (b) constr. | (c) costs | (b_g) | score net | score − noscore | selection net |
|---|---|---|---|---|---|---|---|---|
| 2020 | +8.82 | +9.59 | −0.77 | −0.90 | −0.02 | +33.12 | +23.53 | +24.30 |
| 2021 | −15.08 | −14.13 | −0.95 | −0.86 | −0.14 | −15.25 | −1.12 | −0.17 |
| 2022 | +3.63 | +4.12 | −0.49 | −0.85 | +0.34 | +4.00 | −0.12 | +0.37 |
| 2023 | −17.02 | −16.55 | −0.47 | −0.86 | +0.37 | −10.92 | +5.63 | +6.10 |
| 2024 | −9.16 | −8.44 | −0.72 | −0.87 | +0.12 | −8.49 | −0.05 | +0.66 |
| 2025 | −5.26 | −4.34 | −0.92 | −0.87 | −0.08 | −15.91 | −11.56 | −10.64 |
| 2026 | −4.90 | −4.19 | −0.71 | −0.87 | +0.14 | −0.21 | +3.98 | +4.69 |

- As in WO-21, the universe term drives every swing, while (b) and (c)
  sit flat near −0.8.
- The pool lost to SPY in five of seven years: 2021, 2023, 2024, 2025
  and 2026.

### 2.6 OLS (NW(39) t; alpha ×252/40), B, n = 1,652

**IWM does not cover B.** `IWM.csv` ends 2019-12-31. IWM is not in
`outcome_cache_v2`, which has only SPY and USMV, and the Sharadar panel
is stocks only. No IWM OLS was run, and no data was pulled.

The SPY OLS is reported instead:

| book | excess on SPY: slope (β−1), t | alpha, t | raw on SPY: β, R² |
|---|---|---|---|
| noscore | +0.070, +0.87 | −5.86 %, −1.82 | 1.070, 0.761 |
| random icw8 | +0.068, +0.85 | −6.54 %, −2.04 | — |
| score icw8 | +0.069, +0.98 | −2.99 %, −0.94 | — |
| score icw9_seas | +0.070, +0.90 | −3.03 %, −0.96 | — |

- As post-2011, the B drag is not SPY beta: the slope is not significant.
  It is an intercept.
- The pool's R² on SPY is only 0.76, against 0.97 on IWM in A. That is
  consistent with a small/mid-cap factor the SPY regression can't
  capture. Confirming it needs IWM data for 2020+.

### 2.7 Summary

- **Decomposition:** B's random-book drag is −5.55 %/yr, about twice
  post-2011. Universe is −4.85 (87 %), construction −0.71 (13 %, all null
  churn cost; gross +0.11), costs −0.87 (16 %).
- **Decision map:** **"universe bet"**, the same as WO-21. Both models,
  both bases and all draws agree.
- **Score book:** −1.99 vs SPY = pool −4.85 + score over pool +2.85.
- **Selection:** vs random +3.56 (sd40 0.91, 40/40). But it is
  2020-concentrated: LOYO min −0.17 with 2020 dropped. The average
  2020s selection did not disappear, but outside 2020 it is about zero.
- **icw9_seas:** it has twice icw8's name turnover (0.45 vs 0.23) and
  costs −0.43 vs −0.22. Its gross selection edge over icw8 (+0.19) is
  eaten by that cost.
