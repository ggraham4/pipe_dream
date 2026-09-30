# WO-30 Phase 0: does selection depend on market regime? (2026-09-30)

COO work order WO-30, Phase 0. Descriptive, no trial counted, in-era only
(2007-2019). No HMM is fit. Gabe reopened the regime-gate idea on
2026-09-30; the old 2-state SPY HMM was retired under a different model
and data, and the old regime reports (`final/out/reset2026/regime_backtest_report.json`,
`regime_diagnostic_report.json`, commit 16ef8e9) ran on the superseded v1
survivorship-selected panel. They are used here only for their regime
definitions.

Code: `final/src/regime/regime_phase0.py`. Output:
`final/out/regime/regime_phase0.json` (pre-reg-stage output:
`regime_phase0_prereg.json`).

## 1. Pre-registration (written and committed before Step 3 was computed)

### 1.1 Question and quantities

Question: does the live model's stock **selection** depend on market
regime, or does only the **pool's** return vary?

Harness: v2 grid column c, cap150, h = 40, decile_volq, 40 offsets, net
15 bp, label close[t+40]/open[t+1]. Every loaded frame asserts
max(date) < 2020-01-01. Books:

- **book**: icw8 (`ICW.PRODUCTION_WEIGHTS`) and icw9_seas
  (`ICW.PRODUCTION_WEIGHTS_V9_SEAS`, frozen 4dp, the live Theoretical
  weights). Both are reported, and both feed the decision map.
- **pool**: the WO-7 no-score cap150 book (`drag_decomp.noscore_picks`),
  the same pool WO-21 used.
- **selection over pool** (primary) = book net − pool net, per
  (offset, date) window. The identity book vs SPY = pool vs SPY + selection
  then holds exactly in every state.
- **selection vs random** (secondary, reported only) = book net − mean of 5
  within-date shuffles of the same score (seeds 2000-2004, as WO-21). The work
  order cites WO-21's "+2.78, 40/40". That number is this secondary quantity
  (score − random, post-2011), not score − pool; WO-21's post-2011
  score − pool was +2.00. The decision map uses the primary only. The JSON
  records whether the secondary would change the outcome.

Windows are the full-calendar offset chains (turnover and costs are not
reset at state changes). Each (offset, date) window is tagged with the
regime state on its rebalance date t. Per state: the in-state mean of each
offset's windows × 252/40, then the mean over offsets that have windows.
**Offsets positive / negative are counted out of 40** (an offset with no
window in a state counts as neither). Same-state windows overlap across
offsets, so 40/40 is a robustness count, not 40 independent tests.

LOYO min: drop each calendar year the state occurs in, recompute the state's
selection, take the minimum. A state that lives in a single year has
LOYO = NaN, which counts as failing. "Drop 2008": the state's selection with
all 2008 windows removed.

### 1.2 Step 1 reconcile (hard assert)

icw8 full-period net excess = +0.0285416 (WO-21 `drag_decomp.json`, tol 1e-6;
also 1e-9 to the exact value). icw9_seas frozen 4dp = +0.03486520 (WO-20
`wo20_frozen_backtest.json`, 1e-9). Pool = −0.00248503 (WO-21 noscore,
1e-9). The chain means must equal `DR.backtest` to 1e-12, and the book and
pool must have identical (offset, date) window sets.

**Result (pre-reg run): all four checks pass.** icw8 +0.0285416,
icw9_seas +0.0348652, pool −0.002485035.

The seas factor parquet is read-only from the WO-18 worktree
(`.claude/worktrees/agent-ad57ef9f38454d99d/final/out/seasonality/seas_factor_v2.parquet`,
sha256 8054af21…0e45, identical to the a790 copy). The icw9_seas reconcile
guards it.

### 1.3 Regime definitions (all point-in-time: the label on t uses prices dated ≤ t)

Prices: `final/scripts/td_data_local/SPY.csv` (close, filtered to
< 2020-01-01 at read time, starts 2006-01-03) and `final/data/benchmarks/IWM.csv`
(close, starts 2006-06-01, via `hedged_composite.load_iwm`). Both are
price-only closes. Labels map to panel dates as-of ≤ t (max lag observed:
0 days). Warm-up days are labelled `undefined` and excluded, never
defaulted. The old code defaulted undefined vol to "low".

1. **trend_pit**: the PIT version of the old Regime A. The old
   `regime_backtest.py` classified each window by **SPY's own calendar-year
   return** for the year of t (up > +10 %, down < −10 %, flat otherwise).
   **That uses future information:** a January window is labelled by
   December's close. Here the same thresholds are applied to the **trailing
   252-trading-day SPY return** at t. It is defined from 2007-01-04.
2. **vol**: the old Regime B, unchanged, because it is already causal. The
   60-day realized SPY vol (daily close-to-close std × √252,
   min_periods 30) is compared with its expanding median (min 252 obs,
   from 2006-01-03). high = above the median, low otherwise. It is defined
   from 2007-02-15.
3. **size** (new): the sign of the trailing 252-trading-day IWM return minus
   the SPY return (on common dates). small_lead if > 0, large_lead
   otherwise. It is defined from 2007-06-04.
4. **calyear_ref_nonpit**: the old calendar-year Regime A, reported for
   reference only. It is **not PIT and not used in the decision**.

### 1.4 Episodes

An episode is a contiguous run of one state on the daily panel calendar.
Raw run counts are reported, but a median split or threshold flickers, so
raw counts overstate independent episodes. **For the decision, an episode
is a run of ≥ 40 trading days (one holding horizon).** This is stricter
than the work order's literal "contiguous runs", so it is pre-registered
here. The JSON records whether the raw-count reading would flip the outcome.

Pre-reg run counts (known before Step 3; these are not performance):

| definition | state | windows (of 3272) | raw runs | runs ≥ 40d |
|---|---|---|---|---|
| trend_pit | up | 1791 | 53 | 10 |
| trend_pit | flat | 1148 | 60 | 10 |
| trend_pit | down | 332 | 8 | 2 (both 2008-09) |
| vol | high | 1375 | 20 | 8 |
| vol | low | 1867 | 21 | 9 |
| size | small_lead | 1550 | 87 | 8 |
| size | large_lead | 1618 | 88 | 8 |

Structurally, trend_pit "down" can't trigger (B): it has 2 episodes of
≥ 40 days, both in the 2008-09 crash.

### 1.5 Decision map (fixed before Step 3)

This is evaluated separately for each model (icw8, icw9_seas) over every
state of trend_pit, vol and size (calyear reference excluded).

- **(A)** Selection over pool > 0 (point estimate) **and** ≥ 30/40 offsets
  positive in **every** state, for **both** models. Only the pool varies,
  so any gate is a small-vs-large timing bet. The candidate action is a
  hedge on/off, flagged to the COO as market timing.
- **(B)** In some state, for **either** model: selection < 0 with ≥ 30/40
  offsets negative, **and** that state has ≥ 3 episodes (runs ≥ 40d),
  **and** selection with 2008 dropped is still < 0. Then a gross-exposure
  gate is justified, and a Phase 1 trial is proposed. B takes precedence
  over A.
- **(C)** Neither: stop. The regime gate is closed for this model
  (descriptive).

Iteration cap: 2 (bug fixes only).

### 1.6 Phase 1 (not in this order; noted only)

If B were hit, Phase 1 would need: filtered (not smoothed) HMM
probabilities only; deterministic state labelling (for example, the state
with the higher vol is "stress"); two arms, HMM vs the simple PIT rule that
triggered B; a pre-registered drop-2008 kill (the gate must still add
value with 2008 removed); and the 2020+ hold-out untouched unless Gabe
approves.

## 2. Results

(Filled after the pre-reg commit.)
