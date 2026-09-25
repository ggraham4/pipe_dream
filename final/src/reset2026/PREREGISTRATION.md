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
combination step. `insider_cluster_recent` and the `opt_*` options-implied
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
