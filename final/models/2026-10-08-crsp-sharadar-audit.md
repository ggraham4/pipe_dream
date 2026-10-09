# WO-51: CRSP vs Sharadar backbone audit + permno crosswalk (Gate A, correctness)

Work order WO-51 from the COO, 2026-10-08 (Gabe: "Proceed with all"). Branch `wo51-crsp-audit`.
Audit, not a signal: **trial count 0**. No hold-out read, no fit, no live change, no re-base.
Code: `final/src/wrds_crsp/`. WRDS data (licensed, parquet only, never committed):
`/Users/ggraham/pipe_dream/final/data/wrds/{crsp,link}/`.

## Phase 1 (done before this pre-registration; identity only, no return statistic)

Phase 1 builds the crosswalk. It computes no outcome statistic, so it ran first; WO-52/WO-53 depend on it.

- Pulls (`pull_links.py`): `crsp.stocknames` (83,280 rows), `crsp.dsedelist` (38,872),
  `crsp.stkdelists` (CIZ v2, 29,833) -> `final/data/wrds/crsp/`;
  `wrdsapps.opcrsphist` (OptionMetrics secid <-> permno, 121,773) and `wrdsapps.ibcrsphist`
  (IBES ticker <-> permno, 37,662) -> `final/data/wrds/link/`.
- Crosswalk (`build_crosswalk.py`) -> `final/data/wrds/link/permno_sharadar.parquet`:
  `permno, permaticker, ticker, valid_from, valid_to, match_method, match_quality, n_candidates`.
  9,052 intervals, 8,831 of 9,266 v2-grid tickers (the rest have no CRSP overlap: OTC/ADR-only/etc.).
  - Match 1, `cusip8`: every historical CUSIP in Sharadar TICKERS `cusips` (first 8) joined to CRSP
    `ncusip` (or header `cusip` if `ncusip` is null). Interval = CRSP name span ∩ Sharadar price span.
    Overlaps resolved by longest total overlap with the Sharadar entity, then ticker agreement, then shrcd 10/11.
  - Match 2, `ticker_date`: only for still-unmapped grid name-dates. CRSP ticker = Sharadar ticker or a
    TICKERS `relatedtickers` entry on that date, unique permno, and the permno-date is not already owned
    by another ticker's cusip match (that rule removed ROSEQ->Rosetta and BVH->BankAtlantic collisions).
  - quality A = cusip8 + ticker agrees somewhere in the interval; B = cusip8 only; C = ticker_date.
  - WO-47 ticker reuse: Sharadar renames the old entity of a reused symbol `S1`, so a grid ticker is one
    permaticker. The 3 real reuses (ADRX, RML, HYAC.U) have their new entity in 2026 only; a `S__post*`
    segment would be matched only on ticker+date inside its own segment. Nothing in 2007-2019 is affected.
  - Fixes during the build (both identity, not returns): ATLS1 carried Atlas America's CUSIP for 2006-09
    (now resolved to its own permno 91376); related-ticker collisions above. Final check: 0 permno-dates
    owned by 2+ tickers among cap2000 name-dates; 0 overlapping intervals within a ticker.
- **Coverage (2007-2019 name-dates mapped to a permno):** cap150 9,758,582 name-dates, **99.82%**
  (lowest year 99.56%, 313 names with some unmapped dates); cap2000 3,802,861, **99.95%** (lowest year 99.84%).
  The largest unmapped cap150 blocks are post-exchange OTC tails CRSP does not carry (FNMA, FMCC
  2010+, ROSEQ, MTLQQ after 2009-06-01, ...). CRSP cannot check those days.
- **Anchors (`anchors.py` -> `final/out/wrds_crsp/anchors.json`): 10/10 map to the expected permno.**

| anchor | Sharadar | permno | crosswalk valid_to | Sharadar last price | CRSP delist (code, dlret) |
|---|---|---|---|---|---|
| AAPL 2008 | AAPL | 14593 | 2024-12-31 | 2026-09-25 | active |
| Lehman | LEHMQ | 80599 | 2008-09-17 | 2008-10-15 | 2008-09-17 (574, -0.60) |
| Bear Stearns | BSC1 | 68304 | 2008-05-30 | 2008-05-30 | 2008-05-30 (231, -0.017) |
| Washington Mutual | WAMUQ | 81593 | 2008-10-30 | 2008-10-30 | none in 2008; same permno continues OTC and as WMIH/COOP |
| old GM | MTLQQ | 12079 | 2009-06-01 | 2011-03-31 | 2009-06-01 (574, -0.187) |
| random dead (seed 51) | HIH1 | 89953 | 2007-07-17 | 2007-07-17 | 2007-07-17 (233) |
| | PLNR | 80012 | 2015-11-27 | 2015-11-27 | 2015-11-27 (233) |
| | RSHCQ | 15560 | 2015-02-02 | 2015-03-19 | 2015-02-02 (574, -0.546) |
| | BTUUQ | 88991 | 2016-04-13 | 2017-04-03 | 2016-04-13 (574, -0.267) |
| | MAXY | 87499 | 2013-08-28 | 2013-08-28 | 2013-08-29 (470) |

Whether each anchor's *terminal return* is handled correctly is a Phase 2/3 question (below).

## Pre-registration for Phases 2 and 3 (hash-frozen before any outcome statistic)

This document was frozen on 2026-10-08 by recording its sha256 and a timestamp in LEDGER.md and COO.md. That happened before any Phase 2 or Phase 3 statistic, and the document is not edited afterwards. Git branch creation was denied by the permission classifier, so on Gabe's instruction the commit is queued in PUSH-PLAN-wrds-2026-10-08.md for him to push. Results go in `final/models/2026-10-08-crsp-sharadar-audit-results.md`.

### Data
- CRSP legacy daily `crsp.dsf` (`pull_dsf.py`): permno, date, ret, retx, prc, openprc, shrout, vol,
  cfacpr for the 8,960 crosswalk permnos, 2007-01-01..2019-12-31 (`dsf_<year>.parquet`), plus
  2020-01-01..2020-03-31 (`dsf_2020.parquet`, **exit legs of labels dated in late 2019 only**; the
  baseline harness's Sharadar labels dated <= 2019-12-31 use the same 2020 Q1 prices; no row dated
  2020+ is scored). Delisting: `crsp.dsedelist`.
- Sharadar side: exactly the WO-6 inputs. Daily prices = split-adjusted OHLC CSVs
  (`scripts/td_data_sharadar` + `td_data_sharadar_downcap_v2`); label = `outcome_cache_v2.parquet`
  `gross_return_40`; panel = `composite_panel_v2.parquet`, column c (v2 grid minus SPACs), 2007-01-02..2019-12-31.
- Harness: `final/src/reset2026/downcap_v2_readout.py` logic (per-date `pick_decile_volq` on the cap150
  tier, 40 offsets, `turnover_net_return` at 15bp, excess vs SPY, annualised 252/40), imported read-only
  from an extracted `git archive origin/integration final/src`. **icw8 weights hard-coded** in the WO-51
  script (the `PRODUCTION_WEIGHTS` dict: mom 0.0497, pfh 0.0130, vol60 -0.0130, gp 0.5956, accruals -0.1627,
  net_iss -0.1399, dtnf -0.0130, si_dtc -0.0130), so the 2026-10-07 icw5_seas switch cannot change the book.

### Return basis (fixed now)
The Sharadar label and daily prices are split-adjusted **price** series (no dividends). So:
- **Primary basis = CRSP `retx`** (price return, split-adjusted), matching Sharadar. A dividend-yield gap
  cannot cause FAIL. Secondary (reported, not judged) = CRSP `ret` (total return).
- Delisting return: `dlret`, falling back to `dlretx`; if both are missing, 0 and counted. Shumway's
  -30% for missing 5xx codes is reported as a sensitivity only.

### Phase 2 (descriptive, but its 10bp share is part of the verdict)
- Name-days: **mapped, cap150-eligible, column-c (ticker, date) 2007-2019** where both a Sharadar
  close-to-close return (consecutive rows of the ticker's OHLC) and CRSP `retx` exist on the same date
  for the mapped permno (and the CRSP previous trading day equals the Sharadar previous row). Secondary
  set: all mapped grid name-days.
- Metrics: share with |retx_crsp - ret_sharadar| < 1bp and < 10bp; secondary the same with `ret`;
  worst 20 discrepancies (name, date, both values, explanation). Report item only (bar not adjusted):
  how many >10bp misses are explained by Sharadar's 3-decimal rounding of adjusted prices.
- Delisting check: every grid name with a CRSP delisting (dlstdt in 2007-2019, dlstcd >= 200) is listed
  with Sharadar's terminal treatment (last Sharadar date, Sharadar return from the CRSP delist date's
  close to Sharadar's last close, i.e. the OTC tail it keeps) against CRSP dlret. WaMu (no CRSP delisting
  in 2008) is stated explicitly.

### Phase 3 (decisive)
- Book: icw8, v2 column c, cap150, net 15bp, h=40, all 40 offsets, 2007-01-02..2019-12-31.
- Run S (Sharadar): the harness as is. **Reconcile gate:** S mean-of-40 excess must equal the WO-6 figure
  +2.85%/yr (readout.json) within 0.1pp; otherwise stop and report (the v2 panel was rebuilt 2026-10-06,
  so bit-exactness is not required). Δ is computed same-run, same picks, either way.
- Run C (CRSP): identical picks per date (same factors, flags and `pick_decile_volq` selection, same
  NaN-label drops as S); only each pick's 40-day gross return is replaced:
  - permno = crosswalk permno of (ticker, t). Window on the **market calendar** (union of Sharadar
    trading dates): entry day e = next trading day after t, exit day x = 40th trading day after t.
  - entry leg = CRSP |prc|/openprc on e; if openprc is missing/0, Sharadar close/open on e (counted).
  - then Π (1 + retx) over CRSP rows of the permno with e < date <= x.
  - If the permno's CRSP rows stop before x: exit at the last CRSP price, and multiply by (1 + dlret) only
    if the permno's delisting date lies in (e, x]. Calendar bounds mean a stock with a price gap (WaMu
    OTC) never runs past x.
  - Fallback to the Sharadar label (counted, reported as a share of pick weight): pick unmapped on t,
    no CRSP row on e, or CRSP label NaN.
- **Primary metric:** Δ = C − S in mean-over-40-offsets excess %/yr vs SPY (SPY identical in both, cancels).
- **PASS (Sharadar OK):** |Δ| <= 0.5pp/yr AND >= 99% of Phase 2 primary name-days agree within 10bp
  AND every named anchor is handled correctly.
- **FAIL (re-base needed):** |Δ| > 0.5pp/yr, OR the 10bp share < 99%, OR any named anchor is mis-handled.
  On FAIL: top 20 (ticker, date) contributors to Δ. No re-base is done here; that is Gabe's call.
- Also reported (not judged): Δ on the `ret` basis; Δ with Shumway -30%; sd/min/max over offsets; LOYO.
- **Kill / iteration cap:** at most 3 fix-and-rerun cycles (bugs in the WO-51 code only; the rules above
  do not change). Then stop and report "no result within budget".
- **Era:** every statistic is 2007-2019; nothing before 2007; no 2020+ dated row is read.
