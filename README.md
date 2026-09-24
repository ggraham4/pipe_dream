# pipe_dream: current state of the project

**Consolidated 2026-09-23 by `pipe-dream-readme-manager`** (first full sweep,
then refreshed the same evening after the audit and insider-signals branches
landed, integration `c8bba77`).
This is the one current-state document. It merges every branch's docs, the
coordination ledger, handoffs and project memory, and the newest source wins
where two disagree. Everything that lost is listed in [Superseded](#superseded)
at the bottom.

How to read the tags:

- **landed** means the claim is on `integration` (c8bba77).
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

## 3. Current state (as of 2026-09-24)

### 3.1 The one-paragraph version

Rounds 10-19 (2026-09-09 to 2026-09-16) established that the original
24-feature XGBoost stock model (`q75`) has **no detectable stock-selection
edge**. What it has is a low-volatility tilt plus a sector bet. On 2026-09-18
Gabe restarted the stock model as a **sign-constrained linear factor composite**
built from published anomalies, and moved down-cap. That composite shows a real
nomination-era signal (2007-2019). On the 2020-2026 hold-out, **every version
fails leave-one-year-out on 2020**. Since 2026-09-22, every down-cap (cap150 /
cap500) number is also **unreadable**, because the feature grid it ran on is
survivorship-selected. On rank accuracy the IC-weighted composite beats q75 by
a margin that is **not detectable** at 82 dates (§19, MIDDLE), and its rank
signal is essentially one factor, `gross_profitability`. The app keeps q75 as
the displayed primary, and the composite and the composite+q75 blend appear as
**Candidate** tabs. Gabe set this as the baseline on 2026-09-23. Insider buy/sell
counts are a certified dead end (2026-09-23), with one weak lead (opportunistic
buyers). Congress is forward-only. The Alpha Vantage options pull **crashed**
on 2026-09-23 at 18:09 and is not running. The earnings-timing family is
closed (8-K announcement-date test DEAD, 2026-09-23). Two forward-only bets
(`icw9` leverage, opportunistic insider buyers) are now recorded blind in a side
ledger from panel date 2026-09-08 (landed 2026-09-24). Active new work: the
COO's WO-6 survivorship-safe down-cap grid rebuild (in flight).

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
| Composite hold-out (2020-2026): every version is positive in aggregate and **fails LOYO on 2020**. Original +1.85%/yr (drop 2020 → -2.05%/yr); asset_growth_dropped +2.62%/yr (→ -1.97%/yr); IC-weighted +2.44%/yr (→ -3.95%/yr) | landed | 2026-09-19/22 | [reset doc](final/models/2026-09-19-factor-composite-reset.md) §3.2; [corrections](final/models/2026-09-22-composite-model-corrections.md) §6b, §16 |
| The composite is mostly universe beta. A no-score control earns +2.40%/yr against decile_volq's +4.32% | landed. Unreadable: cap150 grid | 2026-09-22 | [corrections](final/models/2026-09-22-composite-model-corrections.md) §2a |
| The composite is a strong low-beta bet: corr(score, beta_252) -0.2933. Beta-adjusted IC is sharper (t 2.53 → 4.25) | landed. Measured on the cap150 grid, so the survivorship caveat applies | 2026-09-22 | [corrections](final/models/2026-09-22-composite-model-corrections.md) §9b |
| **IC-shrinkage weights** (each factor weighted by sign × max(0.1, abs(t) − 1) of its own pooled-IC t, pre-registered, one run) beat equal weight out of sample on raw-return IC in both split-halves: fit-odd→test-even, weighted +0.0304 vs equal +0.0183; fit-even→test-odd, weighted +0.0496 vs equal +0.0434. On beta-adjusted IC the second split favours equal weight on the point estimate. No portfolio CAGR was computed for this step | landed. cap150 grid, nomination era | 2026-09-22 | [corrections](final/models/2026-09-22-composite-model-corrections.md) §12 (OOS figures as reproduced in §19's sanity gate) |
| **Cross-model rank accuracy (§19): MIDDLE.** Paired rho(icw8 split-half) − rho(q75) mean **+0.0449**, t **+1.89** (bar t ≥ 2), same sign in both halves. icw8 alone +0.0475 (t +4.19); q75 +0.0026 (t +0.12); `gross_profitability` alone +0.0458, so the composite's rank accuracy is **essentially one factor, not eight**. FM-R² ranks the other way because it is unsigned. Required labels: q75's large-cap-leaning (cap500k+) intersection, single s40 grid, pre-2020 only, descriptive (no trial spent) | landed; COO verdict: MIDDLE, no detectable difference | 2026-09-23 | [corrections](final/models/2026-09-22-composite-model-corrections.md) §19; `final/out/reset2026/cross_model_accuracy_report.json` |
| Composite extensions screened on the nomination era, none adopted: Amihud IC +0.0009 (t = +0.10); regime conditioning stopped (momentum flips in high-vol, the low-vol hypothesis fails); exponent p=2 no better; `fcf_yield` null; `profitability_trend` wrong-signed; EWMA beta marginal (IC +0.0462 vs +0.0450). `leverage` IC -0.0161, t -2.44, right sign, **not in the weights** (see §4.1 for its status) | landed. cap150 grid | 2026-09-22 | [corrections](final/models/2026-09-22-composite-model-corrections.md) §10, §11, §13, §17 |
| Turnover: a buffer band (hold unless out of the top 20%) cuts turnover 19.3% → 6.3% at +5.43% vs +5.09% excess. Laddering smooths offset dispersion but does not cut turnover. Buffer is a tested refinement, **not the confirmed default** | landed. cap150 grid, nomination era | 2026-09-22 | [corrections](final/models/2026-09-22-composite-model-corrections.md) §15; [full spec](final/models/2026-09-22-composite-model-full-specification.md) §2.3 |
| Options overlay (top-5 picks, 40-day ATM calls at Black-Scholes fair value, no real chain data): 47.1% of contracts expire worthless, all 5 worthless in 13 of 82 windows, full reinvestment compounds to ruin. A theoretical ceiling, not a recommendation | landed. cap150, nomination era | 2026-09-22 | [corrections](final/models/2026-09-22-composite-model-corrections.md) §18 |
| **Insider buy/sell counts are a certified dead end** as composite factors (cap150, h=40). Registered k=2: `ins_buyers_90` raw IC −0.0006 (t −0.16), halves disagree in sign; `ins_sellers_90` wrong-signed. The book gain is **gross, costs not applied**: ew9+buyers +4.94% vs the ew8 baseline +4.82%, against a shuffle-null p80 of +4.86%. The sector-neutral t of +3.10 is an artefact; with factor and return both sector-demeaned, IC +0.0018, **t 0.65**. Do not re-screen 30/180-day windows | landed; COO certified dead end | 2026-09-23 | [insider results](final/models/2026-09-23-insider-congress-results.md) §2-3, §7; [prereg](final/models/2026-09-23-insider-congress-preregistration.md) |
| **Lead, not a result:** *opportunistic* insider purchases (Cohen, Malloy & Pomorski 2012), **+0.71% sector-demeaned 40-day return (Newey-West t 1.92, n = 10,419 events)**; routine purchases −0.70%. Post-hoc and below t = 2. Its "small-cap" tercile is mostly fallen large-caps | landed. Survivorship-selected cap150 grid | 2026-09-23 | [insider results](final/models/2026-09-23-insider-congress-results.md) §6 |
| **Congress trades are untestable in-era.** AV House coverage starts mid-2018 and 2020+ is spent. Forward-only. The premise that insider and congress data only record the execution date was wrong: SEC Form 345 has `FILING_DATE` (median lag 2 days) and AV congress has `filed_date` (median 28 days) | landed; COO: forward-only | 2026-09-23 | [insider results](final/models/2026-09-23-insider-congress-results.md) §1, §7 |
| **The reset2026 cap500/cap150 grid is survivorship-selected.** 52% of cap150-only rows are future winners, and 4,598 real tickers are missing. Every down-cap result is unreadable until it's rebuilt | landed | 2026-09-22 | [AV spin doc](final/models/2026-09-22-alpha-vantage-spin.md) §A |
| `downcap_universe.py` split-basis bug is fixed; corrected universe written as `downcap_universe_v2.parquet` (v1 kept because `blend_model.py` reads it) | landed | 2026-09-22 | [AV spin doc](final/models/2026-09-22-alpha-vantage-spin.md) §B |
| AV `HISTORICAL_OPTIONS` is the only survivorship-safe AV endpoint (dead names, 2008+, raw volume/OI, PIT-safe OI). EARNINGS/ESTIMATES/INSIDER/NEWS are live-only | landed | 2026-09-22 | [AV spin doc](final/models/2026-09-22-alpha-vantage-spin.md) §1-2 |
| The one positive result from the XGBoost era: `days_to_next_filing` (the earnings announcement premium), h=20 IC -0.0153, t -4.17, and it gains strength under sector neutralisation. `_seasonal` is the tradeable, provably causal version (t -2.18). `_actual`/`_known` are **excluded from every training feature set** | landed (code); in the composite as `days_to_next_filing_seasonal`. The family is now closed (see the 8-K row) | 2026-09-12 | `round18-app-two-models:AGENTS.md` "Round 16" |
| **Earnings announcement premium via 8-K Item 2.02 is DEAD** under its pre-registered rule (trial 6 of 6): pooled raw IC −0.0065, **NW t −1.71 vs a 2.64 bar**, and **2015 = 48.5%** of the effect (limit 45%). Passed: both halves negative, both-sides sector-neutral t −1.82, 0/40 grid flips. **The earnings-timing family (6 trials) is a COO-certified dead end.** Reopen only with a point-in-time source of *announced* dates, tested forward. COO ruling: the doc's Part 2 sentence on moving a portfolio is struck, because the icw9−icw8 book gap is +0.10%/yr on in-sample weights | landed; COO certified dead end | 2026-09-23 | [EAP 8-K doc](final/models/2026-09-23-earnings-announcement-premium-8k.md) Part 2; COO.md dead-end table |
| **Two forward-only bets pre-registered and recording** (WO-2+3): `icw9` (the frozen icw8 rule plus `leverage`, sign −1, weight −0.1582) vs icw8, and CMP-2012 opportunistic insider buyers (`opp_buyers_90`, with the plain count as control). First blind record: panel date **2026-09-08**, 2,214 rows. Decision after **6 non-overlapping matured dates**; the first matures around **2026-11-03**. No backtest was run. Record cadence is Gabe's call | landed | 2026-09-23/24 | [forward ledger doc](final/models/2026-09-23-forward-ledger-leverage-opportunistic-buyers.md) §1-5 |
| LCID was **not** a data bug. It was a real 1-for-10 reverse split on 2025-09-02 | landed | 2026-09-22 | [corrections](final/models/2026-09-22-composite-model-corrections.md) §6d |

"cap150 grid" in the status column means the survivorship caveat in the row
on the reset2026 grid applies: the number is measured on a universe of tickers
that were cap2000 at some point, so it is not a true small-cap result.

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
  3. 2026-09-22: IC-weighted, +2.44%/yr, drop 2020 → -3.95%/yr
     (corrections §16, landed 2026-09-23).

  The composite+q75 blend was also read once (-0.36%, reset branch). COO.md
  counts all four as hold-out reads; the full-spec doc §5 counts the three
  composite versions only. Both are right about what they count.
- **The only unspent test surface is the live forward ledger**
  (`prediction_ledger.py`), started 2026-09-22 on panel date 2026-09-08.
  `prediction_ledger_v3.csv` (IC-weighted and equal-weight columns) landed
  2026-09-23. First maturity is about 2026-11-03, and the COO wants at least
  6 non-overlapping matured dates before any conclusion (COO.md WO-1). Any
  further hold-out look needs Gabe's explicit OK (COO.md). A side ledger,
  `prediction_ledger_ext.csv` (icw9 leverage + opportunistic buyers), landed
  2026-09-24 on the same first date and decision rule (§3.3).

---

## 4. Workstreams

### 4.1 Factor composite (reset2026): active, landed through corrections §19 (2026-09-23)

**Start with the [full specification](final/models/2026-09-22-composite-model-full-specification.md)**
(2026-09-22, landed): the equation, factor table, weights, universe, eras and
reproduction in one place. Its §6 points to "AGENTS.md's reproduction table",
which now lives in §7 below.


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
  IC-shrinkage `PRODUCTION_WEIGHTS` from `ic_weighted_composite.py` (landed
  2026-09-23): `gross_profitability` 0.5956, `accruals` -0.1627,
  `net_issuance_pct` -0.1399, `momentum_12_1` 0.0497, the rest ±0.013 (per
  the landed composite meta). Frozen, fit once on the nomination era.
- **Physics audit (landed 2026-09-22).** Signs mostly right. Equal weights sit
  at cosine similarity 0.47 from the IC-optimal weights. Most of the edge is
  unlikely to be stock selection.
  [`2026-09-22-composite-model-physics.md`](final/models/2026-09-22-composite-model-physics.md).
- **Corrections round (landed §0-9).** `decile1_volq` refuted (−0.83%/yr).
  Book-to-market wrong-signed (IC -0.0240). `asset_growth` dropped. Beta term
  added. `price_adjustment_scanner.py` and `concentration_monitor.py` built.
  [`2026-09-22-composite-model-corrections.md`](final/models/2026-09-22-composite-model-corrections.md).
- **Corrections §10-19 (landed 2026-09-23):** IC-shrinkage weighting, the
  extension screens, regime buckets, turnover, the third hold-out spend, EWMA
  beta, the options overlay and the §19 cross-model comparison. Verdicts are
  in §3.3.
- **`leverage`:** corrections §13 (2026-09-22) called it a ready candidate for
  a promotion decision. The newer COO position (COO.md WO-2, 2026-09-23) is
  that its t −2.44 was already measured in-era, so an in-era test can only
  nominate. Confirmation is forward-only, as an icw9 column in the prediction
  ledger. **Recording since panel date 2026-09-08** (landed 2026-09-24; frozen
  weights and the kill/success rule in the
  [forward ledger doc](final/models/2026-09-23-forward-ledger-leverage-opportunistic-buyers.md) §1a, §4).
- **Next (COO.md, 2026-09-23):** rebuild the down-cap grid (decision #2,
  needs Sharadar SF1 for ~4,600 more names); score the forward ledger from
  about 2026-11-03 (WO-1). Laddered rebalancing was **not launched**: it
  only changes variance and can't fix the 2020 concentration (COO.md;
  corrections §15). Open composite questions for Gabe are COO decision #7.

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

- **AV options bulk pull: crashed 2026-09-23 18:09, not running** (landed
  code). `http.client.IncompleteRead` is not in the retry tuple at
  `final/scripts/av_options_pull.py:151`. It stopped at monthly 2010-08-18:
  32 of 225 monthly dates, 0 of 750 weekly (COO.md; `final/data/alphavantage/pull.out`
  ends in that traceback, mtime 18:09). Restarting it is Gabe's call. Data
  in `final/data/alphavantage/`. It can move to a Windows box:
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
  net issuance (done, Round 20) → insider buys (**done 2026-09-23**, SEC Form
  345, plain counts a dead end, see §4.6) → options liquidity bucketing (AV
  pull crashed, see §4.4) → earnings revisions.
  [`2026-09-17-new-data-sourcing-research.md`](final/models/2026-09-17-new-data-sourcing-research.md).
- Architecture research (2026-09-17): hold the architecture and put effort
  into data. The reset then chose a linear composite.
  [`2026-09-17-model-architecture-research.md`](final/models/2026-09-17-model-architecture-research.md).

### 4.6 Insider and congressional trading: done 2026-09-23 (landed)

- **Data:** SEC Insider Transactions Data Sets (structured Form 3/4/5,
  2006Q1-2026Q1, 868 MB, gitignored in `final/data/edgar/form345/`),
  keyed on `FILING_DATE` and joined by issuer CIK, officers and directors
  only. AV `INSIDER_TRANSACTIONS` is unusable (no filing date, no P/S code,
  today's issuer only).
- **Result:** plain buyer/seller counts are a certified dead end. Nearly all
  the cross-sectional structure is a sector bet: insiders buy most in
  Financials, Energy and Real Estate, which then underperform. Verdicts in
  §3.3.
- **Lead:** opportunistic buyers. Now a pre-registered forward-only bet,
  recording since panel date 2026-09-08 (landed 2026-09-24,
  [forward ledger doc](final/models/2026-09-23-forward-ledger-leverage-opportunistic-buyers.md)).
  A live Form 4 refresh (`final/scripts/edgar_form4_refresh.py`) covers
  2026-04-01 to 2026-09-23. No 2007-2019 reruns.
- **Found, not fixed:** `build_insider_panel.py` takes the min of `TRANS_DATE`
  as a `DD-MON-YYYY` string (lexicographic), so multi-date filings can get the
  wrong transaction date. Effect on historical classification unmeasured.
  Fixing it rebuilds the bulk events the in-era lead was measured on
  (forward ledger doc §5c).
- **Congress:** forward-only. `final/scripts/av_congress_pull.py` needs the
  premium AV key and is **untested** against the REST response.
- Code: `final/src/insider/` (`build_insider_panel.py`, `screen_insider.py`,
  `posthoc_insider.py`). Small reports are committed in `final/out/insider/`.
  [Results](final/models/2026-09-23-insider-congress-results.md),
  [pre-registration](final/models/2026-09-23-insider-congress-preregistration.md).

---

## 5. In flight

Nothing below is current state until it lands.

| branch / worktree | what it will change | state | source |
|---|---|---|---|
| `worktree-factor-composite-reset` (5 commits) | "Merge whole branch, nothing dropped" (Gabe, 2026-09-23): the Retrain-ALL speedup (`build_features_fundamentals_sharadar.py`, 2:42 → 59s, verify-pass), the `blend_q75.py` backtest and report, and `current_signal_blend_full.csv` (per-ticker query statuses). **Its app.py UI reorg is superseded** by the 09-23 baseline, and its `current_signal_blend.py` must not be taken (it drops the frozen-factor guard) | blocked on app.lock contention and app-manager reconciliation | `worktree-factor-composite-reset:final/models/2026-09-22-session-handoff.md`; LEDGER landing queue #2; APP.md |
| `worktree-agent-ab20b69899959cac5` (COO WO-6) | Survivorship-safe down-cap grid rebuild (COO decision #2, Gabe approved) | Phase 1 in progress; Phase 2 blocked on `SHARADAR_API_KEY` | LEDGER; COO.md log 2026-09-24 |
| `app` | = `bca3f7c`, content-identical to integration's `final/app/**`. It should `git merge integration` (c8bba77) | awaiting the merge | `HANDOFF-app.md`; LEDGER landing log |
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
2. ~~Landed code depends on an uncommitted file (`ic_weighted_composite`).~~
   **Resolved 2026-09-23** by f680f94 (audit landed; the integrator verified
   `import current_signal_composite` on integration).
3. **Down-cap survivorship vs the composite's live role.** The AV doc (landed
   2026-09-22) says every cap150/cap500 result is unreadable. The full-spec
   doc (landed 2026-09-23; §4 "~4,011 tickers ever eligible") and the landed
   composite meta quote cap150 numbers without that caveat. The insider
   results doc does carry it. The live composite candidate and the
   forward ledger both use cap150. **Gabe / COO decision #2:** fund the SF1
   pull for ~4.6k names and rebuild, or move the candidate to cap2000.
4. **IC's role (methodology, for the COO).** Round 19 (2026-09-16) retired IC as
   a feature-admission gate (rank correlation with earnings +0.019). Gabe's
   2026-09-22 reframe made pooled IC the composite's *target metric*, and the
   IC-weighting, leverage and §19 cross-model results are judged on IC/rho.
   The insider round (2026-09-23) used both an IC screen and the shuffle
   null, and they disagreed: sellers are wrong-signed on IC but beat the
   shuffle null on the book. The two standards need an explicit
   reconciliation.
5. **App-owned inconsistencies (for `pipe-dream-app-manager`).**
   `final/app/README.md` (2026-09-18) describes the six-tab, q75/xrank-only
   layout. `current_signal_blend.py` and `current_signal_blend_meta.json` say
   `"role": "primary"` and mention a "Theoretical Model tab". The 09-23
   baseline has the blend as a Candidate tab.
6. **Stale coordination entries (for their owners).** COO.md's Active bets
   row still calls the blend "app primary", and its q75 dead-end note says
   "half of the app's primary blend". Both contradict the 09-23 baseline
   (blend is a Candidate tab). COO decision #4 (push the audit branch) is
   moot, because it was pushed and landed (f680f94). The ledger's AV row says
   new commits need landing, but `de4fdb5` is already in integration. Project
   memory (`project_thin_liquidity_options_edge_idea.md`) still says the AV
   bulk pull is RUNNING, but it crashed at 18:09.
7. **Earlier decisions still pending** (COO.md): why the HMM regime gate was
   retired; whether to renew AV premium (around 2026-10-22); whether the
   integrator may fast-forward `main` to `integration` (`main` 7898b52 is far
   behind); the composite open questions (COO decision #7: is 2020 regime or
   luck, adopt `leverage`, a Deflated-Sharpe/Reality-Check gate, EWMA beta);
   the forward-ledger record cadence (every 40 trading days, monthly, or at
   each panel refresh; forward ledger doc §5f).
8. **`neutralize_on_sector` convention (COO decision #6, methodology, for
   Gabe).** It demeans the factor within sector but not the return. The
   insider round showed that this turns a sector-timing effect into a fake
   within-sector t (+3.10 → 0.65 when both sides are demeaned). The same
   function produced the physics doc §7 `*_neutral` rows and the reset's
   neutral cells. The COO recommends reporting the both-sides number next to
   it as standard, without changing past numbers. Not yet decided.
9. ~~COO worker worktrees on origin/main.~~ **Resolved 2026-09-24:** WO-5
   landed at 371f2d0 and WO-2+3 at f3233bd, both via integration.

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
│   │   ├── insider/              insider (SEC Form 345) signals, 2026-09-23
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
| Insider panel, screen, post-hoc (download 81 SEC quarterly zips first) | `build_insider_panel.py` → `screen_insider.py` → `posthoc_insider.py` | [insider results](final/models/2026-09-23-insider-congress-results.md) "Reproduction" |
| Composite, current spec (universe → factors → panel → outcomes → beta, then `ic_weighted_composite.py`, `prediction_ledger.py record/score`) | per the spec | [full spec](final/models/2026-09-22-composite-model-full-specification.md) §6 |
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
| IC-weighted score without renormalising | missing-factor rows compressed | re-run after the fix | corrections §12 |
| Sector-neutral t from demeaning the factor only | insider buyers t +3.10 "within sector"; both sides demeaned gives 0.65 | fire rate vs sector return, corr −0.79 | insider results §3 |
| `build_insider_panel.py` min of `TRANS_DATE` as a string (**unfixed**) | "02-MAR-2026" sorts before "26-FEB-2026"; 17 of 320 rows mismatched | live-vs-bulk Form 4 validation | forward ledger doc §5c |
| AV pull `IncompleteRead` not retried | bulk pull died at 2010-08-18 | `pull.out` traceback | COO.md; `final/scripts/av_options_pull.py:151` |
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
- **`current_signal_blend.py` hardcodes `MAIN_ROOT` to the main checkout**
  and puts its `src/` and `reset2026/` on `sys.path` first. Importing it from a
  worktree can silently pick up the main checkout's stale `composite.py`
  (corrections §19 row 3; ledger landing log). Don't import it for analysis.
- **Sector-neutral numbers:** `neutralize_on_sector` demeans only the
  factor. When a factor's sector concentration tracks sector returns, the
  result looks like within-sector skill but isn't (insider round). Whether
  to report both-sides numbers as standard is pending (Open conflicts #8).
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
EARNINGS/ESTIMATES/INSIDER/NEWS as backtest features · **insider plain
counts** (`ins_buyers_90`/`ins_sellers_90`, cap150, h=40; no 30/180-day
variants) · **congress as a backtest factor** (forward-only) · **the
earnings-timing family** (6 trials, closed 2026-09-23 by the 8-K test; reopen
only with point-in-time *announced* dates, tested forward). Screened
negative but not certified by the COO: Amihud illiquidity, book-to-market
(wrong-signed), exponent transform, `fcf_yield`, `profitability_trend`,
regime conditioning (stopped by its own staging rule).

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
| [`final/models/2026-09-22-composite-model-corrections.md`](final/models/2026-09-22-composite-model-corrections.md) | 2026-09-22 → 09-23 | landed (§0-19) | corrections, LCID retraction, beta term, safeguards, IC weighting, extensions, turnover, third hold-out spend, options overlay, §19 cross-model MIDDLE |
| [`final/models/2026-09-22-composite-model-full-specification.md`](final/models/2026-09-22-composite-model-full-specification.md) | 2026-09-22 | landed | clean spec of the IC-weighted 8-factor composite: start here (§4 lacks the survivorship caveat; §6 points to the old AGENTS.md table) |
| [`final/models/2026-09-22-alpha-vantage-spin.md`](final/models/2026-09-22-alpha-vantage-spin.md) | 2026-09-22 | landed | AV coverage, options pull, **down-cap survivorship finding** |
| [`final/scripts/AV_PULL_WINDOWS.md`](final/scripts/AV_PULL_WINDOWS.md) | 2026-09-23 | landed | moving the AV pull to Windows |
| `worktree-factor-composite-reset:final/models/2026-09-22-session-handoff.md` | 2026-09-22 | in flight | blend promotion (UI part superseded), query fix, retrain speedup |
| [`final/models/2026-09-23-insider-congress-preregistration.md`](final/models/2026-09-23-insider-congress-preregistration.md) | 2026-09-23 | landed | insider k=2 trials, congress ruled untestable before any return |
| [`final/models/2026-09-23-insider-congress-results.md`](final/models/2026-09-23-insider-congress-results.md) | 2026-09-23 | landed | insider counts fail; sector-neutral artefact; opportunistic-buyer lead; congress forward-only |
| [`final/models/2026-09-23-earnings-announcement-premium-8k.md`](final/models/2026-09-23-earnings-announcement-premium-8k.md) | 2026-09-23 | landed | WO-5: 8-K Item 2.02 EAP, DEAD; closes the earnings-timing family (Part 2 "Reading" first sentence struck by the COO) |
| [`final/models/2026-09-23-forward-ledger-leverage-opportunistic-buyers.md`](final/models/2026-09-23-forward-ledger-leverage-opportunistic-buyers.md) | 2026-09-23/24 | landed | WO-2+3: forward pre-registration of icw9 leverage and opportunistic buyers; first blind record 2026-09-08; TRANS_DATE bug |
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
- Insider data source "TBD / AV" (data-sourcing research, 2026-09-17) → EDGAR Form 4 (session-handoff, 2026-09-22) → SEC Form 3/4/5 bulk data sets (insider prereg and results, 2026-09-23, landed).
- AV `HISTORICAL_VOLUME_OPEN_INTEREST_RATIO` gives only a ratio (session-handoff §5, 2026-09-22) → `HISTORICAL_OPTIONS` has raw volume and OI (AV spin doc §1, 2026-09-22).
- Stop-loss 15% adopted (AGENTS.md Round 8) → no stop; Round 13 holds to horizon (AGENTS.md note, 2026-09-11; reset doc §5).
- AGENTS.md sections "Current state (as of 2026-09-02)", "Known gaps", "Future plans", "Where the fuller history lives" → history only. Read them at `git show 29eb67b:AGENTS.md`. Their live content (reproduction table, options gaps, dead ends) is carried in §4, §7 and §8 above.
- `Claude outputs/RUNBOOK.md` (Round 12, 2026-09-09) → `final/src/sweep/RUNBOOK.md` (self-labelled superseded).
- `current_signal_composite.py` fails at import on integration (README Open conflicts #2, 2026-09-23 first sweep) → resolved, audit landed with `ic_weighted_composite.py` (LEDGER landing log, f680f94, 2026-09-23).
- Corrections §10-18, the full-spec doc, `ic_weighted_composite.py` and `prediction_ledger_v3.csv` are uncommitted in the audit worktree (README §5, 2026-09-23 first sweep; COO decision #4) → pushed and landed at 736a424 / f680f94 (LEDGER, 2026-09-23).
- Insider/congress pre-registered, no results (README §5, 2026-09-23 12:28 prereg) → results landed, counts a dead end, congress forward-only (insider results doc; COO.md; c8bba77, 2026-09-23).
- Insider and congress data only record the execution date (the premise the insider session started from, 2026-09-23) → SEC Form 345 has `FILING_DATE` and AV congress has `filed_date` (insider results §1, 2026-09-23).
- AV options bulk pull running (AV spin doc / memory, 2026-09-22) → crashed on `IncompleteRead` at 18:09 (COO.md, `pull.out`, 2026-09-23).
- `leverage` is a ready candidate for an explicit promotion decision (corrections §13, 2026-09-22) → contaminated in-era; confirmation only via a forward-ledger icw9 column (COO.md WO-2, 2026-09-23).
- Laddered rebalancing as a next step for the composite (reset doc §6 / COO leads, 2026-09-22) → smooths dispersion but doesn't cut turnover (corrections §15), and the COO did not launch it (COO.md, 2026-09-23).
- Corrections §12 OOS table: fit-odd→test-even IC +0.0302 (corrections §12 table, 2026-09-22) → +0.0304 after the renormalisation fix (same section's text; §19 sanity gate, 2026-09-23).
- WO-2+3 and WO-5 in flight on origin/main worktrees (README §5 / Open conflicts #9, 2026-09-23) → both landed via integration: 371f2d0, f3233bd (LEDGER / COO.md, 2026-09-24).
- Earnings announcement premium via 8-K as an open lead (COO.md leads, 2026-09-23) → DEAD, earnings-timing family closed at 6 trials (EAP 8-K doc; COO.md dead ends, 2026-09-23).
- `leverage` / opportunistic buyers "confirmation being built" (README §4.1/§4.6, 2026-09-23) → recording forward since panel date 2026-09-08 (forward ledger doc §5e, 2026-09-24).
- EAP 8-K doc Part 2 "Reading", first sentence (portfolio-impact claim, 2026-09-23) → struck by the COO: the icw9−icw8 gap is +0.10%/yr on in-sample weights (COO.md, 2026-09-23).
