# WO-29: EAR (earnings announcement return) nomination screen

Date: 2026-09-30. Worker branch `worktree-agent-ad838240373d22717` (COO WO-29).
Family: SUE/PEAD. Trial 2 of the family (SUE = trial 1, WO-13, passed at
1.96). Bar |t| >= 2.24, sign +. Revenue surprise (trial 3) is NOT part of
this order. No variants of window, holding period or sign after seeing
results.

## 1. Pre-registration (written and committed BEFORE any EAR-vs-return statistic)

### Hypothesis and mechanism
Earnings announcement return drift (Chan-Jegadeesh-Lakonishok 1996;
Brandt-Kishore-Santa-Clara-Venkatachalam 2008): the market's 4-day reaction
to an earnings announcement underreacts, so a stock whose announcement
window return beat the market keeps drifting up. Sign +. Published result
with an economic reason (underreaction / limited attention).

### Data
- Universe: composite_panel_v2 (the working panel, `reset2026/working_panel.py`),
  column c (`downcap_v2_readout.load_column("c")`, SPAC rule applied before
  scoring), `eligible_cap150`, 2007-01-02..2019-12-31.
- Horizon h = 40, label `forward_return_tradable_40` = close[t+40]/open[t+1] - 1.
- Hard `assert date < 2020-01-01` on every loaded frame (panel, outcome
  cache, SEP, SPY.csv, 8-K pool). No 2020+ read of any kind. The era-end
  label overlap into Jan-Feb 2020 (labels of late-2019 rows) stays
  unmasked, per Gabe.
- 8-K pool: `final/data/edgar/8k_item202.parquet` (WO-5 pull, v1 CIKs) plus
  a top-up `final/data/edgar/8k_item202_v2topup.parquet` for v2 CIKs not in
  the WO-5 request list (same EDGAR submissions-API logic, copied to
  `final/src/ear/pull_8k_v2topup.py`; SEC user-agent, <= ~7.5 req/s). Both
  read with a `filing_date < 2020-01-01` filter, then asserted.
- Ticker -> CIK: `tickers_master.csv` `secfilings` (same rule as the pull
  script). The same mapping and merged pool feed both the coverage check
  and the factor.
- Prices: Sharadar SEP `data/sharadar/panel/stocks/2005-01..2019-12`
  (files after 2019-12 never opened), `close` (split-adjusted, not
  dividend-adjusted). SPY: `final/scripts/td_data_local/SPY.csv` `close`
  (raw, not dividend-adjusted), rows < 2020-01-01 only.
- Market calendar: SEP dates with >= 1000 tickers (same rule as WO-26 io_gap).

### Definition (frozen)
- Events: ORIGINAL `8-K` filings whose items include 2.02. `8-K/A` excluded.
  Every original 2.02 filing is an event, including non-earnings 2.02
  filings (pre-announcements, guidance updates): the spec says "latest
  original 8-K Item 2.02 filing", so these reset the window; they are not
  filtered.
- Day 0 = the first market-calendar day on or after `filing_date`.
- Daily returns r_d = close_d / close_{d-1} - 1 on consecutive market-calendar
  days, for the stock (SEP close) and SPY (SPY.csv close).
- EAR = sum over d = -1, 0, +1, +2 of (r_i,d - r_SPY,d). Requires a valid
  (finite, > 0) SEP close for the stock on every market day -2..+2 and an SPY
  close on each of those days; otherwise the event's EAR is missing.
- After-close releases: a release after the close on filing day F has its
  price reaction on F+1, which is inside the -1..+2 window. A pre-open
  release reacts on day 0. Both are covered without using acceptance times.
- Availability: EAR is known at the close of day +2. The feature on panel
  date t uses the latest original event with day0_idx + 2 <= t_idx
  (so filing_date + 2 trading days <= t, and every price used is dated <= t).
  PIT assert on every row: max price date used <= t and filing_date + 2
  market days <= t.
- Live window: EAR is live on t while 0 <= t_idx - (day0_idx + 2) < 60 (60
  trading days from availability, including the availability day), then
  neutral. If the latest available event has missing EAR, the row is neutral
  (an older event is not substituted).
- Signed rank: on each date, over the column-c cap150 rows whose EAR is live
  and finite, `ear = rank_z` = (rank - 1)/(n - 1) - 0.5 (average ties,
  in [-0.5, +0.5]). Every other row (no event, stale, missing EAR, unmapped
  CIK) gets `ear = 0` (neutral mid-rank), NOT NaN. The composite
  renormalizes over present factors (ic_weighted_composite.py ~L165-171), so
  NaN would silently reweight the others. `rz_ear` in the composite is this
  signed rank directly; it is never re-ranked.

### Step 0: pool integrity (Gate A), before any outcome statistic
1. Top up EDGAR for v2 CIKs missing from the WO-5 request list. If EDGAR is
   blocked: stop, report BLOCKED.
2. Coverage: share of column-c cap150 name-dates (2007-2019) with >= 1
   original 8-K Item 2.02 filing with filing_date in the prior 100 market
   trading days (filing day0_idx in (t_idx - 100, t_idx], filing_date <= t),
   for v1-present names (in the frozen 4,011-ticker old grid) vs v1-absent
   names. Must be within 10pp, else report and stop. Diagnostic breakdown by
   `tickers_master.category` (ADRs / foreign filers file 6-K, not 8-K). ADRs
   are NOT excluded to rescue the check.
3. Dead name: LEH (CIK 806085, found by CIK since Sharadar may suffix the
   ticker): confirm its 8-K 2.02s appear and that it is in v2 cap150.
4. Hand-check one named company's filing dates against its quarterly cadence.

### Gates (all must pass)
Harness: `insider/screen_insider_v2grid.py` + `insider/screen_insider.py`
imported as modules (never edited), as WO-13/18/26. Overrides below.
1. Pooled NW(39) Spearman rank-IC of `ear` (all rows, neutral 0 included) vs
   the label: t >= 2.24 with sign +.
2. Mean daily IC > 0 in BOTH 2007-2013 and 2014-2019 (the harness's odd/even
   years split is reported as descriptive only).
3. Both-sides sector-demeaned IC t >= 1.0 (demean factor AND return within
   date x sector; harness `sector_both_sides`).
4. 0/40 grid-offset sign flips of the BOOK INCREMENT: for each offset
   o = 0..39, increment_o = (icw9_seas + EAR) - icw9_seas annualised net
   excess return at that offset (same offset for both books). A flip is
   increment_o <= 0. Gate: 0 flips. (`DR.backtest` is copied into
   `final/src/ear/` so it returns per-offset values.) The harness's
   daily-IC offset flips are reported as descriptive.
5. LOYO: max single-year share of the effect <= 45%, "effect" = sum of the
   daily IC series (harness `year_share`). Book-increment leave-one-year-out
   reported as descriptive.
6. Book: icw10 = icw9_seas + EAR vs base icw9_seas (= FC8 + `seas`, sign +1),
   decile_volq, net 15bp, mean over 40 offsets, split-half OOS weights on
   both sides (WO-18 method: weights w = sign*max(0.1,|t|-1)/sum fit on odd
   years score even years and vice versa; t = NW(39) IC t in the fitting
   half). Real icw10 must exceed the 80th percentile of a 20-draw
   within-date shuffle null (seeds 0..19, numpy default_rng(seed), full
   refit per draw) on the same base. Shuffle domain: the live (nonzero)
   EAR signed ranks are permuted among the live rows within each date;
   neutral rows stay 0, so the neutral mask is identical in the real run
   and every null draw. Rows with no base score are dropped from both books
   (harness `common` mask). Base `seas` is the WO-18 factor
   (`seas_factor_v2.parquet`, sha256 8054af21...), NaN where undefined, as in
   the live icw9_seas.
7. Gate A clean: Step 0 passes, the PIT assert passes, the label trace
   (recompute close[t+40]/open[t+1]-1 from v2 open/close on a sample of
   dates whose t+40 is < 2020-01-01, matches the panel label), harness
   reconcile (icw8 frozen reproduces `downcap_v2/readout.json` to 1e-6),
   frozen weight rule reproduces PRODUCTION_WEIGHTS to 4dp, and the base
   icw9_seas split-half book reproduces WO-18 `seas_screen_report.json`
   `portfolio.icw9.excess_cagr_vs_spy_mean40` to 1e-6.

Descriptive only (cannot rescue a fail): weight-matched null (20 shuffle
draws scored with the REAL fitted EAR weights held fixed, no refit);
icw9_seas + sue + EAR vs icw9_seas + sue (same split-half method, `sue`
from WO-13 `sue_factor_v2.parquet` sha256 198cef0b..., NaN where undefined);
median daily Spearman correlation of EAR with sue, momentum_12_1, io_gap
(WO-26 `io_gap_factor_v2.parquet`); IC on live rows only; odd/even halves;
IC-offset flips; book-increment LOYO.

### Outcome rule
All 7 gates -> PASS-nomination (next step would be a separate unfitted
2020+ read, not in this order; a pass earns a forward-column proposal only).
Any gate fails -> DEAD; the SUE/PEAD family closes at 2 trials.

### Process
`--validate` mode first (Step 0, PIT assert, label trace, reconciles; no
EAR outcome statistic), then the single scored run. Iteration cap 3, bug
fixes only, each logged in section 3 below. Report JSON:
`final/out/ear/ear_screen_report.json`.

## 2. Results (appended after the scored run; section 1 unchanged since cf8eec7)

**Verdict: DEAD.** Six of the seven gates pass. Gate 4 fails: the book
increment is negative at 20 of the 40 grid offsets. Under the kill rule, the
SUE/PEAD family closes at 2 trials, and revenue surprise (trial 3) is not
run. Report: `final/out/ear/ear_screen_report.json`. Gate A / validate:
`final/out/ear/validate_ear.json`. Build meta: `final/out/ear/build_ear_meta.json`.

### Step 0 (Gate A)
- EDGAR top-up. `final/src/ear/pull_8k_v2topup.py` found 3,600 v2 CIKs
  (2007-2019 tickers) that were not in the WO-5 request list (that list
  recomputes to 3,971 today, vs 3,969 in WO-5's meta, from tickers_master
  drift). It wrote 137,982 rows for 3,505 CIKs to
  `final/data/edgar/8k_item202_v2topup.parquet` (main checkout, gitignored).
  95 CIKs have no 2.02 filing and none returned 404. Pull meta:
  `final/out/ear/8k_item202_v2topup_pull_meta.json`. EDGAR was reachable.
- Merged pool before 2020: 241,940 original 8-K Item 2.02 filings across
  6,619 CIKs (2,507 8-K/A excluded). Every cap150 ticker maps to a CIK
  (0 unmapped).
- Coverage: share of column-c cap150 name-dates with at least one filing in
  the prior 100 trading days.

  | group | coverage | name-dates |
  |---|---|---|
  | v1-present | 94.24% | 6.77M |
  | v1-absent | 91.50% | 2.99M |

  The gap is 2.74pp, so the 10pp check **passes**. The gap stays between
  1.3pp and 3.9pp in every year from 2007 to 2019. Domestic Common Stock:
  94.6% v1 vs 91.9% added. No ADR category is large enough to appear in the
  breakdown.
- Dead name: LEH (CIK 806085, Sharadar ticker LEHMQ) has 17 original 2.02
  filings, 2004-09-21 to 2008-09-10: 2007-03-14, 06-12, 09-18, 12-13, then
  2008-03-18, 06-09, 06-16 (pre-announcement), 09-10. It has 435 v2 cap150
  rows (last one 2008-09-30), and EAR is live on 420 of them.
- Cadence: AAPL (CIK 320193) has 4 filings a year in 2010-2018, in late
  Jan/Apr/Jul/Oct (for example 2010-01-25, 04-20, 07-20, 10-18). 2019 has 5
  because of the 2019-01-02 revenue-guidance 8-K, which by spec counts as
  an event. One hand-traced event, AAPL filed 2007-01-17 after the close,
  recomputed from the raw SEP and SPY.csv closes for 01-12..01-19, gives
  EAR -0.061153, which matches the builder exactly.
- PIT assert: passes on all 8,399,842 live rows. The latest price date used
  is never after t, and filing_date plus 2 market days is never after t.
- Label trace: close[t+40]/open[t+1]-1 recomputed from v2 open/close matches
  `forward_return_tradable_40` on 100% of 9,560,097 cap150 rows whose t+40
  is before 2020 (|diff| < 1e-9).
- Harness reconcile passes: icw8 frozen = 2.8542% = readout. The split-half
  OOS ICs match to 1e-6, and the frozen weight rule reproduces
  PRODUCTION_WEIGHTS to 4dp. The base icw9_seas split-half book gives
  +2.5496%/yr, which reproduces WO-18 `portfolio.icw9` exactly.
- Coverage of the factor itself: EAR is live on 86.1% of cap150 rows (87.3%
  v1-present, 83.2% added). 13.9% are neutral because they have no event in
  the prior 60 days of availability, and 0.03% because the latest event's
  EAR is missing.

### Gates
Universe: 13,241,135 column-c rows. Scored cap150 universe: 3,272 dates.

| # | gate | value | bar | pass |
|---|---|---|---|---|
| 1 | pooled NW(39) rank-IC | mean +0.01235, **t +3.26** | t >= 2.24, sign + | yes |
| 2 | halves | 2007-13 +0.01555 (t +3.06); 2014-19 +0.00863 (t +1.53) | both > 0 | yes |
| 3 | both-sides sector-demeaned t | **+2.79** (factor-only +2.76) | >= 1.0 | yes |
| 4 | book-increment offset flips | **20 / 40** increments <= 0 (min -0.48pp, max +0.45pp) | 0 / 40 | **NO** |
| 5 | max single-year share of sum IC | **27.6%** (2007) | <= 45% | yes |
| 6 | icw9_seas+EAR vs icw9_seas, decile_volq net 15bp, split-half OOS | icw10 **+2.5641%/yr** vs base +2.5496% (increment +0.014pp); null p80 +2.5615%, p50 +2.5503%, real at the 85th pct | > null p80 | yes (barely) |
| 7 | Gate A clean | Step 0, PIT, label trace, reconciles all pass | all | yes |

EAR's split-half fitted t is +3.10 in odd years and +1.41 in even years.
Its OOS weights are 0.135 and 0.040. The composite OOS IC moves from 0.0483
(t 6.90) to 0.0493 (t 6.97). The IC is real and robust (gates 1-3 and 5),
but adding EAR to icw9_seas barely changes the decile book. The +0.014pp
mean increment is noise across offsets, which split 20 up and 20 down.

### Descriptive only (cannot rescue a fail)
- Weight-matched null (real fitted EAR weights, shuffled EAR): p50 +2.4992%,
  p80 +2.5250%, real at the 100th pct. The refit null is tighter against the
  real result than the weight-matched one.
- icw9_seas+sue: +2.5640%/yr. icw9_seas+sue+EAR: +2.6782%/yr, an increment
  of +0.114pp. sue's split-half t is +1.82 / +1.22 (in-sample fits, not a
  trial).
- Median daily Spearman correlations. With neutral zeros included: EAR vs
  sue +0.145, vs momentum_12_1 +0.138, vs io_gap +0.037. Live rows only:
  +0.153, +0.152, +0.041.
- IC on live rows only: +0.01336, t +3.23. Odd/even-year halves: +0.0172 /
  +0.0067, both > 0. Harness IC-offset flips: 0/40.
- Book LOYO (min over dropped years): icw9_seas +1.47% (drop 2009), icw10
  +1.56% (drop 2009).

## 3. Iteration log
1. Scored run 1 (10:53 start): all 7 gates were computed and written, then
   the descriptive block crashed. The io_gap parquet read used a string
   filter bound (`"2019-12-31"`) against a timestamp column (pyarrow
   ArrowNotImplementedError). Fix: filter `date < HOLDOUT` (Timestamp). This
   was a bug fix in descriptive code only.
2. Scored run 2 (after that fix): the full rerun is deterministic. The
   `ic`, `gates`, `verdict` and `portfolio` blocks are byte-identical to
   run 1 (checked by JSON equality before the report was overwritten). The
   descriptive block completed. That makes 2 of the 3 allowed iterations,
   with no change to the definition, window, holding period or sign. The
   `--validate` run preceded both and computed no EAR outcome statistic.
