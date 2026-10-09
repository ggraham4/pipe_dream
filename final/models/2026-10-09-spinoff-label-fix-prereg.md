# WO-54 pre-registration: Sharadar spin-off ex-date label fix

Date: 2026-10-09. Owner: Gabe. Commissioned by the COO (WO-54, Gabe: "lets continue with WRDS work orders").
Branch `wo54-spinoff-labels`, based on origin/integration d09101b. Gate A correctness work.
**Trial count 0**: no new signal, no weight change, no hold-out read, no live change.
Written and frozen before any book statistic is computed.

## Why

WO-51 (`final/models/2026-10-08-crsp-sharadar-audit-results.md`) found that Sharadar's split-only price
series books spin-off ex-dates as -60% to -93% one-day returns (SSP 2008-07-01, CY 2008-09-30, MO 2008-03-31,
ITT 2011-11-01, ...). Any 40-day forward label whose window spans such a date is wrong. The CRSP re-base is
closed (D-WRDS-REBASE: NO); this order fixes only the spin-off labels.

## Hypothesis

None about returns. The question is descriptive plus one book read: how many labels are wrong, does the fix
correct the named cases, and how much does it move the deployed baseline book.

## Data

- CRSP legacy `crsp.dsedist` (distributions, exdt 2007-01-01..2019-12-31), pulled to
  `final/data/wrds/crsp/dsedist_3xxx.parquet` (main checkout, gitignored, never committed).
- CRSP daily `final/data/wrds/crsp/dsf_YYYY.parquet` (WO-51 pull): `ret`, `retx`, `prc` on the ex-date and the prior day.
- Crosswalk `final/data/wrds/link/permno_sharadar.parquet` (WO-51).
- Sharadar per-ticker OHLC CSVs (`final/scripts/td_data_sharadar`, `td_data_sharadar_downcap_v2`), read up to
  2019-12-31 only; the labels themselves come from `final/out/reset2026/outcome_cache_v2.parquet` (read only).
- Sharadar ACTIONS cross-check: the local `final/data/sharadar/actions.csv` has no spin-off rows dated 2007-2019,
  so this cross-check is reported as not available for the era.

## Detection rule (frozen)

1. Candidate distributions: `dsedist` rows with `distcd` between 3000 and 3999 **and** `facpr > 0`,
   `exdt` in 2007-01-01..2019-12-31. (Codes with `facpr = -1`, e.g. 3225, 3723, 3783, 3883, 3325, are terminal
   cash-outs / exchanges at a merger, not spin-offs, and are excluded.) Collapse to one event per (permno, exdt);
   several rows on one date (e.g. ITT 2011-11-01: two spin-offs plus a 1:2 reverse split) form one event.
2. CRSP guards: the permno has a CRSP `dsf` row on exdt with finite `ret` and `prc > 0` (a negative `prc` is a
   bid/ask midpoint: skip, count), a CRSP row on the previous trading day with `prc > 0`, and at least one CRSP row
   after exdt. Failures are skipped and counted by reason.
3. Mapping: Sharadar ticker = the crosswalk row with `valid_from <= exdt <= valid_to` (WO-47 segmentation is
   already in the crosswalk). Unmapped events are counted. Events mapped with `match_quality != 'A'` are reported
   separately (they are still applied).
4. Sharadar guards: the ticker's OHLC series has a row dated exdt and its previous row is dated CRSP's previous
   trading day. Otherwise skip and count.
5. Correction factor: `m = (1 + r_S,d) / (1 + r_C,d)` where `r_S,d = close_d / close_{d-1} - 1` (Sharadar) and
   `r_C,d` = CRSP `ret` on exdt (the work order's target; CRSP books the spin value in the price factor, so `ret`
   and `retx` coincide on spin dates; `ret - retx` is reported across all events and any nonzero value flagged as
   a cash leg).
6. Apply only when `|ln m| >= 0.02` (2%; well above the 3-decimal rounding band WO-51 measured). Events below the
   threshold are "Sharadar already consistent" and left alone; the count within 0.02..0.04 is reported.
7. Off-by-one dates: the primary rule uses exdt only. Reported (not applied): the number of events where the
   largest |Sharadar - CRSP| one-day log gap in exdt±3 trading days falls on a day other than exdt.
8. Era edge: events with exdt after 2019-12-31 are **excluded** (no 2020 return is read; in-era rule). Labels of late
   2019 pick-dates whose window would cross a 2020Q1 spin stay unfixed; the count of such distribution records
   (dsedist metadata only, no returns) is reported.

## Correction formula (frozen)

The label is `gross_return_40 = close[j_x] / open[j_e] - 1`, with `j_e = i+1`, `j_x = min(i+40, n-1)` on the
ticker's own row positions (`build_outcome_cache.vectorized_outcomes`). The fix is equivalent to multiplying every
Sharadar open/close dated before the event by `1/m`. For event row position `k` (the exdt row), row `i` is affected iff
`j_e < k <= j_x` (strict on the left: entry at the exdt open is already post-event; truncated rows follow the same
rule). Fixed label: `label' = (1 + label) / m - 1`; several events in one window multiply. No other date or row is
touched. Factor columns (momentum_12_1, seas, pct_from_high_252, volatility_60) carry the same false drop for up to
12 months; **WO-54 fixes labels only** and leaves features as they are (noted for the panel-builder proposal).
Hand check: for at least 5 affected rows, recompute `close[j_x]/open[j_e]` from the CSV with pre-exdt prices
multiplied by `1/m`, and require agreement with the vectorised fixed label to 1e-5 (float32 cache).

## Phase 1 report (descriptive)

Event count (by distcd, by year, skipped by reason), the named cases, share of affected name-dates among
`eligible_cap150` and `eligible_cap2000` rows of v2 column c 2007-2019, agreement between `1/m` and the
CRSP `facpr` (for events with a single distribution row), and the off-by-one count.

**Named-case bar.** Cases: SSP 2008-07-01, CY 2008-09-30, MO 2008-03-31, ITT 2011-11-01, plus STRZA 2013-01-14,
PENN 2013-11-04, NI 2015-07-02, MTW 2016-03-04, SPXC 2015-09-28 (all spin-offs in WO-51's worst 20). A case is
corrected iff (a) the event is detected and applied by the rule (no hand-adding), (b) after the fix the Sharadar
ex-date return equals CRSP `ret` within 1bp, and (c) the fixed 40-day label for the window t = 20 trading days
before exdt is within 2pp of the CRSP-rebuilt label (WO-51 `hand_label` rule, retx basis). A case the rule
misses is a detection bug and uses one of the 3 fix cycles. Not spin-offs, out of scope: CHZS, GLBR, DNDNQ, PAR1,
ABWTQ, ZZ (cash distribution, bid/ask midpoints, unexplained level, factor reset, rights offering).

## Phase 2 book read (metric)

- Model: icw5_seas (`ICW.PRODUCTION_WEIGHTS_V5_SEAS`), v2 column c, cap150, decile_volq, net 15bp, h=40, all 40
  offsets, 2007-01-02..2019-12-31, excess vs SPY, mean over offsets, %/yr.
- Harness: "same harness as WO-51 Phase 3" is read as the same book arithmetic (pick, NaN-drop/renormalise,
  `turnover_net_return`, 40 offsets). WO-51's own loader has no `seas`, so the run uses the WO-48b/WO-53 path
  (`signcheck/dropcheck.load("A")`, `score`, `picks_fast`, `chains`), which must reconcile the unfixed baseline to
  `REF_V5 = 0.036442521084825354` within 1e-10 (re-derived in the same run). Fixed run: identical code with the
  label array replaced by the fixed labels. Assert the pick sets are identical on every date (the fix keeps every
  finite label finite), so Δ decomposes exactly per pick-row: `contrib = w * (r_fix - r) * k_net * ANN / (40 * n_off)`;
  assert the contributions sum to Δ within 1e-9, and that the weight-returning picker reproduces REF_V5.
- Reported: Δ = fixed − unfixed (%/yr, mean of 40 offsets), offsets with Δ > 0, sd40 of both books, LOYO of Δ,
  and the top 20 contributing name-dates.

## Verdict rule

- **FIX** (recommend adopting the correction in the panel builder) if the named-case bar holds for every named
  case, whatever the sign of Δ. Magnitude is information, not a gate.
- Report whether |Δ| > 0.25pp/yr (worth a re-derivation of weights) or not.
- **No result within budget** if the named-case bar still fails after 3 fix-and-rerun cycles.
- Kill: none (correctness work). Iteration cap: 3 fix-and-rerun cycles.

## Hard limits

Worktree outputs only (`final/src/spinfix/`, `final/out/spinfix/` aggregates; per-row CRSP values as parquet under
`final/data/wrds/crsp/derived/`, never committed). No write to the main checkout's `final/out/`, the working panel,
`current_signal_*`, ledgers or `outcome_cache_v2`. Panel-builder change is a proposal in the handoff. CRSP runs about
a year behind, so a live version needs a forward spin-off source (open item, not built here). Nothing reads 2020+
returns. No trading code.
