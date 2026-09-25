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

### Integrity checks (run 2026-09-24, before any return statistic)

Scripts: `final/src/insider/build_insider_panel_v2grid.py` (feature build +
checks, writes `out/insider/insider_features_v2grid.parquet` and
`insider_v2grid_integrity.json`) and `final/src/insider/check_mapping_v2grid.py`
(mapping follow-up, writes `insider_v2grid_mapping_check.json`). Events were
rebuilt from the 81 raw zips with `build_insider_panel.load_events()`:
1,456,667 (filing, owner, code) rows, the same count as the v1 build.

**Row count and CIK uniqueness: PASS.** v2 panel ≤ 2019-12-31: 15,420,963
rows, 7,284 tickers, before and after the CIK merge. `tickers_master` has one
duplicate ticker row; after deterministic dedup every ticker has exactly one
CIK (asserted), and no ticker has two distinct CIKs. CIK-mapped share is
100.0% for old and added tickers alike.

**Reconcile vs `insider_features.parquet`: PASS, exact.** Column b cap150
rows 2007-2019: 6,768,536; all 6,768,536 match a row of the old file;
**0 mismatches** (the old file has 0 duplicate (ticker, date) keys).

**Named filings: PASS.**
- Dimon/JPM: raw 2016q1 zip, accession 0001225208-16-026145, owner CIK
  1195345, issuer CIK 19617, filed 2016-02-11, $26.59M. JPM `ins_buyers_90`
  is 1 on 2016-02-10 and 2 on 2016-02-11 (step +1 on the filing date).
- Added (never-cap2000) names, WO-6 A1 list, first O/D purchases:
  - NGS (CIK 1084991): filed 2007-05-18 → 0 to 1 on 2007-05-18; filed
    2008-12-01 → 0 to 1.
  - WTBA (1166928): filed 2007-02-14 → 0 to 1; 2007-05-10 → 1 to 2.
  - NRIM (1163370): filed 2007-02-22 ($140k) → 0 to 1; 2007-05-24 → 0 to 1.
  - ACHN (1070336): filed 2008-09-02 → 0 to 1; 2008-09-09 → 1 to 2.
  - ANIK (898437): filed 2008-03-12 → 0 to 2 (two owners the same day).
    Its 2008-03-19 filing does not step, correctly: that owner (CIK
    1209114) was already counted from 2008-03-12 (distinct owners).

**Fire rate, old vs added (2007-2019): literal outcome, with the mapping
follow-up the pre-registration requires.**

| cap150 rows (non-SPAC) | rows | fire rate (`ins_buyers_90 > 0`) |
|---|---:|---:|
| old | 6,768,536 | 19.7% |
| added | 2,987,605 | **24.2%** |

| mutually exclusive band | old | added |
|---|---:|---:|
| cap2000 | 16.8% | — (none, by construction) |
| cap500 not cap2000 | 21.8% | 20.2% |
| cap150 not cap500 | 29.5% | 26.5% |

- Aggregated over cap150, added names fire MORE (24.2% vs 19.7%), and in
  both groups the fire rate falls as cap rises, so "small caps show more
  insider buying" holds.
- **Within a band, and at matched market cap, added names fire 2.5-4pp
  LESS** (e.g. $300-500M: 25.2% vs 29.0%; $1-2B: 17.2% vs 20.2%). Taken
  literally, the pre-registered rule reads this as a possible mapping bug,
  so it was tested before proceeding:
  - *Is the CIK live?* Any Form 3/4/5 filed under the mapped CIK within the
    ticker's cap150 date range: added 98.2%, old 97.9%.
  - *Is it the right company?* The most common `ISSUERTRADINGSYMBOL` filed
    under the mapped CIK in that range equals the ticker (trailing digit/Q
    stripped): added 82.3% vs old 85.8% strict, 87.0% vs 89.7% loose
    (prefix). The mismatches inspected are renames where Sharadar keys on
    the latest ticker (ACGN/IDRA Idera, ACR/RSO, ALNT/AMOT Allient,
    ACHV/OGXI), in both groups at similar rates.
  - *Does the gap survive on symbol-verified tickers only?* Yes, unchanged
    (e.g. $300-500M: 25.2% vs 29.4%).
  - Reading: the mapping is not the cause. The residual gap is what the old
    grid's selection predicts: old-grid small-cap rows belong to names that
    were cap2000 at some other date (later winners, fallen angels), and
    insider buying concentrates in both. This is selection on the outcome.
    It is **not** evidence for the signal, and the COO should accept or
    reject this reading.
- 61 CIKs are shared by more than one column-c ticker (share classes,
  renames with overlapping histories); those tickers carry identical
  series. The same was true on the old grid.
- SPACs (excluded from column c) fire at 0-13%.

### Results: pre-registered screen (2026-09-24, run once, exactly as registered)

Command: `python3 final/src/insider/screen_insider_v2grid.py` (20 null
draws, seeds 0..19). Output: `out/insider/insider_v2grid_screen_report.json`,
log `screen_insider_v2grid.log` (copies in this branch). Era
2007-01-03..2019-12-31. Every frame was asserted to end before 2020-01-01.

**Harness reconciliation: PASS, exact.** On column c cap150, before any
insider number was computed:
- icw8 with frozen `PRODUCTION_WEIGHTS`, decile_volq net 15bp, mean of 40
  offsets: +0.0285416326, identical to `readout.json`.
- Split-half OOS IC: +0.0404111 (fit odd, test even) and +0.0553980 (fit
  even, test odd), identical to `readout.json` to 1e-12.
- The vectorized scorer equals `ICW.compute_weighted_score` on 13 sampled
  dates.

**Universes:**
- Primary: column c cap150, 9,756,141 rows, 6,508 tickers, fire rate 21.1%.
- Secondary (added tickers only): 2,987,605 rows, 3,275 tickers, fire rate
  24.2%.
- `ins_buyers_90` is non-null on 100% of rows in both.
- Sector is `Unknown` on 0.03% (primary) and 0.09% (added) of rows.

| gate | bar | primary (column c) | secondary (added only) |
|---|---|---|---|
| 1 pooled IC, NW(39) t | ≥ +2.50 | −0.0017 (t **−0.50**) FAIL | +0.0090 (t **+2.36**) FAIL |
| 2 odd / even halves | both > 0 | −0.0086 (t −2.17) / +0.0064 (t +1.28) FAIL | +0.0043 (t +0.96) / +0.0146 (t +2.47) pass |
| 3 sector-demeaned, both sides | t ≥ +1.0 | −0.0011 (t −0.45) FAIL | +0.0017 (t +0.60) FAIL |
| (3, factor only, not gated) | — | +0.0121 (t +2.97) | +0.0091 (t +2.40) |
| 4 grid-offset sign flips | 0/40 | 6/40 FAIL (offset means −0.0043..+0.0010) | 0/40 pass (+0.0057..+0.0121) |
| 5 max single-year share | ≤ 45% | sum of IC is negative; 2007 = 128% FAIL | 24% (2012) pass; LOYO t 1.87..2.91 |
| 6 icw9 vs 20-draw shuffle, p80 | real > p80 | +2.432% vs p80 +2.387% (p50 +2.360%), 100th pctile, pass | −4.925% vs p80 −4.975% (p50 −5.003%), 100th pctile, pass |
| (6, icw8 split-half OOS) | — | +2.368%/yr; icw9 − icw8 = **+0.063pp** | −4.979%/yr; icw9 − icw8 = **+0.054pp** |
| **verdict** | all six | **KILL** (5 of 6 fail) | **KILL** (gates 1 and 3 fail) |

**Gate-6 details:**
- **Fitted weights.** The weight on `ins_buyers_90` came out +0.083 (fit
  on odd years, where its t is −2.17) and +0.033 (fit on even years, t
  +1.28). The frozen rule uses |t| with the prior sign, so the half where
  buyers were significantly wrong-signed gave them the larger positive
  weight. In the secondary the weights were +0.009 and +0.104.
- **Rows dropped.** The common-universe rule dropped 2,812 primary rows
  and 1,281 added rows whose icw8 score was NaN.
- **What the pass means.** As in the v1 screen, the null's spread is tiny
  (sd 0.022pp/yr primary, 0.061pp/yr added), because permuting one column
  in nine barely moves the book. Beating it shows the column is not pure
  noise inside the composite. It does not show a material gain: the
  +0.05-0.06pp/yr is about a fifth of the book's own offset-to-offset sd.
- **OOS IC with and without the column.** icw9 +0.0490 vs icw8 +0.0485
  (primary); +0.0752 vs +0.0752 (added).

**Reading.**
1. **Primary: KILL.** On the survivorship-safe grid, plain insider buyer
   counts have no cross-sectional IC (t −0.50). The halves disagree in sign
   again, as on the old grid (v1: t −0.16, halves −1.76/+1.61). Adding the
   true small caps did not change the answer.
2. **Secondary: KILL, the nearest miss in this family.** Among the added
   small caps, raw IC is positive and fairly stable:
   - t +2.36, below the 2.50 bar;
   - 0/40 offset flips and no year above 24%;
   - LOYO t stays between 1.87 and 2.91.

   It fails the sector gate, though. Once both the factor and the return
   are demeaned within date × sector, t falls to +0.60. That is the same
   mechanism the v1 results found in reverse: insider buying clusters by
   sector, and sector returns drive the raw IC. The factor-only demeaned t
   (+2.40 here, +2.97 on the primary) is exactly the artefact §3 of the v1
   results warned about. Demeaning only the factor leaves the sector return
   in the label. The registered both-sides version is the one that counts.
3. There is no nomination. Promotion is not in question.
4. **Trial accounting.** The insider family is now k = 4, all spent.
   Re-testing plain buyer counts, on this grid or with window, value or
   cluster variants, would be a fifth trial. The size-conditional reading
   (the secondary) is recorded as a failed, registered secondary. Do not
   re-mine it.

**Out-of-scope observation (not a test, for the COO):** the icw8 book built
*within the added-tickers-only universe* earns **−4.98%/yr vs SPY**, net
15bp, using split-half OOS weights. Its OOS IC is +0.075, the highest of
any universe measured. High rank IC alongside a strongly negative long-only
book in never-large small caps is worth a look. The likely causes are that
the whole slice underperforms SPY, and illiquidity. This work order does
not chase it.
