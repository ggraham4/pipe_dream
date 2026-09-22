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
