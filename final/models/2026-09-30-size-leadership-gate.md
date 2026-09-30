# WO-32: size-leadership gate (hold SPY after large caps have led)

Date: 2026-09-30. Owner: Gabe ("Go", 2026-09-30). Commissioned by the COO.
Branch: `worktree-agent-aae4f860e1b828969`. Code: `final/src/sizegate/`.
Outputs: `final/out/sizegate/`.

## 1. Pre-registration (committed before any gated-vs-ungated number)

### Question

The live model (icw9_seas, cap150) beats its own pool by about +2.8%/yr.
The equal-weighted pool lagged SPY by −1.99%/yr after 2011 and by −4.85%/yr
in 2020-26 (WO-21, WO-24, WO-31). Gabe asks whether holding SPY instead of
the book, when large caps have led, would help. The prior evidence is WO-30
(2007-2019, descriptive). After trailing large-cap leadership the pool did
not lag more (−0.02 vs −0.35), and the book still beat SPY. 2020-26 has not
been tested. The market-timing prior is low, and there are few regime turns.

### Rule (fixed, zero parameters fitted)

On each rebalance date t:

- `S(t)` = trailing 252-trading-day **total return** of IWM minus the same
  for SPY. It uses only data dated ≤ t.
  - Source: yfinance `adj_close` from the WO-31 bench pull,
    `final/out/pool/bench/{SPY,IWM}.parquet`. It is read in place from the
    WO-31 worktree, and its sha256 is asserted against WO-31's
    `pull_meta.json`.
  - Formula: inner-join the dates, then
    `S = adj_iwm/adj_iwm.shift(252) − adj_spy/adj_spy.shift(252)`.
  - Each rebalance date needs an exact same-day `S`. Any as-of lag fails.
- If `S(t) < 0`, hold SPY for that 40-day window. Excess vs SPY is then 0,
  minus any switching cost.
- Otherwise, hold the icw9_seas decile_volq book.
- If `S(t)` is undefined (warm-up at the start of 2007), hold the book. The
  number of affected dates is reported.

**Definition note.** The spec says the definition is the same as WO-30's
small-vs-large regime (`regime_phase0.py`, R3). WO-30 used **price-only**
closes (SPY.csv and IWM.csv). This spec's formula and name-checks say
**total return**, so the explicit formula wins and S is built on total
return.
- To reuse WO-30, I also build a price-only S from the same parquet and check
  that it reproduces WO-30's `size` labels on era A. That check runs
  `regime_phase0.build_labels` read-only.
- I report how many days the price-only and total-return signs disagree in
  A and in B. That comparison is label-only.
- No gated performance is ever computed on the price-only basis.

### Costs

- The book's net return is the harness's, unchanged: 15 bp, turnover-aware
  via f_new, as `downcap_v2_readout.backtest` and `drag_decomp.chains`.
- A flat **0.0015** is subtracted on every chain date where the state
  (BOOK or SPY) differs from the previous chain date's state. Holding SPY
  costs nothing.
- The initial state of every chain is BOOK. If the first date is in SPY,
  that counts as a switch.
- Oracle, per offset (asserted to 1e-12):
  gated − ungated = [−Σ(book excess on SPY dates) − 0.0015 × switches] / n × 252/40.
  Gated and ungated chains cover identical (offset, date) sets.

### Harness

- Everything else is the WO-31 / WO-21 / WO-24 harness, imported read-only:
  `pool_read.picks_w`-equivalent `V.Book.picks`,
  `model_audit_wo23.load_theo`, `drag_decomp.chains`, `per_offset`,
  `loyo_vec`, `per_year` and `window`.
- Grid and pool: v2 grid column c, cap150.
- Construction: decile_volq, net 15 bp, 40 offsets, h = 40.
- Label: close[t+40]/open[t+1] from `outcome_cache_v2`. SPY price leg: the
  outcome_cache_v2 SPY row, as in WO-9 and WO-31.
- Era A is 2007-01-02..2019-12-31, full, plus pre and post around
  2011-10-01. Era B is 2020-01-02..2026-07-30, the last matured label.

### Reconcile first (hard assert)

Ungated icw9_seas cap150 book vs SPY, 40-offset mean, against the WO-31
`pool_hedge_read.json` exact values (1e-10) and the spec's rounded numbers
(≤ 0.01 pp):

| era | icw9_seas | icw8 |
|---|---|---|
| A full | +3.49 | +2.85 |
| A post-2011-10 | +0.51 | +0.01 |
| B | −2.02 | −1.99 |

### Hold-out

Era B is an unfitted read: nothing was fitted or chosen on 2020+, and the
rule is fixed above. This is **hold-out read #12**.

### Primary metric

Gated minus ungated book excess vs SPY, in %/yr. For each era (A full,
A post-2011-10, B) I report the 40-offset mean and the count of offsets
above 0.

**Drop-year checks.** These are leave-one-year-out on the per-offset
difference (`pool_read.diff_stats` style), averaged over offsets:
- A full with 2008 dropped
- B with 2020 dropped

### Decision

- **Success:** gated − ungated > 0 in both A full and B, and still > 0 with
  2008 dropped from A full and with 2020 dropped from B.
- **Kill:** ≤ 0 in either A full or B.
- **Middle:** positive in both, but one of the drop-year checks fails. I
  report it and take no action.

The success rule uses the 40-offset mean. The offset count is reported only.

### Also reported (descriptive)

- The share of rebalance dates in SPY per era, on the panel calendar and as
  a mean over the chains.
- The number of switches per chain, as a mean over offsets.
- The number of distinct large-lead episodes: runs of 40 or more trading
  days on the daily panel calendar.
- Per-year gated vs ungated in B.
- The same gate on icw8, as a robustness row.

### Gate A

- **PIT.** S(t) must be append-invariant: truncating the parquet at t and
  recomputing gives the same S(t), to 1e-12, on sample dates in both eras.
  `adj_close` is back-adjusted by one cumulative factor, so later dividends
  cancel in the ratio.
- **Name-checks, total return on `adj_close`, calendar year**
  (`hedged_composite.cal_year` convention):
  - IWM 2008 −34.14% and 2017 +14.58% (WO-9), within 0.1 pp.
  - SPY 2008 about −36.8% and 2017 about +21.7% (public total returns),
    within 2 pp.

### Trial count

This is trial 1 of the size/market-timing family. WO-30 was descriptive and
not a trial. No threshold or lookback variants will be run after the results
are seen.

### Process

Iteration cap: 2, for bug fixes only.
