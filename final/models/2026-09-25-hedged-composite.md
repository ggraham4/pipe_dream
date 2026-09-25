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

All passed. The pre-registration was committed as 60a2247 before any of these
ran. Log: `final/out/reset2026/downcap_v2/hedged_composite.log`.

| check | result |
|---|---|
| yfinance reachable | yes. IWM pulled 2006-06-01..2019-12-31, 3,420 rows, saved to `final/data/benchmarks/IWM.csv` (new, gitignored, not committed) |
| name-check 2008, total return (`adj_close`) | **−34.14%** vs −34% target, within 2pp. Price-only: −35.13% |
| name-check 2017, total return | **+14.58%** vs +14.6% target, within 2pp. Price-only: +13.06% |
| largest daily IWM close move | 11.2% on 2008-12-01 (a real market day; no split seam) |
| pull-method check: yfinance `auto_adjust=False` SPY vs `SPY.csv` | max relative difference 2.2e-16 on open and close, over all 3,523 dates. The pull reproduces the file SPY's cache row came from |
| method reconcile: `ret40` on SPY.csv vs outcome_cache_v2 SPY `gross_return_40` | 50 sampled dates: max \|diff\| **1.35e-8** (tol 1e-6). Same on all 3,483 eligible dates. The residual is the cache's float32 storage |
| end-of-era mask (C2) | IWM 40d return NaN on the last **40** era dates (from 2019-11-04). Those rebalance dates drop out of every hedged figure |
| machinery reconcile: `backtest_vectors(icw8, bench=SPY)` vs `readout.json` c/tier/icw8 | equal to 1e-6 on mean40, sd40, loyo_min and offsets_positive, for all three tiers (cap150 +0.02854) |
| per-date series oracle | per-offset mean of the per-date hedged series ×252/40 equals `backtest_vectors` to 1e-12 |
| hold-out guard | every frame asserts max(date) < 2020-01-01. SPY cache read filtered to ≤ 2019-12-31 |

## 3. Results

Excess figures are in pp/yr (×252/40): the mean over 40 offsets, with the
number of offsets positive. The short leg costs 10bp per rebalance on top of
the book's 15bp. ETF borrow is assumed ≈ 0. Hedged = net book − IWM − 10bp.

### 3.1 Primary: cap150, price-only IWM, 15bp + 10bp

| window | mean40 | sd40 | min40 | offsets > 0 | LOYO min (dropped year) | beta to SPY (NW t, lag 39) | MDD median / worst |
|---|---|---|---|---|---|---|---|
| full 2007-2019 | **+2.28** | 0.29 | +1.69 | **40/40** | **+1.61** (2018) | **−0.164** (t −5.01) | −13.1% / −14.3% |
| common 2011-10-20..2019 | **+0.92** | 0.33 | +0.11 | 40/40 | −0.40 (2018) | −0.246 (t −5.23) | −13.1% / −14.3% |

Like-for-like, unhedged icw8 vs SPY on the same IWM-available dates: full
+3.10, common +0.33. Masking the last 40 dates moves the full-window figure up
from the readout's +2.85.

Per-year hedged return, cap150 primary (mean over offsets, ×252/40, pp/yr):

| 2007 | 2008 | 2009 | 2010 | 2011 | 2012 | 2013 | 2014 | 2015 | 2016 | 2017 | 2018 | 2019 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| −5.3 | +7.5 | +9.7 | −0.5 | +9.1 | −1.1 | −1.1 | +6.2 | +2.0 | **−12.5** | +6.4 | +10.3 | −1.7 |

Six of 13 years are negative. 2016, the small-cap rally year, is the worst at
−12.5.

### 3.2 Gates (cap150 primary)

| gate | value | result |
|---|---|---|
| full mean40 > +1.0pp | +2.28 | pass |
| common 2011-10..2019 mean40 > +1.0pp | **+0.92** | **FAIL** (short by 0.08pp) |
| ≥ 36/40 offsets positive (full) | 40/40 | pass |
| LOYO min > 0 (full) | +1.61 (drop 2018) | pass |
| LOYO min > 0 (common), if the clause covers it | **−0.40** (drop 2018) | **fail** |
| \|beta to SPY\| < 0.3 | 0.164 (t −5.01) | pass |
| kill: mean40 ≤ 0 in either window | +2.28 / +0.92 | not triggered |
| kill: LOYO min ≤ 0 | full +1.61, common −0.40 | **reading-dependent** (see below) |

**Outcome: it depends on a scope the pre-registration left open.** The work
order's LOYO clauses ("leave-one-year-out min > 0" and "OR LOYO min ≤ 0")
name no window. Neither does clarification C4. The script evaluated LOYO on
the full window only, following WO-7 and the readout. That choice was not
fixed before results, so both readings are reported and the COO decides:

- **LOYO on the full window only: MIDDLE.** The common-window mean40 of
  +0.92 misses the +1.0 gate, and no kill fires.
- **LOYO checked in both windows: KILL.** The common-window LOYO min is
  −0.40 when 2018 is dropped.

cap500 splits the same way (common LOYO −0.64, drop 2018). cap2000's common
LOYO is +0.30 (drop 2014).

The JSON's `verdict_cap150` field ("MIDDLE") and every `gates` block record
the full-window-LOYO reading only. The common-window LOYO values are in each
`common.loyo_min`.

### 3.3 Other tiers (primary construction; reported, not gating)

| tier | full mean40 (pos) | full LOYO min | common mean40 (pos) | beta (t) | MDD median | the gates would read |
|---|---|---|---|---|---|---|
| cap150 | +2.28 (40/40) | +1.61 | +0.92 (40/40) | −0.164 (−5.01) | −13.1% | MIDDLE |
| cap500 | +2.07 (40/40) | +1.38 | +0.69 (40/40) | −0.206 (−7.35) | −14.9% | MIDDLE |
| cap2000 | +2.21 (40/40) | +1.35 | +1.28 (40/40) | −0.298 (−9.02) | −18.4% | pass (beta 0.298, just under 0.3) |

### 3.4 Supplementary variants (disclosed; they do not change the verdict)

| variant, cap150 | full mean40 (pos) | full LOYO min | common mean40 (pos) | the gates would read |
|---|---|---|---|---|
| **total-return IWM** (dividends in the short leg only) | +0.91 (40/40) | +0.22 | **−0.54 (0/40)** | KILL |
| 0bp (no book cost, no short-leg charge) | +3.11 (40/40) | +2.44 | +1.73 (40/40) | pass |

The total-return variant reads KILL in all three tiers (cap500 common −0.77,
cap2000 common −0.18). It is not like-for-like: it credits IWM's dividends
(about 1.4pp/yr) to the short leg while the book, built from split-adjusted
price-only Sharadar OHLC, earns none of its own. The primary is price-only on
both legs, so dividends drop out symmetrically only if the book's names yield
about what IWM yields. That has not been measured. A real short pays IWM's
dividends, and a real long collects the book's, so the tradable answer lies
between the primary and this variant according to the book's yield relative
to IWM's. The gap is material against a +1.0pp gate.

### 3.5 Attribution (not tradable)

Measured on dates where both the icw8 and no-score books exist (cap150: no
dates removed). The IWM-price bench masks dates the same way for both books.

| tier | window | icw8 − noscore | IWM − noscore | noscore − SPY |
|---|---|---|---|---|
| cap150 | full | +3.16 (40/40) | +0.25 | −0.06 |
| cap150 | common | +2.10 (40/40) | +0.55 | −1.77 |
| cap500 | full | +2.87 | +0.17 | +0.02 |
| cap500 | common | +1.77 | +0.45 | −1.67 |
| cap2000 | full | +3.28 | +0.45 | −0.26 |
| cap2000 | common | +2.44 | +0.53 | −1.75 |

IWM is a close proxy for the eligible universe: it trails the no-score book by
only +0.25 (full) and +0.55 (common) pp/yr. That is price-only on both sides.
IWM's total return would sit about 1.4pp higher. So the hedge removes the
universe leg's 2011-2019 shortfall against SPY (−1.77) almost entirely. What
it cannot recover is that the selection spread itself is smaller in the
common window: +2.10 against +3.16 over the full window. The hedged common
figure (+0.92) is roughly that spread minus IWM − noscore (+0.55), minus the
0.63pp/yr that the 10bp short-leg charge costs at 6.3 rebalances a year.

The icw8 − noscore figures are not asserted equal to WO-7's
`total_icw8_minus_noscore`, because WO-7 aligned dates across 20 null books
and these are the icw8/noscore-only dates (C3).

## 3.6 COO ruling and ITERATE #1 (registered before any iterate result)

**COO ruling (made after the results, 2026-09-25).** LOYO applies to the
FULL window only, following the readout/WO-7 precedent. In the work order,
"in either window" qualifies only the kill's mean clause. The primary verdict
is therefore **MIDDLE**. Success fails on the 2011-19 mean (+0.92 < +1.0),
and no kill fires. The 2011-19 LOYO min of −0.40 (drop 2018) stays on the
record.

**ITERATE #1 (1 of 3; this fixes the basis, so it is not a new trial).**
Measure the book's own dividend yield so the tradable number can be pinned
down.

- (a) **Book yield.** For the icw8 decile_volq book, per rebalance over the
  40-day hold, weight each name's dividend return by the book's weights and
  annualise ×252/40. Report the full and 2011-10..2019 windows for every
  tier.
- (b) **IWM yield** over the same windows, from yfinance Adj Close vs Close.
- (c) **Tradable hedged** = price-only hedged + (book yield − IWM yield),
  per rebalance, for full and 2011-19, all tiers, 15bp and 10bp as before.
- **Frozen reading (cap150):** tradable 2011-19 mean40 ≤ 0 → **KILL** (the
  kill's mean clause applied to the tradable number). Tradable 2011-19 > 0
  → verdict stays **MIDDLE** and goes to Gabe with the tradable numbers.
  Tradable full-window mean40 and LOYO min are reported either way.
- **Constraints unchanged:** assert < 2020 on every frame, and mask exits
  after 2019-12-31 as before.

**Clarification, fixed before the iterate ran: the dividend source.** The
COO named `final/data/sharadar/actions.csv`. On inspection that file covers
only 2025-09-09..2026-09-10 (JNJ has just 4 dividend rows, all 2025-26), so
it holds no 2007-2019 dividends and cannot be used. The substitute is from
the same vendor and is disclosed here, not swapped in silently: the Sharadar
SEP price panel, `final/data/sharadar/panel/stocks/*.parquet`. That panel is
the source every book OHLC CSV was exported from (`export_sharadar_ohlc.py`),
and it carries `close` (split-adjusted, the book's basis) alongside
`closeadj` (split- and dividend-adjusted).

- **Formula.** Per name, with f = closeadj/close, entry bar e = i+1 (the
  open) and exit bar x = i+40:
  dividend return = (close[x]/open[e]) × (f[x]/f[e] − 1).
- **Consistency with IWM.** This is the same construction as IWM's
  (Adj Close/Close), i.e. total-return ret40 minus price ret40.
- **Ex-date handling.** A dividend going ex on the entry day is excluded,
  because you buy at the ex-open. One going ex on the exit day is included.

**Checks, fixed before the run:**
- **Basis reconcile.** The panel's open/close reproduce outcome_cache_v2
  `gross_return_40` on the book's picks. Mismatches are counted and must be
  0 apart from a disclosed series-end truncation.
- **Dividend name-check.** Per-share dividends inferred from the f jumps:
  JNJ calendar 2017 = $3.32 and 2018 = $3.54, XOM 2017 = $3.06, each within
  2%.
- **Hold-out.** The panel is loaded through 2019-12-31 only, with a
  max(date) assert.
- **Window.** Only rebalance dates with finite IWM (the C2 mask) are used.
- **Weights.** The book weights are the renormalised weights the gross
  return uses. Names dropped for NaN returns get no dividend.

## 3.7 ITERATE #1 results: the tradable hedged composite

Script: `final/src/reset2026/hedged_tradable.py`. Output: `hedged_tradable.json`
and `.log`. The pre-registration (§3.6) was committed locally as 61d321b
before this ran. The integrator's push of 61d321b was blocked by the
auto-mode permission classifier and was not retried.

**Checks (all passed):**
- **Dividend name-check** (inferred from Sharadar closeadj/close jumps; 4
  ex-dates each):
  - JNJ 2017: $3.298 vs $3.32 (0.789 / 0.834 / 0.842 / 0.835)
  - JNJ 2018: $3.534 vs $3.54 (0.834 / 0.899 / 0.901 / 0.901)
  - XOM 2017: $3.061 vs $3.06
  - The ex-dates are the real ones (e.g. JNJ 2017-02-24, 2017-05-25). All
    three are within 2%.
  - Caveat: closeadj rounding leaves ±0.001 jitter in f on non-ex days. The
    jitter is zero-mean, and the formula reads f only at entry and exit.
- **Basis reconcile.** The panel's open/close reproduce the book's gross
  return on every IWM-live rebalance date (3,232), with max |diff| of
  1.8e-9 (cap150), 1.7e-9 (cap500) and 1.9e-9 (cap2000).
  - Missing names: 0. Era-truncated names: 0.
  - Names on the delisting floor: 9,639 (cap150). These are handled as in
    the outcome cache: the exit is the last bar, with the dividends earned
    up to then.
- **Price-only recheck.** It reproduces §3.1 exactly (to 1e-12).
- **Hold-out.** The panel is loaded 2006-12..2019-12 with a max(date) assert.

**Dividend yields** (pooled over IWM-live rebalance dates, ×252/40, %/yr):

| tier | window | book | IWM | book − IWM |
|---|---|---|---|---|
| cap150 | full | 1.64 | 1.37 | **+0.27** |
| cap150 | 2011-10..2019 | 1.62 | 1.46 | **+0.16** |
| cap500 | full / common | 1.63 / 1.59 | 1.37 / 1.46 | +0.26 / +0.13 |
| cap2000 | full / common | 1.76 / 1.66 | 1.37 / 1.46 | +0.39 / +0.20 |

The low-vol-tilted book out-yields IWM slightly. The short leg's dividend
cost is therefore more than covered, and the tradable number sits just
above the price-only primary, not between it and the total-return variant.

**Tradable hedged** (price-only hedged + book yield − IWM yield; 15bp book
cost + 10bp short leg):

| tier | full mean40 (pos) | full LOYO min | 2011-19 mean40 (pos) | 2011-19 LOYO min | beta (NW t) |
|---|---|---|---|---|---|
| **cap150** | **+2.56** (40/40) | **+1.88** (2018) | **+1.08** (40/40) | −0.26 (2018) | −0.165 (−5.09) |
| cap500 | +2.33 (40/40) | +1.65 (2011) | +0.82 (40/40) | −0.53 (2018) | −0.208 |
| cap2000 | +2.60 (40/40) | +1.73 (2011) | +1.48 (40/40) | +0.49 (2014) | −0.301 |

The 0bp variant (supplementary) for cap150 is full +3.38 and 2011-19 +1.90.

- **cap150 tradable per year** (pp/yr): 2007 −4.7, 2008 +7.8, 2009 +10.0,
  2010 −0.1, 2011 +9.5, 2012 −0.8, 2013 −1.1, 2014 +6.4, 2015 +1.9,
  2016 −12.4, 2017 +6.7, 2018 +10.6, 2019 −1.4.
- **MDD:** median −12.8%, worst −14.2%.

**Frozen reading (§3.6).** The tradable cap150 2011-19 mean40 is +1.08 > 0,
so the verdict is **MIDDLE**, and it goes to Gabe with these numbers.

For information only (this does not change the frozen reading): on the
tradable basis, every WO-9 success gate is cleared at cap150 under the COO's
full-window LOYO ruling.
- full +2.56 > 1.0
- 2011-19 +1.08 > 1.0, by a margin of only 0.08pp
- 40/40 offsets positive
- LOYO min +1.88
- |beta| 0.165

Two things still hold. The 2011-19 result rests on 2018: its LOYO is
−0.26 with 2018 dropped. And the +1.0 bar is cleared only after a basis
fix made post-hoc.

## 4. Verdict

**MIDDLE. It goes to Gabe.** This is the 14th nomination-era trial of the
composite family. ITERATE #1 fixed the basis only, so it is not a new trial.

- **COO ruling.** LOYO is read on the full window only.
- **Primary (price-only IWM).** Every success gate passes except the
  2011-19 mean: +0.92 against the +1.0pp bar. No kill fires.
- **ITERATE #1 (tradable, with book and IWM dividends).** The book
  out-yields IWM by +0.27pp/yr (full) and +0.16pp/yr (2011-19). That puts
  the tradable cap150 at:
  - full +2.56 (40/40), LOYO min +1.88
  - 2011-19 +1.08 (40/40)
  - beta −0.165
  The frozen reading is tradable 2011-19 > 0, so the verdict stays
  MIDDLE. On this basis every WO-9 success gate clears, but the 2011-19
  margin is 0.08pp.

What Gabe should weigh:
- **The hedge does its job.** It removes the small-cap universe's 2011-19
  drag against SPY almost entirely (IWM tracks the eligible universe to
  within about 0.3-0.6pp/yr). The selection spread survives in both windows
  on all 40 offsets.
- **The 2011-19 spread is thin and concentrated.** It is about +1pp/yr
  after costs, and it goes negative with 2018 dropped: −0.26 tradable,
  −0.40 price-only.
- **Year to year, the hedged series is noisy.** Six of 13 years are
  negative, 2016 is about −12pp, and the median offset's MDD is about −13%.
- **The hedge over-shorts the market** (beta −0.16, t −5). That bias cost
  return over 2007-2019.
- **cap2000 is the strongest tier** on the 2011-19 window (+1.48 tradable,
  LOYO +0.49). Its residual beta is −0.30, right at the limit.
