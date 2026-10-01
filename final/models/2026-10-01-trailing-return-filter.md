# WO-40: trailing-40-day return filter on the model's picks

2026-10-01. COO work order WO-40. It was issued as "WO-36" and renumbered by
the COO before the pre-registration commit, because another session already
used WO-36 (cw_spread weights). The spec is unchanged.
Code: `final/src/trailfilter/trailfilter.py`. Outputs: `final/out/trailfilter/`.

## 1. Pre-registration (committed before any filtered-vs-unfiltered number)

**Hypothesis (Gabe's own heuristic, 2026-10-01).** When evaluating the model's
picks, Gabe excludes names whose return over the trailing 40 trading days is
negative, or below a threshold. Mechanism: short-horizon trend, avoiding
falling knives. Counter-evidence already in this project: 1-month return as a
factor was null (momentum_1_1 t -0.39), and among low-turnover names recent
losers did better over the next 40 days (WO-28b, IC t -2.33, reversal).
Prior: neutral to slightly negative.

**Filter (fixed, k=2 arms, no other thresholds or windows).**
r40(t) = closeadj[t] / closeadj[t-40] - 1 on Sharadar SEP `closeadj` (split-
and dividend-adjusted), data <= t only. "t-40" is 40 bars back on the name's
own SEP bars.

- **F0**: exclude names with r40 < 0.
- **F10**: exclude names with r40 < -10%.
- A name with fewer than 40 prior bars, or no SEP bar on t, has r40 undefined
  and is kept.

**Primary construction (filter BEFORE selection).** The filter is applied to
the eligible cap150 set before `decile_volq`: excluded names get a NaN score,
so `composite.pick_decile_volq` drops them from both the volatility-quintile
cut and the selection, and next-ranked names fill in. The book stays a full
decile of the surviving set.

**Descriptive variant (filter AFTER selection).** Take the unfiltered picks,
drop the excluded ones, and renormalise the remaining inverse-vol weights
(proportional reallocation, fewer names).

**Empty book rule (both variants).** If on a rebalance date the filtered book
has no picks (fewer than 20 surviving names, or every pick excluded), the book
is cash for that 40-day window: gross return 0, no holdings, so excess = -SPY.
Re-entry is charged as full turnover. The number of such dates is reported.

**Model and harness.** icw9_seas frozen live weights
(`ICW.PRODUCTION_WEIGHTS_V9_SEAS`); icw8 as a robustness row. v2 grid column
c, cap150, decile_volq, net 15 bp, 40 offsets, h=40, tradable label
close[t+40]/open[t+1] (`outcome_cache_v2`), benchmark SPY from the same cache.
WO-31/WO-32 harness imported read-only (`model_audit_wo23.load_theo`,
`screen_insider_v2grid.Book`, `pool_read.picks_w`, `drag_decomp`).

**Reconcile first (hard assert, <= 0.01 pp).** Unfiltered icw9_seas book vs
SPY: era A 2007-2019 +3.49 %/yr, A post-2011-10 +0.51, era B 2020-01..last
matured label -2.02. Also exact (1e-10) against the committed WO-31
`pool_hedge_read.json`.

**Gate A.**
- PIT on r40: truncating the input at t and recomputing gives the same r40(t);
  rescaling every bar after t (a fake future dividend adjustment) and every bar
  up to t+k by a constant cannot move r40(t).
- Split check: AAPL r40 on 2014-06-09 (7:1 split) is not a spurious -86%.
- At least one delisted name is present with a finite r40.

**Hold-out.** Era B is an unfitted read: the rule is fixed here and nothing is
chosen on 2020+. Logged as **hold-out read #18** (the work order first said #15; the COO
renumbered it because #15 was already taken).

**Primary metric.** Filtered minus unfiltered book (net, %/yr), 40-offset
mean, and the number of offsets with a positive difference, per era window
(A full, A post-2011-10, B), per arm. Model icw9_seas.

**Decision rule (per arm, scored independently).**
- **Success**: > 0 in BOTH A-full and B, with >= 30/40 offsets positive in
  each, AND > 0 in A with 2008 dropped AND > 0 in B with 2020 dropped.
- **Kill**: <= 0 in either A-full or B.
- **Middle**: positive in both but fails an offsets or drop-year check.
  Report, no action.

**Also reported (descriptive, no decision).**
- Share of eligible names and of would-be picks excluded, per era.
- Turnover (mean f_new) and cost drag, filtered vs unfiltered.
- Per-year filtered minus unfiltered in B.
- Mean forward 40-day return (`gross_return_40`) of excluded vs kept would-be
  picks, equal-weighted per date then averaged over dates, per era.
- Max drawdown (per-offset compounded net chain; 40-offset mean and worst)
  and worst single 40-day window (minimum per-rebalance net return over all
  offsets), filtered vs unfiltered.
- Picks-over-pool decomposition: pool = WO-7 no-score construction
  (`drag_decomp.noscore_picks`) on the same (filtered or unfiltered) set;
  filtered minus unfiltered = change in pool + change in selection.
- The after-selection variant, same metric.

**Trial count.** New family "short-term trend filter", k=2 arms scored
independently. Related history: momentum_1_1 and str_lowturn in the closed
reversal family. No threshold or window variants after results.

**Process.** Iteration cap 2 (bug fixes only). No live change, no app change.

## 2. Results (run after the pre-registration commit 2fd0f6a)

**Verdict: KILL for both arms.** The filter costs 2.4 to 3.4 %/yr in 2020-26
with 0 of 40 offsets positive, and is roughly zero in 2007-2019. No action;
no variants were run. Source: `final/out/trailfilter/trailfilter.json`.

### Reconcile and Gate A (passed)

| unfiltered icw9_seas vs SPY | got | spec | vs WO-31 json |
|---|---|---|---|
| A 2007-2019 | +3.487 %/yr | +3.49 | exact |
| A post-2011-10 | +0.509 | +0.51 | exact |
| B 2020-01..last matured label | -2.016 | -2.02 | exact |

icw8 also reconciles (+2.854 / +0.012 / -1.992). Gate A: PIT max difference
2e-16 on 300 sampled rows per era (truncate and rescale tests); AAPL
2014-06-09 r40 = +26.0% on `closeadj` (unadjusted close would give -82.1%);
3,973 delisted tickers carry a finite r40 in era A and 1,431 in era B. r40 is
undefined, so kept, on 0.5% (A) and 0.6% (B) of eligible rows.

### Primary: filtered minus unfiltered, icw9_seas, net, %/yr

| arm | window | unfiltered | filtered | diff | offsets > 0 | drop-year diff |
|---|---|---|---|---|---|---|
| F0 | A full | +3.49 | +3.69 | +0.21 | 26/40 | -0.19 (2008 dropped) |
| F0 | A post-2011 | +0.51 | +0.59 | +0.08 | 26/40 | |
| F0 | B | -2.02 | -5.46 | **-3.45** | 0/40 | -2.72 (2020 dropped) |
| F10 | A full | +3.49 | +3.33 | -0.16 | 22/40 | -0.31 (2008 dropped) |
| F10 | A post-2011 | +0.51 | +0.42 | -0.09 | 16/40 | |
| F10 | B | -2.02 | -4.46 | **-2.44** | 0/40 | -0.72 (2020 dropped) |

- **F0: KILL** (B <= 0). The small era-A gain also fails the offsets check
  (26 < 30) and turns negative with 2008 dropped.
- **F10: KILL** (A-full and B both <= 0).
- icw8 robustness row: all four cells negative (F0 A -0.15, B -2.42; F10 A
  -0.45, B -2.34).

Per-year diff in B (F0 / F10): 2020 -7.7 / -12.3, 2021 +0.1 / +0.8, 2022
-11.7 / -3.5, 2023 -3.6 / -1.2, 2024 -0.3 / +0.4, 2025 -0.6 / -0.9, 2026
+0.5 / +0.3. The loss is concentrated in 2020 and 2022, the rebound years
after sell-offs, which is the reversal pattern the prior pointed to.

### Descriptive

**Share excluded (mean over dates).**

| arm | era | eligible names | would-be picks (count) | would-be picks (weight) |
|---|---|---|---|---|
| F0 | A | 43.7% | 40.7% | 38.7% |
| F0 | B | 46.0% | 43.9% | 41.3% |
| F10 | A | 18.2% | 16.7% | 13.2% |
| F10 | B | 22.8% | 21.2% | 15.9% |

On the worst date F0 excludes 98% of eligible names, but no date ever left
an empty book (0 cash dates in every arm, model and variant).

**Forward 40-day return of excluded vs kept would-be picks** (equal weight
per date, mean over dates):

| arm | era | excluded | kept | excluded - kept |
|---|---|---|---|---|
| F0 | A | +1.70% | +1.95% | -0.25 pp |
| F0 | A post-2011 | +1.72% | +2.16% | -0.44 pp |
| F0 | B | +2.03% | +1.76% | +0.27 pp |
| F10 | A | +1.17% | +1.86% | -0.70 pp |
| F10 | A post-2011 | +0.99% | +2.12% | -1.13 pp |
| F10 | B | +1.97% | +1.85% | +0.12 pp |

In era A the excluded picks did do worse on a simple average, which is the
effect Gabe is seeing. It does not turn into book return: the excluded picks
beat the kept ones on 44-46% of dates in A and 48-49% in B, the gap is
lopsided in time, and the filtered book pays more in costs.

**Turnover and cost.** F0 raises mean new-name share per rebalance from 0.43
to 0.67 (A) and 0.45 to 0.70 (B); cost drag goes from 0.42 to 0.64 %/yr (A)
and 0.43 to 0.67 (B). F10: 0.43 to 0.52 (A), 0.45 to 0.57 (B); cost 0.42 to
0.50 and 0.43 to 0.54 %/yr.

**Drawdown (net, 40-offset mean / worst offset) and worst 40-day window.**

| arm | window | max DD unfiltered | max DD filtered | worst window unf. | filtered |
|---|---|---|---|---|---|
| F0 | A full | -45.9% / -51.4% | -39.5% / -51.6% | -38.6% | -34.9% |
| F0 | A post-2011 | -15.0% / -19.3% | -13.1% / -16.3% | -11.7% | -12.8% |
| F0 | B | -28.1% / -33.9% | -33.2% / -45.1% | -33.9% | -33.6% |
| F10 | A full | -45.9% / -51.4% | -42.0% / -50.7% | -38.6% | -36.9% |
| F10 | B | -28.1% / -33.9% | -28.8% / -33.8% | -33.9% | -33.6% |

The filter trimmed the average drawdown in era A (2008) but made it deeper
in era B for F0. It is not a reliable risk reducer.

**Picks-over-pool decomposition** (filtered minus unfiltered = pool change +
selection change, %/yr):

| arm | window | total | pool change | selection change |
|---|---|---|---|---|
| F0 | A full | +0.21 | -0.83 | +1.04 |
| F0 | A post-2011 | +0.08 | -0.55 | +0.63 |
| F0 | B | -3.45 | -1.96 | -1.48 |
| F10 | A full | -0.16 | -0.54 | +0.38 |
| F10 | B | -2.44 | -1.93 | -0.51 |

The filter makes the pool itself worse in every window (the no-score book on
recent winners only underperforms the no-score book on everyone). In era A
the model's selection inside the filtered pool was better, which offset it;
in era B selection got worse too.

**After-selection variant** (drop flagged picks, hold fewer names): F0 A
+0.35, A post +0.08, B -3.21; F10 A -0.11, A post -0.11, B -2.48. Same
picture.

### Caveats

- **Book size.** The work order says the book "stays full-size". As
  pre-registered here, the filtered book is a full decile of the surviving
  names, so it holds fewer names than the unfiltered book (F0: 166 vs 295 in
  A, 169 vs 313 in B). A variant that takes a larger fraction of survivors to
  keep the name count equal was not run (no variants after results). The
  pool change alone (-1.9 %/yr in B) makes a different verdict unlikely.
- Era B was read once, unfitted, as hold-out read #18.
- Trial count: family "short-term trend filter", k=2, both arms killed.
