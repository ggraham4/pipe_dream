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
