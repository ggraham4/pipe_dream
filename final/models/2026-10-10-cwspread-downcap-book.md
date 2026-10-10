# WO-58 pre-registration: `opt_cw_spread` avoid screen in a thin-slice long book

Date: 2026-10-10. Commissioned by the COO (WO-58; Gabe's standing instruction 2026-10-09: "listen to
the COO"). Branch `wo58-cwspread-downcap-book`. Code: `final/src/cwbook/`. Outputs:
`final/out/cwbook/*.json`.

**Status: pre-registration, frozen before any outcome statistic of this test exists.** It supersedes
`final/models/2026-10-09-cwspread-downcap-book-prereg-DRAFT.md`, which is left untouched. The only
numbers here are label-free (Step 0 and the load counts). The two reproductions of published numbers
(section 6) run after this doc is committed.

Trial count: options family **trial 25 (31 including WO-36)**. Per the COO, WO-55 is trial 23 and WO-56
is trial 24, by pre-reg commit time.

## 1. Why

WO-52 (in era, 2008-2018) and WO-55 (out of era, 2019-01 to 2025-08, hold-out read #22) both found
that thin-slice names in the bottom decile of `opt_cw_spread` underperform the rest of the slice.
`opt_cw_spread` is the Cremers-Weinbaum call-minus-put implied-volatility spread.
- WO-52: M +2.74% per 40 days, NW39 t 12.2.
- WO-55: M +2.36% per 40 days, NW39 t 5.9.

That is a fact about the pool. This test asks whether the screen improves an actual long book built
where the edge lives.

**Framing:** the certified dead end "opt_cw_spread in the long book" (WO-35 exp B / WO-36) was scoped
to cap2000 names; this test is opened under the WO-6 reopen clause of the down-cap dead end ("a new
factor whose premium is specifically small-cap, e.g. a thin-liquidity/options signal, tested on the v2
grid"). It is not a re-test of WO-36.

## 2. Universe

The WO-37 thin slice exactly. Copied from `final/models/2026-10-01-thin-liquidity-prereg.md` §2:

> **Thin slice on date d:** `eligible_cap150 AND NOT eligible_cap2000` in
> `downcap_universe_v2.parquet` on d.

In code it is `tl_common.universe_on`: `u["thin"] = u.eligible_cap150 & ~u.eligible_cap2000`. It is
survivorship-safe: delisted names are included.

The **book pool** on d is the thin slice intersected with the v2 col c panel rows
(`composite_panel_v2.parquet`). The panel rows carry the factor values.
- The col c loader's blank-check (SPAC) exclusion is applied, as in the live loader
  (`model_audit_wo23.load_theo`).
- The book pool covers 99.97% of thin name-dates on the Stage-1 dates.
- The SPAC exclusion removes 483 panel rows across all tiers.

No other universe is used.

## 3. Dates, data and signal

**Dates.** Only the option-store dates are used:
- **Stage 1:** the 133 WO-52 monthly dates, 2008-01-02 to 2018-12-19.
- **Stage 2:** the 80 WO-55 dates, 2019-01-16 to 2025-08-20.

**No new WRDS pull.** The signal comes from the WO-52 and WO-55 feature files, copied byte for byte
into `final/out/cwbook/`. These files are gitignored, and the code asserts each sha256:

| file | source | sha256 |
|---|---|---|
| `feats_stage1_wo52.parquet` | WO-52 `final/out/thinliq_om/om_options_features_thinliq.parquet` | `c6783045523ca80c1f59e02ebb3035f76f1ade9b994327f14e97d8f69eb03801` |
| `feats_stage2_wo55.parquet` | WO-55 `final/out/cwspread_oos/om_options_features_oos.parquet` | `d7778e048964d3289ba7f78419ce8fe0e73f61081db520358013e9889f09ef0e` |
| `feats_wo36_av.parquet` (reproduction only) | WO-36 `final/out/cwweights/av_options_features_wo25.parquet` | `81638c8fbed41f155fec175c4b6850c3fe453c478a69fc3f3ec24b6b4ed8ec26` |
| seas (read in place) | `wo24-construction-drag/final/out/audit/seas_factor_ext.parquet`, the `trailfilter.SEAS_EXT_RO` file | `ca9721d3879bca0b2340bea660ca43949a485fb9bd9cd2513614dd4137f52e2c` |

So `opt_cw_spread` is the WO-52/WO-55 build, unchanged: the same code, identity filter (`av_keep`) and
DTE/delta bands.

**Kept chain.** A (date, ticker) has a kept chain when it has a row in the feature file. On the Stage-1
dates:
- 80.3% of thin name-dates have a kept chain;
- 74.3% have a non-missing `opt_cw_spread`.

**Bottom decile, label-free.** On each date d:
1. Take the thin-slice names with a non-missing `opt_cw_spread`. Call the count n.
2. Set k = max(1, round(0.10·n)).
3. The bottom decile is the k smallest values: a stable argsort over ticker-sorted rows, as in WO-52's
   `bottom_idx`.

This differs from WO-52 in one way. WO-52 also required a non-missing label, which a book screen
cannot know in advance. Names without a kept chain or signal are never removed.

## 4. Base and variant books

**Base book:**
- **Model:** `icw5_seas` with the frozen live weights (`ic_weighted_composite.PRODUCTION_WEIGHTS_V5_SEAS`):
  momentum_12_1, gross_profitability, accruals, net_issuance_pct and seas.
- **Features:** v2 col c features.
- **Scoring:** the score is `compute_composite_ic_weighted`, with rank_z taken within the pool, weights
  renormalised by available |w|, and NaN where no factor is present.
  - `cb_core.score_icw5` equals the imported function to 0.0 on all 133 dates, on both the full and
    the screened pool (`check_score.json`).
- **Construction:** `pick_decile_volq` (the live construction): top 10% by score within each
  volatility_60 quintile, inverse-vol weighted. It uses `cw_core.pick`, checked by WO-36 against
  `run_expB.portfolio` to 1e-9.
- **Label:** h = 40. The label is `outcome_cache_v2.gross_return_40`: entry at open[t+1], exit at
  close[t+40], with the delisting floor. It is the same label as WO-52 and the book label of WO-36.
- **Costs and offsets:** net of costs, minus SPY's `gross_return_40`, × 252/40. The level is the mean
  over the offsets of section 5.

**Variant book:** identical, except that the bottom-decile names (section 3) are removed from the book
pool **before** ranking and picking.
- rank_z and the volatility quintiles are recomputed on the remaining names, so the book refills from
  them.
- This differs from WO-36's V5, which scored the full pool and then dropped names.

## 5. Offsets, metric, null and bars

**Offset mapping.** WO-36 never used a 40-offset grid. `run_expB.N_OFFSETS = 2` splits the monthly
option dates into 2 interleaved sets (dates[0::2] and dates[1::2]); every other monthly date is about
one 40-day window.
- That mapping carries over unchanged, so the **even/odd-date offsets** apply: 67 and 66 dates in
  Stage 1.
- The 40-split rule (≥ 30/40) does **not** apply.
- Turnover f_new is chained within each offset.

**Costs (binding).** Flat 15 bp, using the project formula (`RX.COST_BPS`;
`net = (1+g)(1−h·f)/(1+h·f) − 1`, h = 7.5bp, the same as `run_backtest.turnover_net_return`).
- A copy of the formula with a cost parameter is asserted equal to `cw_core.evaluate` at 15 bp, to
  1e-12, inside the run.
- A flat 50 bp run is descriptive stress only. No down-cap cost model is introduced.

**Primary metric.** Δ = variant − base, in net %/yr on the Stage-1 dates.

**Rules for Δ:**
- **Per offset.** Each offset's Δ is the mean of its per-date (variant − base) net excess × 252/40.
  Δ is the mean of the two.
- **LOYO.** Leave one calendar year out (11 years, 2008-2018). Drop that year's dates from each
  offset's per-date records, keeping the turnover chains as computed on the full sequence (the WO-36
  rule), then average over the offsets.
- **Year share.** A year's sum of per-date Δ divided by the total sum, with both offsets pooled. It is
  defined only when the total is > 0. Otherwise the share criterion fails.

**Null.** 100 draws of paired random removal.
- On each date, remove the same number of names as the real screen removes from the book pool.
  - That number is the count of bottom-decile flags among book-pool names: median 134 per date in
    Stage 1.
- The removed names are drawn uniformly from book-pool names **with a kept chain**.
- Then rank and pick exactly as for the variant.
- Seeds: 20261010 + k (Stage 1) and 20271010 + k (Stage 2), with k = 0..99.
- Report the null p50 and p80 of Δ.

**Stage-1 bars (2008-2018, in era, fixed now):**
- **PASS (all must hold):**
  - Δ > 0;
  - Δ > null p80;
  - both offsets > 0;
  - LOYO min Δ > 0;
  - max single-year share ≤ 45%.
- **KILL:** Δ ≤ 0, OR Δ ≤ null p50, OR the offsets have opposite signs.
- **MIDDLE:** anything else. Report and stop; no Stage 2.
- No NW t is reported. Any t that is reported uses the bar ≥ 3.75 or an empirical null p (D-NWT).

**Descriptive (all stages):**
- **Book levels.** Base and variant net minus SPY, and gross minus SPY.
- **Equal-weight pool.** The no-score thin-slice equal-weight pool: every book-pool name with a label,
  gross, minus SPY, using the same 2 offsets and × 252/40, with no costs. Report book gross minus
  pool.
- **Stress.** Δ and the levels at 50 bp.
- **Turnover.** f_new.
- **Holdings.** Median names held.
- **Capacity.** Position $ = pick weight × $100k. Compare it with the 20-day median of close × volume
  from Sharadar SEP on d. Report:
  - the mean position $;
  - the median dollar volume of names held;
  - the mean and p95 of position / dollar volume.

## 6. Reproductions, before any null run

`run_book.py --mode reproduce` runs after this commit and before Stage 1. Both checks must pass to 1e-6.

**(i) WO-52's thin M on the 133 dates** uses WO-52's own frame and denominator: names with signal AND
label, and `run_arm1.prep`/`evaluate`. The target is 2.7394 %/40d, as stored (4 decimals in percent,
which is 1e-6 as a fraction).

**(ii) WO-36's base-book number** is its Stage-1 base `excess_ann` of 0.053650011496056194
(`final/out/cwweights/stage1_nominate.json`). Its inputs:
- the AV features file;
- its stored `base_weights`;
- `cw_core.prep/build_picks/evaluate`.

If a reproduction fails, the run stops. The failure is reported as a data or code note in the results
doc, not as a redesign.

## 7. Step 0: power check (label-free; done before freezing)

`final/out/cwbook/step0_power.json`, on the Stage-1 dates, with no label read:

| quantity | value |
|---|---|
| base book mean weight in the bottom cw decile | **5.40%** (count share 6.29%) |
| chance level (10% × share of picks with signal 0.801) | about 8.0% |
| share of base picks with a kept chain | 84.3% (with signal 80.1%) |
| median names held / book pool / pool with signal | 175 / 1,797 / 1,344 |
| median names removed by the screen per date | 134 |
| **implied max Δ = 0.0540 × 2.7%/40d × 6.3** | **0.92 %/yr** |

0.92 %/yr ≥ 0.20 %/yr, so the test is **informative** and continues.

The base already under-holds the bottom decile (5.4% against about 8%). WO-36 found the same on
cap2000 (5.7%).

## 8. Stage 2 (only if Stage 1 = PASS): override of the in-era rule, binding for this step only

- **Hold-out read #23,** reserved in COO.md. Before the run, the results doc logs the read: the date,
  what is read, and "unfitted". It carries the marker line `HOLD-OUT READ #23 LOGGED`, and the runner
  refuses to run without it.
- **Window.** 2019-01 to 2025-08, on the WO-55 store. Everything is frozen from Stage 1.
  - There is one run. Only crash fixes are allowed, and each is logged.
  - Nothing is chosen on 2019+.
- **Stage-2 bars:**
  - PASS: Δ > 0 AND Δ > null p80 AND both offsets > 0.
  - KILL: Δ ≤ 0.
  - MIDDLE: anything else.
- **Also reported:** ex-2019 (2019 is inside the icw weight-fit era) and ex-2020, as the LOYO entries.
- **WO-55 already read the cw screen on the same 2019-01..2025-08 window (hold-out read #22), so Stage
  2 tests whether the pool effect carries into the book, not an independent confirmation of the
  screen.**
- **The icw5_seas base was chosen after hold-out read #21, so the base book is in-sample for 2020+.**
- Nothing else after 2019 is read. Nothing before 2007 is read.

## 9. Discipline

- **Iteration cap:** 3 fix-and-rerun cycles, for code bugs only. No rule changes after outcomes.
- **Runner guards.** `run_book.py` asserts this doc's sha256 and that it is tracked in git, and it
  refuses to overwrite `stage1_result.json` or `stage2_result.json`.
- **Frozen copy.** After the commit, a copy of this doc and its sha256 go into
  `~/.claude/pipe_dream-coordination/wrds-frozen-2026-10-10/`.
- **Promotion.** A PASS is a PROMOTE-CANDIDATE recommendation only. Promotion, or any live change, is
  Gabe's decision.
- **No trading.** The code never places, modifies or cancels an order.
- **Plumbing proof** (before this commit, not a result). On shuffled labels (permuted within date,
  demeaned, SPY = 0) with 3 null draws, the full Stage-1 path ran end to end in 80 s
  (`smoke_SHUFFLED_TEST_labels-shuffled.json`). The verdict machinery returned KILL there.
