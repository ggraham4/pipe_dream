# WO-33: rolling-window refit of the icw9_seas weights (walk-forward)

Commissioned by the COO on 2026-09-30. Gabe's question: "weights don't need to be set in stone". Branch
`worktree-agent-ae2ebd3a1386cb352`. Code: `final/src/rollweights/rollweights.py`. Outputs:
`final/out/rollweights/`.

Two parts:

- **Step 1** covers 2010–2019 and is in-era.
- **Step 2** covers 2020-01-02 to 2026-07-30. Gabe approved it on 2026-09-30 ("wo-33 is also a go"). It is
  hold-out read #13, and it fits weights on 2020+ data.

Status: **DONE.** Pre-registration committed in aad1158 before any arm-vs-control statistic. Results are in §3. Both arms were KILLED in Step 1, so there is no change to the live weights.

---

## 1. Pre-registration: Step 1 (spec as issued by the COO, pinned before results)

**Question.** Does refitting the icw9_seas factor weights at regular intervals on a trailing window beat
refitting them on all history to date?

**Mechanism and prior.**
- For: factor momentum (Ehsani-Linnainmaa 2022 JF; Gupta-Kelly 2019). Factor premia are positively
  autocorrelated at 6–12 month lookbacks, so weights from a recent window might track which factors are
  currently paying.
- Against: this project's high-degree-of-freedom fits have overfit before. Short windows give noisy IC
  estimates, because the effective n per 40-day label is small.

**Weight rule.** This is exactly the live icw9_seas rule. Only the estimation window changes.

`w_k = sign_k * max(0.1, |t_k| - 1) / sum_j max(0.1, |t_j| - 1)`

This is `screen_insider.fit_weights` with `ic_weighted_composite.SIGNS_V9_SEAS`. The rule takes nine
factors: the eight production factors plus `seas`. Each factor's sign is fixed by the rule. `t_k` is the
Newey-West (lag 39) t-statistic of the factor's per-date Spearman IC against `forward_return_tradable_40`.
A date counts only if it has at least 20 names (`SI.daily_corr`).

**Fitting frames.** These are the data the live t-statistics came from. The fitting universe is not the
same as the evaluation universe, and that mismatch is also true of the live rule.

- **The 8 production factors.** These are fitted on the v1 cap150 frame. The live t-statistics are in
  `ic_weighted_composite_report.json`, dated 2026-09-22.
  - Today's `composite_panel.parquet` cannot reproduce them. It was rewritten at 2026-09-30 10:46. For
    example, it gives a momentum t of 1.533 against the stored 1.382.
  - A dated, frozen snapshot does reproduce them exactly, to 6dp:
    `composite_panel_v2_through_2026-09-08.parquet`, restricted to v1 tickers and `eligible_cap150_v1`.
    That snapshot is the fitting frame for the 8 factors.
- **`seas`.** This is fitted on v2 col c cap150, using the WO-18 universe
  (`screen_seas.load_universe` on the WO-18 `seas_factor_v2.parquet`). It reproduces `SEAS_T` exactly.
- **short_interest_days_to_cover.** It has no data in the v1 frame before 2020. Its t is therefore NaN,
  which gives it the floor weight throughout Step 1, as in live.

**Reproduction gate (hard assert, passed).** Applied to the full 2007–2019 window through this code's own
IC path, the rule reproduces the live `PRODUCTION_WEIGHTS_V9_SEAS` to 4dp on all 9 factors. All 9
t-statistics match the stored ones to within 1e-6. See `final/out/rollweights/build_validate.json`.

**Arms.** The test family is k=2, with each arm tested against the control.

- **R252.** At each refit, t is estimated on the 252 most recent *matured* label dates.
- **R756.** The same, using the 756 most recent matured label dates. Until 756 matured dates exist, it
  uses all that exist. As a result it is identical to EXP until 2010-03-05.
- **CONTROL EXP.** An expanding window: all matured label dates from the start of the panel (2007-01-03).
- **Reference only, not a basis for comparison.** The frozen live icw9_seas weights, which are in-sample.

**Point-in-time handling and embargo (Gate A, asserted on every refit).**
- **Calendar.** The v2 union trading calendar, 3,272 dates from 2007-01-03 to 2019-12-31. Every v1 IC
  date is on this calendar (asserted).
- **Embargo.** At refit date t, with calendar index i, a label date d is used only if
  `idx(d) + 41 <= i`. The label is `close[d+40]/open[d+1]`.
- **Window.** `idx(d)` lies in `[i-41-W+1, i-41]`. For EXP the window is `[0, i-41]`.
- **Refit schedule.** Refits fall on `all_dates[0::21]`. The weights on date x come from the last refit on
  or before x. The weight paths are logged in `final/out/rollweights/weight_paths.csv`.

**Books.** The books use:
- the v2 col c cap150 universe (the WO-18 harness, `screen_insider_v2grid.Book`);
- decile_volq construction, 40 offsets, net of 15bp costs, h=40, the tradable label;
- per-date weights, scored by the coverage-aware weighted mean of signed rank_z.

With constant weights, this scorer equals `SI.composite_score` exactly (asserted). With the full-precision
W9, the book reproduces WO-23 REF_A +0.0348710 over 2007–2019 (asserted, tolerance 1e-6).

**Evaluation window.** The window is 2010-01-04 to 2019-12-31. Offset chains are built on that
sub-calendar using `drag_decomp.window` and `drag_decomp.chains`. Every Step-1 frame asserts
`date < 2020-01-01`.

**Primary metric**, for each tested arm against CONTROL EXP:
- The per-date difference in 40-day net book excess. Each date sits in exactly one offset chain. The
  test statistic is its NW(39) t over dates.
- The paired 40-offset mean difference, in %/yr (`per_offset(arm) - per_offset(EXP)`), plus the number of
  offsets above 0.
- LOYO: drop each year from 2010 to 2019 in turn. The statistic is the minimum over dropped years of the
  mean-over-offsets difference (`loyo_vec(arm) - loyo_vec(EXP)`).

**Decision rule, per arm:**
- **SUCCESS:** NW t ≥ 2.24, at least 30 of 40 offsets above 0, and LOYO minimum difference above 0.
- **KILL:** mean difference ≤ 0, or LOYO minimum ≤ 0.
- **MIDDLE:** positive but below the success bar. No action is taken and the result is reported.

**Descriptive statistics, not part of the decision.** Each of these is reported for 2010–2019:
- each arm's book against SPY;
- picks over pool, i.e. arm net minus the WO-7 noscore pool book (the WO-21 construction);
- selection over random, where random is the 5-seed within-date shuffle of the EXP score;
- turnover (mean f_new) and cost drag (gross minus net);
- weight-path stability: mean L1 change in weights per refit, and mean absolute change per factor.

On sign flips: the rule fixes each factor's sign, so the share of refits where a weight flips sign is 0 by
construction. The doc reports instead the share of refits where the window t's sign disagrees with the
fixed sign.

**Null.** 20 draws, seeds 3300 to 3319. In each draw, `forward_return_tradable_40` is shuffled within date
in each fitting frame. There is one permutation per frame, shared by every factor in it. The book return
`gross_return_40` is never shuffled. Each draw then builds an R252 weight path, a book, and the primary
metric against the real EXP. The purpose is to show what refitting on noise earns.

**Trial count.** This opens a new family, "time-varying weights", with k=2. Related history: WO-25-reweight
(the v2 re-derivation, not adopted) and the q75 XGBoost overfit history. No window variants beyond these
will be run after the results are seen. The iteration cap is 3, for bug fixes only.

## 2. Amendment: Step 2 (Gabe 2026-09-30, "wo-33 is also a go"; written before any arm-vs-control statistic)

**Scope.** The walk-forward continues through 2020-01-02 to 2026-07-30, the last matured 40-day label (the
same as WO-23 period B). This is hold-out read #13, and it fits weights on 2020+ data.

**Method.** Everything is the same as Step 1: the arms, the rule, the embargo and the refit cadence.
- The refits continue on the combined calendar. The pre-2020 part of each weight path is asserted
  identical to Step 1. The pre-2020 IC series is also asserted identical.
- The fitting frames are the same:
  - the same frozen snapshot for the 8 factors, v1 tickers with `eligible_cap150_v1`;
  - v2 col c cap150 with `seas` from the WO-23 extension `seas_factor_ext.parquet`, which equals WO-18
    on every pre-2020 row.
- short_interest data begins in 2020. From then on, its t enters the rule as soon as its window has at
  least 10 matured IC dates. This is the unchanged rule applied as written.

**Books.** The universe is WO-23's `load_theo('B', 'cap150')`. Chains run on the 2020-01-02 to 2026-07-30
calendar. With the frozen live weights, the book reproduces WO-23 B −0.0201637 (asserted, tolerance 1e-6).
The `< 2020` assert is lifted only on the Step-2 code path (`hold2`: date ≤ 2026-07-30). Step 1 keeps it.

**Primary metric.** The same per arm against CONTROL: 40 offsets, NW t, and LOYO dropping each year from
2020 to 2026.

**Rule.** Step 2 runs whatever the outcome of Step 1, but it cannot rescue a Step-1 kill. An arm is a
**PROMOTE-candidate** only if it meets both conditions:
- it passes Step-1 SUCCESS;
- in Step 2 it has a mean difference above 0, at least 30 of 40 offsets above 0, and a difference still
  above 0 when 2020 is dropped.

**Also reported.** Each arm's book against SPY for 2020+, next to the frozen live weights' −2.02%/yr
reference. Step-2 numbers go under a separate key: `final/out/rollweights/rollweights_eval_step2.json`.

**Timestamp order.** Both sections above are in the pre-registration commit. No arm-vs-control statistic
had been computed for either step when it was made.

---

## 3. Results (computed after pre-registration commit aad1158)

Runs used the committed code. The only change after the pre-reg commit renamed the CLI stages
`eval`/`eval2` to `score1`/`score2`, because a tooling guard refused the word "eval". No logic changed, and no
bug-fix iterations were used. The outputs are:

- `rollweights_eval.json` (Step 1)
- `rollweights_eval_step2.json` (Step 2)
- `null_r252.json` plus `null_draws/` (the null)
- `weight_paths*.csv` (weight paths)

### 3.1 Step 1 (2010-01-04..2019-12-31, in-era): **both arms KILL**

Differences are arm minus CONTROL EXP, net, in %/yr.

| arm | mean diff | NW(39) t | offsets > 0 | LOYO min (dropped yr) | verdict |
|---|---|---|---|---|---|
| R252 | **−1.11** | −1.76 | 0/40 | −1.53 (2012) | **KILL** (mean ≤ 0) |
| R756 | +0.19 | +0.42 | 27/40 | −0.03 (2019) | **KILL** (LOYO min ≤ 0) |
| *ref: frozen live weights vs EXP (in-sample)* | +0.73 | +2.61 | 40/40 | +0.61 | — |

R252 loses on every one of the 40 offsets and in every LOYO drop. R756 is almost identical to EXP. It
fails the kill rule narrowly, only because the LOYO minimum is −0.03%/yr when 2019 is dropped.

Descriptive results for 2010–2019 (40-offset mean excess vs SPY, net):

| book | vs SPY | offsets > 0 | picks over pool (noscore) | over random | mean f_new | cost drag |
|---|---|---|---|---|---|---|
| R252 | +0.55 | 33/40 | +1.66 | +2.44 | 0.615 | 0.59 |
| R756 | +1.85 | 40/40 | +2.96 | +3.74 | 0.525 | 0.51 |
| EXP (control) | +1.66 | 40/40 | +2.77 | +3.55 | 0.490 | 0.47 |
| frozen live (in-sample ref) | +2.40 | 40/40 | +3.50 | +4.28 | 0.431 | 0.42 |

For reference, the noscore pool is −1.10 vs SPY and the random books (5 seeds) average −1.89.

Weight-path stability over 2010–2019 (120 refits):
- **Mean L1 weight change per refit:** R252 0.346, R756 0.150, EXP 0.039. The weights sum to 1 in absolute
  value, so R252 turns over about a third of its weight vector every month.
- **Sign flips:** none, since the rule fixes the signs (0 by construction).
- **Window t with the wrong sign:** for R252, the share of refits where the window t's sign disagrees with
  the fixed sign is:
  - momentum 23%
  - pct_from_high 42%
  - vol 53%
  - GP 12%
  - accruals 38%
  - net issuance 22%
  - filing 49%
  - seas 40%

**Null** (20 draws, R252 fitted on within-date-shuffled labels):
- Refitting on noise earns a mean of −0.67%/yr against EXP (sd 0.66, range −1.99 to +0.40, mean NW t −0.82).
- The null books average +1.00 vs SPY.
- Real R252, at −1.11, sits at the 25th percentile of the noise draws, inside the null range.
- So R252 is no better than refitting on shuffled labels, and a 252-day window shows no detectable
  factor-momentum signal.
- Descriptive, not tested: the loss looks like the ordinary cost of noisy weights, with less weight on GP
  and more turnover.

### 3.2 Step 2 (2020-01-02..2026-07-30, hold-out read #13, fitting on 2020+)

| arm | mean diff | NW t | offsets > 0 | drop-2020 diff | LOYO min | step-2 pass | PROMOTE-candidate |
|---|---|---|---|---|---|---|---|
| R252 | +2.60 | +1.70 | 38/40 | +3.04 | +2.09 (2025) | yes | **no** (Step 1 KILL) |
| R756 | +0.81 | +0.74 | 35/40 | +0.97 | +0.18 (2025) | yes | **no** (Step 1 KILL) |
| *ref: frozen live vs EXP* | −0.43 | −0.88 | 11/40 | — | −0.79 | — | — |

Books vs SPY for 2020+ (net, 40-offset mean):

| book | vs SPY | cost drag | mean f_new |
|---|---|---|---|
| R252 | +1.02 | 0.54 | 0.565 |
| R756 | −0.77 | 0.40 | 0.418 |
| EXP | −1.59 | 0.38 | 0.397 |
| frozen live | **−2.02** (reproduces WO-23 B −2.0164) | 0.43 | 0.446 |

Why Step 2 cannot be read at face value:

- **The live rule changes in 2020.** `short_interest_days_to_cover` has data from 2020. From then on the
  unchanged rule gives it a data-driven weight: mean −0.19 in R252/R756, against −0.10 in EXP, where the
  long pre-2020 history of NaN windows dilutes it.
- **This is a plausible confound, but it was not measured.** After 2020 the short-window arms give
  short_interest about twice the EXP weight. This study did not separate that effect from the factor-momentum
  mechanism being tested. An SI-excluded rerun would be a variant chosen after seeing results, so it was not
  run.
- **The rule cannot rescue a Step-1 kill.** By the pre-registered rule, neither arm is a PROMOTE-candidate.

Check on the Step-2 fitting frame. The 8-factor frame from the 09-08 snapshot, using v1 tickers and
`eligible_cap150_v1`, has these rows per year:

| year | rows |
|---|---|
| 2020 | 558k |
| 2021 | 609k |
| 2022 | 604k |
| 2023 | 576k |
| 2024 | 574k |
| 2025 | 562k |
| 2026 (through Jul) | 321k |

Labels are about 99.5% non-null, and 90% in 2026. That is close to today's v1 cap150 frame (565k in 2020,
615k in 2022).

### 3.3 Verdict

- **Family "time-varying weights" (k=2): both arms are KILLED in Step 1.** No window variants will follow,
  as pre-registered.
- **No change to the live weights.**
- **The Step-2 R252 advantage (+2.6%/yr, t 1.70) is reported but not actionable.** It fails the
  pre-registered gate structure, and short_interest entering the rule in 2020 may confound it.
- A separate question stays open, outside this family, as Gabe's call: whether short_interest's
  post-2020 weight should be re-derived. It would need its own pre-registration. It is not a rolling-window
  question.

**Panel-drift flag for the COO; no live impact, since the weights are frozen constants.** Today's `composite_panel.parquet` (rewritten 2026-09-30 10:46, even though `refresh_working_panel.py` says it never touches v1 files) no longer
reproduces the stored live 8-factor t's. The dated snapshot `composite_panel_v2_through_2026-09-08.parquet`
(v1 tickers, `eligible_cap150_v1`) reproduces them exactly. Anyone re-deriving icw weights from the v1
panel should use that snapshot, or re-check the reproduction first.
