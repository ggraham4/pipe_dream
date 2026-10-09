# WO-54 results: Sharadar spin-off ex-date label fix

Pre-registration: `final/models/2026-10-09-spinoff-label-fix-prereg.md` (sha256 1c1a22ae…9ccd, committed and
pushed as 09d829a before any book statistic; both scripts assert the hash). Gate A correctness work, trial count 0.
In-era 2007-2019 only; no 2020+ return read; no hold-out read; nothing in the main checkout's `final/out/` touched.
0 of 3 fix-and-rerun cycles used: the rule ran as frozen. The only code fixes were a datetime comparison, a
column named `apply`, and the hand check's scaling direction (see "Deviation" below).

## Verdict: FIX

All 9 named cases pass the pre-registered bar. Δ = **+0.091pp/yr** (icw5_seas 3.644% -> 3.735%), positive on
**40/40 offsets**, below the 0.25pp re-derivation line. Recommend adopting the correction in the panel builder
(proposal below). No weight re-derivation needed.

## Phase 1: events (descriptive)

Code: `final/src/spinfix/pull_dist.py`, `events.py`. Output: `final/out/spinfix/phase1.json`; per-event and
per-label tables (CRSP values) in `final/data/wrds/crsp/derived/spinfix_{events,labels}.parquet` (never committed).

| step | count |
|---|---|
| dsedist 3xxx rows, exdt 2007-2019 | 4,362 |
| with facpr > 0 (spin-off candidates; distcd 3763 271, 3753 75, 3853 38, 3863 18, 3285/3265/3862 1 each) | 405 |
| events (permno, exdt) | 388 |
| unmapped (permno not in the v2-grid crosswalk on exdt; 85 permnos; see note) | 112 |
| CRSP / Sharadar guard failures (no CRSP prior row 1, no Sharadar row on exdt 1) | 2 |
| evaluable events | 274 |
| **applied** (abs ln m >= 0.02) | **242** (13 of them within 0.02..0.04) |
| below threshold (Sharadar already consistent) | 32 |
| mapped with match_quality != A | 0 |
| excluded: grid spin records with exdt in 2020Q1 (metadata only) | 3 |

- Unmapped check: for 4 of the 112 the CRSP ticker on exdt is a grid ticker (TMX 2008-06-11, IDT 2009-09-15,
  FOXA 2013-07-01, CNR 2010-08-24). These look like other share classes / reused symbols mapped to a different
  permno, so at most 4 events could be missed; Δ would move by a hair at most. Not chased.
- Applied by year: 15-31 per year, every year 2007-2019. ln m quantiles (applied): p05 -1.25, p25 -0.51,
  median -0.22, p75 -0.10, p95 -0.04. So the typical false drop is ~20%, the tail ~70%+.
- `m` agrees with CRSP's `facpr` (m ≈ 1/(1+facpr)): single-row applied events n=230, median |ln m(1+facpr)| 2e-6,
  92% within 5%. The rest have a split or a second distribution on the same day.
- `ret` ≠ `retx` on 9 applied events (a cash leg paid with the spin: CSC 2015-11-30, HSH, GYRE, MAXY, SBRA, WLTGQ,
  GAMI, WINMQ, TWO). Per the pre-reg the fix targets `ret`. Post-hoc sensitivity with a `retx` target on those 9:
  Δ +0.090pp/yr (vs +0.091), 40/40. Not judged.
- Off-by-one: 4 evaluable events have their largest |Sharadar − CRSP| one-day gap (≥ 2%) on the day before exdt:
  SWY 2014-04-15 (-11%), TWX 2014-06-09 (-4%), NEBLQ 2014-08-04 (-14%) are not applied (Sharadar books the drop one
  day early, so the exdt rule misses them); NRF 2014-07-01 is applied on exdt and also has a -50% (ln 0.5) gap the day
  before, which looks like a split-timing difference, not the spin. Primary rule left as frozen; listed for the builder.
- Labels: 9,438 (ticker, date) labels changed (all tiers). Unfixed cache labels equal an OHLC recompute on all
  9,340 checkable rows (max diff 1e-7); 10 random fixed labels equal a hand recompute (pre-exdt prices × m) to 1e-5.
- **Share of affected name-dates:** cap150 9,112 of 9,758,582 eligible (**0.093%**, 235 events);
  cap2000 6,576 of 3,802,861 (**0.173%**, 172 events).
- WO-51 cross-check: the 473 non-fallback icw8 pick-rows hit by the fix move from a median |S − CRSP| gap of 16.7pp
  to 0.0001pp; 99.8% land within 2pp of WO-51's CRSP label.
- Sharadar ACTIONS cross-check: not available for the era (local `actions.csv` holds no 2007-2019 spin-off rows).

### Named cases (bar: detected by the rule; ex-date return = CRSP ret within 1bp; fixed 40d label at t = exdt − 20 within 2pp of the CRSP retx label)

| case | exdt | Sharadar day | CRSP ret | m | label at t: unfixed | fixed | CRSP | gap pp | pass |
|---|---|---|---|---|---|---|---|---|---|
| SSP (Scripps Networks) | 2008-07-01 | -92.8% | +2.9% | 0.070 | -95.0% | -28.6% | -28.6% | 0.000 | yes |
| CY (SunPower) | 2008-09-30 | -73.3% | +23.8% | 0.216 | -85.0% | -30.5% | -30.5% | 0.000 | yes |
| MO (PMI) | 2008-03-31 | -69.9% | -1.4% | 0.305 | -70.8% | -4.1% | -4.2% | 0.079 | yes |
| ITT (Exelis + Xylem) | 2011-11-01 | -79.4% | +6.2% | 0.194 | -75.8% | +24.8% | +24.8% | 0.000 | yes |
| STRZA | 2013-01-14 | -87.4% | +0.9% | 0.125 | -83.1% | +35.8% | +35.8% | 0.000 | yes |
| PENN (GLPI) | 2013-11-04 | -76.7% | +2.7% | 0.227 | -75.1% | +9.8% | +9.8% | 0.000 | yes |
| NI (Columbia Pipeline) | 2015-07-02 | -62.6% | +4.1% | 0.359 | -61.4% | +7.6% | +7.6% | 0.000 | yes |
| MTW (Welbilt) | 2016-03-04 | -76.2% | +5.3% | 0.226 | -72.1% | +23.3% | +23.3% | 0.000 | yes |
| SPXC (SPX Flow) | 2015-09-28 | -75.9% | -7.2% | 0.259 | -79.2% | -19.6% | -19.6% | 0.000 | yes |

MO's 0.08pp gap is outside the spin day (the ex-date return matches to 1bp), most likely the entry leg (Sharadar open vs CRSP openprc); not checked further. Out of scope (not
spin-offs): CHZS, GLBR, DNDNQ, PAR1, ABWTQ, ZZ.

## Phase 2: book effect (pre-registered)

Code: `final/src/spinfix/book.py`. Output: `final/out/spinfix/phase2.json`. icw5_seas, v2 col c cap150, net 15bp,
h=40, 40 offsets, 2007-01-03..2019-12-31, excess vs SPY. Unfixed baseline re-derived in the same run and reconciled
to REF_V5 = 3.6442521% (diff 0, bar 1e-10). Pick sets identical on every date (asserted).

| | mean40 | sd40 (pp) | min40 | max40 | offsets > 0 |
|---|---|---|---|---|---|
| unfixed | +3.644% | 0.236 | +3.249% | +4.246% | 40/40 |
| fixed | +3.735% | 0.226 | +3.360% | +4.303% | 40/40 |
| **Δ** | **+0.091pp** | | +0.054 | +0.140 | **40/40** |

- LOYO of Δ: +0.078..+0.099pp (no single year drives it).
- 511 pick-rows on 511 dates change. Per-row contributions sum to Δ exactly (|diff| < 1e-9, asserted).
- Top 20 name-dates: 19 rows of SSP (picks 2008-06-03..06-27; label -94..-95% -> -18..-33%, ~+0.0008pp each) and
  CSC 2015-11-05 (-53.6% -> +8.6%). By ticker: SSP +0.015pp, EBAY (PayPal) +0.014, YUM +0.012, HSIC +0.007,
  FNF +0.007, IDT +0.005, KND +0.005, CSC +0.005, CVC +0.004, CTXS +0.004. Full list in `phase2.json`.
- |Δ| = 0.091pp < 0.25pp: **not** worth a weight re-derivation.

## Deviation (recorded, not a rule change)

The pre-reg's prose line "equivalent to multiplying every Sharadar open/close dated before the event by `1/m`"
has the direction backwards. The frozen formulas (`m = (1+r_S)/(1+r_C)`, `label' = (1+label)/m - 1`) are what ran;
they are equivalent to multiplying pre-event prices by `m`, which makes the ex-date return equal CRSP's. The hand
check first used `1/m` (from the prose), failed, and was corrected to `m`; the label code itself never changed.

## Panel-builder proposal (not applied; the live panel and outcome caches are untouched)

1. Add a spin-off event table (permno/ticker, exdt, m) and, in the price step of the panel builder
   (`build_features_sharadar` / `refresh_working_panel.step_prices`, before `build_outcome_cache`), multiply the
   Sharadar open/high/low/close of every row dated before exdt by `m` (cumulative over events). That fixes the
   labels exactly as here **and** the price features (momentum_12_1, seas, pct_from_high_252, volatility_60), which
   carry the same false drop for up to 12 months. The feature side is not measured here; a builder change would need
   a re-run of the icw5_seas book (expected small, same order as Δ) before deploy.
   **Caveat: scale returns, not levels.** Pre-spin the parent really was worth the higher price, so the adjusted
   series must feed only return-based quantities (labels, momentum_12_1, seas, pct_from_high_252, volatility_60).
   Anything using the price level (market cap, dollar volume, price filters) must keep raw prices. The cap150/cap2000
   flags come from the separate down-cap universe grid (`build_panel.py` merges them), not from the OHLC CSVs, but
   the builder owner should confirm no level-based input reads the adjusted series.
2. Forward source: CRSP runs about a year behind, so live use needs a forward spin-off feed. Candidate: Sharadar
   ACTIONS `spinoff` / `spinoffdividend` rows (present in the current `actions.csv`, 2025+), with `m` from the
   ex-date Sharadar return vs the parent+spun value. Not built or tested (open item).
3. Also handle the 3 off-by-one cases (Sharadar books the drop one day early) by testing exdt−1 when exdt is below
   threshold; and decide whether to target `ret` or `retx` for the 9 cash-leg events (Δ difference 0.001pp).
