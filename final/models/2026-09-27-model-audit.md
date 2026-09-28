# WO-23: audit of the live models' weights and variables, plus the seasonality removal checks

Date: 2026-09-27 (work started), 2026-09-28 (pre-registration committed).
Work order WO-23 (COO). Branch `worktree-wo23-model-audit`, based on
`origin/integration` 9e169ce with WO-20 (`origin/worktree-agent-a790eb27c4530aa0a`
@ 56afb05, "WO-20-seas") merged in as input (merge commit ed65d59).

**Status: PRE-REGISTERED.** Sections 1 and 2 were committed before any
period-B (2020+) number was computed. After that commit they are not edited.
Results go only in section 3 onward.

**Hold-out.** Gabe gave a standing OK on 2026-09-27 for unfitted reads of
2020–2026. This read is logged as **hold-out read #5**. Nothing is fitted,
chosen or tuned on 2020+; every weight is the frozen live constant.

**Nature.** Descriptive only. NO fitting, NO weight changes. A flag is a
recommendation to Gabe; nothing is removed by this work order.

## 1. Work order (verbatim)

Models:
- Theoretical icw9_seas: 9 factors, cap150, v2 col c, decile_volq, 40 offsets, net 15bp.
- The blend: its 10-factor equal-weight composite leg plus the q75 leg, cap2000, single grid.

Periods, reported side by side: A = 2007–2019; B = 2020-01 to the last matured 40-day label.

For each factor and each period:
- pooled rank IC with Newey-West t;
- both-sides sector-demeaned t;
- per-year IC;
- leave-one-factor-out book delta for Theoretical (40-offset mean and sd40);
- the current weight next to the weight implied by that period's t under the same ICW rule. This is descriptive only and is never deployed.

At the model level: icw9_seas vs icw8, and blend10 vs blend9, in each period, with LOYO min and post-2011-10 in A.

Pre-fixed flags. A flag is only a recommendation to Gabe; nothing is removed.
- F1: the factor's IC is wrong-signed in BOTH A and B.
- F2: dropping the factor improves the Theoretical book in BOTH A and B by more than that period's sd40.

Seasonality checks:
- S1: in B, seas IC t ≤ 0 AND its leave-one-out delta ≤ 0 → recommend removal now.
- Otherwise S2 applies: removal is decided at the forward ledgers' 6th counted date.

This is 19 factor checks × 2 periods. Flags need agreement in both periods. Make no p-value claims.

## 2. Implementation pins (fixed before any period-B number)

These resolve every choice the work order leaves open. None is chosen by
looking at 2020+ data.

### 2.1 Periods

- **A** = panel dates 2007-01-02 .. 2019-12-31, exactly the WO-18 harness
  (`final/src/seasonality/screen_seas.py::load_universe`, which asserts
  max date < 2020-01-01). Late-2019 rows whose 40-day label ends in early
  2020 are kept, as in WO-13/WO-18.
- **B** = panel dates 2020-01-02 .. **2026-07-30**. 2026-07-30 is the last
  date on which SPY's `gross_return_40` in `outcome_cache_v2.parquet` has
  `truncated == False`; the next date (2026-07-31) has
  `forward_return_tradable_40` finite for 0% of cap150 rows, while 2026-07-30
  has it for 99.3%. (Label-availability metadata only; no return was read to
  set this.)

### 2.2 Theoretical (icw9_seas)

- Universe: `composite_panel_v2.parquet`, column-c ticker rule (old 4,011-ticker
  grid OR not a SPAC, as `downcap_v2_readout.load_column("c")`),
  `eligible_cap150`, outcomes `outcome_cache_v2.parquet` `gross_return_40`,
  SPY from the same cache. Period B uses an identical loader in the new module
  `final/src/audit/model_audit_wo23.py` with only the date bounds changed
  (`screen_seas.py` is not edited).
- Weights: `ic_weighted_composite.PRODUCTION_WEIGHTS_V9_SEAS` (frozen 4 dp,
  the live constant). icw8 = `PRODUCTION_WEIGHTS`. Scorer:
  `screen_insider.composite_score` over per-date `rank_z` (coverage-aware
  |w| renormalisation), shown equal to the live scorer by WO-20.
- Book: `screen_insider_v2grid.Book` → `composite.pick_decile_volq`, net
  15 bp via `run_backtest.turnover_net_return`, 40 grid offsets
  (`all_dates[off::40]` over that period's panel calendar), excess vs SPY
  annualised ×252/40; sd40 = population sd of the 40 offset means; LOYO min
  over calendar years within the period (`downcap_v2_readout.backtest`).
  Period A reproduces the WO-18/WO-20 numbers under the 40-offset mean.
- **Leave-one-factor-out:** for factor k, the book is re-run with weight k
  removed and the other frozen weights unchanged (the scorer renormalises by
  available |w|; no refit). **delta_k = excess(full icw9_seas) −
  excess(icw9_seas without k)**, 40-offset mean; sd40 of the delta series is
  also reported. Positive delta = the factor helps the book.
- The comparison sd40 for F2 is the sd40 of the full icw9_seas book in that
  period.

### 2.3 Blend

- Composite leg: `current_signal_blend._compute_composite_frozen_v10_seas`
  (blend10; 9 original factors incl. `asset_growth` + seas, equal weight) and
  `_compute_composite_frozen` (blend9), exactly as
  `final/src/seasonality/wo20_blend_seas_backtest.py` (v2c panel, column-c
  rule, cap2000, 50/50 `rank_z` blend with the q75 leg, decile_volq, net
  15 bp, single grid on q75's own ~60-day cadence).
- q75 leg: the cached `price_fund_h40_q75_..._s40.parquet` scores. A =
  timepoints < 2020-01-01 (82; reproduces `wo20_blend_seas_backtest.json`).
  B = timepoints 2020-01-14 .. 2026-07-27 (all ≤ 2026-07-30).
- Blend leave-one-factor-out (descriptive, single grid, no flag input):
  blend10 with factor k removed from the EW composite leg. Delta as in 2.2.

### 2.4 Per-factor statistics

- Daily cross-sectional Spearman IC of the raw factor vs
  `forward_return_tradable_40` (min 20 names/date), pooled mean with
  Newey-West lag 39 t (`screen_insider_v2grid.ic_gates`), on:
  Theoretical factors = cap150 column-c universe; blend factors = cap2000
  column-c universe, all panel dates of the period.
- Both-sides sector-demeaned t = `ic_gates(...)["sector_both_sides"]["t"]`.
- Per-year IC = mean daily IC by calendar year.
- **Wrong-signed** = sign(pooled mean raw IC) ≠ the factor's model sign
  (`SIGNS_V9_SEAS` / `_BLEND_FACTOR_SIGNS_V10_SEAS`). A NaN IC is not
  wrong-signed.
- Implied weight = the ICW rule `w_k = s_k·max(0.1, |t_k|−1)/Σ|·|` applied to
  that period's pooled raw t over the model's own factor set (9 for
  Theoretical, 10 for the blend). Note: the rule uses |t|, so a large
  wrong-signed t still receives weight in the model sign's direction; the
  table marks wrong-signed t's. Current blend weight = sign/10.

### 2.5 Seas in period B

- The WO-18 definition, identical (T = t + 28 days; month-end `closeadj`
  returns; mean over Y−10..Y−1, ≥ 5 finite; sign +1; the same 1998–2004
  splice), extended past 2019 by reading SEP month files 2020-01 .. 2025-12
  in addition (the latest B target month is 2026-08, whose returns end at
  2025-08; all 2005+ files come from the one 2026-09-09 bulk pull).
  Built by `final/src/audit/build_seas_ext.py`, which imports
  `build_seas.py`'s functions and does not edit it.
- Checks before use: (i) every pre-2020 row equals WO-18's
  `seas_factor_v2.parquet` exactly; (ii) on sample B dates the values equal
  `seas_live.py`'s at-score-time values (tolerance 1e-9); (iii) AAPL hand
  check; (iv) coverage by year on cap150 and cap2000.

### 2.6 Flags and S1 (decision rules, fixed)

- F1 (all 19 = 9 Theoretical + 10 blend factors): wrong-signed in A AND in B.
- F2 (the 9 Theoretical factors): delta_k < −sd40(full icw9_seas, A) in A AND
  delta_k < −sd40(full icw9_seas, B) in B.
- S1: in B, seas pooled IC t on the Theoretical cap150 universe ≤ 0 AND
  delta_seas (Theoretical, 40-offset mean) ≤ 0 → recommend removal now.
  Otherwise S2: removal is decided at the forward ledgers' 6th counted date.
- No p-value claims.

## 3. Results

(Filled after the pre-registration commit.)
