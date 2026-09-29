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

## 2. Results

(filled after the run)
