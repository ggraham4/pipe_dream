# WO-49: opportunistic insider buyers (Cohen, Malloy & Pomorski 2012) on the v2 grid

Commissioned by pipe-dream-coo (work order WO-49). Branch `wo49-opp-insiders`,
based on `origin/integration` 8319e56. Code: `final/src/oppinsider/`
(`build_opp.py` factor build and integrity, `oppinsider.py` gates).
Outputs: `final/out/oppinsider/`.

## 1. PRE-REGISTRATION (frozen before any outcome statistic; nothing in §1 is edited after the results)

**Mechanism.** CMP (2012, JF, "Decoding Inside Information"): insiders who trade
on a fixed calendar ("routine") carry no information. Non-routine
("opportunistic") open-market purchases predict returns (CMP report about
0.8%/month long-short, value-weighted).

**Trial count.** This is trial k = 5 of the insider family. The earlier four
were buyers v1, sellers v1, the post-hoc opportunistic/size exploration, and
WO-4 v2-grid buyers. All four failed. The earlier post-hoc look (ever-cap2000
grid, opportunistic events +0.71% sector-demeaned 40d, NW t 1.92, n = 10,419)
is NOT evidence and selects nothing here.

### 1.1 Factor (frozen, single column, no variants)

`opp_buy_90` = the number of distinct opportunistic insiders with at least one
open-market purchase filed in the trailing 90 calendar days. Sign +1. The value
is 0 where there is none.

Operational definition. This is §1b of
`2026-09-23-forward-ledger-leverage-opportunistic-buyers.md` (the COO-ruled
definition), made strictly causal:

- **Events.** These are rebuilt from the raw Form 345 zips with the imported
  `build_insider_panel.load_events()`, asserted to be 1,456,667 rows. Each
  event is:
  - an original Form 4 (document type `4`);
  - non-derivative code **P**;
  - filed by an owner whose relationship includes Officer or Director;
  - one event per (accession, owner, code), with trans_date the earliest P
    date in the filing.

  Issuer joins on ISSUERCIK → `tickers_master.secfilings` CIK, deduplicated
  with the imported `build_insider_panel_v2grid.cik_map_dedup()`.
- **Valid.** An event is valid if `2006-01-01 ≤ trans_date ≤ filing_date`.
  Invalid events (typo dates such as year 13 or 1990, or a trans date after
  filing) are neither history nor classified. They count as excluded.
- **History of event e.** The valid O/D P events of the same (issuer, owner)
  with `filing_date < e.filing_date`, strictly earlier. This is a subset of
  "filed before the decision date", so it is PIT-safe. Late-filed prior-year
  trades that arrive after e are ignored, which is slightly conservative.
- **Classifiable.** `year(e) − min(year of history) ≥ 3`. Empty history means
  unclassifiable. Unclassifiable insiders are excluded, as CMP do and as the
  COO ruling says.
- **Routine.** The history contains a purchase in calendar month `month(e)`
  in EACH of the years `y−1`, `y−2` and `y−3`.
- **Opportunistic.** Classifiable and not routine.
- **Timing.** A filing on date f counts for panel dates t with
  `f + 1 ≤ t ≤ f + 90` calendar days. The signal is usable the day after the
  filing, never on the filing date. This is implemented as the imported
  `build_insider_panel.window_counts` on `fday + 1`, the union of
  `[f+1, f+91)` intervals per owner.
- **Fill.** A CIK-mapped ticker with no qualifying event gets 0. An unmapped
  ticker gets NaN; there are none on the cap150 grid.
- **10b5-1.** The SEC `AFF10B5ONE` flag first appears in SUBMISSION.tsv in
  2023. It is absent from every in-era file (it is in the 2023q3 header and
  not in 2019q4). The exclusion is therefore not applicable in-era. REMARKS
  are not text-mined; that would be a variant.
- **Known deviations from CMP.**
  - Classification uses P purchases only, not all trades.
  - Classification is per (issuer, owner) and per trade, not per insider at
    the start of the year.
  - Classifiable means first purchase at least 3 years earlier, not a trade in
    each of the 3 prior years.
  - Only Officer/Director owners count; 10%-only owners are excluded.
  - Value weighting is not used (count factor).
- **Mechanical consequence.** The Form 345 data starts in 2006q1, so nothing
  is classifiable before trans-year 2009. The factor is identically 0 in
  2007–2008. Constant dates drop out of the daily Spearman IC (zero variance),
  and in the book a constant column gets rank_z = 0 on every row. Gates 2, 4
  and 5 therefore run on an effective 2009–2019 era.

### 1.2 Universe, label, era

- **Grid.** v2 survivorship-safe down-cap grid, column c (old tickers plus
  added non-SPAC tickers), cap150-eligible. This is
  `model_audit_wo23.load_theo("A", "cap150")` via the WO-48b harness
  (`dropcheck.load("A")`).
- **Label.** `forward_return_tradable_40` (close[t+40]/open[t+1]), h = 40.
- **Era.** 2007-01-02..2019-12-31 only. Every loader asserts
  `max(date) < 2020-01-01` (HOLD-OUT BREACH). No hold-out read.

### 1.3 Gates (all of 1–7 must hold for PASS; a PASS is a nomination only, promotion is Gabe's)

1. Pooled per-date Spearman IC of `opp_buy_90` with the label, Newey-West
   lag 39: **t ≥ +2.58** (Bonferroni k = 5, two-sided 0.05), sign +1.
   Computed with the imported `screen_insider_v2grid.ic_gates` (dates with
   fewer than 20 finite pairs, or zero variance, are dropped).
2. Odd-year and even-year halves both have mean IC > 0.
3. Both-sides sector-demeaned IC t ≥ +1.0. Demean the factor AND the label
   within date × sector (NaN sector → "Unknown"). Factor-only demeaning is
   reported beside it and is not gated.
4. 0/40 grid-offset sign flips: offset means `s.iloc[o::40]` of the daily IC
   series, o = 0..39, all > 0.
5. LOYO. The total summed daily IC is > 0. No calendar year carries more than
   45% of the summed IC. The minimum leave-one-year-out NW t is > 0.
6. Book: icw6 vs icw5_seas.
   - **Base.** icw5_seas = `ic_weighted_composite.PRODUCTION_WEIGHTS_V5_SEAS`.
     Before any insider book number, it must reconcile to the WO-48b D4 arm
     (`final/out/signcheck/drop/parts/real_A.json`, arm_mean40 =
     0.036442521084825354, +3.64%/yr vs SPY, decile_volq, net 15bp, mean of
     40 offsets) to 1e-10. The WO-48b icw9_seas base (0.0348652) is also
     re-asserted. If either fails: stop and report.
   - **icw6 weights.** The five V5 weights are kept byte-exact.
     `w_opp = +max(0.1, |t_opp| − 1) · k`, with
     `k = Σ|V5| / Σ_k max(0.1, |t_k| − 1)` over the five V5 factors.
     - The t_k come from `ic_weighted_composite_report.json`
       `per_factor_t.full`, plus `SEAS_T` for seas.
     - Each `|V5_k| ≈ max(0.1, |t_k| − 1)·k` is asserted to within 2e-4,
       because V9 is rounded to 4 dp.
     - `t_opp` is the gate-1 t (column c, cap150, 2007–19). The weight is
       therefore in-sample, which is stated here.
     - Scoring uses the coverage-aware weighted mean of rank_z
       (`signcheck.score`). Picks use `signcheck.picks_fast` (decile_volq,
       asserted equal to `pool_read.picks_w` by the harness). Chains use
       `drag_decomp.chains` (net 15bp vs SPY, 40 offsets).
   - **Paired increment.** Per offset, icw6 − icw5 (annualised). The
     statistic is its mean over the 40 offsets.
   - **Null.** 100 draws, seeds 49000..49099. Draw s permutes the finite
     `opp_buy_90` values within each date, using
     `screen_insider_v2grid.shuffle_within_date(U, col, 49000 + s)`. The
     shuffled column is re-ranked (rank_z) and given the SAME `w_opp`, not
     the floor weight. The null increment is shuffled-icw6 − icw5, per offset,
     then averaged over the offsets.
   - **Pass** requires both:
     - mean paired increment > the 80th percentile of the 100 null means
       (numpy linear interpolation);
     - at least 26 of 40 offsets with a positive paired increment.

     icw5's sd across the 40 offsets (sd40) is reported beside this. It is
     NOT the bar (Gabe 2026-10-07, small-weight rule). Null draw 0 is rerun
     and must be bit-identical.
7. Gate A (all three):
   - (a) PIT assert. Every event that counts at t was filed before t
     (`f + 1 ≤ t`), and classification uses only strictly earlier filings.
     This is checked by an independent brute-force recompute of
     `opp_buy_90` from the event table on 3,000 (ticker, date) rows: 1,500
     fired rows and 1,500 random mapped rows. Pass = 0 mismatches.
   - (b) Placebo. The seed-49000 shuffle (null draw 0) is run through gate 1.
     Pass = it FAILS gate 1 (t < 2.58).
   - (c) Hand-check. Three named, real opportunistic purchases are each
     classified opportunistic, and the factor steps up on the first panel date
     AFTER the filing date, not on or before it.

**Kill.** If any of gates 1–6 fails, the verdict is KILL. The insider family
is then CLOSED at k = 5 for the composite. It reopens only with a new data
source (e.g. PIT 10b5-1 plan data) or a short-book use with borrow data. No
post-hoc variants: no windows, value weighting, sellers, clusters or CMP-exact
reclassification. Iteration cap: 3 bug-fix cycles, no spec changes.

**Registered secondary (report only; it cannot PASS alone).** This is the
added-tickers-only slice: column-c cap150 tickers not in the old
`composite_panel.parquet` ticker set (column c minus column b), as in WO-4.
Only gates 1–5 (IC) are reported on it. No book is built for the slice.

### 1.4 Integrity results (factor only; no label or return read; run before this section was frozen)

From `build_opp.py` → `final/out/oppinsider/opp_integrity.json`:

- Events: 1,456,667 rows, as asserted. 326,004 O/D P events. 978 have an
  invalid trans_date; 669 of those were filed in 2006.
- Class by filing year:
  - 2006–2008: no opportunistic or routine events. All are unclassifiable
    (18,121 / 24,300 / 29,790).
  - From 2009, the yearly counts are opportunistic 4,055–6,514, routine
    990–1,293 and unclassifiable 7,149–15,325.
- cap150 2007–19 rows, `opp_buy_90` non-null on 100%:

  | slice | opp fire rate | all-buyer fire rate (same +1 shift) |
  |---|---|---|
  | old tickers | 5.6% | 19.7% |
  | added tickers | 7.7% | 24.2% |

  The fire rate by year is 0 in 2007–2008 and 4.1%–9.4% in 2009–2019. The
  assertion `opp_buy_90 ≤` the all-buyer count holds on every row.
- Brute-force PIT recompute: 3,000 rows, 0 mismatches.
- Hand-check (gate 7c, `logs/hand_check.log`):

  | ticker | insider | filed | class | factor on filing date → next panel date |
  |---|---|---|---|---|
  | JPM | James Dimon, Chairman & CEO, $26.6M | 2016-02-11 | opportunistic (prior buys 2007-09, 2008-10, 2009-01, 2012-07, 2015-10; no February) | 1 → 2 on 2016-02-12 |
  | GE | William G. Beattie (director), $10.1M | 2015-02-19 | opportunistic | 0 → 1 on 2015-02-20 |
  | KO | Barry Diller (director), $20.3M | 2012-05-01 (trade 2012-04-27) | opportunistic | 0 → 1 on 2012-05-02 |

  At JPM, another opportunistic insider was already in the window, which is
  why the count goes from 1 to 2.

## 2. Results

(appended after the run, below this line)

Run 2026-10-10 on branch `wo49-opp-insiders` (merged with integration b78ae87),
one clean pass and no bug-fix iterations. Before any compute, the sha256 of
this doc's frozen state (commit 4787c8f) was checked against the frozen copy:
`c2759af1...a479a`, a match. §1 above was not edited. Era 2007-01-03..2019-12-31
only; every loader's hold-out assert passed. Outputs:
`final/out/oppinsider/opp_report.json`, `parts/real.json`,
`parts/null/000-099.json`, `parts/null_recheck.json` and `logs/*.log`.

**Reconciles.** The icw9_seas base is +0.0348652 (matches WO-48b). icw5_seas is
+0.036442521 against the reference 0.036442521084825354 (within 1e-10). The
fast picker equals `picks_w` on all 3,272 dates.

**Verdict: KILL.** Gates 1-6 all fail and gate 7 passes. Under §1.3 the insider
family is now CLOSED at k = 5 for the composite.

| gate | number | bar | result |
|---|---|---|---|
| 1 pooled IC NW t (lag 39) | **−0.818** (mean IC −0.00216, 2,766 dates, effectively 2009-19) | ≥ +2.58 | FAIL |
| 2 odd / even mean IC | odd −0.00819 (t −2.33), even +0.00507 (t +1.38) | both > 0 | FAIL |
| 3 both-sides sector-demeaned t | **−3.44** (factor-only, not gated: +2.52) | ≥ +1.0 | FAIL |
| 4 grid-offset sign flips | 2 of 40 (offset means −0.00410..+0.00045) | 0 | FAIL |
| 5 LOYO | summed IC −5.99 (< 0); max year share 87.7% (2017); min LOYO t −1.56 | sum > 0, share ≤ 45%, min t > 0 | FAIL |
| 6 book icw6 − icw5_seas | **−0.0094 pp/yr**, 18/40 offsets > 0; null p80 −0.0142 pp/yr (100 draws, p50 −0.0210, p95 −0.0094; real beats 95%) | > null p80 AND ≥ 26/40 | FAIL (offset count) |
| 7 Gate A | PIT brute force 0/3,000 mismatches; placebo (seed 49000) t +0.357 (< 2.58, fails as required); hand checks JPM/GE/KO all opportunistic and step up the day after filing | all three | PASS |

Book details: w_opp = +0.01096. This is the floor `max(0.1, |−0.818| − 1) = 0.1`
times k = 0.10965. The icw5_seas sd40 is 0.236 pp/yr (reported only, not the
bar). The null draw 0 rerun was bit-identical.

**Registered secondary (report only, cannot PASS).** Added-tickers slice:
2,983,634 rows, 3,273 tickers, fire rate 7.7%. Pooled t is
**+4.01**; odd and even means are both positive (+0.0072 / +0.0238); 0 offset
flips; max year share 23.1%; min LOYO t +3.24. The both-sides sector-demeaned t
is **−1.77**, which fails gate 3. So the raw added-ticker IC is a sector/size
composition effect, not a within-sector stock-selection signal. Per §1.3 this
selects nothing and reopens nothing.

**Trial count.** Insider family k = 5, all five failed. Family closed for the
composite. It reopens only with a new data source (PIT 10b5-1 plan data) or a
short-book use with borrow data.
