# The factor-composite reset — full write-up and reproduction guide

**2026-09-19. Written for a human colleague or a future AI assistant with
zero context on this project.** If you're an LLM picking this up cold: read
this whole document before touching any file, then follow "Reproducing this
from scratch" section by section, in order. Do not skip the survivorship-bias
audit section even if you're in a hurry — the entire history of this project
(see `AGENTS.md`'s Round 9-11 sections) is a record of backtests that looked
great and were later found to be measuring bugs, and the discipline below is
what caught this pipeline's own before it shipped.

---

## 1. Why this exists

On 2026-09-18, the project's owner (Gabe) decided to restart the core
stock-picking model from scratch after 19 rounds (documented in `AGENTS.md`)
of feature/model sweeps on a 25-column XGBoost pipeline kept returning null
or unreadable results. The diagnosis: the model had too many degrees of
freedom to distinguish real signal from noise (ten single-knob variants of
the deployed model spanned -8% to +9%/yr excess return just from
hyperparameter noise), the feature-mining was reinventing OHLCV transforms
that kept coming back null, and the $2B+ market-cap floor was capping the
number of independent bets available (Round 15: effective breadth ≈16
regardless of book size).

Three changes were approved, in this order:
1. Replace the high-DOF model with a **sign-constrained linear composite**
   — a handful of factors, combined with fixed signs and no fitted weights.
2. Build factors from **published, mechanism-backed anomalies**, not new
   transforms of price/volume data.
3. **Lower the market-cap floor** to access more names and more independent
   bets.

This document covers the pipeline built to implement that decision, its
results, an audit for the exact bug class (survivorship bias) that has
burned this project twice before, and how to reproduce or extend it.

**Everything here lives in git**, branch `worktree-factor-composite-reset`
(a worktree off `main`), under `final/src/reset2026/`. Read
`final/src/reset2026/PREREGISTRATION.md` alongside this document — that file
is the dated, append-only pre-registration (spec written before each result
was seen, amendments and the final verdict added in their own commits,
never edited after the fact). This document is the narrative; that one is
the record.

---

## 2. The model, precisely

### 2.1 Universe

Three point-in-time market-cap tiers, built in `downcap_universe.py`:

| tier | market-cap floor | liquidity floor |
|---|---|---|
| `cap2000` | $2B (reproduces today's deployed floor exactly) | `closeunadj > $10` |
| `cap500` | $500M | trailing 20-day median dollar volume ≥ $500k |
| `cap150` | $150M | trailing 20-day median dollar volume ≥ $250k |

All floors are evaluated **as of each historical date**, using
`closeunadj` (Sharadar's split-unadjusted close) for the price/liquidity
checks — never split-adjusted `close`. This matters: a $10 floor applied to
split-adjusted close is look-ahead (it would have excluded Apple from the
2008 universe at $5.98 adjusted vs. its real $167 traded price, purely
because Apple split years later — this exact bug was found and fixed in this
project's Round 11). Dollar volume at the two lower tiers replaces the price
floor because a bare price floor doesn't mean much for a $150M company —
real tradability does.

### 2.2 Factors — 9 total, signs fixed before any score was computed

| factor | sign | source | citation |
|---|---|---|---|
| `momentum_12_1` (12-month return, skip the most recent month) | + | new, built here | Jegadeesh & Titman 1993 |
| `pct_from_high_252` (proximity to 52-week high) | + | existing panel column | George & Hwang 2004 |
| `volatility_60` (trailing realized vol) | − | existing panel column | Ang, Hodrick, Xing & Zhang 2006 |
| `gross_profitability` = gross profit / total assets | + | new, built here | Novy-Marx 2013 |
| `accruals` = (net income − operating cash flow) / assets | − | new, built here | Sloan 1996 |
| `asset_growth` (YoY change in total assets) | − | new, built here | Cooper, Gulen & Schill 2008 |
| `net_issuance_pct` (YoY change in shares outstanding) | − | existing (built 2026-09-17, Round 20) | Pontiff & Woodgate 2008 |
| `days_to_next_filing_seasonal` (days to the next expected earnings filing, seasonal/cadence estimator — provably causal, not the unverifiable "actual next date" variant) | − | existing (Round 16) | Frazzini & Lamont 2007 (earnings announcement premium) |
| `short_interest_days_to_cover` | − | existing | Boehmer, Jones & Zhang 2008 |

Every factor is a **named, published anomaly with a citation**, not a
home-grown transform of OHLCV data — the second of the three approved
changes, applied literally.

### 2.3 Combination — genuinely zero fitted parameters

For each rebalance date, each factor's values across the eligible universe
are rank-transformed to `[-0.5, +0.5]` (robust to outliers, handles missing
values as "no opinion" rather than crashing), multiplied by its fixed sign,
and averaged across whichever factors that name actually has data for. No
regression, no gradient descent, no hyperparameter — the entire "model" is
nine signs and an average. See `composite.py:compute_composite`.

A second variant, `neutral`, residualizes each factor on **sector dummies
only** (not size or volatility — volatility is itself factor #3, so
residualizing it on itself would be degenerate) before combining. Comparing
`raw` vs. `neutral` is the test for "is this just a sector bet" — the exact
question this project's Round 13 answered YES to for the deployed model.

### 2.4 Portfolio construction — two variants tested side by side

- **`decile_volq`** (the one actually confirmed): split the eligible
  universe into 5 trailing-volatility quintiles, take the top decile by
  composite score from each, weight inverse-volatility. Mirrors the
  deployed model's own construction. Averages ~200 positions from a ~2,000-
  name universe at the `cap150` tier.
- **`topn_ew`**: flat top 5% of the universe by composite score,
  equal-weighted (~100 positions). Exists specifically to check whether
  `decile_volq`'s result depends on the volatility-quintile bucketing. It
  does — see section 3.

### 2.5 Execution

Every position is realized through `execution.py` (`realize_position`),
**imported, not reimplemented** — this is the project's own already-verified
engine (Round 9), so entry lag (next day's open, 1-day lag), the delisting
exit floor (exit at the last available price rather than dropping a name
that stops trading mid-hold), and the turnover-aware cost model
(`apply_turnover_costs` — a position pays a spread only on an actual entry
or exit, not on every window it's simply held through) all come from code
this project already trusts, not a fresh copy of the arithmetic. Cost is
reported at both 15bp round-trip (the file's own current default) and 50bp
(a stress case). Hold is a fixed 40 trading days, non-overlapping, no
stop-loss.

**A vectorized shortcut, verified, not assumed.** Rather than calling
`realize_position` 12 million times, `build_outcome_cache.py` computes the
identical formula for the no-stop case in one array operation per ticker
(`entry_idx = i+1`, `exit_idx = min(i+40, n-1)`, exactly matching what
`realize_position` computes internally), then **verifies 300 random
samples against a direct call to the real function** — 0 mismatches. This
is the "expensive half once, reuse everywhere" pattern the project's own
`sweep/outcomes.py` established for the old model, applied here to a
no-fit composite instead of a per-cell XGBoost retrain.

### 2.6 The grid-offset problem, and averaging over it

A 40-day non-overlapping window backtest has 40 equally valid starting
offsets, and this project already found (`check_grid_offset.py`) that
weak features flip sign depending on which one you happen to use. **Every
number in this write-up is averaged across all 40 offsets**, not offset 0 —
the "durable fix" this project's own `RUNBOOK.md` flagged as not yet
implemented, implemented here.

### 2.7 Matched null

For every real portfolio draw, 100 "null" draws repeat the exact same
construction (same universe, same bucketing, same weighting) with the
composite scores permuted within each date — same marginal distribution,
cross-sectional information destroyed. The real result is reported as a
percentile against this null, not as a bare "beats SPY."

---

## 3. Results

Full numeric tables: `final/out/reset2026/REPORT_nominate.md` and
`REPORT_holdout.md`. Summary:

### 3.1 Nomination era (2007-2019), 40-offset average, net of 15bp cost

| universe | excess CAGR vs SPY | vs USMV | offsets positive | survives sector-neutral? |
|---|---|---|---|---|
| $2B+ (today's floor) | +1.09%/yr | -0.10%/yr | 37/40 | **No** (-0.32%/yr neutralized) |
| $500M+ | +3.03%/yr | +1.22%/yr | 40/40 | Yes (+2.63%/yr) |
| **$150M+** | **+3.75%/yr** | **+1.86%/yr** | **40/40** | **Yes** (+3.47%/yr) |

Three things make this readable rather than another false positive:
1. **Monotonic in how far the cap floor comes down** — exactly what
   "breadth was the missing lever" (Round 15) predicts, not an assumption.
2. **Survives sector-only neutralization**, losing 0.3pp — the deployed
   model, tested the identical way in Round 13, lost essentially all of it
   (2.80x → 0.77x, the exact center of its own null).
3. **Survives leave-one-year-out.** Dropping any single year — including
   2008, the single largest contributor at +11.78% — never takes the
   13-year mean below +2.1%/yr.

### 3.2 Hold-out (2020-2026) — the one confirmed run

`cap150_raw` / `decile_volq`, confirmed exactly once per the
pre-registration: **+1.85%/yr excess vs SPY, 39/40 offsets positive, 98th
percentile of its own matched null.** By the letter of every gate in this
package, that passes.

**It fails leave-one-year-out — the one check that isn't relaxed.** Year by
year: 2020 +23.98%, 2021 -5.60%, 2022 +11.98%, 2023 -9.91%, 2024 -4.39%,
2025 -7.32%, 2026(partial) +2.94%. Only 2 of 7 years are positive. Dropping
2020 alone flips the mean to **-2.05%/yr**. Dropping both 2020 and 2022:
**-4.86%/yr**. This is the identical failure mode that already killed a
different finding in this project (Round 14's `rate_beta_x_move`, 45% of its
effect from one year) — arguably worse here.

**A second, independent finding on the same hold-out**: swapping the
portfolio construction alone (`topn_ew` instead of `decile_volq`, same
composite scores, same dates) flips the result to **-4.80%/yr, 0/40 offsets
positive, 2nd percentile of its own null.** A meaningful share of whatever
this composite captures lives in *how* picks become a portfolio (the
volatility-quintile bucketing specifically), not only in the ranking itself.

**Honest verdict, written into `PREREGISTRATION.md` at the time, not
softened after the fact:** a real, monotonic-in-cap, sector-neutral-robust
nomination-era signal, that has **not yet demonstrated year-to-year
robustness out of sample.** Not "beats SPY, confirmed." A 7-year hold-out is
a much higher-variance LOYO test than a 13-year nomination era, and
2020/2022 are exactly the dislocation/factor-rotation years this factor mix
(quality, low-vol, value-ish) has a real economic reason to concentrate in
— but this project does not get to call a result confirmed while it fails
its own standing concentration check, and doesn't here either.

### 3.3 Full compounding curve, $10,000 start (2007-01-03 through 2026)

| | terminal value |
|---|---|
| Strategy, offset-average | **$95,963** |
| Strategy, worst of 40 offsets | $72,476 |
| Strategy, best of 40 offsets | $118,863 |
| SPY buy-and-hold | $54,282 |

Every single offset beats SPY buy-and-hold over the full stitched period —
worth seeing alongside the LOYO caveat above, not instead of it: the
terminal-dollar view and the year-by-year robustness view are both true and
both matter.

### 3.4 Comparison against the deployed `q75` model

Computed by scoring the composite on the exact same 124 timepoints and
$2B+ universe the deployed model (`price_fund_h40_q75_trd_xgb_...`) uses,
pulling its cached scores directly from `final/out/sweep/scores/`.

- **Overall rank correlation between the two models' scores: -0.225**
  (median -0.260). Negative in every one of 11 sectors tested (from -0.12
  in Real Estate to -0.44 in Healthcare). This is not "uncorrelated" — the
  two models actively disagree.
- **Sector tilts point opposite ways**: the composite underweights
  Healthcare (0.84x) and Energy (0.72x), which are `q75`'s two largest
  overweights (1.71x, 1.54x); the composite overweights Consumer Cyclical
  (1.63x) and Industrials (1.21x), `q75`'s two largest underweights.
- **Why**: this project's own Round 13 already established `q75` is
  fundamentally a growth-over-value bet (buy expensive, R&D-heavy,
  cash-burning names) that doesn't survive sector-neutralization. This
  composite is built from the literature's opposite family (quality,
  capital discipline, low-vol, momentum) and does survive
  sector-neutralization. A strong negative correlation between an
  unconfirmed growth bet and a partially-confirmed quality/value bet is the
  expected outcome of the two philosophies, not a red flag.

### 3.5 Neither model can rank within its own top decile

Tested directly: IC (rank correlation with realized 40-day return) at
progressively narrower top-score cuts, same 124 timepoints, both models:

| slice | `q75` IC | composite IC |
|---|---|---|
| full universe | +0.004 (t=0.25) | **+0.034 (t=2.61)** |
| top 25% | +0.008 (t=0.72) | +0.007 (t=0.96) |
| top 10% | -0.007 (t=-0.58) | -0.009 (t=-0.98) |
| top 5% | +0.006 (t=0.41) | +0.002 (t=0.17) |

The composite is meaningfully better at separating good from bad across the
**whole** universe. Neither model can meaningfully order its own
best-of-the-best — both collapse toward (and briefly flip past) zero once
restricted to their own top decile. This is consistent with, and explains,
why the broad `decile_volq` construction (~200 names) beat the concentrated
`topn_ew` construction (~100 names) on hold-out: with no reliable
fine-grained ranking inside the "good" pool, spreading bets broadly across
it is the statistically correct response, not a compromise.

---

## 4. Survivorship-bias audit

Read in full — this is the section that decides whether any number above
means anything, and it is proven with specific evidence, not asserted.

### 4.1 Case study: Washington Mutual (`WAMUQ`)

The largest bank failure in US history (FDIC seizure, 2008-09-25). Does not
exist in today's roster — a naive current-universe backtest has zero
history for it at any date, ever.

| date | close | market cap | eligible @ $2B tier | eligible @ $150M tier |
|---|---|---|---|---|
| 2007-01-05 | $45.05 | $42.6B | **True** | True |
| 2007-12-03 | $19.62 | $17.0B | True | True |
| 2008-06-02 | $9.00 | $9.5B | **False** — fails the $10 price floor, correctly, NOT the market-cap floor | True |
| 2008-10-01 | $0.16 | $273M | False | **True** |

Correctly counted as a top-20 megabank when it was one; correctly drops out
of the $2B tier exactly when price crossed below $10 (not before, and for
the right reason — this project's price floor is `AND`ed with the cap
floor, and both conditions are checked, exactly as designed); stays visible
at the $150M tier all the way to its final trading days. Its actual realized
40-day returns from the outcome cache used by the backtest: -37% in June
2008, -97% by August, `truncated=True` (the delisting exit floor) correctly
firing starting 2008-09-05, three weeks before the actual seizure. A pick
made on this name gets charged the real loss.

### 4.2 Scaled up: gap-ticker coverage and actual usage

Of the 264 delisted companies this project separately recovered for
point-in-time correctness (Sharadar-sourced, `gap_tickers_used.json`), **223
were eligible at the $150M tier at some point**, and **163 were actually
selected as picks** by the confirmed strategy during the nomination era —
not a theoretical capability, something the walk-forward backtest did
repeatedly across its 82-window history at a single offset alone.

### 4.3 The one anomaly found, chased to ground rather than waved away

4,053 of 12,278,995 outcome-cache rows (0.033%) are `NaN`. Investigated
directly rather than assumed benign:
- **4,013** are each affected ticker's literal LAST row of data — there is
  no next-day price to enter a position on, which `execution.py`'s own
  `realize_position` also returns `None` for. Mathematically unavoidable,
  and irrelevant to any historical backtest window (it only ever touches
  the very last date in the dataset, near "today").
- The remaining **40** are all `USMV` (a benchmark, never a tradable pick)
  in the final few weeks before the data pull's cutoff.
- **Zero** relate to any stock pick inside the actual backtested period.

### 4.4 Mechanical checks (verified, not assumed, at build time)

- Every SF1 fundamentals join uses `filed_date` (the actual filing date),
  never `calendardate` (the period end, which precedes the filing by 4-6
  weeks and would leak about a month of look-ahead into every fundamental
  factor).
- Every `merge_asof` in this package carries an explicit row-position
  column and asserts no row was lost or reordered afterward — this
  project's own bug ledger records a real incident (Round 16) where
  `.sort_index()` after `merge_asof` was silently a no-op and six columns
  landed on the wrong rows. The assertion would have raised, and did not.
- The down-cap universe's liquidity floor uses `closeunadj * volume`
  (actual dollars traded that day), never split-adjusted `close` — the
  exact quantity whose look-ahead bias this project already found and fixed
  once (Round 11, the Apple/Amazon/NVIDIA exclusion bug).
- `pick_decile_volq` explicitly **excludes** names with a missing
  `volatility_60` from bucketing rather than defaulting them to the lowest-
  volatility bucket — the exact silent-failure mode (`_bucket_idx`'s NaN-
  to-bucket-0 behavior) that corrupted two live picks in this project's
  Round 18.

**Conclusion: no survivorship bias found.** The correction is real,
material (163 delisted names actually traded, not a handful), and its one
loose thread (the 0.033% NaN rate) resolved to an unavoidable, harmless
edge case with zero overlap with the backtested period.

---

## 5. What this strategy actually does (operational description)

- **Rebalances every 40 trading days** (~8x/year), non-overlapping. Not a
  daily or weekly trader.
- **Holds for a fixed 40 trading days, no exceptions.** No stop-loss, no
  profit target, no early exit rule of any kind — pure calendar exit, win
  or lose. Considered and deliberately excluded (this project's Round 13
  found a stop-loss didn't help the deployed model); worth re-examining
  here specifically because the hold-out's best year (2020) is a
  crash-then-snapback pattern a stop-loss could plausibly have cut off
  before the recovery.
- **Scans roughly 2,000 eligible names** each rebalance (domestic common
  stock, market cap ≥ $150M, trailing 20-day dollar volume ≥ $250k).
- **Holds ~200 positions at a time** (splits the universe into 5
  volatility quintiles, takes the top decile by composite score from each).
- **Inverse-volatility weighted** — no single position averages more than
  ~3.5% of the book.
- **About half the book (≈50%) turns over at every rebalance.**

---

## 6. What's not resolved, and worth doing next

In the order I'd prioritize, given what the hold-out actually showed:

1. **Laddered/staggered rebalancing.** Right now the entire book turns over
   on one calendar day every 40 days — which is plausibly *why* the LOYO
   check failed the way it did (2020 and 2022 were good days to be fully
   invested, which is a different claim from "good stocks were picked").
   Splitting the book into ~5 staggered cohorts, each rebalancing every 8
   days, doesn't touch the factors at all but directly attacks this without
   changing what the model believes about any stock.
2. **Understand the `decile_volq` vs. `topn_ew` divergence.** Same scores,
   same dates, and the hold-out result swings from +1.85%/yr to -4.80%/yr
   depending purely on the bucketing choice. That's either a real, useful
   insight (breadth/diversification is doing real work, consistent with
   section 3.5's finding that neither model can fine-rank its own top
   picks) or a fragility worth being nervous about. Both readings are
   plausible; distinguishing them matters.
3. **Test a stop-loss variant** — expect it to hurt (see section 5), but
   confirm empirically rather than assume.
4. **Down-cap universe coverage is bounded by the existing feature panel**
   (4,011 tickers), not the full 8,967-ticker small-cap universe
   (`build_panel.py`'s match-rate check: only 70.9% of `downcap_universe`
   rows found a match). Pulling Sharadar price+fundamentals for the
   remaining ~5,000 names is the most direct way to test whether the
   down-cap effect gets stronger with more true breadth, per Round 15's
   logic.
5. **Sector classification is current-day**, not point-in-time
   (`tickers_master.sector`) — the same disclosed limitation Round 13
   already carries. A company that changed sectors (e.g., the 2018 Telecom
   → Communication Services reclassification) is classified by where it
   sits today, not where it sat historically. Likely a small effect, not
   yet quantified.
6. **Insider-transaction and options-liquidity factors** were on the
   originally-approved data-sourcing list (`project-data-sourcing-
   priorities` memory) but not included here — Alpha Vantage throttling
   and a missing volume/open-interest field respectively were the blockers
   at the time.

---

## 7. Reproducing this from scratch

**Environment:** conda env `pipe_dream` (`/opt/anaconda3/envs/pipe_dream/bin/python3.11`).
All commands below assume that interpreter and are run from anywhere (every
script uses absolute paths — see "A note on paths" below).

**A note on paths.** Every script under `final/src/reset2026/` hardcodes
`MAIN_ROOT = Path("/Users/ggraham/pipe_dream/final")` at the top rather than
deriving it from `__file__`. This was written and run from a git worktree
(`.claude/worktrees/factor-composite-reset/`), and git worktrees only check
out **tracked** files — every data file these scripts read or write is
gitignored, so it physically does not exist inside the worktree. If you're
running this from the primary checkout instead, this still works unchanged
(the absolute path is correct there too); if you fork this to a different
machine or path, update `MAIN_ROOT` in each file first.

**Prerequisites already on disk** (per `AGENTS.md`'s reproduction table —
these are NOT rebuilt by anything below):
- `final/data/sharadar/pit_universe.parquet`, `sf1_fundamentals.parquet`,
  `sf1_shares.csv`, `tickers_master.csv`, `panel/daily/*.parquet`,
  `panel/stocks/*.parquet` (the Sharadar-sourced PIT price/fundamentals data)
- `final/out/features_with_fundamentals_sharadar_pit.parquet`,
  `features_with_issuance_sharadar_pit.parquet`,
  `features_with_short_interest_sharadar_pit.parquet`,
  `features_with_events_sharadar_pit.parquet` (existing feature panels —
  each is the base price/fundamentals panel plus one added column family)
- `final/scripts/td_data_sharadar/*.csv` (per-ticker OHLC export, 4,011
  files, the SAME corporate-action basis the feature panels were computed
  from — see `continuous_walkforward_pit.py`'s `PRICE_DIRS_PIT` for why not
  the older `td_data_local`/`td_data_delisted` directories)
- `final/scripts/td_data_local/SPY.csv`, `final/data/benchmarks/USMV.csv`

If any of these is missing, see `AGENTS.md`'s reproduction table for how to
rebuild it — most require Gabe's own machine (network access this
environment doesn't have).

### Step by step

```bash
cd final/src/reset2026

# 1. Down-cap PIT universe (3 tiers, liquidity floor). ~35s.
python3 downcap_universe.py

# 2. New quality factors (gross profitability, accruals, asset growth,
#    12-1 momentum). ~17s.
python3 quality_factors.py

# 3. Assemble the single working panel (9 factors + sector + universe
#    eligibility flags, joined onto the base price/fundamentals panel).
#    Logs a match-rate sanity check between the universe and feature panel
#    grids -- read it, don't just check the exit code. ~25s.
python3 build_panel.py

# 4. Vectorized, verified realized-outcome cache (every ticker x date,
#    survivorship-correct, verified against execution.realize_position on
#    300 random samples -- must print "0 mismatches" or stop and debug).
#    ~15s.
python3 build_outcome_cache.py --verify-samples 500

# 5. THE MAIN RUN. 6 cells (3 tiers x raw/neutral) x 40 grid offsets x 100
#    matched-null draws each, nomination era (2007-2019). Resumable --
#    checkpoints per cell under out/reset2026/checkpoints/, safe to kill
#    and re-run the same command. ~33 minutes.
python3 run_backtest.py --era nominate

# 6. Aggregate into the headline report (offset-averaged stats, between-
#    offset bootstrap CI, null percentiles).
python3 aggregate_report.py --era nominate
# -> read final/out/reset2026/REPORT_nominate.md

# 7. Before trusting anything in step 6, check leave-one-year-out
#    concentration on whichever cell looks best -- this project's standing
#    procedure since Round 14. There's no dedicated script for this (it's
#    an ad-hoc pandas read of the checkpoint JSONs' "yearly" field); the
#    exact snippet used is reproduced in this repo's git history
#    (commit "Name the nomination-era winner before running the
#    hold-out") if you want the precise code rather than rederiving it.

# 8. Name the ONE nomination-era winner in PREREGISTRATION.md (a manual,
#    written-down step -- this is what makes the next command honest) and
#    commit that BEFORE running step 9. As shipped, the answer was
#    cap150_raw / decile_volq.

# 9. THE HOLD-OUT. Runs exactly once, gated by two required flags. ~3-4
#    minutes (one cell instead of six).
python3 run_backtest.py --era holdout --only cap150_raw --i-am-confirming
python3 aggregate_report.py --era holdout
# -> read final/out/reset2026/REPORT_holdout.md

# 10. Leave-one-year-out on the hold-out itself -- do this even though (or
#     especially because) it might undermine what step 9 just showed. As
#     shipped, it did (section 3.2 above). No script; same ad-hoc-pandas
#     pattern as step 7, reproduced in the git history of the commit
#     "Hold-out confirmation: passes the pre-registered gates, fails LOYO".

# 11. Full compounding equity curve (only needed if you want the dollar
#     view alongside the annualized-excess view). ~2 minutes.
python3 compounding_curve.py
# -> out/reset2026/compounding_curve.json
```

### If you want to test a DIFFERENT configuration than the one confirmed here

Everything in `composite.py` (`FACTOR_SIGNS`, `TIERS`,
`pick_decile_volq`/`pick_topn_ew`) and `run_backtest.py` (`HORIZON`,
`NULL_DRAWS`, `COST_LEVELS`) is a plain module-level constant or function —
no config file, no CLI flag sprawl. Change the constant, then:

1. **Write down what you're changing and why, in a new dated section of
   `PREREGISTRATION.md`, before running anything.** This is not
   bureaucracy — it's the only thing standing between "I found something"
   and "I found something because I looked 12 times and this is the one
   that worked." See standing rule 9 in `sweep/RUNBOOK.md`.
2. Delete or rename `out/reset2026/checkpoints/` before re-running
   `run_backtest.py` on nomination era, or the resumability logic will skip
   every cell it already has a checkpoint for and you'll be looking at
   stale numbers.
3. **The 2020-2026 hold-out is now spent for this pipeline** (see section
   3.2 and `PREREGISTRATION.md`'s closing note). A new configuration gets
   evaluated on the nomination era only, honestly, and does not get a fresh
   hold-out draw to "check" it — that isn't how a hold-out works. If you
   genuinely need a clean out-of-sample test for a materially different
   idea, that requires new data (time passing) or a pre-registered
   different split, not re-running this one.

---

## 8. File manifest

```
final/src/reset2026/
  PREREGISTRATION.md       the dated spec + amendments + named selection + verdict
  downcap_universe.py      3-tier PIT universe, liquidity floor
  quality_factors.py       gross profitability, accruals, asset growth, momentum_12_1
  build_panel.py           assembles the 9-factor working panel
  build_outcome_cache.py   vectorized survivorship-correct realized returns, verified
  composite.py             rank-transform, sign-fixed combination, portfolio construction
  run_backtest.py          the orchestrator (40 offsets x 6 cells x 100 nulls, resumable)
  aggregate_report.py      offset-averaged headline report generator
  compounding_curve.py     $10k-start equity curve, all offsets + true SPY/USMV buy-hold

final/out/reset2026/
  REPORT_nominate.md       nomination-era headline numbers
  REPORT_holdout.md        hold-out headline numbers + the LOYO failure write-up
  compounding_curve.json   equity curve data
  checkpoints/*.json       one file per (era, tier, neutral, offset) cell -- the raw
                           evidence every number above is computed from
```
