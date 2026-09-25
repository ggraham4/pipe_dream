# AGENTS.md — orientation for any model (or human) working in this repo

This file is for anyone/anything landing in this repo cold — a colleague's
tooling, a different AI assistant, a future Claude session with no memory
of prior conversations. It answers: what is this project, what state is it
in, what's actually reproducible, and what's the plan. It does not replace
the narrative history — see "Where the fuller history lives" at the bottom
for the documents that record *why* decisions were made, not just *what*
the current state is.

**This file will go stale.** It reflects the repo as of 2026-09-04. If
something here contradicts what you actually find on disk (a file that's
supposed to exist doesn't, a script behaves differently than described),
trust the repo over this file, and please update this file to match once
you've sorted out the discrepancy.

## What this project is

A personal, from-scratch quantitative trading research project. The core
question: can price/volume-based ML models (and, increasingly, other
signal sources) identify stocks likely to outperform over a multi-week
horizon, backtested honestly with point-in-time discipline (no lookahead,
walk-forward retraining, embargo gaps). It has grown from a single
buy/no-buy classifier into several related workstreams (see "Current
state" below). There is a live Streamlit dashboard app that surfaces the
model's current picks.

**Owner: Gabe.** All modeling decisions, scope calls, and the standing
constraint below are his; treat this file and the other project docs as
recording *his* decisions, not a spec to freely deviate from.

## Standing constraints — read before touching anything

1. **Never push to / redeploy the live app without Gabe's explicit,
   in-the-moment permission**, even if a change looks obviously correct or
   beneficial. This has been an explicit standing instruction throughout
   this project's development. If you're an AI assistant and unsure
   whether a change would affect the live app, ask first.
2. **Don't run destructive git operations** (`push --force`, `reset --hard`,
   history rewrites) without explicit request, and never on `main` without
   being asked.
3. **Treat `.gitignore`'d paths as regenerable, not disposable-without-
   thought.** Most of them are — exact commands are below. A couple are
   flagged as **not currently reproducible** (see "Known gaps" below) —
   don't delete those assuming a script will rebuild them, because none
   currently will.
4. This is a solo research project that occasionally gets outside review —
   Gabe mentioned (2026-08-30) a colleague is independently building a
   similar stock-picking project with a different model architecture and
   different input variables. If you're helping compare notes with that
   project or its outputs, don't assume this repo's specific choices
   (feature set, horizon, universe) are the only reasonable ones — they're
   this project's choices, arrived at empirically and documented as such
   throughout, not a claim that they're optimal in general.
5. **`git add`/`git commit`/`git push` are fine to run yourself, on your
   own judgment (changed 2026-09-17, per Gabe — previously this required
   handing files to him to run manually).** This does NOT loosen anything
   else: constraint #1 (never push/redeploy the *live app*) and constraint
   #2 (no destructive ops — force-push, `reset --hard`, history rewrites —
   without explicit request) both still stand exactly as before, including
   pushing/merging to `main`, which still needs Gabe's in-the-moment
   go-ahead like any other main-branch or deploy action. Keep `.gitignore`
   doing its job — don't commit large/regenerable files (see the
   reproduction table below); everything currently gitignored should stay
   that way unless there's a specific reason to change it.
6. **Never store live API keys/secrets in any file that lives inside this
   git repo** (`SHARADAR_API_KEY` included) — those belong only in
   whatever out-of-repo secrets store this project's owner uses (e.g. the
   Claude Project's own docs, kept separate from git), never committed.

## Repo map

Repo root (`pipe_dream/`) contains both the current, actively-developed
project (`final/`) and some earlier-stage artifacts from before that
reorganization:

```
pipe_dream/
├── final/                    <- THE ACTIVE PROJECT. Nearly everything
│                                 described in this file lives here.
├── options_raw/               <- a `dolt clone` of DoltHub's
│                                 `post-no-preference/options` DB (see
│                                 below). NOT the same thing as
│                                 final/data/options_raw/ (a parquet/csv
│                                 export FROM this clone).
├── src/, analysis/             <- pre-reorg, early-stage code (LSTM
│                                 tensor-builder experiments, XGBoost/PCA/
│                                 UMAP exploration notebooks-as-scripts).
│                                 Superseded by final/src/. Kept for
│                                 history; not part of the active pipeline.
├── out/                       <- essentially empty (8KB), a leftover from
│                                 before the final/ reorg. Not in active use.
├── pipe_dream.egg-info/        <- auto-generated by `pip install -e .`
│                                 against the top-level pyproject.toml.
└── pyproject.toml              <- packages the top-level src/ as an
                                    editable install. Unrelated to final/.
```

### `final/` in detail

```
final/
├── app/              <- the live Streamlit dashboard.
│   ├── app.py            <- entry point (`streamlit run app.py`)
│   ├── lib/               <- app-specific modules: stock_model.py (secondary
│   │                         price-only XGBoost/LSTM), pit_model.py
│   │                         (**primary** as of 2026-09-02 — the PIT
│   │                         augmented+stop-loss model), options_model.py,
│   │                         options_common.py, data_refresh.py, paths.py.
│   │                         regime_gate_model.py (the HMM gate) still
│   │                         exists on disk but app.py no longer imports
│   │                         it — see workstream 2 below.
│   ├── logs/              <- runtime logs from scheduled refresh jobs
│   │                         (gitignored — regenerates itself)
│   └── requirements.txt
├── src/              <- the model pipeline (all core scripts). Two parallel
│                         tracks live here: the original non-PIT scripts
│                         (features.py, current_signal.py,
│                         lstm_current_signal.py, current_signal_gated.py,
│                         fundamentals_features_beta.py,
│                         regime_signals_beta.py — still run by the
│                         Secondary Models tab, no longer the primary
│                         signal) and the PIT (point-in-time,
│                         survivorship-bias-corrected) track that now
│                         drives the app's primary "Today's Picks":
│                         features_pit.py, fundamentals_features_pit.py,
│                         price_discontinuity.py, pit_universe_continuous.py
│                         (+ the older, 8-fixed-timepoint pit_universe.py),
│                         continuous_walkforward_pit.py (the PIT backtest —
│                         also where MIN_MARKET_CAP/MIN_PRICE, the
│                         point-in-time mid-cap+ eligibility floor, and
│                         STOP_LOSS_PCT live), and current_signal_pit.py
│                         (the live signal generator app/lib/pit_model.py
│                         wraps — trains fresh, no cached-checkpoint-only
│                         path exists for this one yet).
│                         NOTE (2026-09-11): current_signal_pit.py now
│                         IMPORTS its selection and weighting from
│                         sweep.portfolio rather than reimplementing them,
│                         so the live pick and the backtested pick cannot
│                         drift apart. STOP_LOSS_PCT is no longer used by
│                         the deployed config (Round 13 holds to horizon).
│   └── sweep/        <- the pre-registered sweep harness (Rounds 12-17).
│                         Splits a backtest into an expensive half (score
│                         caching, one model run per signal config) and a
│                         cheap half (portfolio post-processing, free), so
│                         27 x 48 = 1,296 backtests cost 27 model runs.
│                         Also holds every measurement tool built since:
│                         feature_ic.py (per-feature IC screen), factors.py
│                         (sector/size/vol neutralization), breadth.py
│                         (effective breadth), stats.py (deflated Sharpe,
│                         Reality Check, matched nulls), attribute.py, and
│                         the feature families rates.py and events.py.
│                         START AT final/src/sweep/RUNBOOK.md.
├── scripts/          <- data-acquisition scripts, meant to be run
│                         directly by Gabe (not through an AI assistant's
│                         sandboxed tools — see individual script
│                         docstrings for why: yfinance/SEC EDGAR/DoltHub
│                         are all blocked from Claude's cloud sandbox
│                         and, for DoltHub specifically, from the
│                         device-bridge shell too via an org allowlist)
├── data/             <- raw/intermediate data (options history, GARCH
│                         vol, options training tables)
├── out/              <- pipeline outputs: feature parquets, backtest
│                         results, trained-model checkpoints, charts
├── models/           <- the options-premium-model workstream's own
│                         scripts, results, and trained artifacts
│                         (separate from final/out/models/ — see below)
└── analysis/, universe/, backtest/, signals/, models/ (as markdown docs)
    <- NOTE: these markdown docs live in the Claude Project attached to
       this work, not as files in this repo. See "Where the fuller
       history lives" at the bottom.
```

## Current state of the project (as of 2026-09-02)

> **SUPERSEDED IN PART.** Everything in this section describing model
> PERFORMANCE predates the Round 11 data rebuild (2026-09-09), which
> replaced the universe every prior result was measured on. The repo map,
> file locations and workstream descriptions here are still accurate; the
> numbers are not. See "Rounds 10-17" below before trusting any figure.

**The headline change since this file was last accurate:** the
survivorship-bias-correction workstream (was "#4, in progress") is now
essentially complete, has taken over as the **primary live signal in the
app**, and the HMM-gated blend that used to be primary (was "#2") has
been retired from the app entirely. If you only read one thing below,
read workstream 4.

**1. Core buy/no-buy stock classifier (v4, "permanent" as of 2026-08-27) —
now "Secondary Models" in the app.** Two models — XGBoost and an LSTM —
same 11 price/volume features (momentum at 4 windows, volatility at 2
windows, volume ratio, relative strength vs. SPY, position within 52-week
range), same ~1,620-ticker current-universe screen (market-cap>$2B + US-
incorporated + price>$10, see
`universe/2026-08-27-expanded-universe-methodology.md` in the Claude
Project), predicting/holding over a 40-trading-day horizon. Walk-forward
backtest, 8 timepoints, embargo discipline. Result: XGBoost 6/8 beat SPY,
+21.54%/trial avg; LSTM 6/8, +8.96%/trial avg. **Not survivorship-bias-
corrected** (no point-in-time gap-ticker coverage, no point-in-time
mid-cap+ floor) — kept in the app for transparency/comparison, not as the
recommendation. Full detail: `models/final-buy-no-buy-model.md`,
`backtest/dollar-simulation-results.md`.

**2. Fundamentals-augmented ("beta") model and HMM regime gate —
RETIRED from the live app (2026-09-02), per Gabe's explicit instruction
("we are no longer using the HMM").** This used to be the app's primary
signal (a 2-state Gaussian HMM fit on SPY returns,
`final/src/regime_signals_beta.py`, blending a price-only and a
fundamentals-augmented model's picks). `app.py` no longer imports
`regime_gate_model.py` or calls `current_signal_gated.py`; the "Today's
Picks" tab is workstream 4's model now (below). The source files, the
HMM-gate logic, and the historical backtest docs (`models/fundamentals-
beta-results.md`, `backtest/2026-ytd-hmm-gated-sequential-results.md`,
`backtest/2026-ytd-pit-blend-and-last-80-days-results.md`) are all still
on disk/in the Project for history — nothing was deleted, just
disconnected from the app. **This also means the "gated behind finishing
the HMM joint model" section of Future Plans (below) is stale** — Gabe
concluded this workstream by moving on from it rather than by finishing
it in the way that section anticipated; treat those ideas as unblocked
but re-confirm priority with Gabe rather than assuming the old gate still
applies.

**3. Options premium model (in active development, design doc 2026-08-26
onward, NOT the same thing as the stock model).** Predicts a distribution
over the underlying's price at expiration, prices calls/puts off that
distribution against real market premiums (sourced free from DoltHub's
`post-no-preference/options`, ~91M rows, 2019-02 to present, S&P 500 +
expanded-universe coverage), and sizes positions via a calibrated-decile
Kelly optimizer. **Calls show a real, if noisy, edge** — a Tweedie GLM
beats a "market is fairly priced" benchmark on held-out data (though see
the PIT-integration CV-retune discrepancy below), and the decile-calibrated
Kelly sizing cut a would-be −50% trial down to −11% by correctly sizing
down when its own signal was weak. **Puts do not have a working model** —
every candidate underperformed the benchmark, an open, unsolved problem.
**PIT/fundamentals integration attempted 2026-09-02, per Gabe's request —
no clear win, not adopted into production.** Joined the stock model's PIT
fundamentals panel onto the calls training data (point-in-time, no
lookahead) and applied the same market_cap>=$2B/close>=$10 eligibility
floor the stock model uses, evaluated at each option's own entry_date. At
the fixed production hyperparameters (power=1.4, alpha=0.001, so the
comparison isolates the data change): the eligibility floor ALONE made the
walk-forward backtest worse (avg return −1.56%/−0.64% equal-weight/Kelly
vs. the original +11.43%/+7.28%); adding fundamentals back on top mostly
recovered what the floor cost (+6.15%/+6.52%) and meaningfully cut variance
(std 15.8% vs. the original 41.6% for equal-weight — a better
return-per-unit-of-risk ratio) but didn't clearly beat the existing
production model, and win-rate against SPY dropped (2/5 vs. the original
4/5). Sample size is thin throughout (5-6 usable annual timepoints) — none
of this should be read as decisive. The reusable deliverable from this pass
is the reproduction pipeline itself:
`final/models/pit_integration/` (5 scripts + README) — at the fixed
production hyperparameters it reproduces the existing backtest numbers to
the basis point, closing the "no reproduction script" gap below. Full
detail, including a from-scratch CV-retune discrepancy worth resolving
before trusting either version's exact numbers as final:
`models/options-premium-model-design.md`'s "PIT/fundamentals integration"
section.
**Hyperparameters re-evaluated 2026-09-02, same day, per Gabe's direct
follow-up request — production hyperparameters (power=1.4, alpha=0.001)
CONFIRMED, not changed.** A much wider Tweedie grid (63 combos, power
1.1-1.9) and a re-swept GAM hurdle model (unchanged since Round 1/2) were
run across all three variants (OLD/BASE-PIT/AUG-PIT), then — critically —
both CV "winners" were validated against the real walk-forward dollar
backtest rather than trusted on offline accuracy alone. Result: GAM wins
offline MAE by a wide margin (1.02-1.05 vs. Tweedie's 1.08-1.09 across
variants) but is a genuine trap — it produces −45% to −72% average
backtest return (0-2/5 win rate vs. SPY) in every variant, apparently from
overfitting on the small training pools available at early backtest
timepoints (BASE-PIT and AUG-PIT both post an identical −76.63% at the
very first usable timepoint). The widened Tweedie search's CV-optimal
power (1.1) sits at the edge of the tested grid and is roughly tied with
production only under Kelly sizing, not equal-weight — not a clear enough
win to adopt given it's an edge-of-grid result on a 5-timepoint backtest.
Reusable deliverable: `final/models/hyperparameter_retune/` (2 scripts +
README). Full detail: `models/options-premium-model-design.md`'s
"Hyperparameter re-evaluation" section.

**Major rebuild + selling-premium pivot, 2026-09-04 (six rounds, same
day, `final/models/buy_no_buy_options_v2/`) — real bugs fixed, one
genuinely promising (if still unconfirmed) new signal found, several
dead ends closed off with evidence rather than guesswork.** Started from
Gabe's suspicion (correctly) that some calls the model was recommending
had strikes implausibly far from spot, tracing back to leftover
survivorship-biased data.

*Fixed, real wins:*
- **The options model's PIT-fundamentals coverage gap (flagged below in
  "Known gaps" as of 2026-09-02) is now closed for eligibility purposes**:
  re-filtered the stock model's existing
  `final/out/features_with_fundamentals_pit.parquet` (already covers the
  full expanded options universe via the SEC EDGAR pull done for the stock
  model — no new Sharadar call needed) up from 495 to **1,266 tickers**,
  joined via `merge_asof` (120-day tolerance) — see
  `options_pit_fundamentals_expanded.parquet` /
  `build_pit_capcheck_v3.py`. Applies to both calls and puts now.
- **Root-caused and properly fixed a stock-split price/strike scale
  mismatch**: local price data is split-adjusted for continuity, but
  DoltHub's option chain strikes are never retroactively adjusted — so a
  strike pulled from 2019 and a "current" split-adjusted spot price are on
  different scales for any ticker that's split since. Fixed with a
  cumulative "still-to-come" split-ratio rescale, keyed off a fresh
  Sharadar `actions`-table pull (`sharadar_splits_raw.csv`, 1,326 events /
  660 tickers, validated against 5 known real splits) —
  `final/scripts/sharadar_splits_pull.py` (run directly by Gabe, same
  network-blocked-from-sandbox reason as the other Sharadar scripts) and
  `build02c_v3_properrescale.py`. This replaced an earlier crude
  workaround (drop rows with weird moneyness) that was silently deleting
  ~4.4% of rows concentrated in large/liquid/high-momentum names — which
  had been *inflating* the apparent baseline edge (+2.11% under the old
  workaround vs. −0.70% once properly fixed — see below).
- **Found and fixed two independent EOD-data-quality bugs** while
  building a 60-day-horizon variant: an MLK-Day exact-date-join gap
  (~20% of rows silently dropped — fixed via `merge_asof(direction=
  "backward", tolerance=3 days)` instead of an exact-date merge) and a
  universe-wide missing-`iv_current`-on-one-specific-date gap in
  `volatility_history_expanded.parquet` (fixed via `dropna` before the
  asof join). Both are now-known failure modes worth checking for in any
  future asof join against this options data.
- **Built a full parallel short-puts ("selling premium") pipeline**,
  mirroring the calls pipeline end to end: `build02b_pull_puts.py` →
  `build02c_puts_properrescale.py` (same split-rescale/PIT/feature
  infrastructure, computing cash-secured-put economics: `loss_ratio`,
  `premium_pct_of_collateral`, `pct_return_on_collateral`,
  `loss_ratio_plus1` as the Tweedie target) → `build_pit_puts.py`.
- **Diagnosed a too-good-to-be-true backtest down to its actual root
  causes** rather than reporting it — worth reading as a caution for any
  future session that gets a suspiciously good number. An unconstrained
  puts backtest showed +15%/cohort Kelly average, 5/5 win years; three
  checks exposed it as almost entirely artifact: (1) the *same 1-2
  tickers* dominated every single year's top picks — a red flag on its
  own; (2) those tickers (MNST, APH) each carry a stock split dated
  suspiciously close to the data-pull date, which had corrupted their
  entire reconstructed price history via the split-rescale math; (3)
  systematically comparing every row's quoted premium against a
  Black-Scholes fair value computed from that row's *own* stated
  `entry_iv` — a cheap "richness ratio" check that needs no real
  bid/ask/volume data — showed the 90th-percentile deep-OTM pick was
  priced 16-50x its own theoretical value (99th percentile: 2,400x),
  i.e. stale/unexecutable quotes, not real mispricing. Under 1% of rows
  had missing or implausible `entry_iv` yet dominated nearly every year's
  picks. Fixed via `build_pit_puts_cleaned.py` (drop richness_ratio>3x,
  9.1% of rows) plus an `entry_iv` sanity range (0-150%, 0.8% of rows) in
  the generic backtest script.
- **After cleaning, a real, modest, tail-risk-honest signal survives**,
  confirmed at monthly cadence (85 real timepoints from
  `entry_expiration_pairs.parquet`, not just 5-6 annual snapshots):
  selling near-ATM/OTM cash-secured puts, Kelly avg **+3.32%/cohort
  (~30-day hold), std 5.95%, win 70/85 (82%)** — including a real
  −33.5% drawdown in the Feb-2020 (COVID-crash) cohort, which is itself
  reassuring: the cleaned backtest now shows realistic short-vol tail
  risk instead of an implausible always-positive streak. Treat as a
  promising lead, not a confirmed edge — see caveats in the Project doc
  (below): cleaning thresholds were reasonable-but-ad-hoc, no transaction-
  cost/assignment modeling, and one COVID-sized month in an 85-month
  sample can't fully characterize short-vol tail risk either way.

*Dead ends, closed off with evidence (don't re-try these without a new
reason to believe they'd work now):*
- **Buy/no-buy gate + ATM strike, on the corrected expanded universe**:
  underperformed the ungated baseline (Kelly avg −9.44%, std 14.99%,
  1/5 win) — not adopted.
- **Strike-moneyness grid search** across the expanded universe: noisy,
  unstable across every tested point — no confident signal at any
  moneyness.
- **60-day horizon**: clearly worse than the 30-day baseline (Kelly avg
  −16.11%, std 12.40%, 1/5 win).
- **~2-day horizon** (closest honest proxy to 0DTE): Kelly avg 0.00% —
  the calibrated-Kelly sizer correctly held 100% cash every timepoint
  (n=4; one skipped for a genuine data gap). **Literal 0DTE was
  deliberately never built**: entry_date==expiration_date makes
  moneyness and payoff deterministic functions of the same EOD price —
  methodologically circular, not a real forecasting test.
- **Very-long (6mo/1yr) horizon**: infeasible, a real data ceiling —
  per-ticker coverage cliff-drops from 843 tickers at 73 DTE to 25 at 74
  DTE and stays low past 100 days, not concentrated in real LEAPS-active
  names.
- **The existing calls baseline itself, once properly rescaled + widened
  + confirmed at monthly cadence**: Kelly avg −0.70% (annual, n=5) /
  −0.16% (monthly, n=74, std 3.28%, win 14/74) — no edge, essentially
  flat. This supersedes the earlier +2.11%/+11.43% numbers reported
  elsewhere in this doc and in `models/options-premium-model-design.md`,
  which predate the split-rescale fix above and the wider PIT
  fundamentals coverage; those numbers should now be read as
  superseded, not as the current honest baseline.

The canonical reusable script going forward is `backtest_generic.py`
(`MODE=calls|puts`, `CADENCE=annual|monthly`, optional `MAX_MONEYNESS`
arg, env vars `EXCLUDE_RECENT_SPLITS`/`FILTER_BAD_IV`/`USE_CLEANED_PUTS`)
— prefer it over the older one-off `baseline_properrescale_backtest*.py`
scripts for any new backtest variant in this workstream. **None of
today's new files are in git** (per standing constraint #5 — written
directly to Gabe's `final/models/buy_no_buy_options_v2/` folder, nothing
committed). Full blow-by-blow, including every intermediate number in the
data-artifact diagnosis above and the full caveats list, is in the
Project doc `models/2026-09-04-buy-no-buy-options-integration.md`
(six rounds, all in one doc, most-recent-round-first).

**4. Survivorship-bias correction / PIT (point-in-time) pipeline —
COMPLETE enough to be the primary live model, actively being extended
(Rounds 1–8, 2026-08-28 through 2026-09-02).** Started from Gabe's
observation that the production universe (today's ~1,650 tickers) was
being applied retroactively across the whole backtest window, silently
excluding every company that later went bankrupt, got delisted, or was
acquired. What exists now, in order:
  - **Point-in-time gap-ticker recovery**: 264 gap tickers (companies real
    S&P 500 constituents at some point since ~2007 but absent from
    today's universe) with price history via a paid Sharadar subscription
    (`final/scripts/sharadar_data_pull.py`, `SHARADAR_API_KEY` env var
    required) — 158/211 of the original set plus a 2007-2008-extension
    batch landed usable data; fundamentals for the current universe still
    come from SEC EDGAR (`scripts/fundamentals_raw/`), gap-ticker
    fundamentals from Sharadar (`scripts/fundamentals_raw_delisted/`).
  - **`price_discontinuity.py`**: catches and segments fabricated
    single-day "returns" from unadjusted corporate-action price seams
    (root case: CHRD/Chord-Energy's bankruptcy-reorg, a +6,254% fake
    return that inflated an early full-universe backtest run to $10k ->
    $797M before this was caught and fixed).
  - **Point-in-time mid-cap+ eligibility floor** (`continuous_walkforward_
    pit.py`'s `MIN_MARKET_CAP`/`MIN_PRICE`, Round 7): reapplies the
    production mkt-cap>$2B/price>$10 screen AT EVERY HISTORICAL STEP,
    not just once against today's values — closed a real look-ahead-bias
    hole (confirmed for MARA: pickable as a nano-cap in 2013/2017 windows
    purely because it's a multi-billion-dollar company TODAY). This is
    what took the "expanded universe" backtest from implausible
    (single-digit-million-dollar totals from $10k) down to believable.
  - **Empirically-optimized stop-loss** (Round 8, `--stop-pct` /
    `_stoploss_sweep` modes on `continuous_walkforward_pit.py`): swept
    5%-50% stop percentages against the same backtested picks (re-
    simulation only, no retraining, so a full sweep is cheap) and found a
    well-supported 12-17% plateau; **15% is the adopted operating value**
    (`OPTIMAL_STOP_PCT` in `current_signal_pit.py`), roughly doubling the
    already-improved Round-7 total.
  - **Current backtest headline** (expanded universe, mid-cap+ floor,
    123 non-overlapping 40-day windows, 2007-03-02 to 2026-07-27):
    `augmented_stoploss` (15% stop) $10k -> **$214,606** vs. SPY's
    $53,306. See `backtest/survivorship-bias-correction-results.md`,
    Round 7 and Round 8, for the full sweep tables, robustness checks
    (an sp500-only-universe cross-check), and caveats (small-sample,
    no transaction-cost modeling, stop-loss level chosen from a backtest
    sweep with no guarantee it holds going forward).
  - **Promoted to the live app (2026-09-02, this same round)**: a new
    live-signal script, `final/src/current_signal_pit.py`, trains the
    augmented model fresh on all history, applies the same point-in-time
    mid-cap+ floor to today's candidates, and outputs today's top-5 picks
    with the 15% stop-loss as guidance — wired into the app as the
    **primary "Today's Picks" tab** via `app/lib/pit_model.py`. **Known,
    fixed gotcha for future sessions**: `features.latest_complete_date()`
    (borrowed from the non-PIT pipeline) requires 90% of ALL tickers in a
    panel to have a row on some date — fine for `features.parquet` (every
    ticker there is actively tracked) but silently returns NaT on any PIT
    panel, since ~260+ permanently-delisted gap tickers never have a
    recent row and drag the combined-universe coverage below 90% forever.
    `current_signal_pit.py`'s own `latest_complete_date_pit()` fixes this
    by checking coverage against current-universe tickers only — if you
    write a NEW script against a PIT panel, use that pattern (or
    `continuous_walkforward_pit.py`'s `current_universe_tickers = set(...)
    - gap_tickers` split), not the plain `features.py` helper.
  - **Sandbox note for AI assistants**: the PIT parquet files
    (`features_pit.parquet`, `features_with_fundamentals_pit.parquet`)
    are ~800-900MB and reliably OOM a device-bridge shell with ~3.8GB RAM
    — `features_pit.py`, `fundamentals_features_pit.py`, and
    `current_signal_pit.py` (anything that loads the full panel) must run
    on Gabe's own machine. The lean stop-loss-sweep modes on
    `continuous_walkforward_pit.py` (load only `[ticker, date, low,
    close]`) are the exception — those have run successfully via the
    device bridge.

## Round 9 (2026-09-07) — independent review, and what it broke

An outside methodology review of commit `3b59675` was worked through in
full. Read `backtest/2026-09-07-review-response-and-execution-corrections.md`
in the Project for the complete write-up. The short version, because it
changes how every number above should be read:

**The headline result does not survive corrected execution.** With a
one-bar entry lag, gap-through-aware stop fills, the delisting exit floor
and 50bp round-trip costs, the augmented + 15% stop model returns $25,299
against SPY's $55,597 over the same 122 windows. A stop level chosen on
2007-2019 only (16%, not 15%) delivers **t = 0.01** on the 2020-2026
hold-out. Treat every pre-Round-9 terminal-dollar figure in this file as
an upper bound produced by same-bar execution and zero costs.

**Two data bugs, neither previously documented.**

1. `--refresh-recent` in `local_data_pull.py` spliced freshly-pulled
   (post-split) bars onto stored (pre-split) history, fabricating a
   one-day crash at the join. It had corrupted **MNST** (2:1, 2026-07-13)
   and **PRIM** (2:1, 2026-05-06) — i.e. the *live signal*, not the
   backtest. The top-up now verifies the adjustment factor on the
   overlapping dates and re-pulls in full when it has moved.

2. **`scripts/td_data_delisted/` has `close` on the dividend-adjusted
   basis and `open`/`high`/`low` on the split-adjusted-only basis.** 157
   of 260 tickers have `close` outside their own `[low, high]` on >98% of
   bars (`td_data_local` is clean: 0 of 1,648). Close-to-close returns
   never noticed, but the stop-loss reads `low` against an entry taken
   from `close`, so stops barely fired on those names — 17.2% stop-out
   rate versus 44.7% on clean tickers. Since the gap tickers *are* the
   survivorship correction, the 15% stop was capping losses on half the
   book only. Windows containing at least one such pick average +5.21%
   excess vs SPY; windows containing none average +0.31%.

   Run `src/repair_ohlc_coherence.py` before anything that reads intraday
   columns. It writes `scripts/td_data_delisted_repaired/` and is
   non-destructive. `local_data_pull_delisted.py` now refuses to write an
   incoherent file.

**A note on the review itself:** its section 4 claimed unadjusted splits
across the whole panel. That is wrong — yfinance back-adjusts splits even
with `auto_adjust=False`, verified against AAPL/NVDA/TSLA/GOOGL/AMZN and a
6.4M-bar scan. The historical feature panels were never split-contaminated.
The bugs above are different and were found while checking the claim.

**Survivorship fix.** `continuous_walkforward_pit.py` no longer does
`dropna(subset=FEATURE_COLS + [LABEL_COL])` before the walk-forward loop
— that deleted any stock whose series ends within the next 40 trading
days from the candidate pool on exactly the dates it was about to blow
up. Candidates now need only features; the label filter applies to the
training set only. **Expect a retrain to look worse than the numbers
above** — it adds those positions back.

**New modules.** `src/execution.py` is now the single place a position is
realized (entry lag, stop fills, exit floor, costs) — use it rather than
growing another copy of the arithmetic. `src/resimulate_corrected.py` and
`src/holdout_analysis.py` reproduce the tables in the Project doc.
`--execution as_published` reproduces pre-Round-9 numbers for comparison.

## Rounds 10–17 (2026-09-09 → 2026-09-12) — the data rebuild, and what survived it

**If you read one section of this file, read this one.** Everything above
describing model performance predates a data rebuild that invalidated it.

### The short version

Round 11 replaced the universe every prior result was measured on. Rounds 12–15b
then established, with well-powered negatives, that the model has **no detectable
stock-selection edge** — what looked like one was survivorship bias, then a
sector bet, then the winner's curse. Round 16 found the first genuine positive in
the project's history: an **earnings-event timing feature**. Round 17 (pruning)
is in progress.

The full write-ups live in the Claude Project, not in this repo. The index is at
the end of this section.

### Round 11 — the universe was wrong, and so was everything measured on it

The candidate pool every prior result used was missing **a third of the eligible
early universe, and 89% of what was missing had since died**:

```
2008-06-30   981 eligible   old pool had 666   missing 315, of which 281 dead (89%)
2014-06-30 1,418 eligible   old pool had 923   missing 495, of which 396 dead (80%)
```

Missing names include Genentech, Monsanto, Anheuser-Busch, Dell, DuPont,
Wachovia, EMC, Yahoo, Sprint. Three further defects found in the same pass, all
affecting prior results:

1. **41 of 264 gap price files were the wrong company** — symbols reissued to new
   issuers, 46,854 wrong-issuer bars.
2. **The $10 price floor was look-ahead** — applied to split-adjusted `close`, it
   excluded Apple ($5.98 adjusted vs $167.44 actual), Amazon, NVIDIA and 41 other
   names worth $708B from the 2008 universe, because they split *later*.
3. **~240 tickers' features used prices carrying spinoff adjustments that had not
   happened yet.**

A genuinely point-in-time universe now exists:
`final/data/sharadar/pit_universe.parquet` — 6,888,686 rows, 5,454 trading days,
4,011 tickers.

**Treat any performance number in this file dated before 2026-09-09 as measured
on defective data — untrustworthy in either direction, not merely pessimistic.**

### Rounds 12–15b — five well-powered negatives

| round | question | verdict |
|---|---|---|
| 12 | does any of 1,296 configs beat the market? | **NO.** Deflated Sharpe 0.746, Reality Check p=0.61 |
| 13 | is the fundamental signal real? | **NO.** It is a sector bet — `rnd_intensity` t 3.28 → **0.77** after sector neutralization; 0 of 24 features reach \|t\|>2 |
| 14 | do rate-sensitivity features help? | **NO.** The one candidate was 2019: that year is 8% of windows and **45% of the effect** |
| 15 | is breadth the missing lever? | **NO.** Capped at `1/ρ ≈ 16` bets per window by an average pairwise active correlation of 0.055–0.076 that is flat across book sizes 5–100 and horizons 10/20/40 — a property of the asset class, not our construction |
| 15b | does shortening the horizon help? | **NO.** Breadth varied **13×** (24.7 → 366.9 bets/yr) and the result did not move. Under `IR = IC × √breadth` that is only possible if IC ≈ 0 |

**Calibration everyone should know before reading any backtest in this repo:**
in a synthetic grid containing **no signal at all**, 27% of configurations beat
the market and the best reached **2.577×**. A single config beating SPY is not
evidence of anything.

**What the deployed model actually does.** Its sector-neutralized IC is −0.0038
(t −0.63) — slightly *negative*. Residualizing scores on size/vol/sector drops
the nomination-era result from 2.7957× to **0.7719 against a null median of
0.7721** — the exact centre of its own matched null. So 100% of the apparent
performance is factor loading. Decomposed:

```
static sector tilt (tech/health/energy)   +0.54%/yr   t 1.99, survives LOYO, ETF-replicable
sector timing / rotation                  +0.42%/yr   t 0.28 - nothing
within-sector stock picking                ~0%/yr     at or below random
```

The `volq` + `invvol` construction is where the headline number comes from, and
it works by **cutting variance drag, not by picking better**: at top-5 it barely
moves arithmetic return (+14.54 → +16.30%/yr) while halving volatility, taking
drag from 7.16%/yr to 2.49%/yr.

### Round 16 — the first genuine positive

`days_to_next_filing` — days until a company's next earnings filing.

```
h=20   IC -0.0153   t -4.17   BH q 0.0004   permutation p 0.000
h=40   IC -0.0179   t -3.14   BH q 0.020    permutation p 0.035
```

It **gains** strength under sector neutralization (t → −4.59), so it is not a
sector bet. It survives leave-one-year-out: min \|t\| across all 13 year-drops is
**3.42** at h=20. The sign matches the **earnings announcement premium** (Beaver
1968; Frazzini & Lamont 2007) — a named, heavily-replicated anomaly. And PC1 is
only 27–33% of IC variance (versus 67–69% for the price/fundamental families), so
this is genuinely independent information.

**The caveat that governs how it may be used.** The strong variant uses the
*true* next-filing date. Earnings dates are scheduled and announced weeks ahead,
so a real trader knows them — but neither Sharadar nor Alpha Vantage records
*when a date was announced*, only when the filing landed, so this dataset cannot
prove it was knowable. Three variants are therefore carried side by side:

```
_est        cadence (last filing + own median gap)     provably causal   t -1.66
_seasonal   same quarter last year (Frazzini-Lamont)   provably causal   t -2.18
_actual     the true next date                         unverifiable      t -4.17
```

**`_actual` and `_known` are excluded from every training feature set.** Shipping
an unverifiable column in a deployed model is not acceptable. The seasonal
estimator is the tradeable version. Note the asymmetry in our favour: live
trading *will* have real announced dates, so the honest backtest **understates**
live performance.

A training-free stage 2 (rank or filter the model's top-50 by earnings proximity)
was tested and **failed** — nearest-earnings sits at the null median. The only
robust piece is that *farthest*-from-earnings is bad (1st–2nd percentile), i.e.
the premium seen from the short side. An IC of 0.008 cannot be detected in 82
portfolio windows; it belongs inside the model as a column, not outside it as a
rule.

### The gate philosophy changed on 2026-09-12

`claude/validation-gates.md` now has a **DECISION BAR** section that supersedes
Gate B for deployment questions. Gate B's `t > 3` is a hypothesis-testing bar
applied to what is actually a decision problem. The standard is now: **deploy
when expected excess return is positive after costs and the downside is
understood. Significance is not required; honesty about the expectation is.**

Two things did *not* change:

- **Gate A is unchanged and absolute** — placebo, look-ahead, pool integrity.
  Those catch *bugs*, not insignificance.
- **Leave-one-year-out survives**, because concentration is a statement about
  forward expectation rather than significance. A result that is 45% one year has
  a near-zero forward expectation whatever its p-value.

What does *not* work, and is recorded because it is the tempting mistake: "27% of
zero-signal configs beat the market, so we will take something in that 27%." That
27% is measured **in-sample**. It is the lucky tail of a distribution centred on
zero, not a subpopulation with an edge. Winning a large search is not evidence
about forward return; a reason to work, or confirmation on untouched data, is.

### The hold-out is spent

2020–2026 was used **once**, in Round 13, to confirm the top-5 breadth choice.
Rounds 15, 15b, 16 and 17 are all nomination-era only, and the `breadth` and
`horizon` CLI commands refuse `--era holdout` outright. **Nothing may be
confirmed on it again.** Anything that passes from here is a *nomination*,
confirmable only on genuinely new data.

### New code since Round 11

```
final/src/sweep/              the sweep package - see its RUNBOOK.md
  breadth.py                  Round 15 - effective breadth
  rates.py                    Round 14 - rate sensitivity (screened, rejected, kept)
  events.py                   Round 16 - earnings timing + tail shape
  factors.py  feature_ic.py  attribute.py  stats.py  outcomes.py
final/src/build_rate_features.py
final/src/build_event_features.py
final/data/rates/treasury_yields.csv
```

Panels are additive and never overwrite each other, so every prior result stays
reproducible from the panel it was built on:
`features_with_fundamentals_*` → `features_with_rates_*` → `features_with_events_*`.

### Six bugs, one pattern — read before adding a feature

| bug | how it presented | what caught it |
|---|---|---|
| NaN ranking (R13) | `argsort` sorts NaN last, so an 85%-missing column got top ranks and manufactured IC | asking what a mostly-empty column *should* score |
| NaN era split (R14) | one NaN made `.mean()` return NaN for a whole era, printed as "no estimate exists" | asking why an estimate would be missing |
| breadth estimator (R15) | assumed equal position variances; under invvol over vol quintiles reported 19.1 where truth was 5.0 | `capture > 1`, impossible by definition |
| merge_asof alignment (R16) | `merge_asof` resets the index, so `.sort_index()` is a no-op and six columns landed on wrong rows | a fire rate of 0.7% where cadence implies 64% |
| empty feature list (R17) | column missing from `PanelContext.want` → screened nothing, reported "no windows" | noticing it reported *nothing*, not *no signal* |
| inf in features (R17) | `pct_change` over zero revenue → 27k infinities; XGBoost takes NaN but rejects inf | three cells dying at training time |

**Every one passed its automated checks.** In every case the checks verified
*internal consistency* and the bug was in *correspondence to the outside world*.
Distribution-shaped checks — coverage, dispersion, range, monotonicity — cannot
detect a permutation of rows, because a permutation preserves every distribution.

**Standing rule.** Any feature whose expected magnitude or frequency is derivable
from something already known — a filing cadence, a sector count, a named company,
a physical bound — gets that number written into its acceptance check as an
explicit expected value with a tolerance. This is Gate A7c restated: **verify by
naming what should be there, not by counting.** Every automated check passed on a
2008 universe with no Apple in it.

### Where the Round 10–17 write-ups live

In the Claude Project (`pipe_dream`), not this repo:

```
claude/validation-gates.md                       gates + the DECISION BAR
claude/DATA-PIPELINE-HANDOFF.md                  pipeline contract
claude/2026-09-12-merge-asof-alignment-bug.md    bug post-mortem
universe/2026-09-09-*                            the Round 11 rebuild (6 docs)
backtest/2026-09-11-round12-sweep-results.md
models/2026-09-11-feature-ic-screen.md           Round 13
models/2026-09-11-rates-feature-screen.md        Round 14
backtest/2026-09-12-round15-breadth-results.md
backtest/2026-09-12-round15b-horizon-results.md
models/2026-09-12-sector-bet-decomposition.md
backtest/2026-09-12-turnover-and-what-the-ranking-actually-buys.md
models/2026-09-11-deployed-best-case-config.md   what the app is running
```

Pre-registrations sit alongside under `claude/`, written before each round ran.

## THE FEATURE-ADMISSION GATE CHANGED (2026-09-16). Read this first.

`final/src/build_shuffle_null.py`, `check_grid_offset.py`,
`sweep/scorecache.py` (`shuffle_col` / `shuffle_seed`).
Full write-up: `models/2026-09-16-shuffle-null-replaces-the-ic-gate.md`.

**IC is retired as a feature-admission gate.** Gabe: *"our thresholds are so
strict that they would exclude features already in the model."* He was right.

| feature | `sweep.cli features` t | |
|---|---|---|
| `volatility_60` | **−0.41** | 60.3% of XGBoost's importance |
| `momentum_20` | **+0.23** | production feature; flips sign on 16/40 grid offsets |

And across all 64 cells then scored, the rank correlation between a cell's
`mean_ic` and what it EARNED was **+0.019**. Zero. The best cell (2.94×) has IC
+0.0020; the highest IC anywhere (+0.0243) earns 1.49×; `volonly_xrank` has IC
−0.0145 and earns 2.04×. Every feature ever rejected on an IC threshold was
rejected on a statistic with no measured relationship to the objective.

### The replacement
- **Metric:** what the portfolio does (`mult_ratio`, `excess_cagr`,
  `info_ratio`, and `decile_volq_excess` for power).
- **Null:** refit the identical cell with the candidate column **permuted within
  each date**. Same marginals, same column count. NOT "drop the column", which
  changes the model's shape.
- **Gate:** beat the **80th percentile** of the null (Gabe's choice; 20%
  false-pass per feature).
- A shuffle source must be a CANDIDATE, never a production feature — permuting
  `momentum_20` measures the cost of DESTROYING information and would make
  anything look like a pass. `plan()` refuses it.

### A performance gate WITHOUT the null is worse than the IC gate
In the 84-cell sweep, **the best cell is a shuffled one**: `...shufaccel_2012`
at **3.309×**, beating the deployed model's 2.938× and every real config ever
scored here. A column of pure noise, permuted, produced the best backtest in the
grid. Never quote a backtest improvement for a feature without its null.

### accel_20 FAILED (20 draws, nominate era)
| metric | real | baseline | null p50 | null p80 | pctile | |
|---|---|---|---|---|---|---|
| mult_ratio | 2.013 | 2.796 | 1.850 | 2.113 | 70% | fail |
| excess_cagr | 0.0585 | 0.0871 | 0.0513 | 0.0626 | 70% | fail |
| info_ratio | 0.445 | 0.605 | 0.390 | 0.483 | 70% | fail |

Null on mult_ratio 1.919 ± 0.415. It is not neutral either: the null median
1.850 vs the deployed 2.796 means adding a 25th column costs ~a full multiple,
and accel_20's own information recovers almost none of it. **Not added to
`FEATURE_COLS`.**

### The backlog
23 candidates (5 rates, 8 events, 9 options, accel_20) were rejected on the
retired statistic and need rerunning under this gate. **Not naively:** at an
80th-percentile gate, k=23 yields ~5 false passes, so decide the correction
BEFORE the run. The shared-null shortcut (one null for all candidates, ~3.5h
instead of ~37h) assumes exchangeability across shuffle sources and is
**unverified** — only one candidate is materialised, so the check has not run.

## Round 19 (2026-09-16) — order information in a 20-day path, and accel_20

`final/src/screen_path_order.py`, `calibrate_path_order.py`,
`build_accel_feature.py`; registrations in
`claude/2026-09-16-order-information-preregistration.md` (+ Amendment A),
`...-amendment-b-decile.md`, `...-accel20-promotion-preregistration.md`;
results in `models/2026-09-16-order-information-in-20-day-paths.md`.

`momentum_20` is the SUM of 20 daily returns and is therefore blind to their
ORDER. Tested directly rather than by building an LSTM: order-aware statistics
on identical inputs, each paired against **its own 5 matched shuffles** (same
returns permuted, same sum, order destroyed), 4,911 daily cross-sections.

| | IC | traded tail | verdict |
|---|---|---|---|
| `slope_20` (trend) | +1.75 | **+0.33** | 9 of 10 order-free draws beat it. Nothing. |
| `accel_20` (2nd half − 1st half) | −1.74 | **−1.97** | 17/20 years one sign, emp p ≈ 0.18 |

All three registered reads returned INCONCLUSIVE. **|t| = 2.0 was the wrong
bar**: an exact leave-one-out permutation null (`calibrate_path_order.py`) shows
order-free control series reaching **2.47** at IC and 2.18 at the decile. A
near-miss of 2.0 is not a near-miss of significance here.

**Three control failures, all in the registration, two of them decisive:**
- The original gate would have reported a **PASS** — `slope_20` cleared +2.16
  and the shuffle cleared *higher* at +2.48. The conditional null is not centred
  at zero; Amendment A subtracts the control instead of vetoing on its level.
- Amendment B's positive control (`volatility_60`) is structurally invalid for a
  decile metric that **buckets on volatility**. Its FAIL gate was unreachable
  before the run started.
- `effratio_20` is permutation-invariant and was never order-aware. Its paired
  statistic is exactly 0.00000 in all 20 years — now a self-test, and proof the
  shuffle machinery is exact.

**Carry this forward:** at `decile_volq_excess`, 15 order-free shuffle series
reach median |t| 1.66 and max 3.86, against 1.09/2.51 for IC. Any decile screen
in this project that reads an **unpaired** t against a ±2 bar is using a
statistic whose null is roughly twice that wide.

### accel_20 is promoted as a CANDIDATE, not a feature
`features.CANDIDATE_FEATURE_COLS` is a new list, deliberately separate from
`FEATURE_COLS`: nothing reaches the deployed model by being listed there.
`build_accel_feature.py` adds the column to the fundamentals panel in place
(arrow-native, schema byte-identical to sibling panels, 99.3% finite) and
refuses to run if `accel_20` ever appears in `FEATURE_COLS`. Feature set `path`
screens only that one column, per the Round 14/16 convention.

### accel_20 FAILED its screen, and found a defect in the screen
`python3 -m sweep.cli features --era nominate --features path --horizons 40`
returned t +1.88 (gate: 2.0), permutation p 0.080 (gate: 0.05) and IC **+0.0226
— the wrong SIGN** (gate: negative, matching the promotion evidence's −0.0033).
Three of four gates fail. accel_20 is **not promoted**, is not traded,
`FEATURE_COLS` is unchanged, and the path-order line closes as a negative.
`promotion_trial_count = 7` is spent; retesting it would be an eighth trial.

**The sign gate earned its place.** Chasing the flip down eliminated the label
(same one), neutralisation (raw is −0.0009, neutralised −0.0033, both negative),
the feature definition (asserted identical to 1e-12) and the universe. The cause
is **which 82 days the screen looks at**.

## THE GRID-OFFSET PROBLEM — read this before promoting any feature

`sweep/feature_ic.py` measures IC on non-overlapping windows, one cross-section
every `horizon` days. Correct instinct — overlapping days inflate a naive t by
~sqrt(40). But there are **forty equally-valid grids**, one per starting offset,
and the screen silently uses **offset 0**.

Nomination era, h=40, all 40 grids (`final/src/check_grid_offset.py`):

| feature | all 3,272 days | offset 0 | grid min | grid max | sign flips |
|---|---|---|---|---|---|
| `accel_20` | −0.0011 (t −0.54) | **+0.0218 (t +1.83)** | −0.0350 | +0.0272 | **21/40** |
| `momentum_20` | −0.0059 | +0.0031 | −0.0388 | +0.0170 | **16/40** |
| `volatility_60` | −0.0101 | −0.0092 | −0.0174 | −0.0034 | 0/40 |
| `pct_from_high_252` | +0.0153 | +0.0187 | +0.0041 | +0.0251 | 0/40 |

Stable for features with a real effect; a **coin flip for features near zero** —
exactly the ones a screen exists to judge. Two of accel_20's forty grids would
have cleared |t| >= 2; two others would have cleared it with the opposite sign.

**Does NOT invalidate** the past negatives (rounds 12/14/16 concluded "nothing",
and a null feature reads null on most grids). **Does invalidate** any near-miss,
narrow pass, or claim about a weak feature's sign or magnitude — `momentum_20`
is a production feature and flips on 16/40 grids.

**Rule:** run `check_grid_offset.py` before promoting anything on a
`sweep.cli features` result. Non-zero sign flips means the result is not
evidence. The durable fix — average over offsets, or use all days with
Newey-West as `screen_path_order.py` does — is NOT yet implemented.

## Sector enrichment (2026-09-16) — the null must be volatility-stratified

`final/src/sweep/enrich.py`, `final/src/build_sector_enrichment.py`,
`out/sector_enrichment.json`, app → Stock → Sector Bets.

A hypergeometric enrichment test over the model's picks, the same test used for
GO terms. **The naive version is wrong here.** The construction takes the best
name in each of five trailing-volatility quintiles, so a group's pick count is
a sum of five *one-draw* hypergeometrics, not one five-draw hypergeometric. The
two have identical expectations (equal-sized quintiles) and different
dispersion; for a group that sits inside one quintile — utilities low, biotech
high, which is most of what a fine taxonomy separates — the flat version is
over-dispersed and understates a real concentration by ~10–50×. Both are
reported so the size of the correction stays visible. Same lesson as
`decile_volq_excess`: an unmatched null measures the selection.

Every p carries a Benjamini-Hochberg q across all groups at that level (up to
439 at `sicindustry`). Exact Poisson-binomial tails, no normal approximation,
numpy only. Invariant checked at build and in the app: **Σ expected over all
groups == number of draws** (620 pooled, 5 live).

Pooled over 124 windows / 620 draws, **enriched in BOTH eras** (q < 0.10 in
2007-2019 *and* independently in 2020-2026):

| level | groups |
|---|---|
| sector | Healthcare, Energy |
| famaindustry | Pharmaceutical Products, Petroleum and Natural Gas |
| industry | Biotechnology |
| sicindustry | Pharmaceutical Preparations |

All eras, sector: Healthcare 124 vs 72.4 expected (1.71×, p 9.6e-10),
Technology 1.32× (p 1.0e-3), Energy 1.54× (p 1.1e-4). Significantly **avoided**:
Industrials (q 0.0012), Financial Services / Real Estate / Basic Materials /
Utilities (q ≈ 0.015).

This is descriptive — it reports what the model picked, it selects nothing — so
the hold-out rule does not bind and the eras are split rather than pooled.
**It says nothing about whether those bets made money**; Round 13 already
established that sector-neutralising removes essentially all of the edge, so
this names the bet rather than validating it.

**Today's five picks are tested live in the app and are near-powerless by
design** — a group needs 2 of 5 before BH can call anything at 145 groups. An
empty table there is the expected table, not evidence of no tilt.

### Also this round
- **Ticker → group lookup.** `sector_view.ticker_groups()` returns one ticker's
  group at all six levels beside the pooled enrichment for each, on both the
  ticker query and the Sector Bets tab. The gap between levels is the useful
  part: XOM sits in Energy (1.54x, q 6.6e-4) but in Oil & Gas Integrated, where
  the model has bought **0** against 1.63 expected — the energy bet is E&P, not
  integrateds.
- All six taxonomy levels are now displayed (`sector` → `sicindustry`);
  `sic2`/`sic3` render as `"283 · Pharmaceutical Preparations"` via
  `taxonomy.display_label_map()`, never as a bare code. Neutralisation
  statistics still stop at four levels — that limit is about regression, not
  counting.
- `taxonomy._table/load/sic_names/display_label_map` are now `lru_cache`d; the
  sector tab was re-reading a 20k-row CSV twelve times per rerun.
- **Silent-failure fix.** `sector_view.eligible_universe()` imported
  `continuous_walkforward_pit`, which imports xgboost at module scope; a bare
  `except` turned any import failure into an empty universe, and the tab then
  showed every group at 100% active weight with no warning. It now reads
  `pit_universe.parquet` directly and `describe()` returns `_universe_ok`,
  which the app renders as a blocking error.

## Round 18 (2026-09-16) — the app shows two models, and what that cost

### What changed on the app

The Stock tab now renders **two signals side by side** plus **SPY and USMV**:

```
PRIMARY    q75    price_fund_h40_q75_trd_xgb_d3e01r100_expanding_cap500k_pit_s40
CANDIDATE  xrank  price_fund_h40_xrank_trd_xgb_reg_d3e01r100_expanding_cap500k_pit_s40
```

Identical features (24), identical hyperparameters (depth 3, eta 0.1, 100
rounds, most recent 500k labelled rows), identical construction (top 1 from
each of 5 volatility quintiles, inverse-vol weighted, next-open entry, 40-day
hold, no stop). **The only difference is the training target.**

| | 2007-2019 (in-sample) | 2020-2026 (hold-out) |
|---|---|---|
| q75 | +8.71%/yr, 2.796× SPY | **+7.33%/yr, 1.526×** |
| xrank | +6.35%/yr, 2.132× SPY | **−4.28%/yr, 0.771×** |

The candidate is **displayed, not traded**, and every surface that renders it
carries the hold-out number. Nothing blends the two scores, and nothing should:
overlap between them is near-foregone given how much they share.

USMV is on the chart because Round 18's attribution says the model's edge is a
**low-volatility tilt** (score-vol correlation −0.134; 88% of the volatility
bucketing's benefit is higher arithmetic return, not reduced variance drag)
plus a tech/healthcare sector bet. Both are purchasable for an expense ratio.
Putting the min-vol ETF on the same axes is the honest question in front of the
model every time it is opened.

### Two live-vs-backtest divergences found and fixed

`current_signal_pit.py` had drifted from the cell whose backtest the app
quotes. Both changed today's picks:

1. **Label basis.** The cell id ends in `_trd_` — trained on
   `forward_return_tradable_40` (`close[t+H] / open[t+1]`). The live script was
   training on `forward_return_40` (`close[t]`-to-`close[t+H]`), which credits a
   move that was over before you could trade it. Now `TRADABLE_LABEL_COL`.
2. ~~**Candidate pool.**~~ **RETRACTED THE SAME DAY — this was not a fix, it
   was a regression.** The claim was that the sweep scores every name in the
   day's point-in-time universe and lets XGBoost handle missing features
   natively, so the live script's `dropna(subset=FEATURE_COLS)` was excluding
   names the backtest held. That is false. `scorecache._run_cell` contains no
   filter of its own, but `PanelContext` calls

   ```python
   W.load_panel_prepared(path, want, list(FEATURE_COLS), horizon)
   ```

   whose third argument is `filter_cols` and which "keeps only rows with
   complete features". Every incomplete row is gone before `_run_cell` ever
   slices a test set. Proof: the deployed cell's 154,839 cached rows contain
   **zero** NaN `volatility_60`.

   The error was reading `_run_cell`, finding no filter there, and concluding
   there wasn't one — without checking where its `frame` came from. Same shape
   as the six bugs in the table above: internal consistency verified,
   correspondence to the rest of the pipeline not.

   **What it cost, before Gabe caught it by looking at the picks.** The change
   admitted 59 names (3.5% of the universe). `volatility_60` is itself one of
   `FEATURE_COLS`, so a name missing it reaches `_bucket_idx` as NaN — and
   `_bucket_idx` initialises its output to zeros and overwrites only the finite
   entries, so **a NaN volatility is filed in bucket 0, the LOWEST-volatility
   quintile**. An unknown volatility is not a low volatility. On 2026-09-08 two
   of the five deployed picks (`COAG`, 3 NaN features; `KARD`, 5 including
   `volatility_60`) were names that should never have been scored, and `KARD`
   displaced the genuine low-vol pick in **both** signals. The model's one
   demonstrated edge is a low-vol tilt, so the defect attacked precisely the
   part that works.

   Reverted. The complete-price-feature filter in `current_signal_pit.py` is
   deliberate and load-bearing, and now runs once, up front, in
   `_modelling_frame()` — before the label ranking, the training mask and
   today's candidate pool, mirroring where the sweep applies it. A hard
   `RuntimeError` guard asserts no selectable name has a NaN `volatility_60`.

   **Latent trap worth knowing separately:** `_bucket_idx`'s NaN-to-bucket-0
   behaviour is still there in the shared backtest path. It is harmless today
   because the panel filter means no NaN vol ever reaches it, but it is one
   filter change away from being live again, and it fails silently rather than
   loudly. Fixing it touches `simulate()` and therefore every backtest number,
   so it is left as a flagged decision rather than changed in passing.

Divergence 1 was real and the fix stands. Divergence 2 was not a divergence at
all, and "fixing" it introduced a worse defect than the one it claimed to
remove — see the retraction above.

**Standing additions, both earned the hard way in one afternoon:**

- A live script that names a backtested cell id must be **diffable against that
  cell's config, field by field**. The feature list already was (24 columns,
  same order, verified). The label basis was not, and nothing caught it for
  five days.
- Before claiming the production path and the backtest disagree, **trace the
  backtest's data to where it is loaded, not to where it is used.** A filter
  applied at panel load is invisible at the point of use, and the absence of a
  filter in the function you happen to be reading is not evidence that there
  isn't one. The cheap check that would have settled it in seconds: the score
  cache is on disk, so count the NaNs in it.

### New / changed files

```
final/src/current_signal_pit.py        rewritten -- trains BOTH signals from one
                                       panel load; VARIANTS is the single place a
                                       signal is defined; --only <key> for one
final/src/build_app_benchmarks.py      NEW -- out/app_model_comparison.json:
                                       equity curves + summaries for both cells
                                       against SPY and USMV, both eras
final/app/lib/pit_model.py             rewritten -- variant-aware; both-model
                                       ticker query; comparison loader
final/app/lib/paths.py                 + SHARADAR_DIR, PIT_UNIVERSE_PARQUET,
                                       BENCHMARKS_DIR
final/app/app.py                       Stock tab rewritten; Secondary Models tab
                                       and every XGBoost/LSTM cross-check removed
final/app/README.md                    rewritten for the two-signal layout
```

New outputs: `out/current_signal_pit_xrank.csv`, `..._xrank_meta.json`,
`out/current_signal_compare.json`, `out/app_model_comparison.json`,
`out/models/xgb_pit_xrank_model.json`, `data/benchmarks/USMV.csv`.

### The Secondary Models tab is gone

The non-PIT price-only XGBoost and LSTM were trained on the pre-Round-11
universe — missing a third of the eligible 2008 names, 89% of them since dead.
Every number they produced is measured on data now known to be defective, so
showing them beside point-in-time picks invited a comparison that was not valid
in either direction. `src/current_signal.py` and `src/lstm_current_signal.py`
are still on disk; nothing in the app calls them, and the "Retrain ALL models"
sequence no longer runs them.

### `build_app_benchmarks.py` touches the hold-out, and why that is allowed

Every other command in `sweep/` refuses `--era holdout`. This one evaluates it,
under three constraints written into the file:

- The cell list is **hard-coded**. No grid, no glob, no `--only`. A report over
  a fixed set of two is not a search.
- Both hold-out numbers were **already spent and published** — q75 in Round 13,
  xrank in Round 18. Re-plotting a number already paid for costs nothing.
- Adding a third cell to that list to "see how it does" is the exact search the
  file is shaped to prevent. Don't.

The rule is unchanged: nothing new may be confirmed on 2020-2026.

### The number to read everything else against

Ten cells differing from the deployed one **only by a turned knob** (training
window, training cap, tree depth, market-cap tier, label basis) — same features,
same label, same model — span **−8.01 to +9.15 %/yr excess, mean +3.40,
sd 5.03**. The deployed cell's +8.71 is 1.06 sd above its own family mean.

The app prints this band above both equity charts and beside today's picks.
Any gap smaller than it — including the gap between the two plotted models — is
not evidence of anything. `build_app_benchmarks.py` recomputes it from
`out/sweep/live_nominate.csv` rather than hardcoding it, so it tracks the grid.

## Known gaps — read before assuming something "just works"

- **`final/models/final_model_calls.pkl` and `final_model_puts.pkl` still
  have no DIRECT reproduction script** — the original round-1/round-2 model
  comparison and hyperparameter search that produced them was run ad-hoc in
  a prior Claude cloud session's sandbox and never saved as a checked-in
  script, and these two files are deliberately **left tracked in git** (not
  gitignored) because of that. **Partially mitigated 2026-09-02**:
  `final/models/pit_integration/train_options_pit_model.py` independently
  reconstructs the Round 2 protocol (4 purged folds, 25-combo power/alpha
  grid, same holdout) from scratch, and its "OLD" variant's backtest output
  (via `backtest_pit_variants.py`, fixed hyperparameters) reproduces the
  existing documented backtest numbers exactly — a working, validated
  substitute for the original ad-hoc process, though it picked a different
  hyperparameter combo on its own CV re-tune (power=1.2/alpha=0 vs. the
  originally-documented 1.4/0.001) and didn't beat the benchmark on
  deviance the way the original Round 2 claimed to — an unresolved
  discrepancy, see `models/options-premium-model-design.md`. Extracting a
  clean `scripts/train_options_premium_model.py` from this is still a real
  to-do, not done here.
- **`build_training_data_expanded.py`, `optimizer_backtest_expanded.py`,
  and related expanded-universe options scripts are referenced by name in
  `models/options-premium-model-design.md` but were not confirmed present
  in this repo as of 2026-08-30** — the design doc itself flags that "the
  device link to Gabe's machine dropped partway through committing the
  last batch of these files... whether they landed in the actual folder
  needs to be verified/finished next session," and that verification does
  not appear to have happened yet. Check `final/scripts/` and `final/data/
  options_raw/expanded/` directly before assuming these exist.
- **Puts (options model) has no working model.** Don't build on top of a
  puts signal assuming it's just unoptimized — it was tested and
  genuinely underperforms the "market is fairly priced" benchmark.
- **The options premium model's live scoring path (`live_score.py`,
  `app/lib/options_model.py`) still scores off the plain current-universe
  screen, NOT the PIT-integrated version.** The 2026-09-02 PIT/fundamentals
  integration (see workstream 3 above) was a research pass only — it
  wasn't adopted (no clear win) and nothing in the live app or
  `live_score.py` was changed. If a future session wants to actually adopt
  it, `final/models/pit_integration/` has the pipeline, but the current
  live behavior is unchanged from before this pass.
- **The options model's universe was built from TODAY's roster, not a
  point-in-time-correct one — PARTIALLY addressed 2026-09-04, still a
  real gap.** The 2026-09-04 rebuild (see workstream 3 above) widened PIT
  fundamentals coverage to 1,266 tickers and applies a point-in-time
  market_cap/price eligibility floor at each option's own entry_date, for
  both calls and puts — closing the *fundamentals-eligibility* half of
  this gap. What's still NOT point-in-time-correct: the underlying
  option-chain pull itself (`expanded_universe_tickers.txt` and friends)
  is still built from today's roster — a company that had tradeable
  options in, say, 2019-2021 before later being removed from the current
  expanded-universe list is a real, still-uncaptured source of
  survivorship bias distinct from the eligibility-floor fix. Flagged in
  both the design doc's PIT-integration section and
  `models/2026-09-04-buy-no-buy-options-integration.md` as a real next
  step, not resolved.
- **Survivorship-bias correction (workstream 4) is real and now the
  primary signal, but still has known, documented incompleteness** — not
  every gap ticker has usable Sharadar coverage (of the current 264-file
  set, some have no fundamentals data at all), some ticker-symbol
  quarantine calls trade off completeness for safety by design (see
  `validate_gap_coverage()`), and the stop-loss percentage (15%) was
  chosen from a single backtested sweep, not cross-validated across
  independent time periods. Treat every backtest number in this repo,
  PIT or not, as carrying transaction-cost/slippage-free and small-sample
  caveats — see `backtest/survivorship-bias-correction-results.md` for
  the full, current list.
- **The "Retrain ALL models" and per-tab "Retrain" buttons in the app do
  NOT refresh `scripts/fundamentals_raw/` (SEC EDGAR) or
  `scripts/fundamentals_raw_delisted/` (Sharadar)** — those are separate,
  much-less-frequent pulls Gabe runs directly (see the reproduction table
  below). A "retrain" only rebuilds feature panels and retrains models
  off whatever raw fundamentals are already on disk.
- Several `.DS_Store` files are currently **tracked** in git (visible as
  "modified" in `git status`). Untracking them (`git rm --cached
  '**/.DS_Store'`) is a one-time cleanup Gabe should run himself — not
  done here to avoid touching the git index without being asked.
- As of this writing there are uncommitted local modifications to
  `final/src/backtest.py`, `final/src/current_signal.py`,
  `final/src/features.py`, and several `final/out/*` result files —
  pre-existing local changes, not something to assume is "the last
  committed state." Run `git diff` before trusting `git log`'s picture of
  the current pipeline. This is now ALSO true of the whole PIT track
  (`features_pit.py`, `fundamentals_features_pit.py`,
  `continuous_walkforward_pit.py`, `price_discontinuity.py`,
  `pit_universe_continuous.py`, `current_signal_pit.py`) and the app
  changes (`app.py`, `app/lib/pit_model.py`) delivered 2026-09-02 —
  written to Gabe's files but, per standing constraint #5, not committed
  by any AI assistant. Don't assume these are in git history yet. The same
  applies to `final/models/pit_integration/` (new, 2026-09-02) and
  `final/data/options_pit_fundamentals_slim.parquet` and
  `final/data/training/options_calls_training_pit.parquet` — the latter
  two are large generated data files and should probably stay gitignored
  rather than committed; the scripts under `pit_integration/` are the part
  worth adding to git. This also now includes `final/models/hyperparameter_
  retune/` (new, 2026-09-02, same day) — two scripts + README + a
  `results/` subfolder of JSON/CSV, all worth adding to git (no large
  generated data files this time, just results).

## Reproducing every gitignored path

Everything below except the two exceptions already noted (`final_model_
calls.pkl`, `final_model_puts.pkl` — deliberately still tracked) is
excluded from git via `.gitignore` and reproducible from what's already in
the repo. **All of these scripts must be run directly on Gabe's own
machine, not through an AI assistant's sandboxed/proxied tools** — every
one of them depends on a data source (yfinance, SEC EDGAR, DoltHub) that's
blocked from Claude's cloud sandbox by network restrictions, and DoltHub
specifically is also blocked from the device-bridge shell by an
organization-level allowlist. See each script's own docstring for the
specific confirmed-blocked details.

| Gitignored path | Size | How to regenerate |
|---|---|---|
| `final/scripts/td_data_local/`, `td_data_local*.tar.gz` | ~700MB | `python3 final/scripts/local_data_pull.py` (yfinance, current 1,619-ticker universe) |
| `final/scripts/td_data_delisted/`, `fundamentals_raw_delisted/` (Sharadar-sourced) | 12MB / part of 41MB | `python3 final/scripts/sharadar_data_pull.py` (requires `SHARADAR_API_KEY` env var and an active Sharadar subscription — see the script's docstring). As of 2026-09-02: 264 gap-ticker files landed (158/211 of the original set + a 2007-2008-extension batch). Old path, kept for history / as a fallback if a ticker has no Sharadar coverage: `local_data_pull_delisted.py` then `local_data_pull_delisted_v2.py` (yfinance + free Kaggle "Huge Stock Market Dataset" — **partial coverage only**) |
| `final/scripts/fundamentals_raw/`, `fundamentals_raw.zip` | ~370MB | `python3 final/scripts/local_fundamentals_pull.py` (SEC EDGAR, current universe) |
| `final/scripts/fundamentals_raw_delisted/` | 41MB | `python3 final/scripts/local_cik_lookup_delisted_v3.py` **(v3 only — v1 and v2 each have documented, real bugs; do not run them; see `backtest/survivorship-bias-correction-results.md` Round 2b/2c)**, then `local_fundamentals_pull_delisted_v2.py` |
| `final/data/options_raw/*.parquet`, `option_chain.csv`, `volatility_history.csv` | 26GB | Requires the `options_raw/.dolt` clone below first. Then: `dolt table export -f csv` the `option_chain` and `volatility_history` tables, filter to the target ticker universe, convert to Parquet. This was done via an ad-hoc `dd`-byte-range-slicing + DuckDB pipeline (device-bridge shell's 45-second-per-call limit forced chunking) — **no single checked-in script does this end to end**; see `models/options-premium-model-design.md`'s "Access mechanics" and "Dataset built and validated" sections for the exact commands used, and `final/scripts/update_options_history.py` for the *incremental* update path (this one IS a real, run-directly script, for pulling new rows since the last export). |
| `options_raw/.dolt/` | 8GB | `cd pipe_dream && dolt clone post-no-preference/options options_raw` (requires the `dolt` CLI: https://docs.dolthub.com/introduction/installation, and network access to dolthub.com run directly, not through an AI assistant's tools) |
| `final/data/training/options_calls_training.parquet`, `options_puts_training.parquet` | 44MB | Built from the DoltHub export above via entry/exit-mechanics + feature-join logic described in detail in `models/options-premium-model-design.md`'s "Training dataset built" section — **no single checked-in script name was confirmed for the non-expanded version**; `build_training_data_expanded.py` exists for the expanded-universe version (see "Known gaps" above re: whether it actually landed in this repo). |
| `final/data/garch_volatility.parquet` | 1.9MB | Walk-forward GARCH(1,1) via the `arch` package (`pip install arch`) on `final/scripts/td_data_local/*.csv` — expanding-window refit every 21 trading days per ticker. Exact algorithm in `models/options-premium-model-design.md`'s "GARCH volatility" section. ~28.5 min wall-clock for the full universe as last measured. No single checked-in script name confirmed — same caveat as above. |
| `final/out/features.parquet`, `features_pit.parquet`, `features_with_fundamentals_beta.parquet`, `features_with_fundamentals_pit.parquet` | ~700-900MB each | `python3 final/src/features.py` / `features_pit.py`, then `fundamentals_features_beta.py` / `fundamentals_features_pit.py` — run from `final/src/`, not `final/scripts/`. Requires the price/fundamentals data above to already exist. `features_pit.py` also writes `out/gap_tickers_used.json` (the exact gap-ticker set found on disk that run) and prints its `price_discontinuity.py` break-detection results — read the console output, don't assume zero breaks. **Must run on Gabe's own machine** — these panels are large enough to OOM a device-bridge shell (see workstream 4 above). |
| `final/out/models/` (xgb/lstm checkpoints + norm stats), `current_signal_pit.csv`/`current_signal_pit_meta.json` | 532KB+, regenerates every run | Rebuilt automatically by `final/src/current_signal.py`, `current_signal_gated.py`, `lstm_current_signal.py` (secondary/legacy), and `current_signal_pit.py` (**primary**, as of 2026-09-02 — writes `out/models/xgb_pit_augmented_model.json` plus `out/current_signal_pit.csv`/`.._meta.json`) — these all retrain point-in-time on every invocation, so this directory is expected to churn and isn't meant to be a stable checkpoint across commits. |
| `pipe_dream.egg-info/` | 16KB | `pip install -e .` from the repo root |
| `__pycache__/`, `*.pyc` | — | Regenerates automatically the next time Python imports anything; no action needed |

## Future plans

**The Sharadar/PIT integration described in earlier versions of this
section is DONE** — see workstream 4 above for current status. What's
actually open now:

- **Options-model PIT/fundamentals integration was attempted 2026-09-02**
  (see workstream 3 above) — no clear win, not adopted into production.
  Real follow-ups if this gets revisited: (a) rebuild the options
  training-data ticker list from a point-in-time-correct universe rather
  than today's roster (the integration pass never touched WHICH tickers
  are included, only added features/eligibility for the existing 496); (b)
  combine with the expanded (1,284-ticker) universe rather than keeping
  them isolated; (c) root-cause why the from-scratch CV retune picked
  different hyperparameters and didn't beat the benchmark on deviance the
  way the original Round 2 did.
- **A much deeper hyperparameter search was also run 2026-09-02** (same
  day, separate request) — confirmed production hyperparameters
  (power=1.4, alpha=0.001) rather than finding a better setting. See
  workstream 3 above. If GAM is ever revisited despite its backtest
  failure here, a real speed fix (fewer spline terms, a feature-selection
  pass before GAM, or accepting a much longer run) is needed before a
  Tweedie-scale grid becomes practical, and the −76.63%-at-first-timepoint
  pattern deserves an actual learning-curve check rather than the
  by-pattern diagnosis this pass used.
- **Adjusted-vs-unadjusted-close question, still open**:
  `sharadar_data_pull.py` defaults to Sharadar's `closeadj` (split/
  dividend-adjusted close) for momentum/volatility feature consistency,
  but the original Yahoo delisted-ticker pull used unadjusted close —
  worth a second look at whether `features.py`/`features_pit.py`
  implicitly assume one or the other before trusting momentum/volatility
  features that mix old (Yahoo-sourced) and new (Sharadar-sourced) closes
  across the combined universe. Flagged, not yet resolved.
- **Not every gap ticker has Sharadar coverage.** Of the 264 files
  currently on disk, some have price but no fundamentals (or vice versa);
  `validate_gap_coverage()`'s trailing-history check quarantines anything
  that doesn't clear `MIN_TRAILING_DAYS`, but chasing the remaining gaps
  ticker-by-ticker (the way `KNOWN_DELISTING_DATES` was hand-built
  earlier in this project) hasn't been revisited since Sharadar landed.
- **Stop-loss percentage cross-validation.** Round 8's 15% figure comes
  from ONE backtested sweep over ONE universe/time range (2007-2026,
  expanded universe). A robustness check against the sp500-only universe
  found a different nominal optimum (10%, on a much smaller/worse-
  performing universe overall) — worth understanding whether that's
  genuine universe-dependence or just sampling noise before treating 15%
  as settled for good, if this becomes a priority again.
- **`baseline_stoploss`'s own optimal stop percentage** was never swept
  (Round 8 only swept `augmented_stoploss`, since that's the model
  actually promoted to primary) — a natural, cheap follow-up if wanted
  for comparison (`--mode baseline_stoploss_sweep`, same lean re-
  simulation, no retraining needed).

**Independent of the HMM joint model — can be piloted anytime (added
2026-08-30):**

- **Stop-limit exits within the 40-day hold.** The backtest currently uses
  a fixed 40-trading-day hold with no dynamic exit — already flagged as a
  known limitation since `models/final-buy-no-buy-model.md`'s v3 ("Fixed
  40-trading-day hold in the backtest — not a dynamic exit"). Idea: exit a
  pick early if its price falls too far below entry at any point during
  the 40-day window, instead of always riding to the fixed exit date.
  Needs (a) a concrete stop rule — a flat % drawdown, or something
  volatility-scaled off the existing `volatility_20`/`volatility_60`
  features so the stop is wider for names that are normally choppier; (b)
  a walk-forward-safe way to evaluate it — has to check price day-by-day
  within the hold using only information available up to that day, not
  just the eventual `forward_return_40` value the backtest computes today,
  which only knows the day-40 close; and (c) a decision on what happens to
  the freed-up capital after a stop-out — sit in cash for the rest of that
  window, or roll into the next-best-ranked pick. This is a direct
  extension of the existing walk-forward backtest infrastructure
  (`final/src/backtest.py` / `backtest_pit.py`) — no new data source or
  model needed, so it doesn't have to wait on anything else in this list.
- **Time-series foundation models (TSFMs) — idea from Gabe, 2026-09-01.**
  Pretrained sequence models like Chronos-2, TimesFM 2.5, and MOIRAI-2.0,
  and the finance-specific Kronos. Researched, not yet built. Bottom line:
  generic TSFMs pretrained on non-financial data (weather, web traffic,
  retail) are a weak fit zero-shot for daily equity returns — a 2026 study
  found their gains over a random-walk benchmark were statistically
  significant in only 2 of 10 tested equity/model pairs, and a supervised,
  asset-specific baseline (iTransformer) beat every pretrained TSFM on
  META specifically. A domain-specific model (Kronos, pretrained on 12B+
  real K-line records) beats generic TSFMs by a wide margin on financial
  benchmarks, meaning finance-specific pretraining data matters more than
  model architecture. There's also a documented risk of inflated benchmark
  results from train/test overlap between TSFM pretraining corpora and
  common evaluation datasets — a reason to be skeptical of any TSFM's
  self-reported numbers without checking for this. **Where this could
  actually fit this project:** not the core buy/no-buy classifier, which
  is a classification task on 11 hand-engineered features, not a raw
  sequence-forecasting task a TSFM is built for. The better fit is the
  options premium model (workstream 3), which already needs a *predicted
  distribution* over the underlying's future price — exactly the shape of
  output a TSFM like Chronos-2 produces natively (probabilistic, not point
  forecasts). If piloted, do it there, fine-tuned or few-shot-adapted on
  this project's own tickers rather than used zero-shot, and benchmark
  against the existing Tweedie GLM rather than assuming it's better by
  default.

**Originally gated behind finishing the HMM joint model (workstream 2),
per Gabe's framing as of 2026-08-30 — that gate is STALE as of 2026-09-02.**
Workstream 2 concluded by being retired from the app rather than
"finished" in the sense this section originally meant, so these ideas are
probably unblocked now, but that's an inference, not a decision Gabe has
made explicitly — confirm priority with him before starting any of these
rather than assuming the list below is still accurate:

- **Gabe's own retrospective on the LSTM:** the original hope was that an
  LSTM, given raw trailing sequences, would learn something like implicit
  technical analysis — pattern recognition over price/volume history that
  hand-built features don't capture. In practice it hasn't shown a clear
  edge over XGBoost, and XGBoost's own feature importances show the
  model's real edge is overwhelmingly driven by trailing realized
  volatility (60.3% on `volatility_60` alone at the 40-day horizon) —
  i.e., a simple, already-hand-engineered signal is doing most of the
  work, not anything pattern-like the LSTM might have discovered on its
  own.
- **Behavioral transition matrices.** In behavioral-science analysis,
  once a continuous stream of behavior is discretized into a small set of
  states, a transition matrix (P(next state | current state)) is a
  standard next step. **This already exists in this project in one form**
  — the regime-gate HMM (`final/src/regime_signals_beta.py`) is literally
  a 2-state Markov model with a transition matrix, just applied once, at
  the whole-market level (SPY returns), to gate model blending. Gabe's
  idea is a natural generalization of that same tool downward: build
  per-stock or per-sector behavioral states (not just one market-wide
  regime) and their transition dynamics, as a feature source or standalone
  signal in its own right.
- **Unbiased "behavioral syllable" extraction (MoSeq-style).** MoSeq
  (Datta lab; the class of tool `moseq2`/similar packages implement) uses
  an autoregressive HMM over continuous 3D pose data to discover brief,
  statistically-defined, recurring "behavioral syllables" *unsupervised*
  — no human-imposed labels, no hand-built ethogram. The direct analogy
  here: instead of hand-engineering momentum/volatility features (or
  hoping an end-to-end LSTM discovers structure implicitly, per the point
  above), fit an AR-HMM (or a modern equivalent — a switching linear
  dynamical system, or a sequence model with a discrete bottleneck) directly
  on raw per-ticker price/volume trajectories to let the model discover
  its own small vocabulary of recurring short-timescale "market behavior
  syllables," then use the discovered syllable sequence and its transition
  statistics as a feature or signal. This is architecturally close to what
  the regime-gate HMM already does — the novel part is applying it
  per-ticker (or per-sector) at a shorter timescale, unsupervised, instead
  of once for the whole market.
- **"Wins Above Replacement" for stocks.** A single portable score per
  ticker (or per model), analogous to the baseball sabermetric: how much
  better did this pick perform than a defined "replacement level" baseline,
  aggregated across every time it was picked (or could have been picked).
  **This project already has natural replacement-level baselines to build
  from** — SPY buy-and-hold, and the "universe average return" naive
  baseline already reported in every backtest table (see
  `backtest/dollar-simulation-results.md` and
  `models/options-premium-model-design.md`'s backtest tables). Formalizing
  either as the WAR denominator, computed per-ticker across all trials
  rather than per-trial across the whole portfolio, would let you ask "is
  this model adding value on this specific stock/sector" rather than only
  "did this portfolio beat SPY this year" — useful both for model
  diagnosis and for comparing against a colleague's differently-built
  model on shared tickers.

Both the syllable-extraction and transition-matrix ideas are also a
reasonable framework for **directly comparing against a colleague's
differently-architected project** later, if that comes up — a
syllable/transition-matrix representation could serve as a shared
"language" to compare two structurally different models' learned dynamics
against each other, rather than only comparing their final backtest
numbers.

## Where the fuller history lives

The detailed, dated, decision-by-decision narrative for every workstream
above — including results tables, bugs found and fixed, and the reasoning
behind every non-obvious choice — lives in markdown docs in the Claude
Project attached to this work (not as files in this git repo):

- `models/final-buy-no-buy-model.md` — the core classifier, full detail
- `models/fundamentals-beta-results.md` — the augmented model + HMM gate
- `models/options-premium-model-design.md` — the options premium model,
  start to finish (long — this is the single most detailed doc in the
  project)
- `backtest/dollar-simulation-results.md` — the core model's backtest,
  full methodology and numbers
- `backtest/2026-ytd-hmm-gated-sequential-results.md`,
  `backtest/2026-ytd-pit-blend-and-last-80-days-results.md` — recent
  live-signal backtests
- `backtest/survivorship-bias-correction-results.md` — the bias-correction
  effort, including the Sharadar decision and reasoning
- `universe/2026-08-27-expanded-universe-methodology.md` — how the
  1,619/1,620-ticker universe was built
- `signals/2026-08-25-top-10-buy-list.md` — a dated snapshot of live
  model output
- `models/2026-09-04-buy-no-buy-options-integration.md` — the 2026-09-04
  options-model rebuild + selling-premium pivot, six rounds in one doc
  (most-recent-round-first): survivorship-bias/split-rescale fixes, the
  buy/no-buy-gate and strike/duration dead ends, the too-good-to-be-true
  puts backtest and how it was diagnosed down to real root causes, and
  the modest signal that survived cleaning

If you're an AI assistant with access to a "Projects" tool tied to this
work, read those directly rather than relying on this file's necessarily
compressed summaries above.
