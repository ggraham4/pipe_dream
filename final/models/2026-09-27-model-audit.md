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

Run 2026-09-28 on branch `worktree-wo23-model-audit` after the pre-registration
commit 8a58c88. Code: `final/src/audit/build_seas_ext.py`,
`final/src/audit/model_audit_wo23.py`, `final/src/audit/summarize_wo23.py`.
Outputs: `final/out/audit/model_audit_wo23{,_A,_B}.json`, run logs
`model_audit_wo23_{A,B}.log`, `build_seas_ext_meta.json`
(`seas_factor_ext.parquet` is gitignored; rebuild with `build_seas_ext.py`,
about 3 minutes).

### 3.1 Headline

- **F1: no flag.** None of the 19 factors is wrong-signed in both A and B.
- **F2: no flag.** No Theoretical factor's removal improves the book by more
  than sd40 in both periods. Only net_issuance_pct clears the bar in A
  (−0.35 vs sd40 0.22 %/yr), and it does not clear it in B (−0.28 vs 1.03).
- **S1: not triggered.** In B, seas has IC t = +0.23 (> 0) and a Theoretical
  LOO delta of −0.03 %/yr (≤ 0). Both halves of S1 must hold; the t half
  fails. **S2 applies:** removal of seas is decided at the forward ledgers'
  6th counted date.
- **Not a flag, but the most important descriptive fact:** both live models
  are **below SPY in B**. Theoretical icw9_seas is −2.02 %/yr (0/40 offsets
  positive, offset range −3.93..−0.35) and icw8 is −1.99 %/yr. The blend is
  −1.41 %/yr (blend10) vs −0.63 %/yr (blend9). 2020 is strongly positive and
  2021 and 2023–2025 are negative (per-year excess below). Adding seas changed
  B by −0.02 %/yr (Theoretical) and −0.78 %/yr (blend, single grid).
- **In B, seas is about zero.** IC +0.0017 (t +0.23), sector t +0.67. Its
  per-year IC is mixed: 2020–2022 are negative, 2023–2024 positive, and 2026
  (Jan–Jul) is −3.6. In A it was +0.0113 (t +2.84). Its implied weight falls
  from +0.10 (A) to +0.008 (B); the live weight is +0.19.

### 3.2 Reconcile (hard asserts, before any other number)

| check | got | reference | tol | result |
|---|---|---|---|---|
| icw8, A, 40-offset mean | +0.0285416326 | +0.0285416 | 1e-6 | PASS |
| icw9_seas full precision, A | +0.0348710491 | +0.0348710 | 1e-6 | PASS |
| icw9_seas live 4-dp constant, A | +0.0348652006 | WO-20 `wo20_frozen_backtest.json` +0.0348652006 | 1e-9 | PASS |
| blend_prev9, A, single grid | +0.0251645940 | `wo20_blend_seas_backtest.json` +0.0251645940 | 1e-9 | PASS |
| blend_seas10, A, single grid | +0.0240069670 | +0.0240069670 | 1e-9 | PASS |
| generic loader (A) vs `screen_seas.load_universe` | 9,756,141 rows, all used columns equal | | exact | PASS |
| LOO cross-check: delta_seas vs icw9_seas − icw8 | A +0.00630 vs +0.00632; B −0.00028 vs −0.00025 | | ≈ 4-dp rounding | consistent |

The work order's +0.0348710 is the COO's **full-precision** icw9_seas. The live
constant `PRODUCTION_WEIGHTS_V9_SEAS` is its 4-dp rounding. WO-20 recorded
the gap as −5.85e-6, so both are reconciled. Every audit number uses the live
4-dp constant, per section 2.2.

**Seas extension checks (section 2.5):**
- (i) All 13,253,466 pre-2020 rows are identical to WO-18's
  `seas_factor_v2.parquet` in seas, seas_nyears and target_ym.
- (ii) `seas_live.seas_asof` equals the extension on 7 B dates from
  2020-01-02 to 2026-07-30, with max abs diff 0.0 and equal NaN and nyears
  patterns.
- (iii) AAPL hand check (independent loops on raw SEP) equals the extension
  on 2020-06-01 (−0.01516), 2023-01-03 (−0.01405) and 2026-07-30 (+0.06523).
- (iv) seas coverage on cap150 is 0.71–0.85 by year in B (A: 0.76–0.85). On
  cap2000 it is 0.79–0.89 (A: 0.83–0.90).

### Theoretical icw9_seas (cap150), per factor

| factor | sign | live w | implied w A | implied w B | IC A (t) | IC B (t) | sector t A | sector t B | LOO delta A (sd40) | LOO delta B (sd40) | F1 | F2 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| momentum_12_1 | +1 | +0.0402 | +0.0217 | +0.0571 | +0.0165 (+1.39) | +0.0308 (+1.68) | +1.56 | +2.14 | +0.08 (0.13) | +0.62 (0.64) | - | - |
| pct_from_high_252 | +1 | +0.0105 | +0.0608 | +0.1075 | +0.0309 (+2.09) | +0.0520 (+2.29) | +2.20 | +2.22 | -0.01 (0.10) | -0.07 (0.13) | - | - |
| volatility_60 | -1 | -0.0105 | -0.1059 | -0.1072 | -0.0418 (-2.90) | -0.0620 (-2.28) | -3.33 | -2.08 | +0.03 (0.10) | +0.23 (0.27) | - | - |
| gross_profitability | +1 | +0.4808 | +0.2797 | +0.2046 | +0.0393 (+6.03) | +0.0411 (+3.45) | +4.51 | +3.43 | +1.49 (0.28) | +0.87 (1.14) | - | - |
| accruals | -1 | -0.1314 | -0.0056 | -0.0527 | -0.0024 (-0.39) | +0.0154 (+1.63) WS | -0.28 | -0.09 | +0.17 (0.14) | -0.05 (0.47) | - | - |
| net_issuance_pct | -1 | -0.1129 | -0.2361 | -0.2937 | -0.0341 (-5.25) | -0.0731 (-4.52) | -4.56 | -2.95 | -0.35 (0.16) | -0.28 (0.48) | - | - |
| days_to_next_filing_seasonal | -1 | -0.0105 | -0.1826 | -0.0106 | -0.0106 (-4.28) | -0.0056 (-1.13) | -4.61 | +1.31 | -0.03 (0.12) | +0.26 (0.28) | - | - |
| short_interest_days_to_cover | -1 | -0.0105 | -0.0056 | -0.1582 | n/a (n/a) | -0.0266 (-2.89) | n/a | -1.65 | +0.00 (0.00) | +0.02 (0.33) | - | - |
| seas | +1 | +0.1928 | +0.1021 | +0.0084 | +0.0113 (+2.84) | +0.0017 (+0.23) | +2.87 | +0.67 | +0.63 (0.23) | -0.03 (0.40) | - | - |

LOO deltas in %/yr (full minus without; + = factor helps). F2 thresholds: sd40(full) A 0.22, B 1.03 %/yr. WS = wrong-signed.

### Blend composite leg (cap2000), per factor

| factor | sign | live w | implied w A | implied w B | IC A (t) | IC B (t) | sector t A | sector t B | LOO delta A (1 grid) | LOO delta B (1 grid) | F1 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| momentum_12_1 | +1 | +0.1000 | +0.0093 | +0.0171 | +0.0137 (+0.93) | +0.0148 (+0.73) | +1.16 | +0.85 | +0.25 | +0.95 | - |
| pct_from_high_252 | +1 | +0.1000 | +0.0093 | +0.0171 | +0.0153 (+0.91) | +0.0091 (+0.43) | +1.25 | +0.60 | +0.44 | -0.73 | - |
| volatility_60 | -1 | -0.1000 | -0.0093 | -0.0171 | -0.0101 (-0.55) | -0.0103 (-0.37) | -0.73 | -0.43 | +0.17 | -0.27 | - |
| gross_profitability | +1 | +0.1000 | +0.4033 | +0.1118 | +0.0444 (+5.35) | +0.0235 (+1.65) | +2.88 | +2.06 | +1.41 | -1.23 | - |
| accruals | -1 | -0.1000 | -0.1489 | -0.0171 | -0.0174 (-2.61) | +0.0058 (+0.65) WS | -1.89 | -0.84 | +0.53 | +0.13 | - |
| asset_growth | -1 | -0.1000 | -0.0093 | -0.0171 | +0.0074 (+0.93) WS | -0.0063 (-0.47) | +0.52 | +0.46 | -1.19 | -0.46 | - |
| net_issuance_pct | -1 | -0.1000 | -0.2631 | -0.3630 | -0.0284 (-3.84) | -0.0446 (-3.12) | -2.84 | -2.38 | -0.21 | +0.12 | - |
| days_to_next_filing_seasonal | -1 | -0.1000 | -0.0358 | -0.0171 | -0.0041 (-1.39) | -0.0002 (-0.04) | -1.01 | +1.55 | -0.44 | +0.32 | - |
| short_interest_days_to_cover | -1 | -0.1000 | -0.0093 | -0.4053 | n/a (n/a) | -0.0294 (-3.36) | n/a | -2.90 | +0.00 | +1.66 | - |
| seas | +1 | +0.1000 | +0.1025 | +0.0171 | +0.0118 (+2.11) | +0.0022 (+0.26) | +2.09 | +0.96 | -0.12 | -0.78 | - |

### Model level (excess vs SPY, %/yr, net 15bp)

| model | A mean | A sd40 | A LOYO min (yr) | A post-2011-10 | B mean | B sd40 | B LOYO min (yr) |
|---|---|---|---|---|---|---|---|
| icw9_seas (40 offsets) | +3.49 | 0.22 | +2.46 (2009) | +0.51 | -2.02 | 1.03 | -8.39 (2020) |
| icw8 (40 offsets) | +2.85 | 0.30 | +1.71 (2009) | +0.01 | -1.99 | 1.12 | -8.33 (2020) |
| blend_seas10 (1 grid, n=82/42) | +2.40 | - | +1.87 (2013) | +0.20 | -1.41 | - | -5.19 (2020) |
| blend_prev9 (1 grid, n=82/42) | +2.52 | - | +2.07 (2010) | +0.60 | -0.63 | - | -4.85 (2020) |

icw9_seas - icw8: A +0.63 (sd40 0.23), B -0.02 (sd40 0.41) %/yr.
blend10 - blend9: A -0.12, B -0.78 %/yr (single grid).

S1: seas B t = +0.23, LOO delta B = -0.03 %/yr -> S2: removal decided at the forward ledgers' 6th counted date

### Per-year mean daily IC, theoretical (cap150)

| factor | 2007 | 2008 | 2009 | 2010 | 2011 | 2012 | 2013 | 2014 | 2015 | 2016 | 2017 | 2018 | 2019 | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 | 2026 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| momentum_12_1 | +6.4 | +2.6 | -14.7 | +2.9 | +1.9 | +6.0 | +5.2 | +1.3 | +10.1 | -7.0 | +2.9 | -1.4 | +5.3 | -0.6 | -0.3 | +9.0 | +5.5 | +5.5 | +1.6 | -0.9 |
| pct_from_high_252 | +12.1 | +7.2 | -16.9 | -2.2 | +4.9 | +3.3 | +1.2 | +6.6 | +14.1 | -6.4 | +5.0 | +4.1 | +7.2 | -6.2 | +13.8 | +9.4 | +5.9 | +8.9 | +0.9 | +2.7 |
| volatility_60 | -7.6 | -10.7 | +8.5 | +2.4 | -7.4 | -4.3 | +3.2 | -10.6 | -14.5 | +3.6 | -2.9 | -6.4 | -7.5 | +10.1 | -22.1 | -12.1 | -6.1 | -9.2 | +1.2 | -4.5 |
| gross_profitability | +4.6 | +6.7 | +6.4 | +3.5 | +5.7 | -0.5 | +5.1 | +3.2 | +2.0 | -2.3 | +7.6 | +7.1 | +2.0 | +8.8 | +7.3 | +5.1 | +7.3 | +2.2 | -4.1 | +0.8 |
| accruals | -1.2 | -1.0 | -5.4 | -5.0 | -0.2 | +2.6 | -2.9 | +1.1 | +5.0 | +1.1 | +0.1 | -1.7 | +4.4 | -4.2 | +2.9 | +1.8 | +1.4 | +3.7 | +4.4 | +0.3 |
| net_issuance_pct | -1.8 | -5.7 | -0.7 | -1.0 | -6.5 | -3.9 | -3.4 | -5.1 | -5.6 | -0.7 | -4.2 | -2.9 | -2.7 | +2.3 | -21.2 | -10.8 | -7.6 | -5.1 | -2.2 | -5.9 |
| days_to_next_filing_seasonal | -1.6 | -1.4 | -2.0 | -0.3 | -0.9 | -1.4 | -0.1 | -1.3 | -1.9 | -0.7 | +0.2 | -0.4 | -1.9 | -0.4 | -0.7 | -1.6 | -1.0 | -0.7 | -0.2 | +1.4 |
| short_interest_days_to_cover | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | +2.3 | -5.3 | -4.0 | -4.4 | -5.3 | -0.9 | +2.9 |
| seas | +1.6 | +4.0 | +1.1 | +1.5 | +3.2 | +0.2 | +1.9 | +2.2 | +1.2 | +0.4 | -2.1 | -0.4 | -0.1 | -0.6 | -1.8 | -0.1 | +2.9 | +2.1 | +0.8 | -3.6 |

Values are IC x 100. 2026 covers Jan-Jul (144 dates).

### Per-year mean daily IC, blend (cap2000)

| factor | 2007 | 2008 | 2009 | 2010 | 2011 | 2012 | 2013 | 2014 | 2015 | 2016 | 2017 | 2018 | 2019 | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 | 2026 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| momentum_12_1 | +6.2 | +2.1 | -14.5 | +3.3 | -0.5 | +6.0 | +7.3 | -0.8 | +9.0 | -8.7 | +4.7 | -1.6 | +5.3 | +3.4 | -7.4 | +2.2 | +4.0 | +6.6 | +1.5 | -0.9 |
| pct_from_high_252 | +10.5 | +8.0 | -20.9 | -3.9 | +2.5 | +1.0 | +1.1 | +3.7 | +13.0 | -7.5 | +5.3 | +2.6 | +4.3 | -4.0 | +3.7 | +2.0 | +0.4 | +6.1 | -1.1 | -1.9 |
| volatility_60 | -0.7 | -13.3 | +14.8 | +9.5 | -5.8 | -0.7 | +4.7 | -7.9 | -11.7 | +6.5 | -0.2 | -5.0 | -3.2 | +14.0 | -16.9 | -7.0 | +2.0 | -3.8 | +5.0 | +0.0 |
| gross_profitability | +4.0 | +8.5 | +3.3 | +3.3 | +7.0 | +0.1 | +5.9 | +2.5 | +4.6 | -4.0 | +11.8 | +6.3 | +4.3 | +8.7 | +1.8 | +1.8 | +8.2 | -1.6 | -3.1 | -0.7 |
| accruals | -4.4 | -5.5 | -3.3 | -3.6 | -3.4 | +2.1 | -1.2 | -2.4 | +2.0 | +1.4 | -1.8 | -4.2 | +1.7 | -5.4 | +2.7 | +2.8 | -1.7 | +2.9 | +4.1 | -2.7 |
| asset_growth | +7.2 | -1.8 | -0.5 | +2.1 | -0.7 | -4.7 | -0.4 | -1.0 | -0.0 | -0.9 | +4.7 | +1.6 | +4.0 | +7.5 | -9.8 | -4.9 | +1.7 | +3.0 | -0.5 | -1.9 |
| net_issuance_pct | +0.5 | -4.9 | -1.5 | +0.6 | -6.6 | -3.7 | -6.4 | -2.6 | -5.5 | -1.7 | -5.7 | +1.4 | -0.9 | +3.6 | -15.5 | -8.3 | -4.3 | -0.3 | -2.5 | -3.5 |
| days_to_next_filing_seasonal | -1.1 | -3.3 | -0.7 | +1.0 | -1.4 | +1.3 | -0.6 | -0.6 | -2.0 | +0.2 | +1.3 | +1.5 | -0.9 | +1.8 | -1.7 | -2.1 | +0.1 | -0.1 | -0.1 | +3.5 |
| short_interest_days_to_cover | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | +3.2 | -6.9 | -2.1 | -4.3 | -4.0 | -5.0 | +2.9 |
| seas | +2.2 | +4.8 | +2.5 | +2.8 | +3.9 | -0.7 | +1.0 | +0.8 | +0.8 | +1.3 | -3.5 | -0.5 | -0.1 | -0.4 | -2.8 | +0.3 | +3.9 | +2.6 | +0.6 | -4.6 |

Values are IC x 100. 2026 covers Jan-Jul (144 dates).

### 3.3 Notes for reading the tables

- **Implied weights in A do not reproduce the live weights, even in-sample.**
  The live t's come from the v1-panel `ic_weighted_composite_report.json`.
  These t's are on v2 column-c cap150, and for the blend on cap2000. The
  difference is a panel/universe difference, not drift. Examples:
  gross_profitability (live +0.48, A-implied +0.28) and accruals (live −0.13;
  the column-c A t is only −0.39, so A-implied is −0.006).
- **The ICW rule uses |t|.** A wrong-signed t still gets weight in the model
  sign's direction. Accruals in B (t +1.63, wrong-signed) gets an implied
  weight of −0.053 for that reason. Read implied weights next to the WS marks.
- **short_interest_days_to_cover has no data in A.** Coverage on cap150 is 0%
  for every year 2005–2019 and 61–99% for 2020–2026. In A its t is NaN, so the
  rule gives it the floor, and it is not wrong-signed. In B it is correctly
  signed and strong (t −2.89 cap150, −3.36 cap2000), but the live model holds
  it at the floor weight (−0.0105 Theoretical, −0.10 EW blend).
- **Near-misses (no flag).** Accruals is wrong-signed in B for both models
  and weak in A on column c (t −0.39 cap150). For the blend, asset_growth is
  wrong-signed in A and weak in B (t −0.47). days_to_next_filing_seasonal's
  sector-demeaned t flips sign in B (cap150 −4.61 → +1.31).
- **Blend LOO** is on a single grid (82 A windows, 42 B windows) and is not a
  flag input. Its per-factor deltas are large relative to the Theoretical
  40-offset deltas, which is what one grid gives.
- **The q75 leg in B** is the cached expanding-window XGB score file. This
  work order did not check its 2020+ training-window purge. That is a caveat,
  not a check.
- **2026** in the per-year tables covers Jan–Jul (144 dates). The last B
  rebalance date is 2026-07-30 for Theoretical and 2026-07-27 for the blend's
  q75 timepoint.

### 3.4 Per-year excess vs SPY (%/yr, offset-averaged for Theoretical; single grid for the blend)

| model | 2007 | 2008 | 2009 | 2010 | 2011 | 2012 | 2013 | 2014 | 2015 | 2016 | 2017 | 2018 | 2019 | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 | 2026 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| icw9_seas | −9.9 | +15.0 | +15.7 | +12.1 | +10.1 | +0.1 | +5.2 | −1.0 | −4.1 | +2.3 | +0.6 | +9.3 | −10.4 | +33.3 | −18.3 | +3.9 | −11.5 | −5.7 | −15.2 | −0.3 |
| icw8 | −11.9 | +14.8 | +16.5 | +10.0 | +8.6 | −0.7 | +4.4 | −0.8 | −5.7 | +0.6 | +1.5 | +10.6 | −11.3 | +33.1 | −15.3 | +4.0 | −10.9 | −8.5 | −15.9 | −0.2 |
| blend10 | +4.5 | +6.5 | +5.1 | +7.8 | +6.1 | +0.3 | +8.0 | −6.0 | −6.1 | −1.6 | +0.8 | +6.1 | −2.4 | +17.5 | −10.0 | +10.3 | −6.4 | −6.8 | −7.0 | −13.9 |
| blend9 | +3.1 | +3.9 | +7.9 | +7.3 | +5.6 | −0.5 | +6.5 | −4.8 | −5.2 | −1.2 | +1.3 | +7.5 | −0.0 | +20.5 | −7.4 | +11.5 | −7.8 | −6.2 | −8.7 | −13.2 |

## 4. Deviations from the pre-registration

1. **Check (i), section 2.5.** The pre-registration says every pre-2020 row
   equals WO-18 exactly. The factor columns (seas, seas_nyears, target_ym) do.
   The metadata column `in_sep` (ticker present anywhere in the SEP span read)
   differs on 90 rows (8 tickers), because those tickers' SEP rows start after
   2019. All 90 rows have NaN seas in both files, so no factor value differs.
   The check compares the factor columns and reports the `in_sep` flips.
2. **Reconcile target for icw9_seas.** The +0.0348710 in the work order is
   the full-precision run (see 3.2). It is reconciled at 1e-6, and the live
   4-dp constant is reconciled to WO-20's recorded value at 1e-9. The audit
   uses the live constant, as pinned in 2.2.

No other deviation. Nothing was fitted, and no weight or file outside
`final/src/audit/`, `final/out/audit/` and this doc was changed.
