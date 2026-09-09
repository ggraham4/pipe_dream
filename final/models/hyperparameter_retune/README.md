# Full hyperparameter re-evaluation (2026-09-02)

Per Gabe's request, following the PIT/fundamentals integration pass:
"reevaluate all of the hyperparameters given all of the new data we now
have." Full narrative and numbers in
`models/options-premium-model-design.md`'s "Hyperparameter re-evaluation"
section (Claude Project doc). Short version:

**Recommendation: keep the current production hyperparameters (Tweedie GLM,
power=1.4, alpha=0.001).** A much wider/deeper search found different
"winners" on offline metrics (Tweedie power=1.1 on CV deviance; GAM hurdle
on MAE), but neither beat the current production choice in the walk-forward
dollar backtest that actually matters. **GAM in particular is a genuine
trap**: it wins clearly on held-out MAE (1.02-1.05 vs Tweedie's 1.08-1.09)
but produces a catastrophic backtest (-44% to -72% average return, 0-2 win
rate out of 5 years) — it overfits badly on the smaller training pools
early backtest timepoints have, something a single large final-holdout
metric never exposed. This is a real, worth-remembering methodological
lesson, not just a negative result to file away.

## Scripts (run in order, from `final/`)

1. **`retune_all_hyperparameters.py`** -- sweeps Tweedie GLM (63 combos:
   power 1.1-1.9 step 0.1 x alpha in {0,0.001,0.01,0.03,0.1,0.3,1.0}, vs.
   Round 2's original coarser 25-combo grid) and a GAM hurdle model
   (LogisticRegression for P(ITM) x GammaGAM for magnitude, lam in
   {20,100} x n_splines in {6,10}, matching Round 2's grid -- a wider GAM
   grid wasn't practical, see caveats below), on the same purged
   walk-forward CV protocol as Round 2, for all three universe/feature
   variants (OLD/BASE_PIT/AUG_PIT from the PIT integration pass). Picks a
   per-variant winner by holdout MAE, saves
   `results/retune_all_hyperparameters_results.json`.
2. **`backtest_retuned_models.py`** -- takes those per-variant winning
   hyperparameters (both the Tweedie-retuned AND the GAM candidate) and
   reruns the actual walk-forward dollar backtest (equal-weight top-5 +
   calibrated-decile Kelly optimizer) for all of them. This is the step
   that caught GAM's real-world failure -- its CV-holdout MAE advantage
   does not survive contact with the actual selection-and-trade backtest.

## Known limitations of this pass

- **GAM's hyperparameter grid was not widened** the way Tweedie's was --
  a single GammaGAM fit on the new 32-feature (with fundamentals) dataset
  takes 15-45s even capped at 150k rows, so a comparably wide grid would
  have taken hours. If GAM is ever revisited, a real speed fix (fewer
  spline terms, a feature-selection pass before GAM, or accepting a much
  longer run) would be needed before a wider GAM grid is practical.
- **The GAM backtest failure was diagnosed by pattern, not root-caused
  line-by-line** -- the "-76.63% at 2021-01-15 across all three variants"
  result strongly suggests overfitting on a small/early training pool
  (GAM's many spline parameters relative to how little data exists that
  early in the walk-forward), but this wasn't confirmed with, e.g., a
  learning-curve plot showing GAM's holdout performance as a function of
  training-set size. Worth doing if GAM's write-off is ever questioned.
- **This full re-tune only covers calls** (puts are still shelved, per the
  earlier, unresolved "puts don't have a working model" finding -- not
  reinvestigated here).
