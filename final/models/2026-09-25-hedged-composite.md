# WO-9: the universe-hedged composite (2026-09-25)

Work order WO-9, commissioned by the pipe_dream COO. Worker branch
`worktree-agent-a4c6de08254d118aa`, based on WO-7's tip 975ec2d.
Script: `final/src/reset2026/hedged_composite.py`.
Output: `final/out/reset2026/downcap_v2/hedged_composite.json`.

Sections: 1 pre-registration (frozen before any result), 2 data checks,
3 results, 4 verdict.

## 1. Pre-registration (frozen verbatim before any result)

### 1.1 Work order text (verbatim)

> ## Mechanism
> WO-7 (final/models/2026-09-24-noscore-control-v2.md; final/src/reset2026/noscore_control_v2.py; /Users/ggraham/pipe_dream/final/out/reset2026/downcap_v2/noscore_control.json) found the following on the survivorship-safe v2 grid, cap150, 2007-2019, net 15bp, mean of 40 offsets:
> - The icw8 composite ranking beats a random same-size decile_volq book by +3.95pp/yr (sd 0.25, 40/40 offsets).
> - The eligible universe itself earned −0.25 vs SPY.
> - On the window 2011-10-20..2019, icw8 was +0.00 vs SPY, because the small-cap universe lagged SPY by about 2pp/yr.
>
> Question: does hedging the universe leg with a tradable small-cap index keep the selection spread in both windows?
>
> ## Pre-registration (freeze verbatim in your dated doc BEFORE any result)
> - **Data.** IWM (iShares Russell 2000) daily OHLC, adjusted for splits and dividends, from yfinance on this machine, 2006-06..2019-12-31 only.
>   - Save it to /Users/ggraham/pipe_dream/final/data/benchmarks/IWM.csv as a new file. It is gitignored data, so don't commit it.
>   - Name-check: IWM's 2008 calendar-year total return should be about −34%, and 2017 about +14.6%. Assert both within 2pp.
>   - Build the 40-day gross return on the same basis as outcome_cache_v2's gross_return_40 for SPY. First find out exactly what that basis is (read how outcome_cache_v2 / execution.realize_position computes SPY), then replicate it for IWM.
>   - Reconcile the method: apply your IWM function to SPY's own OHLC and reproduce outcome_cache_v2's SPY gross_return_40 on 50 sampled dates to 1e-6.
>   - If yfinance is blocked or fails, stop and report BLOCKED (Gabe's machine needed). Don't substitute another source silently.
> - **Construction.** For each of the 40 offsets and each rebalance date, hedged = (icw8 decile_volq net-15bp book return) − (IWM 40d return) − 10bp per rebalance for the short leg. Assume ETF borrow is ~0 and state that. Excess is annualised ×252/40, as in downcap_v2_readout.backtest.
>   - Reuse noscore_control_v2.py and downcap_v2_readout.py by importing them. Don't edit them.
>   - Also report, as attribution only (not tradable): icw8 − no-score universe book, and IWM − no-score universe book, which checks how well IWM proxies the eligible universe.
> - **Tiers.** cap150 is primary. Report cap500 and cap2000 as well.
> - **Era.** 2007-01-02..2019-12-31. Assert max(date) < 2020-01-01 on every frame. 2020+ is a spent hold-out: never touch it.
> - **Windows.** Full 2007-2019, and common 2011-10-20..2019-12-31. Label each and never splice them.
> - **Trial count.** This is the 14th nomination-era trial of the composite family (≥13 spent before). A pass is a nomination only; promotion is Gabe's call.
> - **Success (cap150, all must hold):**
>   - hedged mean40 > +1.0pp/yr on the full window;
>   - hedged mean40 > +1.0pp/yr on 2011-10..2019;
>   - ≥ 36/40 offsets positive on the full window;
>   - leave-one-year-out min > 0;
>   - |beta| of the hedged per-rebalance series to SPY < 0.3. Report the beta and its t.
> - **Kill:** hedged mean40 ≤ 0 in either window, OR LOYO min ≤ 0.
> - **Middle:** anything else. It goes to Gabe.
> - **Also report:**
>   - the per-year hedged return;
>   - max drawdown of the hedged series;
>   - a 0bp variant (disclosed as supplementary).

### 1.2 Clarifications fixed before any result (2026-09-25)

These settle points the work order leaves open or where two of its
instructions conflict. They were written and committed before the IWM pull,
the name-check, or any backtest number.

**C1. Price basis. The work order's instructions conflict; "same basis as
SPY" governs.** What the SPY basis actually is was found by reading code, not
by running anything:

- `outcome_cache_v2.parquet` was built by `build_downcap_grid_v2.py --step
  outcome`, which calls `build_outcome_cache.main()` unchanged except for the
  stock OHLC directories. SPY's row comes from
  `final/scripts/td_data_local/SPY.csv` through `vectorized_outcomes`:
  `gross_return_40[i] = close[min(i+40, n-1)] / open[i+1] - 1` (NaN when
  `i+1 > n-1`). This is bit-for-bit `execution.realize_position(entry_lag=1,
  entry_at="open", stop_pct=None, cost_bps=0)`.
- `SPY.csv` was written by `final/scripts/local_data_pull.py`, which calls
  `yf.download(..., auto_adjust=False)` and keeps `Open`/`Close`. So it is
  split-adjusted and NOT dividend-adjusted: a price-return series. The
  stock legs (`export_sharadar_ohlc.py`) are on the same split-adjusted,
  price-only basis.
- "Adjusted for splits and dividends" therefore conflicts with "the same
  basis as SPY". The construction rule (and the 1e-6 SPY reconcile, which is
  only meaningful under it) governs. **Primary IWM series: yfinance
  `auto_adjust=False` `Open`/`Close`, price-only, the same basis as SPY and
  as the book.** IWM.csv also stores `adj_close` so the total-return
  variant can be computed from the same file.
- **Name-check:** the −34% (2008) and +14.6% (2017) targets are total-return
  figures, so the within-2pp assertion runs on `adj_close`. The price-only
  calendar returns are reported next to them.
- **Supplementary:** a total-return IWM hedge (IWM 40d return built from
  `adj_close`-scaled open/close) with its gate outcomes disclosed. It is
  expected to sit roughly IWM's dividend yield per year below the primary.
  The primary is price-only on both legs, so dividends are omitted
  symmetrically.
- **Pull-method check:** SPY is pulled with the same yfinance call and its
  `Close` compared against `SPY.csv` on sampled dates in 2007-2019, which
  confirms that the pull reproduces the file SPY's cache row came from.

**C2. End-of-era truncation.** IWM is pulled only through 2019-12-31. The
vectorised rule `exit = min(i+40, n-1)` would give the last ~40 IWM dates a
shortened return, while the book and SPY returns on those dates run into
2020 because the cache was built on the full series. So IWM's 40d return is
set to NaN wherever `i+40 > n-1`. The pull is not extended. `backtest_vectors`
drops NaN-bench dates after costing, exactly as it does for SPY. The number
of dropped rebalance dates is disclosed. icw8-vs-SPY is also reported on the
same masked dates, for a like-for-like comparison. For the SPY reconcile,
SPY.csv is loaded to 2019-12-31 only, and the 50 dates are sampled only from
those whose exit bar falls within that range.

**C3. Machinery.** Books come from `noscore_control_v2.build_books(p, TIERS,
with_null=False)` on `downcap_v2_readout.load_column("c")`. The hedged
excess is `noscore_control_v2.backtest_vectors(icw8, all_dates, bench=IWM40
+ 0.0010)`. That is identical to "net book − IWM − 10bp", because
`backtest_vectors` subtracts the bench after costing. Before any IWM number,
the same call with `bench=SPY` must reproduce `readout.json`
c/tier/icw8 (mean40, sd40, loyo_min, offsets_positive) to 1e-6. The
common window uses `IWM40.where(date >= 2011-10-20)`, built the same way as
WO-7's `spy_common`. The attribution lines are icw8 − noscore and
IWM − noscore, where "IWM − noscore" is the mean over offsets of
(IWM − noscore net). They use WO-7's alignment (dates on which both icw8
and noscore books exist), not its 20-null-book alignment, so icw8 − noscore
will not exactly equal WO-7's `total_icw8_minus_noscore`. The gap is
reported and not asserted.

**C4. Definitions.**
- **mean40 / offsets positive / LOYO min:** as in `noscore_control_v2.summarize`
  (LOYO is the mean over offsets of the excess with one calendar year dropped;
  the minimum over dropped years).
- **Beta:** per-rebalance hedged series pooled over all rebalance dates. The
  40 offset chains partition the calendar, so each date appears once. OLS of
  hedged (net − IWM − 10bp, not annualised) on SPY `gross_return_40` with an
  intercept. t from Newey-West HAC with lag 39, the project's convention,
  because consecutive dates' 40-day returns overlap. Full window.
- **Max drawdown:** compound each offset chain's per-rebalance hedged return
  (1+h) into a wealth path and take its maximum peak-to-trough decline.
  Report the median and the worst across the 40 offsets. Full window.
- **Per-year hedged return:** for each calendar year, the mean over offsets
  of that year's mean per-rebalance hedged return, ×252/40.
- **0bp variant (supplementary):** the 15bp book cost and the 10bp short-leg
  charge both set to zero.
- **Borrow:** ETF borrow cost assumed ≈ 0. IWM is general collateral, and the
  10bp per rebalance is the only short-leg charge.
- **Gates** are evaluated on the primary: cap150, price-only IWM, 15bp + 10bp.
  cap500, cap2000, total-return IWM and 0bp are reported and do not
  change the verdict.

## 2. Data checks

(filled after the pre-registration commit)

## 3. Results

(filled after the data checks)

## 4. Verdict

(filled last)
