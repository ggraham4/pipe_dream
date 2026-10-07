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

## Step 2 pre-registration (committed BEFORE any model with the new columns is trained)

Written 2026-10-06, after Step 1 and before any Arm 1, Arm 2 or null fit. Arm 0 has been run because it uses no new column; its only use so far is the reproduction check.

No labels from the new columns have been read. Coverage numbers below are label-free (`store_meta.json`).

**Trial count.** This is batch-retrain trial 1, with 2 arms. The XGBoost line's history:
- Rounds 12–19: the score-cache sweep, the one-knob family (label, horizon, depth, window, cap, features). It spanned −8 to +9 %/yr, sd 5.03.
- Feature-backlog shuffle nulls: Round 19/20, about 15 single-column candidates and the options/short-interest eras.
- Round 15b certification as a standalone dead end: deflated Sharpe 0.746, Reality Check p = 0.61, sector-neutral IC −0.0038.
- Pre-2020, q75 alone had rank-IC +0.003 (t 0.12), against +0.048 for icw8.

Gabe reopened the line for this one batch retrain.

### Data

**Base panel:** `final/out/features_with_rates_sharadar_pit.parquet`, sha256 `18fa37b9…eb56c6`.
- It is the cache-era build, and it reproduces the cache bit-exactly (Step 1b).
- The 24 `price_fund` columns are loaded via `load_panel_prepared` (filter = 11 price columns, h = 40, tradable label), unchanged.
- The Oct-5 fundamentals panel is rejected: it does not reproduce the cache and it carries the ADRX merge.

**Hold-out handling.**
- Rows dated ≥ 2020-01-01 are dropped after the load.
- Any label whose 40-row exit is ≥ 2020-01-01 is set to NaN (89,274 labels). None of them could train a ≤ 2019 score date anyway.
- Stored rows: 7,353,383, dated 2006-02-01..2019-12-31.

**New columns.** Values come from the screen modules' frozen outputs, copied into `final/out/xgbretrain/inputs/` with sha256 recorded in `store_meta.json`. Duplicate copies of seas and SUE were verified identical. Each column is attached by (ticker, date) key lookup and takes the raw value; trees are rank-invariant, so no sign is applied.

| column | source | coverage on PIT rows 2007–2019 |
|---|---|---|
| `io_gap` | `overnight/build_io_gap.py`, `io_gap` | 99.99% |
| `seas` | `seasonality/build_seas.py`, `seas` | 88.8% |
| `sue` | `sue/build_sue.py`, `sue` | 90.4% |
| `ear` | `ear/build_ear.py`, `ear_raw` (NaN unless live, cap150 rows only) | 88.9% |
| `str_lowturn` | `volshock/screen_volshock.str_lowturn_rank` on the screen's universe (v2 column c, cap150), NaN outside it (frozen definition kept) | 99.9% |

**Coverage limits.**
- The v2 grid starts 2007-01-02, so all five columns are NaN on 2006 rows.
- With the 500k-row cap (about one year of rows), fits for score dates before roughly 2008-01 see few or no new-column values. Arms 1 and 2 are expected to sit close to Arm 0 there.
- PIT asserts are those of the source builders: every input is dated ≤ t (seas < t). They are asserted row by row in each builder's meta.

### Walk-forward

- One fit per trading day, 2007-01-02..2019-12-31: 3,272 score dates, which covers all 40 grid offsets.
- The procedure is the cached cell's:
  - cutoff = calendar[t − 40]; train rows = finite label, date ≤ cutoff, last 500k rows;
  - label = 1 if the tradable 40-day return is above the 75th percentile of those rows;
  - `binary:logistic`, hist, max_bin 256, single thread, seed 0.
- Every fit asserts that no training row's label exit is after the score date.
- Rows are scored on the PIT universe (the cached cell's scored set). Training never touches a row dated ≥ 2020.
- Code: `final/src/xgbretrain/run_arms.py`.

### Arms

- **Arm 0:** the 24 columns with q75 parameters (depth 3, eta 0.1, 100 rounds).
  - Correctness gate: reproduce the cached scores on 2007–2019 dates.
  - **Result before this pre-reg:** bit-exact on all 92,615 pre-2020 cached rows (82 dates), max |diff| 0. Tolerance used: exact.
- **Arm 1:** 24 + 5 columns with q75 parameters.
- **Arm 2:** 24 + 5 columns with **the one retune**, fixed here from first principles and not searched:
  - depth 3, eta 0.1, 100 rounds;
  - `colsample_bynode 0.5`;
  - `min_child_weight 100`;
  - `lambda 10`.
  - Rationale:
    - Depth stays 3 so 2–3-way interactions, the hypothesis, remain expressible.
    - Column subsampling stops the volatility columns from taking every split and gives weak columns split opportunities.
    - min_child_weight and L2 suppress small noisy leaves.
- **Nulls:** 5 per arm, seeds s = 1..5, built with `default_rng(1000+s)`.
  - Within each date, each of the 5 new columns is permuted among its own finite rows (NaN stays NaN), with an independent permutation per column, all five in one draw.
  - Applied to training and scoring rows alike.
  - The same 5 shuffled matrices serve both arms.

### Evaluation (`final/src/xgbretrain/evaluate.py`)

**Book (primary):** the blend's q75 leg construction.
- Universe: v2 panel, column-c rule, `eligible_cap2000`, 2007-01-02..2019-12-31.
- Score: the run's PIT-row score, NaN elsewhere.
- Picks: `composite.pick_decile_volq`.
- Returns: `gross_return_40` from `outcome_cache_v2`; picks without a return are dropped (WO-20 rule).
- Costs: net of 15 bp via `run_backtest.turnover_net_return`.
- Offsets: 40, `all_dates[off::40]`.
- Score dates run through 2019-12-31; their 40-day outcomes may run into early 2020 and stay in, unmasked (Gabe, WO-13).

**Primary metric:** mean over the 40 offsets of annualised (×252/40) net excess vs SPY. Plain net %/yr is reported beside it. Arm − Arm 0 differences are identical either way, since SPY cancels window by window.

**Reconciliations, asserted before any arm number:**
- R1: the cached q75 on its own single grid equals WO-20 v2c q75 0.0235164099 (tol 1e-9).
- R2: the cached q75's 50/50 blend with the live 9-factor composite on that grid equals WO-20 v2c blend_prev9 0.0251645940 (tol 1e-9).
- R3: icw9_seas (live 4-dp weights), cap150, 40 offsets, equals WO-20 frozen 0.0348652006 (tol 1e-6).
- R4: Arm 0 on the cached grid equals R1 (tol 1e-12).
- R5: the v2 calendar equals the XGB panel calendar on the era.

**Gate (sweep RUNBOOK §9).**
- Per arm: t = (arm − mean(5 nulls)) / (sd(nulls, ddof 1)·√(1+1/5)), one-sided p from t with 4 df.
- Benjamini-Hochberg across the 2 arms; pass at q ≤ 0.20.

**SUCCESS for an arm requires all four:**
1. the null gate passes;
2. arm − Arm 0 > 0 on ≥ 32/40 offsets (per-offset differences on identical windows);
3. no year carries more than 45% of the improvement;
   - year contribution = offset-mean of (sum of that year's window differences / that offset's window count)·252/40;
   - share = contribution / total difference;
   - max share ≤ 0.45, which requires total > 0;
   - negative years count as negative shares;
4. LOYO min of (arm − Arm 0) ≥ 0, where each LOYO value is the offset mean of the difference with one calendar year dropped.

The gap is also reported against the 5.03 %/yr noise scale. That comparison is not gated.

**KILL:** neither arm succeeds. Either way, report:
- the gain importance of the 5 new columns from every fit;
- mean |SHAP| on every 20th score date;
- parent-child split pairs involving a new column (new×old, new×new), as evidence of whether interactions with them are used.

**Context only, not gated:**
- the top-5 construction (best per vol quintile, inverse-vol weighted, same pool);
- daily rank-IC vs the tradable 40-day label on the same pool;
- the 50/50 blend of each arm with the live 9-factor composite;
- icw9_seas on cap2000, and the cap150 value from R3.

**Iteration cap:** 3 fix-and-rerun cycles, for bugs only. No change to features, arms, parameters, nulls or thresholds after any Arm 1 or Arm 2 real-label number is seen. A pass is a recommendation to Gabe; live q75 is unchanged.

## Step 2 results (run 2026-10-06/07, 2007–2019 only, no hold-out read)

**Verdict: KILL.** Neither arm meets any of the four success criteria. Live q75 is unchanged, and nothing is recommended for promotion.

All runs completed with 0 bug-fix cycles: 13 runs × 3,272 score dates, about 42.5k fits, with the per-fit leakage assert never tripping. The evaluation is `step2_results.json`, with reconciliations R1–R5 asserted first:

| check | value |
|---|---|
| R1: cached q75, own grid | 0.023516409867 (exact) |
| R2: cached q75 blend with live 9-factor | 0.025164593970 (exact) |
| R3: icw9_seas cap150 | 0.034865200579 (exact) |
| R4: Arm 0 on the cached grid | equals R1 |
| R5: calendars | equal (3,272 dates) |

**Primary metric.** decile_volq on cap2000 ∩ PIT-scored names, 40-offset mean, net of 15 bp:

| run | excess vs SPY %/yr | net %/yr | offsets > 0 |
|---|---|---|---|
| Arm 0 (24 cols, q75) | +2.224 | +9.733 | 40/40 |
| Arm 1 (+5, q75 params) | +2.176 | +9.685 | 40/40 |
| Arm 2 (+5, retune) | +2.387 | +9.896 | 40/40 |
| Arm 1 nulls (5) | +2.444 mean, sd 0.038 | | |
| Arm 2 nulls (5) | +2.562 mean, sd 0.049 | | |

**Gate and criteria:**

| | Arm 1 | Arm 2 |
|---|---|---|
| arm − Arm 0, %/yr | −0.048 | +0.163 |
| offsets positive (need ≥ 32) | 18/40 | 25/40 |
| LOYO min (need ≥ 0) | −0.269 (2007 dropped) | −0.086 (2007 dropped) |
| max year share (need ≤ 0.45) | n/a: total ≤ 0, so the criterion fails | 1.48 (2007) |
| null t (one-sided, df 4) | −6.48 | −3.26 |
| p | 0.998 | 0.984 |
| BH q (need ≤ 0.20) | 0.998 | 0.998 |
| gap / 5.03 %/yr noise scale | −0.01 | +0.03 |

**The real columns did worse than their own shuffles.**
- Every one of the 10 null draws beat Arm 0, by +0.18 to +0.39 %/yr.
- Both real arms land below their own null distributions.
- The nulls are **not pure noise columns.** The shuffle keeps each column's NaN pattern, as pre-registered, and that pattern carries information:
  - EAR is NaN unless an earnings event fell in the last 60 days.
  - EAR and str_lowturn are NaN outside cap150.
  - All five columns are NaN off the v2 grid.
- A plausible reading, **untested and not a finding**: missingness alone (earnings recency, cap150 membership, grid coverage) helps the book a little, and on this book the columns' values add nothing on top of it.
- This is the same pattern RUNBOOK §9 warns about ("the best cell was a scrambled one").

The year contributions to arm − Arm 0 are small and alternate in sign. 2007 is the largest positive year for both arms. In 2007 the new columns are mostly NaN in training (the v2 grid starts 2007-01-02), so those splits mostly encode "row has v2 data", effectively a date or coverage marker.

**Context only, not gated, no nulls:**

| run | daily rank-IC (cap2000 ∩ PIT) | top-5 volq excess | 50/50 blend with live 9-factor |
|---|---|---|---|
| Arm 0 | +0.0087 | +2.53 %/yr (33/40) | +2.32 %/yr |
| Arm 1 | +0.0134 | +3.79 %/yr (33/40) | +2.19 %/yr |
| Arm 2 | +0.0129 | +3.67 %/yr (34/40) | +2.24 %/yr |

(No t-statistic is given for rank-IC: daily dates with overlapping 40-day labels would inflate it about √40×.)

**Post-hoc descriptive null comparison for the context metrics** (`context_nulls.py` / `context_nulls.json`, not pre-registered, gates nothing):
- **Rank-IC:**
  - Arm 1 nulls: +0.01169 ± 0.00005 against the real +0.01339.
  - Arm 2 nulls: +0.01133 ± 0.00011 against the real +0.01292.
  - So the real columns' values do add about +0.0016 to +0.0017 of IC over their shuffles; most of the rise from Arm 0's +0.0087 comes with the shuffled columns too.
  - That IC gain does not reach the decile_volq book.
- **Top-5:**
  - Arm 1 nulls: +3.26 ± 0.31 %/yr against the real +3.79.
  - Arm 2 nulls: +4.06 ± 0.41 %/yr against the real +3.67.
  - The top-5 gain is therefore mostly something any 29-column tree gets, not the information in the columns.

- icw9_seas on the same cap2000 pool: +2.86 %/yr, rank-IC +0.0487.
- The arms raise rank-IC by about +0.005 and top-5 by about +1.2 %/yr. The descriptive nulls above show most of each comes from adding the columns' shape and missingness, not their values.
- The blend gets slightly worse with either arm.
- icw9_seas still beats every XGBoost arm on IC by about 3.6×.

**Are the new columns and their interactions used?** Yes, heavily. They are used and do not help. Source: `importance.json`, all 3,272 fits per arm.
- **Gain:** the new columns take 9.6% of total gain (Arm 1) and 9.5% (Arm 2). Shares by year range from 7% to 13%.
- **Splits:** 16% of all splits, about 7 of 10 trees per fit.
- **Mean splits per fit:** sue 31, seas 28, ear 27, io_gap 22, str_lowturn 7.5.
- **Interactions:** 29% of parent-child split pairs involve a new column (Arm 1: 159 new×old and 17 new×new per fit). Interactions with them are used.
- **SHAP:** mean |SHAP| share is seas 3.4%, sue 2.4%, ear 2.4%, io_gap 2.1%, str_lowturn 0.9%, against volatility_60 at 13.8%.
- **Top gain columns are unchanged:** volatility_60, pct_from_high_252, volatility_20, market_cap, momentum_20.

**Reading.** The tree spends about a tenth of its gain on the five columns, including interactions, and the book does not improve beyond what the same number of noise columns produce. The WO-46 state-dependence (net_issuance × hi52) is not something this model can harvest through these five columns either.

This is batch-retrain trial 1 of the XGBoost line (2 arms). Together with Rounds 12–19 it supports keeping XGBoost certified as a dead end for adding features. q75's role as the live blend's second leg is unaffected. Arm 0 is the cached cell behind the blend's backtest record, reproduced exactly. The live q75 is retrained on the Oct-5 panel (FLAG 2).

### Checks run / not run

**Run:**
- the Step 1 audit (both panels);
- bit-exact cache replay on 82 dates;
- Arm 0 bit-exact on 92,615 rows;
- per-fit leakage assert (42.5k fits);
- R1–R5 reconciliations;
- hold-out asserts on every frame read;
- input hashes and duplicate-copy identity.

**Not run:**
- a matched null for the blend context metric (top-5 and IC have the post-hoc descriptive one above);
- a second Arm 2 retune (not allowed);
- any 2020+ number.
