# Pre-registration — factor-composite reset (2026-09-18/19)

Written before any backtest in this package runs. Standing rules 6/9 (RUNBOOK
§10): gates and this spec do not move after seeing a result; a change gets its
own commit, before the next run, and prior verdicts stand.

## Why this package exists, and why it is NOT `sweep/`

Gabe's decision 2026-09-18 (`project-2026-09-18-foundation-reset` memory):
restart the stock model from scratch on three changes, because 19 rounds of
XGBoost/24-feature sweeps returned null or unreadable results — a knob-family
spread of sd 5.03%/yr with the deployed cell only 1.06 sd above its own
family's mean, a zero-signal synthetic grid reaching 2.577x, and the best cell
in an 84-cell sweep being a shuffled-noise column beating the deployed model.
The apparatus could not resolve effect sizes as small as real anomalies
produce.

The three changes, in the order Gabe approved them:

1. **Sign-constrained linear composite**, not a 25-column depth-3 XGBoost —
   collapses degrees of freedom to (approximately) zero: no fitted
   coefficients, only pre-registered signs and equal weights.
2. **Published anomalies**, not OHLCV transforms — every home-grown
   price/volume transform mined in Rounds 12-19 came back null; the only
   things that ever survived cleanly (`pct_from_high_252`, `volatility_60`,
   `days_to_next_filing`) are named, mechanism-backed anomalies.
3. **Down-cap the universe** — the $2B floor caps the Round 15 breadth
   ceiling (`1/ρ̄ ≈ 16` bets/window, flat across book sizes 5-100) and points
   away from where small-cap premia live.

This package (`final/src/reset2026/`) implements those three changes as a
**separate, self-contained pipeline**. It does not import `sweep/` and does
not gate on any `sweep/` verdict — the 253-cell shuffle-null backlog run in
progress on this machine as of this writing (started 18:09 EDT, before the
reset decision at ~20:15 EDT) is scoring 25-column XGBoost cells, i.e.
measuring the exact architecture this reset replaces. It is left running
(resumable, not mine to kill) but its output is not an input to anything
below.

## Hold-out status

Per `project-2026-09-18-foundation-reset` and
`feedback-dont-relitigate-methodology-calls`: Gabe explicitly refreshed the
2020-2026 hold-out for this restart and said not to re-argue that point. This
package treats 2020-2026 as unspent for the ONE configuration named in
"The hold-out shot" below, and only for that one configuration.

## 1. Universe

Base pool: `pit_universe.parquet`'s construction (domestic common stock,
Sharadar `tickers_master`), but re-derived at three market-cap tiers with a
**dollar-volume liquidity floor replacing the naive price floor** used at the
$2B tier:

| tier | market cap floor | liquidity floor | rationale |
|---|---|---|---|
| `cap2000` | $2B | `closeunadj > $10` (existing, for comparison) | reproduces the current deployed floor exactly |
| `cap500` | $500M | trailing 20-day median dollar volume ≥ $500k | mid-cap |
| `cap150` | $150M | trailing 20-day median dollar volume ≥ $250k | the down-cap expansion |

**Documented trap being avoided** (Round 11 post-mortem): the original $10
floor was look-ahead when applied to split-adjusted `close` (excluded Apple at
$5.98 adjusted vs $167.44 actual in the 2008 universe). The floors above are
applied to `closeunadj` (or, for the liquidity floor, `closeunadj * volume`,
which is dollars actually traded that day regardless of split history) —
never to split-adjusted `close`. Market cap itself (`marketcap` /
`sharesbas * close`) is a levels quantity and carries no such bias.

All three tiers are point-in-time: eligibility is evaluated at every
historical rebalance date from that date's own market cap and trailing
dollar volume, not today's.

## 2. Factors, signs fixed before any score is computed

| # | factor | sign | source | mechanism / citation |
|---|---|---|---|---|
| 1 | `momentum_12_1` | + | new (price panel) | Jegadeesh-Titman 1993 |
| 2 | `pct_from_high_252` | + | existing (`FEATURE_COLS`) | George-Hwang 2004 (52-week-high) |
| 3 | `volatility_60` | − | existing | Ang, Hodrick, Xing, Zhang 2006 (low-vol) |
| 4 | `gross_profitability` (`gp/assets`) | + | new (SF1) | Novy-Marx 2013 |
| 5 | `accruals` (`(netinc-ncfo)/assets`) | − | new (SF1) | Sloan 1996 |
| 6 | `asset_growth` | − | new (SF1) | Cooper, Gulen, Schill 2008 |
| 7 | `net_issuance_pct` | − | existing (`sweep/issuance.py`, Round 20) | Pontiff-Woodgate 2008 |
| 8 | `days_to_next_filing_seasonal` | − | existing (`sweep/events.py`, Round 16) | Frazzini-Lamont 2007 (earnings announcement premium; the seasonal estimator is the provably-causal variant — `_actual` is excluded here for the same reason it is excluded from `FEATURE_COLS`) |
| 9 | `short_interest_days_to_cover` | − | existing (`sweep/short_interest.py`) | Boehmer, Jones, Zhang 2008 |

Nine factors, nine literature-backed signs, zero fitted parameters at the
combination step.

**Correction (2026-09-22, model-audit section below):** `#9
short_interest_days_to_cover` has **zero non-null coverage anywhere in the
2007-2019 nomination era** (`model_audit_report.json`'s
`factor_availability`: first non-null date 2020-04-27). Every confirmed
nomination-era number in this document — including the named selection
below and the +3.75%/yr headline — was produced by an **8-factor**
composite, not nine; the 9th factor is real, correctly wired, and active
only in the hold-out period and the live signal, where it has never been
evaluated (evaluating it would require the 2020-2026 hold-out, which is
spent). Read every "9 factors" claim in this document as "8 factors,
2007-2019; a 9th active from 2020" until this is corrected at the source.
Also disclosed: `#6 asset_growth` measures `IC = +0.0105` (t = +1.47,
stable sign across both halves of the sample) against its assigned `-1` —
the opposite of its citation's prediction in this specific universe. Not
acted on here (see the model-audit section's ablation, tested and
reported beside the baseline, not substituted for it).

`insider_cluster_recent` and the `opt_*` options-implied
columns exist on disk but are declared OUT of the pre-registered composite —
insider data was flagged by Gabe as needing a source re-check
(`project-data-sourcing-priorities`), and the options columns cover a
large-cap-only subset (thin coverage below the $2B tier, which is exactly
where this reset is moving), so including them would silently reweight the
composite toward the sub-universe that has them. Either may be added as a
**new, separately-dated pre-registration** later; not folded in here after
the fact.

## 3. Combination — no fit

For each rebalance date, for each factor: cross-sectional **rank-transform**
to `[-0.5, +0.5]` across that date's eligible universe (robust to outliers and
fat tails; matches the existing project's use of rank-based scores elsewhere).
A missing factor value contributes 0 (neutral) for that name that date, and
the composite is the **mean of available signed ranks**, not the sum — so a
name missing 3 of 9 factors is not structurally penalized relative to one with
full coverage, and coverage itself is reported per date as a diagnostic.

    composite(i, t) = mean_k [ sign_k * rank_z(factor_k, t)[i] ]  over available k

Two variants are run side by side, per Round 13's discriminator:

- **raw** — the composite as defined above.
- **neutral** — each of the 9 factors residualized cross-sectionally on
  **sector only** (dummy variables, `tickers_master.sector` — current-day
  classification, the same declared limitation Round 13 already carries)
  BEFORE rank-transforming and combining. If `raw` shows excess return that
  `neutral` does not, the edge is a sector bet, not stock selection, per
  Round 13's own finding on the deployed model.

  **Amendment (pre-run, before any score was computed):** the control set is
  sector alone, not {sector, size, vol} as an earlier draft of this section
  said. `volatility_60` is factor #3 in the table above — residualizing it on
  itself is degenerate (identically zero), and more importantly, low-vol is
  a disclosed, literature-backed factor in this composite, not a confound to
  neutralize away. The vol/size-tilt question this project already knows to
  ask (Round 18: "is the edge just a purchasable ETF's tilt") is answered
  instead by the **USMV comparison in §6**, which tests it directly against
  a real low-vol fund rather than against a synthetic residualization that
  would have partly cancelled one of this composite's own named factors.

## 4. Portfolio construction — two variants, both reported

- **decile_volq** (mirrors the deployed model / RUNBOOK's primary metric for
  comparability): within each of 5 trailing-volatility quintiles, take the
  top decile by composite score, inverse-vol weighted across the resulting
  ~half-book.
- **topN_ew**: flat top 5% of the eligible universe by composite score,
  equal-weighted. Exists specifically to check whether `decile_volq`'s result
  is variance-drag reduction (Round 18's finding on the deployed model) rather
  than selection — if `topN_ew` shows materially less excess than
  `decile_volq` at similar volatility, that is the same artifact recurring in
  a new wrapper.

## 5. Execution and horizon

40-trading-day holds, non-overlapping windows, next-open entry with a
1-trading-day lag (`execution.realize_position`, unmodified, imported not
reimplemented) — same conventions as `execution.py`/`portfolio.py`. No
stop-loss (Round 13: the model this project already has does not need one to
be readable, and it is one more knob this reset is deliberately not adding
back).

**Amendment (pre-run):** cost is reported at TWO points, both post-processed
from the same cached gross per-position returns via `execution.
apply_turnover_costs`'s turnover-aware model (charges a position only on
actual entries/exits, not on every held position every window — Round 9's
finding that the naive alternative overstates cost by ~a third): **15bp**
round-trip, `execution.py`'s own current `DEFAULT_COST_BPS` (revised down
from an earlier, unchecked 50bp assumption — see that file's header), as the
base case, and **50bp** as an explicit stress case. An earlier draft of this
section named only 50bp as "matching execution.py"; that was a stale
assumption never checked against the file's actual current default, caught
before any score was computed.

Real underlying OHLC for every position (entries, exits, and the delisting
exit floor for any name that stops trading inside the 40-day hold) comes from
`scripts/td_data_sharadar/` — the single Sharadar-sourced, per-ticker export
that `continuous_walkforward_pit.py`'s own `--universe pit` path uses for
exactly this reason (see that file's `PRICE_DIRS_PIT` comment): mixing it
with the older `td_data_local`/`td_data_delisted` directories would price a
position on a different corporate-action basis from the one its features
were computed on for ~13% of tickers, and `td_data_delisted` still carries
41 wrong-issuer files. SPY and USMV benchmarks use their own existing files
(`scripts/td_data_local/SPY.csv`, `data/benchmarks/USMV.csv`) run through the
identical `realize_position` call for exact comparability.

**All 40 grid offsets are used, not offset 0.** `check_grid_offset.py`
demonstrated the non-overlapping-grid choice is a coin flip for weak signals
(`accel_20` sign-flips on 21/40 offsets). The headline statistic here is the
**mean across all 40 offset-grids**, with the full offset distribution
reported so a fragile result is visible as one, not hidden by a lucky offset.

## 6. Metrics

**Primary / the literal ask:** calendar-year excess return vs SPY (year-by-
year, net of costs) and the count of calendar years beaten — "beat SPY y/y"
is a win-rate statement, not a terminal-multiple statement, and is reported as
such first.

**Secondary, for power and honesty:**
- `decile_volq_excess`-analog (RUNBOOK's primary metric, same construction)
- excess CAGR, annualized info ratio, offset-averaged
- block-bootstrap 95% CI on excess CAGR (block length = 1 horizon, i.e. 40
  trading days, to respect the within-window autocorrelation this project
  already knows about)
- matched null: 100 draws per configuration, composite scores permuted within
  each date before ranking (same construction, same coverage pattern,
  cross-sectional pairing destroyed) — reported as a percentile, not a bare
  beat/no-beat
- **USMV comparison**, not only SPY (`final/data/benchmarks/USMV.csv`) —
  Round 18's attribution says the deployed model's edge is a low-vol tilt
  plus a sector bet, both purchasable for an expense ratio; a composite that
  beats SPY but not USMV has not demonstrated stock picking

## 7. Gates

- **Gate A (unchanged, absolute):** placebo/look-ahead/pool-integrity checks
  before any result is trusted — verified PIT joins (assert row count/order
  preserved through every merge_asof, same pattern as `sweep/issuance.py`),
  no NaN-to-bucket-0 silent fallback (RUNBOOK's own known trap — this
  package's bucketing explicitly masks NaN scores out of ranking rather than
  defaulting them into a bucket).
- **Decision bar, not a significance bar** (RUNBOOK §5, `validation-gates.md`
  DECISION BAR): deploy-worthy means expected excess return positive after
  costs with the downside understood via the bootstrap CI and the null
  percentile — a clean `t > 3` is not required and its absence is not by
  itself disqualifying.
- **Leave-one-year-out concentration**, standing procedure since Round 14, on
  any configuration that clears the above: if excess return is dominated by
  one or two calendar years the way `rate_beta_x_move` was (45% of the effect
  from 2019 alone), that is reported as a concentration finding, not silently
  averaged away.
- **Sector-neutral contrast is load-bearing, not a follow-up.** Both `raw`
  and `neutral` variants run in the same pass, and the headline report leads
  with both numbers side by side.

## 8. Selection and the hold-out shot

Nomination-era (2007-2019) search space: 3 universe tiers × 2 portfolio
constructions × 2 neutralization variants = **12 configurations**. All 12 are
scored; the ONE with the best `decile_volq_excess` (offset-averaged) on
2007-2019, subject to passing Gate A and not failing LOYO outright, is named
in a follow-up commit to this file BEFORE the hold-out run, together with
`--selection-trials 12` on the confirming run (Deflated-Sharpe-style
deflation against the true search size, per RUNBOOK's standing flag about
this exact bug: a hold-out run once printed DSR 0.956 against 4 trials where
the honest 1,152 gave 0.791).

The hold-out run happens exactly once, for exactly that one configuration.
Nothing here waits on the currently-running `sweep/` backlog job.

## Nomination-era result and the named selection (added after the nominate-era
run completed, before any hold-out score was computed)

Full results: `out/reset2026/REPORT_nominate.md`. Headline, all 40 offsets,
2007-2019, net of the turnover-aware 15bp cost:

| cell | decile_volq excess vs SPY | vs USMV | null pctile | offsets positive |
|---|---|---|---|---|
| cap2000_raw | +1.09%/yr | -0.10%/yr | 100% | 37/40 |
| cap2000_neutral | -0.32%/yr | -1.94%/yr | 91% | 8/40 |
| cap500_raw | +3.03%/yr | +1.22%/yr | 100% | 40/40 |
| cap500_neutral | +2.63%/yr | +1.22%/yr | 100% | 40/40 |
| **cap150_raw** | **+3.75%/yr** | **+1.86%/yr** | **100%** | **40/40** |
| cap150_neutral | +3.47%/yr | +2.36%/yr | 100% | 40/40 |

Three findings that make this readable, not just a big number:

1. **Monotonic in down-cap.** cap2000 (today's $2B floor, the universe every
   prior round in this project measured) is flat-to-negative once
   neutralized — consistent with everything Rounds 12-19 already found on
   that universe. The edge appears and grows as the floor comes down. This is
   what "down-cap is where the breadth ceiling was" predicts, not an
   assumption.
2. **Survives sector-neutralization.** cap150_raw -> cap150_neutral costs
   0.3pp (3.75% -> 3.47%), not the near-total collapse Round 13 found on the
   deployed model (2.80x -> 0.77x, to the exact centre of its own null). This
   is the discriminator PREREGISTRATION.md section 3 named as load-bearing,
   and it comes back the opposite way from every previous round's headline
   number.
3. **Survives leave-one-year-out.** No single dropped year takes the 13-year
   mean below +2.1%/yr (worst case: dropping 2008, the largest single-year
   contributor at +11.78%, still leaves +2.96%/yr). 2019 -- the year that
   was 45% of Round 14's now-rejected `rate_beta_x_move` effect -- is a DRAG
   here (-9.52%), not the driver. See `out/reset2026/` LOYO check output
   (reproducible via the per-offset `yearly` field already in every
   checkpoint JSON).

**Named selection: `cap150_raw`, `decile_volq` portfolio construction.**
Highest nomination-era `decile_volq_excess` of the 12 pre-registered
configurations, passes Gate A (PIT joins verified, outcome cache verified
against `execution.realize_position` on 300 direct samples, 0 mismatches),
passes LOYO. `topn_ew` on the same cell is reported alongside as the
already-included secondary construction, not a second search.

Confirming now, once:

    python3 run_backtest.py --era holdout --only cap150_raw --i-am-confirming

Selection trials = 12 (the full nomination-era search space named in section
8) is recorded here for the record. This package does not implement a
Deflated-Sharpe-style formal deflation against that count -- the DECISION
BAR philosophy this project adopted 2026-09-12 does not require one to act
-- but the number is written down now, before the hold-out score exists, so
anyone who wants to compute one later is not reconstructing it after the
fact.

## Hold-out result -- read `out/reset2026/REPORT_holdout.md` in full before
## acting on this

Confirmed once, `cap150_raw`/`decile_volq`, 2020-2026: **+1.85%/yr excess vs
SPY (15bp), 39/40 offsets positive, 98th percentile vs its own matched
null.** By the letter of this package's own gates (Gate A, decision bar,
null percentile) this passes.

**It fails leave-one-year-out, the one check this project's standing
procedure (RUNBOOK section 5, since Round 14) does not relax for a passing
gate elsewhere.** Two of seven hold-out years (2020, 2022) are positive; the
other five are all negative; dropping 2020 alone flips the seven-year mean
to -2.05%, and dropping both 2020 and 2022 gives -4.86%. This is the same
failure mode that already killed `rate_beta_x_move` in Round 14, arguably
worse here (2/7 years carrying it vs that finding's 1/13).

The nomination-era result (13 years, LOYO-clean, worst single-year drop
still +2.96%/yr) is NOT overturned by this -- a 7-year hold-out is a much
higher-variance LOYO test than a 13-year one, and 2020/2022 are exactly the
dislocation/factor-rotation years this composite's construction (quality,
low-vol, value-ish tilts) has a real economic reason to concentrate in. But
this package does not get to call the hold-out "confirmed" while failing its
own project's concentration standard. The honest status, carried forward:
**a real, monotonic-in-cap, sector-neutral-robust nomination-era signal that
has not yet demonstrated year-to-year robustness out of sample**, plus a
second open question (the `topn_ew` divergence: identical composite scores,
same dates, -4.80%/yr instead of +1.85%/yr on the SAME hold-out from a
portfolio-construction change alone) about how much of this lives in the
9 factors versus in the vol-quintile-bucketed construction specifically.

Per standing rule 9 (gates do not move after seeing a result): this verdict
is written directly into this document rather than softened, and no further
hold-out draw is taken to try to resolve it -- 2020-2026 is spent again,
this time for real, for this pipeline.

## Future avenues (roadmap discussed with Gabe, 2026-09-19)

Not implemented beyond the first item below. Recorded so a future session
doesn't have to reconstruct the reasoning.

**The "meta model" framing.** Gabe's framing: this composite should end up
as ONE INPUT among several into a higher-level model, not necessarily the
final answer on its own -- the higher level could be a gated blend, an
RNN, an XGBoost combiner, or something else. Three tiers emerged, ordered
by how much fitting each needs and how much this project's own history
already warns against jumping straight to the top of that order:

1. **Zero-fit blend of composite + q75** (DONE, this section). Rank-
   average the two scores 50/50, same `decile_volq` construction as the
   rest of this package, no new fitted parameters -- the cheapest possible
   version of "combine disagreeing signals." Motivated directly by the
   q75-comparison finding (section on comparison against q75, main
   write-up): rank correlation -0.225, negative in every sector -- two
   genuinely different views of the market, and combining forecasts that
   disagree is one of the more robust results in the forecasting
   literature (Bates & Granger 1969) independent of whether either view is
   individually strong.

   **Result** (`blend_q75.py`, `out/reset2026/blend_q75_report.json`):
   run on a SINGLE grid (q75's score cache has only one cadence --
   confirmed identical to this package's offset 0; scoring q75 at the
   other 39 offsets means retraining XGBoost 39 more times, which defeats
   the point of a cheap test), on the cap2000 universe (q75's own,
   not the composite's strongest cap150 tier), with q75 and the composite
   BOTH forced through `decile_volq` so the comparison isolates the blend
   effect rather than a construction difference:

   | | excess vs SPY/yr | nominate-only | holdout-only |
   |---|---|---|---|
   | q75 alone | +0.35% | +2.35% | -3.55% |
   | composite alone (cap2000) | +0.54% | +1.18% | -0.71% |
   | blend (50/50) | **+1.54%** | +2.52% | **-0.36%** |

   Blend beats both components, especially on hold-out, and beats its own
   matched null on 100/100 draws. **The genuinely encouraging part**: LOYO
   on the blend drops 2020 (still the largest single contributor) and the
   mean per-window excess goes from +0.24% to +0.06% -- it stays
   POSITIVE. This is a real difference from the cap150 composite-alone
   result, which flipped to -2.05%/yr when 2020 was dropped (main write-up
   section 3.2). The blend looks more stable, not just bigger.

   **Caveats, all real**: single grid (not the 40-offset average every
   other number in this package gets); q75 and composite here are NOT
   measured with their own headline constructions (q75's deployed book is
   5 concentrated single-best-per-quintile picks, not a ~160-name
   decile_volq book -- these numbers say nothing about the deployed app's
   actual performance); hold-out excess is still negative for all three
   in absolute terms, the blend is least-bad, not a confirmed winner.
   Treat as a promising lead consistent with the theory, not a second
   confirmed result at the same evidentiary bar as section 3.

2. **Low-dimensional, pre-specified regime gate** (bull/bear, or a
   trailing-vol threshold) -- NOT STARTED. Cheap in the same sense as the
   blend (no real fitting, just a threshold), but this project already
   ran a bull/bear-style regime gate once (the 2-state HMM on SPY returns
   blending the price-only and fundamentals-augmented models,
   `regime_signals_beta.py`) and it was retired on Gabe's explicit
   instruction ("we are no longer using the HMM"). The specific reasoning
   beyond that line isn't recorded here -- **check with Gabe why it was
   dropped before reusing the concept**, so this doesn't rebuild something
   already found wanting for a reason not visible in this document.

3. **Sparse, heterogeneous-effect events** (Fed surprises, geopolitical
   shocks, market-moving news/tweets) -- NOT STARTED, and structurally
   different from tiers 1-2. A per-stock factor or a smooth market-wide
   gate can't express "this event helps sector A and hurts sector B,"
   which is what these events actually do -- that needs something with
   real capacity, like a small neural net. The data-scarcity trap that
   motivated this whole reset applies here in a sharper form (a handful
   of major Fed surprises across the whole backtest is a much smaller
   sample than the breadth problem already documented) UNLESS the problem
   is reframed: pool across STOCKS reacting to each event, not across
   events themselves -- one FOMC decision is ~2,000 stock-level reactions
   with their own characteristics (sector, rate-sensitivity, existing
   factor scores) as inputs, turning "40-80 events" into tens of thousands
   of event x stock observations, a normal supervised-learning sample
   size. Alpha Vantage's `NEWS_SENTIMENT` endpoint is already connected in
   this environment and is the concrete starting point if this gets
   picked up -- build a per-stock, per-day sentiment/event-exposure
   feature first, joined onto the existing panel, before any learned
   stock-conditional-reaction model.

## Model-audit pre-registration (2026-09-22)

Written before `model_audit.py` runs, per Gabe's request to treat this
composite the way a physicist treats a theoretical model: state the
predictions, check the signs/coefficients against data, name missing
variables, and score fit across the WHOLE cross-section (not just the
traded book). This is a **descriptive audit of the already-confirmed
nomination-era model**, not a new backtest and not a search for a better
config -- like the sector-enrichment work (`AGENTS.md`, 2026-09-16), it
reports what the existing composite does, it does not select anything, so
the hold-out rule does not bind for the audit itself. It touches
**2007-2019 (nomination era) only** -- 2020-2026 is spent for this
pipeline (see above) and nothing below reopens it.

**Exactly two candidate variables are tested as an extension**, both built
from columns already on disk (no new data pull): `log(market_cap)` as a
continuous factor (distinct from its existing use as a step-function
universe floor) and 1-month reversal `momentum_1_1` (the return the
existing `momentum_12_1` explicitly skips). These are nominations, not
promotions -- scored for IC/sign only, never added to `FACTOR_SIGNS`, never
backtested as a portfolio. Trial count for this addition: 2.

**Quantities computed, all on `forward_return_tradable_40` (never the
non-tradable label -- Round 18's divergence #1), pooled across ALL trading
days in 2007-2019 (not one 40-day grid offset -- the grid-offset problem
applies to non-overlapping-window sampling, not to a pooled-day IC), with
Newey-West standard errors at lag 39 to account for the serial correlation
40-day-overlapping forward returns induce:**

1. Per-factor pooled Spearman IC + NW t-stat, on the `cap150` eligible
   universe, for each of the 9 signed factors plus the 2 candidates --
   compared against `FACTOR_SIGNS` to flag any measured-vs-assigned sign
   mismatch.
2. The same, split by `coverage` (number of the 9 factors a name has data
   for that day): high (>=8) vs low (<=4) -- tests whether the pooled
   score's tails are populated by low-coverage names with mechanically
   higher score variance and no matching return edge (the averaging-fewer-
   terms effect: a k-factor mean of iid-ish signed ranks has variance
   ~1/(12k), so k=2 is ~4.5x noisier than k=9).
3. Composite IC (raw and sector-neutral) on `cap150` and `cap2000`, full
   universe and by score decile -- extends the existing full-vs-top-decile
   comparison in the main write-up (section 3.5) to all 10 deciles, to see
   exactly where monotonicity breaks rather than only that it does.
4. IC -> IR consistency check: given Round 15's measured effective breadth
   (~16 at cap2000; cap150's own breadth has not been measured by this
   audit and is estimated from the same active-correlation method if cheap,
   else flagged as unmeasured), does `IR = IC x sqrt(breadth)` predict the
   realized portfolio IR in `REPORT_nominate.md`? A realized IR well above
   what IC supports implies the excess is construction (vol-bucketing /
   inverse-vol weighting cutting variance drag), not selection.
5. 9x9 factor-vs-factor pooled rank-correlation matrix (cap150, nomination
   era) and a comparison of equal weighting against the Grinold-Kahn
   IC-implied optimum (Sigma^-1 . IC) -- diagnostic only, per the
   package's own no-fitted-parameters design; the reported output is
   whether equal-weight sits within the estimation noise of the IC-implied
   weights, not a refit.
6. Fama-MacBeth cross-sectional regression of `forward_return_tradable_40`
   on the composite score, one regression per day, averaged: mean slope
   (NW t) and mean R^2, for cap150 raw, cap150 neutral, and cap2000 raw --
   reported alongside IC, not instead of it (a 0.1-1% cross-sectional R^2
   is the normal size for a real equity signal and should not be read as
   "explains nothing").
7. Sign-flip robustness for all 9 factors using the existing
   `check_grid_offset.py`-style approach (40 offsets) is NOT rerun in this
   audit (that machinery lives in `sweep/`, keyed to the old panel's
   column names, and porting it is out of scope for a descriptive pass) --
   instead, split-half stability is used as a cheaper proxy: pooled IC
   computed separately on odd/even calendar years of the nomination era,
   reported alongside the full-period IC for each factor.

Output: `final/out/reset2026/model_audit_report.json` (all numbers) and
`final/models/2026-09-22-composite-model-physics.md` (the write-up).

## Correction-round pre-registration (2026-09-22, part 2)

Written before `correction_variants.py` runs, after an advisor review of
the model-audit findings above talked one candidate correction back out
of scope before it ran (recorded here for the record, not softened):
**dropping every factor with pooled |t| < 1 was considered and
rejected.** `volatility_60` and `pct_from_high_252` — two of the
candidates that rule would have dropped — are the exact two factors
`AGENTS.md`'s grid-offset section records as 0/40 sign flips in the old
panel, the most stable measurements this project has produced, and
section 8 of the physics write-up attributes most of the realized
portfolio edge to a low-vol/quality tilt. A t-stat computed on 13 years of
this data was also just shown (the odd/even split-half check) to not
reliably order factors by true IC. A post-hoc threshold chosen after
seeing the t-stats, applied to the same data used to compute them, and
then evaluated once more on that same nomination era, is exactly the
27%-of-zero-signal-configs-beat-the-market failure mode Round 12 already
calibrated. **`FACTOR_SIGNS` is not touched by this correction round.**
Every test below is a variant reported beside the confirmed 8-factor
baseline (`cap150_raw`, `decile_volq`, already in `REPORT_nominate.md` —
not rerun), matching how every other alternate view in this project is
handled (`topn_ew` beside `decile_volq`, `xrank` beside `q75`,
`blend_q75.py` as its own script) — never a replacement computed in
place.

**Trial count: 3 backtest variants + 1 factor screen (not a backtest).**
Written down before any of the four run.

1. **`decile1_volq`** — identical construction to the confirmed
   `decile_volq` (top decile within each of 5 trailing-vol quintiles,
   inverse-vol weighted) except it selects **decile 1** (the second-from-
   bottom decile) instead of decile 9 (the top). Directly tests section
   6's finding that decile 1's pooled mean forward return (+1.92%) was
   numerically above decile 9's (+1.78%) on the exact same scores — same
   book size, same weighting, same universe, same dates; only which
   decile is selected changes.
2. **`exclude_bottom_decile`** — within each vol quintile, hold every
   name EXCEPT the bottom composite-score decile (inverse-vol weighted
   across the remaining ~90%). Tests section 6's other reading directly
   ("the model's information is in what to avoid, not what to buy").
   **Disclosed as not apples-to-apples on book size or turnover** — this
   holds roughly 9x the names the confirmed construction does, which by
   itself changes variance-drag and diversification characteristics
   (Round 15/18's own finding for the old model) independent of any
   selection effect. Reported with that caveat attached, not as a clean
   isolation of scores from construction.
3. **`asset_growth_dropped`** — the confirmed 8-factor composite minus
   `asset_growth` (7 real factors), same `decile_volq` (top-decile)
   construction as the baseline. A drop, never a sign flip — flipping
   would fit the sign to the exact data used to validate it; dropping
   only removes a term whose measured sign contradicts its own citation
   in this universe, without asserting a new sign in its place.
4. **`book_to_market` factor screen, IC only, no portfolio.** Built from
   `sf1_fundamentals.parquet`'s existing `equity` (book value, ARQ/ARY,
   filed-date keyed, same as `assets` in `quality_factors.py`) divided by
   the panel's own point-in-time `market_cap` — zero new data pull, same
   merge_asof-with-row-position-assertion pattern
   `quality_factors._asof_value` already uses. Screened for pooled
   Spearman IC + NW t + split-half stability on cap150, 2007-2019, the
   same measurement `model_audit.py` already applies to every other
   factor. **Not added to any composite, not backtested as a portfolio,
   not promoted** — Novy-Marx 2013's own framing (already cited for
   `gross_profitability`) motivates checking it, and this is the cheapest
   possible check, but promoting a 9th (10th) real factor into a traded
   composite is a modeling decision `AGENTS.md` reserves for Gabe.

All four run on cap150 (the confirmed tier), raw (not sector-neutral, to
match the named selection), nomination era only (2007-2019 — 2020-2026
remains spent), 15bp round-trip cost, 40 grid offsets, using the
already-verified `outcome_cache.parquet`. Matched-null draws reduced from
100 to 50 per cell for the three backtest variants (a runtime concession
for a diagnostic pass, not a methodology change — the null's role here is
a sanity floor, not a formal significance claim, so halving the draw
count does not change what any of these three tests can or can't
conclude).

Output: `final/out/reset2026/correction_variants_report.json` and
`final/models/2026-09-22-composite-model-corrections.md`.

## Second hold-out spend (2026-09-22, part 3) — explicit, at Gabe's request

2020-2026 was already spent once for this pipeline (see the hold-out
result section above: `cap150_raw`/`decile_volq` confirmed +1.85%/yr,
passed its pre-registered gates, then failed leave-one-year-out). Every
section since has said, correctly, that nothing new gets confirmed on it
again. Gabe asked directly, after being told exactly that caveat, to see
the hold-out numbers for `asset_growth_dropped` anyway. That is his call
to make (`AGENTS.md`: modeling decisions are his), and it is recorded
here as a second, deliberate spend rather than a quiet one.

**Scope, to keep this one number rather than a second search:** only
`asset_growth_dropped` is run on 2020-2026 — not `decile1_volq`,
`exclude_bottom_decile`, or a fresh confirmation of the baseline (already
on file in `REPORT_holdout.md`). Running all four would turn a requested
number into a four-cell hold-out search, which is a different and much
weaker statistic than the one asked for.

**This is descriptive, not a confirmation.** Nothing about
`asset_growth_dropped`'s hold-out result changes its status: it remains
an unadopted recommendation, scored once on data it was never
pre-registered against, reported beside the baseline's own hold-out
result (+1.85%/yr, 39/40 offsets positive, 98th percentile, but 2/7 years
positive and LOYO-negative on dropping 2020) with the same leave-one-year
-out check applied, not a bare aggregate number.

Output: `final/out/reset2026/holdout_asset_growth_dropped_report.json`.

## Factor-set decision (2026-09-22) — Gabe's call, made

`asset_growth_dropped` is adopted. `composite.py`'s `FACTOR_SIGNS` no
longer includes `asset_growth` as of this commit. This is a modeling
decision (`AGENTS.md`: those are Gabe's), made after seeing:

- The wrong-sign finding (`asset_growth` IC +0.0105 vs. assigned -1,
  stable across both halves of the nomination era —
  `2026-09-22-composite-model-physics.md` section 3).
- The single pre-registered ablation testing exactly this (drop, never
  flip): +3.75%/yr -> +4.32%/yr excess vs SPY on the confirmed
  `cap150_raw`/`decile_volq` cell, LOYO-clean, 40/40 offsets positive,
  harness-verified against `run_backtest.py` on the unmodified 9(8)-factor
  cell before trusting the delta (`2026-09-22-composite-model-
  corrections.md` sections 3 and 6a).
- The disclosed cost: offset-to-offset dispersion rose (sd 0.55% vs.
  0.37%), and the hold-out comparison is uninformative either way (both
  the baseline's and this variant's hold-out results are dominated by
  single-ticker concentration in 2020 — GME real, LCID real, see sections
  6c/6d of the same document — not evidence for or against this specific
  change).

**What this does NOT do**: it does not re-confirm anything on 2020-2026
(still spent), and it does not re-run the 40-offset/100-null nomination
sweep under the NEW 8(7)-factor definition — `REPORT_nominate.md` and
`REPORT_holdout.md` still describe the prior 9(8)-factor composite and
are stale as of this commit. `correction_variants_report.json`'s
`asset_growth_dropped` entry is, from this point on, simply *the*
confirmed nomination-era number for `cap150_raw`/`decile_volq`, not a
variant beside a different baseline. Regenerating the full six-cell
report under the new factor set (`run_backtest.py --era nominate` +
`aggregate_report.py`, ~33 min) is a reasonable next step if a clean,
canonical `REPORT_nominate.md` matching the new `FACTOR_SIGNS` is wanted,
but is not required to treat this decision as in effect — the ablation's
own dedicated 40-offset run already is that confirmation, run on the
exact same construction and cost assumptions the six-cell report uses.

## Live forward-prediction ledger (started 2026-09-22) — pre-registered
## before any outcome exists

Per Gabe's request for a theoretical model whose predictions can actually
be tested, without spending 2020-2026 again: every day in that window has
already been analyzed multiple times today, so there is no unspent day
left inside it. The only genuinely clean test is real calendar time that
has not happened yet.

`prediction_ledger.py record`, run 2026-09-22, committed predictions for
**every eligible cap150 name** (2,214 tickers, not one — a single
ticker's outcome has no statistical power) on the panel's most recent
cross-section, **2026-09-08**, verified beforehand to have 0% realized
`forward_return_tradable_40` coverage (the 40-trading-day-forward outcome
does not exist in the data at all yet — confirmed for every date after
late July 2026). Two predictions per name, per Gabe's steer that ranking
matters more than a noisy point estimate but both are worth having:

1. **Rank / percentile** by composite score (`asset_growth_dropped`,
   `composite.FACTOR_SIGNS` as of this commit) — the primary, robust
   prediction.
2. **A calibrated relative-return forecast**, `slope x (S_i - mean(S))`,
   using the Fama-MacBeth slope estimated on nomination-era data only
   (0.00433, 3,272 dates, causal, never touches 2020+). Deliberately
   de-meaned — the model has no view on the market's absolute return
   (the physics audit's own finding: IC is a within-date, market-neutral
   quantity), so the point forecast is scoped to what the model actually
   claims to know.

Written to `out/reset2026/prediction_ledger.csv`, one immutable row per
ticker, with both the panel date and the real wall-clock timestamp this
was recorded — the record that proves this was committed before the
outcome existed. `prediction_ledger.py selftest` validates the scoring
arithmetic against already-known nomination-era dates first (single-date
IC ranges from -0.11 to +0.27 across 5 arbitrary dates picked for this
check — noisy, not buggy, and itself a demonstration of why one date
proves nothing and the ledger needs to accumulate many).

**Gate, stated now, before any score exists**: `prediction_ledger.py
score` becomes meaningful only once ~40 trading days have passed AND
Gabe has pulled fresh price data past 2026-09-08 (this sandbox cannot
refresh `td_data_sharadar`/`composite_panel.parquet` itself — see
`AGENTS.md`'s reproduction table). No number from this ledger is to be
read as a confirmation on fewer than several independently-scored dates
— the single-date noise range above is the reason. Re-run `record` at
each future rebalance (roughly every 40 trading days, or opportunistically
whenever fresh data lands) to keep building the track record; run `score`
any time after to catch up whichever dates have matured.

## Ledger versioned (2026-09-22, same day) — market-beta term added

Superseded within hours by the model's first structural extension (see
`2026-09-22-composite-model-corrections.md` section 9). The point forecast
above was calibrated on raw returns; `beta_diagnostic.py` then showed
scoring against beta-adjusted (market-model abnormal) returns sharpens
the measured IC (t 2.53 -> 4.25) rather than weakening it, so the
calibration changed to match. **The v1 ledger entry above
(`prediction_ledger.csv`, panel_date 2026-09-08) is frozen, not
retroactively edited** — a live commitment doesn't get upgraded after
the fact. A new entry for the same panel_date, same 2,214 names, under
the new beta-adjusted spec, was written to `prediction_ledger_v2.csv`
immediately after. Every `record`/`score` invocation from here forward
targets v2. See the corrections doc section 9 for the full diagnostic
evidence and the exact schema change.

## Two more pre-registrations (2026-09-22), before running either

Per Gabe's "go ahead" (Amihud) and "I agree, continue" (regime
conditioning) on the two remaining structural-gap proposals.

**Amihud illiquidity (`build_amihud_feature.py`).**
`amihud_20 = trailing-20-day mean(|daily return| / (closeunadj*volume))`,
same window/basis convention `downcap_universe.py` already uses for its
liquidity floor. Hypothesized sign **+1** (illiquidity premium, Amihud
2002) — a candidate, screened for pooled Spearman IC (cap150, nomination
era, same methodology as every other candidate this session) before any
promotion decision. One trial. Not added to `FACTOR_SIGNS` regardless of
sign unless the measured direction matches the hypothesis and the
decision is made explicitly, matching how every other promotion this
session was handled (drop-only for wrong-signed factors, never flip).

**Regime-conditioning diagnostic (staged, per Gabe's explicit steer not
to repeat the HMM's fitted-parameter mistake).** Regime variable: trailing
60-day realized SPY volatility (reusing the existing `volatility_60`
window convention). Split rule: **causal expanding-window median** of
that series — a parameter-free split (no percentile chosen by looking at
results; the median is the least-arbitrary binary threshold available).
Two hypotheses, both already cited in the physics audit, both directional
and pre-specified before measurement:

1. `momentum_12_1`'s IC should be weaker (or negative) in the high-vol
   half (Daniel-Moskowitz momentum-crash mechanism).
2. `volatility_60`'s IC should be stronger (more negative, i.e. the
   low-vol premium more pronounced) in the high-vol half (flight-to-
   quality / institutional-constraint literature).

**Staged, not a single leap to a new traded variant**: first, screen both
factors' pooled IC separately in the high-vol and low-vol halves
(zero new parameters — a split-sample measurement, not a new rule). Only
if BOTH hypotheses hold in the predicted direction does this proceed to
step 2: a single, pre-registered conditional-composite variant (exclude
`momentum_12_1` from the composite when in the high-vol regime, binary
on/off, no continuous scaling parameter to avoid inventing a tunable
magnitude) backtested once, nomination era, cap150, same construction as
the confirmed baseline. If either hypothesis fails, stop at the
diagnostic stage and report the negative — consistent with this
project's standing practice of reporting well-powered negatives as
real results, not silently dropping them.

Output: `out/reset2026/amihud_feature.parquet`,
`out/reset2026/regime_diagnostic_report.json`.

## IC-shrinkage weighting (2026-09-22) — pre-registered before running,
## per advisor consult

Per Gabe's reframe: the objective is rank prediction, not return
magnitude, which makes pooled IC the objective itself, not a diagnostic.
An advisor consult before implementing pointed at the one lever already
measured and left unpulled this session: equal weighting sits at cosine
similarity 0.47 from the IC-implied (Grinold-Kahn) optimum
(physics doc section 4), and `gross_profitability` alone (IC +0.041,
t 5.58) outscores the full equal-weighted composite (IC +0.026-0.032) —
dilution has a measured, non-trivial cost.

**Exactly one rule, written down before any result exists:**

```
w_k_raw = max(FLOOR, |t_k| - 1)     FLOOR = 0.1 (no factor goes to exactly
                                     zero -- shrinkage, not hard selection)
w_k     = sign_k * w_k_raw / sum_j(w_j_raw)
```

`t_k` is each factor's pooled Spearman-IC Newey-West t-stat, computed the
identical way `model_audit.py` already does it. `short_interest_days_to_
cover` (zero nomination-era coverage) gets the floor weight by
definition (undefined `t`), same as any other minimally-supported factor
— not specially excluded. This is a **measurement-informed shrinkage
weight, not a fitted parameter** in the sense this project has
disqualified before: it is not a grid search over weight vectors chosen
to maximize a backtest, it is one pre-specified functional form of one
already-measured statistic, applied once.

**The honest caveat, stated before running**: fitting weights on
nomination-era IC and measuring IC on the same nomination-era data is
in-sample by construction and would only show "how much signal dilution
costs," not "the new weights forecast better." To get a genuine
out-of-sample read, **weights are fit on odd calendar years and IC is
measured on even years, and vice versa** (the same odd/even split this
package already uses for factor-stability checks) — two genuinely
held-out results, not one in-sample number.

**Metrics**: pooled Spearman IC (existing machinery) AND Kendall tau,
both with Newey-West t, on both raw (`forward_return_tradable_40`) and
beta-adjusted returns (reusing `beta_feature.parquet` — the beta work
already showed this sharpens the read, t 2.53->4.25 on the equal-weight
composite). Portfolio CAGR is not computed here — per Gabe's explicit
reframe, rank accuracy is the target this round, not dollars.

**Ruled out before running, per the advisor's explicit caution**: no
re-opening of Amihud/regime/value (all three produced clean negatives
this session); no new candidate factors before this question is settled;
no comparison of multiple weighting rules against each other (one rule,
one run). `FACTOR_SIGNS` and the confirmed `compute_composite` are NOT
modified — this is scored as a side-by-side variant
(`compute_composite_ic_weighted`), same pattern as every other
comparison this session.

Output: `out/reset2026/ic_weighted_composite_report.json`.

A bug was found and fixed in `compute_weighted_score` after the first
results existed (missing renormalization by available weight when a
factor is absent for a given row) — the whole script was re-run to
confirm the fix before trusting any number; every value moved by less
than 0.0003. See corrections doc section 12 for the full account.

## Ledger versioned again (2026-09-22) — IC-weighted model added

v1 and v2 (panel_date 2026-09-08 each) stay frozen. The IC-weighted
model's score/rank is added as new columns (`ic_weighted_score`,
`ic_weighted_rank_pct`) alongside the existing equal-weight ones, so a
new file (`prediction_ledger_v3.csv`) starts rather than corrupting v2's
header. A new blind entry was recorded for the same panel_date
(2026-09-08, 2,214 names) with both models' predictions in one row per
ticker. Going forward, this schema is meant to be **extensible** — a
future model addition should add columns here, not trigger another
version bump, unless it changes what an existing column means.

## Trial-count ledger and next round (2026-09-22), per advisor consult
## before running

**Running trial count against the nomination era, written down before
this round runs, per the advisor's explicit flag**: `asset_growth`
ablation (1) + `decile1_volq` (1) + `exclude_bottom_decile` (1) +
`log_market_cap` screen (1) + `momentum_1_1` screen (1) + `book_to_
market` screen (1) + Amihud screen (1) + regime diagnostic (1, stopped
before a backtest) + IC-shrinkage weighting (1) = **9 trials before this
round**. This round adds up to 4 more (3 factor screens + 1 exponent
variant) = **13 total**. Written here so the count exists before results
do, not reconstructed after.

**Exponent transform (technical correction from advisor, important
enough to restate): Spearman rho is invariant to any monotonic transform
of the FINAL composite score** — raising the finished score to a power
changes nothing about its rank correlation, by construction. The only
place an exponent can matter is applied to EACH FACTOR'S signed rank
BEFORE the weighted sum, where it changes how factors trade off against
each other and can therefore reorder the composite. Rule, fixed in
advance: `signed_rank_k -> sign(r) * |r|^p`, **p = 2, one value, no
sweep**, applied per-factor, then combined with the existing IC-shrinkage
weights exactly as now. Justification is a prior finding, not a search:
the decile table (physics doc section 6) showed the composite's
information concentrated at the bottom of the score range with a flat
middle; p > 1 is the transform that lets extreme factor values dominate
the weighted sum instead of being averaged against an uninformative
middle.

**Three new candidate factors, one screen each, IC only, split-half
(odd/even years) exactly as `book_to_market`/`log_market_cap` were
tested** — all built from columns already in `sf1_fundamentals.parquet`
(no new data pull):

| factor | formula | sign | citation |
|---|---|---:|---|
| `fcf_yield` | `(ncfo + capex) / market_cap` (capex already negative in this data, confirmed 88.8% of ARY rows) | **+1** | Novy-Marx/value literature: cash generation predicts returns |
| `leverage` | `debtnc / assets` (both stock/level concepts, backward asof, same pattern as `assets` in `quality_factors.py`) | **-1** | Campbell, Hilscher & Szilagyi 2008 (distress risk anomaly: high-distress firms earn LOWER, not higher, returns) |
| `profitability_trend` | YoY change in `opinc/revenue` (same 365-day-lookback pattern as `asset_growth`) | **+1** | fundamental/margin momentum literature |

`rnd_intensity` is explicitly NOT re-added — Round 13 already established
it dies under sector-neutralization (a sector bet), and this project's
own standing rule is not to relitigate closed methodology calls.

**Expectation, stated before running, per the advisor's explicit
caution**: rho 0.03-0.05 at a 40-day horizon in liquid equities is close
to what published cross-sectional signals typically achieve, not a
limitation of this factor set specifically. Three more fundamentals
ratios added to a composite already dominated by `gross_profitability`
should be expected to move rho by low single-digit thousandths, if at
all — a null result here is not a surprising one.

**Also requested, to run after the above**: a portfolio-return-vs-SPY
breakdown by market regime, for the confirmed IC-weighted composite.
Framed by Gabe as lower-risk than a fitted model's equivalent check
("purely theoretical, not based on fitted values") — a fair distinction
(no parameter search over this data occurred; the weights are a fixed
function of a measured statistic) but not a different rule about
*which era* to look at. **Regimes defined externally, not chosen after
seeing results**: (a) each nomination-era calendar year classified by
SPY's OWN realized return that year (up >+10%, down <-10%, flat
between) — a fact about SPY, not chosen by inspecting the composite's
performance; (b) high/low realized-volatility regime, reusing the exact
causal expanding-median split already built for the regime diagnostic
above (`amihud_and_regime_diagnostic.py`), not a new threshold. Both
computed on the **nomination era only** — this does not reopen or
re-spend 2020-2026.

Output: `out/reset2026/new_factor_screens_report.json`,
`out/reset2026/exponent_variant_report.json`,
`out/reset2026/regime_backtest_report.json`.

## Turnover realism + third hold-out spend (2026-09-22), pre-registered
## before running

Per Gabe's caveat review: (1) scoping out factor-concentration/risk-model
concerns as out of interest (theoretical validity only, not investor
safety) -- caveats 1 and 3 from the corrections doc's caveat review are
not pursued further; (2) a direct request to test the IC-weighted model
on 2020-2026, on the correct grounds that frozen (non-refit) weights make
that test closer to honest than a fresh search would be; (3) two
turnover-realism constructions.

**Third hold-out spend, scope stated before running**: `IC-weighted
composite`, `decile_volq`, cap150, 15bp, 2020-2026, **purpose is data-
quality/generalization robustness, not discovery** -- this model's
weights are frozen from nomination-era measurement and are not being
re-fit to whatever this shows. Leave-one-year-out applied immediately on
the result, same standing check as every other hold-out number in this
package (the 2020-concentration failure is the most likely outcome and
is checked for explicitly, not only reported if it appears favorable).

**Two turnover constructions, tested separately, both using the
IC-weighted score, cap150, nomination era**:

1. **Laddered/staggered**: 5 cohorts at offsets 0/8/16/24/32 (evenly
   spaced across the 40-day cycle), 20% of capital each, blended by
   summing each cohort's own independently-compounding terminal wealth.
   **Prediction, stated before running**: smooths offset-to-offset timing
   luck and reduces the variance/concentration risk this session already
   found (2020, GME/LCID), but should NOT reduce total annual dollar
   turnover -- the whole book still rotates once per 40-day cycle either
   way, just staggered in time.
2. **Buffer/hysteresis band**: a name already held stays unless it falls
   out of the top 20% (by IC-weighted score, within its own vol quintile)
   rather than being re-picked from a strict top-decile cutoff every
   window; new entries still require top-decile. **20%/10% is one fixed,
   asymmetric, round-number choice, declared here, not swept.** Requires
   sequential (state-carrying) simulation, single offset (0), since this
   construction is path-dependent in a way the ladder isn't.

**Beta remedy**: replace the flat 252-day rolling-window beta with an
EWMA (RiskMetrics-convention 0.94 daily decay) covariance/variance
estimate -- a standard, off-the-shelf convention (same status as the
252-day window itself), not a parameter fit to this backtest. Re-run the
beta diagnostic (composite-vs-beta correlation, raw vs. beta-adjusted IC)
to check whether this changes the picture.

**Explicitly deferred, per effort triage**: the shrinkage-constant
sensitivity check (floor/offset robustness) is the least likely of the
five items this round to change any conclusion and is not run this
round.

Output: `out/reset2026/holdout_ic_weighted_report.json`,
`out/reset2026/turnover_realism_report.json`,
`out/reset2026/ewma_beta_diagnostic_report.json`.

## Era-transfer + AV option factors (2026-09-22, alpha-vantage-spin branch) — pre-registered before any result exists

Gabe's request: integrate the new data, then "use the older data as training
data and the former training data as test data", and "integrate the new data
into the model". Written before `era_transfer.py` has produced a single
number; the smoke test on the first 3 landed dates reports plumbing only.

**Relationship to the factor-composite-audit worktree.** That session's
IC-shrinkage rule (`w_k = sign_k * max(0.1, |t_k| - 1) / Σ`, `t_k` = pooled
Spearman-IC Newey-West t, lag 39) and its 8-factor set (`asset_growth`
dropped) are reused verbatim. Nothing here re-opens its conclusions. The
2007-2019 era is where the factor list and construction were chosen, so a
test there validates the transferred WEIGHTS, not the design — stated once,
not argued.

**Universe.** `downcap_universe_v2.parquet`: the v1 liquidity floor multiplied
split-adjusted volume by unadjusted price, which (a) admitted later-splitting
names early and (b) excluded 1,144 later-reverse-splitting names (+527k
cap150 rows). All v1 cap500/cap150 results in this package carry that
look-ahead; whether to re-run them is Gabe's call. Named check: AAPL Jan-2008
20d median $ volume = $5.8-9.4B/day (v2), vs $162B (v1).

### Experiment A — weight transfer (train old, test newer)
- TRAIN: 1998-12 .. 2006-12 (needs the Sharadar backfill; blocked on
  SHARADAR_API_KEY). Until it lands, only 2005-2006 exists — too short
  (~12 non-overlapping windows); A does not run on it.
- Fit `t_k` on TRAIN, freeze `w`. TEST: 2007-01 .. 2026-08, all 40 offsets.
- Compared, on identical TEST name-dates: equal weights; TRAIN-fit weights.
  (PRODUCTION_WEIGHTS were fit on 2007-2019 and are in-sample there; they are
  reported only on 2020-2026, where both are out of sample.)
- **Adoption rule, fixed now:** TRAIN-fit weights replace equal weights only
  if the per-date IC difference (TRAIN-fit minus equal) has NW t >= 2.0 on
  TEST and is positive in >= 2/3 of TEST years (LOYO-style). Otherwise equal
  weights stand. `short_interest_days_to_cover` has no pre-2020 data and gets
  the floor weight, as in the audit rule.

### Experiment B — AV option factors
Nominate 2008-01 .. 2018-12 (all new AV data), confirm 2019-01 .. 2026-08.
Only `av_monthly` rows are used (weekly = down-cap only; DoltHub = different
IV source starting exactly at the split — either would confound).
Candidates and signs, fixed now, each from a published anomaly:

| factor | definition | sign | source |
|---|---|---:|---|
| `opt_cw_spread` | OI-weighted call-minus-put IV, matched strikes | +1 | Cremers & Weinbaum 2010 |
| `opt_rr25` | IV(-25d put) - IV(+25d call), ~56 DTE | -1 | Xing, Zhang & Zhao 2010 |
| `opt_os_ratio` | 100 * option volume / 20d median share volume | -1 | Johnson & So 2012 |
| `opt_pc_vol_ratio` | put / (put+call) volume (proxy; P-P used open-buy volume) | -1 | Pan & Poteshman 2006 |
| `opt_vrp` | ATM IV - volatility_60 * sqrt(252) | -1 | Bali & Hovakimian 2009 |

k = 5. Liquidity columns (`opt_log_oi`, `opt_log_vol`, `opt_spread_atm`) are
NOT factors — conditioning/cost inputs for the thin-liquidity test only.
- **Screen (nominate era):** pooled Spearman IC, NW t, sector-neutral and raw,
  on matched name-dates (rows with the option factor present). Holm-corrected
  at 0.05 across k=5 on the sector-neutral t, AND sign must match the table.
- **Admission (nominate era):** composite+factor vs composite on the SAME
  optionable name-dates; improvement in pooled IC must beat the 80th
  percentile of a within-date shuffle null of the candidate (20 draws).
  Every monthly date is used (no 40-day subsampling), so the grid-offset
  problem does not arise; stated so it is not assumed.
- **Confirmation:** admitted factors only, frozen, on 2019-01 .. 2026-08: IC
  difference positive with NW t >= 1.5 and LOYO no sign flip. One shot.

### Amendment 1 (same day, before any Experiment A/B number exists): tier
**The cap500/cap150 panel is a survivorship-selected sample.**
`composite_panel.parquet`'s feature grid is `features_*_sharadar_pit.parquet`,
built only for the 4,011 tickers that were cap2000-eligible at SOME date in
2005-2026. So a small company is in the cap150 tier only if it was, or later
became, a $2B company. Measured (descriptive, prices only, monthly samples,
SPACs excluded):
- 52% of cap150-only panel rows belong to names that reach cap2000 only LATER
  (future winners); 894k rows are fallen angels; names that were never large
  are absent entirely.
- v2 cap150-only rows outside the grid: 5.09M rows, 1.2% SPAC; 4,598 non-SPAC
  tickers, spread evenly over 2005-2026.
- 40-day forward return, cap150-only, in-grid minus out-of-grid: +3.03% per
  window (~+19%/yr), positive in 92% of 256 months, t 17.0. Out-of-grid names
  delist within 40 days at 4x the rate (1.31% vs 0.31%).
The share of future-winner rows rises as the cap floor falls (0 at cap2000),
which reproduces the "monotonic in cap" pattern by construction. Every
cap500/cap150 result in this package, and the audit worktree's cap150
IC-weighted hold-out, is conditioned on future success and unreadable until
re-run on a complete grid. cap2000 is clean: every cap2000-eligible
name-date is inside the grid.

**Therefore: Experiment B's primary tier is cap2000.** cap500/cap150 wait for
a rebuilt grid (union of v2 cap150 tickers; prices from panel/stocks, no key;
SF1-based factors need the Sharadar key). `era_transfer.py` refuses any tier
where < 99% of v2-eligible rows are present in the panel. The cap2000 run
does NOT test the thin-liquidity hypothesis. All other thresholds unchanged.
