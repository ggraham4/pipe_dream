# WO-61 results: thin-slice book audit (Gate A on the level, spread-based costs)

Plan: `final/models/2026-10-10-thinbook-audit.md`, committed and pushed as bfcaa8d (sha256 `2d601f52…53b9db`)
before any outcome statistic. Every script asserts that hash and the input-file hashes in the plan.
Code: `final/src/thinaudit/`. Outputs: `final/out/thinaudit/*.json`.

- **Trial count 0**, and **0 of 3 fix-and-rerun cycles** used. Three crash fixes came before any result existed:
  1. a string-typed panel `date` column in a parquet filter;
  2. a pandas 3 read-only array;
  3. a run killed before it printed anything.
- **Era:** entry dates 2008-01-02..2018-12-31. Exit legs run to 2019-03 at most, and every CRSP or quote read is
  capped at 2019-03-31.
- The one exception is step A of check 1. It runs WO-6's own 2007-2019 window, only to reproduce WO-6's number.
- Step A uses WO-6's own `load_column`. Its late-2019 entries carry labels whose 40-day exits fall in early 2020,
  exactly as in WO-6's published +2.85. That number is reproduced here, not broken out by year.
- Apart from that, nothing dated 2020+ is read. No hold-out read, and nothing before 2007. Research code only:
  nothing in it can trade.

## Verdict: LEVEL-OK

All four Part-1 checks pass. The thin icw5_seas book on the daily 40-offset grid is **+7.02 %/yr**, which is within
2pp of +8.06.

**Why the level is high.** No artefact explains it. It is located in four pieces:
- **Window choice: +2.6pp.** Dropping 2007 and 2019 accounts for this much. The same years drive every tier, not
  just thin.
- **Universe: +0.55pp.** Thin rather than cap150.
- **Model: +1.6pp.** icw5_seas rather than icw8.
- **Monthly dates: about +1pp.** Sampling on the 133 monthly dates flatters the level against the full daily grid.

**The spread-based costs barely move it:**
- base +7.82 %/yr net vs SPY, against +8.06 at flat 15bp;
- variant +8.32;
- Δ +0.503.

All figures are in %/yr: net of 15bp minus SPY `gross_return_40`, × 252/40, averaged over the offsets, unless
marked otherwise.

## Check 1: reconcile with WO-6's construction. PASS

`check1_reconcile.json`.
- **(a) PASS.** WO-6's slow path (`compute_composite_ic_weighted` + `pick_decile_volq`) on WO-58's pool reproduces
  WO-58's base: 0.0805866644 vs 0.0805866632, an error of 1.2e-9 against a bar of 1e-6. That is float noise between
  the pandas and numpy rank paths.
- **(b) PASS, exact.** Step A reproduces WO-6's cap150 icw8 +2.8541632641% with an error of 0.0. The 2026-10-10
  rebuild of the panel and outcome cache did not move it. cap2000 is +2.8368%, against WO-6's published +2.84.
- **(c) PASS.** The decomposition below changes one variable per step.

**Other checks:**
- **Fast path = slow path.** Picks match on all 133 dates, with 0 mismatched dates, for thin icw5_seas, thin icw8
  and the cap150 icw8 pick sets.
- **Thin flag.** The panel's `eligible_cap150 & ~eligible_cap2000` equals WO-58's `downcap_universe_v2` thin pool
  exactly: 240,372 = 240,372 name-dates, Jaccard 1.0.

| step | universe | model | dates | offsets | level | step Δ |
|---|---|---|---|---|---|---|
| A | cap150 | icw8 | daily 2007-2019 | 40 | +2.85 | |
| B | cap150 | icw8 | daily 2008-2018 | 40 | **+5.45** | **+2.60** |
| C | cap150 | icw8 | 133 monthly | 2 | +5.89 | +0.44 |
| D | thin | icw8 | 133 monthly | 2 | +6.44 | +0.55 |
| E | thin | icw5_seas | 133 monthly | 2 | **+8.06** (= WO-58) | +1.62 |

**The biggest piece is the window (A→B).** cap2000 icw8 also moves, from +2.84 to +4.63. Taking the averages
roughly, the two dropped years (2007 entries, and 2019 entries whose 40-day exits run into early 2020) cost about
−11 %/yr each against SPY. So the down-cap and cap2000 books both look much better on 2008-2018 than on 2007-2019.
This is a fact about the window, not about the thin book. WO-58 inherited it from WO-52's option-store dates.

**Tiers on identical dates:**

| | 133 dates, 2 offsets: icw8 | 133: icw5_seas | daily 2008-18, 40 offsets: icw8 | 40 offsets: icw5_seas |
|---|---|---|---|---|
| cap2000 | +4.38 | +4.74 | +4.63 | +4.51 |
| cap150 | +5.89 | +6.55 | +5.45 | +6.18 |
| thin | +6.44 | +8.06 | +5.72 | **+7.02** |

On 2008-2018 there is a down-cap gradient, which WO-6's 2007-2019 grid did not show:
- under icw8, thin is +1.1 over cap2000;
- under icw5_seas it is +2.5, because seas adds more in thin names (+1.3) than in cap2000 (−0.1).

**NaN seas.** A name with NaN seas is scored on its 4 present factors: Σ w·rank_z / Σ|w| over those factors.
- Pool share with NaN seas is 25.1%. Picks: 27.1% by count, 23.4% by weight. That is only mild over-selection.
- On the 133 dates, the level is +7.50 with NaN seas set to neutral (rank_z 0, |w| kept in the denominator), and
  +8.20 on seas-present names only.
- On the 40-offset grid the same two levels are +6.60 and +7.17.
- The missing-seas handling does not inflate the level.

## Check 2: daily 40-offset grid. PASS (measurement)

`check2_offsets40.json`. 2,769 trading days, 2008-01-02..2018-12-31, at least 69 dates per offset.

| book | mean | sd | min | offsets > 0 | LOYO min (year dropped) |
|---|---|---|---|---|---|
| **thin icw5_seas** | **+7.02** | 0.66 | +5.55 | 40/40 | +5.30 (2009) |
| thin icw8 | +5.72 | 0.51 | +4.69 | 40/40 | +4.03 (2009) |

- **Equal-weight thin pool** (gross, 40 offsets): +1.96 (sd 0.36).
- **Gap to WO-58:** +7.02 is 1.04pp below WO-58's +8.06. The 133 monthly option dates, on 2 offsets, are a
  favourable sample of the daily grid. They are not wrong.

## Check 3: name checks (WO-58 base book, 133 dates). PASS

`check3_names.json`.

**Top 10 contributors.** Together they give 7.9% of the gross level. All 10 are real, normal operating companies:
each one's CRSP-label contribution equals its Sharadar contribution within 0.2%. None has a fallback row, a
spin-off fix row or a reuse suffix, and each maps to a single permno. Contribution figures are pp of the annualised
gross level.

| ticker | name | pick rows | contribution | CRSP / Sharadar | entry price range |
|---|---|---|---|---|---|
| PZZA | Papa John's | 75 | 0.158 | 1.000 | $16-88 |
| TPL | Texas Pacific Land | 60 | 0.156 | 1.000 | $27-195 |
| CROX | Crocs | 70 | 0.140 | 1.000 | $1.9-26 |
| USNA | USANA Health Sciences | 92 | 0.134 | 1.002 | $20-147 |
| SAM | Boston Beer | 63 | 0.134 | 1.000 | $24-161 |
| SAIA | Saia | 86 | 0.133 | 1.000 | $11-77 |
| CYBX | Cyberonics (later acquired) | 46 | 0.132 | 1.000 | $10-73 |
| PETS | PetMed Express | 76 | 0.120 | 1.000 | $9-46 |
| SFLY | Shutterfly (later acquired) | 55 | 0.119 | 1.000 | $6-57 |
| ASPS | Altisource Portfolio | 47 | 0.118 | 1.000 | $17-89 |

TPL has 2 permnos in the crosswalk, but every one of its picks maps to one of them.

**The other name checks:**
- **Delisting path.** 276 pick rows have a window that ends in a delisting (2.8% of weight). Their mean label is
  +2.08% on Sharadar. On the 272 rows where CRSP can be compared, it is +2.14% on Sharadar and +2.52% on CRSP, with
  dlret applied on all 272. The gap is 0.38pp against a 2pp bar: PASS. These are mostly acquisitions, not failures.
- **Names that later delisted** (descriptive). They make up 54.9% of pick rows and 53.1% of weight. Their mean label
  is +2.31%, against +3.21% for the others. No survivorship tilt shows in the picks.
- **Price < $5 at entry.** 7.7% of pick rows and 5.2% of weight. Their mean label is +6.2%, so this tail adds to the
  level and should be watched. It is small.
- **WO-54 spin-off fix.** It touches 3 pick rows. The fixed book is +8.066, a Δ of +0.008pp against a bar of
  ≥ −0.25: PASS.

## Check 4: label basis. PASS

`check4_labels.json`.
- **The label.** WO-58's label is `outcome_cache_v2.gross_return_40` (close[t+40]/open[t+1] − 1, with the delisting
  floor), read by `cb_core.attach_labels`.
- **CRSP rebuild.** Labels are rebuilt from CRSP using WO-51's Phase 3 rule. My re-implementation matches WO-51's
  stored r_C on 20,000 random pick rows to 8.9e-13, with identical fallback flags.
- **Mapping.** 23,530 pick rows. 99.77% are mapped by count (99.83% by weight). Fallback weight: unmapped 0.17%,
  entry leg NaN 0.08%, NaN retx in the window 0.02%.
- **Agreement.** **98.72%** of non-fallback rows agree within 10bp, against a bar of ≥ 98%.
- **Book.** S +8.059, C (CRSP retx) +8.252. **Δ S − C = −0.193pp/yr**, against a bar of |Δ| ≤ 0.5. Sharadar
  understates the book slightly, the same sign WO-51 found at cap150 (−0.17).
- **Dividends** (ret basis, not judged): CRSP total return gives +9.73, a Δ of −1.67, which is the dividend yield
  the price-only label leaves out.

## Part 2: spread-based costs (DESCRIPTIVE ONLY, no pass/fail; the binding cost model is Gabe's call)

`part2_costs.json`.

**Data.** One WRDS connection, 12 year queries of `crsp.dsf` `bid, ask` for the 5,207 permnos mapped from the thin
pool. 99.77% of thin name-dates are mapped. Dates run 2008-01-01..2019-03-31. The pull is stored as
`final/data/wrds/crsp/dsf_bidask_2008..2019.parquet` in the main checkout: gitignored, never committed.

**Spreads.**
- **Source:** 99.4% of trade legs are priced from a valid closing quote, 0.6% by Corwin-Schultz, and 0.015%
  (base) / 0.018% (variant) by the 7.5bp default.
- **Per side, entry legs, after the 5bp floor:** median 6.1bp, mean 11.1bp, p90 20.1bp. 42% of legs sit at the
  floor.
- **By year (mean):** 15.9bp in 2008, 12.4 in 2009, about 9-10 in 2010-2016, 11.6 in 2017 and 12.8 in 2018.

| net %/yr | base vs SPY | variant vs SPY | Δ (variant − base) | base vs EW thin pool | variant vs EW thin pool |
|---|---|---|---|---|---|
| flat 15bp (= WO-58 to 1e-9) | +8.059 | +8.563 | +0.504 | +5.37 | +5.87 |
| **spread-based** | **+7.819** | **+8.322** | **+0.503** | +5.13 | +5.63 |
| spread-based × 1.5 | +7.475 | +7.967 | +0.492 | +4.79 | +5.28 |

- **Assert.** The primary model with every half-spread set to 7.5bp equals the flat-15bp formula to 1e-12.
- **Weighting sensitivity.** With pick-weighted exact turnover, the levels are: spread base +7.86 / variant +8.37,
  Δ +0.506; ×1.5 base +7.54 / variant +8.04, Δ +0.497.
- **What the levels mean.** Quoted spreads cost the thin book about 0.24pp/yr more than flat 15bp, or 0.58pp at
  ×1.5. The cw-spread screen's Δ is unchanged.

**Caveats:**
- These are closing quotes. The entry fill is at the open, where spreads are usually wider.
- There is no market impact. That is consistent with WO-58's capacity check: a mean position of $565 at a
  $100k book.
- In the output, the trade-source labels are truncated to "corwi"/"defau" (a string-width quirk). The shares are
  correct.

## What this means for D-THINBOOK (input only)

**The +8.06 is not a bug.** On the honest daily grid it is about +7.0. Realistic spreads take off about 0.25pp.

**But most of the gap to WO-6's +2.85 is the 2008-2018 window.** Every tier gains from dropping 2007 and 2019: about
1.8pp for cap2000 and 2.6pp for cap150 (icw8). On WO-6's 2007-2019 window the thin icw5_seas book was not measured here, because that
is outside this WO's era rule. WO-54's cap150 icw5_seas figure there is +3.64.

**Out of era it trails SPY.** On 2019-2025 the same book was −4.7 (WO-58 Stage 2, hold-out read #23).

**Read the thin book's in-era premium over cap2000 as about +2.5pp under icw5_seas on 2008-2018.** Do not read it as
+8.

## Checks run

- Hashes: the plan doc and every input file are asserted in every script.
- Check 1: WO-6 reproduced exactly; WO-58 reproduced to 1.2e-9; fast path = slow path on all 133 dates (0
  mismatches); thin-flag Jaccard 1.0.
- CRSP label re-implementation = WO-51's stored r_C to 8.9e-13 on 20,000 rows.
- Part 2: flat reproduction of WO-58 to 1e-9, base and variant; the per-name cost model collapses to the flat
  formula to 1e-12.
- Read caps: every CRSP, quote and outcome read is asserted at or before 2019-03-31. Entry dates are at or before
  2018-12-31, apart from WO-6's own step A.
