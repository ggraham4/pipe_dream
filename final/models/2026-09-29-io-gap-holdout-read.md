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
