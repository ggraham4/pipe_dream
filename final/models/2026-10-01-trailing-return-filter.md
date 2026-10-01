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

## 2. Results

Not run yet at the time of the pre-registration commit.
