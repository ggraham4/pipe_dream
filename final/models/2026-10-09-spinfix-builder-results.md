# WO-57 results: the WO-54 spin-off correction in the panel builder

Date: 2026-10-09. Branch `wo57-spinfix-builder` (based on origin/integration 1bef6a0). Pre-registration
`final/models/2026-10-09-spinfix-builder-prereg.md`, committed 29514f4 (sha256 a4c44e9b…5d56) before any book
number or ACTIONS recall. Trial count 0. No hold-out read, no 2020+ outcome, no live change, 0 of 3 fix cycles used.

## Verdict: PASS-history, forward source gap

- C1 identical: raw O/H/L/C/V from the hooked `features_for` == hook off on 266 tickers (216 with events + 50
  random cap150 tickers), and `market_cap` from `compute_fundamentals` identical on all 815,796 rows. The
  eligibility flags come from `downcap_universe` (raw SEP/DAILY `marketcap`, `closeunadj x volume`), which never
  sees the adjusted prices; the fixed panel carries `market_cap`/`eligible_*` unchanged.
- Δ(B) = **+0.088pp/yr** (bar ≥ −0.10pp): PASS. |Δ| < 0.25pp: **keep the icw5_seas weights** (no re-derivation).
- Sharadar ACTIONS recall (±1 trading day, 242 applied CRSP events) = **83.5%** < 90%: the forward source is not
  good enough on its own. Gap named below.

## Book (icw5_seas, v2 col c, cap150, net 15bp, h=40, 40 offsets, 2007-2019)

| arm | what is fixed | 40-offset mean | Δ vs U (pp/yr) | offsets > 0 | LOYO Δ range | pick overlap |
|---|---|---|---|---|---|---|
| U | nothing (m = 1 through the same path) | +3.6443% (= REF_V5, diff 0) | | | | |
| L | labels | +3.7354% | +0.091 | 40/40 | +0.078..+0.099 | 1.000 |
| F | features (mom_12_1, seas, vol_60, pfh_252) | +3.6418% | **−0.002** | 17/40 | −0.014..+0.006 | 0.9963 |
| **B** | **both (primary)** | **+3.7320%** | **+0.088** | **39/40** | +0.070..+0.097 | 0.9963 |
| B1 | B + the 3 early-drop events | +3.7328% | +0.089 | 40/40 | +0.071..+0.098 | 0.9963 |

- L reproduces WO-54's fixed book to 7.6e-12 (C3: fixed labels == WO-54 `label_fix`, max diff 4.1e-7 on 9,418 rows).
- The feature-only effect is nil (−0.002pp, half the offsets each way). Fixing `volatility_60` moves vol buckets and
  inverse-vol weights, so picks differ on 2,296 of 3,272 dates, by 0.37% of names on average.
- B delta min over offsets −0.003pp (one offset slightly negative), max +0.18pp.

## Builder change (opt-in, default OFF)

- `final/src/spinfix/adjust.py`: `load_events`, `multiplier`, `apply_spin_factors` (pre-exdt O/H/L/C × m, compounding,
  after WO-47 segmentation; an event attaches to the segment containing exdt), `adjust_month_ends`.
- Hooks: `build_features_sharadar.features_for(g, spy, spin_events=None)` (features + labels from adjusted prices,
  raw PRICE_COLS returned) and `--spinfix`; `quality_factors.momentum_12_1()` + `SPINFIX_EVENTS`;
  `build_beta_feature.SPINFIX_EVENTS`; `build_outcome_cache.spin_adjust_ohlc` + `SPINFIX_EVENTS` + `--spinfix`;
  `refresh_working_panel --spinfix` (refused without `--no-swap`, see below); `build_seas.SPINFIX_EVENTS_ADJ`;
  `seas_live.seas_asof(..., spin_events_adj=None)` (checked == builder seas on 2 dates, max 8e-17).
- `seas` uses `closeadj`, which already absorbs most of the spin (median |ln m_adj| 1.1% vs 22% on `close`), so it
  gets its own factor: 97 of 274 events cross the 2% line on `closeadj` (242 on `close`).
- C2: the hook-off recompute equals the stored panel **exactly** (0 diffs, 712,883 rows) for momentum_12_1,
  volatility_60, pct_from_high_252, seas and gross_return_40. Material changes (relative > 1e-6) with the hook on, in
  cap150 rows: momentum 49,262; vol 13,396; pfh 44,807; seas 8,994; labels 9,112. Other changed rows are float
  rounding from the scaling (≤ 1e-6 relative).
- Nothing was written under the main checkout's `final/out` (C5 `find -newer` empty).

## Sharadar ACTIONS as the forward source (2007-2019)

- Pulled spinoff/spinoffdividend/spunofffrom (289/270/289 rows; 275 parent ticker-dates) into
  `final/out/spinfix_builder/actions_spin_2007_2019.parquet` (gitignored). `final/data/sharadar/actions.csv` untouched.
- Recall vs 242 applied CRSP events: exact 82.6%, **±1 day 83.5%** (202 hit; 27 ticker absent from ACTIONS spin
  rows; 13 rows not near the date). On the 274 candidates: 77.4%. Adding child-side `spunofffrom` rows: no gain.
  Misses are spread across years (1-5 a year); examples PDE 2009, FWONA 2014/2016, DELL 2018, JEF 2019, AIG 2011,
  RIG 2007, PPL 2015.
- Precision (±1 day) 88.0%: 213 of 242 ACTIONS parent rows on grid tickers match a CRSP 3xxx record. Unmatched ones
  include DD 2019-06-03, GE 2019-02-26, LEN 2017-12-06, HWM 2016-11-01: mostly real spins whose CRSP record was
  unmapped or carried another code, so true precision is likely higher.
- The 3 WO-54 early-drop misses: TWX 2014-06-09 and NEBLQ 2014-08-04 are in ACTIONS (on the CRSP ex-date, 1 trading
  day after Sharadar's drop); SWY 2014-04-15 is absent. The CRSP ±1 variant (V1) catches all 3 (Sharadar drops
  2014-04-14, 2014-06-06, 2014-08-01) and adds +0.001pp.
- m from ACTIONS (descriptive): `ratio × spinco close` on exdt reproduces CRSP m almost exactly where both legs exist
  (median |Δ ln m| 4e-7; 186 events), so ACTIONS + Sharadar prices can supply m going forward; the
  `spinoffdividend` value is looser (median 0.8%).

## Forward source gap (for Gabe / COO)

ACTIONS alone misses about 1 in 6 material spins. Options: (a) ACTIONS + a price-gap detector (a one-day close
drop with a `spunofffrom`/listed child, or any |ln| gap ≥ 2% vs `closeadj`) to flag candidates; (b) CRSP once a
year to backfill (≈1-year lag); (c) accept the gap: the whole correction is worth +0.09pp/yr, so a 17% miss costs
about 0.015pp/yr.

## Live adoption (not done; Gabe's call)

The hook rewrites historical rows, so `refresh_working_panel`'s old-row compare would fail on them. Adoption needs
a full rebuild of the working panel/outcome cache/seas with `--spinfix` (or a carve-out in the compare), plus a
forward event source. `--spinfix` is refused without `--no-swap` for that reason. `audit/build_seas_ext.py` (the
WO-23 seas extension) and `seas_forward.py` call build_seas/seas_live and would need the event frame passed through.

## Scope limits

No events before 2007 (no extra WRDS pull): early-2007 momentum/vol/high rows and `seas` (10-year lookback to 1998)
stay uncorrected where they cross older spins. Events after 2019-12-31 are excluded.

## Files

- Code: `final/src/spinfix/{adjust,builder_panel,actions_test,book_arms}.py`; hooks in the 7 builder files listed above.
- Outputs (committed): `final/out/spinfix_builder/{phase1_builder,actions_test,phase2_book}.json`.
- Gitignored: `final/out/spinfix_builder/patch_panel.parquet` (fixed patch panel), `events_{close,closeadj,v1}.parquet`,
  `actions_spin_2007_2019.parquet`, `parts/arm_*.json` (per-arm picks, not committed).
