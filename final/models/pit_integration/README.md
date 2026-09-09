# Options model PIT/fundamentals integration (2026-09-02)

Per Gabe's request to integrate the survivorship-bias-corrected / PIT
(point-in-time) fundamentals data collected for the stock model into the
options premium model (previously flagged as a longer-term goal, explicitly
deferred as out of scope until now -- see
`models/options-premium-model-design.md`'s "Future plans" and this repo's
`AGENTS.md`).

**Bottom line: no clear win.** Full narrative, numbers, and caveats are in
`models/options-premium-model-design.md`'s "PIT/fundamentals integration"
section (Claude Project doc, not a file in this repo). Short version: adding
the point-in-time market-cap/price eligibility floor alone made the
walk-forward backtest modestly worse; adding the fundamentals features back
on top mostly recovered what the eligibility floor cost (and meaningfully
cut variance -- std 15.8% vs the original 41.6% for the equal-weight
approach) but did not clearly beat the existing production model, and the
underlying decile-ranking diagnostic (win-rate near-monotonic, mean-return
not) is essentially unchanged. Given only 5-6 usable backtest timepoints
throughout, none of this should be read as decisive either way.

## Pipeline (run in order, on Gabe's own machine -- see below)

1. **`build_options_pit_fundamentals_slim.py`** -- extracts a slim,
   ticker/column-filtered copy of `out/features_with_fundamentals_pit.parquet`
   (928MB, every PIT-tracked ticker) down to just the 496 tickers that
   appear in the options training data and the columns actually needed
   (market_cap, close, and 12 fundamentals ratios). Writes
   `data/options_pit_fundamentals_slim.parquet` (~40MB). **Must run on
   Gabe's machine** -- the full panel OOMs a device-bridge shell.
2. **`build_options_pit_features.py`** -- point-in-time asof-joins that
   slim fundamentals panel onto `options_calls_training.parquet` (nearest
   fundamentals snapshot on or before each option's own entry_date, no
   lookahead), then applies the same `market_cap >= $2B` / `close >= $10`
   eligibility floor the stock PIT model uses (`continuous_walkforward_pit.py`),
   evaluated at the option's OWN entry_date rather than "is this ticker on
   today's list." Writes `options_calls_training_pit.parquet` (the
   eligibility-filtered, fundamentals-joined table) and
   `options_calls_training_fundjoin_only.parquet` (fundamentals joined but
   NOT eligibility-filtered, kept for the ablation). Ran in the cloud
   sandbox (small files, no OOM risk) -- reproducible either place.
3. **`train_options_pit_model.py`** -- retrains the Tweedie GLM under the
   Round 2 purged walk-forward CV protocol (4 folds, cutoffs
   2023/2024/2025/2026-01-01, 25-combo power/alpha grid, final holdout
   entry_date>=2026-04-01) for three variants: OLD (original, unfiltered
   universe, price/vol features only -- this is also, incidentally, the
   first real reproduction script for Round 2's methodology, closing the
   "no reproduction script" gap flagged in AGENTS.md's Known Gaps), BASE_PIT
   (eligibility floor only), AUG_PIT (eligibility floor + fundamentals).
   Saves `results/pit_model_comparison_results.json` and
   `results/final_model_calls_pit_augmented.pkl`.
4. **`backtest_pit_variants.py`** -- reruns the two production backtests
   (equal-weight top-5, calibrated-decile Kelly) for all three variants.
   `HYPERPARAM_SOURCE = "fixed"` (the default, recommended) scores all three
   variants at the CURRENT PRODUCTION hyperparameters (power=1.4,
   alpha=0.001) so the comparison isolates the DATA change, not an
   independent hyperparameter retune -- and its OLD variant exactly
   reproduces the existing documented backtest numbers to the basis point,
   which is what validates that this whole reproduction pipeline is
   behaving correctly. Set it to `"tuned"` to instead score each variant
   with its own from-scratch-retuned hyperparameters (a secondary check,
   see `results/*_tuned.*`).
5. **`decile_diagnostic_pit_variants.py`** -- reruns the pooled-decile
   ranking diagnostic (spearman rank correlation, per-decile mean/win-rate)
   for all three variants at the fixed production hyperparameters.

## Where things must run

Steps 1 needs Gabe's machine (full PIT panel, OOMs the device-bridge shell).
Steps 2-5 use only the small (<50MB) files those produce and were run in
Claude's cloud sandbox this session -- reproducible there or on Gabe's
machine, whichever is convenient going forward.

## Results directory

- `pit_model_comparison_results.json` -- Step 3's full CV grid + holdout
  metrics for all three variants.
- `backtest_summaries_fixed.json` / `backtest_*_fixed.csv` -- Step 4's
  primary comparison (fixed production hyperparameters).
- `backtest_summaries_tuned.json` / `backtest_*_tuned.csv` -- Step 4's
  secondary comparison (each variant's own retuned hyperparameters).
- `decile_table_*.csv` -- Step 5's pooled decile tables.
- `final_model_calls_pit_augmented.pkl` -- the trained AUG_PIT model
  (scaler + Tweedie GLM + feature list + winning hyperparameters from its
  own from-scratch retune, NOT the fixed-hyperparameter version -- refit
  with power=1.4/alpha=0.001 first if adopting this into `live_score.py`).

Nothing here has been wired into `app.py`, `options_model.py`, or
`live_score.py` -- this is research output only, not a production change.
