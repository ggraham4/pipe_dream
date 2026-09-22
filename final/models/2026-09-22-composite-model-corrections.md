# Correcting the composite audit's findings — results, and one finding that
# refuted the audit's own hypothesis

**2026-09-22, same day as `2026-09-22-composite-model-physics.md`.** That
document raised several issues with the confirmed factor composite and, in
its recommendations section, floated some cheap next tests. Gabe asked for
those to be systematically worked through before proceeding. An advisor
review of the plan **removed one recommendation before it ran** (a |t|<1
weight-pruning rule) as overfitting risk rather than correction — see
section 0. What actually ran: three pre-registered backtest variants and
one factor screen, spec in `PREREGISTRATION.md`'s "Correction-round
pre-registration (2026-09-22, part 2)."

**`composite.py` and `FACTOR_SIGNS` are unchanged.** Every result below is
a variant reported beside the confirmed `cap150_raw`/`decile_volq` baseline
(`REPORT_nominate.md`: **+3.75%/yr** excess vs SPY, sd 0.37% across 40
offsets, 40/40 positive, 10.8/13.0 years beaten, 100th percentile vs its
matched null) — not a replacement. Nomination era only (2007-2019);
2020-2026 stays spent. Reproduction: `python3 correction_variants.py` →
`correction_variants_report.json`.

## 0. A recommendation rejected before it ran

The physics audit's recommendation #4 ("shrinkage toward equal weight —
zero out factors with |t| < 1") was **not implemented.** An advisor review
caught it before any code ran: `volatility_60` and `pct_from_high_252` —
two of the factors that rule would have dropped — are exactly the two
factors `AGENTS.md`'s grid-offset section already records as the most
stable measurements in this project's history (0/40 sign flips), and the
physics audit's own section 8 attributes most of the realized portfolio
edge to a low-vol/quality tilt. Dropping the low-vol term from the model
whose one demonstrated edge is a low-vol tilt, on the strength of a t-stat
the audit's own split-half check had just shown doesn't reliably order
these factors, would have been the audit finding its own instability and
then acting on it anyway. Recorded here so the recommendation isn't
quietly reattempted later without this context.

## 1. `decile1_volq` — the audit's own top follow-up, and it was wrong

**Result: mean excess −0.83%/yr vs SPY (sd 0.47%, 1/40 offsets positive,
0% mean percentile vs its own matched null, 6.1/13.0 years beaten).**

The physics audit (section 6) found that a **pooled, vol-quintile-blind**
decile table showed decile 1's mean forward return (+1.92%) numerically
above decile 9's (+1.78%), and recommended testing a construction that
picks decile 1 instead of decile 9. Tested directly, under the real
construction (5 trailing-volatility quintiles, decile taken **within**
each quintile, inverse-vol weighted) rather than the unconditional table
the audit used to motivate it: **decile 1 is unambiguously worse than
decile 9**, worse than SPY in 39 of 40 offsets, and worse than its own
randomly-permuted null in every single offset. This is not a weak or
marginal result — it is decisive in the opposite direction from what the
audit predicted.

**A candidate explanation for why the pooled table was misleading — not
tested directly, inferred from the correlation matrix, stated at that
strength:** the audit's decile table pooled forward returns across the
WHOLE eligible universe by composite-score rank alone, ignoring which
volatility quintile each name sits in. `decile_volq`'s actual construction
picks a decile **conditional on** volatility quintile — a different
partition of the same names. A name's marginal composite-score decile and
its within-quintile composite-score decile could disagree once volatility
itself correlates with any of the nine input factors (and it does —
`volatility_60` is one of the nine, and the signed-factor correlation
matrix in the physics doc's section 4 shows several factors correlated
with it at 0.03-0.15). This is the most plausible mechanism, not a
verified one — confirming it would mean cross-tabulating marginal decile
against within-quintile decile on a sample of dates, not done here. What
IS established directly, without needing this explanation, is that
conditioning on volatility quintile before ranking is not a cosmetic
detail of the construction: it changes which specific names decile 1 and
decile 9
refer to.

**This corrects, not confirms, the physics audit's section 6
recommendation.** The "avoid the bottom, don't chase the top" reading of
the unconditional decile table does not transfer to the actual
vol-quintile-conditioned construction the way the audit assumed. Anyone
reading `2026-09-22-composite-model-physics.md` section 6 alone would be
pointed at a worse portfolio; this document is the correction.

## 2. `exclude_bottom_decile` — real, consistent, but not apples-to-apples

**Result: mean excess +2.79%/yr vs SPY (sd 0.20%, 40/40 offsets positive,
100% mean percentile vs its own matched null, 8.2/13.0 years beaten).**

Holding everything except the bottom composite-score decile within each
volatility quintile (~90% of the eligible universe, vs. `decile_volq`'s
~10%) **beats its own matched null in all 40 offsets** — meaning the
score's information about what to avoid is real and does real,
consistent work, not just in the top-decile construction but across a
much larger fraction of the universe too.

**Two honest caveats, both material.** First, this holds roughly 9x the
names `decile_volq` does — a fundamentally lower-concentration,
lower-active-risk portfolio, not a like-for-like alternative to the
confirmed construction. Comparing its **absolute** excess return
(+2.79%) against `decile_volq`'s (+3.75%) is not a fair comparison of
"which construction is better" without a proper risk adjustment; this
document doesn't attempt one. Second, no "hold the eligible universe with
NO score-based exclusion at all" control was run here, so it isn't yet
established how much of this +2.79% is the score identifying the bottom
decile specifically versus simply being long a down-cap, survivorship-
corrected universe that has some structural edge over SPY on its own —
the matched null (which reshuffles the SAME score before excluding a
decile) rules out "any random 10% exclusion would do," but not "no
exclusion at all would do almost as well." That control is a clean,
cheap follow-up, not done here.

**What this result is good evidence for**: the **notably lower dispersion
across offsets** (sd 0.20% vs. the confirmed construction's 0.37%) is a
real, structural property of holding a much broader book, consistent with
this project's own repeated finding (Round 15, Round 18) that broader
construction cuts variance drag. It is not, on its own, evidence that
this specific construction should replace `decile_volq` — that would
require the missing no-exclusion control and a risk-matched comparison,
both flagged as follow-ups.

## 3. `asset_growth_dropped` — the one variant that improved on the
## confirmed baseline

**Result: mean excess +4.32%/yr vs SPY (sd 0.55%, range [+2.99%,
+5.30%], 40/40 offsets positive, 100% mean percentile vs its own matched
null, 11.1/13.0 years beaten) — vs. the confirmed baseline's +3.75%/yr
(sd 0.37%, range [+3.03%, +4.45%], 10.8/13.0 years beaten).**

Dropping `asset_growth` (measured wrong-signed in the physics audit,
`IC = +0.0105` against its assigned `-1`, stable across both halves of
the sample) from the composite, same `decile_volq` construction as the
confirmed cell, **improves the mean excess return by +0.57pp/yr and wins
more years (11.1 vs 10.8 of 13)** — consistent with removing a term that
was measurably working against its own economic rationale. This is a
single, pre-registered ablation, not a search over which factor to drop,
which is what makes it interpretable rather than another lucky draw from
Round 12's calibrated 27%-of-zero-signal-configs-beat-the-market
distribution.

**The honest complication: dispersion across offsets went UP, not down**
(sd 0.55% vs. 0.37%, and the range's low end, +2.99%, sits below the
baseline's own low end of +3.03%). Removing a wrong-signed term improved
the average outcome but made the result somewhat less stable
offset-to-offset. This is a real trade-off, not a clean win on every
axis, and it's reported as measured rather than rounded up to "strictly
better."

**This is a recommendation, not a change already made.** `FACTOR_SIGNS`
in `composite.py` is untouched. Whether to adopt `asset_growth_dropped`
as the traded composite is a modeling decision that belongs to Gabe
(`AGENTS.md`'s standing note) — this document puts the number in front of
him rather than deciding it.

**Harness cross-check, run before escalating this number.** The ablation
ran through `correction_variants.py`'s own backtest loop, not
`run_backtest.py` (a code-reuse convenience, not a re-verification), so
before trusting +4.32% vs. +3.75% as a real ablation effect rather than a
cross-harness artifact, the UNMODIFIED confirmed composite (all
`FACTOR_SIGNS`, `pick_decile_volq`) was run through this same harness
(`harness_check.py` → `harness_check_report.json`):

```
mean excess CAGR vs SPY:  +3.751%/yr   (REPORT_nominate.md: +3.75%/yr)
sd across offsets:         0.372%      (REPORT_nominate.md: 0.37%)
range:              [+3.026%, +4.452%] (REPORT_nominate.md: [+3.03%, +4.45%])
offsets positive:          40/40       (REPORT_nominate.md: 40/40)
mean years won:            10.775/13   (REPORT_nominate.md: 10.8/13)
```

Matches to within rounding on every reported statistic. The two harnesses
agree on the identical configuration, so `asset_growth_dropped`'s
+4.32%/yr is the ablation's real effect, not a `run_backtest.py` vs.
`correction_variants.py` discrepancy — the Round 18 lesson (diff a live
script against the cell it claims to reproduce, field by field, before
trusting a divergence) applied here before escalating the number rather
than after.

## 4. Book-to-market screen — a second wrong-signed finding, more decisive

**Not backtested. IC screen only, per the pre-registration.**

Built from `sf1_fundamentals.parquet`'s existing `equity` column (ARQ/ARY,
filed-date keyed — identical join pattern to `quality_factors.py`'s
`assets`, row-position-asserted merge_asof) divided by the panel's own
point-in-time `market_cap` — zero new data pull, 99.9% coverage of the
cap150-eligible nomination-era rows.

```
pooled IC = -0.0240   t = -2.32   n = 3,272 dates
odd-year IC  = -0.0424   t = -3.04
even-year IC = -0.0025   t = -0.18   (same sign, much weaker)
```

**The classic value premium (Fama-French HML, and the Novy-Marx 2013
framing this composite already cites for `gross_profitability`) predicts
sign +1** — high book-to-market ("cheap," value) names should earn higher
forward returns. **The measured sign here is -1.** The pooled t (-2.32)
clears significance, but the split-half check says the pooled number
cannot be trusted to characterize the effect's actual magnitude: odd
years carry essentially the entire pooled result (t = -3.04) while even
years show almost nothing (t = -0.18) — a 17x swing in magnitude between
the two halves, never flipping sign, but the same shape of concentration
that already discredited Round 14's `rate_beta_x_move` (45% of that
effect from a single year). **What survives this scrutiny is narrower
than "significant, wrong-signed": the sign is consistently wrong across
both halves, but the size of the effect is not something this sample can
pin down.** The conclusion is unchanged either way — not added to the
composite, in either sign — but it is a weaker, not stronger, negative
than `asset_growth`'s cleanly split-half-stable measurement.

**Read this as: the physics audit's own recommendation #3 ("value is the
strongest omission... cheap to build") does not survive being measured.**
The audit argued for building this factor from a real citation; having
built and measured it, the data says the classical value premium is not
present — or is inverted — in this specific down-cap universe over this
specific period. **Not added to the composite, in either sign** — a
wrong-signed measurement is not grounds to add the factor with the
opposite sign any more than `asset_growth`'s was; both are disclosed
negative findings, not backtestable discoveries.

One candidate explanation, not tested here: this universe already screens
on `gross_profitability` (the "other side of value" per Novy-Marx's own
framing), and a down-cap universe skews toward small, statistically
"cheap" names that are cheap **because they are troubled** rather than
because they are mispriced-but-sound — the classic value-trap failure
mode the profitability literature exists to filter out. If this gets
revisited, screening book-to-market's IC **within** the top
gross-profitability tercile specifically (rather than the whole eligible
universe) would test that explanation directly rather than assuming it.

## 5. Summary table

| variant | construction | mean excess/yr | sd (offsets) | offsets positive | null pctile | vs. confirmed baseline |
|---|---|---:|---:|---:|---:|---|
| **confirmed baseline** | `decile_volq`, 9(8) factors | **+3.75%** | 0.37% | 40/40 | 100% | — |
| `decile1_volq` | `decile_volq`, decile 1 not 9 | **−0.83%** | 0.47% | 1/40 | 0% | refutes physics doc §6 |
| `exclude_bottom_decile` | hold ~90%, same factors | +2.79% | **0.20%** | 40/40 | 100% | real, not apples-to-apples |
| `asset_growth_dropped` | `decile_volq`, 8(7) factors | **+4.32%** | 0.55% | 40/40 | 100% | improves mean, adds dispersion |
| `book_to_market` | screen only, no portfolio | n/a (IC −0.024, t −2.32) | — | — | — | wrong-signed, not added |

## 6. What this changes about the physics audit's own recommendations

- **Recommendation #1** (doc fixes) — done, both source documents corrected.
- **Recommendation #2** (test avoid-decile-0 / buy-deciles-1-3) — tested as
  `decile1_volq` (refuted) and `exclude_bottom_decile` (real but not a
  clean comparison to the confirmed construction). Neither is a drop-in
  replacement for `decile_volq` on this evidence.
- **Recommendation #3** (build book-to-market) — done; the value premise
  did not survive measurement (section 4).
- **Recommendation #4** (|t|<1 shrinkage) — rejected before running
  (section 0).
- **Recommendation #6** (promote `log_market_cap`) — untouched by this
  round; still an unactioned nomination per the physics audit, still
  Gabe's call.

**The one number worth bringing to Gabe directly: `asset_growth_dropped`
at +4.32%/yr vs. the confirmed +3.75%/yr**, on a single pre-registered
ablation, with the added-dispersion caveat stated plainly. Everything else
in this document is either a disclosed negative (decile1, book-to-market)
or a real-but-uncertain-comparison positive (exclude-bottom-decile) that
needs the no-exclusion control before it means anything more than "the
score isn't garbage."

## 7. Reproduction

```bash
cd final/src/reset2026
python3 correction_variants.py
# -> final/out/reset2026/correction_variants_report.json

python3 harness_check.py   # optional -- the section 3 cross-check above
# -> final/out/reset2026/harness_check_report.json
```

~10 minutes (3 backtest variants x 40 offsets x 50 matched nulls, plus one
IC screen). Requires `composite_panel.parquet` and `outcome_cache.parquet`
already built. Touches 2007-2019 only.
