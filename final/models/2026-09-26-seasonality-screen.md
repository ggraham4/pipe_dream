# WO-18: Heston-Sadka return seasonality (`seas`), v2 grid, nomination era

Date: 2026-09-26. Work order WO-18 (COO).
Branch `worktree-agent-ad57ef9f38454d99d`, based on `integration` 2009552.
Code: `final/src/seasonality/`. Outputs: `final/out/seasonality/`.

Status: **PRE-REGISTERED.** This part was committed before any IC or portfolio
number for `seas` was computed. Results are appended below the line at the end.

## Mechanism

Heston & Sadka (2008, JFE), "Seasonality in the cross-section of stock
returns". A stock's return in the same calendar month in past years predicts
its return this month. The proposed mechanisms are recurring flows and
liquidity or information cycles. There is no prior test of this in the
project (COO grep), so this is trial 1 of a new family.

## Definition (frozen; from the work order)

- `seas`: the mean of the stock's monthly total return in calendar month m,
  in years Y−1 through Y−10, where m is the calendar month in which the
  40-trading-day holding window mostly falls. One mapping, no variants.
- At least 5 of the 10 years are required, otherwise NaN.
- Prices dated ≤ t only. Tradable total returns from SEP.
- Sign +1.
- PIT: prices only, on the v2 survivorship-safe grid (dead names included),
  with the SPAC rule applied as WO-6/7/9 did (`downcap_v2_readout.load_column("c")`).

## Screen (frozen; from the work order)

- **Grid.** v2 column c, cap150, h = 40, label `forward_return_tradable_40`,
  nomination era 2007–2019.
- **Reconcile first.** The harness icw8 decile_volq net 15bp over 40 offsets
  must reproduce readout.json cap150 (+0.0285416) to 1e-6, before any `seas`
  number (WO-13's reconciliation value).
- **Trial family.** "return seasonality", NEW, 0 prior trials, this is trial 1,
  **k = 1. Bar: pooled NW(39) IC t ≥ +1.96 in sign +1.**
- **PASS requires ALL of** (the WO-4 stack, as in WO-13):
  1. NW(39) t ≥ +1.96, sign +;
  2. both halves (odd / even years) positive;
  3. both-sides sector-demeaned t ≥ +1.0 (factor-only reported, not gated);
  4. 0/40 grid-offset sign flips;
  5. leave-one-year-out: max single-year share of the summed daily IC ≤ 0.45
     (LOYO NW t reported alongside);
  6. icw9 vs icw8, decile_volq net 15bp, split-half OOS, above the 80th
     percentile of a 20-draw within-date shuffle null of `seas`;
  7. icw9 weights by the frozen rule `w_k = s_k·max(0.1, |t_k|−1)/Σ`; the rule
     must reproduce `PRODUCTION_WEIGHTS` to 4dp (hard assert, checked in
     validation below).
- **Descriptive only:** coverage; median cross-sectional Spearman of `seas`
  with the icw8 score (frozen weights), momentum_12_1 and volatility_60.
- **PASS = nomination only.** The COO recommends a forward column; no in-era
  promotion. **KILL = any gate fails**; the COO certifies the family dead.

Hold-out: rebalance dates 2007-01-02..2019-12-31 only; asserted (no row / label
date ≥ 2020-01-01). Late-2019 dates whose 40d labels run into 2020 are kept
unmasked, per Gabe's ruling as applied in WO-13; the +0.0285416 reconciliation
value includes them. No price dated ≥ 2020-01-01 feeds `seas` (SEP files after
2019-12 are never opened; asserted per file).

## Implementation notes (frozen before any IC)

Choices the spec leaves open, fixed here:

1. **Target-month mapping (the one mapping).** T = t + 28 calendar days
   (≈ 20 trading days, the midpoint of the t+1..t+40 holding window);
   m = month(T), Y = year(T). The lookback years are anchored on Y, not on
   year(t): for a mid-December t the target is January, and January of Y−1
   (the January just past) is used. A calendar offset is used rather than
   the trading calendar so that no date after t is read. Agreement with the
   month of trading day t+20 is reported as a descriptive (validation below).
2. **Monthly total return.** r(i, y, m) = ME(i, y, m) / ME(i, previous
   calendar month) − 1, where ME is ticker i's last finite, positive SEP
   `closeadj` in that calendar month. Both months are required.
3. **Price basis: SEP `closeadj`, not the panel's `close`. Deviation from the
   work order's premise.** The work order says to use "the dividend-adjusted
   closes the panel already uses". The panel does not use them: its `close`
   is split-adjusted only, and the labels exclude dividends
   (DATA-PIPELINE-HANDOFF §6.3). The operative instruction is "monthly total
   return … from SEP", so `seas` uses SEP `closeadj` (split and dividend
   adjusted). The labels are unchanged (close-based `forward_return_tradable_40`).
   Only the factor uses `closeadj`.
4. **1998–2004 SEP pull.** Every local price source starts in 2005-01. With a
   10-year lookback and a 5-of-10 rule, `seas` would be empty for 2007–2009,
   so the registered era would really be 2010–2019. SEP history on the API
   starts in 1998-01 (probed: AAPL 1998-01 present, nothing on 1997-12-01;
   8,075 tickers on 1998-12-01). `pull_sep_pre2005.py` runs the shared puller
   (unedited) with `SHARADAR_PANEL_DIR` redirected to the NEW directory
   `final/data/sharadar/sep_pre2005/` (main checkout, gitignored). Nothing is
   written to `data/sharadar/panel/`, which the live refresh globs.
   Months 1998-01..2004-12 plus 2005-01 as an overlap month.
5. **closeadj basis splice.** `closeadj` is re-based at pull time, so a
   dividend or split between the main SEP pull (2026-09-09) and this pull
   (2026-09-26) rescales the whole pre-2005 history of that ticker. Per
   ticker, g = ME_new(2005-01) / ME_main(2005-01) on the same last-obs date,
   and the pre-2005 closeadj is divided by g. A ticker with rows through
   2004-12 and main rows in 2005-01 but no valid g has its 2004-12 month-end
   dropped (the one boundary return is NaN, not mis-scaled). Ratios within
   one pull are unaffected by the basis.
6. **PIT assert.** The latest month used is month m of year Y−1; its last
   calendar day is asserted < t on every row.
7. **Tickers.** Panel tickers are joined to SEP tickers by name (both are
   Sharadar tickers; dead names carry the vendor's suffix/`Q` symbols). Share
   of panel tickers with SEP rows, old grid vs added, is reported.
8. **Harness.** `screen_insider_v2grid` imported as a module with
   `COL = "seas"`, `SIGN = +1`, `SIGNS9 = SIGNS8 + {seas: +1}`,
   `T_BAR = 1.96`, `OUT_JSON` repointed to the worktree, exactly as
   `sue/screen_sue.py`. `ic_gates(U, xcol="seas")` and `gate6` are called
   explicitly; its `main()` is not used. Gate 6 uses split-half OOS weights
   with the frozen rule, a common icw8-finite universe, and 20 shuffle draws
   (seeds 0..19, full weight refit per draw), as WO-4/WO-13.
9. **Gate 7 check.** `ICW.fit_weights` and `screen_insider.fit_weights`
   applied to the stored full-era t's
   (`out/reset2026/ic_weighted_composite_report.json`, `per_factor_t.full`)
   must equal `PRODUCTION_WEIGHTS` after rounding to 4dp. A descriptive
   full-era icw9 weight for `seas` (its pooled t added to the 8 stored t's)
   is reported after the screen.
10. **Descriptive Spearman.** Per-date Spearman (`screen_insider.daily_corr`,
    min 20 names) of `seas` vs the frozen-PRODUCTION_WEIGHTS icw8 score,
    momentum_12_1 and volatility_60; median over dates.
11. **Iteration cap 3**, bug fixes only, never definition changes.

12. **Input hashes** (recorded in `out/seasonality/build_seas_meta.json`;
    re-hashed at screen start and asserted equal):
    - `composite_panel_v2.parquet` sha256
      `796eb808a414f65435b3f61f05ac7526f581317f4ac76078b2b8758ef4a644f0`
      (mtime 2026-09-25 22:51, the WO-14/16 refresh). This differs from WO-13's
      `4baff1d7…62dc`, but the harness reconcile below reproduces readout.json
      exactly on the same 9,756,141 rows.
    - SEP 2005-01..2019-12 (`data/sharadar/panel/stocks`, one pull 2026-09-09
      00:21–00:49): digest of per-file sha256
      `83e7b89085665b0722d1be1bd41b6f37defb2b285b79777adb3892e15f36ab44`.
    - SEP 1998-01..2005-01 (`data/sharadar/sep_pre2005/stocks`, pulled
      2026-09-26): digest
      `f916e63e7c716276f2454e446caa932a9129bd9dc8e3f933b0c89a1903549f58`.
      84 months 1998-01..2004-12 plus the 2005-01 overlap, 12,885,396 rows.

## Data validation (run before this commit; no IC computed)

Scripts: `final/src/seasonality/pull_sep_pre2005.py`, `build_seas.py`,
`hand_check_seas.py`, `screen_seas.py --validate`. Outputs:
`final/out/seasonality/build_seas_meta.json`, `hand_check_seas.json`,
`validate_seas.json`, `pull_sep_pre2005.log`.

**Harness reconciliation: PASS (hard assert).**

| check | harness | readout.json |
|---|---|---|
| icw8 decile_volq net 15bp, mean of 40 offsets | +0.028541633 | +0.028541633 |
| split-half OOS IC, fit odd → test even | 0.0404111057 | 0.0404111057 |
| split-half OOS IC, fit even → test odd | 0.0553979834 | 0.0553979834 |

**Gate 7 (frozen weight rule): PASS.** `ICW.fit_weights` and
`screen_insider.fit_weights` applied to the stored full-era t's reproduce all
8 `PRODUCTION_WEIGHTS` to 4dp. For example, gross_profitability 0.5956 and
accruals −0.1627.

**Universe.** Column c cap150, 2007–2019: 9,756,141 rows, 6,508 tickers, and
2,987,605 rows on added tickers. These match WO-13.

**SEP join.** 99.94% of old-grid tickers and 99.97% of added tickers have SEP
`closeadj` rows. The three with none are BILL, LMPX and SPT.

**Splice (2005-01 overlap).**
- 6,354 tickers have a same-date overlap ratio g.
- For 96.1% of them, g = 1 to within 1e-4.
- The other 238 (3.9%) show a closeadj basis revision between the two pulls. They are rescaled. The extremes are vendor split revisions: ALSE 0.0002, LDIS 212.
- One boundary month-end (WCRX1) was dropped because it had no valid g.

**Monthly returns.**
- 1,630,818 finite ticker-months.
- The median is +0.02%.
- The 0.1% and 99.9% quantiles are −75% and +193%.

**`seas` distribution** on cap150 rows:
- 1%, 50% and 99% quantiles: −9.6%, +1.2% and +16.4% a month.
- Years used per finite value: median 10, 5th percentile 6.

**Coverage of finite `seas`** among eligible cap150 column-c rows: **79.2%
overall**, 82.2% on the old grid, 72.5% on added tickers.

| year | all | old grid | added |
|---|---|---|---|
| 2007 | 78.4% | 83.1% | 71.4% |
| 2008 | 77.8% | 82.3% | 68.9% |
| 2009 | 80.9% | 84.4% | 71.9% |
| 2010 | 81.8% | 85.5% | 73.9% |
| 2011 | 83.3% | 86.8% | 75.7% |
| 2012 | 84.7% | 87.4% | 78.1% |
| 2013 | 83.6% | 86.1% | 77.9% |
| 2014 | 78.4% | 81.4% | 72.0% |
| 2015 | 76.0% | 79.0% | 68.9% |
| 2016 | 76.4% | 78.5% | 71.0% |
| 2017 | 76.2% | 78.1% | 71.7% |
| 2018 | 75.8% | 78.2% | 69.8% |
| 2019 | 78.1% | 80.0% | 72.8% |

Coverage is flat across the era. The 1998–2004 pull is what makes 2007–2009
usable. Without it, 2007 would need listings from 2002 or earlier inside the
2005+ files, which is impossible. The rows that are missing are young
listings with fewer than 5 same-month years.

**Mapping agreement (descriptive).** month(t + 28 calendar days) equals the
month of trading day t+20 on 96.96% of 3,252 dates. Only dates whose t+20 is
≤ 2019-12-31 are compared, so no 2020 date is read.

**Name checks: PASS.** `hand_check_seas.py` is an independent script that
does not import `build_seas`. It reads the raw SEP month files directly.
Both cases match to 1e-9, with all 10 years finite.
- AAPL, t = 2008-03-14: the target is April, years 1998–2007, so the check
  spans the 2005 splice. g = 1. **seas = +0.0392024061.**
- RSHCQ (RadioShack, delisted 2015), t = 2012-06-15: the target is July,
  years 2002–2011. **seas = +0.0384331185.**
- The PIT assert (latest month used ends before t) holds on all 13,253,466
  panel rows.

---

## Results

(Appended after the screen runs.)
