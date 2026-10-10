# WO-60 results: bottom-decile hedged SHORT book (composite short book, formal trial 1)

Date: 2026-10-10. Branch `wo60-short-book`. Pre-registration: `final/models/2026-10-10-short-book-prereg.md`, frozen at commit c8f32d1 (sha256 `33fd448c…8b18`) before any outcome was computed.
Trial count for the family: this is formal trial 1. Informal looks already spent: 3 (COO 2026-10-09/10; one of them was hold-out read #24). Fix-and-rerun cycles used: 0 of 3.
**No 2020+ outcome was read.** Signal dates run 2007-01-03..2019-10-24, a cut that is asserted in code before any return column is joined. No price after 2019-12-31 was read.
**No order code exists.** The picks are recommendations only (AGENTS.md #7).

## Verdict: PROMOTE-CANDIDATE (all of S1-S8 pass; no kill fires)

This goes to Gabe as a candidate for a forward paper ledger. There are two caveats he should weigh, set out in "Read this before acting" below:
1. Most of the edge sits before 2011-10.
2. The pre-declared B1 fee map is almost flat.

Primary metric: M = mean annualized net return of the cap2000 short book, hedged with H1 (long the EW eligible cap2000 universe), net of 15bp/side on both legs and B1 borrow fees, averaged over 40 offsets, 2007-2019. **M = +4.50%/yr.** The null is 200 within-date score shuffles: p50 −2.12%, **p80 −2.01%, p95 −1.92%**, max −1.83%.

| Criterion | Value | Result |
|---|---|---|
| S1 M ≥ +3.0%/yr | +4.50% | PASS |
| S2 M under B3 (B1 + 3%/yr) ≥ +1.0% | +1.50% | PASS (thin margin) |
| S3 M > null p95 | +4.50% vs −1.92% | PASS |
| S4 ≥ 36/40 offsets > 0 | 40/40 (worst offset +3.55%) | PASS |
| S5 LOYO min ≥ +1.5% and max year share ≤ 35% | LOYO min +3.74% (drop 2008); max share 23.4% (2008) | PASS |
| S6(a) sector-neutral M > 0 | +2.08% | PASS |
| S6(b) H2 beta-matched SPY book > 0 | +6.06% | PASS |
| S6(c) lower-half-SIR (easy-to-borrow) subset > 0 | +3.19% | PASS |
| S7 bottom 5% / bottom 20% > 0 | +4.72% / +3.92% | PASS |
| S8 Gate A all pass | A1-A5 pass | PASS |
| K1 M ≤ 0 | +4.50% | does not fire |
| K2 S6(c) ≤ 0 | +3.19% | does not fire |
| K3 M ≤ null p80 | +4.50% vs −2.01% | does not fire |
| K4 LOYO min ≤ 0 | +3.74% | does not fire |

## Read this before acting (descriptive, not decisive)

1. **Decay.** Split at 2011-10-01, M is **+9.26%/yr before and +1.70%/yr after**. The in-year means for 2012-2019 are −3.4, +5.2, +5.7, +5.0, −6.5, +5.8, +4.3 and +0.1 (2019 covers signal dates through 10-24 only). The live long book shows the same post-2011 pattern (its post_2011_10 is +0.5%). Under B3 stress, 2008 carries 54.6% of the summed effect. S5 is read on the base book, so it passes, but the stressed book is concentrated.
2. **The B1 tier map is flat, by construction.** The pre-declared spec uses cell medians, fit on Markit 2011-03-21 × cap150 (2,904 of 2,933 names linked). Nine of the 10 DTC-quintile × price<$5 cells have a median of 0.375%/yr, the GC rate. The tiers are 0.50% (q4, <$5) and 0.75% (q5, <$5, also used for missing SI). So the B1 fee for the cap2000 book averages 0.38%/yr, and the "fee > 10%" exclusion never binds.
   - Markit's actual 2011 means are 0.61% for the cap2000 bottom decile and 0.55% for the cap2000 universe.
   - Re-running with a flat 0.61% fee (descriptive) gives M = +4.28%.
   - B3 (+3%/yr on every short) is the real borrow stress, and it leaves +1.50%.
3. **B2 cross-check: B1 is not too low at the median, but there is a tail.** Put-call-parity implied borrow on 11 WO-37 years (2008-2018) for the cap2000 bottom decile:
   - Median by year is between −0.65% and +0.33% (all of it ≤ B1's 0.375%).
   - p75 is 1.2-3.7%; p90 is 3.5-7.8%.
   - 16% of bottom-decile name-dates have B2 > B1 + 3%; 3.8% have B2 > 10%.
   - The bias is upward, from American early exercise.
   - cap150 has a fatter tail: p90 is 6.8-12.7%, and 9.3% of name-dates are above 10%.
4. **Where the return comes from (cap2000, annualized).**
   - Short leg: −2.87%. The bottom decile still rose, about +2.9%/yr total return.
   - H1 universe leg: +8.77%.
   - Costs: −1.02% (one-way turnover 46% per rebalance, about 290%/yr).
   - Borrow: −0.38%.
   - This is relative selection, not shorting losers outright. An unhedged short would have lost money.
5. **Hedge choice.**
   - H2 (SPY × book beta) gives +6.06% and H3 (SPY 1:1) gives +5.08%. Both beat H1 because the EW cap2000 universe outperformed SPY 2007-2019 (a size tilt).
   - H1 isolates selection, and it is the number to believe.
   - The universe leg means holding about 1,100+ names EW. In practice it would be an ETF proxy, which this test did not price.
6. **Concentration and tails.**
   - Worst 40-day period −10.2%; max drawdown −8.1% (mean over offsets), −10.9% (worst offset).
   - Largest single-name 40d loss: PBYI 2014-07 +276% (CRSP-confirmed), then CIEIQ 2011-12 +216%, AIG 2009-07 +187%, SAGE 2017-10 +173%, GEVA 2015-04 +161% (cash merger).
   - Worst names by P&L: STT, ICE, FSLR, VRUS1, CMA, KMR, KKR, LNC, MET, SIVBQ, each about −0.1%/yr.
   - Per-name cap variant (a stock gain is capped at +100%, which is where a short reaches 2× EW; only the 40-day marks exist, so this is a grid-mark approximation): +4.57%.
7. **Thin post-SPAC prints.** ORGO (2019-01-10 open $147 on 4,380 shares, then $7) and PHUN (2019-03) are among the top-20 winning shorts. CRSP confirms both, so A4 passes, but neither would have been borrowable. Removing them gives M = +4.49%, which is immaterial.
8. **Overlaps.**
   - With the live long book (cap150 top decile): 0 rows.
   - With the short-interest top decile: 11.1% of book rows (cap2000), 11.9% (cap150).
   - S6(c) split: low-SIR half +3.19% vs high-SIR half +5.33%. More of the edge is in the hard-to-borrow half, but the easy half is clearly positive.
9. **Excluded (not shortable) share.** 0.19% of cap2000 pick rows (657 with price < $5, 55 with no entry bar, 0 with fee > 10%). For cap150 it is 4.6%.

## Per-year (cap2000, H1, B1; in-year annualized mean, % / yr)

| 2007 | 2008 | 2009 | 2010 | 2011 | 2012 | 2013 | 2014 | 2015 | 2016 | 2017 | 2018 | 2019* |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| +10.6 | +13.4 | +4.4 | +5.0 | +8.0 | −3.4 | +5.2 | +5.7 | +5.0 | −6.5 | +5.8 | +4.3 | +0.1 |

\* 2019 signal dates run to 10-24 only.

## Secondary book: cap150 (reported, not decisive)

| | cap150 |
|---|---|
| M (H1, B1) | +6.76%, 40/40 offsets |
| Null (200 shuffles) | p50 −1.43%, p80 −1.35%, p95 −1.28% (M is far above) |
| B3 stress | +3.76% |
| LOYO min | +5.63% (2009 is the largest year share, 23.2%) |
| S6(a) sector-neutral | +6.24% |
| H2 | +8.09% |
| S6(c) low-SIR | +3.29% |
| 5% / 20% | +6.81% / +5.52% |
| H3 | +7.28% |
| Max drawdown (worst offset) | −9.2% |
| Worst 40-day period | −6.7% |

Per year: +13.8, +16.1, +20.0, +7.9, +10.1, −2.9, +5.3, +5.0, +2.1, −1.0, +4.0, +7.6, −2.4. The cap150 book has a heavier borrow tail (point 3), so its B1 number is the least reliable.

## Borrow model (B1, B2, B3)

**Markit 2011-03-21 sample.** 9,441 rows in total, of which 7,299 are US Equity marketareas. The WO's "~8,581" is not what this table holds. Units are annual fractions: the median fee by DCBS runs 1→0.375%, 2→1.9%, 3→3.5%, 5→8%, 7→14.5%, 10→60%.

| 2011-03-21 | n (with fee) | median | mean | p75 | p90 | DCBS ≥ 3 | fee > 10% |
|---|---|---|---|---|---|---|---|
| cap2000 bottom decile | 104 | 0.375% | 0.61% | 0.375% | 0.50% | 2.9% | 1.0% |
| cap2000 universe | 1,049 | 0.375% | 0.55% | 0.375% | 0.375% | 1.5% | 0.4% |
| cap150 bottom decile | 284 | 0.375% | 1.45% | 0.50% | 3.0% | 10.9% | 2.8% |
| cap150 universe | 2,904 | 0.375% | 0.91% | 0.375% | 0.625% | 4.3% | 1.2% |

**Data substitution (pre-registered, section D).** `short_interest_days_to_cover` in the panel is empty before 2020-04. The SI used here comes from Compustat `comp.sec_shortint`:
- DTC = shortint / CRSP 20d ADV.
- Available at settlement + 8 business days.
- Coverage of the tier universe is 96-99% every year.

## Gate A

- **A1 (look-ahead): PASS.** SI availability equals settlement + 8 business days for every row, and it is attached as-of. seas_live asserts that the last used month ends before t. The panel factors are the live scorer's columns.
- **A2 (pool integrity): PASS.** The v2 grid is used. 0 NaN labels were dropped.
  - Truncated (delisted-in-window) share: 0.58% of book rows vs 0.67% of universe rows.
  - Later delisted by end-2019: 19.7% of book vs 19.3% of universe.
  - Delisting classes in the cap2000 book:
    - merger_2xx: 2,140 rows, −0.13%/yr P&L contribution.
    - drop_5xx: 14 rows, +0.02%/yr.
    - CRSP-active or no-match: 9 rows, +0.02%/yr.
    - unlinked: 0.
    - The CRSP dlret part is small (−0.02%/yr).
  - cap150 adds liquidation_4xx (83 rows) and drop_5xx (49).
- **A3 (placebo, 200 shuffles): PASS.** Null p50 is −2.12%, ≤ 0. Shuffled books lose their cost and borrow drag, as they should.
- **A4 (hand-verify vs CRSP): PASS, 40/40 within 5pp.** The check covered the 20 largest winning short positions and the 20 largest distinct tickers. It includes LEHMQ (−99.8%, CRSP 574), GGP, GTATQ, FMCC, AIG and BSC. No ticker-reuse splice or reverse-split artifact was found. The 5 largest losses also match. ORGO and PHUN are real CRSP prints but untradeable (point 7).
- **A5 (live vs backtest score): PASS.** Max abs score diff 0.0; bottom-decile overlap 100% on 2015-03-19, 2017-06-15 and 2019-03-21, for both tiers. The vectorized picker equals `composite.pick_decile_volq` on 260 checked dates.

## Files

- Code: `final/src/shortbook/`
  - `sb_common.py`, `build_si.py`, `prechecks.py`, `prep.py`, `engine.py`, `check_picker.py`, `gate_a4_markit.py`, `b2_implied_borrow.py`, `descr_extra.py`, `aggregate.py`
- Small outputs: `final/out/shortbook/` (committed)
  - `prechecks.json`, `b1_tiermap.json`, `real_cap2000.json`, `real_cap150.json`, `gate_a4.json`, `markit_2011_fees.json`, `b2_implied_borrow.json`, `descr_extra.json`, `check_picker.json`, `wo60_report.json`
- Large intermediates: the main checkout's `final/out/shortbook/` (gitignored; regenerable by `prep.py`)
  - rows, picks, null draws, SEP cache
- Raw pulls: `final/data/wrds/comp/` (Compustat SI, ccm links) and `final/data/wrds/markit/`, plus `optionm/zerocd_wo60.parquet` (gitignored).

## Suggested next step (for COO and Gabe)

Start a forward paper ledger of the cap2000 bottom-decile short book, H1-hedged, recording picks weekly with no trades. Before any real short, check live borrow on the actual names (broker locate/fee). The 2011 Markit sample is a single date, and the B2 tail shows that 10-16% of names can cost more than B1 + 3%.
