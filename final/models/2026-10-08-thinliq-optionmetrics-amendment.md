# WO-52: thin-liquidity probe on OptionMetrics (amendment to the WO-37 pre-registration)

Date: 2026-10-08. Commissioned by COO (WO-52, Gabe: "Proceed with all").
Branch `wo52-optionm-thinliq`. Status: **amendment, written before any
real-label number exists.** It changes the data source of
`final/models/2026-10-01-thin-liquidity-prereg.md` (WO-37) and nothing about
its hypothesis, construction, null, bars or verdict rules. Everything not
named here is as in that doc.

## 0. Why

WO-38, the real run of the WO-37 pre-registration, was BLOCKED. The Alpha
Vantage (AV) store has thin-slice chains on 9 of 133 window dates, and the gate
needs at least 120. OptionMetrics IvyDB US (WRDS `optionm`, 1996 to 2025-08,
dead names included) covers every listed US equity option, so it should
clear the gate. This doc fixes how before any outcome is computed.

## 1. Source and pull

- **Option quotes:** `optionm.opprcd{YYYY}`, 2008 to 2018. There is one query
  per entry date, and dates are read in year order.
- **Entry dates:** the 133 window dates of the WO-37 grid. These are the
  `date=*.parquet` names in `alphavantage_full/options/monthly/` from
  2008-01-02 to 2018-12-19. The grid is reused as listed, not rebuilt.
- **Server-side filter:**
  - `date` is the entry date;
  - `ss_flag = '0'` (standard settlement);
  - `contract_size = 100`;
  - `exdate > date`;
  - the security is not an index (`securd.issue_type` 'A') or an ETF ('%').
- **What the filter does not drop:**
  - Both calls and puts, and all expiries and strikes, are kept. There is
    **no DTE or delta band**. The pre-registered `opt_cw_spread` uses all
    expiries and matched strikes, and its IV and delta are recomputed (see
    section 2). A server-side band would change the signal, so the pre-reg
    wins over the order's "filter by DTE and delta bands" wording.
  - Common stock and ADRs are not cut down to the thin slice on the server.
    The slice can only be cut after linking, and Arm 1's `--phase2` also
    computes the same-date cap2000 figure (descriptive).
- **No option path to expiry is pulled.** Arm 2 settles on Sharadar closes
  (`run_wo_o1.settle`), exactly as pre-registered.
- **Underlying prices:** `optionm.secprd{YYYY}` close on the entry dates, for
  the same secids. They are used only for the identity check (section 3).
- **Storage:** parquet only, under `/Users/ggraham/pipe_dream/final/data/wrds/optionm/`:
  - raw: `opprcd/date=YYYY-MM-DD.parquet` and `secprd.parquet`;
  - the AV-shaped store the harness reads: `av_shaped/options/monthly/date=*.parquet`;
  - the pull log: `av_shaped/calls.parquet`.
- **Nothing from 2019 on is pulled or read.**

## 2. Field mapping (AV store column <- OptionMetrics)

| AV-shaped column | OptionMetrics | Note |
|---|---|---|
| `sharadar_ticker` | secid -> permno (`wrdsapps` `opcrsphist`, sdate <= d <= edate) -> Sharadar ticker (WO-51 `link/permno_sharadar.parquet`, valid_from <= d <= valid_to) | point in time on d; WO-47 ticker-reuse segments are respected because the crosswalk is keyed by Sharadar ticker segment |
| `av_symbol` | `str(int(secid))` | the identity tie-break key in `av_keep` |
| `expiration` | `exdate` | pre-2015 standard monthlies list on the Saturday, which `accepted_expiries` accepts |
| `strike` | `strike_price / 1000` | OptionMetrics stores strike x 1000 |
| `type` | `cp_flag` C/P -> call/put | |
| `bid`, `ask` | `best_bid`, `best_offer` | end-of-day best quotes |
| `volume` | `volume` | that day's contracts |
| `open_interest` | `open_interest` | OptionMetrics lags OI by one day after 2000-11-28, so this is the prior close, the same as AV's |
| `bid_size`, `ask_size` | none; set to 0 | OptionMetrics has no sizes (section 5) |
| `last`, `mark` | NaN, mid | not read by either arm |
| `closeunadj` | Sharadar `closeunadj` on d (`downcap_universe_v2`) | the spot that `convert_av` uses for the IV solve, as for AV |
| `om_iv`, `om_delta` | `impl_volatility`, `delta` | carried for a cross-check only; **not used by either arm** |

`impl_volatility` and `delta` are not used for the signal or for put
selection. `convert_av` (imported unchanged) recomputes IV and delta by
Black-Scholes on the bid/ask mid with the Sharadar spot and the 3-month bill,
exactly as for AV. That keeps `opt_cw_spread` and the 0.30-delta pick as
pre-registered. A vendor-IV version of the signal is **not** computed, so it
adds no trial.

## 3. Pull log and coverage gate (what counts as terminal)

There is one log row per (entry date, thin or cap2000 Sharadar name). The
statuses map onto the WO-37 gate like this:

| Situation on date d | Status | Terminal for the gate? |
|---|---|---|
| No permno for the Sharadar ticker on d in the WO-51 crosswalk | `unlinked` | **no** (counts against the 99%) |
| Permno found, but no OptionMetrics secid links to it on d | `no_data` | yes (no listed options) |
| Secid found, but no rows on d after the filter | `no_data` | yes |
| Secid found with rows | `ok` | yes |

- **Why `unlinked` is not terminal.** It means the link failed, not that the
  name has no options. Counting it as terminal would make the gate pass
  trivially.
- **`ok` rows carry:** `identity = 'verified'`, `spot_parity` = the
  OptionMetrics secprd close on d, `closeunadj` = Sharadar's, and
  `symbol` = the secid.
- **Identity filter.** The pre-registered `av_keep` (imported unchanged) then
  keeps a chain only when `|secprd close / Sharadar closeunadj - 1| < 5%`.
  When two Sharadar tickers claim one secid on a date, the closer one wins.
- **No secprd close.** Such a chain is `unverified` with `symbol != ticker`,
  so `av_keep` drops it.
- **Several secids for one permno on d:** the lowest `score` is kept, then
  the secid with the most rows.

The gate itself is unchanged: the thin slice must be at least 99% terminal on
at least 120 of the 133 dates. If it fails, the order stops and reports
BLOCKED with the coverage table, and the gate is not relaxed.

**Presence checks.** These are unchanged: ATPAQ (2012-06-20), SIGM
(2018-06-20), pool integrity, and the dead-vs-listed chain share.
- TXG is outside the window and its thin dates (2024-10 to 2025-12) are not
  pulled. Its check therefore reads "pending" and does not block, as the
  WO-37 code already treats it.
- The link rate and three named link checks (a dead name, a reused ticker
  and a large cap) are reported.

## 4. Stale-quote and richness check (quote side only; runs before Phase 2)

These run on the 9 early AV dates (2008-01-02 to 2008-08-20), where both
sources exist:

1. **Richness ratio.** Contracts are matched on (Sharadar ticker, expiry,
   strike, call/put), with bid > 0 in both sources. Take the median of the
   OptionMetrics mid divided by the AV mid, over thin-slice contracts.
   - **Required: within [0.90, 1.10].**
   - Also reported: the share of matched contracts with identical bid and
     ask, and the same median for cap2000.
2. **Chain share.** Take the OptionMetrics thin-slice share with a kept chain
   on those dates, against AV's 63.4%.
   - **Required: OptionMetrics >= 60%.** OptionMetrics should cover at least
     what AV did.
3. **Stale quotes (descriptive).** For the Arm 2 chosen puts, report the
   share with zero volume on d. Also report the share whose OptionMetrics
   `last_date` (last trade date) is more than 30 days before d.

If check 1 or 2 fails, the run stops before Phase 2 and reports the mismatch.
This is a data check, not an iteration.

## 5. Changes forced by the source

- **No bid sizes.** OptionMetrics has none, so every name-date has
  `sizes_populated = False`. Under the pre-registered rule, unknown size is
  not held against an entry.
  - The fillable set is therefore quoted plus open interest >= 50.
  - The capacity cap is min(10% of OI, that day's volume).
  - The "strict" descriptive variant (size must be populated) is empty by
    construction. This is a fact of the data, not a rule change.
- **Holiday-expiry rule (COO-mandated fix from WO-37).** `run_arm2.build_entries`
  selects expiries with `run_wo_o1.accepted_expiries`: the 3rd Friday, the
  Saturday after it, or, if that Friday is a market holiday, the trading day
  before it.
  - This fix landed on integration with WO-47 (`test_expiry.py`), so it is
    verified here, not re-edited.
  - It matters in-window: on 2008-03-21, Good Friday was the 3rd Friday, and
    OptionMetrics lists that expiry as Saturday 2008-03-22. That is accepted.
- **Harness plumbing.** `final/src/wrds_optionm/run_thinliq_om.py` imports
  `thinliq/tl_common` and repoints its module paths before importing the arms:
  - the store goes to the AV-shaped root;
  - the outputs go to `final/out/thinliq_om/` so the WO-37 AV files are not
    touched;
  - `read_log` reads `calls.parquet` instead of the AV sqlite.
  - No rule function is edited. The guard also requires this amendment doc
    to be tracked in git.

## 6. Unchanged

- **Window:** 133 dates, 2008-01 to 2018-12. There is no 2019+ read and no
  hold-out read.
- **Labels:** `gross_return_40` from `outcome_cache_v2`, with the delisting
  floor.
- **Arm 1:** S1-S8 and K1-K6 exactly as pre-registered.
  - PASS needs NW lag-39 t >= 3.75 AND M >= +1.0% per 40 days, plus the other
    six.
  - Under the null the lag-39 t has sd about 1.5 (D-NWT). The run therefore
    also reports the **null-seed sd** of t and M on the OptionMetrics thin
    slice: `run_arm1 --labels shuffled --seeds 100` (labels permuted within
    date, calibration only).
- **Arm 2:** SURVIVES, DEAD or MIDDLE as pre-registered. It cannot create a
  pass.
- **Also reported:** spreads (median relative spread of the chosen puts, and
  `opt_spread_atm` of the pool, as % of mid) and fill size (capacity).
- **Verdict:** Arm 1's. A KILL certifies thin-liquidity options dead, to be
  reopened only with new data.
- **Trial tally.**
  - Before this run, the options family stood at 20 (26 including WO-36).
  - WO-38 never computed a real-label number, so its two trials were not
    spent.
  - This run adds 2 (Arm 1 and Arm 2), for **22 (28 including WO-36)**.
  - The null calibration, the cap2000 comparison, the terciles and the checks
    in section 4 are descriptive and add none.
- **Iteration cap:** 3. Any spec change after a real-label number exists is
  written in the results file and hash-logged in LEDGER.md before the rerun.
- **Dead ends not touched:**
  - `opt_cw_spread` in the long book (at any weight, or as an exclusion);
  - cash-secured puts on cap2000;
  - long calls and LEAPS;
  - any new option factor.
  Arm 2 is the pre-registered thin-slice put arm, not the cap2000 dead end.

## 7. Phase 1 facts (quotes and presence only, 2026-10-08)

No real-label number has been computed. Every figure below comes from quotes,
links or the universe flags.

**Pull.**
- 133 of 133 entry dates, with about 0.19M to 0.72M contract rows per date
  (2,850 to 3,590 secids).
- `secprd` returned 1.08M rows.
- Wall time was 11 minutes.

**Link rate (`final/out/thinliq_om/link_report.json`).**

| Slice | Name-dates | Linked to a permno | `ok` | `no_data` |
|---|---|---|---|---|
| Thin | 240,454 | 99.77% | 80.5% | 19.3% |
| cap2000 | 152,258 | 99.94% | 98.4% | 1.5% |

- Every `ok` link has `opcrsphist` score 1.
- 99.8% of `ok` chains have the OptionMetrics close within 5% of Sharadar's.

**Named link checks.**
- **ATPAQ on 2012-06-20:** permno 88906, secid 114698, close 4.42 in both
  sources.
- **Reused ticker CB1 vs CB on 2008-01-02:** Chubb Corp (CB1) maps to permno
  59192, secid 103015, close 53.38. ACE (Sharadar CB) maps to permno 79057,
  secid 112254, close 61.04. This is the collision that broke AV symbol
  matching, and it is clean here.
- **AAPL on 2015-06-17:** permno 14593, secid 101594, close 127.30.

**Coverage gate (`final/out/thinliq_om/arrival_gate.json`).** **PASS:
133 of 133 dates**, against the 120 required.
- Thin-slice terminal share: minimum 99.39%, median 99.78%.
- **ATPAQ:** present on its must-date, 100% of its thin dates, and 9 of 9
  early dates.
- **SIGM:** present on its must-date, 100% of its thin dates, and 9 of 9
  early dates.
- **Pool integrity:** 193,038 thin name-dates with a kept chain, 100% of them
  in the panel and 100% in the outcome cache.
- **Dead vs listed chain share:** 80.46% vs 80.47%.
- **TXG:** pending (outside the window).

**Section 4 cross-source check (`final/out/thinliq_om/crosscheck.json`):
PASS.**
- **Richness:** the median OptionMetrics/AV mid ratio is 1.000 (IQR 1.000 to
  1.000) on 557,881 matched thin contracts. 98.8% of them have identical bid
  and ask. On cap2000 the figures are 747,177 contracts and 97.7% identical.
- **Thin kept-chain share on the 9 early dates:** OptionMetrics 64.3%, AV
  62.4%.

**Holiday-expiry rule.** `test_expiry.py` passes. OptionMetrics lists the
March 2008 monthly (Good Friday, 2008-03-21) as 2008-03-22, which
`accepted_expiries` accepts.

## 8. Results

Results are in `final/models/2026-10-08-thinliq-optionmetrics-results.md`, not here. On Gabe's instruction (2026-10-08), git branch creation was classifier-denied, so this amendment was frozen by sha256 plus a timestamp recorded in LEDGER.md and COO.md. The freeze happened before any real-label number was computed. The file was not edited after that. The commit is queued in PUSH-PLAN-wrds-2026-10-08.md for Gabe to push. The run guard checks the frozen sha256 in place of `git ls-files`.
