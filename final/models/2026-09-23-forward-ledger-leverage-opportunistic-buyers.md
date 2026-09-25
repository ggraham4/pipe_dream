# 2026-09-23 — Forward pre-registration: leverage (icw9) and opportunistic insider buyers

Work orders WO-2 and WO-3 (commissioned by pipe-dream-coo, 2026-09-23).
Branch `worktree-wo23-forward-ledger`.

**Status of this document.** Sections 1–4 are the PRE-REGISTRATION. They
were written and committed before any side-ledger (`prediction_ledger_ext.csv`)
row existed, and before any forward outcome for any record date exists. They
are not edited after that. Section 5 onward (Gate-A checks, first record) is
a results log, appended below the line.

Nothing in this work order computes anything on 2020-01-01 → 2026 panel dates
with realized returns. The hold-out is spent. This is forward-only: no backtest
is run.

---

## 1. What is being tested, and why forward only

Both candidates produced in-era (2007–2019) evidence. In-era re-tests cannot
confirm them, because the evidence came from that era, and 2020–2026 is spent.
So the only unspent test surface left is real calendar time. Both are logged
beside the live composite in a side ledger and judged only on matured forward
dates.

### 1a. WO-2: leverage as a 9th composite factor (model `icw9`)

- **Factor.** `leverage = debtnc / assets`. Both come from the latest SF1 filing
  (ARQ or ARY) as of the panel date, by backward as-of join on the filing
  date. Assets must be > 0. This is exactly `build_new_factors.py`'s
  definition. `record()` recomputes it from `sf1_fundamentals.parquet` for the
  record date, so it does not depend on a stale `new_factors.parquet`.
- **Sign:** −1 (literature: higher leverage → lower subsequent return).
- **Model.** `icw9` is the frozen production ICW8 rule
  (`ic_weighted_composite.py`, `w_k = s_k·max(0.1, |t_k| − 1) / Σ|·|`,
  rank-z per factor, renormalized by the available |weight| per row) extended
  with leverage. Every t is the full nomination-era pooled Spearman IC,
  Newey-West t (lag 39), raw sign, against `forward_return_tradable_40`, cap150,
  2007-01-02 → 2019-12-31. The 8 production t's come from
  `out/reset2026/ic_weighted_composite_report.json` (`per_factor_t.full`).
  Leverage's t comes from `out/reset2026/new_factor_screens_report.json`
  (`leverage.pooled`). That is the same convention, verified in
  `screen_new_factors_and_exponent.py`: same label, NW lag 39, cap150,
  nomination era, not neutralized. **No new screen was run.**

**FROZEN icw9 weights** (constant `ICW9_WEIGHTS` in `prediction_ledger.py`):

| factor | sign | t used | max(0.1,\|t\|−1) | weight |
|---|---|---|---|---|
| momentum_12_1 | +1 | +1.3823 | 0.3823 | **+0.0419** |
| pct_from_high_252 | +1 | +0.8363 | 0.1 (floor) | **+0.0110** |
| volatility_60 | −1 | −0.2096 | 0.1 (floor) | **−0.0110** |
| gross_profitability | +1 | +5.5775 | 4.5775 | **+0.5014** |
| accruals | −1 | −2.2508 | 1.2508 | **−0.1370** |
| net_issuance_pct | −1 | −2.0749 | 1.0749 | **−0.1177** |
| days_to_next_filing_seasonal | −1 | −0.7703 | 0.1 (floor) | **−0.0110** |
| short_interest_days_to_cover | −1 | NaN (no pre-2020 data) | 0.1 (floor) | **−0.0110** |
| **leverage** | −1 | **−2.4442** | 1.4442 | **−0.1582** |

Normalizer Σ = 9.1298. The same rule reproduces the production icw8 weights
(e.g. GP 4.5775 / 7.6856 = 0.5956), and selftest asserts this. Leverage is NOT
added to `composite.FACTOR_COLS` / `FACTOR_SIGNS`, so the v3 equal-weight and
icw8 scores are untouched.

**Comparator:** icw8 = `ic_weighted_composite.PRODUCTION_WEIGHTS`, as already
recorded in `prediction_ledger_v3.csv` (`ic_weighted_score`).

### 1b. WO-3: opportunistic insider buyers (Cohen, Malloy & Pomorski 2012)

Definition fixed from `final/src/insider/posthoc_insider.py`, with the COO
ruling of 2026-09-23 on unclassifiable pairs:

- **Events.** SEC Form 4 (original only, document type `4`, not `4/A`),
  non-derivative transaction code **P** (open-market purchase), reporting owner
  whose relationship includes Officer or Director. Issuer is joined by
  ISSUERCIK → `tickers_master.secfilings` CIK, never by the reported symbol.
  One event per (accession, owner, code). Its transaction date is the earliest
  P transaction in the filing.
- **Routine.** The same (issuer, owner) made an O/D P purchase with a
  transaction date in the same calendar month in EACH of the 3 prior calendar
  years (y−1, y−2, y−3).
- **Classifiable.** The (issuer, owner) pair's first O/D P purchase is at least
  3 calendar years earlier (`year − first_year ≥ 3`). This is posthoc's rule.
- **Opportunistic** = classifiable AND not routine.
- **Unclassifiable** = not classifiable. These are **excluded** from
  `opp_buyers_90` (COO ruling) and counted separately in `unclass_buyers_90`.
- **Causality.** When computing for panel date t, the routine key-set and the
  first-purchase year use only events with `filing_date ≤ t`. posthoc used all
  events, which lets a late-filed old purchase leak in. The live version cannot.
- **Signals, per (t, ticker):**
  - `opp_buyers_90` = number of distinct O/D owners with an opportunistic P
    filing whose **FILING_DATE** ∈ (t−90d, t].
  - `ins_buyers_90` = same, all O/D P filings. This is the plain-count control,
    identical to `build_insider_panel.py`.
  - `unclass_buyers_90` = same, unclassifiable filings.
  - All are 0 when there is no filing, for every CIK-mapped name, and NaN when
    the name has no CIK.
- **Sign:** +1.
- **In-era lead** (post-hoc, NOT a trial): opportunistic events +0.71%
  sector-demeaned 40d return, month-clustered NW t 1.92, n = 10,419.

### 1c. Trial count

- **Leverage.** One in-era screen already spent. It is one of the ≥13
  composite-family nomination-era trials in PREREGISTRATION.md's trial-count
  ledger. This forward test is the confirmation path, not a new in-era trial.
- **Opportunistic buyers.** First registered trial of this form. Insider plain
  counts (`ins_buyers_90` etc.) are a COO-certified dead end at cap150/h40, and
  they are logged only as the control.

## 2. What gets recorded

`prediction_ledger.py record` writes the v3 ledger, unchanged in schema and
skipped if that panel date is already present. It ALSO writes a side ledger,
`final/out/reset2026/prediction_ledger_ext.csv`, with one row per (panel_date,
ticker) for every cap150-eligible name whose composite is finite:

`panel_date, recorded_at, ext_version, ticker, icw9_leverage_score,
icw9_leverage_rank_pct, leverage, opp_buyers_90, ins_buyers_90,
unclass_buyers_90, insider_data_max_filing_date`

`record()` writes the ext rows only if:
- (a) no name on the panel date has a realized 40d outcome (blind);
- (b) that panel date is not already in the ext ledger;
- (c) the v3 row count for that date is unchanged by the call.

The **insider columns are written as NaN** (the icw9 columns are still written)
when the newest filing date in the insider event data is more than 7 calendar
days older than the panel date. `insider_data_max_filing_date` is recorded
either way.

Insider data = bulk SEC Form 345 quarterly sets (`data/edgar/form345/`,
through 2026Q1), plus `final/scripts/edgar_form4_refresh.py`. The refresh reads
EDGAR daily form indexes and each Form 4's XML for later filings, and writes
`out/insider/insider_events_live.parquet`.

## 3. How it is scored (`prediction_ledger.py score`)

For each ext panel date whose 40d outcome has matured (label
`forward_return_tradable_40` from `composite_panel.parquet`, beta-adjusted as
v3 does: `r − beta_252 · SPY_40`), one row goes to
`prediction_ledger_ext_scores.csv`:

- `rho_icw9_raw`, `rho_icw8_raw`, `diff_raw = rho_icw9 − rho_icw8`, plus the
  same three on beta-adjusted returns. Each is a per-date Spearman over names
  where both scores and the return are finite. icw8 comes from v3's
  `ic_weighted_score` for the same date and ticker.
- **Opportunistic buyers, both sides sector-demeaned.** Within the date,
  x_s = x − mean_sector(x) and y_s = r − mean_sector(r), with sector from the
  panel.
  - `opp_spread` = mean(y_s | opp ≥ 1) − mean(y_s | opp = 0)
  - `opp_rho` = Spearman(x_s, y_s)
  - `opp_n_fire`, `opp_fire_rate`
  - The same four for `ins_buyers_90` (the control).

## 4. Decision rule (forward only; FIXED)

- **Qualifying dates.** Selection is mechanical. Take the first ext record date.
  Then add, greedily, each next ext record date that is at least 40 trading days
  after the previously selected one. The decision is made at the first moment 6
  selected dates have matured, using exactly those 6. Reads before that are
  descriptive only.
- **Minimum firing (opp only).** A selected date with fewer than 10 names at
  `opp_buyers_90 ≥ 1`, or with insider columns withheld as stale, does not
  count for WO-3. The next qualifying date replaces it. The WO-2 read is
  unaffected.
- **Leverage (WO-2).**
  - KILL: mean over the 6 of `diff_raw` ≤ 0.
  - SUCCESS: mean `diff_raw` > 0 AND `diff_raw` > 0 on ≥ 4 of 6.
  - SUCCESS is a nomination to Gabe, not a promotion. The beta-adjusted
    difference is reported alongside and does not decide.
- **Opportunistic buyers (WO-3).**
  - KILL: mean over the 6 of `opp_spread` ≤ 0.
  - SUCCESS: `opp_spread` > 0 on ≥ 4 of 6 AND mean `opp_spread` > mean
    `ins_spread` (beats the plain-count control).
  - Anything between KILL and SUCCESS is reported as INCONCLUSIVE and is not
    promoted.
- **Iteration cap.** 3 fix-and-rerun cycles, on the CODE only. The decision
  rule and the frozen weights do not change.

---

## 5. Results log (appended after the pre-registration was committed)

The pre-registration above (sections 1–4) was committed at `a98a28d` and pushed
to `origin/worktree-wo23-forward-ledger`. That happened before any
`prediction_ledger_ext.csv` row existed.

### 5a. Selftest (`prediction_ledger.py selftest`, date 2026-09-23)

All checks PASS. They check the scoring logic on nomination-era date 2015-06-15;
nothing on 2020+ is touched.

- The icw9 weights reproduce from `ICW9_T_USED` under the rule. The same rule
  also reproduces the production icw8 `PRODUCTION_WEIGHTS`.
- Leverage recomputed from SF1 matches `new_factors.parquet` on 100% of 2,180
  names. Coverage is 79.1%.
- Side-ledger icw8 rho = +0.063777. This equals v3 `_score_frame`
  `rank_ic_raw_ic_weighted` and `scipy.stats.spearmanr` to 1e-12.
- Canary: permuting the returns moves the rho.
- `ins_buyers_90` from the new causal code equals
  `insider_features.parquet`'s column on all 2,180/2,180 names (fire rate
  17.75%). This checks the window, the CIK join and the dtypes.
- **Hand counts** come straight from the raw 2015 SEC zip TSVs, via a separate
  code path that does not use `insider_events.parquet` or `opportunistic.py`.
  opp/ins/unclassifiable:
  - ABCB (CIK 351569): 1/3/2. This one exercises the unclassifiable exclusion.
  - MAIN (CIK 1396440): 10/13/3. Monthly buyers: in Apr 2015 an owner is
    routine, and in May 2015 the same owner is opportunistic because they missed
    May in one of 2012–2014.

  Both equal the ledger values.
- The one date's descriptive numbers are not evidence, just a scale reference:
  rho icw9 +0.0504 vs icw8 +0.0638; opp fire rate 6.7% (144 names) vs
  ins 17.9%.

### 5b. Gate A: Dimon's JPM buy (filed 2016-02-11)

Accession 0001225208-16-026145 records Jamie Dimon (owner CIK 1195345) buying
JPM (CIK 19617): transaction 2016-02-11, filed 2016-02-11, $26.59M.
**OPPORTUNISTIC.**
- Classifiable: his first O/D purchase at JPM is a 2007-09-04 transaction,
  late-filed 2011-07-07. Even without it, his next purchase is from 2008-10, and
  2016 − 2008 ≥ 3.
- Not routine: he made no February purchase in 2015, 2014 or 2013. His prior
  purchases were Oct 2008, Jan 2009, Jul 2012 and Oct 2015.
- On 2016-02-12, JPM had `opp_buyers_90` = 2: Dimon, plus director 1185064
  (purchases 2016-01-15 and 2016-02-04, none in Jan/Feb 2013–2015 for either
  month).

### 5c. Live refresh validation, and a bug in the bulk events

`edgar_form4_refresh.py --validate` was run on 2026-03-02, plus the part of
2026-03-03 already fetched. That is 1,490 filings, 320 P/S owner-code rows. It
matched the bulk 2026q1 set exactly on:
- row set (0 rows only in live, 0 only in bulk);
- issuer CIK, is_od, filing date: 100%;
- value: 100% within 1%.

`trans_date` matched on only 94.7%. All 17 mismatches are code S, and the live
date is the earlier one. **The cause is a bug in `build_insider_panel.py`:** it
takes `min` of TRANS_DATE while it is still a `DD-MON-YYYY` string, so the
minimum is lexicographic by day-of-month. For example, "02-MAR-2026" sorts
before "26-FEB-2026". The live parser takes the true earliest date.

It only matters when a single filing's transactions span dates. For the routine
test it matters only when they span a month boundary, and the affected rows in
this sample were all sells. The effect on historical P classification is
therefore expected to be small, but it is not measured. It is **not** fixed
here: fixing it means rebuilding the bulk events, which would change the data
the in-era lead was measured on. It is flagged for the insider workstream's
owner. Going forward, live events use the correct date and bulk events keep the
string-min date.

### 5d. Live refresh coverage

`edgar_form4_refresh.py` finished all 126 business-day indexes from 2026-04-01
to 2026-09-23, with no gaps, and fetched 51,950 in-universe Form 4 filings. That
produced 18,270 P/S owner-code rows in `out/insider/insider_events_live.parquet`,
with filing dates 2026-04-01 to 2026-09-23.

Two operational notes:
- EDGAR answers **403, not 404**, for a daily index that does not exist. The
  first case was form.20260619.idx, for Juneteenth. The script now treats that
  as a holiday.
- Throughput drops sharply while the Mac idles, so run it under `caffeinate`.

### 5e. First blind ext record: panel_date 2026-09-08 (run 2026-09-24)

All three blind conditions held:
- 0 of 2,214 names had a realized 40d outcome.
- The newest insider filing on disk is 2026-09-23, which is ≥ the panel date, so
  the insider data is not stale. The causal cut still uses only filings dated on
  or before 2026-09-08.
- The v3 ledger was unchanged: 2,215 lines, md5 `84e42f49…` before and after.
  The guard logged "NOT re-appending".

Output: 2,214 rows in `prediction_ledger_ext.csv`, `ext_version`
`ext1_icw9lev_oppbuy_2026-09-23`.
- Leverage coverage 83.1%; icw9 score finite for 100%.
- `insider_data_max_filing_date` 2026-09-23.

**Fire rates on 2026-09-08:**

| signal | fire rate | names |
|---|---|---|
| `opp_buyers_90` ≥ 1 | 4.83% | 107 (clears the registered minimum of 10) |
| `ins_buyers_90` ≥ 1 | 13.6% | — |
| `unclass_buyers_90` ≥ 1 | 9.9% | — |

For comparison, `ins_buyers_90` fired 19.7% of the time in-era (17.75% on the
2015-06-15 selftest date), and opp fired 6.7% on that date. Both are lower now.
This is plausibly seasonal: mid-quarter blackout windows. It is not
investigated.

**Top 5 by `opp_buyers_90`.** Ties are broken by `ins_buyers_90`. All filings
come from the live refresh.

| ticker | opp | ins | unclass | opportunistic owner filings in (06-10, 09-08] |
|---|---|---|---|---|
| ELAN | 3 | 5 | 2 | directors 1374175 (filed 08-10), 1566340 (08-13), 1352090 (08-21, $0.94M) |
| MTDR | 3 | 5 | 2 | 1540655 (Dir+Off; 5 filings 06-11 → 08-28), 1688490 (06-17), 1934692 (08-12) |
| AMRC | 3 | 4 | 1 | 1496665 (Dir/Off/10%; 4 filings 08-11 → 09-01), 1496494 and 1633385 (08-26) |
| CHCO | 3 | 4 | 1 | directors 1234850, 1880770, 1730666 (all 07-21) |
| EMBC | 3 | 4 | 1 | 1910501, 1784562, 1910621 (all 08-13) |

**Two filings hand-verified on EDGAR.** Each was fetched directly from
`sec.gov/Archives`, and the raw XML fields were read:
1. **ELAN**, accession 0001352090-26-000006.
   - Filing: FILED AS OF 20260821; documentType 4; issuerCik 0001739104 (ELAN);
     owner Kurzius Lawrence Erik (CIK 1352090); isDirector true; code P.
   - Classification: his prior O/D purchases at ELAN are 2018-09, 2025-03 and
     2025-12. First purchase is 2018 (≥ 3 years), so classifiable. No August
     purchase in 2023–2025, so **opportunistic**. ✔
2. **CHCO**, accession 0000726854-26-000155.
   - Filing: FILED AS OF 20260721; documentType 4; issuerCik 0000726854 (CHCO);
     owner FISHER ROBERT D (CIK 1234850); isDirector 1; code P.
   - Classification: he is a near-quarterly buyer since 2016, with July purchases
     in 2025 and 2023, but the 2024 purchase was in **August**. So by the
     registered rule he is **opportunistic**. ✔ (matches the code)
   - This is a known edge of the CMP definition: a plan-like buyer who slips one
     month in one year reads as opportunistic. It is recorded here and not
     changed; the rule is frozen.

### 5f. Adding record dates going forward (options for Gabe; cadence is his call)

The order matters. Each step feeds the next:
1. Gabe's panel refresh, which updates `composite_panel.parquet`, the SF1
   fundamentals and `beta_feature.parquet`.
2. `caffeinate -i /opt/anaconda3/envs/pipe_dream/bin/python3.11 /Users/ggraham/pipe_dream/final/scripts/edgar_form4_refresh.py`
   - Resumable and incremental. It starts from the bulk data's end and skips
     index days it has already done.
   - Time: about 3–5 minutes per new business day of filings.
3. `/opt/anaconda3/envs/pipe_dream/bin/python3.11 <repo>/final/src/reset2026/prediction_ledger.py record`
   - It refuses to record a matured date.
   - It skips a date that is already recorded.
   - It writes NaN insider columns if the Form 4 data is more than 7 days stale.
4. Any time: `... prediction_ledger.py score`, to score both ledgers' matured
   dates.

Cadence options:
- **(a) Every 40 trading days.** About 8 weeks. Every date qualifies under
  section 4, so the 6 needed dates take about 1 year.
- **(b) Monthly.** Only every second date qualifies. Descriptive reads are
  denser, but the decision date doesn't move.
- **(c) Whenever the panel is refreshed anyway.** The greedy ≥ 40-trading-day
  selection in section 4 keeps any cadence honest.

Under any option the first matured date is 2026-09-08, around 2026-11-03.

## Implementation fix 2026-09-24: TRANS_DATE min (WO-8)

This fixes the bug described in section 5c. It is an implementation fix. The
definition is unchanged, and it is not a new trial.

**The bug.** `build_insider_panel.load_events()` ran
`groupby(["ACCESSION_NUMBER","TRANS_CODE"]).agg(trans_date=("TRANS_DATE","min"))`
while TRANS_DATE was still a `DD-MON-YYYY` string. The minimum was therefore
lexicographic by day of month. For example, "04-MAR-2008" sorted before
"11-FEB-2008". `edgar_form4_refresh.py` already took the true minimum, so the
bulk events and the live events were on different bases.

**The fix.** TRANS_DATE is now parsed with
`pd.to_datetime(..., format="%d-%b-%Y", errors="coerce")` before the groupby.
Nothing else changed. `out/insider/insider_events.parquet` was regenerated with
an atomic write. The old file was kept as
`out/insider/insider_events_prefix_2026-09-24.parquet`. `insider_features.parquet`
was **not** rebuilt, and its sha1 is unchanged. Its columns are keyed on
filing_date and don't read trans_date.

**What changed in the events file** (1,456,667 rows; row set and every other
column are identical):
- 25,081 rows (1.72%) have a new trans_date. These are 17,620 of the 217,778
  multi-date (accession, code) groups, which is 8.09%.
  - The "5.3%" in section 5c was the share of all rows on one day's sample
    (17 of 320). It was not a share of multi-date filings.
- The fixed date is always earlier than the old one, and every change moves the
  year-month. Because of that, every changed row can matter to the routine test.
  3,237 of the changed rows also change year.
- By code: 13,246 S rows and 11,835 P rows changed. Of the 326,004 O/D P rows,
  5,293 changed.
- Three accessions were checked by hand against the raw zips. Each matches the
  true minimum:
  - 0001181431-08-031743: 04-MAR-2008 → 11-FEB-2008
  - 0000712534-17-000046: 01-FEB-2017 → 31-JAN-2017
  - 0001144204-09-011901: 02-MAR-2009 → 27-FEB-2009
- Known residual: 3 changed rows now take a mistyped raw year as their minimum,
  for example "08-MAY-0013". These come from the SEC data, not from this fix. We
  left them alone.

**Effect on the 2026-09-08 blind record: zero flips.**
- Using the old events, the classifier reproduces the recorded
  `opp_buyers_90`, `ins_buyers_90` and `unclass_buyers_90` exactly for all
  2,214 tickers.
- Using the fixed events:
  - In-window O/D P events: 615. Opportunistic 180 → 180, routine 19 → 19,
    unclassifiable 416 → 416. No event changed class.
  - Owner-issuer pairs in the window: 529. Opportunistic 146, routine 18,
    unclassifiable 365. None flipped.
  - Tickers whose count changed: 0 for each of opp, ins and unclass. Fire
    counts: opp 107, ins 301, unclass 219, the same before and after.
- The reason: every event in the 90-day window is a live-refresh event, and
  those already had the correct date. The fix only moves the historical key set
  that the routine and classifiable tests read. For this cross-section, none of
  those moves hit a month that decides a result.

**Bulk vs live agreement on trans_date.** This compares the
`--validate` sample, 320 overlapping rows, with no re-fetch.
- Before the fix: 94.69% (17 mismatches).
- After the fix: 100.00% (0 mismatches).
- The full live file (filed 2026-04-01 onward) has no accessions in common with
  the bulk data (which ends at 2026q1), so no other comparison is possible.

**Status of the ledger.**
- The 2026-09-08 record stands as recorded. It was not rewritten, and there are
  no flips for the evaluator to account for.
- The fix applies from the next record date. From then on, bulk and live
  events are on the same basis.

**For the insider workstream (not acted on here).** Across the full history,
classifying every O/D P event filed on or before 2026-09-08 with the old dates
versus the fixed dates flips 1,185 of 327,456 events (0.36%):
- opportunistic → routine: 243
- opportunistic → unclassifiable: 106
- routine → opportunistic: 332
- unclassifiable → opportunistic: 495

`posthoc_insider.py` classifies on trans_date from the same events file. The
in-era opportunistic-buyer lead in `2026-09-23-insider-congress-results.md` was
measured on the old dates. Re-running that would be the insider owner's call
(and the COO's). This fix does not re-run it.
