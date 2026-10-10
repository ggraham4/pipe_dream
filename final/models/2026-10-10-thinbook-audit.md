# WO-61 plan: thin-slice book audit (Gate A on the level, spread-based costs)

Date: 2026-10-10. Commissioned by the COO (WO-61). Branch `wo61-thinbook-audit` (based on origin/integration
2a96082). Code `final/src/thinaudit/` (imports `final/src/cwbook/` and the reset2026 harness read-only). Outputs
`final/out/thinaudit/*.json`. Results go to `final/models/2026-10-10-thinbook-audit-results.md`.

**Status: plan, frozen before any outcome statistic of this audit exists.** Nothing below has been computed on
labels. The only numbers here are file hashes and figures already published by WO-6, WO-51, WO-54 and WO-58.

- **Trial count 0.** This is an audit: no new signal, no admission decision, no bars on the book.
- **Iteration cap:** 3 fix-and-rerun cycles. Then stop and report "no result within budget".
- **Never trades.** Research code only; no broker or order code.

## 1. Why

WO-58 (integration a5c9013) put the thin-slice icw5_seas book at **+8.06 %/yr** net of 15bp vs SPY on the 133
WO-52 monthly dates, 2008-2018 (2 interleaved offsets), and +5.82 gross over the equal-weight thin pool. WO-6 found
no cap premium on the survivorship-safe v2 grid: icw8, 40 offsets, 2007-2019, cap150 +2.85, cap2000 +2.84. WO-54
put icw5_seas at cap150 on the same grid at +3.64. Before Gabe decides on a thin book (D-THINBOOK), the level has to
be explained and costs have to be realistic for $150M-$2B names.

## 2. Era and data (binding)

- **Entry dates 2008-01-02 .. 2018-12-31 only.** Exit legs of late-2018 windows reach about 2019-03 (close[t+40]).
  That is the same as WO-58 and inside the standing 2007-2019 era. No read goes past the last exit date of a
  2018 entry: every CRSP/quote read is capped at **2019-03-31** and asserted. No hold-out read. Nothing before 2007.
- The one WO-6 reproduction in §3 step A runs WO-6's own window (2007-01-02 .. 2019-12-31, inside the era) only to
  reproduce its published number.
- Input files and sha256 (computed at plan time; the code asserts each):

| file | sha256 |
|---|---|
| `final/out/reset2026/composite_panel_v2.parquet` (built 2026-10-10 13:23) | `48ef4e47c9e8e704c989ee6dbe0ee9cc00e969a04a1725929e7ad458ec6082b7` |
| `final/out/reset2026/outcome_cache_v2.parquet` (built 2026-10-10 13:23) | `434d353fe63d27bbaaaba47cd8238f049a95def72304e2989dfef1982e2212d4` |
| `final/data/sharadar/downcap_universe_v2.parquet` | `f4a40f4b71883b2010e9d8f97c790b46da89279c5f058a61a25c03512daccfeb` |
| WO-52 features (copy in `final/out/thinaudit/`, gitignored) | `c6783045523ca80c1f59e02ebb3035f76f1ade9b994327f14e97d8f69eb03801` (= WO-58's) |
| seas (`trailfilter.SEAS_EXT_RO`) | `ca9721d3879bca0b2340bea660ca43949a485fb9bd9cd2513614dd4137f52e2c` (= WO-58's) |
| `final/data/wrds/link/permno_sharadar.parquet` (WO-51 crosswalk) | `4db64e336fb1ec147cafa85a50a340c5bc1ba8a1a83bc787c42bb7365f72108c` |
| `final/data/wrds/crsp/derived/spinfix_labels.parquet` (WO-54 fixed labels) | `84b3ff99585af9dc4dd2f05cb269ad1726c753c22d9a3ea09cbf356ec7f6d81a` |

- WO-54's spin-off label fix is opt-in (WO-57, default OFF), so `outcome_cache_v2` carries **unfixed** labels.
  WO-58's +8.06 ran on them. Check 3 applies WO-54's `label_fix` to the pick rows it touches and reports the book Δ.
- CRSP daily `ret/retx/prc/openprc` already on disk (`final/data/wrds/crsp/dsf_YYYY.parquet`, WO-51) are used for
  check 4. The only new WRDS pull is Part 2's bid/ask (§5).

## 3. Part 1: Gate A on the level (binding checks; pass/fail each)

All books: v2 col c features, SPAC (blank-check) exclusion as WO-6/WO-58, `pick_decile_volq` (top 10% by score
within volatility_60 quintiles, inverse-vol weights), label `outcome_cache_v2.gross_return_40`
(close[t+40]/open[t+1] with the delisting floor), picks with a NaN label dropped and weights renormalised, net 15bp
via `net = (1+g)(1−h·f)/(1+h·f) − 1`, minus SPY `gross_return_40`, × 252/40. "Thin" = `eligible_cap150 AND NOT
eligible_cap2000`. Scores rank within the pool being booked.

**NaN seas (stated now).** `compute_composite_ic_weighted` and WO-58's `score_icw5` skip a NaN factor and divide by
the |w| of the factors present. A name with NaN seas is scored on the other four factors only, as a weighted mean of
fewer rank_z terms, so its score has fatter tails. Reported (descriptive): share of base picks with NaN seas vs the
pool's share; the book level with NaN seas set to neutral (rank_z 0, |w| kept in the denominator); the book level on
seas-present names only.

### Check 1: reconcile with WO-6's construction

The fast numpy path (`cb_core.score_icw5` + `cw_core.pick`) is used only after its picks equal WO-6's slow path
(`ICW.compute_composite_ic_weighted` + `C.pick_decile_volq`, as in `downcap_v2_readout.per_date_picks`) on all 133
dates, for icw8 and icw5_seas, on the thin pool (same tickers, weights to 1e-12).

WO-6's `backtest()` stitches `all_dates[off::40]`, which cannot run on 133 monthly dates. On the 133 dates its picks
are stitched with WO-58's 2-offset evaluate (even/odd dates).

Decomposition, one variable per step (all icw8 unless named):

| step | universe | model | dates | offsets |
|---|---|---|---|---|
| A | cap150 | icw8 | all trading days 2007-01-02..2019-12-31 | 40 |
| B | cap150 | icw8 | all trading days 2008..2018 | 40 |
| C | cap150 | icw8 | the 133 WO-52 dates | 2 |
| D | thin | icw8 | 133 | 2 |
| E | thin | icw5_seas | 133 | 2 (= WO-58 base) |

Plus, on identical dates: cap150 / cap2000 / thin × icw8 / icw5_seas on the 133 dates (2 offsets) and on the
2008-2018 40-offset grid. Also the thin flag from the panel's `eligible_*` vs WO-58's `downcap_universe_v2` thin flag
(agreement share on the 133 dates), and WO-58's book-pool share.

**Pass (all):**
- (a) step E through WO-6's slow path equals WO-58's +0.08058666317545946 to 1e-6;
- (b) step A equals WO-6's published cap150 icw8 +0.028541632641009042 to 1e-6, **or** the gap is explained by a
  named file change (the panel and outcome cache were rebuilt 2026-10-10; WO-51 was bit-exact on 10-08);
- (c) every step of A→E is reported, so the +2.85 → +8.06 gap is located step by step, with no unexplained residual
  (the steps telescope by construction).

### Check 2: daily 40-offset grid

The thin icw5_seas book on every trading day 2008-01-02..2018-12-31 that has panel rows, offsets
`dates[off::40]`, off = 0..39, turnover chained within each offset (WO-6 `backtest`). Report mean, sd, min, max over
the 40 offsets, offsets > 0, LOYO min. Also the same for thin icw8, cap150 and cap2000 (icw5_seas and icw8).
**Pass:** the thin icw5_seas 40-offset mean is computed on ≥ 30 of 40 offsets with ≥ 60 dates each (this check
measures; the level bar is in the verdict).

### Check 3: name checks (WO-58 base book, 133 dates)

- **Top 10 contributors.** Contribution of a ticker = Σ over its pick rows of (w · r) / n_dates(offset) × 252/40,
  averaged over the 2 offsets (so the contributions sum to the gross book level). For each of the 10 largest:
  per-row Sharadar vs CRSP 40-day label (check-4 method), WO-54 spin events in any window, the WO-47 ticker-reuse
  segment (ticker suffix / crosswalk permno unique over its windows), entry price and the min/max close in the
  window. **A name is real if** its contribution recomputed with CRSP labels (retx) is within ±25% of its Sharadar
  contribution and it has no spin/reuse event that CRSP disagrees with. Unmapped names: a hand check of the
  Sharadar price path against Sharadar `closeunadj`/actions, stated as such.
- **Delisting path.** Pick rows whose window ends in a delisting (`truncated`): count, weight share, mean Sharadar
  label, mean CRSP label (with dlret). Also pick rows of names that delisted at any later date (descriptive).
- **Price < $5 at entry:** share of pick rows and of pick weight with `closeunadj` < 5 on t (descriptive).
- **WO-54 spin-off fix:** book level with `label_fix` substituted on the pick rows it covers; Δ reported.
- **Pass:** all 10 top contributors real, AND |mean Sharadar − mean CRSP label| on delisting-path pick rows ≤ 2pp,
  AND the spin-fix Δ ≥ −0.25pp/yr (a fix that lowers the book by more than that is an artefact).

### Check 4: label basis

Confirm in code that the WO-58 label is `outcome_cache_v2.gross_return_40` (= close[t+40]/open[t+1], delisting
floor). Rebuild each base-book pick row's label from CRSP exactly as WO-51 Phase 3 (`crsp_labels`): entry leg
|prc|/openprc on e = t+1, × Π(1+retx) over e < d ≤ x = t+40, delisting return if the CRSP delisting date is in (e, x],
Sharadar label as counted fallback. My reimplementation is first checked against WO-51's
`derived/phase3_pickrows.parquet` r_C on a random 20,000-row sample to 1e-9.
- Report: mapped share of thin pick rows (count and weight), fallback reasons, share of non-fallback pick rows with
  |S − C| ≤ 10bp, book Δ = S − C (retx basis, primary) in %/yr, and Δ on ret basis (dividends; not judged).
- **Pass:** ≥ 98% of non-fallback pick rows within 10bp (WO-51's cap150 pick-level figure was 98.6%) AND
  |S − C| ≤ 0.5pp/yr (WO-51's bar).

## 4. Verdict

- **LEVEL-OK:** checks 1-4 all pass AND the check-2 thin icw5_seas 40-offset mean is within 2pp of +8.06
  (6.06 .. 10.06).
- **LEVEL-BUG:** any check finds an artefact. The corrected level is quantified (e.g. CRSP-label book, spin-fixed
  book, 40-offset level).
- A LEVEL-OK is input to D-THINBOOK, nothing more.

## 5. Part 2: spread-based costs (DESCRIPTIVE ONLY, no pass/fail; the binding cost model is Gabe's call)

**Pull.** `crsp.dsf` `permno, date, bid, ask` (closing quotes; not `bidlo`/`askhi`) for the permnos the crosswalk maps
from the thin book pool on the 133 dates and on the 2008-2018 daily grid, dates 2008-01-01 .. 2019-03-31, one
connection, one query per year, parquet `final/data/wrds/crsp/dsf_bidask_YYYY.parquet` (main checkout, gitignored,
never committed). A negative `prc` (no trade) does not void the quote.

**Half-spread per trade** = (ask − bid) / (ask + bid), i.e. half the quoted spread over the mid, on the trade date:
- entry: the closing quote on e = t+1 (the fill is at the open; the close quote is the proxy);
- exit: the closing quote on x = t+40; if the name stops trading before x, the last quote on or before x in the
  window;
- **valid quote:** bid > 0, ask > bid, and spread/mid ≤ 50%; otherwise missing;
- **missing quote or unmapped** → Corwin-Schultz (2012) two-day high-low estimate from Sharadar SEP OHLC on
  (day−1, day), negative estimates set to 0, half-spread = S/2. If OHLC is missing too, 7.5bp (counted);
- **floor 5bp** per side; the ×1.5 scenario multiplies after the floor;
- the shares of trades priced by quote / Corwin-Schultz / default are reported.

**Aggregation (primary)** mirrors WO-58's turnover formula with per-name costs: on each date with N picks and new
names S_new (new vs the previous date in the same offset),
`c_in = (1/N) Σ_{i∈S_new} hs_i(e)`, `c_out = (1/N) Σ_{i∈S_new} hs_i(x)`, `net = (1+g)(1−c_in)/(1+c_out) − 1`.
With every hs = 7.5bp this is exactly the flat-15bp formula; the code asserts that to 1e-12.
**Sensitivity (descriptive):** pick-weighted exact turnover, `c_in = Σ_{i new} w_i hs_i(e)`,
`c_out = Σ_{i not held next date} w_i hs_i(x)`.

**Report**, base and WO-58 variant (cw-spread bottom-decile removed before ranking), 133 dates, 2 offsets:
net vs SPY and net vs the equal-weight thin pool (gross), under (i) flat 15bp, which must reproduce WO-58 exactly
(base +0.08058666, variant +0.08562552, Δ +0.00503886, to 1e-9), (ii) spread-based, (iii) spread-based × 1.5; and
Δ (variant − base) under each. Also the median and mean half-spread of traded names, by year.

## 6. Outputs

`final/out/thinaudit/check1_reconcile.json`, `check2_offsets40.json`, `check3_names.json`, `check4_labels.json`,
`part2_costs.json`. Per-row CRSP values go only to `final/data/wrds/crsp/derived/` (parquet, never committed).
