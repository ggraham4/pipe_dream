# WO-6: survivorship-safe down-cap feature grid (2026-09-24)

Commissioned by pipe-dream-coo; approved by Gabe ("Go ahead with the down cap
grid since that should be easy with the SHARADAR subscription").
Branch `worktree-agent-ab20b69899959cac5`, based on integration 371f2d0.

## Why

`PREREGISTRATION.md` Amendment 1 (2026-09-22): `composite_panel.parquet`'s
grid is the 4,011 tickers that were cap2000-eligible at *some* date. Its
cap500/cap150 rows are therefore conditioned on later success. In-grid minus
out-of-grid 40d return on cap150-only rows was +3.03%/window (t 17). Every
cap500/cap150 number, including the composite's +3.75%/yr cap150 headline,
is unreadable until the grid covers the names that never became large.

## Phase 1 findings, measured BEFORE any build (read-only)

Scripts: `final/src/reset2026/downcap_grid_inventory.py`,
`final/src/reset2026/downcap_grid_prechecks.py`; outputs in
`final/out/reset2026/downcap_v2/{inventory,prechecks}.json` (main checkout).

**Inventory.**

| | count |
|---|---:|
| tickers cap500- or cap150-eligible at any date (v2) | 9,262 |
| already in the old grid | 4,007 |
| missing from the old grid | 5,255 |
| ... SPAC (SIC "Blank Check") | 657 |
| ... non-SPAC | **4,598** (3,186 since delisted) |
| non-SPAC missing with SEP prices already on disk (`panel/stocks`) | **4,598 (100%)** |
| non-SPAC missing with SF1 ARY on disk / ARQ on disk | 4,584 / 4,595 |
| non-SPAC missing with `sf1_shares.csv` rows | 4,595 |
| v2 cap150 non-SPAC rows whose ticker has SF1 on disk | 99.996% |

**The key is barely needed.** Amendment 1 assumed SF1 had to be pulled.
It does not: `sharadar_pull_fundamentals.py` pulled SF1 ARQ/ARY for *every*
ticker by date range (13,864 tickers), not only the grid, and
`panel/stocks` is Sharadar SEP for every domestic common stock. Checked for
completeness in time, not just presence: for 40 random missing names, the last
ARQ `calendardate` equals `tickers_master.lastquarter` in 40/40. The first
ARQ is about one year after `firstquarter` in 20/40. That is the same pattern
old-grid names show (ETSY 2013-12-31 vs 2014-12-31; AAPL's is capped by the
2003 pull start), so it is Sharadar's pre-IPO comparative quarter, not a
missing pull.

The pull list is **14 tickers × SF1 (ARQ+ARY), 0 × SEP, 0 × ACTIONS**:
BRR, CCXI, COE1, GLF, MCGA, MONT, NKT, OPI, PKDC, QRR, USDE (ARQ present, no
ARY), and MKTSQ1, NCLX, SIC1 (neither). All are domestic common. The bulk
by-date pull already returned nothing for them, so a per-ticker re-pull will
most likely return nothing too. It is optional. The build below does not wait
for it, and their rows count as coverage loss (≤0.3% of tickers).

**FINRA short interest** (`data/finra/short_interest_raw.csv`) runs from
2020-04-15 onward and covers 99.9% of the missing names that are still alive.
It is irrelevant to the nomination era, where the factor is NaN for every
name, old or new.

**Reproduction-target provenance.** `composite_panel.parquet` (Sep 18) was
built by the `process_ticker`-based `build_features_fundamentals_sharadar.py`
that is on integration. The main checkout's copy of that file is an
uncommitted 2026-09-22 vectorized rewrite that casts the 14 fundamental
columns to **float32**. It produced the current (Sep 22)
`features_with_fundamentals_sharadar_pit.parquet`, whose `market_cap`
differs from `composite_panel`'s in 43,250 of 43,743 rows on the 20 test
dates. Price columns (open, close, volatility_60, pct_from_high_252,
forward_return_tradable_40) match on 43,743/43,743. So the baseline is named
explicitly: **reproduce `composite_panel.parquet` (Sep 18) using integration's
code**, not today's main-checkout intermediates. Flagged to the COO: the main
checkout's fundamentals panel is no longer the one the composite was measured
on.

## Build design

`final/src/reset2026/build_downcap_grid_v2.py` runs the existing builders
unchanged. It imports each one, repoints its module-level input and output
paths to new `*_downcap_v2*` files, and calls its own `main()`/`build()`:

1. `build_features_sharadar` (prices → 11 price features and labels)
2. `build_features_fundamentals_sharadar` (SF1 → 14 fundamentals, market_cap)
3. `build_issuance_features`, `build_short_interest_features`,
   `build_event_features`
4. `reset2026/quality_factors` (gross_profitability, accruals, asset_growth,
   momentum_12_1)
5. `reset2026/build_panel` → `composite_panel_v2.parquet`, with the v2
   eligibility flags as `eligible_cap*` and the v1 flags carried as
   `eligible_cap*_v1`
6. `reset2026/build_beta_feature` → `beta_feature_v2.parquet`
7. OHLC CSVs for the added tickers go to a NEW directory,
   `scripts/td_data_sharadar_downcap_v2/` (the shared `td_data_sharadar/` is
   not touched). `build_outcome_cache` reads both directories and writes
   `outcome_cache_v2.parquet`.

The ticker set is the union of the old 4,011 and all 9,266 v2 tickers, SPACs
included. SPACs are excluded at analysis time. Every step refuses to run if
its output path already exists. No existing file is overwritten.

## PRE-REGISTRATION (written before the v2 build has produced a row)

### R: reproduction (key acceptance test)
On the 20 dates below (evenly spaced over 2007-2019), take the rows of the old
4,011 tickers **out of the full v2 build**. This is stronger than a restricted
re-run, because it also shows that adding 5,255 tickers perturbs nothing: every
builder works per ticker. Compare them against `composite_panel.parquet`
(v1 flags against `eligible_cap*_v1`) and against `beta_feature.parquet` and
`outcome_cache.parquet`.

Dates: 2007-01-03, 2007-09-10, 2008-05-15, 2009-01-21, 2009-09-28,
2010-06-04, 2011-02-08, 2011-10-13, 2012-06-20, 2013-02-28, 2013-11-04,
2014-07-14, 2015-03-19, 2015-11-20, 2016-07-29, 2017-04-05, 2017-12-11,
2018-08-17, 2019-04-26, 2019-12-31.

**Pass means:** the (ticker, date) row sets are identical. Every numeric
column is bit-identical (`a == b`, or both NaN), so the NaN masks are
identical too. Sector and the v1 flags are equal. `gross_return_40`,
`truncated`, `beta_252` and `market_return` are identical. Anything else is
a FAIL, and it is reported with the columns and counts. There is no tolerance.

### Build success (all three required)
1. R passes.
2. **Row coverage:** ≥ 95% of v2 `eligible_cap150` non-SPAC (ticker, date)
   rows are present in `composite_panel_v2`, both over the whole panel and over
   2007-2019.
3. **Factor coverage:** for each of the 7 factors other than short interest,
   the non-null rate on v2 cap150 non-SPAC rows that are NEW (ticker not in
   the old grid) is ≥ 90% of the old grid's own non-null rate on its cap150
   rows over the same dates (2007-2019). Short interest has no data before
   2020 and is excluded. "Complete factor features" cannot mean all 8
   non-null: `momentum_12_1` needs 252 days of history and SF1 lags filings,
   so that reading would fire for definitional reasons.

Plus named checks A1-A3 pass.

### Build kill
Row coverage < 90% of v2 cap150 non-SPAC rows. That would mean Sharadar lacks
the names: report and stop.

### Named Gate-A checks (expected values fixed now)
**A1: never-large small caps are present at plausible dates.** None of these
is in the old grid, and none was ever cap2000-eligible. Each must be in
`composite_panel_v2` on 2014-06-30 with `eligible_cap150 == True` and grid
`market_cap` within ±30% of the Sharadar daily `marketcap` shown (the grid's
cap is SF1 `sharesbas` × close, a different construction):

| ticker | company | Sharadar mcap 2014-06-30 ($M) | outside ref: Alpha Vantage current mcap vs Sharadar last ($M) |
|---|---|---:|---|
| ANIK | Anika Therapeutics | 668.1 | 272.7 vs 281.6 (−3%) |
| NGS | Natural Gas Services Group | 412.0 | 428.0 vs 476.3 (−10%) |
| WTBA | West Bancorporation | 243.5 | 486.1 vs 493.1 (−1%) |
| NRIM | Northrim BanCorp | 174.6 | 545.7 vs 579.0 (−6%) |
| ACHN | Achillion Pharmaceuticals (dead) | 732.7 | Alexion acquisition ≈ $930M, closed Jan 2020, vs Sharadar last 946.7 |

A historical outside reference was not available: the Twelve Data market-cap
endpoints are not on this plan. Alpha Vantage's current market cap anchors
the Sharadar series' scale, within 10% on all four live names.

**A2: dead names are present with their delisting.** The last grid date equals
`tickers_master.lastpricedate`: ACHN 2020-01-27, HNR 2017-05-04, GCAP
2020-07-30. In `outcome_cache_v2`, `truncated` is True on each name's final
40 rows and False before them.

**A3: per-date counts.** `composite_panel_v2` rows with `eligible_cap150`
(SPACs included, matching the report) are ≥ 99% of
`downcap_universe_v2_report.txt`: 2,953 on 2008-06-30, 3,213 on 2014-06-30,
3,100 on 2017-06-30. The cap500 counts are 1,993, 2,449 and 2,418. The 1%
tolerance covers universe rows whose (ticker, date) has no SEP bar.

### Phase 2 read-out (fixed now; NOT run in Phase 1)
A re-measurement of the existing model on honest data. It is descriptive, it
is not a new trial, and it has no kill. It replaces the unreadable +3.75%/yr.
- Model: icw8 = frozen `ic_weighted_composite.PRODUCTION_WEIGHTS`, not refit.
- Metrics: (i) split-half out-of-sample pooled Spearman IC (odd/even years),
  as `ic_weighted_composite.py`; (ii) `decile_volq` excess return net of
  15bp, averaged over all 40 grid offsets, with leave-one-year-out.
- Tiers: cap150 and cap500. Era: nomination only, 2007-01-01 .. 2019-12-31.
  The code asserts `max(date) < 2020-01-01`. SPACs are excluded.
- Three columns, so the two fixes are not conflated:

| column | grid | eligibility flags | reads |
|---|---|---|---|
| a | old | v1 | should reproduce the published number |
| b | old | v2 | b − a = the liquidity-floor (split-basis) fix |
| c | v2 | v2 | c − b = the survivorship fix |

## Results

(appended after the build, below this line; nothing above is edited)
