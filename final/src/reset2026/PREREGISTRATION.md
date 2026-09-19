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
- **neutral** — each factor residualized cross-sectionally on
  {sector, log market cap, `volatility_60`} (reusing `sweep/factors.py`'s
  design, sector map from `tickers_master` — current-day classification, the
  same declared limitation Round 13 already carries) BEFORE rank-transforming
  and combining. If `raw` shows excess return that `neutral` does not, the
  edge is a sector/size/vol bet, not stock selection, per Round 13's own
  finding on the deployed model.

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
1-trading-day lag, 50bp round-trip cost — same conventions as
`execution.py`/`portfolio.py`. No stop-loss (Round 13: the model this project
already has does not need one to be readable, and it is one more knob this
reset is deliberately not adding back).

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
