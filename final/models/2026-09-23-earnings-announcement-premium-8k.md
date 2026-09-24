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

Run 2026-09-23 at 23:20 ET, first run with no fix cycles used. Part 1's sha256
(`a0c5ae02…d3f6ce`) is recorded in the output JSON. Outputs:
`final/out/eap/eap_screen_report.json`, `eap_gateA.json`, `screen_eap.log`,
`pull_8k_item202.log` and `final/data/edgar/8k_item202_pull_meta.json`, all in
the main checkout.

### Verdict: **DEAD** (2 of 7 gates fail)

| gate | result | pass |
|---|---|---|
| T1 pooled raw NW t ≤ −2.64 | IC −0.0065, **t −1.71** | no |
| T1 both halves negative | odd −0.0091 (t −1.84), even −0.0034 (t −0.62) | yes |
| T2 both-sides sector-neutral t ≤ −1.0 | IC −0.0063, t −1.82 | yes |
| T3 zero grid sign flips | 0/40; grid means −0.0109 to −0.0020 | yes |
| T6 icw9 net > null p80 | +5.359%/yr vs p80 +5.163% (percentile 1.00) | yes |
| T6 icw9 net > icw8 net | +5.359% vs +5.254%/yr | yes |
| T7 no year > 45% of effect | **2015 = 48.5%** | no |

The 8-K announcement-date version is directionally consistent: negative in both
halves, on every one of the 40 grids, and in both sector-neutral forms. It is
also about 4.6× stronger than the filing-date version on the same rows. But it
does not reach the family-corrected bar, and its effect is concentrated in one
year. This form of the earnings-timing family is closed. There are no variants,
and the trial count is spent (6/6).

### Data and Gate A

- The pull uses `data.sec.gov/submissions` for 3,969 universe CIKs. It returned
  207,736 Item-2.02 rows (8-K and 8-K/A) from 3,945 CIKs, covering 2004-08-23 to
  2026-09-23. 24 mapped CIKs had zero 2.02s; there were 0 404s. The signal uses
  205,771 original 8-Ks from 3,944 CIKs; 1,965 8-K/A are excluded.
- EFTS cross-check: 10 of 10 sampled accessions were found by full-text search,
  and each had `2.02` in its items.
- AAPL FY2012 2.02 dates are 2012-01-24, 04-24, 07-24 and 10-25, all present.
  The signal is E = 2013-01-22 at 2013-01-02, 12 trading days. The day after the
  2013-01-23 2.02, E jumps to 2013-04-23. The asserts pass.
- Dead companies:
  - LEHMQ: 18 2.02s, 2004-09-21 to 2008-09-10, with 954 signal rows.
  - MER: 18.
  - CFC: 61.
  - WAMUQ: 50. Its CIK kept filing after the estate emerged, but the panel ends
    on 2008-10-30.
- Cadence, over issuer-years 2007-2019: the median is **4.0** filings a year
  (p10 4, p90 5, mean 4.22). 70.8% of issuer-years have exactly 4.
- Acceptance time, from UTC converted to ET:
  - 37.2% of filings are accepted after 16:00 ET, 40.8% before 09:30, and 22.0%
    during the session.
  - 4.2% are accepted after 17:30, and EDGAR already gives those the next day's
    `filing_date` (5.6% of rows have a filing date different from the acceptance
    date).
  - So an after-close filing on day t enters row t only. The tradable label
    enters at open[t+1], so nothing is used before it could be traded.
- Distribution on cap150 nomination rows: median 34 trading days, p10 8, p90 62,
  and 60.1% ≤ 40, all as predicted. The maximum is 253. 5.8% are > 70, where a
  firm skipped or moved a quarter.
- Coverage on cap150 rows is 95.1% overall and rises steadily from 93.7% in 2007
  to 95.9% in 2019.

### Test numbers

1. **IC** raw −0.0065 (NW t −1.71, n = 3,272 dates). Beta-adjusted −0.0049
   (t −1.23). Halves as in the table.
2. **Sector-neutral.** Both-sides −0.0063 (t −1.82; odd t −1.25, even t −1.43).
   The factor-only `neutralize_on_sector` form gives −0.0085 (t −2.48). As in
   the insider work, the factor-only form overstates the result, here by about
   0.66 in t. The both-sides number is the one that counts.
3. **Grid offsets.** 0/40 flips. Every one of the 40 non-overlapping h=40 grids
   has a negative mean IC.
4. **Head-to-head** on 6,331,837 common rows: new −0.0064 (t −1.71) vs
   `days_to_next_filing_seasonal` −0.0014 (t −0.50). The paired daily difference
   has NW t −1.21, so the new column is better but not significantly. The
   average daily rank correlation between the two is +0.33.
5. **Ablation, out of sample.** The harness first reproduced
   `PRODUCTION_WEIGHTS` to a max |dev| of 0.00005.
   - Fit odd, test even: weight on new −0.107; icw9 IC +0.03098 vs icw8 +0.03044
     raw, and +0.03009 vs +0.03049 beta-adjusted.
   - Fit even, test odd: weight −0.032; icw9 +0.04970 vs +0.04959 raw, and
     +0.05013 vs +0.05001 beta-adjusted.

   The raw change is small in both halves, and in one half it reverses on the
   beta-adjusted return.
6. **Portfolio**, `decile_volq`, 40 offsets, net of 15bp per unit turnover.
   - The ew8 harness gives **+0.04321**, reconciling exactly with
     `correction_variants_report.json`'s `asset_growth_dropped` (+0.04321).
   - icw8 is +5.254%/yr (offset sd 0.25%). icw9, with the full-era weight −0.085
     on the new column, is **+5.359%/yr** (sd 0.36%). Both are positive on 40/40
     offsets.
   - The 20-draw within-date shuffle null gives p50 +5.108% and p80 +5.163%, and
     the real icw9 sits above all 20 draws.
   - The null median is itself 0.15%/yr *below* icw8. Adding a noise column at
     8.5% weight dilutes the book. So the +0.10%/yr over icw8 understates the
     column's own contribution, which is about 0.25%/yr over its null.
7. **LOYO.** Min |t| is **0.95**, reached when 2015 is dropped. 2015 alone
   carries 48.5% of the signed IC sum. The other large years are 2016 (22.5%),
   2014 (19.7%) and 2019 (18.6%). Five years are wrong-signed: 2007, 2010, 2012,
   2017 and 2018. Dropping 2018 raises t to −2.06.

### Reading

The mechanism is real enough to move a portfolio net of costs, beating its own
shuffle null at the 100th percentile of 20 draws. Measuring the announcement
date instead of the filing date did sharpen the signal, from t −0.50 to −1.71
on identical rows. But an IC of about −0.006 with a third of years wrong-signed
and one year carrying half the effect is not a nomination under the rule fixed
before the run. The pass rule was not changed. The portfolio result is recorded
as the most favourable number here, and it is not a reason to promote. This
closes the earnings-timing family at 6/6 trials. Any future test of the EAP
needs a new reason and forward data, not another estimator.
