# IBES analyst EPS revisions (`rev3`, Chan-Jegadeesh-Lakonishok 1996), v2 grid, nomination era

Date: 2026-10-08. COO work order WO-53; Gabe approved ("Proceed with all", 2026-10-08).
Branch `wo53-ibes-revisions` (to be based on `origin/integration`). Code: `final/src/wrds_ibes/`.
Outputs: `final/out/wrds_ibes/`. Data (parquet, gitignored, never committed; WRDS licence):
`/Users/ggraham/pipe_dream/final/data/wrds/ibes/`.

Status: **PRE-REGISTRATION, HASH-FROZEN (not committed).** No outcome statistic (IC, label,
return, book) was computed before the freeze. Git branch creation was denied by the permission
classifier, so on Gabe's instruction (2026-10-08) this file was frozen by recording its sha256 and a
timestamp in LEDGER.md and COO.md before the screen ran, and it was not edited afterwards. The commit is
queued in PUSH-PLAN-wrds-2026-10-08.md for Gabe to push. Results go in a separate file:
`final/models/2026-10-08-ibes-revisions-results.md`.

## Hypothesis and mechanism

Analysts fold new information into their forecasts slowly, and investors under-react to
the revisions (Givoly-Lakonishok 1979; Stickel 1991; Chan, Jegadeesh & Lakonishok 1996,
REV6). Stocks whose FY1 consensus EPS was revised up, scaled by price, earn higher
forward returns. **Sign +1.** One-sided: a negative t is a KILL, and the flipped sign is
not run.

**Scope fence.** This is estimate REVISIONS only. SUE / earnings surprise /
announcement-window / days-to-announcement features are certified dead (SUE/PEAD family
closed at 2 trials, WO-29; EAP/timing family closed at 6, WO-5) and are not computed.
Recommendation changes (ibes.recddet) are not part of this order.

**Trial count.** New family "analyst estimate revisions", trial 1, k = 1. It was on the
approved backlog, blocked only because AV estimates start in 2017.

## Data (pulled 2026-10-08; integrity below, no outcome read)

- `ibes.statsumu_epsus` (UNADJUSTED summary): measure EPS, fiscalp ANN, fpi '1' and '2',
  statpers 2006-06-01..2019-12-31; usfirm = 1, curcode USD applied in the build.
  1,453,744 rows raw, 1,388,274 US/USD/ANN. FY2 is pulled only for the rollover rule.
  The 2006 months are lag inputs for early-2007 dates only; this is not an era extension
  (no outcome before 2007-01-02 is ever computed).
- `wrdsapps.ibcrsphist` (IBES ticker <-> permno, 37,662 rows).
- `crsp.dsedist` share-adjustment events (facshr != 0), exdt 2006..2019 (8,884 rows).
- WO-51 crosswalk `final/data/wrds/link/permno_sharadar.parquet` (permno <-> Sharadar
  ticker with validity windows; respects WO-47 ticker-reuse segmentation), sha256
  `4db64e33…08c` (mtime 2026-10-08 16:01).
- Sharadar SEP `closeunadj` (and `close`, diagnostic only) from
  `data/sharadar/panel/stocks/2006-02..2019-12`.
- Grid: `final/out/reset2026/composite_panel_v2.parquet` sha256 `52f634ac…38ba`.

## Factor definition (frozen)

For IBES ticker i and monthly statistical period s1:

- FY1 at s1: `fpi='1'` row, fiscal period end E = `fpedats`, F1 = `meanest`, n1 = `numest`.
- s0 = i's statpers in calendar month(s1) − 3 (the IBES release three monthly cycles back).
- **FY1 rollover rule: same fiscal period.** F0 = the s0 consensus mean for fiscal period
  E, taken from whichever of `fpi '1'` or `'2'` at s0 has `fpedats = E`. If none, NaN.
  (25.4% of finite cap150 rows match through the s0 FY2 row.)
- numest ≥ 2 at both s0 and s1, else NaN.
- **Split basis: no share-basis change allowed.** If the linked permno has any CRSP
  distcd 5xxx event (split / stock dividend) with exdt in (s0 − 35 days, **t**], or the
  Sharadar SEP implied split ratio `(closeunadj/close)` between s0 and s1 differs from 1
  by more than 2%, the value is NaN. No split adjustment is ever applied to the factor.
  The 35-day lead covers IBES lagging a split by up to one monthly cycle; extending the
  window to t covers IBES moving to the new basis before the ex-date (see the split-lead
  check below). Every exdt used is ≤ t, so the rule is PIT. This removes 0.90% of cap150
  rows.
- P0 = Sharadar `closeunadj` on the last trading day ≤ s0 (within 7 days), so price and
  both EPS values are in the same (s0) share basis.
- **rev3 = (F1 − F0) / P0.** No winsorisation (the screen uses within-date ranks).
- **Link.** IBES ticker → permno via ibcrsphist with score ≤ 2 and sdate ≤ s1 ≤ edate
  (lowest score wins; no ambiguities occurred). permno → Sharadar ticker via the WO-51
  crosswalk, valid_from ≤ date ≤ valid_to, at the panel date t for the row and at s0 for
  P0 (ambiguous → NaN; 2 IBES rows).
- **PIT.** At panel date t, use the LATEST s1 with s1 < t strictly (first usable on the
  next trading day, i.e. a ≥ 1-trading-day lag) and t − s1 ≤ 45 calendar days. If that
  latest s1 fails any rule above the value is NaN; it never falls back to an older s1.
  Asserted row by row in the build: s1 < t, s0 < s1, staleness ≤ 45 d, price date ≤ s0.
- Momentum overlap: CJL note revisions overlap with price momentum, so a residual gate is
  registered (gate 6).

Code: `build_rev3.py` (factor only; never opens a label/return) →
`final/out/wrds_ibes/cache/rev3_factor.parquet` (sha256
`544cdda101a060ad0be7d35d4ec228d756cd3451b2d947b05569468787632865`, asserted at screen
start) and `rev3_integrity.json`. `hand_check_rev3.py` is an independent recompute.

## Integrity results (factor only; run before this draft was frozen)

- IBES funnel (FY1 rows 2006-06..2019): 699,630 → s0 month exists 664,431 → same fiscal
  period matched 661,480 → numest ≥ 2 both ends 538,242.
- Link ibcrsphist (score ≤ 2): 652,122 FY1 rows linked; 0 ambiguous.
- Split checks: SEP-implied vs CRSP split ratio agree within 2% on 99.94% of rows (94.0%
  on rows with a CRSP split in window; 163 disagreeing rows, e.g. HWM late 2016, are excluded by the basis-change rule anyway).
- **Three split examples** (why unadjusted values must not be differenced across a split):
  - AAPL 7:1, s0 2014-03-20 → s1 2014-06-19: F0 42.79, F1 6.31. Naive (F1 − F0)/P0 =
    −0.069 (a fake large downgrade); split-restated = +0.0026. Excluded (NaN) under the rule.
  - MWE 2:1, 2007-01-18 → 2007-04-19: naive −0.027, restated −0.0024. Excluded.
  - BASXQ 1:571 reverse split, 2016-12-15 → 2017-03-16: naive −0.76, restated +13.5 (F0 appears
    to be already on the new basis), so even restating leaks. Excluded.
  - Split-window rows' naive revision spans q01..q99 −38.5..+1.14 vs −0.147..+0.074 on
    clean rows, which is why the rule drops them rather than adjusting.
  - Split-lead check (before the window was extended to t): 7,978 cap150 rows (0.09%) had
    an event in (s1, t]; their |rev3| q99 was 0.217 vs 0.113 on clean rows and 19 rows
    showed F1/F0 ≈ 1/k (IBES already on the new basis). Hence the (…, t] window; after
    the rebuild the check finds 0 such rows.
- **Coverage, cap150 column c 2007–2019** (9,756,141 rows, 6,508 tickers, 3,272 dates;
  same universe as WO-13/18/49): finite rev3 **86.2%** (old grid 91.2%, added tickers
  74.8%); 99.82% of rows have a permno; by year 81.8%–88.2%, flat. Median staleness 18 d.
- Distribution (cap150 finite): q01 −0.092, q05 −0.029, q25 −0.0042, q50 0.0, q75 +0.0020,
  q95 +0.0137, q99 +0.047; 6.8% exactly zero.
- **Named checks** (independent recompute, all match the build to 1e-12):
  AAPL 2012-06-15 +0.006472 (s1 2012-06-14, s0 2012-03-15, FY 2012-09);
  MSFT 2015-06-15 −0.000690; dead names LEHMQ 2008-06-16 −0.035668 (IBES LEHM, F 6.43 →
  4.49) and WAMUQ 2008-06-16 −0.123369 (IBES WAMU, F −0.95 → −3.03); AAPL 2014-07-01 NaN
  (split exclusion).
- Brute-force recompute of 100 random finite cap150 rows (seed 53): 0 mismatches, PIT
  s1 < t on all, fiscal period E identical and s0 matched on E for all.

## Screen (frozen; same stack as io_gap / seasonality / WO-49)

- **Grid.** v2 column c, cap150, h = 40, label `forward_return_tradable_40`
  (close[t+40]/open[t+1]), 2007-01-02..2019-12-31, SPAC rule, loaded via
  `signcheck/dropcheck.load("A")` (asserts max date < 2020-01-01). No 2020+ outcome read.
- **Base: icw5_seas** (`ic_weighted_composite.PRODUCTION_WEIGHTS_V5_SEAS`, the current
  live composite). Before any rev3 book number, icw5_seas must reconcile to the WO-48b D4
  arm (`arm_mean40` = 0.036442521084825354) to 1e-10, and the icw9_seas base is
  re-asserted by `dropcheck.base_chain`. Fail → stop and report.
- **PASS requires ALL of:**
  1. Pooled per-date Spearman IC, Newey-West lag 39: **t ≥ +2.0** (new family, k = 1).
  2. Odd-year and even-year halves both have mean IC > 0.
  3. Both-sides sector-demeaned IC t ≥ +1.0 (factor-only demeaning reported, not gated).
  4. 0/40 grid-offset sign flips (offset means of the daily IC, o = 0..39, all > 0).
  5. LOYO: total summed IC > 0, max single-year share ≤ 45%, min leave-one-year-out t > 0.
  6. Momentum residual (same construction as WO-50's `ind_mom_resid`): per-date
     cross-sectional OLS with intercept of raw rev3 on raw momentum_12_1, on the cap150 rows
     of that date where both are finite; the NW(39) IC t of the residual ≥ +1.0. The median per-date Spearman with momentum_12_1 is
     reported beside it.
  7. Book: icw6 = icw5_seas + rev3 vs icw5_seas, decile_volq, net 15 bp vs SPY, 40 offsets.
     - The five V5 weights are byte-exact. `w_rev = +max(0.1, |t_rev| − 1) · k`,
       `k = Σ|V5| / Σ max(0.1, |t_k| − 1)` over the V5 factors (t_k from
       `ic_weighted_composite_report.json` plus `SEAS_T`; each V5 weight asserted to 2e-4).
       t_rev is the gate-1 t, so the weight is in-sample (stated).
     - Paired increment = mean over 40 offsets of (icw6 − icw5).
     - Null: 100 draws, seeds 53000..53099, within-date permutation of the finite rev3
       values, re-ranked and given the **SAME w_rev as the real factor** (not the floor
       weight). Null increment = shuffled-icw6 − icw5, mean over offsets.
     - Pass: paired increment > null p80 (numpy linear) **and** ≥ 26/40 offsets positive.
       Base sd40 is reported, not the bar. Null draw 0 rerun must be bit-identical.
  - Gate A (integrity, already met above, re-checked in the aggregate): the seed-53000
    placebo fails gate 1; hand checks and the 100-row brute force have 0 mismatches.
- **Verdict.** PASS = nomination for a forward side-ledger column only; Gabe decides.
  KILL (any of 1–7 fails) = the analyst-revisions family is certified dead; it reopens
  only with forward data. No post-hoc variants: no other horizons (REV6/REV1), FY2,
  numup/numdown, median, dispersion, price-scaling alternatives, or split-adjusted file.
- **Iteration cap 3**, bug fixes only, never definition changes. Code:
  `final/src/wrds_ibes/screen_rev3.py` (a copy of WO-49's `oppinsider.py` structure).
  Run order: `--real`, `--null 100 --procs 4`, `--recheck`, `--aggregate 100`, each under
  `caffeinate -i`.

---

## Results

(Not run. Blocked on branch creation; see status above.)
