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
