# WO-36: call-put IV spread under other weights, or as an exclusion screen

Date: 2026-10-01. Commissioned by the COO; Gabe asked for the weight variants.
Code: `final/src/cwweights/` (`cw_core.py`, `run_cw.py`). Outputs:
`final/out/cwweights/*.json`.

**Status of this section: pre-registration.** Everything down to the
"Results" heading was written and committed before any real-label number for
variants V1 to V6 existed. The only real-label numbers computed before the
commit are the two already published by Experiment B (the 8-factor base and
V0), which the order allows.

## 1. Question

Does `opt_cw_spread` (Cremers-Weinbaum call minus put implied volatility,
sign +1) help the long book when it is given a smaller weight than the
project rule gives it, or when it is used only to remove names from the
candidate pool?

## 2. Prior knowledge (all of it in-sample for this question)

From Experiment B (`final/models/2026-10-01-options-phase2.md`, pre-registered
in `final/models/2026-09-29-options-readiness-wo25.md` section 3): cap2000
names with option chains, 133 monthly dates 2008-01 to 2018-12, label 40-day
forward tradable return.

- Sector-neutral rank IC +0.016, Newey-West lag-39 t +3.54. Raw t +6.09
  (lag-2 t 2.94).
- As a ninth factor under the rule `w = sign * max(0.1, |t| - 1)` on raw t,
  normalised, it got weight 0.353, the largest of nine. The book fell from
  5.36 to 3.65 %/yr over SPY (net 15bp, decile within volatility quintile,
  mean of 2 offsets). Shuffled-factor null 80th percentile 5.28. Not admitted.
- A descriptive decile split by the COO on the same data: 40-day return
  against the date mean, lowest to highest cw_spread decile, was −1.03, −0.22,
  −0.14, +0.12, +0.03, +0.18, +0.15, +0.29, +0.25, +0.33 percent. The effect is
  in the bottom decile.
- The variants below were designed after seeing all of this. 2008-2018 is
  in-sample. The 2019-01 to 2026-08 window has not been read for any option
  factor.
- Trial tally before this order: 18 options trials. This order adds 6
  (V1 to V6): **24**.

## 3. Data and fixed machinery

- Features: a copy of WO-35's `av_options_features_wo25.parquet` in
  `final/out/cwweights/` (gitignored), 225 monthly dates 2008-01-02 to
  2026-08-19.
- Loader, label, book, costs and benchmark are imported from
  `final/src/options_wo25/run_expB.py` unchanged: `load()`, cap2000, the book
  universe is name-dates with a non-missing cw_spread, `pick_decile_volq`,
  net 15bp on turnover, excess over SPY × 252/40, mean of 2 interleaved
  offsets.
- **Base weights are frozen at Experiment B's published values**
  (`final/out/options_wo25/expB_screen.json`, fit on 2008-2018). They are
  never refit, in either stage.

**Data difference found during reproduction (before any new number).** The
features file gained 10 name-dates on 2018-10-17 after Experiment B ran. The
pull repaired 10 `error` rows and that date's features were rebuilt at 23:23,
after the screen at 23:00 (`arrival_report.json` in the WO-35 worktree now
shows that date complete; the landed copy shows it at 0.989). The file has
296,655 rows against 296,645, and the window has 147,606 name-dates against
147,596. All ten are in 2018; the 2019+ rows are unchanged.

| | Experiment B | here, published weights | offsets here |
|---|---|---|---|
| 8-factor base | 5.363 | 5.365 | 5.171 / 5.559 |
| V0 (cw at 0.353) | 3.650 | 3.631 | 3.721 / 3.541 |

Offset 2 matches Experiment B to every digit on both rows. Offset 1 contains
2018-10-17 and differs by 0.005 (base) and 0.039 (V0). Refitting the base
weights on the topped-up file moves them in the fourth decimal and the base to
5.27; that refit is recorded in `frozen_weights.json` and not used. I treat
the two published numbers as reproduced and continue on the current file with
the published weights.

## 4. The variant family (fixed; nothing is added)

Write `x` for cw_spread's share of total absolute weight. The eight base
weights are multiplied by `1 − x`.

| id | definition | x |
|---|---|---|
| V0 | rule weight on raw t (reference, already failed) | 0.3534 |
| V1 | fixed small weight | 0.05 |
| V2 | fixed small weight | 0.10 |
| V3 | fixed small weight | 0.20 |
| V4 | rule applied to the sector-neutral t (3.5408) for cw only, all nine normalised | 0.2144 |
| V5 | exclusion: 8-factor book, bottom 10% of cw_spread removed from the pool | none |
| V6 | exclusion: same, bottom 20% | none |

Decisions the order left open, fixed here:
- V4 comes to 0.2144, almost the same as V3. It stays in the family as
  ordered.
- V5 and V6: the 8-factor score is computed on the full pool, then names with
  cw_spread percentile rank (average ties, rank / count) at or below 0.10
  (0.20) on that date are dropped, then `pick_decile_volq` runs on what is
  left. Volatility quintile cutoffs and the 10% count are therefore taken on
  the smaller pool, so the book is about 10% (20%) smaller.
- Null draws: cw_spread is permuted within date, one permutation per date per
  draw, shared by all six variants. All weights stay frozen in the null,
  including V4's 0.2144 (it is not refit on the shuffled factor). V0 is not in
  the maximum.
- Random-thinning null for V5 and V6: a shuffled cw_spread's bottom decile is
  a uniformly random 10% of names, so the thinning null is the V5 (V6) column
  of the same shuffled draws. It is reported per variant.
- Halves are odd and even calendar years. Leave-one-year-out and halves drop
  dates from each offset's per-date net-excess records; turnover costs stay as
  computed on the full sequence. The reported figure is the mean over the two
  offsets.
- Turnover is the mean fraction of the book that is new at each rebalance
  (`f_new`).
- 100 null draws, seed 20261001 (Stage 2: 20271001). 80th percentile.

## 5. Stage 1: nominate on 2008-01 to 2018-12 (in-sample, descriptive)

For each of V1 to V6: %/yr over SPY, difference from the base, both offsets,
both halves, leave-one-year-out minimum of the difference, turnover.

A variant is **nominated** only if all three hold:
1. its difference from base exceeds the 80th percentile of the
   maximum-over-six shuffled-cw null;
2. the difference is positive on both offsets;
3. the leave-one-year-out minimum of the difference is above zero.

**Selection rule.** No variant nominated: verdict KILL at Stage 1, Stage 2
does not run. One or more nominated: exactly one goes to Stage 2, the
nominated variant with the largest leave-one-year-out minimum. No second
choice.

## 6. Stage 2: one confirmation read on 2019-01 to 2026-08

**Hold-out read #16.** Unfitted: base weights, the chosen variant and its
weight are frozen from Stage 1. Run once; `run_cw.py --mode stage2` refuses if
`stage2_confirm.json` exists, if Stage 1 nominated nothing, or if this doc is
not committed. `load()` keeps its 99% pool-integrity guard; if it raises, the
run stops and is reported, not loosened.

**Success (all must hold)** for the chosen variant's difference from base:
1. above zero on both offsets;
2. above zero in both halves (odd and even years);
3. leave-one-year-out minimum above zero, with the 2020-dropped figure
   reported on its own line;
4. above the 80th percentile of its own shuffled-cw null on this window.

**Kill:** anything else. A fail closes the weighted-factor and exclusion
routes for cw_spread. The only reopening condition is a short book with real
borrow-cost data. The base's own level on this window is reported too.

## 7. Discipline

- Iteration cap 3. Any design change after a real number exists is written
  here and committed first, and counts.
- Stage 1 on real labels is refused by the script until this doc is in git.
- All headline numbers are checked against the imported
  `ET.score_frame` + `run_expB.portfolio` path to 1e-9.

## 8. Code proof on shuffled labels (run before this commit, no real statistic)

`final/out/cwweights/proof_SHUFFLED_TEST_labels-shuffled.json`. Outcomes
permuted within date, demeaned, SPY set to 0; weights frozen; the full Stage 1
nomination rule applied with the 100-draw max-over-six null. **6 of 50 runs
nominated anything (rate 0.12)**, under the one-in-five ceiling. Stage 2 was
also run end to end on shuffled labels for V5 and V3
(`stage2_SHUFFLED_TEST_labels-shuffled.json`); pool integrity on 2019-2026 is
100.00%, and both runs returned KILL.

## Results

Pre-registration committed as `c19b698` before Stage 1 ran. No iterations
used (0 of 3). Trial tally now 24.

**Verdict: KILL at Stage 1.** No variant was nominated, so Stage 2 did not
run and **hold-out read #16 was not used**. For plumbing, the 2019-2026
outcomes were loaded twice (V5, then V3) with labels permuted within date,
demeaned, and SPY set to 0. No real-label statistic was computed on that
window. Whether that loading matters is for the COO to judge. The V3 run
overwrote the V5 run, so `stage2_SHUFFLED_TEST_labels-shuffled.json` holds
V3 only.

The deciding number: **leave-one-year-out minimum −0.06 %/yr** (2010
dropped) for V6 (drop the bottom 20%), the best variant and the only one
above the null (+0.13 against +0.03 %/yr). V6 is also −0.05 on offset 1.
Every other variant is below the base.

These two failing margins are about the size of the 2018-10-17 top-up's
effect on V0's offset 1 (0.04). The verdict follows the pre-registered rule
on the pre-registered file; nothing was rerun.

Stage 1, 2008-01 to 2018-12, 133 dates, %/yr over SPY
(`final/out/cwweights/stage1_nominate.json`). Base 5.37 (offsets 5.17 / 5.56,
odd years 4.41, even years 6.15, turnover 0.263).

| variant | %/yr over SPY | diff from base | diff offset 1 / 2 | diff odd / even years | LOYO min of diff (year dropped) | turnover | nominated |
|---|---|---|---|---|---|---|---|
| V0, x 0.353 (reference) | 3.63 | −1.73 | −1.45 / −2.02 | | | 0.539 | n/a |
| V1, x 0.05 | 5.25 | −0.11 | +0.29 / −0.51 | −0.23 / −0.01 | −0.29 (2018) | 0.274 | no |
| V2, x 0.10 | 4.85 | −0.52 | −0.12 / −0.91 | −0.36 / −0.65 | −0.70 (2017) | 0.305 | no |
| V3, x 0.20 | 3.87 | −1.49 | −1.25 / −1.73 | −1.11 / −1.81 | −1.77 (2018) | 0.399 | no |
| V4, x 0.214 | 3.98 | −1.38 | −1.39 / −1.37 | −0.82 / −1.85 | −1.63 (2017) | 0.414 | no |
| V5, drop bottom 10% | 5.09 | −0.28 | −0.10 / −0.46 | −0.63 / +0.02 | −0.50 (2018) | 0.294 | no |
| V6, drop bottom 20% | 5.49 | +0.13 | −0.05 / +0.30 | −0.40 / +0.55 | −0.06 (2010) | 0.341 | no |

Nulls (100 shuffles of cw_spread within date):
- Max-over-six null: 80th percentile **+0.03 %/yr**, median −0.17.
- Random thinning (the V5 and V6 columns of the same draws): V5 80th
  percentile −0.06, median −0.25, real −0.28 (below the median of random
  thinning). V6 80th percentile −0.09, median −0.41, real +0.13 (above).
- Per-variant null medians for the weighted variants: V1 −0.39, V2 −0.81,
  V3 −1.72, V4 −1.85. The real weighted variants lose less than a noise
  factor at the same weight (V3 −1.49 against −1.72) but still lose.

What the table shows:
- The loss grows steadily with the weight (−0.11, −0.52, −1.49, −1.73 at
  0.05, 0.10, 0.20, 0.353). No weight tried improves the book, so the
  Experiment B failure was not caused by the rule over-weighting the factor.
- Turnover rises with the weight (0.26 to 0.54 new names per rebalance).
  That part of the loss is cost is inferred, not verified: no gross-of-cost
  difference was computed.
- Removing the bottom decile does not help the long book (−0.28, at the
  median of random thinning, −0.25), although that decile carries the
  factor's return spread. The base book already under-holds those names:
  5.7% of its picks (4.9% by weight) sit in the bottom cw_spread decile
  against 10% by chance, and 13.4% in the bottom quintile against 20%
  (label-free count on the Stage 1 picks, made after the result).
- V6's +0.13 is small, sits on one offset and on even years, and turns
  negative when 2010 is dropped.

Closed by this result: cw_spread as a weighted factor and as an exclusion
screen for the long book. Only reopening condition: a short book with real
borrow-cost data.

Checks run:
- Base and V0 reproduce Experiment B (section 3), offset 2 to every digit.
- Fast path equals `ET.score_frame` + `run_expB.portfolio` to 1e-9 on base,
  V0 and all six variants, on real labels inside the Stage 1 run and on
  shuffled labels before it.
- Shuffled-label nomination rate 0.12 (6 of 50); 0.20 when only the
  above-null condition is applied, as designed.
- `run_cw.py --mode stage2` refuses: "Stage 1 nominated nothing".

Not verified: that the 10 added name-dates are the same 10 tickers as the
repaired `error` rows. The counts, the date and the rebuild time agree; the
ticker lists were not compared because the pre-top-up file no longer exists.
