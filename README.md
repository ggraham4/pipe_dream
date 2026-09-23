# pipe_dream: current state of the project

**Consolidated 2026-09-23 by `pipe-dream-readme-manager`, first full sweep.**
This is the one current-state document. It merges every branch's docs, the
coordination ledger, handoffs and project memory, and the newest source wins
where two disagree. Everything that lost is listed in [Superseded](#superseded)
at the bottom.

How to read the tags:

- **landed** means the claim is on `integration` (29eb67b).
- **in flight** means it comes from an unlanded branch or from uncommitted files
  in a worktree. In-flight claims never describe current state. They live in
  [In flight](#5-in-flight).
- Paths written as `branch:path` exist only on that branch or worktree.
- "Project doc" means a markdown doc in the Claude Project, not in this repo.

`AGENTS.md` is now only the standing constraints and a pointer to this file.
Coordination rules for parallel sessions are in `~/.claude/CLAUDE.md` and
`~/.claude/pipe_dream-coordination/LEDGER.md`, both outside git.

---

## 1. What this project is

This is Gabe's personal, from-scratch quantitative trading research project.
The core question: can a model identify stocks likely to outperform over a
multi-week (40-trading-day) horizon, backtested honestly with point-in-time
discipline? That means no look-ahead, a survivorship-correct universe,
walk-forward evaluation, next-open execution and costs. There is also an
options workstream, plus a local Streamlit dashboard (`final/app/`) that shows
current picks.

**Owner: Gabe.** Every modeling decision, scope call and verdict is his. The
`pipe-dream-coo` agent recommends research direction, and Gabe decides. This
file records decisions and doesn't make them.

## 2. Standing constraints

These are Gabe's rules, copied byte-for-byte into [`AGENTS.md`](AGENTS.md). Read
them there. They are not repeated here, so the two copies can't drift apart.

Two newer rules live outside the repo and interact with them. See
[Open conflicts](#6-open-conflicts-and-decisions-for-gabe), item 1.

- **Rule 0 (`~/.claude/CLAUDE.md`, 2026-09-23).** Only `pipe-dream-integrator`
  runs git write operations (commit, push, merge, branch, stash, worktree). No
  other agent or session does.
- **Ownership (ledger, 2026-09-23).** `final/app/**` belongs to
  `pipe-dream-app-manager`. `README.md` and `AGENTS.md` belong to
  `pipe-dream-readme-manager`. `.gitignore`, `final/models/2026-09-19-factor-composite-reset.md`
  and `final/src/reset2026/PREREGISTRATION.md` are integrator-owned protected
  files.

---

## 3. Current state (as of 2026-09-23)

### 3.1 The one-paragraph version

Rounds 10-19 (2026-09-09 to 2026-09-16) established that the original
24-feature XGBoost stock model (`q75`) has **no detectable stock-selection
edge**. What it has is a low-volatility tilt plus a sector bet. On 2026-09-18
Gabe restarted the stock model as a **sign-constrained linear factor composite**
built from published anomalies, and moved down-cap. That composite shows a real
nomination-era signal (2007-2019). On the 2020-2026 hold-out, **every version
fails leave-one-year-out on 2020**. Since 2026-09-22, every down-cap (cap150 /
cap500) number is also **unreadable**, because the feature grid it ran on is
survivorship-selected. The app keeps q75 as the displayed primary, and the
composite and the composite+q75 blend appear as **Candidate** tabs. Gabe set
this as the baseline on 2026-09-23. Active new work: the Alpha Vantage options
pull (running), and the insider and congressional signals (just
pre-registered).

### 3.2 What the app shows: the baseline Gabe fixed on 2026-09-23 (landed, `bca3f7c`)

Gabe, 2026-09-23, quoted in the ledger's landing queue: *"keep the current
state of the app so we can get everything in order this is becoming a mess, we
need a new baseline so I am saying this is the current baseline."*

`final/app/app.py` on `integration` has four top-level tabs (Overview, Stock
Buy/No-Buy, Options Premium, Data & Updates). Stock has **eight sub-tabs**:

| sub-tab | what it shows | role |
|---|---|---|
| Today's Picks | `q75` (PRIMARY) and `xrank` (CANDIDATE) side by side, from `final/src/current_signal_pit.py` | q75 is displayed as primary. Neither is a validated edge. |
| Query a Ticker | per-ticker answer from `pit_model` | — |
| Sector Bets | hypergeometric, vol-stratified enrichment of the picks (`sweep/enrich.py`) | descriptive |
| Model Weights, Backtest & History, Universe | q75/xrank internals, equity curves vs SPY and USMV | — |
| Small-Cap Composite (Candidate) | corrected 8-factor, IC-weighted composite, cap150 (`final/src/current_signal_composite.py`) | candidate, not deployed |
| Composite+q75 Blend (Candidate) | 50/50 rank blend on cap2000 (`final/src/current_signal_blend.py`) | candidate, not deployed |

The numbers the app prints beside q75/xrank, from `final/app/README.md` (landed
2026-09-18):

```
             2007-2019 (in-sample)     2020-2026 (hold-out)
q75          +8.71%/yr   2.796x SPY    +7.33%/yr   1.526x SPY
xrank        +6.35%/yr   2.132x SPY    -4.28%/yr   0.771x SPY
```

Read those numbers against the knob-family band printed above them: ten cells
that differ from q75 only by one turned knob span **-8.01 to +9.15 %/yr
excess, sd 5.03**. Any gap smaller than that is not evidence.

The blend tab's own meta (`final/out/current_signal_blend_meta.json`, landed)
gives: single-grid backtest, excess vs SPY 1.54%/yr, hold-out -0.36%. The
composite tab's meta (`final/out/current_signal_composite_meta.json`, landed)
gives: hold-out excess 2.44%/yr, 40/40 offsets, **fails LOYO** (dropping 2020
flips it to -3.95%/yr). The composite runs on cap150, so the survivorship
caveat in 3.3 applies to it.

Known inconsistencies in app-owned files: these are for `pipe-dream-app-manager`,
not fixed here. `final/app/README.md` still describes six stock tabs.
`current_signal_blend.py` and its meta still say `"role": "primary"`.
See [Open conflicts](#6-open-conflicts-and-decisions-for-gabe).

### 3.3 Headline verdicts

| verdict | status | date | source |
|---|---|---|---|
| The rebuilt point-in-time data erased the old edge: augmented model **−0.11% per window, t = −0.09**, compounded **1.00x vs SPY 5.23x** | landed | 2026-09-09 | [`DATA-PIPELINE-HANDOFF.md`](DATA-PIPELINE-HANDOFF.md) §0 |
| Old XGBoost stock selection: no edge. Round 12 Deflated Sharpe 0.746, Reality Check p=0.61. 100% of the apparent performance is factor loading | landed (code), certified dead end | 2026-09-11/12 | [`final/src/sweep/RUNBOOK.md`](final/src/sweep/RUNBOOK.md) §5; `round18-app-two-models:AGENTS.md` "Rounds 10–17" |
| IC is retired as a *feature-admission* gate. The gate is now a within-date shuffle null at the 80th percentile | landed | 2026-09-16 | [`final/src/sweep/RUNBOOK.md`](final/src/sweep/RUNBOOK.md) §9 |
| Factor composite, nomination era, cap150: **+3.75%/yr** excess vs SPY, 40/40 offsets (9(8)-factor original) | landed. **Unreadable**: survivorship-selected grid | 2026-09-19 | [`final/out/reset2026/REPORT_nominate.md`](final/out/reset2026/REPORT_nominate.md), [reset doc](final/models/2026-09-19-factor-composite-reset.md) §3.1 |
| `asset_growth` dropped (Gabe's call): nomination **+4.32%/yr**, sd 0.55%. `FACTOR_SIGNS` is now 8 factors | landed. Unreadable: same grid | 2026-09-22 | [`PREREGISTRATION.md`](final/src/reset2026/PREREGISTRATION.md) "Factor-set decision"; [corrections](final/models/2026-09-22-composite-model-corrections.md) §3 |
| Composite hold-out (2020-2026): every version is positive in aggregate and **fails LOYO on 2020**. Original +1.85%/yr (drop 2020 → -2.05%/yr); asset_growth_dropped +2.62%/yr (→ -1.97%/yr); IC-weighted +2.44%/yr (→ -3.95%/yr) | landed (first two write-ups and the third's meta); third write-up in flight | 2026-09-19/22 | [reset doc](final/models/2026-09-19-factor-composite-reset.md) §3.2; [corrections](final/models/2026-09-22-composite-model-corrections.md) §6b; `final/out/current_signal_composite_meta.json` |
| The composite is mostly universe beta. A no-score control earns +2.40%/yr against decile_volq's +4.32% | landed. Unreadable: cap150 grid | 2026-09-22 | [corrections](final/models/2026-09-22-composite-model-corrections.md) §2a |
| The composite is a strong low-beta bet: corr(score, beta_252) -0.2933. Beta-adjusted IC is sharper (t 2.53 → 4.25) | landed | 2026-09-22 | [corrections](final/models/2026-09-22-composite-model-corrections.md) §9b |
| **The reset2026 cap500/cap150 grid is survivorship-selected.** 52% of cap150-only rows are future winners, and 4,598 real tickers are missing. Every down-cap result is unreadable until it's rebuilt | landed | 2026-09-22 | [AV spin doc](final/models/2026-09-22-alpha-vantage-spin.md) §A |
| `downcap_universe.py` split-basis bug is fixed; corrected universe written as `downcap_universe_v2.parquet` (v1 kept because `blend_model.py` reads it) | landed | 2026-09-22 | [AV spin doc](final/models/2026-09-22-alpha-vantage-spin.md) §B |
| AV `HISTORICAL_OPTIONS` is the only survivorship-safe AV endpoint (dead names, 2008+, raw volume/OI, PIT-safe OI). EARNINGS/ESTIMATES/INSIDER/NEWS are live-only | landed | 2026-09-22 | [AV spin doc](final/models/2026-09-22-alpha-vantage-spin.md) §1-2 |
| The one positive result from the XGBoost era: `days_to_next_filing` (the earnings announcement premium), h=20 IC -0.0153, t -4.17, and it gains strength under sector neutralisation. `_seasonal` is the tradeable, provably causal version (t -2.18). `_actual`/`_known` are **excluded from every training feature set** | landed (code); in the composite as `days_to_next_filing_seasonal` | 2026-09-12 | `round18-app-two-models:AGENTS.md` "Round 16" |
| LCID was **not** a data bug. It was a real 1-for-10 reverse split on 2025-09-02 | landed | 2026-09-22 | [corrections](final/models/2026-09-22-composite-model-corrections.md) §6d |

The certified dead ends list is owned by the COO (`~/.claude/pipe_dream-coordination/COO.md`,
2026-09-23) and is reproduced in §8.3.

### 3.4 Hold-out accounting

- The **old** 2020-2026 hold-out was spent on the XGBoost track: Round 13
  (top-5 breadth) and Round 18 (xrank).
- On 2026-09-18 Gabe **refreshed** it for the reset, and said not to re-argue
  that ([memory](#9-doc-index): `feedback_dont_relitigate_methodology_calls`).
- Since then it has been read for the composite **three times**:
  1. 2026-09-19: `cap150_raw`/`decile_volq`, the one pre-registered shot.
  2. 2026-09-22: `asset_growth_dropped`, the "Second hold-out spend" in
     PREREGISTRATION.md.
  3. 2026-09-22: IC-weighted. Its write-up (corrections §16) and its
     PREREGISTRATION entry are **in flight** (audit worktree, uncommitted).
     Its number is already in the landed composite meta.

  The composite+q75 blend was also read once (-0.36%, reset branch).
- **The only unspent test surface is the live forward ledger**
  (`prediction_ledger.py`), started 2026-09-22 on panel date 2026-09-08.
  Landed as v1/v2. The v3 IC-weighted ledger is in flight. Any further
  hold-out look needs Gabe's explicit OK (COO.md).

---

## 4. Workstreams

### 4.1 Factor composite (reset2026): active, landed through 2026-09-22 §9

- **Model:** a rank-transform of each factor, a fixed sign, then an average.
  Top decile within 5 trailing-vol quintiles, inverse-vol weighted, 40-day hold,
  next-open entry, 15bp costs, averaged over all 40 grid offsets, matched
  shuffle null. `final/src/reset2026/composite.py`.
- **Factors (landed `FACTOR_SIGNS`, 8):** `momentum_12_1` +, `pct_from_high_252`
  +, `volatility_60` −, `gross_profitability` +, `accruals` −,
  `net_issuance_pct` −, `days_to_next_filing_seasonal` −,
  `short_interest_days_to_cover` −. The last one has **zero coverage before
  2020-04-27**, so every nomination number is effectively from 7 factors.
- **Weights:** equal-weight in `composite.py`. The live candidate uses
  IC-shrinkage `PRODUCTION_WEIGHTS` (`gross_profitability` 0.5956,
  `accruals` -0.1627, `net_issuance_pct` -0.1399, `momentum_12_1` 0.0497,
  the rest ±0.013, per the landed composite meta). The module defining those
  weights (`ic_weighted_composite.py`) is **not committed**. See the open
  conflicts.
- **Physics audit (landed 2026-09-22).** Signs mostly right. Equal weights sit
  at cosine similarity 0.47 from the IC-optimal weights. Most of the edge is
  unlikely to be stock selection.
  [`2026-09-22-composite-model-physics.md`](final/models/2026-09-22-composite-model-physics.md).
- **Corrections round (landed §0-9).** `decile1_volq` refuted (−0.83%/yr).
  Book-to-market wrong-signed (IC -0.0240). `asset_growth` dropped. Beta term
  added. `price_adjustment_scanner.py` and `concentration_monitor.py` built.
  [`2026-09-22-composite-model-corrections.md`](final/models/2026-09-22-composite-model-corrections.md).
- **Latest in-flight results** (§10-18: IC weighting, leverage, buffer,
  options overlay): see [In flight](#5-in-flight).
- **Next (COO / reset doc §6):** rebuild the down-cap grid (needs Sharadar SF1
  for ~4.6k more names), laddered rebalancing, buffer construction.

### 4.2 Old XGBoost stock model (q75 / xrank): displayed, no validated edge

- Kept in the app as the displayed primary. The COO notes this is Gabe's
  decision, and the "certified dead end" is **not** grounds to remove it.
- Its demonstrated content: a low-vol tilt (score-vol correlation -0.134) plus a
  tech/healthcare sector bet. Sector-neutralised IC is −0.0038.
- Live script: `final/src/current_signal_pit.py`. It trains both variants from
  one panel load, and the tradable label `_trd_` was fixed in Round 18.
- Full history: `round18-app-two-models:AGENTS.md` (Rounds 9-19). The
  integrator held those sections back from `integration` pending a decision,
  and this README carries their current-state content. Also
  [`final/src/sweep/RUNBOOK.md`](final/src/sweep/RUNBOOK.md).

### 4.3 Composite+q75 blend (meta-model tier 1): Candidate tab

- `blend_score = mean(rank_z(composite_9factor_frozen), rank_z(q75))`, cap2000,
  zero fit. Single-grid backtest: 1.54%/yr vs SPY (q75 alone 0.35, composite
  alone 0.54), hold-out -0.36%. cap2000 is unaffected by the survivorship-grid
  issue.
- The composite half is **frozen** to the original 9-factor equal-weight
  definition on purpose. Don't let it import the current `composite.py`,
  because that would invalidate its own backtest (APP.md).
- Tier 2 (regime gate) is not started. Ask Gabe why the old HMM was retired
  first (COO decision #1). Tier 3 (sparse events) needs a survivorship-safe news
  source, since AV NEWS fails on dead names.

### 4.4 Options

- **AV options bulk pull: running** (landed code). `final/scripts/av_options_pull.py`,
  data in `final/data/alphavantage/`. It can move to a Windows box:
  [`final/scripts/AV_PULL_WINDOWS.md`](final/scripts/AV_PULL_WINDOWS.md).
  A unified AV+DoltHub chain and option features are built
  (`build_option_chain_unified.py`, `build_av_options_features.py`).
- **Pre-registered, not run.** Exp B (option factors, cap2000) needs ≥120
  nominate-era monthly dates landed. Exp A (train-old/test-new weights) needs
  the 1998 Sharadar backfill (blocked: `SHARADAR_API_KEY` not set).
  `final/src/reset2026/era_transfer.py`. **Do not** run `--exp B --stage confirm`
  or any cap500/cap150 tier before the grid rebuild.
- **AV subscription:** $49.99/mo, renews around 2026-10-22 (COO decision #3).
- **Earlier options model (2026-08/09):** long calls ≈ flat (Kelly −0.16%/mo,
  n=74). Long puts have no working model. Selling cash-secured puts is a
  **lead**: +3.32%/cohort, 70/85 months, a −33.5% COVID month, ad-hoc cleaning,
  and a DoltHub universe that isn't survivorship-safe. Details are in
  `final/models/buy_no_buy_options_v2/`, `final/models/pit_integration/README.md`
  and `final/models/hyperparameter_retune/README.md`. The live options tab still
  scores the S&P 500 chain.

### 4.5 Data layer

- The Round 11 point-in-time Sharadar rebuild is the ground everything stands
  on: `pit_universe.parquet` 6,888,686 rows, 4,011 tickers. Reproduction and
  acceptance tests: [`DATA-PIPELINE-HANDOFF.md`](DATA-PIPELINE-HANDOFF.md).
- Approved data-sourcing order (Gabe, 2026-09-17): sector-neutral features →
  net issuance (done, Round 20) → insider buys (**EDGAR**, not AV; now in flight)
  → options liquidity bucketing (AV pull running) → earnings revisions.
  [`2026-09-17-new-data-sourcing-research.md`](final/models/2026-09-17-new-data-sourcing-research.md).
- Architecture research (2026-09-17): hold the architecture and put effort
  into data. The reset then chose a linear composite.
  [`2026-09-17-model-architecture-research.md`](final/models/2026-09-17-model-architecture-research.md).

---

## 5. In flight

Nothing below is current state until it lands.

| branch / worktree | what it will change | state | source |
|---|---|---|---|
| `worktree-factor-composite-audit` (uncommitted files) | Corrections §10-18: Amihud null (t +0.10); regime diagnostic (momentum flips in high-vol, low-vol hypothesis fails, stopped); **IC-shrinkage weights** (OOS IC gain in both split-halves on raw returns); leverage candidate (IC -0.0161, t -2.44, not promoted); buffer band cuts turnover 19.3% → 6.3%; third hold-out spend; EWMA beta (marginal); options overlay (47.1% of contracts expire worthless). Also the full-spec doc, `ic_weighted_composite.py`, `prediction_ledger_v3.csv`, ~10 reset2026 scripts, and PREREGISTRATION appends | uncommitted. The session's commit was blocked twice by its Bash classifier. Needs Gabe or the integrator | `worktree-factor-composite-audit:final/models/2026-09-22-composite-model-corrections.md` §10-18; `...:final/models/2026-09-22-composite-model-full-specification.md`; `HANDOFF-worktree-factor-composite-audit.md` |
| `worktree-factor-composite-reset` (5 commits) | "Merge whole branch, nothing dropped" (Gabe, 2026-09-23): the Retrain-ALL speedup (`build_features_fundamentals_sharadar.py`, 2:42 → 59s, verify-pass), the `blend_q75.py` backtest and report, and `current_signal_blend_full.csv` (per-ticker query statuses). **Its app.py UI reorg is superseded** by the 09-23 baseline, and its `current_signal_blend.py` must not be taken (it drops the frozen-factor guard) | blocked on app.lock contention and app-manager reconciliation | `worktree-factor-composite-reset:final/models/2026-09-22-session-handoff.md`; LEDGER landing queue #2; APP.md |
| `worktree-insider-signals` (uncommitted) | Insider (SEC Form 3/4/5 bulk, `FILING_DATE`-keyed) and congressional signals vs the composite. Pre-registered k=2 (`ins_buyers_90` +, `ins_sellers_90` −). Congress is recorded as untestable under the era rules (forward-only) | pre-registered 2026-09-23, no results | `worktree-insider-signals:final/models/2026-09-23-insider-congress-preregistration.md` |
| `app` | = `bca3f7c`, content-identical to integration's `final/app/**`. It needs a fast-forward to integration | awaiting a fast-forward | `HANDOFF-app.md` |
| `worktree-papermoney-order-sheet` | paper-broker order sheet | **not to land** (Gabe, 2026-09-23) | LEDGER |
| `round18-app-two-models` | superseded. Its AGENTS.md Rounds 9-19 narrative is absorbed into this README | not merged. The merge-abort still needs confirming (LEDGER queue #0) | LEDGER |

---

## 6. Open conflicts and decisions for Gabe

1. **Standing constraints vs newer out-of-repo rules.** AGENTS.md #5 (dated
   2026-09-17) says agents may `git add/commit/push` themselves. Rule 0 in
   `~/.claude/CLAUDE.md` (2026-09-23) says only the integrator may. AGENTS.md #1
   says never push or redeploy the live app, while project memory (2026-09-23)
   records Gabe giving the integrator authority with "the app is for my use
   only". The constraints are copied verbatim and not edited. **Gabe: amend #1
   and #5 in AGENTS.md, or confirm the out-of-repo rules take precedence?**
   `final/src/sweep/RUNBOOK.md` §10 still carries the pre-2026-09-17 "never
   commit" wording.
2. **Landed code depends on an uncommitted file.** Integration's
   `final/src/current_signal_composite.py` does `import ic_weighted_composite`,
   which exists on **no branch** (it's untracked in the audit worktree). A fresh
   checkout of `integration` can't run the composite tab's retrain. Its meta
   also cites the uncommitted full-spec doc. **For the integrator:** land the
   audit worktree's non-app files (Gabe runs the commit, or grants a Bash
   permission rule).
3. **Down-cap survivorship vs the composite's live role.** The AV doc (landed
   2026-09-22) says every cap150/cap500 result is unreadable. The audit's
   full-spec doc (uncommitted, same day) and the landed composite meta quote
   cap150 numbers without that caveat. The live composite candidate and the
   forward ledger both use cap150. **Gabe / COO decision #2:** fund the SF1
   pull for ~4.6k names and rebuild, or move the candidate to cap2000.
4. **IC's role (methodology, for the COO).** Round 19 (2026-09-16) retired IC as
   a feature-admission gate (rank correlation with earnings +0.019). Gabe's
   2026-09-22 reframe made pooled IC the composite's *target metric*, and the
   in-flight IC-weighting and leverage results are judged on IC. The insider
   pre-registration (2026-09-23) uses both an IC screen and the shuffle null.
   The two standards need an explicit reconciliation.
5. **App-owned inconsistencies (for `pipe-dream-app-manager`).**
   `final/app/README.md` (2026-09-18) describes the six-tab, q75/xrank-only
   layout. `current_signal_blend.py` and `current_signal_blend_meta.json` say
   `"role": "primary"` and mention a "Theoretical Model tab". The 09-23
   baseline has the blend as a Candidate tab.
6. **Stale coordination entries (for their owners).** COO.md lists the blend as
   "app primary" and counts one composite hold-out spend. The ledger's AV row
   says new commits need landing, but `de4fdb5` is already in integration.
7. **Earlier decisions still pending** (COO.md): why the HMM regime gate was
   retired; whether to renew AV premium (around 2026-10-22); whether the
   integrator may fast-forward `main` to `integration` (`main` 7898b52 is far
   behind).

---

## 7. Repo map and reproduction

```
pipe_dream/
├── AGENTS.md, README.md          constraints / this file (readme-manager owns)
├── DATA-PIPELINE-HANDOFF.md      Round 11 point-in-time data build (2026-09-09)
├── final/                        THE ACTIVE PROJECT
│   ├── app/                      Streamlit dashboard (app-manager owns; see its README)
│   ├── src/                      pipeline
│   │   ├── reset2026/            factor composite (2026-09-18 onward), PREREGISTRATION.md
│   │   ├── sweep/                XGBoost-era sweep harness, Rounds 12-20; RUNBOOK.md
│   │   ├── insider/              (in flight) insider/congress signals
│   │   ├── current_signal_pit.py        q75 + xrank live signal
│   │   ├── current_signal_composite.py  composite candidate
│   │   ├── current_signal_blend.py      blend candidate (frozen 9-factor composite)
│   │   ├── execution.py          the one place a position is realized (Round 9)
│   │   └── build_*.py, sharadar_pull_*.py   data builders
│   ├── scripts/                  data acquisition, run on Gabe's machine (network)
│   ├── data/                     sharadar/, alphavantage/, options_unified/, benchmarks/ (mostly gitignored)
│   ├── out/                      panels, score caches, reset2026/ reports, signal CSVs
│   └── models/                   dated round docs (YYYY-MM-DD-*.md) + options workstream folders
├── src/, analysis/, out/         pre-reorg history, not in the active pipeline
└── options_raw/                  dolt clone of post-no-preference/options (8GB, gitignored)
```

**Environment:** conda env `pipe_dream` (`/opt/anaconda3/envs/pipe_dream/bin/python3`).
The base `anaconda3` env has a broken pandas/numpy ABI (APP.md, 2026-09-23).

**Reproduction, newest pipeline first.** Every network pull runs in Gabe's own
terminal. Sharadar, SEC EDGAR, yfinance, DoltHub and Alpha Vantage are
unreachable from agent sandboxes, and keys (`SHARADAR_API_KEY`,
`ALPHAVANTAGE_API_KEY`) never go in the repo.

| layer | how | source |
|---|---|---|
| Point-in-time Sharadar data, universe, feature panels, `td_data_sharadar/` | 9-step sequence (`sharadar_pull_pit_panel.py` … `export_sharadar_ohlc.py`) | [`DATA-PIPELINE-HANDOFF.md`](DATA-PIPELINE-HANDOFF.md) §3 |
| Factor composite: universe, factors, panel, outcome cache, backtest, reports | `downcap_universe.py` → `quality_factors.py` → `build_panel.py` → `build_outcome_cache.py` → `run_backtest.py` → `aggregate_report.py` | [reset doc](final/models/2026-09-19-factor-composite-reset.md) §7 |
| Composite corrections / audit | `model_audit.py`, `correction_variants.py`, `harness_check.py` | [physics](final/models/2026-09-22-composite-model-physics.md) §12, [corrections](final/models/2026-09-22-composite-model-corrections.md) §7 |
| Sweep harness (XGBoost era) | `python3 -m sweep.cli …` | [`final/src/sweep/RUNBOOK.md`](final/src/sweep/RUNBOOK.md) |
| AV options pull + unified chain + features | `av_options_pull.py`, `build_option_chain_unified.py`, `build_av_options_features.py` | [AV spin doc](final/models/2026-09-22-alpha-vantage-spin.md) §C-E |
| Live signals | `current_signal_pit.py`, `current_signal_composite.py`, `current_signal_blend.py` (the app's "Retrain ALL" runs them) | `final/app/README.md` |
| Older gitignored paths (yfinance `td_data_local/`, EDGAR `fundamentals_raw/`, DoltHub options exports, GARCH, pre-Round-11 panels) | per-path commands | `git show integration:AGENTS.md` at 29eb67b, "Reproducing every gitignored path" (historical copy, see §Superseded) |

**Older known gaps, still open** (from AGENTS.md "Known gaps", 2026-09-02/04,
not superseded by anything newer):

- `final/models/final_model_calls.pkl` / `final_model_puts.pkl` have no direct
  reproduction script. They stay tracked in git on purpose.
  `final/models/pit_integration/` is the validated substitute.
- `build_training_data_expanded.py` and its related expanded-universe options
  scripts were never confirmed present. Check before assuming they exist.
- The app's "Retrain" buttons don't refresh the raw EDGAR/Sharadar
  fundamentals pulls. Those run separately on Gabe's machine.
- Several `.DS_Store` files are tracked (a one-time `git rm --cached` for Gabe
  or the integrator).
- The sweep-era idea backlog, unprioritized since the reset (from AGENTS.md
  "Future plans", 2026-08-30/09-01): stop-limit exits, time-series foundation
  models for the options distribution, per-stock behavioral transition
  matrices, MoSeq-style "syllables", and per-ticker "Wins Above Replacement".
  Confirm priority with Gabe or the COO first.

---

## 8. Lessons and landmines: read before adding a feature

### 8.1 Bugs that passed every automated check (deduplicated)

| bug | how it presented | what caught it | source |
|---|---|---|---|
| Survivorship-determined universe (Round 11) | 2008 pool missing a third of names, 89% of them dead | naming companies that should be there (Apple, Wachovia) | DATA-PIPELINE-HANDOFF §1 |
| $10 floor on split-adjusted close | excluded Apple ($5.98 adjusted) from 2008 | named company | same |
| Reissued symbols (41 of 264 gap files) | wrong-issuer bars | identity map | same |
| `--refresh-recent` splice (Round 9) | fake one-day crash in MNST/PRIM, the *live* signal | adjustment-factor check | integration AGENTS.md Round 9 |
| Delisted OHLC basis mismatch (Round 9) | stops barely fired on gap tickers | `close` outside `[low, high]` | same |
| NaN ranking (R13) | `argsort` put NaN last, so an empty column got top ranks | asking what an empty column should score | sweep RUNBOOK §6 |
| NaN era split (R14) | one NaN made an era "no estimate" | asking why it was missing | same |
| Breadth estimator (R15) | reported 19.1 where the truth was 5.0 | `capture > 1` is impossible | same |
| `merge_asof` alignment (R16) | `.sort_index()` no-op, six columns on the wrong rows | fire rate 0.7% vs 64% expected | same |
| Empty feature list / inf in features (R17) | "no windows", dead cells | noticing *nothing* ≠ *no signal* | same |
| Live label basis `_trd_` (R18) | live trained on close-to-close | field-by-field diff vs the cell id | round18 AGENTS.md R18 |
| "Candidate pool" fix, **retracted** (R18) | admitted NaN-vol names, and `_bucket_idx` filed them in the lowest-vol bucket | Gabe reading the picks | same; APP.md |
| `downcap_universe.py` `closeunadj × split-adjusted volume` | inflated past dollar volume for later splitters | AAPL 2008 $162B/day | AV spin doc §B |
| Survivorship-selected down-cap grid | 52% of cap150-only rows are future winners | pool-integrity check, 62.85% | AV spin doc §A |
| IC-weighted score without renormalising | missing-factor rows compressed | re-run after the fix | corrections §12 (in flight) |
| LCID "bug", **retracted** | adjusted vs raw price compared | split-signature scanner | corrections §6d |

**Standing rule** (Round 16/17): verify by naming what should be there, with
explicit expected values, not by counting. Distribution checks can't detect a
permuted row.

### 8.2 Rules that bind new work

- **Pre-register before running.** Gates don't move after a result. Composite
  work goes in `final/src/reset2026/PREREGISTRATION.md` (protected, append-only)
  or its own dated pre-registration doc.
- **Grid offset.** Average over all 40 offsets. Offset 0 alone flips weak
  features (`momentum_20` flips on 16/40) (`check_grid_offset.py`).
- **Feature admission (XGBoost track):** beat the 80th percentile of a
  within-date **shuffle** null. A shuffled noise column once produced the best
  backtest in the grid (3.309×). Never quote an improvement without its null.
- **Leave-one-year-out** is never relaxed. A result concentrated in one year has
  a near-zero forward expectation.
- **Run `concentration_monitor.py`** on any new backtest's picks, and
  `price_adjustment_scanner.py` before calling a price series a bug.
- **Live script = backtest cell, field by field.** Trace a backtest's data to
  where it is *loaded*, not where it is used.
- **Never admit NaN-feature names to a scored pool.** `_bucket_idx` sends NaN
  vol to the lowest-vol bucket. The fix touches `simulate()`, so it's Gabe's
  call.
- **The decision bar** (Project doc `claude/validation-gates.md`, 2026-09-12)
  replaces Gate B's t > 3 for deployment questions. Deploy when the
  expected excess return is positive after costs and the downside is
  understood. **Gate A (placebo, look-ahead, pool integrity) is unchanged
  and absolute.**
- **`build_app_benchmarks.py`** is the one tool allowed to touch the
  hold-out, and only for its hard-coded list of two already-spent cells.
  Never add a cell "to see how it does".
- **Unpaired decile t-stats:** at `decile_volq_excess`, order-free shuffle
  series reach median |t| 1.66 and max 3.86. A decile screen read against a
  ±2 bar is using a null roughly twice as wide as it looks (Round 19).
- **Calibration:** in a zero-signal grid, 27% of configs beat the market and
  the best reached 2.577×. One config beating SPY is evidence of nothing.

### 8.3 Certified dead ends (COO.md, 2026-09-23). Reopen only with the stated reason

Old XGBoost stock selection · fundamentals as a selection signal (R13) ·
rate-sensitivity features (R14) · breadth via book size/horizon (R15/15b) ·
path-order / `accel_20` (R19; an 8th trial is not allowed) · IC as a feature
gate · the old HMM gate (until Gabe says why it was dropped) · earnings
proximity as a stage-2 rule · composite `decile1_volq` · options: long calls,
long puts, buy/no-buy gate + ATM, 60-day, ~2-day/0DTE, LEAPS, GAM hurdle · AV
EARNINGS/ESTIMATES/INSIDER/NEWS as backtest features. In flight (not yet
certified): Amihud illiquidity, book-to-market (wrong-signed), exponent
transform.

---

## 9. Doc index

Dates come from filenames, else the doc, else the last commit. "Landed" means
the file is on `integration`.

| doc | date | status | one line |
|---|---|---|---|
| [`AGENTS.md`](AGENTS.md) | 2026-09-23 | landed after this lands | standing constraints + pointer |
| [`DATA-PIPELINE-HANDOFF.md`](DATA-PIPELINE-HANDOFF.md) | 2026-09-09 | landed | Round 11 point-in-time Sharadar rebuild, reproduction, acceptance tests |
| [`final/src/sweep/RUNBOOK.md`](final/src/sweep/RUNBOOK.md) | 2026-09-18 (commit) | landed | sweep package, Rounds 12-19, shuffle-null gate, bug ledger (§10 git rule stale) |
| [`final/models/2026-09-17-model-architecture-research.md`](final/models/2026-09-17-model-architecture-research.md) | 2026-09-17 | landed | 15 ranked model-architecture options |
| [`final/models/2026-09-17-new-data-sourcing-research.md`](final/models/2026-09-17-new-data-sourcing-research.md) | 2026-09-17 | landed | 15 ranked data sources; Gabe approved the top 5 order |
| [`final/models/2026-09-19-factor-composite-reset.md`](final/models/2026-09-19-factor-composite-reset.md) | 2026-09-19 (+09-22 correction) | landed, protected | the reset: model, results, survivorship audit, reproduction |
| [`final/src/reset2026/PREREGISTRATION.md`](final/src/reset2026/PREREGISTRATION.md) | 2026-09-18 → 09-22 | landed, protected | append-only record of every composite decision and spend |
| [`final/out/reset2026/REPORT_nominate.md`](final/out/reset2026/REPORT_nominate.md), [`REPORT_holdout.md`](final/out/reset2026/REPORT_holdout.md) | 2026-09-19 | landed; **stale** (9(8)-factor, pre-`asset_growth` drop, pre-survivorship finding) | offset-averaged headline tables |
| [`final/models/2026-09-22-composite-model-physics.md`](final/models/2026-09-22-composite-model-physics.md) | 2026-09-22 | landed | physics-style audit of the composite (§6 recommendation refuted by corrections §1) |
| [`final/models/2026-09-22-composite-model-corrections.md`](final/models/2026-09-22-composite-model-corrections.md) | 2026-09-22 | landed §0-9; §10-18 in flight | corrections, LCID retraction, beta term, safeguards |
| `worktree-factor-composite-audit:final/models/2026-09-22-composite-model-full-specification.md` | 2026-09-22 | in flight (uncommitted) | clean spec of the IC-weighted 8-factor composite |
| [`final/models/2026-09-22-alpha-vantage-spin.md`](final/models/2026-09-22-alpha-vantage-spin.md) | 2026-09-22 | landed | AV coverage, options pull, **down-cap survivorship finding** |
| [`final/scripts/AV_PULL_WINDOWS.md`](final/scripts/AV_PULL_WINDOWS.md) | 2026-09-23 | landed | moving the AV pull to Windows |
| `worktree-factor-composite-reset:final/models/2026-09-22-session-handoff.md` | 2026-09-22 | in flight | blend promotion (UI part superseded), query fix, retrain speedup |
| `worktree-insider-signals:final/models/2026-09-23-insider-congress-preregistration.md` | 2026-09-23 | in flight (uncommitted) | insider/congress pre-registration |
| [`final/app/README.md`](final/app/README.md) | 2026-09-18 | landed; stale vs app.py (app-manager) | how to run the app, tab guide |
| [`final/models/pit_integration/README.md`](final/models/pit_integration/README.md) | 2026-09-02 | landed | options PIT-integration reproduction |
| [`final/models/hyperparameter_retune/README.md`](final/models/hyperparameter_retune/README.md) | 2026-09-02 | landed | options Tweedie/GAM retune |
| `round18-app-two-models:Claude outputs/RUNBOOK.md` | 2026-09-09 | superseded (self-labelled) | Round 12-only runbook |
| `round18-app-two-models:AGENTS.md` | 2026-09-16 | not landed; absorbed here | Rounds 9-19 narrative |
| `~/.claude/pipe_dream-coordination/` LEDGER.md, COO.md, APP.md, HANDOFF-*.md | 2026-09-23 | outside git | who's doing what; research verdicts; app state |
| `~/.claude/projects/-Users-ggraham-pipe-dream/memory/*.md` | 2026-09-17 → 09-23 | outside git | Gabe's recorded decisions (foundation reset, data priorities, meta-model roadmap, don't-relitigate) |
| Project docs (`claude/validation-gates.md`, `backtest/*`, `models/*`, `universe/*`) | 2026-08 → 09-16 | Claude Project, not in repo | the pre-reset narrative. Gates: the DECISION BAR (2026-09-12) |

---

## Superseded

Old claim, its source and date → what replaced it, with source and date.

- The q75 / PIT "augmented + 15% stop" model is primary at $10k → $214,606 (AGENTS.md workstream 4, 2026-09-02) → corrected execution gives $25,299 vs SPY $55,597 (AGENTS.md Round 9, 2026-09-07), and then the rebuilt data gives 1.00x vs SPY 5.23x (DATA-PIPELINE-HANDOFF, 2026-09-09).
- The v4 XGBoost/LSTM "Secondary Models" tab, XGBoost +21.54%/trial (AGENTS.md workstream 1, 2026-08-27) → tab removed; the pre-Round-11 universe was defective (app README / round18 AGENTS.md Round 18, 2026-09-16).
- The HMM-gated blend is primary (pre-2026-09-02) → retired, "we are no longer using the HMM" (AGENTS.md workstream 2, 2026-09-02). Reason unrecorded (COO decision #1).
- Options calls show a real edge, +11.43%/+7.28% (AGENTS.md workstream 3, 2026-09-02) → calls baseline flat, Kelly −0.16% monthly n=74 (AGENTS.md 2026-09-04 rebuild).
- Options universe built from today's roster (AGENTS.md Known gaps, 2026-09-04) → closed for 2008+ by AV `HISTORICAL_OPTIONS` as-traded symbols (AV spin doc, 2026-09-22). The DoltHub-based puts lead still carries it.
- "Treat Round 12 top-5 breadth as confirmed on the hold-out" (Round 13) → hold-out spent (round18 AGENTS.md, 2026-09-12) → hold-out refreshed for the reset (memory, 2026-09-18) → read three times for the composite (2026-09-19/22).
- IC `|t|` gates feature admission (sweep era) → shuffle null at the 80th percentile (sweep RUNBOOK §9, 2026-09-16).
- The deployed model is the 24-column XGBoost q75 (app README, 2026-09-16) → stock model restarted as a linear factor composite (memory / reset doc, 2026-09-18/19). q75 stays displayed by Gabe's decision.
- 9-factor equal-weight composite incl. `asset_growth` (reset doc, 2026-09-19) → 8 factors, `asset_growth` dropped (PREREGISTRATION "Factor-set decision", 2026-09-22). The candidate tab uses IC-shrinkage weights (composite meta, 2026-09-22).
- "9 factors" in the nomination era (reset doc, 2026-09-19) → 8 active before 2020 (`short_interest_days_to_cover` 0% coverage) (physics doc §2, 2026-09-22).
- Nomination +3.75%/yr "monotonic in cap", "no survivorship bias found" (reset doc §3.1/§4, 2026-09-19) → the down-cap grid is survivorship-selected, and these results are unreadable (AV spin doc §A, 2026-09-22).
- Physics doc §6: buy deciles 1-3 / avoid decile 0 (2026-09-22) → `decile1_volq` −0.83%/yr, refuted (corrections §1, 2026-09-22).
- Physics doc §9.1: value is the strongest omission (2026-09-22) → book-to-market wrong-signed, IC -0.0240 (corrections §4, 2026-09-22).
- Physics doc recommendation #4 (|t|<1 shrinkage) → rejected before running (corrections §0, 2026-09-22).
- LCID price series is a data bug (corrections §6c; AGENTS.md Known gaps, 2026-09-22) → real 1-for-10 reverse split, retracted (corrections §6d; integration AGENTS.md, 2026-09-22).
- Blend promoted to PRIMARY, with q75/xrank, Sector Bets, Model Weights, Backtest & History and the composite tab retired (reset `b37b7db` and session-handoff, 2026-09-19/22) → the app baseline keeps all tabs, blend as Candidate (Gabe, LEDGER landing queue #2, 2026-09-23).
- Composite and blend branch "not merged to main; Gabe merges" (session-handoff, 2026-09-22) → all landing goes through the integrator onto `integration` (LEDGER / Rule 0, 2026-09-23).
- Standing constraint #5 "Never run git add/commit/push yourself" (origin/main AGENTS.md; sweep RUNBOOK §10) → "fine to run yourself" (AGENTS.md #5, 2026-09-17). Further narrowed by Rule 0 (2026-09-23; see Open conflicts #1).
- AV options are blocked, with no volume/OI field (memory, 2026-09-17) → unblocked, AV premium bought, bulk pull running (AV spin doc / memory, 2026-09-22).
- Insider data source "TBD / AV" (data-sourcing research, 2026-09-17) → EDGAR Form 4 (session-handoff, 2026-09-22) → SEC Form 3/4/5 bulk data sets (insider prereg, 2026-09-23, in flight).
- AV `HISTORICAL_VOLUME_OPEN_INTEREST_RATIO` gives only a ratio (session-handoff §5, 2026-09-22) → `HISTORICAL_OPTIONS` has raw volume and OI (AV spin doc §1, 2026-09-22).
- Stop-loss 15% adopted (AGENTS.md Round 8) → no stop; Round 13 holds to horizon (AGENTS.md note, 2026-09-11; reset doc §5).
- AGENTS.md sections "Current state (as of 2026-09-02)", "Known gaps", "Future plans", "Where the fuller history lives" → history only. Read them at `git show 29eb67b:AGENTS.md`. Their live content (reproduction table, options gaps, dead ends) is carried in §4, §7 and §8 above.
- `Claude outputs/RUNBOOK.md` (Round 12, 2026-09-09) → `final/src/sweep/RUNBOOK.md` (self-labelled superseded).
