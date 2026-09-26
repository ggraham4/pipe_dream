# WO-13: standardized unexpected earnings (SUE) / post-earnings-announcement drift, v2 grid, nomination era

Date: 2026-09-25. Work order WO-13 (COO), approved by Gabe 2026-09-25.
Branch `worktree-agent-a82cc71ecb09661f5`, based on `integration` 8f47808.
Code: `final/src/sue/`. Outputs: `final/out/sue/`.

Status: **PRE-REGISTERED.** This part was committed before any IC or portfolio
number for `sue` was computed. Results are appended below the line at the end.

## Mechanism

Post-earnings-announcement drift (Ball-Brown 1968; Foster-Olsen-Shevlin 1984;
Bernard-Thomas 1989). Prices under-react to earnings surprises and drift in
the surprise's direction for about 60 trading days. One of the most
replicated anomalies, and stronger in small and illiquid names. It is
different from the closed earnings-timing family (WO-5 and Round 16 were
about WHEN announcements happen). This one is about the SIZE of the surprise.

## Definition (frozen; copied verbatim from the work order)

- **Data.** `final/data/sharadar/sf1_fundamentals.parquet`, **dimension == 'ARQ' ONLY**. ARQ is as-reported quarterly, not restated. MRQ restatements would be look-ahead, and the file has no MRQ; assert that. Column `eps`. The availability date is SF1 `date` (the datekey, i.e. the filing date).
  - First verify that `date` IS the filing date (datekey), not the period end. Name-check AAPL and MSFT: their 2015-2016 quarterly `date` values should match their 10-Q/10-K filing dates, which fall about 25-45 days after `reportperiod`.
  - If `date` is not the filing date, STOP and report BLOCKED.
- **Duplicates.** If one (ticker, reportperiod) has several ARQ rows, use the FIRST by `date` (as first reported).
- **SUE_q** = (EPS_q − EPS_{q−4}) / sd(EPS_j − EPS_{j−4} for the 8 quarters j = q−1..q−8). This is the seasonal random walk (Bernard-Thomas).
  - Require at least 6 of those 8 differences, and sd > 0. Otherwise NaN.
  - Quarters are matched by `reportperiod` (fiscal quarter end), with q−4 being the same fiscal quarter a year earlier, within ±15 days.
  - Winsorize SUE at ±10.
- **Factor `sue`** on panel date t = the SUE of the latest ARQ filing with `date` ≤ t−1. Use a one-trading-day lag, because a filing after the close can't be traded until the next session.
  - Stale after 100 calendar days since that filing's `date`, then NaN.
  - **Registered sign +1.**
- **Explicit expected-value checks:**
  - About 4 ARQ filings per name per year among cap150 names (median in [3.5, 4.5]).
  - Median |SUE| roughly in [0.5, 1.5].
  - Hand-compute SUE for 3 named filings with an independent short script, e.g. one AAPL quarter, one small cap, one dead name that later delisted.
  - Report coverage of finite `sue` among eligible cap150 names by year. Expect > 60% after 2009; lower suggests a join or mapping bug. Also report coverage for old-grid vs added tickers, since a much lower rate on added small caps would suggest a mapping bug.

## Screen (frozen; copied verbatim from the work order)

Use the same gate stack and harness style as WO-4 (`final/src/insider/screen_insider_v2grid.py`) and WO-5 (`final/src/eap/screen_eap.py`). Import and reuse them; don't copy.

- **Grid.** v2 column c (`downcap_v2_readout.load_column("c")`, which includes the SPAC rule described in `working_panel.py` / the WO-11 doc).
- **Settings.** cap150 primary, h = 40, label `forward_return_tradable_40`, nomination era.
- **Reconcile first.** The harness icw8 decile_volq net 15bp over 40 offsets must reproduce readout.json cap150 (+0.0285416) to 1e-6. Do this before any SUE number.
- **Trial family.** "earnings surprise / PEAD", NEW, **k = 1. Bar: pooled NW(39) IC t ≥ +1.96 in the registered sign.**
- **PASS requires ALL of:**
  1. NW t ≥ +1.96;
  2. both halves (odd/even years, as WO-4) positive;
  3. both-sides sector-demeaned t (demean factor AND return within sector) ≥ +1.0. Report the factor-only t too, labelled;
  4. 0/40 grid-offset sign flips;
  5. LOYO: no single year > 45% of the effect;
  6. icw9 (sue added to icw8 with the frozen IC-shrinkage weighting rule, split-half OOS, exactly as WO-4/WO-5) vs icw8 decile_volq net 15bp beats the 80th percentile of a 20-draw within-date shuffle null of `sue`.
- **KILL:** any gate fails. A pass is a NOMINATION only; promotion is Gabe's. Add nothing to any live list or the forward ledger.
- **Descriptive only (not gates):**
  - the median cross-sectional Spearman of `sue` with the icw8 score, momentum_12_1, gross_profitability, and volatility_60;
  - IC at h = 20 as a sanity check on drift decay. Label it clearly; it is not a trial.
- **Pre-registration.** Copy the Definition and Screen sections verbatim into the doc and have the integrator COMMIT it BEFORE any IC or portfolio number is computed. The data-validation checks above may run first.

Hold-out: rebalance dates 2007-01-02..2019-12-31 only. Late-2019 dates whose
40d labels run into 2020 are kept unmasked (Gabe's ruling). No statistic is
computed on dates ≥ 2020-01-01.

## Implementation notes (frozen before any IC)

Choices the spec leaves open, fixed here before any IC/portfolio number:

1. **Quarter matching.** "q−k" = the same ticker's (deduplicated) ARQ row
   whose `reportperiod` is nearest to `reportperiod_q − 3k calendar months`
   (pandas `DateOffset(months=3k)`), within ±15 days; none → missing. q−4 is
   k = 4 (12 months). For each prior quarter j, EPS_{j−4} is matched from j
   the same way (j's own 12-month match).
2. **Point-in-time legs.** EPS_{q−4} counts only if filed (`date`) on or
   before q's `date`. A D_j counts only if both of its legs (j and j−4) were
   filed on or before q's `date`.
3. **sd** is the sample standard deviation (ddof = 1) of the finite D_j
   (need ≥ 6 of 8 and sd > 0). Winsorize (clip) at ±10 after the division.
4. **t−1** = the previous date on the union trading calendar of
   `composite_panel_v2` (all tickers). The factor uses the latest filing with
   `date` ≤ t−1. Two filings on the same `date`: the one with the latest
   `reportperiod` wins.
5. **No fallback.** If the latest eligible filing's SUE is NaN, `sue` is NaN
   (no reaching back to an older filing). Stale means (t − filing `date`) >
   100 calendar days → NaN.
6. **Screen universe.** Primary cap150 column c ONLY (k = 1). Old-grid vs
   added tickers is a coverage descriptive, NOT a second screened universe.
   The harness is `screen_insider_v2grid` imported as a module with
   `COL = "sue"`, `SIGN = +1`, `SIGNS9 = SIGNS8 + {sue: +1}`, `T_BAR = 1.96`;
   `ic_gates(U, xcol="sue")` is called explicitly; its `main()` is not used.
   Gate 5 is WO-4's max single-year share of the summed daily IC ≤ 0.45
   (LOYO NW t reported alongside).
7. **Descriptive Spearman.** Per-date Spearman (screen_insider.daily_corr,
   min 20 names) of `sue` vs the frozen-PRODUCTION_WEIGHTS icw8 score and vs
   the raw factor columns; the median over dates is reported.
8. **h = 20 descriptive.** Label = close[t+20] / open[t+1] − 1 built from
   composite_panel_v2's own open/close (row shifts within ticker; prices
   through 2020-02 may feed labels of late-2019 dates only). The same
   construction at 40 must reproduce `forward_return_tradable_40` before the
   h = 20 IC is reported. NW lag 19. Not a trial.
9. **Input hashes.** `sf1_fundamentals.parquet` sha256
   `7812f5e1a53f00963e3fc67534845447b73544a252a55e38436db222f58cb5b7`;
   `composite_panel_v2.parquet` sha256
   `4baff1d7e947882966683e611ae0ea934cee844d49a207c9005a8aa3863ea2dc`
   (mtime 2026-09-24 14:10). Re-hashed at screen start.
10. SF1 per-share fields are split-adjusted jointly with share counts (AAPL
    2012 eps 0.336 with 26.2B shares, i.e. both after the 7:1 and 4:1
    splits; eps·shareswa/netinc median 0.9997, 5-95% [0.84, 1.15]), so SUE,
    a ratio within one ticker's history, is scale-consistent. The
    `actions.csv` split table only covers 2025+, so it can't be used for a
    split-proximity check.

## Data validation (run before this commit; no IC computed)

Scripts: `final/src/sue/build_sue.py`, `validate_sue.py`, `hand_check_sue.py`.
Outputs: `final/out/sue/build_sue_meta.json`, `validate_sue.json`,
`hand_check_sue.json`.

**Datekey verification: PASS.** `date` is the filing date, not the period end.

| ticker | reportperiod | SF1 date | lag | actual filing |
|---|---|---|---|---|
| AAPL | 2014-12-27 | 2015-01-28 | 32 | 10-Q filed 2015-01-28 |
| AAPL | 2015-06-27 | 2015-07-22 | 25 | 10-Q filed 2015-07-22 |
| AAPL | 2015-09-26 | 2015-10-28 | 32 | 10-K filed 2015-10-28 |
| AAPL | 2015-12-26 | 2016-01-27 | 32 | 10-Q filed 2016-01-27 |
| MSFT | 2015-06-30 | 2015-07-31 | 31 | 10-K filed 2015-07-31 |
| MSFT | 2015-09-30 | 2015-10-22 | 22 | 10-Q filed 2015-10-22 |
| MSFT | 2016-03-31 | 2016-04-21 | 21 | 10-Q filed 2016-04-21 |
| MSFT | 2016-06-30 | 2016-07-28 | 28 | 10-K filed 2016-07-28 |

All AAPL/MSFT 2015-2016 quarters have lags of 20-32 days. They match the
known 10-Q/10-K filing dates. MSFT's lags of 20-22 days sit just below the
"about 25-45" rule of thumb because MSFT files its 10-Q on earnings day.
Across all ARQ rows, the filing lag median is 40 days, with 5-95% at [28, 90]
days. Two rows have date < reportperiod.

The file's dimensions are {ARQ, ARY}; MRQ is asserted absent. There are
492,578 ARQ rows, or 474,166 after first-by-date dedup of (ticker,
reportperiod). No row has a null date or reportperiod.

**Expected-value checks (cap150 column c, 2007-2019):**

- **Filings per name-year** (names eligible that year): median **4.0**, in
  [3.5, 4.5]. Mean 3.85; 0.9% of name-years have zero filings.
- **Median |SUE|** (pre-winsor): **0.60**, in [0.5, 1.5]. 0.85% of values
  have |SUE| ≥ 10. Mean SUE is +0.089, and 46.9% of values are > 0.
- **Hand check** (independent script, no import of build_sue): all 3 match
  to 1e-9.
  - AAPL 2015-12-26 (filed 2016-01-27): SUE **+0.6569**
  - AAME 2013-06-30 (Atlantic American, micro cap, v2-added ticker): SUE
    **+7.5094**
  - RSHCQ 2013-09-30 (RadioShack, delisted 2015): SUE **−4.7590**
- **Lag timing spot check.** AAPL's value switches on 2016-01-28, the
  session after its 2016-01-27 filing.

**Coverage of finite `sue` among eligible cap150 column-c rows:**

| year | all | old grid | added |
|---|---|---|---|
| 2007 | 77.0% | 80.6% | 71.5% |
| 2008 | 78.9% | 82.2% | 72.3% |
| 2009 | 84.6% | 86.7% | 79.2% |
| 2010 | 86.7% | 88.7% | 82.5% |
| 2011 | 86.4% | 88.7% | 81.3% |
| 2012 | 84.5% | 87.1% | 78.4% |
| 2013 | 83.7% | 86.3% | 77.9% |
| 2014 | 80.9% | 83.7% | 74.8% |
| 2015 | 79.4% | 81.9% | 73.6% |
| 2016 | 81.3% | 83.2% | 76.3% |
| 2017 | 83.5% | 84.9% | 80.1% |
| 2018 | 83.8% | 85.6% | 79.2% |
| 2019 | 83.4% | 85.2% | 78.2% |

- **2009 onward:** 83.4% overall; 85.6% on the old grid, 78.3% on added
  tickers. That clears the > 60% bar. Added tickers run about 7 points below
  the old grid: a uniform gap, not a collapse, which fits their younger
  histories (the rule needs 3 years of quarters).
- **Tickers with no ARQ rows at all:** 0 old-grid tickers, and 1 added
  ticker (SIC1).
- **Coverage by month:** about 85% in every month except February (56%)
  and March (77%). That dip is the 100-day staleness rule at work: the gap
  from the Q3 10-Q to the 10-K is longer than 100 days.
- **Why rows are missing (2009+):**
  - 71%: the latest filing's SUE is NaN (short history or a q−4 mismatch);
  - 28%: stale;
  - 0.7%: no filing yet.

---

## Results

Written after the pre-registration commit 76d0e1f (15:34:03). The screen ran
15:34:24–15:42:55 on 2026-09-25 and was not rerun.
- Script: `final/src/sue/screen_sue.py`.
- Report: `final/out/sue/sue_screen_report.json`; log:
  `final/out/sue/screen_sue.log`.
- composite_panel_v2 sha256 at screen start: `4baff1d7…62dc`, identical to
  the pre-registration hash.

**Verdict: PASS (nomination only).** All six registered gates pass. Promotion
is Gabe's call. Nothing was added to any live list or to the forward ledger.

### Universe

- Rows: column c, cap150, 2007-01-02..2019-12-31. That is 9,756,141 rows
  across 6,508 tickers, of which 2,987,605 rows are on added tickers.
- Coverage of finite `sue`: **82.5% overall**, **84.9% on old-grid tickers**,
  **77.0% on added tickers**.
- Coverage by year is in the Data validation section above: above 60% in
  every year, 83.4% for 2009+.

### Harness reconciliation (run before any SUE number; hard assert)

| check | harness | readout.json | diff |
|---|---|---|---|
| icw8 decile_volq net 15bp, mean of 40 offsets | +0.028541633 | +0.028541633 | 0 |
| split-half OOS IC, fit odd → test even | 0.0404111057 | 0.0404111057 | <1e-15 |
| split-half OOS IC, fit even → test odd | 0.0553979834 | 0.0553979834 | 0 |

### Gates

| # | gate | value | bar | pass |
|---|---|---|---|---|
| 1 | pooled NW(39) Spearman IC t, sign +1 | IC +0.01320, **t +2.17** (3,272 dates) | t ≥ +1.96 | yes |
| 2 | odd-year / even-year mean IC | +0.01680 (t +1.82) / +0.00899 (t +1.22) | both > 0 | yes |
| 3 | both-sides sector-demeaned IC t | **+2.09** (IC +0.01086) | ≥ +1.0 | yes |
| 3 (reported, not gated) | factor-only sector-demeaned IC t | +2.09 (IC +0.00939) | — | — |
| 4 | grid-offset sign flips of the daily IC | **0/40**; offset means range +0.0112 .. +0.0162 | 0/40 | yes |
| 5 | max single-year share of summed daily IC | **0.335** (2015; 2007 is also 0.335) | ≤ 0.45 | yes |
| 6 | icw9 vs icw8, decile_volq net 15bp, split-half OOS; 20-draw within-date shuffle null of `sue` | icw9 +2.4412%/yr vs null p80 +2.3504% (p50 +2.3436%, sd 0.019pp); real beats 20/20 draws | > null p80 | yes |

Only 0.03% of rows have an Unknown sector.

**Year shares of the summed daily IC:**

| 2007 | 2008 | 2009 | 2010 | 2011 | 2012 | 2013 |
|---|---|---|---|---|---|---|
| +0.335 | +0.167 | **−0.410** | +0.033 | +0.225 | +0.089 | +0.082 |

| 2014 | 2015 | 2016 | 2017 | 2018 | 2019 |
|---|---|---|---|---|---|
| +0.196 | +0.335 | −0.140 | +0.150 | −0.030 | −0.031 |

**Leave-one-year-out NW t (the year shown is the one dropped):**

| 2007 | 2008 | 2009 | 2010 | 2011 | 2012 | 2013 |
|---|---|---|---|---|---|---|
| 1.56 | 2.00 | 3.81 | 2.12 | 1.72 | 2.00 | 2.00 |

| 2014 | 2015 | 2016 | 2017 | 2018 | 2019 |
|---|---|---|---|---|---|
| 1.77 | 1.52 | 2.55 | 1.86 | 2.26 | 2.28 |

**Gate 6 detail:**

| quantity | value |
|---|---|
| icw8 (split-half OOS weights) | +2.3683%/yr; sd over 40 offsets 0.54pp; 40/40 offsets positive |
| icw9 | +2.4412%/yr; sd 0.48pp; 40/40 offsets positive |
| icw9 − icw8 | **+0.073pp/yr** |
| null − icw8 | median −0.025pp; p80 −0.018pp |
| `sue` t used for the weights | fit-odd +1.82; fit-even +1.22 |
| `sue` weight in icw9 | +0.060 (fit on odd years) / +0.026 (fit on even years) |
| OOS IC of the score | icw9 +0.04869 (t 6.63) vs icw8 +0.04848 (t 6.65) |
| rows dropped as icw8-NaN | 2,812 |

### Descriptive only (not gates, not trials)

**Median cross-sectional Spearman of `sue` with:**

| icw8 score (frozen weights) | momentum_12_1 | gross_profitability | volatility_60 |
|---|---|---|---|
| +0.062 | **+0.262** | +0.036 | −0.083 |

`sue` overlaps partly with momentum, which is expected (the post-announcement
return feeds 12-1 momentum). It barely overlaps with the composite.

**IC at h = 20 (DESCRIPTIVE, NOT A TRIAL; NW lag 19):**
- Pooled IC is +0.01402, t +3.22.
- Odd years: +0.01923 (t +3.09). Even years: +0.00795 (t +1.38).
- For comparison, h = 40 on the same rows gives IC +0.01320, t +2.17.
- The per-date IC is about the same at 20 and 40 days, but the t-stat is
  higher at 20 days. That fits drift concentrated in the first month after
  the filing.

**Label reconstruction check (label used for h = 20):**
- The h = 20 label is close[t+20]/open[t+1] − 1, built from the panel's own
  open/close.
- The same construction at 40 days matches `forward_return_tradable_40` to
  1e-6 on 100% of 9,678,148 rows. Coverage ratio 1.0.

### Caveats (COO)

- (a) The portfolio contribution is small. icw9 − icw8 is +0.073pp/yr. The null median is −0.025pp and p80 is −0.018pp, so the null band is narrow because the added weight is only 0.03–0.06.
- (b) The halves are thin (t +1.82 / +1.22). LOYO t falls to 1.52 if 2015 is dropped and 1.56 if 2007 is dropped. 2009 is −41% of the sum. It passes the registered ≤ 45% share gate, but the pooled t of 2.17 depends on 2007 and 2015.
- (c) SF1 ARQ EPS is retroactively split-adjusted (AAPL FY16Q1 shows 0.82 = 3.28/4). SUE is a within-ticker ratio, so it is scale-invariant and there is no look-ahead in the value.
- (d) icw8 on the finite-sue rows earns +2.37%/yr, against +2.85 on all of column c, because the comparison runs on the finite-sue universe.
  - *Worker correction to (d), from the report JSON:* the gate-6 books run
    on all 9,756,141 column-c cap150 rows, not only the finite-sue rows.
    Only 2,812 rows (icw8-NaN) are dropped. Rows with a NaN `sue` are still
    scored, because the coverage-aware composite averages the factors each
    row has. The +2.37% vs +2.85% gap comes from the weights:
    - gate 6's icw8 uses split-half out-of-sample refit weights (fit on odd
      years, score even years, and vice versa), as WO-4 did;
    - +2.85% is icw8 with the frozen full-era PRODUCTION_WEIGHTS (the
      reconciliation row).
    The comparison is still like-for-like. icw8 and icw9 use the same rows
    and the same OOS scheme.
- (e) This is a nomination only. Confirmation is forward-only and Gabe's call.
