# WO-42: the stabilizer admission rule, applied to EAR (and reported for str_lowturn)

Date: 2026-10-01. Worker branch `worktree-agent-afcd45cd69ed78d09` (COO WO-42).
Hold-out read #19 (S3, unfitted, under Gabe's standing 2026-09-27 OK for
unfitted 2020+ reads).

## 1. Pre-registration (committed BEFORE any S1 null draw beyond the 20 already published, and before any 2020+ EAR number)

### Why this exists
Gabe approved a methodology change on 2026-10-01 ("Yes I agree"). A signal
that predicts returns (passes the IC gates) but adds about nothing to the
book's mean fails gate 4 of the nomination screen ("the book increment has
0/40 offset sign flips"). His reasoning: "if signals improve IC but don't
change returns they should be added… our confidence intervals will be
narrowed." Such a signal may be admitted as a STABILIZER if it narrows the
dispersion of results.

### Stabilizer admission rule, Gabe 2026-10-01
A candidate that passed gates 1,2,3,5,6,7 of its screen and failed only gate 4 is admitted as a STABILIZER iff ALL of:
- S1 dispersion: the reduction in sd across the 40 offsets of the book's net excess vs SPY (candidate+base minus base, same split-half OOS weight method as the screen) is larger than the 80th percentile of the same reduction over a 100-draw within-date shuffle null of the candidate column (shuffled column given the weight the real candidate gets = weight-matched null). In-era 2007-2019.
- S2 no harm: mean increment ≥ 0; worst-offset book not lower than base; LOYO min of the book not lower than base (both in-era).
- S3 out-of-era sign: unfitted read on 2020-01..last matured label: candidate standalone pooled NW(39) rank-IC has the pre-registered sign with t ≥ +1.0 (same threshold WO-26-io used), with all weights frozen from 2007-2019. Also report (descriptive) the 2020+ book with vs without at frozen weights: mean, sd40, worst offset, offsets > 0 of the increment, turnover/cost.

A pass earns a FORWARD COLUMN proposal only (like icw10_io); live weights are Gabe's later decision.

### What is and is not out-of-sample (stated plainly)
The rule was written AFTER seeing EAR's in-era dispersion numbers (sd across
40 offsets 0.47 → 0.42pp, worst offset 1.42 → 1.55, LOYO min 1.47 → 1.56)
and str_lowturn's. So S1 and S2 in-era are partly in-sample for the rule
itself: the rule's shape was chosen knowing EAR would look good on them. The
only parts not seen when the rule was written are (a) where the real sd
reduction sits in a 100-draw weight-matched null (the screen only ran 20
draws and never looked at their sd), and (b) S3, the 2020+ read. S3 is the
only out-of-sample element.

### Trial count
This is a rule change by Gabe, applied once to EAR. EAR is the same signal as
WO-29 (SUE/PEAD family, trial 2). No new signal variant, window, holding
period or sign is tested, so the family trial count does not move. One
application of the rule. str_lowturn (reversal family trial 2, WO-28b) is
reported, not a second application: it already fails S2.

### Scope (frozen)
- Universe: composite_panel_v2, column c, `eligible_cap150`. Construction
  decile_volq, net 15bp, 40 grid offsets, h = 40, label
  `forward_return_tradable_40` = close[t+40]/open[t+1] - 1, excess vs SPY
  annualised x252/40.
- In-era (S1, S2): 2007-01-02..2019-12-31. Base = icw9_seas with split-half
  OOS weights (fit on odd years, score even years and vice versa), exactly
  the base of the WO-29 and WO-28b gate 6. Candidate book = base + candidate
  with the candidate's split-half fitted weights from its screen. This is
  the method the reconcile targets (2.55 / 0.47) come from. The S1/S2 script
  carries a hard `assert date < 2020-01-01` on every frame.
- Out-of-era (S3, EAR only): 2020-01-02..2026-07-30. Base = icw9_seas at the
  frozen LIVE weights (`PRODUCTION_WEIGHTS_V9_SEAS`). The panel's last
  matured label is 2026-08-03, but the frozen `seas` extension
  (`seas_factor_ext.parquet`, WO-23) ends 2026-07-30, and that is the window
  WO-23, WO-26-io, WO-31 and WO-40 all used. One window is used for both the
  S3 IC and the descriptive books, so the last two label dates (07-31,
  08-03) are not read.
- Harnesses `final/src/ear/` and `final/src/volshock/` are imported
  read-only; nothing in them is edited. New code is in `final/src/stabilizer/`.

### Reconcile (hard asserts, before any new number)
The in-era books are recomputed and must match the two committed reports
(`final/out/ear/ear_screen_report.json`,
`final/out/volshock/str_lowturn_screen_report.json`) within 1e-4 absolute
(fractions, not percent) on each of:

| book | mean40 | sd40 | min40 | LOYO min |
|---|---|---|---|---|
| base icw9_seas (split-half) | 0.0254965 | 0.0047198 | 0.0142012 | 0.0147386 |
| + EAR | 0.0256405 | 0.0042252 | 0.0154541 | 0.0156191 |
| + str_lowturn | 0.0256408 | 0.0043094 | 0.0154355 | 0.0136749 |

These are the headline 2.55 %/yr sd40 0.47pp; +EAR 2.56 / 0.42; +str_lowturn
2.56 / 0.43. sd40 is the POPULATION sd (ddof = 0) of the 40 per-offset
annualised net excess values, the `sd40` field of `downcap_v2_readout.backtest`.
The run is deterministic, so the script also asserts the 40 per-offset
increments equal the reports' `increment_per_offset` to 1e-9, and that null
draws 0..19 of the weight-matched null reproduce each report's
`weight_matched_null_DESCRIPTIVE.draws` (book mean) to 1e-9. Only after
those asserts does it look at any null sd.

### S1 (exact statistic)
- reduction_real = sd40(base) - sd40(base + candidate), ddof 0.
- Null: seeds 0..99, `numpy.default_rng(seed)`. Each draw shuffles the
  candidate column within date using the candidate's own screen shuffle,
  then scores base + shuffled candidate with the REAL candidate's split-half
  fitted weight dicts held fixed (no refit):
  - EAR: `screen_ear.shuffle_live` (the live signed ranks are permuted among
    live rows of the date; neutral rows stay 0). Weights: the report's
    `weights10_fit_odd` / `weights10_fit_even` (EAR weight 0.1353 / 0.0403).
  - str_lowturn: `screen_insider_v2grid.shuffle_within_date` on the
    str_lowturn column (all finite values of the date are permuted,
    including the exact-zero non-eligible rows), as WO-28b's weight-matched
    null did. Weights: the report's `weights10_fit_odd` / `_even`
    (-0.0162 / -0.1033).
- reduction_null_k = sd40(base) - sd40(base + shuffled_k).
- S1 passes iff reduction_real > numpy.percentile(reduction_null, 80)
  (strict). Also reported: the percentile of the real reduction in the null,
  null p50, and the same comparison for min40 and the book mean (descriptive).

### S2 (exact)
From the reconciled in-era books: (a) mean40(book) - mean40(base) >= 0;
(b) min40(book) >= min40(base); (c) LOYO min(book) >= LOYO min(base), where
LOYO min is `downcap_v2_readout.backtest`'s `loyo_min`. All three must hold.
Known before this pre-registration from the reports: EAR passes all three;
str_lowturn fails (c) (1.37 < 1.47).

### S3 (EAR only; hold-out read #19, unfitted)
- EAR for 2020+ is built by `final/src/stabilizer/build_ear_ext.py`, a copy
  of `build_ear.py`'s factor logic with only the date bounds changed (SEP
  2005-01..2026-07, panel rows to 2026-07-30, 8-K pool `filing_date` to
  2026-07-30). The frozen definition is unchanged: original 8-K Item 2.02,
  day 0 = first market day on or after filing, EAR = sum of d = -1..+2 of
  stock minus SPY daily return, available at the close of day +2, live for
  60 trading days, signed rank among live column-c cap150 rows of the date,
  every other row neutral 0.
- Identity (hard assert, before any 2020+ label is joined): on every row
  dated <= 2019-12-31 the extended build must equal WO-29's frozen
  `ear_factor_v2.parquet` (same NaN pattern, `ear_raw` to 1e-12, `ear_age`,
  event dates, `cov100`).
- Pool for 2020+: the two existing pulls cover filings through 2026-09 for
  the CIKs they requested, but those request lists were built from tickers
  with 2007-2019 rows. A check that used no outcome found 1,371 of the 5,737
  cap150 tickers with 2020+ rows have a CIK with no filing in the pool
  (about 6% of 2020+ cap150 rows), mostly post-2019 listings. Those CIKs are
  topped up from EDGAR with a copy of the WO-29 pull logic, written to a NEW
  file `final/out/stabilizer/8k_item202_2020topup.parquet` (gitignored;
  nothing existing is overwritten). The same Step 0 coverage statistic as
  WO-29 (share of name-dates with an original 2.02 filing in the prior 100
  trading days) is reported by year for 2020-2026. If EDGAR is blocked, S3
  is reported BLOCKED and S1/S2 are still delivered.
- Gate: standalone pooled NW(39) Spearman rank-IC of `ear` (all cap150
  column-c rows, neutral 0 included, exactly the gate-1 statistic of WO-29)
  vs the label on 2020-01-02..2026-07-30. Pass iff mean IC > 0 and t >= +1.0.
  The same code on 2007-2019 must first reproduce the screen's in-era
  t = +3.2572 to 1e-6 (hard assert).
- Descriptive 2020+ books at frozen weights, with vs without:
  - without = icw9_seas at `PRODUCTION_WEIGHTS_V9_SEAS`. Must reproduce the
    WO-31 / WO-40 period-B value -0.020163649457176646 to 1e-6 (hard assert;
    this is the reference computed on the current panel
    sha 80e28e4d…; WO-23's -0.0201637 is the same to 6e-9).
  - with = icw10_ear, the frozen rule w = sign*max(0.1,|t|-1)/sum on the 8
    full-era t's of `ic_weighted_composite_report.json` + seas t 2.8356 +
    EAR's in-era pooled t 3.2572 (2007-2019 only), rounded to 4dp (the
    WO-26-io pattern). Frozen here, before the read:

    | factor | weight |
    |---|---|
    | momentum_12_1 | 0.0325 |
    | pct_from_high_252 | 0.0085 |
    | volatility_60 | -0.0085 |
    | gross_profitability | 0.3886 |
    | accruals | -0.1062 |
    | net_issuance_pct | -0.0913 |
    | days_to_next_filing_seasonal | -0.0085 |
    | short_interest_days_to_cover | -0.0085 |
    | seas | 0.1558 |
    | ear | 0.1916 |

    `rz_ear` is the signed rank with neutral 0, never re-ranked.
  - Reported for each book: mean40, sd40, min40, offsets > 0, LOYO min, mean
    turnover (share of new names per rebalance) and the cost it implies at
    15bp. Reported for the increment (with minus without, paired by offset):
    mean, sd, offsets > 0, min, max. The same two frozen-weight books on
    2007-2019 are reported as an in-sample reference row.
  - Descriptive, not gated: IC on live rows only; per-year IC; sector
    both-sides t.

### Verdict rule
- EAR: ADMITTED as stabilizer iff S1 and S2 and S3 all pass; otherwise NOT
  ADMITTED, naming the failed part. If S3 is BLOCKED the verdict is PENDING S3.
- str_lowturn: S1 is run and reported. Its verdict is NOT ADMITTED whatever
  S1 says, because it fails S2 (LOYO min). No S3 read for it; no 2020+
  str_lowturn value is computed.
- An ADMITTED verdict is a proposal for a forward tracking column only.

### Process
Iteration cap 2, bug fixes only, each logged in section 3. Outputs in
`final/out/stabilizer/`: `s1s2_ear.json`, `s1s2_str_lowturn.json`,
`build_ear_ext_meta.json`, `s3_ear_holdout.json`, logs.

## 2. Results

(appended after the runs; section 1 is not edited after its commit)

## 3. Iteration log

(none yet)
