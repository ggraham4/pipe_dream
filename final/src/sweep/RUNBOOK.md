# The sweep package — runbook and reference

**Covers Rounds 12–19 (2026-09-09 → 2026-09-16).** Supersedes the Round 12-only
version of this file.

> **ROUND 19 CHANGED THE FEATURE-ADMISSION GATE. Read §9 before adding or
> judging any feature.** IC is retired as an admission criterion, standing rule
> 8 in §10 has been rewritten, and the replacement is a shuffled-feature null
> scored on `decile_volq_excess`.

One command per line. A trailing `# comment` parses as an argparse argument and
has silently skipped probes on this project before, so nothing below has one.

All commands run from `~/pipe_dream/final/src` in your own terminal. The device
bridge caps at ~3.9GB RAM and ~45s per command, well short of a panel load.

```
cd ~/pipe_dream/final/src
```

---

## 0. What this package is, and the one idea it is built on

A walk-forward backtest has an expensive half and a cheap half, and conflating
them is what made earlier rounds unaffordable:

- **Expensive half** — training a model at every timepoint to produce a *score*
  per (date, ticker). Cost is one full walk-forward per signal configuration.
  `scorecache.py`.
- **Cheap half** — turning scores into a portfolio: breadth, weighting, stops,
  costs, bucketing, vol-targeting. Given cached scores this is pure numpy and
  effectively free. `portfolio.py`.

So 27 signal configs × 48 portfolio configs = 1,296 backtests costs 27 model
runs, not 1,296. Everything else in the package follows from that split.

`outcomes.py` is the enabler: it precomputes every (timepoint, ticker) realized
outcome across 4 horizons × 10 stop levels and stores **gross** returns only.
Net is a deterministic transform of gross, which makes `cost_bps` a free axis.

---

## 1. Module map

| module | what it does |
|---|---|
| `_num.py` | rankdata, spearman, skew, kurtosis, norm_cdf/ppf, ridge. **stdlib + numpy only** — no scipy or sklearn, because neither is guaranteed on the target env |
| `outcomes.py` | vectorized realized outcomes + `verify_against_reference()` gate (passed 12,000 comparisons exactly) |
| `scorecache.py` | `SignalConfig`, `PanelContext`, `run_signal()`. The expensive half. Also `FEATURE_SETS`, `PANEL_FOR`, `BACKLOG_SETS`, and **`shuffle_col`/`shuffle_seed`** (R19 — the null) |
| `portfolio.py` | `Prepared`, `_pick_idx`, `_weights`, `simulate`, `score_run`, `mean_ic`, **`decile_stats`** (R19 — the primary metric). The cheap half |
| `stats.py` | Deflated Sharpe, White's Reality Check, matched random-selection null, grid consistency |
| `factors.py` | sector map, cross-sectional design matrix, residualize, variance_removed |
| `feature_ic.py` | per-feature IC screen, BH q-values, permutation null on max\|t\|, era split |
| `attribute.py` | factor attribution ladder, null attribution, window concentration |
| `breadth.py` | **Round 15.** Effective breadth, the ladder, decile analysis, selection-time neutralization |
| `rates.py` | **Round 14.** Interest-rate sensitivity features. Screened and rejected; kept for reuse |
| `events.py` | **Round 16.** Earnings-event timing and tail-shape features |
| `enrich.py` | **Round 19.** Hypergeometric / Poisson-binomial enrichment + BH, for "which industry groups does the model over-pick". numpy only |
| `gridspec.py` | the frozen grid |
| `cli.py` | orchestrator — 10 subcommands |

---

## 2. Commands

```
probe       timing probe at several training-set caps
verify      BLOCKING correctness gate against the production baseline
scores      build the score cache (the expensive half)
outcomes    build realized outcomes + reference verification
features    per-feature IC screen
portfolio   score the portfolio grid (the cheap half)
attribute   factor attribution + grid consistency for one cell
breadth     Round 15 — effective breadth, B1/B2/B3/B4
horizon     Round 15b — does the horizon breadth lever survive its costs
prune       Round 17 — rank feature subsets by model IC
```

### The two flags that are not optional

`--null-draws` on `portfolio`, `breadth` and `horizon`. **Without it there is no
gate at all.** Breadth, tranching and wider books all improve compounded return
with literally zero signal by cutting variance drag — in this harness 27% of
zero-signal configs beat the market, best 2.577×. Only the construction-matched
null separates that from selection. Beating SPY is not evidence and is not
reported as if it were.

`--selection-trials` on any `--only` run. The Deflated Sharpe deflates against
the number of configs the winner was *selected* from, not the number scored in
this call. This bit the project once: a hold-out run printed DSR 0.956 against 4
trials where the honest 1,152 gives **0.791**.

---

## 3. Standard sequence for a new round

```
python3 sweep/gridspec.py all
python3 -m sweep.cli probe --start 2023-01-03 --caps 0,1500000,500000
python3 -m sweep.cli verify
python3 -m sweep.cli scores --cells sweep/cells_phase_a.json --resume
python3 -m sweep.cli outcomes
python3 -m sweep.cli portfolio --grid sweep/grid_portfolio.json --era nominate --null-draws 100
```

`verify` is **blocking**. It compares the harness's top-5 picks window by window
against the production baseline. Do not run anything downstream until it prints
`VERIFY PASS` — if the harness does not reproduce production pick-for-pick, every
cell measures something other than the baseline and the round means nothing.

`scores` is fully resumable: per-timepoint checkpoints, finished cells skipped,
cells grouped by (panel, horizon) so the panel load is paid once per group.
Timing: **~274s per cell** at `train_cap=500000`, h=40.

### The hold-out. Once. It is spent.

```
python3 -m sweep.cli portfolio --grid sweep/grid_portfolio.json --era holdout --only <cell_id> --i-am-confirming --null-draws 200 --selection-trials 1152
```

The CLI refuses `--era holdout` without both flags and refuses to run a grid
there at all. **2020–2026 was spent in Round 13** confirming the top-5 breadth
choice. Rounds 15, 15b and 16 are all nomination-era only and `breadth`/`horizon`
refuse `--era holdout` outright.

---

## 4. Feature sets (`scorecache.FEATURE_SETS`)

| name | cols | panel |
|---|---|---|
| `price` | 11 | `features_sharadar_pit.parquet` |
| `novol` / `volonly` | 9 / 2 | same |
| `price_fund` | 24 | `features_with_fundamentals_sharadar_pit.parquet` **(deployed)** |
| `rates` / `price_fund_rates` | 5 / 29 | `features_with_rates_sharadar_pit.parquet` |
| `events` / `price_fund_events` | 14 / 38 | `features_with_events_sharadar_pit.parquet` |
| `fund_events` | 23 | same |
| `survivors` | 9 | same |
| `minimal` | 5 | same |
| `path` / `price_fund_path` | 1 / 25 | `features_with_fundamentals_sharadar_pit.parquet` **(R19, `accel_20`)** |
| `pf_<column>` × 15 | 25 each | rates or events panel **(R19 backlog, one per candidate)** |

**Convention:** a bare family name (`rates`, `events`) screens ONLY the new
columns, so the multiple-testing family is the new hypotheses rather than a
re-test of columns already known to be dead. The `price_fund_*` variants are the
combined sets for modelling.

`survivors` and `minimal` deliberately exclude the `_actual` and `_known` event
variants. `days_to_next_filing_actual` is the strongest column in any screen the
project has run (t −4.17) but rests on the true next-filing date, which this
dataset cannot prove was knowable at the time. Training on it would ship an
unverifiable column. The seasonal estimator is the tradeable version.

**Adding a feature family — the three places, and the failure mode of each:**

1. `FEATURE_SETS` — the column list.
2. `PANEL_FOR` — which panel carries it.
3. **`PanelContext.want`** — the load list. Forget this and
   `feature_ic.screen()` silently filters your features to an empty list and
   reports "no windows", which reads as *no signal* rather than *nothing was
   measured*. Round 17 lost a run to exactly this. `screen()` now raises and
   names the missing columns instead.

---

## 5. Results to date

| round | question | verdict |
|---|---|---|
| 12 | does any of 1,296 configs beat the market? | **NO.** DSR 0.746, Reality Check p=0.61, best cell 2.938× with IC 0.0020 |
| 13 | is the fundamental signal real? | **NO.** It is a sector bet — `rnd_intensity` t 3.28 → 0.77 neutralized; 0 of 24 features reach \|t\|>2 |
| 14 | do rate-sensitivity features help? | **NO.** `rate_beta_x_move` t −2.27, but 2019 alone is 8% of windows and **45% of the effect** |
| 15 | is breadth the missing lever? | **NO.** Capped at `1/rho ≈ 16` per window by ρ̄ = 0.055–0.076, flat across book sizes and horizons — a property of the asset class |
| 15b | does shortening the horizon help? | **NO.** Breadth varied 13× (24.7 → 366.9 bets/yr); the result did not move. Direct evidence that IC ≈ 0 |
| 16 | do earnings-event features help? | **PARTIALLY YES.** `days_to_next_filing` is the first feature to clear BH (q=0.0004) and the permutation null, survives LOYO (min \|t\| 3.42) |
| 17 | does pruning help? | see the Round 17 docs |
| 18 | should the xrank label replace q75? | **NO.** q75 hold-out 1.526× SPY, xrank **0.771×**. Displayed, not traded |
| 19a | is there ORDER information in a 20-day price path? | **INCONCLUSIVE ×3.** `slope_20` dies at the tail (+0.33); `accel_20` reaches −1.97 paired, 17/20 years one sign. \|t\|=2.0 was the wrong bar — an order-free control reaches **2.47** |
| 19b | does `accel_20` belong in the model? | **NO.** Shuffled-feature null: 70th percentile on all three metrics. Null median 1.850 vs deployed 2.796 — the 25th column *dilutes* |
| 19c | which industry groups does the model over-pick? | Healthcare and Energy in **both** eras (q<0.10); Biotechnology at `industry`. Descriptive, not an attribution |

**The one positive.** `days_to_next_filing_actual`: IC −0.0153 (h20, t −4.17),
−0.0179 (h40, t −3.14). Gains strength under sector neutralization, so it is not
a sector bet. Sign matches the **earnings announcement premium** (Beaver 1968;
Frazzini & Lamont 2007). The provably-causal seasonal estimator gets t −2.18.

**Standing procedure since Round 14:** any candidate that survives a gate gets
the **leave-one-year-out concentration test** before it is believed. That test
is what killed `rate_beta_x_move` after BH and max-\|t\| had already said no for
the wrong reason, and it is what validated the event feature.

**Gate philosophy changed 2026-09-12** — see the DECISION BAR section of
`claude/validation-gates.md`. Gate B's t>3 threshold is a hypothesis-testing bar
applied to what is actually a decision problem. Deploy when expected excess
return is positive after costs and the downside is understood; significance is
not required. Gate A (placebo, look-ahead, pool integrity) is unchanged and
absolute — it catches *bugs*, not insignificance. LOYO survives the change
because concentration is about forward expectation, not significance.

---

## 6. Bugs this package has shipped and caught

Read this before adding a feature. Every one passed its automated checks.

| bug | how it presented | what caught it |
|---|---|---|
| **NaN ranking** (R13) | `np.argsort` sorts NaN last, so an 85%-missing column got the highest ranks and manufactured IC | asking what a mostly-empty column *should* score |
| **NaN era split** (R14) | a plain `.mean()` over one NaN returned NaN for a whole era, printed as "no estimate exists" | asking why an estimate would be missing |
| **breadth estimator** (R15) | assumed equal position variances; under invvol over vol quintiles it reported BR_eff 19.1 where truth was 5.0 | `capture > 1`, impossible by definition |
| **merge_asof alignment** (R16) | `merge_asof` resets the index, so `.sort_index()` is a no-op and six columns landed on wrong rows | a fire rate of 0.7% where cadence implies 64% |
| **empty feature list** (R17) | missing from `PanelContext.want` → screened nothing, reported "no windows" | noticing the screen reported *nothing*, not *no signal* |
| **inf in features** (R17) | `pct_change` over zero revenue → 27k infinities; XGBoost accepts NaN but rejects inf | three cells dying at training time |
| **live candidate pool** (R18) | the live script dropped rows with any NaN feature; I "fixed" it to match a backtest I had *assumed* scored everything. It does not. 59 names (3.5%) wrongly admitted; `KARD` entered the picks with a NaN `volatility_60`, which `_bucket_idx` files into the LOWEST vol quintile | **Gabe looked at the picks and said they were obviously bad.** No automated check fired |
| **pandas str dtype** (R19) | `taxonomy.load()` did `(v or "").strip()`. Under object dtype `.astype(str)` maps NaN→`"nan"`; under Arrow-backed `str` it *preserves* NaN, and `float('nan')` is truthy | crashed on Gabe's Mac, passed on mine. Same CSV, different pandas |
| **silently empty universe** (R19) | `sector_view.eligible_universe()` imported a module that imports xgboost at module scope; a bare `except` turned any failure into an empty set, and every group then read 100% active weight | noticing 100% concentration at *every* level |
| **pandas round-trip retyped a 2.3GB panel** (R19) | appending one column via `to_pandas()`/`from_pandas()` per batch silently changed `ticker` from `large_string` to `string` across the whole panel | comparing the schema against a sibling panel afterwards |
| **grid-offset dependence** (R19) | `feature_ic` uses one of *forty* equally-valid non-overlapping grids and silently takes offset 0. `accel_20` reads +0.0218 there and −0.0011 on all days; 21 of 40 offsets flip sign | a pre-registered SIGN gate disagreeing with the promotion evidence |
| **shared null was not shared** (R19) | one null reused across 15 candidates passed **11 of 15**. Two order-free nulls on the same era differ by 1.84 sd on `mult_ratio` | 11 of 15 previously-rejected features passing at once is not plausible |
| **a control that cannot fail** (R19) | Amendment B nominated `volatility_60` as the positive control for `decile_volq_excess` — a metric that *buckets on volatility* and is built to be blind to it | the control coming back at 1.69 against a 3.0 bar |

**The pattern, six times over:** the automated checks verified *internal
consistency* and the bug was in *correspondence to the outside world*.
Distribution-shaped checks — coverage, dispersion, range, monotonicity — cannot
detect a permutation of rows, because a permutation preserves every
distribution.

**Standing rule.** Any feature whose expected magnitude or frequency can be
derived from something already known — a filing cadence, a sector count, a named
company, a physical bound — gets that number written into the acceptance check as
an explicit expected value with a tolerance. Checks that only ask "is this
self-consistent" are necessary and never sufficient.

This is Gate A7c's lesson restated: **verify by naming what should be there, not
by counting.** Every automated check passed on a 2008 universe with no Apple in
it.

---

## 7. Adding a feature family — the template

`rates.py` and `events.py` are the two worked examples; `build_rate_features.py`
and `build_event_features.py` are their builders. The pattern:

1. **Compute causally.** Every trailing window shifted by one. If the feature
   points forward, say exactly how and prove it — `events.py` carries three
   variants of next-filing date precisely so the causal one can be compared to
   the unverifiable one rather than argued about.
2. **Write a builder with acceptance checks that have external expected
   values**, not just self-consistency. See §6.
3. **Do not overwrite the existing panel.** New family → new panel file, so the
   deployed model and every prior result stay reproducible.
4. **Wire three places** (§4) — and remember `PanelContext.want`.
5. **Screen the new columns alone first**, so the multiple-testing family is the
   new hypotheses. One feature set PER COLUMN, not per family: the bundled
   `rates`/`events` sets answer "does this group help", which is a different
   question from "does this column belong". See `BACKLOG_SETS`.
6. **Run the shuffled-feature null (§9), not the IC screen.** Own null per
   candidate, `decile_volq_excess` primary, BH across candidates.
7. **Run LOYO on anything that passes** before believing it.

---

## 8. Housekeeping backlog

- 3 unrun Round 12 cells
- grid-level max-t(α) permutation
- duplicate `relative_strength_20` in the panel
- stale validation scripts still pointing at pre-Round-11 paths
- `roll5` vs `cap500k` calendar-drift swap (see the deployed-config doc §5 —
  `TRAIN_CAP` is row-anchored so its calendar span shrinks as the universe grows)
- delete leftover `_cmd_*_snippet.py` files in `sweep/`

---

## 9. Round 19 — the feature-admission gate (READ BEFORE ADDING A FEATURE)

Full write-ups: `models/2026-09-16-shuffle-null-replaces-the-ic-gate.md`,
`models/2026-09-16-accel20-fails-and-the-grid-offset-problem.md`.

### Why the old gate was retired

Gabe, 2026-09-16: *"our thresholds are so strict that they would exclude
features already in the model."* He was right, and not narrowly:

| feature | `sweep.cli features` t | |
|---|---|---|
| `volatility_60` | **−0.41** | 60.3% of XGBoost's split importance |
| `momentum_20` | **+0.23** | production feature; sign flips on 16 of 40 grid offsets |
| `accel_20` | +1.88 | rejected on this evidence |

A screen that rejects the model's single most important feature cannot decide
what goes into the model. Three independent defects, any one of which is fatal
for admission: IC measures the wrong population (§10 rule 8); the non-overlapping
grid is offset-dependent for weak features (`check_grid_offset.py`); and none of
it is denominated in what the portfolio earns.

`sweep.cli features` is still a fine **description of the data**. It is no longer
evidence that a column belongs in the model.

### The replacement

**Metric.** `decile_volq_excess` is primary; `mult_ratio` and `info_ratio` are
reported beside it and gate nothing.

**Null.** Refit the identical cell with the candidate column **permuted within
each date** — same marginals, same column count, cross-sectional pairing
destroyed. `SignalConfig(shuffle_col=..., shuffle_seed=...)`; a null draw is an
ordinary cell with its own id and cache entry.

*Not* "drop the column". Dropping changes the model's shape and confounds "this
column carries nothing" with "24 columns behave differently from 25".

**Three rules the null has already taught us the hard way:**

1. **A shuffle source must be a CANDIDATE, never a production feature.**
   Permuting `momentum_20` measures the cost of *destroying* information, lands
   far below the null, and would make any candidate look like a pass.
   `build_shuffle_null.plan()` refuses it.
2. **Every candidate needs its OWN null.** Two order-free nulls on the same era
   and construction came back at 1.919 ± 0.415 (shuffling `accel_20`) and
   1.230 ± 0.330 (shuffling `earnings_in_window`) — 1.84 pooled sd apart, and
   not explained by the column's cardinality (rank corr with the result +0.066).
   A single shared null passed **11 of 15** backlog candidates and was an
   artifact. On `decile_volq_excess` the same gap is 1.05 sd — better, still
   too large to borrow.
3. **A market-level column cannot be tested this way at all, and that is a
   proof, not a limitation.** A date-constant column (VIX, fed funds, 10y)
   permuted within its date is the identity operation: the null draw is
   bit-identical to the real cell. A feature whose matched shuffle cannot be
   distinguished from itself carries exactly zero cross-sectional information.
   Market state enters as a *beta* (name-specific sensitivity) or not at all.

**Gate.** Beat the 80th percentile of the null — implemented as a one-sided t of
the real cell against its own draws (prediction form, `sd·√(1+1/n)`), then
Benjamini-Hochberg across candidates, pass at **q ≤ 0.20**.

Use the parametric p, not the empirical rank: with *n* draws the empirical p is
floored at 1/(n+1), so at 25 draws and 15 candidates BH needs the best one under
0.20/15 = 0.013 — **unreachable by construction**. An empirical-rank gate at
this sample size rejects everything regardless of the data, which is not a test.

**Power is the binding constraint, not rigour.** Null sd on the decile is
~0.0005 against a baseline of +0.00584. We are looking for effects of ~10% of
the metric against a null spread of ~8%. Expect to reject; a clean rejection is
a real answer here.

### A performance gate WITHOUT the null is worse than the IC gate

In the 84-cell sweep the **best cell was a scrambled one** —
`...shufaccel_2012` at **3.309×**, beating the deployed model's 2.938× and every
real configuration ever scored in this project. Never quote a backtest
improvement for a feature without its matched null beside it.

### Commands

```
python3 build_shuffle_null.py --plan --candidate <col> --featureset <set> --draws 20
python3 build_shuffle_null.py --plan-backlog --draws 8
python3 -m sweep.cli scores --cells sweep/runs/backlog_cells.json
python3 -m sweep.cli portfolio --grid sweep/runs/shuffle_null_portfolio.json --era nominate
python3 build_shuffle_null.py --score-backlog
python3 check_grid_offset.py
```

Long runs go through `tee` with a DONE banner, not a silent `nohup`:

```
( python3 -m sweep.cli scores --cells sweep/runs/backlog_cells.json 2>&1 ; echo "=== SCORES DONE $(date) ===" ) | tee ../out/backlog2.log
```

### Promoting a column without trading it

`features.CANDIDATE_FEATURE_COLS` is a list deliberately separate from
`FEATURE_COLS`. A column listed there is computed into every panel and visible
to every screen, and reaches no model. `build_accel_feature.py` is the worked
example and refuses to run if its column ever appears in `FEATURE_COLS`.
Materialise onto an existing panel arrow-natively — never round-trip batches
through pandas (§6) — and assert the promoted column matches the screened one
bit for bit, or the screen's evidence no longer applies to what is traded.

---

## 10. Standing rules that bind this package

From `AGENTS.md`, unchanged:

1. Never push to or redeploy the live app without Gabe's explicit,
   in-the-moment permission.
2. No destructive git operations without explicit request, never on `main`.
3. `.gitignore`'d paths are regenerable, not disposable-without-thought.
4. **Never run `git add`/`commit`/`push`.** Deliver changed files and the
   commands; Gabe runs them.
5. Never store live API keys in any file inside this repo.

Plus, from `claude/validation-gates.md`:

6. Pre-register the prediction before running.
7. Attack spectacular and disappointing results equally.
8. **Trust the high-observation-count metric over terminal value** —
   **REWRITTEN IN ROUND 19.** The old wording was "trust IC over terminal
   value". The instinct was right and the instrument was wrong.

   Across all 64 cells scored to that point, the rank correlation between a
   cell's `mean_ic` and what it actually earned is **+0.019**. The best cell
   (2.94×) has IC +0.0020; the highest IC in the set (+0.0243) earns 1.49×;
   `volonly_xrank` has IC **−0.0145** and earns 2.04×. The two worst cells in
   the sweep are fly variants whose IC beats anything in the top four.

   IC weights all ~1,600 names equally; the book holds five. It is a
   high-powered measurement of something the portfolio does not do.

   The metric that keeps the observation count *and* measures what is traded is
   **`decile_volq_excess`** (`portfolio.decile_stats`): top 10% within each
   volatility quintile — the deployed selection rule, widened — averaged over 82
   windows at ~160 names each. Measured head to head on four cells, `mult_ratio`
   spans 3× where the decile spans ±10%.

   Terminal value remains the worst of the three and is still not a gate.
9. Gates do not move after seeing the result. Re-specification happens in its
   own commit, before the next experiment, and prior verdicts stand.
10. One command per line when handing over runs.
