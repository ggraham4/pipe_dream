# WO-26-io: unfitted 2020+ hold-out read of the frozen `io_gap` factor

Date: 2026-09-29. Commissioned by the COO (WO-26-io in COO.md) under Gabe's
standing 2026-09-27 rule: unfitted reads of 2020-2026 are OK if each one is
logged. **This is hold-out read #9.** The ledger row first said #8; the COO
renumbered it because #7/#8 were already assigned to WO-25. A first worker
died on the API spend limit before it read anything, so no 2020+ io_gap
number had been seen before this doc was committed.

Branch `worktree-agent-a648114375fb9da59`, based on `origin/integration`
2338c91 (the io_gap screen landing, b6b6b64). Code:
`final/src/overnight/holdout_io_gap.py`. Outputs:
`final/out/overnight/io_gap_holdout_report.json` (+ `.log`); the extended
factor `final/out/overnight/io_gap_factor_ext.parquet` is gitignored.

Status: **PRE-REGISTERED.** This section was committed and pushed before any
2020+ io_gap value was computed. Results are appended below the line at the
end.

## Question

Does the frozen `io_gap` factor (definition in
`final/models/2026-09-29-overnight-intraday-screen.md`, registered at
b451e52, sign +1) keep its sign out of era, and does it add to the LIVE
Theoretical model (icw9_seas)?

Family "overnight/intraday decomposition", **trial 1** (this is a read of the
same trial, not a new one). No sign flip, no variant, no new lookback, no
refit. Nothing is fitted on 2020+ data.

## Data

- v2 composite panel, column c (survivorship-safe v2 grid, SPAC filter as
  `downcap_v2_readout.load_column("c")`), `eligible_cap150`, h = 40, label
  `forward_return_tradable_40` (open[t+1] → close[t+40]).
- Rebalance dates 2020-01-02 .. the last date whose
  `forward_return_tradable_40` has matured. A check before this doc found
  that date is **2026-07-30** (cap150 label coverage 99.3% on 2026-07-30,
  0% from 2026-07-31). This equals WO-23's period-B end.
- Loader: `final/src/audit/model_audit_wo23.load_theo(period)` (WO-23, on
  integration), imported, not edited. Its `SEAS_EXT` is pointed at the
  gitignored WO-23 file
  `/Users/ggraham/pipe_dream/.claude/worktrees/wo23-model-audit/final/out/audit/seas_factor_ext.parquet`.
  Period A = 2007-01-02..2019-12-31, period B = 2020-01-02..2026-07-30.
- PIT and survivorship exactly as in era. Runs locally, no network.

## Extending the factor (identity check first, hard asserts)

The frozen builder `final/src/overnight/build_io_gap.py` is **not edited**
and its `main()` is **never called** (it would overwrite the frozen outputs).
The wrapper imports its functions (`sep_files`, `load_sep`,
`daily_components`, `market_calendar`, `io_gap_for`) and changes only the
module bounds (`LAST_YM`, `HOLDOUT`) at run time.

- **SEP window.** The extended build loads SEP month files **2005-01 through
  2026-07**. This is a superset of "2019-01 onward". The full span is used
  because the first 2020 window reaches back to about 2018-12-31 for
  `closeadj_prev`, and because it keeps the market calendar and per-ticker
  cumulative sums prefix-identical to the frozen build. Panel query rows run
  2007-01-02..2026-07-30. The `q_on.all()` assert (every panel date is on the
  market calendar) is kept.
- **Stage `identity`** (prints no label-joined number):
  1. The v2 panel sha256 and the SEP digest of 2005-01..2019-12 equal
     `build_io_gap_meta.json` (`30f636fd…`, `83e7b890…`).
  2. The wrapper with the **frozen** bounds (2005-01..2019-12, rows ≤
     2019-12-31) reproduces the frozen
     `/Users/ggraham/pipe_dream/.claude/worktrees/overnight-intraday/final/out/overnight/io_gap_factor_v2.parquet`
     on every (ticker, date) row: `io_gap`, `io_intraday`, `io_overnight`
     each to ≤ 1e-12 (NaN pattern identical), and `io_nvalid` exactly.
  3. The **extended** build (2005-01..2026-07) gives the same values on every
     row ≤ 2019-12-31, to the same tolerance. Only then are rows ≥
     2020-01-01 kept. The PIT assert (last price used ≤ t) holds on every
     finite row.
- **Stage `read`**, before any io_gap outcome number:
  1. io_gap is merged into the `load_theo` output of each period; the row
     count and order must not change.
  2. `add_ranks(FT + ["io_gap"])` on that same U.
  3. **Reconcile** icw8 (`PRODUCTION_WEIGHTS`) and icw9_seas
     (`PRODUCTION_WEIGHTS_V9_SEAS`, 4 dp) 40-offset mean excess vs SPY to
     WO-23: period B to `final/out/audit/model_audit_wo23_B.json`
     (`theoretical.icw8`, `theoretical.icw9_seas`), and period A to
     `model_audit_wo23_A.json`, each to 1e-6.
  4. The recomputed in-era io_gap pooled NW t must reproduce the screen
     report's +3.995 (`io_gap_screen_report.json` `ic.pooled.t`) to 1e-6.

## Frozen weights (from 2007-2019 t's only, fixed before the read)

Rule `SI.fit_weights` (w_k = s_k·max(0.1, |t_k| − 1) / Σ) on the ICW
report's full-era t's for the 8 factors, `ICW.SEAS_T` = 2.8356 for seas, and
the screen's io_gap t = +3.995. Rounded to 4 dp. The script asserts it
reproduces these dicts exactly:

| factor | icw10 | icw9_io |
|---|---|---|
| momentum_12_1 | 0.0305 | 0.0358 |
| pct_from_high_252 | 0.0080 | 0.0094 |
| volatility_60 | −0.0080 | −0.0094 |
| gross_profitability | 0.3657 | 0.4286 |
| accruals | −0.0999 | −0.1171 |
| net_issuance_pct | −0.0859 | −0.1006 |
| days_to_next_filing_seasonal | −0.0080 | −0.0094 |
| short_interest_days_to_cover | −0.0080 | −0.0094 |
| seas | 0.1467 | — |
| io_gap | 0.2393 | 0.2804 |

Comparators are the live frozen constants: icw9_seas
(`PRODUCTION_WEIGHTS_V9_SEAS`) for icw10, and icw8 (`PRODUCTION_WEIGHTS`)
for icw9_io.

## PRIMARY (one read)

io_gap pooled NW(39) Spearman rank IC against `forward_return_tradable_40`,
column c cap150, dates 2020-01-02..2026-07-30 (the `ic_gates` code of the
in-era screen, `screen_insider_v2grid.ic_gates`).

- **SUCCESS:** IC > 0 and NW t ≥ +1.0.
- **MIDDLE:** 0 < t < +1.0.
- **KILL:** NW t ≤ 0.

## SECONDARY (descriptive; cannot rescue a KILL)

Every row reports the 2007-2019 number next to the 2020+ number. Period-A
book numbers are **in-sample** (the weights were fit on those t's). They use
frozen full-era weights, so they are not the screen's split-half OOS +0.145pp
and are not reconciled to it.

1. **Books.** decile_volq, net 15 bp, 40 offsets (`screen_insider_v2grid.Book`
   + `downcap_v2_readout.backtest`): icw10 vs icw9_seas, and icw9_io vs icw8.
   For each: 40-offset mean excess vs SPY, sd40, and the paired per-offset
   difference (mean, sd40, count of offsets > 0 out of 40).
2. **LOYO by year** for each paired difference: for each year y, the mean
   over the 40 offsets of the paired difference with year y dropped. Also
   the per-year paired difference.
3. **Per-year io_gap IC**, 2007..2019 and 2020..2026 (mean daily IC by
   calendar year, with n dates).
4. **io_gap IC after momentum residualization:** per date, OLS with
   intercept of rank-z(io_gap) on rank-z(momentum_12_1), on rows where both
   are finite; the residual's Spearman NW(39) IC against the label. Both
   periods.
5. **Leg ICs:** `io_intraday` and `io_overnight` pooled NW IC, both periods
   (descriptive; no sign is registered for either leg).
6. **Both-sides sector-demeaned** io_gap IC t (`ic_gates`
   `sector_both_sides`), both periods.
7. Also reported from `ic_gates`: odd/even-year halves, 40-offset sign flips,
   and the per-year share, both periods. io_gap coverage by year.

## Iteration cap and logging

Iteration cap 3, bug fixes only. A crash in stage `identity` prints no
outcome number and is not an iteration. Any iteration is listed in the
Results. This read is logged here and in the HANDOFF as **hold-out read #9**.
The COO records it in COO.md.

---

## Results (appended after the read; hold-out read #9)

The pre-registration above was committed as **e634896** and pushed to
`origin/worktree-agent-a648114375fb9da59` before any 2020+ io_gap value was
computed. Iterations used: **0 of 3**. Both stages ran once, with no fixes.
Runs: `holdout_io_gap.py --stage identity` (log
`final/out/overnight/io_gap_holdout_identity.log`), then `--stage read` (log
`io_gap_holdout_report.log`). All numbers come from
`final/out/overnight/io_gap_holdout_report.json`.

### Checks (all hard asserts passed)

- Panel v2 sha256 `30f636fd…` and SEP 2005-01..2019-12 digest `83e7b890…`
  match `build_io_gap_meta.json`.
- **Identity.** Wrapper with the frozen bounds vs the frozen
  `io_gap_factor_v2.parquet`: 13,253,466 rows, 12,424,924 finite, max abs
  diff **0.0** on io_gap, io_intraday and io_overnight, NaN pattern
  identical, io_nvalid exact. The extended build (SEP 2005-01..2026-07) gives
  the same result on every row ≤ 2019-12-31 (max abs diff 0.0). PIT assert
  holds on every finite row. Extended factor: 20,263,674 rows.
- **Weight rule.** `SI.fit_weights` on the in-era t's reproduces the icw10
  and icw9_io dicts exactly to 4 dp.
- **WO-23 reconcile** (40-offset mean excess vs SPY, exact to float
  precision):
  - A: icw8 +0.0285416, icw9_seas +0.0348652
  - B: icw8 −0.0199180, icw9_seas −0.0201637
- **In-era IC reconcile.** io_gap pooled NW t +3.995309, the same as the
  screen.

### PRIMARY: **SUCCESS**

io_gap pooled NW(39) rank IC vs `forward_return_tradable_40`, column c
cap150, from 2020-01-02 to the last matured date, **2026-07-30**
(**1,652 dates**): **IC +0.0397, NW t +2.62**. The bar was IC > 0 and
t ≥ +1.0. The sign held out of era, and the 2020+ IC is larger than the
in-era IC (+0.0322, t +4.00).

### SECONDARY (descriptive; 2007-2019 next to 2020+)

Book rows for 2007-2019 are **in-sample**: the frozen full-era weights were
fit on those years' t's. They are not the screen's split-half OOS +0.145pp.
Units: excess return vs SPY, %/yr, net 15 bp, decile_volq, mean of 40
offsets.

| metric | 2007-2019 | 2020-01..2026-07 |
|---|---|---|
| io_gap IC (NW t) | +0.0322 (+4.00) | **+0.0397 (+2.62)** |
| odd / even-year IC (t) | +0.0282 (+2.33) / +0.0370 (+3.75) | +0.0605 (+2.73) / +0.0223 (+1.23) |
| both-sides sector-demeaned IC (t) | +0.0276 (+3.57) | +0.0315 (+2.14) |
| IC after residualizing on momentum_12_1 (t) | +0.0298 (+5.00) | +0.0308 (+2.39) |
| median daily Spearman with momentum_12_1 | +0.30 | +0.30 |
| leg io_intraday IC (t) | +0.0287 (+2.64) | +0.0440 (+2.42) |
| leg io_overnight IC (t) | −0.0247 (−4.56) | −0.0169 (−1.36) |
| 40-offset sign flips of daily IC | 0/40 | 0/40 |
| max single-year share of summed IC | 0.167 (2015) | 0.389 (2021) |
| LOYO IC t, minimum | +3.50 | +1.97 |
| icw10 | +3.774 | −1.853 |
| icw9_seas (live) | +3.487 | −2.016 |
| **icw10 − icw9_seas, paired 40-offset mean (sd40)** | +0.288 (0.249) | **+0.164 (0.320)** |
| icw10 − icw9_seas, offsets > 0 | 34/40 | **27/40** |
| icw10 − icw9_seas, LOYO minimum (year dropped) | +0.013 (2007) | −0.165 (2026) |
| icw9_io | +3.204 | −1.938 |
| icw8 | +2.854 | −1.992 |
| icw9_io − icw8, paired mean (sd40) | +0.350 (0.297) | +0.054 (0.593) |
| icw9_io − icw8, offsets > 0 | 36/40 | 18/40 |
| icw9_io − icw8, LOYO minimum (year dropped) | +0.041 (2007) | −0.588 (2025) |

**Per-year io_gap IC** (mean daily IC):

| year | IC | year | IC |
|---|---|---|---|
| 2007 | +0.020 | 2017 | +0.020 |
| 2008 | +0.060 | 2018 | +0.056 |
| 2009 | −0.067 | 2019 | +0.061 |
| 2010 | +0.023 | **2020** | **−0.065** |
| 2011 | +0.062 | **2021** | **+0.101** |
| 2012 | +0.051 | **2022** | **+0.052** |
| 2013 | +0.031 | **2023** | **+0.066** |
| 2014 | +0.030 | **2024** | **+0.066** |
| 2015 | +0.070 | **2025** | **+0.014** |
| 2016 | +0.002 | **2026** (144 dates) | **+0.046** |

**Book deltas, 2020+** (%/yr; paired, mean over offsets):

| year | icw10 − icw9_seas, that year | LOYO (year dropped) | icw9_io − icw8, that year | LOYO (year dropped) |
|---|---|---|---|---|
| 2020 | −3.96 | +0.91 | −5.72 | +1.10 |
| 2021 | +0.84 | +0.04 | −0.80 | +0.19 |
| 2022 | +1.35 | −0.06 | +0.76 | −0.07 |
| 2023 | +1.43 | −0.07 | −0.11 | +0.08 |
| 2024 | −2.24 | +0.59 | +1.34 | −0.18 |
| 2025 | +1.52 | −0.09 | +3.58 | −0.59 |
| 2026 | +3.43 | −0.16 | +1.99 | −0.14 |

Per-year deltas rest on about 6 rebalances per offset each, so they are
noisy. io_gap coverage in cap150, 2020+: 92-99% by year (in era 94-99%).

### Reading (descriptive; the verdict is the primary bar above)

1. **The factor replicated out of era.** IC t was +2.62 on 1,652 dates, with
   0/40 offset flips, a sector-demeaned t of +2.14, and a t of +2.39 after
   momentum residualization, so it is not momentum in disguise. Its one bad
   year, 2020 (−0.065), resembles 2009 (−0.067): both were momentum-crash or
   rebound years. 2021 carries 39% of the summed IC, which is under the
   in-era 0.45 cap, and the IC t stays +1.97 with any single year dropped.
2. **Its increment to the live book is small and not robust.** icw10 beat
   icw9_seas by +0.16pp/yr, on 27/40 offsets, with an sd40 of 0.32pp. The
   delta goes slightly negative when any one of 2022, 2023, 2025 or 2026 is
   dropped, and it is +0.91pp without 2020. Both books still lose to SPY in
   2020-26 (icw10 −1.85, icw9_seas −2.02). That loss is WO-24's universe
   drag, which io_gap does not fix. On icw8, icw9_io adds +0.05pp on 18/40
   offsets, which is noise. The book result matches the in-era calibration:
   the IC holds up, but a weight of about 0.24 buys a gain of a few tenths of
   a percent per year.
3. **The legs flipped roles.** In era the overnight leg carried more of the
   signal (−4.56 vs +2.64). In 2020+ the intraday leg does (+2.42 vs
   −1.36). That weakens the post hoc case for an overnight-only trial 2 (see
   COO.md), and it fits the registered io_gap mechanism, which is
   institutions buying intraday, better than it fits pure sentiment
   reversal.
4. Under the COO's pre-fixed D-IO rule, a primary SUCCESS means the COO
   recommends a **forward side-ledger column only** (`icw10_io`), with no
   live-weight change. That decision belongs to the COO and Gabe, not to
   this read.
