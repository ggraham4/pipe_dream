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

### 2a. The no-exclusion control (2026-09-22, per Gabe's request) — mostly
### universe beta, not selection

`no_exclusion_control.py`: same vol-quintile bucketing, same inverse-vol
weighting, **zero score input** — every eligible cap150 name is held,
nothing excluded. Nomination era, cap150, 15bp, all 40 offsets:

```
mean excess CAGR vs SPY:  +2.40%/yr   (exclude_bottom_decile: +2.79%/yr)
sd across offsets:         0.20%      (exclude_bottom_decile: 0.20%)
offsets positive:          40/40      (exclude_bottom_decile: 40/40)
mean years won:            8.1/13.0   (exclude_bottom_decile: 8.2/13.0)
```

**This resolves the open question, and not in `exclude_bottom_decile`'s
favor.** A construction that uses the composite score for literally
nothing gets +2.40%/yr — 86% of `exclude_bottom_decile`'s +2.79%/yr, with
matching dispersion and years-won. Knowing which decile to exclude adds
about +0.39pp/yr on top of simply being long the down-cap,
survivorship-corrected universe, inverse-vol weighted. That +0.39pp/yr
may still be real (it's the right sign, and consistent with the
composite's own measured full-universe IC), but it is a small increment
on a large, construction-driven base, not evidence that "avoid the
bottom decile" is itself a strong standalone strategy.

**Read together with `decile_volq`'s own number, this is informative
about where the confirmed construction's edge actually comes from.**
The three constructions, same scores, same universe, same dates:

| construction | book size | mean excess/yr |
|---|---|---:|
| `decile_volq` (confirmed, adopted) | ~10% | **+4.32%** |
| `exclude_bottom_decile` | ~90% | +2.79% |
| no exclusion at all | 100% | +2.40% |

Concentrating into the top decile roughly **doubles** the excess return
of holding the broad universe or excluding only the worst decile. Most
of the "broad" constructions' edge is universe beta; most of
`decile_volq`'s incremental edge over that beta is genuine top-decile
selection — the opposite conclusion the audit's decile table (section 6
of the physics doc) originally pointed toward, and the reason
`decile1_volq` (§1 above) failed outright. The confirmed construction's
concentration is doing real, measurable work.

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

## 6b. Second hold-out spend (explicit, at Gabe's request) — the aggregate
## number and the LOYO check disagree

Gabe asked to see `asset_growth_dropped` on 2020-2026 anyway, having
already been told 2020-2026 is spent for this pipeline. That is his call;
recorded as a second, deliberate spend in `PREREGISTRATION.md`, scoped to
this one variant only (not the other three, which would turn one
requested number into a four-cell hold-out search). Descriptive, not a
confirmation — this does not change `asset_growth_dropped`'s status as an
unadopted recommendation either way.

| | confirmed baseline (`decile_volq`, 9(8) factors) | `asset_growth_dropped` |
|---|---:|---:|
| mean excess CAGR vs SPY | +1.85%/yr | **+2.62%/yr** |
| offsets positive | 39/40 | **40/40** |
| mean null percentile | 98% | 99% |

**On the aggregate alone, the ablation looks better on hold-out too.**
Year by year (pooled across all 40 offsets per year, not a single-offset
read):

| year | baseline excess | `asset_growth_dropped` excess |
|---|---:|---:|
| 2020 | +23.98% | **+30.72%** |
| 2021 | −5.60% | −8.14% |
| 2022 | +11.98% | +9.64% |
| 2023 | −9.91% | −7.23% |
| 2024 | −4.39% | −1.07% |
| 2025 | −7.32% | −6.68% |
| 2026 (partial) | +2.94% | +1.65% |

**The ablation's hold-out result is carried by 2020 to the same degree
the baseline's was, not less.** Leave-one-year-out, computed the same way
as the baseline's own check (pooling every offset's per-year excess,
dropping one calendar year, re-averaging the rest):

```
drop 2020  ->  mean excess flips to -1.97%/yr   (baseline: -2.05%/yr)
drop 2021  ->  +4.50%/yr
drop 2022  ->  +1.54%/yr
drop 2023  ->  +4.35%/yr
drop 2024  ->  +3.33%/yr
drop 2025  ->  +4.26%/yr
drop 2026  ->  +2.87%/yr
```

**This is essentially the identical failure mode, at essentially the
identical magnitude.** A +0.77pp/yr bigger headline number
(+2.62% vs +1.85%) is not a more robust one — dropping 2020 flips both to
almost exactly the same small negative number (-1.97% vs -2.05%). The
ablation that improved the nomination-era result (section 3) does not fix
the thing that actually failed in the original hold-out confirmation: a
7-year hold-out dominated by one COVID-recovery year is not made
more trustworthy by a factor change that also happens to do slightly
better in that same year (+30.72% vs +23.98% — `asset_growth_dropped`'s
2020 is bigger, not smaller, than the baseline's).

**Reading this correctly**: the nomination-era ablation result (section 3,
LOYO-clean there, worst single-year drop still positive) stands on its own
un-touched by this. What this section adds is narrower and more
deflating: whatever hold-out improvement the ablation shows is not
evidence the ablation fixed the hold-out's known fragility — it's the
same fragility, slightly bigger in both directions.

Reproduction: `python3 holdout_check_asset_growth_dropped.py` →
`holdout_asset_growth_dropped_report.json`. ~75 seconds.

## 6c. A real data bug found chasing 2020, per Gabe's own suspicion of the
## 2020 numbers

Investigated directly (`investigate_2020.py`) rather than accepted: which
tickers actually drove 2020's +30.72% excess. Two names dominate the tail
of 55,191 (offset, date, ticker) picks that year.

**`GME` (GameStop) — real, checked against the public record, not a bug.**
Picked in late Nov/early Dec 2020 (price ~$3.7-4.2, low weight ~0.1% —
correctly bucketed as a small, unremarkable position at entry); a 40-day
hold from those dates lands squarely in the real, well-documented January
2021 short-squeeze window. Returns of +452% to +1,970% on this position
are consistent with GME's actual public trading history. This is a real,
extraordinary, one-off event the model could not have predicted and
should not be expected to repeat — luck of calendar timing, not signal.

**`LCID` — a real data bug, not checked out before this, and it is the
single largest contributor to the whole year.** `LCID` (5 picks, Dec
2020, weight ~3% each — the HEAVIEST weight of any 2020 pick, because the
pipeline's series shows it as extremely low-volatility) contributes
**+2.09 (weight x return) of the year's 18.76 total — more than the
next 4 tickers combined**, on returns of +427% to +482%.

Checked against the real, public trading history of the security this
ticker actually was in Dec 2020-Feb 2021 (`LCID` = Lucid Group's ticker
only from July 2021 onward; before that it was Churchill Capital Corp IV,
"CCIV," the SPAC that later merged with Lucid — one of the most
well-documented SPAC squeezes of that period): **the pipeline's series
shows $573.70 on 2021-02-22; CCIV's real, publicly documented close that
day was $64.86** — off by ~8.85x. Whatever this pipeline's Sharadar-
sourced `LCID.csv` holds for 2020-07-30 through mid-2021, it does not
match the real security's trading history at anywhere near the right
scale. Root cause not chased further here (ticker-history mapping error
of the kind Round 11 already found and fixed 41 instances of; a units-
vs-shares or split-factor scaling error; or something else) — flagged as
an open, unresolved data-quality bug, not fixed in place.

**Quantified impact** (`lcid_impact_check.py`, LCID excluded from the
eligible universe entirely, full 40-offset re-run): 2020's excess drops
from +30.72% to **+24.28%** (LCID alone: +6.44pp of that one year), and
the **full 7-year headline drops from +2.62%/yr to +1.80%/yr** —
**statistically indistinguishable from the original baseline's own
+1.85%/yr.** The entire nominal hold-out "improvement" this section
opened with (section 6b: +2.62% vs the baseline's +1.85%) does not
survive removing one bad ticker. Whether the baseline's own +1.85%/yr is
similarly inflated by the same `LCID` contamination was not checked here
(same construction, same dates, so plausibly yes) — a clean same-basis
comparison would need to exclude `LCID` from the baseline's own hold-out
run too, not done in this pass.

**This does not touch anything already reported as confirmed.** `LCID`'s
price data in this pipeline starts 2020-07-30 — it has zero effect on the
2007-2019 nomination-era result (section 3's `asset_growth_dropped`
result, and everything in `2026-09-22-composite-model-physics.md`) either
way.

Reproduction: `python3 investigate_2020.py` (diagnostic, prints
concentration/top-contributor tables) and `python3 lcid_impact_check.py`
(quantifies the exclusion). ~3-4 minutes combined.

## 6d. RETRACTION: LCID was not a bug. It was a real, SEC-filed reverse
## split, and this section 6c is wrong about the root cause

Section 6c's core claim — that `LCID`'s price series doesn't match reality
— does not survive a second look, kept here rather than deleted because
the mistake and how it was caught are as useful as the correct answer.

**What broke the original comparison.** Section 6c compared the
pipeline's *adjusted* `close` on 2021-02-22 ($573.70) against a *raw*,
unadjusted historical price recalled from memory (CCIV's real close that
day, ~$64.86) and called the ~8.85x gap a bug. That comparison is invalid
on its face once you know the adjusted series gets *retroactively
rescaled* every time a later split happens — the two numbers are not on
the same basis, and the gap says nothing by itself.

**What actually happened, built while validating a general safeguard, not
by re-litigating LCID specifically** (`price_adjustment_scanner.py`, built
in response to Gabe's request to safeguard future experiments): a genuine
stock split has a specific, checkable signature — the RAW price
(`closeunadj`) shows a real, same-day jump matching the split ratio, while
the adjusted price (`close`) stays smooth, because staying smooth across
real splits is the entire point of adjusting. Checked against AAPL's
undisputed 2020-08-31 4-for-1 split first to validate the logic (raw
499.23 -> 129.04, a real ~3.9x drop; adjusted 124.808 -> 129.04, ordinary
— signature confirmed), then applied to LCID: **`closeunadj` jumps from
$1.98 to $17.66 (~8.9x) on 2025-09-02, while `close` moves smoothly
($19.80 -> $17.66) that same day — the identical real-split signature.**

**Verified against the public record** (web search, not a project script —
the network restriction in `AGENTS.md` is about this pipeline's own
data-pull scripts, not about fact-checking a public corporate action):
Lucid Group filed an 8-K and completed a real 1-for-10 reverse stock
split effective 2025-09-02, shares outstanding reduced from
~3,072.6 million to ~307.3 million
([SEC 8-K](https://www.sec.gov/Archives/edgar/data/1811210/000181121025000022/lcid-20250829.htm),
[Lucid IR](https://ir.lucidmotors.com/news-releases/news-release-details/lucid-group-inc-announces-effective-date-reverse-stock-split)).
This is a real corporate action, filed and dated within a day of the
exact transition this pipeline's data shows. There is no bug.

**What this means for section 6c's numbers.** LCID is real, in the same
sense GME is real — an extraordinary, non-repeatable, correctly-priced
event that a low-vol-bucketed, inverse-vol-weighted construction happened
to pick right before it moved. The **quantified impact stands as a
concentration finding, not a data-quality finding**: excluding LCID still
drops the full hold-out headline from +2.62%/yr to +1.80%/yr, and that
number is still the right one to look at when asking "how much of this
result rests on one ticker" — it just isn't evidence of a corrupted price
file. `AGENTS.md`'s Known Gaps entry for this is corrected alongside this
section, not left standing.

**The actually useful output of chasing this down**: `price_adjustment_
scanner.py` (validated on two real cases, reduces a naive close-vs-
closeunadj scan from 710 false positives — mostly ordinary splits missing
from an incomplete reference table — down to a 91-event shortlist most of
which are very likely real spin-offs/special distributions the split-ratio
arithmetic doesn't model, not confirmed bugs either) and
`concentration_monitor.py` (flags when one ticker dominates a period's
return regardless of whether the cause is real or a bug — the check that
should have run automatically before section 6c's claim was ever written
down). Both described in full in section 8 below, both meant to run
before trusting a future number, neither meant to auto-classify a flag as
"confirmed bad" the way section 6c did.

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

## 8. Two standing safeguards, built chasing 2020, meant to run before
## trusting the next report

Per Gabe's request to clean up the data and safeguard future experiments,
built and validated while working through sections 6c/6d above. Neither
is a one-time fix -- both are meant to be reusable, run again on the next
suspicious number rather than something only this session benefits from.

### 8.1 `price_adjustment_scanner.py` -- a triage tool, not a bug classifier

Scans every ticker's `close` vs `closeunadj` (`data/sharadar/panel/
stocks/*.parquet`) for ratio jumps and checks each one against the
validated signature of a real stock split: `closeunadj` shows a real,
same-day jump matching the ratio change; `close` stays smooth, because
staying smooth is what adjustment is for.

**Two earlier versions of this check were built and both failed, kept in
the script's own docstring rather than silently replaced:**
1. Cross-referencing `sharadar_splits_raw.csv` (a 660-ticker table built
   for the options workstream) flagged 710 "anomalies" -- almost all
   ordinary real splits simply outside that table's coverage.
2. Cross-referencing `sf1_shares.csv` flagged AAPL's own famous 2014 and
   2020 splits as unexplained -- `sharesbas` turns out to already be
   split-continuity-restated (AAPL's filed share count sits flat straight
   through its 2020 split), so it can't discriminate a real split from a
   bug either way.

**The version that works** is validated against two real, checked cases
(AAPL's 2020 split: correctly clears; LCID's 2025 reverse split: also
now correctly clears, after the arithmetic bug in an earlier draft of
this same check briefly flagged it too -- see the script's own history).
Run against the full ~4,011-ticker universe: reduces 1,203 raw ratio
jumps to a **91-event shortlist across 81 tickers**
(`out/reset2026/price_adjustment_scan_report.json`). Most of the
remainder look like real spin-offs and special distributions (HLT/Hilton
2017, MSI/Motorola 2011, LDOS/Leidos 2013, EXPE/Expedia 2011 all appear,
and all are real, documented corporate separations) that the pure
split-ratio arithmetic doesn't model correctly, rather than confirmed
bugs. **Treat the output as a manual-review shortlist, not a finished
bug list** -- the LCID episode is the direct demonstration of why: this
project got the classification wrong once already on stronger-seeming
evidence than a bare scanner flag.

Usage: `python3 price_adjustment_scanner.py` (~10s, no new data). Run it
whenever a backtest number looks unusually good, or periodically as a
standing check, and web-search-verify (as done for LCID) or check
`AGENTS.md`'s existing corporate-action documentation for any name that
lands in a future concentration flag (8.2) before spending time treating
it as a bug.

### 8.2 `concentration_monitor.py` -- always run this one

Flags when a single ticker accounts for more than 10% (`FLAG_THRESHOLD`,
untuned -- a starting point) of a period's total (weight x return)
contribution. Deliberately agnostic about WHY a name concentrates --
GME (real) and the LCID false alarm (also real, it turns out) would both
have been flagged by this exact check, and both deserved a human look
before the number that depended on them got quoted, regardless of which
one turned out to be a bug.

```python
from concentration_monitor import concentration_report, print_report
report = concentration_report(records)   # records: the same per-pick
print_report(report)                     # dicts run_offset() already produces
```

Self-test (`python3 concentration_monitor.py`) reproduces this session's
2020 finding: top ticker LCID, 11.1% share of 2020's total contribution,
flagged. This is the check that should have run automatically before
section 6c's claim was ever written down by hand -- from here forward,
call it on every new backtest's picks before reporting a headline number,
not only when a year looks suspiciously good.

**A real bug in this metric, found immediately on first use against the
nomination era, fixed before it shipped.** The original `top_ticker_share`
(contribution / the period's NET total) reported `DADE` as "-85% of
2007" -- DADE's actual 2007 picks were an unremarkable handful of small
positive contributions; 2007's NET total merely happened to sit close to
zero, and dividing anything by a near-zero denominator produces
meaningless, sign-flipping percentages. Fixed by gating the flag on
`top_ticker_share_of_gross` (contribution / sum of |contributions|,
always positive, immune to this) instead; the net-total share is still
reported for context but never gates a flag. Documented in the module's
own `FLAG_THRESHOLD` comment so the failure mode doesn't get silently
reintroduced.

**Run against the now-confirmed, now-adopted composite's nomination-era
picks** (`concentration_check_nominate.py`) — **not flagged in any of the
13 years.** Max single-year gross share: 2.6% (`KDP`, 2018), well under
the 10% threshold. This is genuinely reassuring: the fragility found in
the hold-out (GME, LCID) is a hold-out-specific property of a short,
regime-concentrated window, not a standing weakness of the confirmed
nomination-era result.

## 9. Theoretical model extension #1: a mechanical market-beta term

Per Gabe's direction to extend the theoretical model with logic-derived,
not fitted, terms — reasoning: "a theoretical model that makes
predictions and can be tested... based in logic not fitted values, like a
physical model." Two structural gaps were identified; this section covers
the one to build now (a market-beta term). The other (a jump/catalyst
term distinct from the smooth-drift factors) is addressed in section 9c
below as an explicit, accepted theoretical limitation, not built.

### 9a. The gap and the fix

The composite has never had a term for the single largest mechanical
driver of any 40-day stock return: exposure to the market itself. Every
IC and backtest number in this project measures a within-date
cross-sectional rank correlation, which nets out the *average* market
move that day — but it does NOT net out the *dispersion* in exposure that
comes from stocks having different betas. Two stocks with identical
composite scores but different betas will realize different returns on a
day the market moves, for reasons that have nothing to do with the
composite's information.

`build_beta_feature.py`: `beta_i,t = Cov(r_i, r_mkt) / Var(r_mkt)`,
trailing 252 trading days, causal, via SPY as the market proxy. This is
the identical definition from Sharpe (1964) and the market-model
methodology of Fama, Fisher, Jensen & Roll (1969) — a mechanical
estimate, not a fitted parameter. 252 days and SPY are the standard,
off-the-shelf choices; nothing here was tuned against this project's own
backtest. Coverage 91.8% of the full panel; distribution (median 1.07,
p10 0.55, p90 1.75) matches textbook expectations for individual-stock
betas.

### 9b. Diagnostic result: the composite is already a strong beta bet, and
### removing it sharpens the signal

`beta_diagnostic.py`, nomination era, cap150, adopted (`asset_growth_
dropped`) composite:

```
corr(composite score, beta_252):        -0.2933   t=-17.12   (n=3272 dates)

IC vs RAW forward_return_tradable_40:   +0.0317   t=+2.53
IC vs BETA-ADJUSTED (market-model
  abnormal) return:                     +0.0450   t=+4.25
```

**Two findings, both real.** First, the composite's own already-diagnosed
"low-volatility tilt" (physics doc section 8) is, more precisely, a
**strong low-beta bet** — a -0.29 correlation is not a subtle effect.
Second, and more useful: scoring against beta-adjusted returns instead of
raw returns **sharpens** the measured IC (t goes from 2.53 to 4.25,
point estimate up 42%) rather than weakening it. This says the raw-return
IC was carrying real noise, not signal — on days the market moved a lot,
the composite's mechanical beta tilt pushed its raw-return IC around
(down on up days, up on down days) independent of whatever genuine
stock-specific information it has. Removing that noise makes the model's
actual selection skill easier to see, not harder. This is exactly the
kind of result a logic-first addition should produce: a mechanical
correction, no fitting, and it improves the read rather than being
selected because it improved the read.

### 9c. Theoretical model changes made

`prediction_ledger.py`'s point forecast is now calibrated on beta-adjusted
(market-model abnormal) returns rather than raw returns, per 9b. The
already-committed v1 ledger entry (`prediction_ledger.csv`, panel_date
2026-09-08, recorded under the pre-beta spec) is **frozen and untouched**
— a live commitment doesn't get retroactively upgraded. All predictions
from this point forward go into `prediction_ledger_v2.csv` (new schema:
adds `beta_252` per name, renames the point-forecast column to
`predicted_idiosyncratic_return_40d`, and `score()` now reports both the
raw-return test and the beta-adjusted test side by side, since the raw
number is what you'd have actually made and the beta-adjusted number is
the cleaner read on whether the composite itself is working). A new
blind entry was recorded for the same panel_date (2026-09-08, 2,214
names) under the new spec, immediately after `selftest` validated the
updated scoring arithmetic against known nomination-era dates (including
catching and fixing a real NaN-propagation bug in the beta-adjusted
calibration: `beta_252` coverage is ~98%, not 100%, and the few missing
rows were poisoning the whole regression before being explicitly dropped).

**Illustrative, not new evidence** (this date is inside the already-spent
2020-2026 window): re-scoring the one already-matured recent date from
earlier in this session (2026-07-13, previously reported as a miss:
raw rank IC -0.058) under the new beta-adjusted lens gives IC -0.018 —
still slightly negative, but much closer to neutral. A meaningful chunk
of that "miss" was market-direction noise, not a genuinely bad set of
picks. This is a concrete illustration of 9b's point, not a new finding.

### 9d. Structural gap #2 (jump/catalyst risk): accepted as a theoretical
### limitation, not modeled

Per Gabe's explicit direction: **not built.** Stated here formally as a
limitation of this theory, not a silent omission.

GME and LCID (sections 6c/6d) are both, in different ways, instances of a
real, mechanism-backed phenomenon this linear model structurally cannot
express: **discrete, catalyst-driven repricing events (short squeezes,
merger-rumor pops) that are mechanistically MORE likely for exactly the
population (thin float, high short interest, compressed trailing
volatility) that a low-beta/low-vol composite is most likely to select
and weight heavily.** The existing `short_interest_days_to_cover` factor
already identifies this population — it just treats it as a linear,
negative expected-return signal (Boehmer-Jones-Zhang), which is a
different, both-real claim from "this variable also raises the
probability of an extreme positive tail event." A linear model can
express a variable's effect on the mean; it cannot simultaneously express
a second, opposite-signed claim about that variable's effect on the
tail.

**Explicitly not attempted**: a jump-probability sub-model, an
options-implied-volatility-based catalyst flag, or any other predictive
treatment of this population. The theory, as it stands, treats these
events as **irreducible idiosyncratic tail risk** — real, mechanism-
backed, and outside what a sign-constrained linear composite can
describe. This is the honest boundary of the current theory's scope, not
a gap to be quietly patched over. Any future attempt at this (Gabe's
originally-proposed item 2, tier 3 of the "meta model" roadmap —
`project-meta-model-roadmap` memory) needs real model capacity (a small
NN, or an explicit two-state jump-diffusion treatment) and its own
pre-registration; this document does not open that work.

## 10. Amihud illiquidity — screened, not promoted

Per Gabe's "go ahead." `build_amihud_feature.py`: trailing-20-day mean of
`|daily return| / (closeunadj x volume)`, same window/basis convention
`downcap_universe.py` already uses. Hypothesized sign +1 (illiquidity
premium, Amihud 2002).

```
pooled IC = +0.0009   t = +0.10   (n=3,272 dates)
odd-years IC  = -0.0100   t = -0.81
even-years IC = +0.0137   t = +0.98
```

**Essentially zero, and the split-half doesn't even agree on sign.** A
clean, well-powered negative — not a near-miss, not marginal. **Not added
to `FACTOR_SIGNS`.** Down-cap illiquidity, at least measured this way, is
not a source of return premium in this universe over this period.

## 11. Regime-conditioning diagnostic — one hypothesis holds, one fails,
## stopped per the pre-registered staging rule

Per Gabe's "I agree, continue." `amihud_and_regime_diagnostic.py`:
causal expanding-median split of trailing 60-day realized SPY volatility
(a parameter-free threshold — no percentile chosen after seeing results),
1,375 high-vol-regime days vs. 1,897 low-vol-regime days in the
nomination era.

```
momentum_12_1 IC:    high-vol regime -0.0242 (t=-1.02)   low-vol regime +0.0495 (t=+3.76)
  -> Hypothesis 1 (momentum weaker in high-vol, Daniel-Moskowitz): HOLDS

volatility_60 IC:    high-vol regime +0.0150 (t=+0.58)   low-vol regime -0.0168 (t=-0.87)
  -> Hypothesis 2 (low-vol premium stronger in high-vol, flight-to-quality): FAILS
```

**Hypothesis 1 is a real, substantial, correctly-directioned effect** —
momentum doesn't just weaken in high-vol regimes, it flips sign entirely
(+0.050 to -0.024), consistent with the momentum-crash mechanism this
project already cites (physics doc section 10). **Hypothesis 2 fails
outright, and not narrowly** — `volatility_60`'s IC is not just weaker
but wrong-signed (+0.015) in the high-vol regime, the opposite of the
flight-to-quality prediction.

**Per the pre-registration's explicit staging rule, this stops here.**
Both hypotheses were required to hold before proceeding to an actual
conditional-composite backtest (excluding `momentum_12_1` in high-vol
regimes). Only one did. Building the conditional variant anyway — keeping
the momentum-exclusion rule because it looks good and quietly dropping
the low-vol-strengthening half — would be exactly the selective,
post-hoc pattern-chasing this project's own culture treats as a red flag
(the "27% of zero-signal configs beat the market" calibration exists
because partial, cherry-picked confirmation is how false positives get
manufactured). **No conditional-composite variant is built. `FACTOR_SIGNS`
is unchanged.**

**What this is still worth**, honestly stated: hypothesis 1's result is
real and could motivate a *narrower*, separately pre-registered test
later (e.g., a momentum-only conditional rule, not bundled with a second
hypothesis that already failed) — but that is a new trial, not a
continuation of this one, and isn't opened here.

## 12. IC-shrinkage weighting — the first genuinely out-of-sample win
## this composite has produced

Per Gabe's explicit reframe: the objective is rank prediction, not
return magnitude, which makes pooled IC the target metric directly. An
advisor consult pointed at the one lever this session had already
measured and left unpulled: equal weighting sits at cosine similarity
0.47 from the IC-implied optimum (physics doc section 4), and
`gross_profitability` alone (IC +0.041) already outscores the full
equal-weighted composite (IC +0.026-0.032).

**Rule, pre-registered before running** (`ic_weighted_composite.py`):
`w_k = sign_k * max(0.1, |t_k| - 1) / normalizer`, `t_k` the factor's own
pooled-IC Newey-West t-stat. One rule, one run, no comparison of
alternatives.

**Genuinely out-of-sample** (weights fit on one half's years, IC measured
on the OTHER half only — never fit and measured on the same data):

| test | metric | weighted | equal-weight | 
|---|---|---:|---:|
| fit odd → test even | IC (raw) | **+0.0302** (t=+2.80) | +0.0183 (t=+1.12) |
| fit odd → test even | IC (beta-adj.) | **+0.0300** (t=+2.60) | +0.0254 (t=+1.84) |
| fit even → test odd | IC (raw) | **+0.0494** (t=+5.54) | +0.0434 (t=+2.35) |
| fit even → test odd | IC (beta-adj.) | +0.0501 (t=+5.62) | **+0.0622** (t=+4.08) |

**On raw returns, the weighted composite wins cleanly in both directions**
— higher point estimate AND higher t-stat, every time. **On beta-adjusted
returns it's more nuanced**: it wins the first split clearly, but in the
second split equal-weight has a higher point estimate (0.062 vs 0.050)
even though the weighted version still posts a higher t-stat (5.62 vs
4.08) — a smaller but more stable effect. Reported exactly as measured,
not rounded up to a clean sweep.

**In-sample** (full-period fit, full-period test — context only, this is
"how much dilution costs," not a forecasting claim): IC (raw) +0.0418
(t=+5.78) weighted vs +0.0318 (t=+2.51) equal; IC (beta-adj.) +0.0420
(t=+5.63) weighted vs +0.0452 (t=+4.26) equal — same pattern as the
out-of-sample splits.

**Production weights** (fit on the full nomination era — the most
data-rich estimate, used going forward since the split-half check above
already validated the *rule*, not this specific fit):

```
gross_profitability             +0.596   (vs +0.125 equal)
accruals                        -0.163   (vs -0.125 equal)
net_issuance_pct                -0.140   (vs -0.125 equal)
momentum_12_1                   +0.050   (vs +0.125 equal)
pct_from_high_252, volatility_60,
  days_to_next_filing_seasonal,
  short_interest_days_to_cover   +/-0.013 each (floor weight, vs +/-0.125 equal)
```

`gross_profitability` goes from 1/8 of the vote to essentially the
majority of it — a direct, disciplined correction of the dilution
documented in the physics audit, not a new discovery.

**What this is and isn't.** It IS a genuine, out-of-sample improvement in
rank prediction on the metric the project now cares about most (IC),
using a pre-registered, non-fitted functional form of an already-measured
statistic. It is NOT a portfolio backtest — no CAGR was computed here,
deliberately, per the reframe. Before this becomes the traded model,
someone needs to decide whether "reasonably predicts rank" is sufficient
on its own or whether a portfolio-level check is still wanted eventually;
that decision is not made here.

**A real bug found and fixed before trusting the numbers above.** The
first version of `compute_weighted_score` summed weighted terms without
renormalizing by how much |weight| was actually available per row — a
name missing `gross_profitability` (~60% of the total weight) would have
been scored off the remaining ~40% only, silently compressing its score
toward zero relative to fully-covered peers on the same date. Fixed to
renormalize by available weight (the weighted analog of how
`compute_composite`'s `.mean(skipna=True)` already handles equal-weight
missingness), then **re-ran the entire script to confirm the fix actually
mattered**: every number above moved by less than 0.0003 (e.g. fit-odd/
test-even IC_raw: 0.0302 -> 0.0304) — negligible, because the dominant
missing factor (`short_interest_days_to_cover`, absent for 100% of
nomination-era rows) is missing *uniformly*, which is a rank-preserving
scale change, not a rank-distorting one. The table above already
reflects the corrected numbers.

**Implemented**: `ic_weighted_composite.py` exposes
`compute_composite_ic_weighted()` with the full-period production
weights above as a reusable scoring function, parallel to (not
replacing) `composite.compute_composite()`. `prediction_ledger.py`'s
`record()` now computes and stores BOTH the equal-weight rank/score
(existing) and the IC-weighted rank/score (new columns
`ic_weighted_score`, `ic_weighted_rank_pct`) for every future blind
prediction, so the live forward ledger will independently track whether
the out-of-sample improvement above holds up on real, never-before-seen
dates going forward — the only test of this that hasn't already been
run.

## 13. Pushing further: three more factors, one exponent transform, per
## an advisor-guided 30,000ft pass — one real win, two clean negatives,
## the exponent idea correctly ruled out by math before it ran

Trial count against the nomination era, written into `PREREGISTRATION.md`
before this round ran: 9 prior trials + up to 4 more here = 13. All four
built from `sf1_fundamentals.parquet` columns already on disk — no new
data pull.

**Technical correction, worth restating precisely because it changes what
"try a power law" can even mean**: Spearman rho is invariant to any
monotonic transform of the FINAL composite score — raising the finished
score to a power moves rho by exactly zero, not approximately zero. The
only place an exponent can matter is applied to each factor's signed rank
*before* the weighted sum, where it changes how factors trade off against
each other. Tested that version, `p=2` fixed in advance (motivated by the
physics doc's own decile finding: information concentrated at the bottom
of the score range, flat middle — a transform that should, in principle,
let extreme values dominate more than the middle).

```
                          p=2 (exponent)      p=1 (baseline, current)
fit-odd -> test-even:    IC=+0.0302 t=+2.85   IC=+0.0304 t=+2.84
fit-even -> test-odd:    IC=+0.0466 t=+5.35   IC=+0.0496 t=+5.63
```

**No improvement — if anything, very slightly worse in both splits.**
Not adopted. `p=1` (the existing linear rank transform) stays.

**Three new fundamentals-based candidates, IC screen only, split-half:**

| factor | pooled IC | t | odd/even | sign |
|---|---:|---:|---|:---:|
| `fcf_yield` | +0.0059 | +0.81 | +0.0059 / +0.0059 | matches (+1), not significant |
| `leverage` | **-0.0161** | **-2.44** | -0.0206 / -0.0107 | **matches (-1), stable, significant** |
| `profitability_trend` | -0.0091 | -1.70 | -0.0101 / -0.0079 | **wrong sign** (assigned +1) |

**`leverage` (debtnc/assets) is a real, well-powered result** —
significant, correctly signed against the distress-risk-anomaly citation
(Campbell, Hilscher & Szilagyi 2008: high-distress firms earn *lower*
returns), and stable in sign across both halves of the sample. This is
the same evidentiary bar `asset_growth_dropped` cleared before being
adopted. **Not added to `FACTOR_SIGNS` in this pass** — flagged as a
ready, tested candidate for an explicit promotion decision, not adopted
unilaterally, since every other factor-set change this session went
through that same checkpoint. `fcf_yield` is a clean, unremarkable
negative. `profitability_trend` is wrong-signed and, per this project's
standing practice with `asset_growth`, would be a drop-candidate, not a
flip-candidate, if it mattered enough to act on — it doesn't clear
significance either way.

**Expectation set before running, now confirmed**: three more
fundamentals ratios moved measured rho by low single digits of a
thousandth at most, and the one real find (`leverage`) is exactly the
kind of result more data of the *same type* (more balance-sheet ratios,
same filings) was expected to produce — a modest, independent addition,
not a ceiling-breaker. Per the advisor's explicit framing: the realistic
ways rho's ceiling moves are a shorter horizon (more independent
observations), a wider universe (Round 15's breadth logic), or a
genuinely orthogonal data source — not more ratios off the same 10-Ks.

## 14. Returns vs SPY by market regime — confirmed IC-weighted composite,
## nomination era

Per Gabe's request, framed as lower-risk than the equivalent check on a
fitted model since no parameter search over this data occurred (a fair
distinction — the weights are a fixed function of an already-measured
statistic — but not a different rule about which era to look at; this
stays on the nomination era, 2020-2026 is not reopened). Construction:
`decile_volq` (the confirmed construction), IC-weighted composite score,
cap150, 15bp, all 40 offsets — identical methodology to every other
number in this package. Both regimes defined externally (SPY's own
realized return; the already-built causal vol split), not chosen after
seeing results.

**Regime A — SPY's own realized calendar-year return:**

| regime | years | n windows | mean excess/yr | sd | offsets positive |
|---|---|---:|---:|---:|---:|
| down (SPY < -10%) | 2008, 2022 | 253 | **+18.76%** | 8.24% | 40/40 |
| flat (-10% to +10%) | 2007, 2011, 2015, 2018 | 1,006 | +3.23% | 6.65% | 40/40 |
| up (SPY > +10%) | most years | 2,013 | +4.56% | 6.35% | 40/40 |

**Regime B — high/low realized-volatility regime** (causal expanding-
median split, reused from section 11's diagnostic):

| regime | n windows | mean excess/yr | sd |
|---|---:|---:|---:|
| high-vol | 1,375 | +7.21% | 8.37% |
| low-vol | 1,897 | +3.83% | 5.30% |

**Positive in every single regime bucket, 40/40 offsets positive in
every regime tested** — genuinely broad robustness, not concentrated in
one kind of market. **The model does best specifically in down markets
and high-vol regimes** — consistent with, and not a new discovery beyond,
everything already established this session about its low-beta
(section 9b: -0.29 correlation with mechanical beta) and quality tilt:
a defensive bet should be expected to look relatively best exactly when
markets are stressed, and it does.

**One real caveat, stated plainly**: the "down" bucket is **two calendar
years** (2008, 2022) — the same order of thinness that already burned
this project once this session (the 2020-dominance finding in the
hold-out). +18.76% could plausibly be carried disproportionately by one
of the two rather than reflecting broad-based down-market performance.
Not further decomposed here (would need re-running with per-window
records saved, not done in this pass) — flagged rather than asserted as
clean, matching how every other thin-sample result in this document has
been handled.

## 15. Turnover realism — one of the two mechanisms works, one doesn't,
## exactly as predicted before either ran

Per Gabe's steer that no real trader mechanically replaces the whole book
every 40 days. Two constructions, IC-weighted composite, cap150,
nomination era, tested separately because they do different things.

**Laddered/staggered (5 cohorts, offsets 0/8/16/24/32, 20% capital each,
blended by summing independently-compounding terminal wealth):**

```
single-offset legs:  ann_excess range +4.81% to +5.51%  (sd 0.23pp)
ladder (blended):     ann_excess +5.18%, mean_f_new 19.1%
```

**Confirmed exactly as predicted**: the ladder smooths offset-to-offset
dispersion (the timing-luck problem behind the 2020/GME/LCID fragility)
but its per-window turnover (`f_new` = 19.1%) is statistically identical
to any single offset's own (~19%). Staggering does not reduce turnover —
it only reduces which specific window's luck you're exposed to.

**Buffer/hysteresis band (hold unless a name falls out of the top 20% —
vs. strict top-decile re-picking every window; 20%/10% fixed, not swept):**

```
                 ann_excess    mean turnover (f_new)
baseline:        +5.09%        19.3%
buffered:        +5.43%        6.3%
```

**This is the mechanism that actually works** — turnover cut ~3x, and
the return did not suffer (it's marginally higher, though not claimed as
significant on its own). At 50bp cost (vs. 15bp): baseline loses 0.44pp
to the higher cost, buffered only loses 0.14pp — the cost drag shrank by
almost exactly the same ~3x the turnover did.

**Verdict on the hypothesis: half confirmed, half not, exactly split
along the line predicted before either ran.** Laddering addresses
variance/timing-luck; buffering addresses turnover and cost. They're not
substitutes for each other, and the honest answer to "will costs be less
of a concern" is: yes, but only because of the buffer, not because of
staggering the schedule.

## 16. Third hold-out spend: IC-weighted composite on 2020-2026 —
## the same fragility appears a third time

Per Gabe's request, on the correct grounds that frozen (non-refit)
weights make this closer to honest than a fresh search — logged as an
explicit third spend, purpose stated as data-quality/generalization
robustness, not discovery.

```
mean excess CAGR vs SPY (40 offsets): +2.44%/yr, 40/40 offsets positive
2020: +41.54%   2021: -7.17%   2022: +7.57%   2023: -7.76%
2024: -5.66%    2025: -13.60%  2026: +2.91%
drop 2020 -> mean flips to -3.95%/yr
```

**This is now the third time this exact pattern has appeared** — the
original baseline hold-out, `asset_growth_dropped`'s hold-out, and now
the IC-weighted composite's hold-out all show a strong, uniform,
40/40-offsets-positive aggregate that fails leave-one-year-out on the
identical year. That consistency is itself informative: this is not a
property of any one factor-weighting choice — it is a property of the
STRATEGY TYPE (down-cap, low-beta, quality-tilted) meeting one
extraordinary, largely non-repeatable market event (the COVID crash and
V-shaped recovery). Correcting caveat 4's framing directly: "no fitted
parameters" is exactly why this test was worth running (it isn't
contaminated by re-fitting to what it found), but it does not, and
cannot, immunize the result against a hold-out window that is short and
concentrated in one dominant regime. The result is the same finding
restated a third time with different weights, not three independent
confirmations.

## 17. Beta remedy: EWMA tested, found not broken, found genuinely more
## reactive than useful improvement — a disclosed, honest negative

RiskMetrics-convention EWMA (lambda=0.94 daily, ~11-trading-day effective
half-life) built as a remedy for the flat 252-day window's staleness. A
first implementation (cumulative lam^-t power weighting) threw a
numerical warning and produced AAPL beta collapsing toward zero and
flipping sign near the end of its ~5,000-day history — investigated
directly rather than dismissed. Re-implemented via pandas' own `.ewm()`
(a numerically stable recursive filter) and got **the identical values**
— confirming the original implementation was not algorithmically wrong.
Checked AAPL's actual daily returns against SPY in that window directly:
genuine, real divergence (e.g. 2026-08-18: AAPL +1.5%, SPY -0.7%) — not
corrupted data, just an ~11-day-memory estimate reacting to real
short-term idiosyncratic noise faster than a monthly-rebalance strategy
needs.

**Empirical comparison, same methodology as the original beta diagnostic:**

```
IC vs raw return:                +0.0317
IC vs beta_252-adjusted return:  +0.0450
IC vs beta_EWMA-adjusted return: +0.0462
```

EWMA is marginally better than the 252-day version, not worse — so the
"too reactive" concern doesn't show up as a practical cost in this
specific measurement. **Honest conclusion: a real, disclosed remedy
attempt that produced a small, not clearly significant improvement, not
a clean fix.** The standard RiskMetrics convention is not obviously
wrong for this use, but it also isn't obviously the right memory length
for a 40-day-hold strategy — a properly chosen (and pre-registered, not
swept) longer-memory decay might do better, but that is a new,
not-yet-run trial, not concluded here.

## 18. Options overlay: top-5 IC-weighted picks, 40-day ATM calls,
## Black-Scholes fair value — a direct empirical test of the already-
## disclosed "no jump/catalyst capability" limitation

Per Gabe's direct request. **No real option-chain data is loaded in this
environment** (that lives in the separate, 26GB DoltHub-sourced options-
premium-model workstream) — this uses Black-Scholes FAIR VALUE with
trailing realized volatility (`volatility_60`, corrected here to
annualized scale: the panel stores a raw daily std dev, median 0.0216,
confirmed by comparison to the normal 15-45% annualized range for
equities) as the implied-vol proxy, and the real point-in-time 3-month
Treasury yield (`data/rates/treasury_yields.csv`) as the risk-free rate.
**This is a theoretical ceiling, not a tradable estimate** — real market
IV is well-documented to sit above trailing realized vol on average (the
variance risk premium), which would raise true entry cost above what's
computed here.

Construction: top-5 by IC-weighted score each rebalance (single offset,
cap150, nomination era, 82 windows, 325 total option positions), strike
= entry close rounded to nearest $5, 40 trading days to expiry, held to
expiration.

```
Individual option contracts (n=325):
  mean return:    +23.4%      median return:    -79.8%
  47.1% expire completely worthless (return = -100%)
  23.4% gain more than 100%; max single-contract gain: +1,301%

Per-window basket (5 contracts, equal-weighted, n=82 windows):
  arithmetic mean:  +23.6%/window     median: +8.3%/window
  13 of 82 windows (15.9%): ALL 5 picks expire worthless simultaneously

Naive full-reinvestment compounding: terminal wealth -> $0 (ruin) --
  a single all-5-worthless window, compounded, permanently zeros a
  strategy that reinvests its whole book every cycle. Verified by
  inspecting the 13 individual wipeout windows directly, not assumed.
```

**Read this correctly: the compounded "-100%" and the arithmetic "+23.6%
per window" are both true, and both matter.** The option payoff structure
(lottery-shaped: mostly small/total losses, occasionally very large gains)
is a direct, real consequence of turning a *small, relative* signal (rho
0.03-0.05, decile spreads of a few percent) into a bet that requires a
*large, absolute* move to pay off at all. This is exactly the gap the
theory itself already named in §9d: this composite has no mechanism for
predicting discrete, large moves, only relative outperformance — asking
it to price options is asking it to do something it was never built to
do, and the ~16% total-wipeout rate is what that mismatch looks like in
practice, not a flaw specific to this options exercise.

**Not a recommendation either way.** A real trader would never run this
at 100% reinvestment (that's what produces the ruin number) — real
position sizing for a lottery-shaped payoff is its own separate problem
(Kelly-style sizing, already explored for a different purpose in this
project's options-premium-model workstream) that this pass does not
attempt. The honest summary: modestly positive in expectation under a
generous (fair-value, no variance-risk-premium) pricing assumption,
with a real, high, and here-quantified risk of simultaneous total loss
across the whole book that a stock-only version of this strategy cannot
produce.

## 19. Cross-model rank-accuracy comparison — icw8 (split-half) vs. q75,
## xrank, and simple baselines, on their common, pre-2020 intersection

**Pre-registered 2026-09-23, before `cross_model_accuracy.py` was run,**
per Gabe's direct request ("compare R²/rho across models") via the
project's COO coordination process. This section is the commitment; the
result (SUCCESS/KILL/MIDDLE, fixed in advance, see below) is appended
once the script has actually run, not edited into this pre-registration.

**Hold-out guard (mandatory, enforced at read time via parquet row-group
filters, not by post-hoc dropping):** the `q75`/`xrank` score caches
(`final/out/sweep/scores/price_fund_h40_{q75,xrank}_trd_*_s40.parquet`)
run through 2026. Every read in this comparison is filtered to
`timepoint < 2020-01-01` (score caches) / `date < 2020-01-01` (composite
panel, beta feature, outcome cache) at load time, plus a final
`assert max(timepoint) < 2020-01-01` on the assembled row set. Any
2020+ read here would be this project's fifth hold-out spend on this
factor set (see sections 6a, 6d, 16 for the first three, all on this
model; the fourth was the options-overlay pass in section 18, nomination
era only, not a hold-out spend itself but drawn from the same
pre-registration lineage) — not attempted.

**Rows:** the (timepoint, ticker) intersection of the two score caches
above and composite-panel rows with `eligible_cap150` and a non-null
`forward_return_tradable_40`. N is reported per date; expected to land
around 1,100-1,250 names across roughly 82 pre-2020 dates (q75's cache is
built on a large-cap-leaning universe, cap500k-and-up by construction —
see the required label below). If N per date comes in far below that,
the run stops to check for a ticker-symbol convention mismatch between
the Sharadar-style score-cache tickers and the composite panel's, rather
than reporting a result off a broken join.

**Models (fixed list, each scored on its OWN native cap150 cross-section
first, THEN subset to the intersection for IC — not scored only within
the intersection, which would silently change every model's own ranking
population):**

1. **icw8, split-half weights** — the headline row. Per-factor pooled-IC
   t-stats (`ic_weighted_composite.per_factor_t`) fit separately on
   ODD nomination years and EVEN nomination years (full cap150 panel,
   not the intersection), converted to weights via
   `ic_weighted_composite.fit_weights` (identical to section 12's
   protocol). The odd-fit weights score every EVEN-year date; the
   even-fit weights score every ODD-year date — every date in this row
   is scored out-of-sample with respect to its own weights. Before
   scoring anything, the odd/even weight sets are checked against
   section 12's own reported numbers as a sanity gate; if they don't
   reproduce, the run stops rather than proceeding on a silently
   different weight-fitting implementation.
2. **icw8, full-era `PRODUCTION_WEIGHTS`** — context only, not the
   headline (weights fit on the full nomination era including the dates
   being scored — in-sample by construction, kept for comparison against
   row 1's genuinely-OOS number).
3. **ew8** — the equal-weight 8-factor composite (`composite.py`'s
   current `compute_composite`, i.e. the corrected, `asset_growth`-
   dropped version). Imported directly from this worktree's own
   `reset2026/composite.py` — NOT via `current_signal_blend.py`, which
   inserts the MAIN CHECKOUT's stale, pre-correction 9-factor
   `composite.py` onto `sys.path` ahead of anything else; importing that
   file at all would risk silently turning this row into ew9. Not
   imported, at all, for that reason.
4. **`gross_profitability` alone** — signed rank_z, sign +1 (its own
   factor sign), the single strongest factor in the composite's weights.
5. **q75 score** — read as-is from its score cache, no transform
   (Spearman is invariant to monotonic transforms of either side).
6. **xrank score** — same, read as-is.
7. **Low-vol baseline, −`volatility_60`** — signed rank_z, sign -1.
8. **Composite+q75 blend — DROPPED, not computed.** The pre-registered
   condition for including this row was "only if computed by calling
   `current_signal_blend.py`'s own combination logic; otherwise drop the
   row, don't invent a blend." That file's blend formula
   (`blend_score = mean(rank_z(composite), rank_z(q75_score))`) is
   inline in its `main()`, not a callable function — re-typing that
   one-line formula would itself be "inventing a blend" under the
   pre-registered condition's own terms, and importing the file to reach
   it carries the exact stale-`composite.py`-on-`sys.path` hazard row 3
   avoids. Dropped rather than worked around either way.

**Metrics:** per-date Spearman rho, and Fama-MacBeth cross-sectional R²
exactly as defined in the physics doc's section 7 / implemented in
`model_audit.py`'s `fama_macbeth_r2` (per-date OLS of score on return,
R² = 1 - SS_res/SS_tot, mean across dates) — reused directly, not
re-derived. Each computed on both the raw `forward_return_tradable_40`
and the beta-adjusted (market-model abnormal) return, using the exact
`beta_252 × SPY forward_return_tradable_40` convention from section 9 /
`beta_diagnostic.py`. Because the score cadence (s40) is spaced exactly
40 trading days apart with 40-day-forward labels, the windows are
non-overlapping — a plain t-stat across timepoints is used for this
section's tables, NOT the Newey-West lag-39 correction used elsewhere in
this project for overlapping-window statistics (that correction assumes
serial correlation this cadence structurally doesn't have).

**Primary comparison:** the per-date PAIRED difference
rho(icw8 split-half) − rho(q75), on RAW returns (the physics doc's
section 2.6 defines rho on raw returns; beta-adjusted is reported as a
secondary table only, not the outcome-determining series). Mean, plain t
across timepoints, and both odd/even halves reported.

**Outcomes (fixed now, all terminal — reported as whichever this
produces, not reinterpreted after the fact):**
- **SUCCESS:** paired diff > 0, t ≥ 2, same sign in both halves. The
  composite ranks better than q75.
- **KILL:** paired diff ≤ 0. The composite is no better than q75 at rank
  accuracy.
- **MIDDLE:** positive, but t < 2 or the halves disagree. No detectable
  difference.

**Required labels on the result, wherever it's reported:**
- The intersection is roughly q75's large-cap-leaning pool (cap500k+),
  not cap150's full breadth — this result says nothing about how any
  model ranks the small-cap tail cap150 alone would include.
- Single s40 grid (one rebalance-offset cadence) — not this project's
  usual 40-offset average.
- Descriptive, not a new hypothesis test with its own trial budget — the
  running trial count in `PREREGISTRATION.md` is unchanged by this
  section.

**Not attempted here, by explicit scope (already logged as Gabe
decisions or open work orders in `COO.md`, not reopened by this
section):** the leverage factor's production-weight decision, a formal
Deflated-Sharpe/White-Reality-Check gate for this composite, the 2020
hold-out-dependency question, and EWMA-vs-rolling-252-day beta as the
production default.

*(Result appended below once `cross_model_accuracy.py` has actually run.)*

---

**Result, 2026-09-23.** Sanity gate passed first: the split-half weight
fit reproduced section 12's own reported OOS numbers exactly
(fit-odd→test-even IC=+0.0304, fit-even→test-odd IC=+0.0496) before
anything else ran. Intersection: 91,883 rows, 82 pre-2020 dates, N/date
612-1,442 (median 1,132) — within the expected large-cap-leaning range,
no ticker-join problem.

| model | rho (raw) | t | FM-R² (raw) |
|---|---:|---:|---:|
| **icw8, split-half (headline)** | **+0.0475** | **+4.19** | 0.0110 |
| icw8, full-era PRODUCTION_WEIGHTS (context) | +0.0490 | +4.43 | 0.0106 |
| ew8 (equal-weight) | +0.0443 | +2.77 | 0.0221 |
| gross_profitability alone | +0.0458 | +4.04 | 0.0107 |
| q75 | +0.0026 | +0.12 | 0.0359 |
| xrank | +0.0089 | +0.53 | 0.0208 |
| low-vol baseline (−volatility_60) | +0.0069 | +0.30 | 0.0364 |
| composite+q75 blend | — | — | DROPPED (see pre-registration above) |

**Primary comparison** — paired diff rho(icw8 split-half) − rho(q75), raw
returns: mean **+0.0449**, t **+1.89**, odd years +0.0518, even years
+0.0365 (same sign both halves).

**OUTCOME: MIDDLE.** The pre-registered SUCCESS bar was t ≥ 2 with
agreeing halves; this landed at t=1.89 — same sign in both halves, but
under the bar. Reported as pre-registered, not rounded up or
re-interpreted: this is not a SUCCESS.

**What the numbers say, read plainly (not part of the outcome
determination, which stands as decided above):** on this specific
large-cap-leaning intersection, icw8/ew8/GP-alone all rank meaningfully
better than q75 and xrank do (rho ~0.044-0.049 vs. ~0.003-0.009, roughly
an order of magnitude), and every composite variant clears its own t≥4
bar individually — q75 and xrank do not clear even t=1 individually on
this population. The PAIRED comparison's shortfall (t=1.89, not the
individual rows' own significance) comes from date-to-date variance in
the difference itself, not from the composite's own signal being weak.
FM-R² tells a different, worth-noting story: q75 (0.0359) and the
low-vol baseline (0.0364) have HIGHER cross-sectional R² than every
composite variant (0.0106-0.0221) despite lower rank correlation — R² is
sensitive to a few large-return names dominating the sum of squares in a
way Spearman rho is not, so the two metrics are not measuring the same
thing here and neither is more "correct." Required labels above (large-
cap-leaning intersection, single s40 grid, descriptive) apply to every
number in this result.

**R² inversion, explained (added on COO review):** Fama-MacBeth R² here
is UNSIGNED — a per-date OLS fit's R² is high whenever score and return
are tightly related in EITHER direction, even if the sign of that
relationship flips from date to date. A score whose slope sign is
unstable across dates can still collect a large mean R² despite carrying
no consistent directional information at all. That is almost certainly
what's happening with q75 (rho≈0.003, essentially no rank signal, yet
the highest R² in the table) and the low-vol baseline (rho≈0.007, same
pattern) — high per-date fit, no consistent direction. Rho is this
comparison's directional-accuracy metric and the one the primary
comparison and outcome are built on; R² is reported only as a magnitude
cross-check and should not be read as contradicting the rho-based
result.

**One factor, not eight (added on COO review):** `gross_profitability`
alone (rho +0.0458, t +4.04) is nearly indistinguishable from the full
icw8 split-half composite (rho +0.0475, t +4.19) — a difference of
0.0017 against differences of 0.02-0.04 between either of them and
q75/xrank. On this comparison, the composite's rank accuracy is
essentially carried by one factor, not a genuine eight-factor blend. This
is consistent with `PRODUCTION_WEIGHTS` already assigning
`gross_profitability` ~60% of total weight (section 12) — this result
is a second, independent confirmation of that concentration, not a new
finding, but worth stating plainly here since the headline number could
otherwise be read as "eight factors combine to beat q75."
