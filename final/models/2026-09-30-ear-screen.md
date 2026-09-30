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
