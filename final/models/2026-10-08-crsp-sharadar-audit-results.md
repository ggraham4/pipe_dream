Pre-registration hash-frozen (sha256 709986f9…e087, 2026-10-08T20:30:20Z), not committed, at the time these outcomes were computed.

# WO-51 results: CRSP vs Sharadar backbone audit, Phases 2 and 3

Pre-registration: `final/models/2026-10-08-crsp-sharadar-audit.md` (sha256
709986f9abed3943863b962322061cd888722fb2318281dc6226c1054eefe087, re-checked before each run).

## Anchor criterion (operationalisation, written before any Phase 2/3 number was computed)

The pre-registration says PASS needs "every named anchor is handled correctly" but sets no numeric bar.
This is the reading used here, fixed before running:

1. The crosswalk gives the expected permno on the anchor date (Phase 1, `anchors.json`).
2. The Run C rule is followed for a 40-day window across the anchor's terminal event
   (t = 20 trading days before CRSP's last trade; for WaMu, before the 2008-09-26 seizure), and at the two
   boundaries (CRSP delisting date on e, and on x). Checked by recomputing each label row by row
   (`hand_label` in `phase3.py`) and requiring equality with the vectorised label to 1e-9.
3. Sharadar keeps the terminal event: its 40-day label for the same window exists (the name stays pickable)
   and differs from the CRSP label by at most 10pp. A gap above 10pp means Sharadar mis-handles that anchor.
   Every gap is reported, and any anchor close to the line is flagged, not rounded to OK.

(Results below.)

## Verdict: FAIL, on the anchor leg only

| Leg (pre-registered) | Result | Bar | Leg |
|---|---|---|---|
| Δ = C − S, mean of 40 offsets, excess %/yr vs SPY, retx basis | **+0.171pp/yr** (S +2.854%, C +3.025%) | abs ≤ 0.5pp | pass |
| Phase 2 primary name-days within 10bp (retx) | **99.835%** (9,708,390 / 9,724,467) | ≥ 99% | pass |
| Named anchors handled correctly (criterion above) | 6 OK, 1 not evaluable (WaMu), **3 gaps over 10pp** (old GM, RSHCQ, BTUUQ) | all OK | **fail** |

By the rule as written, the verdict is **FAIL (re-base needed)**. The FAIL comes from the anchor leg's terminal-treatment
criterion. It does not come from the book: Sharadar's backbone gives the icw8 book 0.17pp/yr *less* than CRSP, well
inside the 0.5pp bar, and the daily return series agree on 99.8% of name-days. The pre-registration says no re-base is
done here; whether this FAIL calls for one is Gabe's call (see "Sensitivity" below for the narrower reading).

**Caveat on the deciding leg.** The anchor criterion is WO-51's own operationalisation. It sits in this results file
and is not part of the hash-frozen pre-registration: it was written after the pre-registration was frozen, but before
the anchor smoke test and before any Phase 2/3 number. The whole FAIL rests on it.

## Reconcile gate (Run S)

S mean-of-40 excess = **+2.8541632641%/yr** against readout.json `columns.c.cap150.icw8` = +2.8541632641%/yr
(difference -1e-17). Gate (within 0.1pp): **OK**. Bit-exact, despite the 2026-10-06 panel rebuild.
The market calendar (SPY dates) equals the union of column-c panel dates for 2007-2019 (3,272 = 3,272 days).
icw8 weights are hard-coded, and the script asserts they equal the extracted `ICW.PRODUCTION_WEIGHTS`.

## Phase 3 (decisive)

966,579 pick-rows on 3,272 dates, 2,070 permnos.

| | mean40 | sd40 | min40 | max40 | offsets > 0 | LOYO min (year dropped) |
|---|---|---|---|---|---|---|
| S (Sharadar) | +2.854% | 0.304 | +1.930% | +3.404% | 40/40 | +1.706% (2009) |
| C (CRSP retx, primary) | +3.025% | 0.304 | +2.110% | +3.576% | 40/40 | +1.886% (2009) |
| C (CRSP ret, total return; not judged) | +4.570% | 0.301 | +3.661% | +5.122% | 40/40 | +3.422% (2009) |
| C (retx + Shumway -30%; not judged) | +3.025% | 0.304 | +2.110% | +3.576% | 40/40 | +1.886% (2009) |

- **Δ retx = +0.1712pp/yr** (primary). Δ ret = +1.716pp/yr. That is the dividend yield the price-only
  Sharadar label leaves out, as expected, and not judged. Δ Shumway = +0.1712pp/yr, identical because none of the
  74 pick-rows with a missing dlret has a 5xx code (64 x 261, 5 x 470, 3 x 252, 2 x 262), so the -30% never applies.
- Δ is positive in every leave-one-year-out drop (C − S from +0.14 to +0.19pp across the 13 drops) and in every
  offset (+0.12 to +0.22pp).
- **Fallback to the Sharadar label: 2,245 rows, 0.169% of pick weight.** By reason (weight share): unmapped on t
  0.099%, entry leg NaN (CRSP prc missing on e) 0.055%, NaN retx inside the window 0.015%, no CRSP row on e 0.0004%.
  185 rows took the entry leg from Sharadar close/open (openprc missing).
- Delisting mechanics: 9,687 rows exit before x; dlret applied on 9,434 of them; 74 of those had no dlret/dlretx (0 used).
- Boundary exposure under the literal (e, x] rule:
  - 253 non-fallback rows have the CRSP delisting date on e (0.089% of weight). The rule leaves dlret out for these.
    Post-hoc sensitivity, not judged (`verify_phase3.py`): applying dlret on those rows gives Δ = +0.1726pp/yr
    (vs +0.1712). They are mostly mergers (codes 233 x200, 241 x33, 231 x15; weighted mean dlret +0.23%).
  - 217 rows have the delisting in (e, x] while CRSP rows still reach x (0.035%). For every delisted grid permno,
    CRSP's last trade date equals dlstdt, so here dlstdt = x. The delisting return falls after the exit close and
    is correctly left out. No bias.
- Pick-level 40-day agreement (for context only, not the Phase 2 bar): 98.6% of non-fallback pick-rows within 10bp.
- Contributions: the per-row decomposition sums to Δ exactly (|diff| < 1e-9, asserted). Top 20 contributors to Δ
  (required on FAIL; they sum to +0.021pp of the +0.171pp): 10 rows of CHZS (Computer Horizons, permno 26252,
  picks 2007-03-02..03-15) and 10 rows of SSP (E.W. Scripps, permno 84176, picks 2008-05-05..05-16). Both mappings
  are right (CRSP comnam matches the Sharadar name and CUSIP). In each, Sharadar's 40-day label is about -85% / -93%
  while CRSP's is about +1% / -5%.
  - SSP: the 2008-07-01 Scripps Networks spin-off plus 1:3 reverse split. CRSP moves the price-adjustment factor
    (cfacpr 4.735 -> 0.333). Sharadar's split-only series books the ex-date drop as a loss (Phase 2 worst-20 #2).
  - CHZS: the drop in Sharadar's series around the 2007 sale of its businesses and the 2007-03-30 move to OTC
    (CRSP code 520, dlret -1.3%). This looks like an unadjusted cash distribution, but no distribution record was checked.
  Full list: `final/out/wrds_crsp/phase3.json` `top20_contributors`.

## Phase 2 (descriptive; the 10bp share is a verdict leg)

Primary set: mapped, cap150-eligible, column-c name-days, 2007-01-02..2019-12-31.

| | total | mapped | evaluated | retention (eval/total) | < 1bp | < 10bp |
|---|---|---|---|---|---|---|
| Primary, retx | 9,756,141 | 9,738,576 | 9,724,467 | 99.68% | 99.291% | **99.835%** |
| Primary, ret (secondary basis) | | | 9,724,467 | | 98.492% | 99.061% |
| All mapped grid name-days, retx | 13,241,135 | 12,818,158 | 12,688,428 | 95.83% | 96.994% | 98.325% |
| All mapped grid name-days, ret | | | 12,688,428 | | 96.310% | 97.659% |

- Evaluated means both returns exist and CRSP's previous trading day equals Sharadar's previous row. Of the mapped
  primary name-days, 99.86% are evaluated. Every grid ticker has an OHLC CSV.
- Primary 10bp share by year: lowest 2009 99.57%, 2007 99.64%; all other years ≥ 99.73%.
- **Rounding item (report only):** of 16,077 primary misses ≥ 10bp, 1,154 (7.2%) fall inside Sharadar's
  3-decimal rounding bound 0.0005·(1 + c_t/c_{t−1})/c_{t−1}. Other overlapping classes: 410 on a CRSP cfacpr change,
  846 on a CRSP bid/ask-midpoint price, 3,437 ≥ 1%, 303 ≥ 10%.
- **Worst 20** (`phase2.json` `worst20_primary`). 16 of the 20 are days where CRSP changes its price-adjustment
  factor for a spin-off or special distribution and Sharadar's split-only series books the ex-date drop as a return of
  -60% to -93%: CY 2008-09-30 (SunPower), SSP 2008-07-01, STRZA 2013-01-14, ITT 2011-11-01, SBRA 2010-11-16,
  DSHK 2014-11-07, MTW 2016-03-04, PENN 2013-11-04, NC 2017-10-02, UNTD 2013-11-01, MSGN 2015-10-01, SPXC 2015-09-28,
  MO 2008-03-31 (Kraft/PMI), NI 2015-07-02, SLM 2014-05-01, ABWTQ 2007-10-29 (+92%, factor 0.52 -> 1). ZZ 2009-05-21
  is a rights offering (factor change). GLBR 2015-01-16 and DNDNQ 2007-03-30 are CRSP bid/ask-midpoint days (GLBR:
  CRSP -88%, Sharadar flat). PAR1 2008-03-17 is an unexplained price-level disagreement (Sharadar +66%, CRSP -2%).
  These are real Sharadar label errors around spin-offs, and they cut the book's Sharadar return (part of why Δ > 0).
- **Delisting check.** 2,955 grid permnos have a CRSP delisting (dlstdt 2007-2019, code ≥ 200): 2,270 2xx, 13 3xx,
  23 4xx, 649 5xx. Sharadar keeps an OTC tail past the CRSP delisting date for 655 (545 of the 5xx). For 2,300 its series
  ends on or before dlstdt. In every case CRSP's last trade date equals dlstdt. 91 tails are truncated at 2019-12-31
  (era). dlret and dlretx are both missing for 91 (43 of them 5xx).
  The gap (Sharadar tail from the delisting close to its last close ≤ 2019, minus CRSP dlret): within 1pp for 58.9%,
  within 10pp for 78.7%, median -0.07pp, p05 -76pp. By family, within 10pp: 2xx 96.7% (median -0.05pp), 5xx 13.7%
  (median -32.7pp), 3xx 15.4%. For 5xx names, Sharadar follows the stock down the OTC tail well past CRSP's
  delisting value. Per-name table: `final/data/wrds/crsp/derived/phase2_delistings.parquet` (CRSP values; never committed).
  - **WaMu** (WAMUQ, permno 81593): no CRSP delisting in 2007-2019 (dsedelist code 100, dlstdt 2024-12-31). CRSP's last
    priced day is 2008-09-26 (0.1604), followed by rows with no price. Sharadar continues OTC (0.16 through
    2008-10-15, 0.06 by 2008-10-30, last price 2008-10-30). On the days checked, 2008-09-22..26, its open and close match CRSP.

## Anchors

Main window: t = 20 trading days before CRSP's last trade (WaMu: before 2008-09-26); AAPL: t = 2008-06-02.
Criteria 1 (permno) and 2 (C rule matches the row-by-row hand computation to 1e-9) hold for all 10 anchors, on all
26 windows including the boundaries (`phase3_anchors.json`).

| anchor | permno | Sharadar 40d | CRSP 40d | gap | Sharadar tail vs CRSP dlret (Phase 2) | criterion 3 |
|---|---|---|---|---|---|---|
| AAPL 2008 | 14593 | -15.96% | -15.94% | 0.02pp | active | OK |
| Lehman (LEHMQ) | 80599 | -99.38% | -99.60% | 0.2pp | tail to 10-15 -38.5% vs dlret -60% | OK |
| Bear Stearns (BSC1) | 68304 | -16.62% | -18.06% | 1.4pp | ends on dlstdt (tail 0) vs dlret -1.7% | OK |
| Washington Mutual (WAMUQ) | 81593 | -98.26% | n/a (CRSP NaN after 09-26, fallback) | n/a | no CRSP delisting | not evaluable; 1-2 OK |
| old GM (MTLQQ) | 12079 | -39.36% | -67.55% | **28.2pp** | tail to 2011 -94.7% vs dlret -18.7% | **FAIL** |
| HIH1 | 89953 | +0.99% | +1.14% | 0.2pp | tail 0 vs +0.15% | OK |
| PLNR | 80012 | +6.30% | +6.30% | 0.0pp | tail 0 vs 0 | OK |
| RSHCQ (RadioShack) | 15560 | -29.49% | -72.05% | **42.6pp** | tail to 2015-03-19 -37.5% vs dlret -54.6% | **FAIL** |
| BTUUQ (Peabody) | 88991 | -32.71% | -61.45% | **28.7pp** | tail to 2017 -81.5% vs dlret -26.7% | **FAIL** |
| MAXY | 87499 | +0.79% | +0.40% | 0.4pp | Sharadar ends 08-28, CRSP dlstdt 08-29, no dlret | OK |

How to read the three FAILs. Each is a 5xx bankruptcy delisting. Sharadar keeps the stock through its OTC tail and the
40-day label exits at the actual OTC close on day 40. CRSP stops at the exchange delisting and applies dlret, a value
taken soon after delisting. Both are records of real prices. The two backbones disagree about how to treat the terminal
period, and in all three windows the OTC close on day 40 was above CRSP's delisting value. Over a longer tail Sharadar is the lower one (GM -94.7% and BTUUQ -81.5% by their last prices).
By the criterion fixed before the run, these anchors are mis-handled, and that leg is not rounded to OK.

Boundary windows are evidence for criterion 2 only, not judged on criterion 3. With the delisting on e, the literal
(e, x] rule leaves dlret out of C (GM: C +4.2% against S -58.6%; RSHCQ: C +0.1% against S -37.5%). That is a gap in the
pre-registered C rule, not a Sharadar error.

BTUUQ boundary window "delisting on x" (t 2016-02-16): S -8.0%, C -50.0%. This is not the tail mechanism. CRSP's
2016-04-13 row (Chapter 11 filing day, NYSE suspension) is a bid/ask midpoint of -1.125 (retx -45.7%). Sharadar's
2016-04-13 row is a stale 2.07/2.07 carried from the day before, and its first OTC print, 0.825, is on 2016-04-14.

## Sensitivity (not judged)

Under a narrower anchor reading (right entity, terminal event retained),
all 10 anchors are OK and the audit would PASS on all three legs. The book-level evidence is that Sharadar costs the
icw8 book 0.17pp/yr against CRSP (Δ > 0, so Sharadar is conservative). The 5xx terminal-treatment difference is real
(Phase 2: median -33pp tail-minus-dlret for 5xx). Its book effect is inside Δ, because the C run replaces every pick's
label, delistings included.

## Process

- Pre-registration sha256 re-checked before Phase 3 and before Phase 2: unchanged (709986f9…e087).
- Era: every statistic is 2007-01-02..2019-12-31. OHLC CSVs and SPY are read line by line and stop at the cutoff
  (2019-12-31 for Phase 2; 2020-03-31 for Phase 3 exit and entry legs only). CRSP dsf is filtered at load to the same cutoffs
  (asserted). No 2020+ row is scored.
- Fix-and-rerun cycles used: **1 of 3**. Phase 2's first full run crashed in the delisting check because a column
  named `tail` shadowed `DataFrame.tail`. Before the full Phase 3 run, the anchor smoke test (not a full run) caught
  a hand-check helper that lacked the pre-registered Sharadar open-leg fallback. Phase 3 ran once.
- Independent re-derivation: a separate script (`final/src/wrds_crsp/verify_phase3.py`) that does not import the WO-51 code or the harness re-reads
  `phase3_pickrows.parquet` and the SPY label. It rebuilds the 40 offsets with its own turnover and cost arithmetic
  and gets S +2.854163%, C +3.025345%, Δ +0.171181%, and fallback weight share 0.16917%, all matching.
- Code: `final/src/wrds_crsp/{common,phase2,phase3,verify_phase3}.py`. Outputs: `final/out/wrds_crsp/{phase2,phase3,phase3_anchors}.json`.
