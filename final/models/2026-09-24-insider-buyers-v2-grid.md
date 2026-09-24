# WO-4: plain insider buyer counts on the survivorship-safe v2 down-cap grid (2026-09-24)

Commissioned by pipe-dream-coo (work order WO-4). Branch
`worktree-agent-a0bac8b9484da825b`, based on `origin/integration` 26f600f.

This reopens a certified dead end under its own stated reopen condition.
The original k=2 registration (`2026-09-23-insider-congress-preregistration.md`)
failed on the old grid (`ins_buyers_90` raw IC t −0.16, halves −1.76/+1.61;
`2026-09-23-insider-congress-results.md`). That grid was survivorship-selected
(tickers that were cap2000-eligible at *some* date; PREREGISTRATION.md
Amendment 1). The recorded reopen condition was "a survivorship-safe
down-cap grid exists (true small caps)". WO-6 built it
(`2026-09-24-downcap-grid-rebuild.md`, BUILD SUCCESS). The Lakonishok-Lee
(2001) and Seyhun results put most of the insider-purchase effect in small
firms, which is exactly what the old grid lacked.

## PRE-REGISTRATION (frozen verbatim from the COO's work order; written before any statistic was computed)

- **Trial count:** insider family k = 4 (buyers v1, sellers v1, the post-hoc
  opportunistic/size-tercile exploration counted as one, and this WO-4).
  Bar |t| ≥ 2.50 (two-sided 0.05, Bonferroni k=4). Sign +1.
- **Column:** `ins_buyers_90` ONLY. No sellers, no value columns, no
  30/180-day or other window variants.
- **Primary:** cap150-eligible, v2 column c, nomination era
  2007-01-02..2019-12-31, label `forward_return_tradable_40`, h=40.
- **Registered secondary:** the added-tickers-only slice (column c minus
  column b tickers), where the Lakonishok-Lee small-cap mechanism should
  live. Same bar; reported separately; a pass there alone is reported as a
  secondary nomination, not a primary pass.
- **Pass (primary; ALL must hold):**
  1. pooled NW(39) Spearman IC t ≥ +2.50;
  2. both halves (odd/even years) positive;
  3. both-sides sector-demeaned IC t ≥ +1.0 (demean BOTH factor and return
     within date x sector; also report the factor-only-demeaned number
     beside it);
  4. 0/40 grid-offset sign flips of the IC;
  5. LOYO: no single year carries > 45% of the effect;
  6. icw9 (`ins_buyers_90` added to the 8 composite factors with the same
     frozen IC-shrinkage weighting rule, split-half OOS as
     `ic_weighted_composite.py` does) vs icw8 on decile_volq net 15bp, 40
     offsets, beats the 80th percentile of a 20-draw within-date shuffle of
     `ins_buyers_90` (seeds 0..19).
- **Kill:** any of (1)-(6) fails.
- A pass is a nomination only; promotion is Gabe's decision.

### Operational definitions (fixed here, before any result; they only make the gates above computable)

- **Column c** = `composite_panel_v2.parquet` restricted to the old 4,011
  tickers plus the added non-SPAC tickers, exactly
  `downcap_v2_readout.load_column("c")`. **Column b** = v2 restricted to the
  old 4,011 tickers. **Added slice** = column-c tickers not in the old grid.
  Eligibility = the v2 `eligible_cap150` flag. Outcomes from
  `outcome_cache_v2.parquet`. Every frame is filtered to ≤ 2019-12-31 and
  the code asserts `max(date) < 2020-01-01`.
- **Feature:** `ins_buyers_90` is built exactly as `build_insider_panel.py`
  builds it (imported, not copied): Form 4 originals, non-derivative code P,
  officer/director owners, FILING_DATE availability, distinct owners with a
  filing in the trailing 90 calendar days (interval union), ISSUERCIK ->
  `tickers_master.secfilings` CIK. CIK-mapped rows with no filing = 0;
  unmapped rows = NaN. Events are rebuilt from the raw zips with
  `build_insider_panel.load_events()` (the shared events parquet is not read).
- **IC:** per-date Spearman correlation of `ins_buyers_90` with the label
  over cap150 rows with both finite (dates with < 20 such rows dropped), as
  `screen_insider.daily_corr`. Pooled mean and Newey-West t with lag 39
  (`screen_insider.newey_west_mean_t`). Halves = odd vs even calendar years.
- **Gate 3:** `x_sn = x − mean(x | date, sector)` and
  `y_sn = y − mean(y | date, sector)` (NaN sector -> "Unknown"), then the same
  Spearman IC of `x_sn` vs `y_sn`. The factor-only variant (`x_sn` vs `y`) is
  reported beside it, not gated.
- **Gate 4:** the 40 grid offsets are `dates[o::40]` for o = 0..39 over the
  sorted daily IC series; offset mean IC computed on each. A sign flip is an
  offset whose mean has the opposite sign to the pooled mean (or is exactly 0).
  Pass = 0 flips.
- **Gate 5:** year share = Σ(daily IC in year y) / Σ(all daily IC). Pass =
  max share ≤ 0.45 (and the total is positive; if not, gate 1 has failed
  anyway). The leave-one-year-out pooled t is also reported.
- **Gate 6:**
  - Scores: coverage-aware weighted mean of signed per-date rank_z, i.e.
    `ic_weighted_composite.compute_weighted_score` (vectorized, asserted equal
    on sampled dates). Weights from `ic_weighted_composite.fit_weights`'s
    rule `w_k = sign_k·max(0.1, |t_k|−1)/Σ`, with `t_k` the pooled NW(39)
    Spearman-IC t of each factor on the FIT half; sign of `ins_buyers_90`
    is +1.
  - Split-half OOS: weights fit on odd years score even-year dates, weights fit
    on even years score odd-year dates; the two scored halves are stitched
    into one daily score series. This is done identically for icw8 (8
    factors) and icw9 (8 + `ins_buyers_90`).
  - Book: `composite.pick_decile_volq` construction (top 10% of each of 5
    trailing-vol quintiles, inverse-vol weights; NaN vol or score excluded).
    Returns `gross_return_40` from `outcome_cache_v2`. Cost 15bp via
    `run_backtest.turnover_net_return`, `f_new` computed per offset from the
    previous window's pick set, exactly as `downcap_v2_readout.backtest`.
    Metric = excess vs SPY, annualised ×252/40, mean over the 40 offsets.
  - Null: for seed s in 0..19, `ins_buyers_90` is permuted within each date
    (`numpy.random.default_rng(s)`), and the ENTIRE icw9 procedure (split-half
    weight refit included) is rerun on the permuted column. Pass = real icw9
    metric > the 80th percentile of the 20 null icw9 metrics (numpy default
    linear interpolation). icw8 and the icw9 − icw8 difference are reported.
  - **Common universe:** both icw8 and icw9 score only rows whose icw8
    score is finite (a row whose 8 factors are all NaN would otherwise get an
    icw9 score from `ins_buyers_90` alone and jump to the top of the book).
    The number of rows this drops is reported.
  - **Weights for 9 factors:** `screen_insider.fit_weights(t, signs9)` (same
    rule; `ICW.fit_weights` only knows the 8 composite signs). Asserted equal
    to `ICW.fit_weights` in the 8-factor case. The rule uses |t| with the
    prior sign, so a fit half where `ins_buyers_90` is strongly negative gets
    a larger +1 weight; the rule is frozen and not changed, and the per-half
    t and fitted weight of `ins_buyers_90` are reported.
  - **Shuffle, exactly:** the frame is sorted by (date, ticker); for seed s,
    `rng = numpy.random.default_rng(s)`; within each date, in date order, only
    the finite `ins_buyers_90` values of the evaluated universe (cap150 rows
    for the primary, the added cap150 slice for the secondary) are permuted
    among themselves (coverage mask preserved). The 8 factors' fit-half t
    are unchanged under the shuffle and are cached; only `ins_buyers_90`'s t
    and the weights are refit per draw.
  - **Harness reconciliation (hard assert before any insider number):** on
    column c cap150, icw8 with frozen `PRODUCTION_WEIGHTS` must reproduce
    `readout.json`'s decile_volq excess net 15bp mean of 40 offsets, and the
    split-half OOS IC (both fit directions) must reproduce `readout.json`,
    each to 1e-6. `composite.pick_decile_volq` and
    `downcap_v2_readout.backtest` are called directly (not reimplemented);
    only the scoring is vectorized, and it is asserted equal to
    `ICW.compute_weighted_score` on sampled dates.
- **Secondary (added slice):** the identical six gates with the universe on
  each date restricted to added tickers that are cap150-eligible: IC, halves,
  sector, offsets and LOYO on that slice; for gate 6 the icw8/icw9 books are
  built within the slice (weights fit on the slice, decile_volq within the
  slice's own vol quintiles), with its own 20-draw null.

### Integrity checks (must pass before any statistic is reported)

- Panel row count unchanged after the CIK merge; exactly one CIK per ticker
  (tickers_master deduplicated deterministically: first non-null CIK after
  sorting by ticker, CIK; asserted unique).
- `insider_features.parquet` checked for duplicate (ticker, date) keys
  (the old `cik_map()` did not deduplicate), reported before the reconcile.
- CIK-mapped coverage and fire rate (share of rows with `ins_buyers_90 > 0`)
  for old vs added tickers, by mutually exclusive cap band (cap2000;
  cap500 not cap2000; cap150 not cap500), 2007-2019. Small caps should show MORE insider
  buying; a LOWER fire rate on added names is treated as a mapping bug to fix
  before proceeding.
- Named filings, by hand from the raw zips: the Dimon JPM buy filed
  2016-02-11 (signal steps up on the 2016-02-11 panel date), plus at least
  two more known filings, including at least 2 insider buys at added
  (never-cap2000) tickers drawn from WO-6's A1 names (ANIK, NGS, WTBA,
  NRIM, ACHN), with the step-up date confirmed.
- Share of `Unknown` (NaN) sector rows, old vs added, reported beside gate 3.
- Reconcile: on column b cap150 rows restricted to the old grid's
  (ticker, date) rows, my `ins_buyers_90` must match
  `insider_features.parquet` (mismatch rate reported; expect ~0).

## Results

(appended after the run, below this line; nothing above is edited)
