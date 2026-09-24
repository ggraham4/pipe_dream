# WO-5: the earnings announcement premium, measured with 8-K Item 2.02 dates

2026-09-23. Commissioned by pipe-dream-coo (work order WO-5). Earnings-timing
family, **trial 6 of 6**. Nomination era only (2007-01-02 to 2019-12-31). The
hold-out (2020 onward) is not touched by any return computation in this work.

## Part 1: pre-registration (written before any return was computed)

This part was written and saved before `final/src/eap/screen_eap.py` read any
return column. The screen records this file's sha256 in its output JSON
(`final/out/eap/eap_screen_report.json`, key `prereg_sha256_part1`), hashed over
the text between the Part 1 heading and the Part 2 heading. So an edit made after
the run shows up as a hash mismatch. A git commit timestamp could not be used:
the branch re-base was denied by the permission gate (see Part 2).

### Hypothesis

Stocks earn abnormal returns in the window around scheduled earnings
announcements (Beaver 1968; Frazzini & Lamont 2007; Barber, De George, Lehavy &
Trueman 2013). Round 16 measured this with periodic-filing dates (10-Q/10-K),
which lag the announcement by weeks. Item 2.02 of an 8-K is filed on the
announcement day itself. The question is whether a provably causal
announcement-date estimate built from 8-K 2.02 dates carries the premium where
the filing-date version (`days_to_next_filing_seasonal`, t −2.18 at cap2000 and
−0.77 at cap150) is weak.

### Data

- Source: `data.sec.gov/submissions/CIK##########.json` plus all of its `files`
  pages. Pages whose `filingTo` is before 2004-08-01 are skipped, since item codes
  begin 2004-08-23. Script: `final/scripts/edgar_8k_item202_pull.py`, output
  `final/data/edgar/8k_item202.parquet`.
- Why this source: it gives structured `items`, `filingDate` and
  `acceptanceDateTime` for every filing a CIK ever made, dead issuers included.
  EFTS full-text search has no server-side item filter, returns one hit per
  exhibit, and is capped at 10,000 hits per query. It is used only to cross-check
  a sample of 10 filings.
- CIK universe: every ticker in `composite_panel.parquet`, mapped through
  `tickers_master.secfilings` CIK, the same join as
  `insider/build_insider_panel.py`. Tickers that share a CIK all receive that
  CIK's dates.
- **Forms used by the signal: original `8-K` only.** `8-K/A` amendments are
  excluded, because an amendment a few days later would add a spurious extra
  anniversary.
- A filing counts if its `items` field, split on commas, contains `2.02`.
- The availability date is `filing_date`, EDGAR's filing date. A filing accepted
  after 17:30 ET already carries the next business day's filing date.

### Signal (fixed): `days_to_next_announce_8k_seasonal`, sign −1

For ticker i and panel date t, with F = its 2.02 filing dates (8-K only):

1. Candidates: for each f in F with t − 15 months < f ≤ t, the candidate is
   c = f + 364 calendar days. Only filings on or before t are used. A date filed
   after t is never used.
2. "Quarter already announced" exclusion: candidate c is dropped at t if some
   g in F has c − 45 days ≤ g ≤ t. That means this year's announcement for that
   quarter has already happened, even if it came early. As an interval: c is
   active for t in [f, min(c, g_c)), where g_c is the earliest g in F with
   g ≥ c − 45d.
3. Expected next date E(t) = the minimum active candidate that is > t.
4. Value = trading days from t to E(t), counted as
   `searchsorted(cal, E) − searchsorted(cal, t)` on the trading calendar formed
   by the distinct dates of `composite_panel.parquet`. Only the date column is
   used, not returns. For an E that falls on a non-trading day, searchsorted
   counts the next trading day.
5. NaN if the firm has no 2.02 in (t − 15 months, t], or if no candidate is
   active.

The "actual next date" variant is forbidden and is not computed.

Attaching the signal to the panel uses an explicit `_row` position column, with
the row count and order asserted (the Round 16 merge_asof lesson).

### Era, universe, label

Nomination era 2007-01-02 to 2019-12-31. Universe `eligible_cap150`. Label
`forward_return_tradable_40`. Every script that reads returns asserts
`max(date) < 2020-01-01`. The composite's 8 factors and signs are hardcoded from
`ic_weighted_composite.PRODUCTION_WEIGHTS`, which is the post-2026-09-22 set
without `asset_growth`. That set is asserted equal to
`composite.FACTOR_SIGNS − {asset_growth}`.

### Tests

The machinery is copied from `final/src/insider/screen_insider.py`: per-date
Spearman, NW lag 39, and vectorized rank_z / composite.

1. Pooled daily Spearman IC of the signal against the label with NW t (lag 39).
   Reported raw and beta-adjusted (label − beta_252 × SPY forward 40d), pooled,
   and for odd and even years.
2. Sector-neutral IC, two forms:
   - (a) **both-sides**: both the signal and the label are demeaned within
     (date, sector), then the per-date Spearman is taken.
   - (b) factor-only: `composite.neutralize_on_sector` (OLS on sector dummies)
     residual of the signal, per date, against the raw label.

   Both are reported. The pass rule uses (a).
3. Grid offsets: for each offset o in 0..39, take the dates at positions
   o, o+40, o+80, ... and compute the mean IC and its plain t on that grid. A
   **sign flip** is a grid whose mean IC is > 0, the opposite of the registered
   sign. Report the count out of 40.
4. Head-to-head against `days_to_next_filing_seasonal`. Use rows where both
   columns and the label are non-null. Per date, compute IC(new) − IC(old), then
   the NW t of the mean difference. Negative means the new one is more strongly
   negative, which is better under sign −1. Both ICs are reported on the common
   rows.
5. Composite ablation, icw9 vs icw8. The weight rule is
   w_k = sign_k × max(0.1, |t_k| − 1) / Σ|·|, with t_k each column's pooled NW t.
   Fit on odd years and test on even years, and vice versa. Report the out-of-
   sample pooled IC (raw and beta-adjusted) of icw9 and icw8, and the new
   column's weight. Before fitting, the 8 full-era t's must reproduce
   `PRODUCTION_WEIGHTS` to within 1e-3 per weight, or the run stops.
6. Portfolio plus shuffle null:
   - Construction: `decile_volq` (top 10% within each of 5 volatility_60
     quintiles, inverse-vol weighted, ties broken by the default `np.argsort`,
     identical to `composite.pick_decile_volq`).
   - Returns: `gross_return_40` from `outcome_cache`, over 40 offsets.
   - Net of 15bp per unit turnover using `run_backtest.turnover_net_return`'s
     formula. f_new is tracked per offset exactly as
     `correction_variants.run_offset` does it: the previous set updates only on
     non-empty books, and picks with NaN return are dropped after picking.
   - Metric: annualized mean per-window net excess over SPY (× 252/40), averaged
     over the 40 offsets.
   - icw9 uses the **full-nomination-era weights** (fit rule above, with the new
     column's full-era t), the same status as `PRODUCTION_WEIGHTS`. icw8 uses
     `PRODUCTION_WEIGHTS`.
   - Null: 20 draws. In each draw, the raw new column is permuted within date and
     re-ranked. The icw9 weights stay fixed and only the column is permuted.
   - **Reconciliation gate**: the ew8 book computed by this harness must land
     within ±0.0010 of `correction_variants_report.json`'s
     `asset_growth_dropped` value, 0.04321. If it doesn't, the run stops as a
     harness bug.
7. LOYO on the pooled raw IC: drop each year in turn and report the NW t. Report
   min |t|. A year's **share** = (sum of that year's daily ICs) / (sum of all
   daily ICs), both taken in the registered direction (i.e. × −1). The largest
   share is reported.

### Pass rule (fixed)

NOMINATED only if ALL of the following hold:

- Test 1: pooled raw NW t < 0 and |t| ≥ 2.64 (Bonferroni over 6 family trials,
  two-sided 0.05).
- Test 1: odd-year and even-year mean IC are both < 0.
- Test 2(a): the both-sides sector-neutral t is < 0 and |t| ≥ 1.0.
- Test 3: 0 sign flips out of 40.
- Test 6: real icw9 net > the null's 80th percentile, and real icw9 net > icw8
  net.
- Test 7: no single year's share exceeds 45%.

Anything less is DEAD for this form, with the numbers recorded. A nomination is
not a promotion. Promotion is Gabe's call, and confirmation is forward-only.
Tests 4 and 5 are reported but are not gates. Up to 3 fix-and-rerun cycles are
allowed, for bugs only. The rule above never changes.

### Gate A (name what should be there)

- AAPL's (CIK 320193) FY2012 2.02 dates include 2012-01-24, 2012-04-24,
  2012-07-24 and 2012-10-25.
- Signal checks, written as asserts:
  - AAPL at 2013-01-02 → E = 2013-01-22 (2012-01-24 + 364).
  - On the first panel date after AAPL's January-2013 2.02, E jumps to about
    2013-04-23 (2012-04-24 + 364).
- At least one dead company has 2.02s before its death (Lehman, Wachovia or
  WaMu, whichever is mapped).
- The median issuer has about 4 filings per year (8-K 2.02, issuer-years with at
  least 1 filing, 2007-2019).
- Report the fraction of 2.02 filings accepted after 16:00 ET.
- Distribution: the value should be roughly uniform on [0, ~63]. Expect a median
  in the low 30s and roughly 60–65% of rows ≤ 40. A large miss means
  misalignment.
- Coverage on cap150 rows, by year.

## Part 2: results

(Filled after the run. Nothing above this heading changes after the run.)
