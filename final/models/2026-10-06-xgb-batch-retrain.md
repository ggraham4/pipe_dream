# WO-43: XGBoost (q75) batch-feature retrain (2026-10-06)

COO work order WO-43. Gabe launched it on 2026-10-06 ("Try WO43").
- Branch: `wo43-xgb-retrain`, based on integration e1f598d.
- Code: `final/src/xgbretrain/`.
- Outputs: `final/out/xgbretrain/`.
- Nothing here changes the live q75 model, its score cache, production weights or anything the app reads.

## Step 1: leakage audit of the q75 cache (read-only)

**Object audited:** `final/out/sweep/scores/price_fund_h40_q75_trd_xgb_d3e01r100_expanding_cap500k_pit_s40.parquet`
- sha256 `ae87d306…89db4`, written 2026-09-10.
- 124 score dates, 2007-01-03..2026-07-27.
- Produced by `sweep/scorecache.run_signal`.

**COO rule:** a training row whose label ends on the score date's close passes. A label ending strictly after the score date is a violation.

### Verdict: PASS for the cache (zero violations)

**Reconstructing the cache's input.** The fundamentals panel the cell names (`features_with_fundamentals_sharadar_pit.parquet`) was rebuilt on 2026-10-05, after the cache was written. The current build does **not** reproduce the cache: max |score diff| is 0.05 to 0.14 on the dates tried, with zero bit-equal rows (`step1b_cache_replay_current_panel_oct05.json`).

`features_with_rates_sharadar_pit.parquet` (2026-09-11, sha256 `18fa37b9…eb56c6`) was derived from the cache-era fundamentals panel. Refitting the cell from its 24 `price_fund` columns with the harness's own code reproduces the cached scores **bit-exactly on all 82 pre-2020 cache dates**:
- 82/82 dates match.
- Every scored ticker matches, with max |diff| = 0.
- Source: `step1b_cache_replay_features_with_rates_sharadar_pit_all_pre2020.json`.

That panel is therefore the cache's input, and the audit below runs on it (`step1_audit_features_with_rates_sharadar_pit.json`). 2020+ cache dates were not refit, because that would compute 2020+ labels. For those dates the evidence is the metadata-only audit: dates and label finiteness only.

1. **Row-shift check.** `load_panel_prepared` builds the 40-day tradable label `close[i+40]/open[i+1]-1` by **row position inside each ticker block** of the raw panel. So the risk is real in principle.
   - We computed every row's label exit date, the date of raw row i+40 in its block, against the market calendar.
   - Of 11,138,024 finite-label rows, **0 span more than 40 market days and 0 span fewer**: every label is exactly 40 market days.
   - Dates strictly increase inside all 4,030 ticker blocks.
   - We rebuilt the exact training mask for each of the 124 score dates: finite label, date ≤ cutoff, last 500k rows, same order. That gives 61,837,430 training-row uses with **0 violations** (0 before the cap as well).
2. **Cutoff proof.** On every one of the 124 score dates:
   - cutoff = calendar[score − 40];
   - the last training row is dated exactly on the cutoff;
   - the maximum label exit **equals** the score date (passes under the COO rule; entry is the next open).
   - The cache's timepoints equal `build_step_dates(calendar, 2007-01-02, 40)`.
3. **PIT spot checks (200 random pre-2020 cache rows).**
   - `momentum_20` and `volatility_20` recomputed from the ticker's close history truncated at t: 200/200 match.
   - Panel close vs raw Sharadar SEP close at t: 200/200 match.
   - `gross_margin` vs gp/revenue of the latest SF1 ARY filing with datekey ≤ t: 200/200 match. In 180/200 the next filing after t would have given a different value, so the as-of join really binds.
   - Cache `close`, `market_cap`, `volatility_20` and `volatility_60` are bit-equal to the panel on all 92,615 pre-2020 cache rows.
   - The scored ticker set equals PIT universe ∩ panel on 82/82 pre-2020 dates.
4. **Named example: AAPL on 2015-02-10.**
   - AAPL is in the PIT universe and is scored.
   - Cache close 30.505 = panel = SEP close.
   - Market cap $710.7B and vol60 0.01771 match the panel.
   - Score 0.2043 (36th percentile that date).
   - The refit reproduces the score bit-exactly (part of the 82-date replay).

### FLAG 1, current panel: a reused ticker merges two companies into one block (not in the cache)

On the 2026-10-05 panel (`step1_audit_current_panel_oct05.json`):
- **The merge:** ticker `ADRX` is one block holding the old company's 2005-2006 rows plus 6 rows of a **new listing dated 2026-09-25..2026-10-02**.
- **Effect on labels:** the row shift gives 6 rows (2006-09-11..2006-09-18) a "40-day" label that exits in 2026.
- **Effect on training:** they fall inside the training set of the 6 score dates 2007-01-03..2007-10-18, which is 36 violating row-uses (744 before the cap).
- **Scope:** it is the only span-over-40 case in the whole current panel (6 of 11.1M finite labels).
- **Why the cache is clean:** the 2026 rows did not exist when the cache was written (2026-09-10), and the cache-era panel has 0 such rows.
- **Live model:** the live q75 (`current_signal_pit.py`) trains on the most recent 500k labelled rows (2025-2026), so the 2006 rows are not in its window. This is not leakage for live.
- **Who is exposed:** any **re-run of a sweep cell on today's panel** would train its 2007 dates on 2026 prices.
- **Possible fix (Gabe/COO call, not done here):** split blocks on ticker reuse, as `__post` segmentation already does for price discontinuities.

### FLAG 2, panel drift (not leakage)

The 2026-10-05 fundamentals panel differs from the cache-era build on pre-2020 rows:
- 12,321,653 vs 12,335,243 raw rows;
- 4,015 vs 4,030 ticker blocks;
- the scored set differs (e.g. `CLGX` is now in the PIT pool on 2007 dates).
- Refits on it do not reproduce the cache.

So the cache's backtest record and today's live q75 come from different inputs. One line for the COO; not chased here.

Scripts:
- `final/src/xgbretrain/step1_audit.py [panel]`
- `final/src/xgbretrain/step1b_cache_replay.py [panel] [all]`
- xgboost 3.2.0.
