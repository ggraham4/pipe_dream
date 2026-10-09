# WO-57 pre-registration: the WO-54 spin-off correction in the panel builder

Date: 2026-10-09. Owner: Gabe. Commissioned by the COO (WO-57; D-SPINFIX = COO rec yes, applied per Gabe
2026-10-09, "listen to the COO"). Branch `wo57-spinfix-builder`, based on origin/integration 1bef6a0.
Gate A correctness work. **Trial count 0**: no new signal, no weight change, no hold-out read, no 2020+ outcome,
no live change (constraint #1). Written and frozen before any book number or ACTIONS recall is computed.

## Why

WO-54 (`final/models/2026-10-09-spinoff-label-fix-results.md`) showed that Sharadar's split-adjusted `close`
books spin-off ex-dates as large one-day drops, and fixed the 40-day labels only (Δ +0.091pp/yr, 40/40). Its
handoff proposed moving the fix into the builder so the price features are fixed too. This order does that, on
the branch only, and measures the effect on the deployed baseline book.

## Correction (frozen)

- Per event (ticker, exdt): `m = (1 + r_S) / (1 + r_C)`, `r_S` = the Sharadar series' exdt return,
  `r_C` = CRSP `ret` on exdt. Every price of that ticker **dated before exdt** is multiplied by `m` (several events
  compound). This makes the adjusted exdt return equal CRSP's. (WO-54's pre-reg text wrote `1/m` in one place;
  the WO-54 code, and this order, multiply pre-exdt prices by `m`.)
- Uniform scaling is point-in-time safe for every ratio feature: a feature at date t uses prices <= t; if all of
  them are pre-exdt they are all scaled by the same m and the ratio is unchanged; the feature moves only when its
  window spans an exdt <= t, which was known on exdt.
- Applied to `open, high, low, close` (volume untouched) of the Sharadar daily series, after WO-47
  `segment_reused_symbols`; an event is attached to the segment whose date span contains exdt.

## Which columns use adjusted vs raw prices (frozen)

| adjusted prices (return / price-ratio quantities) | raw prices (levels) |
|---|---|
| forward labels: `gross_return_40` (outcome cache), `forward_return_40`, `forward_return_tradable_40` | stored `open/high/low/close/volume` columns of the price panel |
| `momentum_{w}`, `volatility_{w}` (incl. `volatility_60`, the book's vol buckets and inverse-vol weights), `pct_from_high_252`, `pct_from_low_252`, `relative_strength_20`, `daily_return`, `volume_ratio_20` (volume only: unchanged) | `market_cap` (= close x shares in the fundamentals step), `pe/pb/ps_ratio` |
| `momentum_12_1` (quality step) | eligibility flags `eligible_cap*` (downcap_universe from raw SEP/DAILY: `marketcap`, `closeunadj * volume`, price floor) |
| `beta` (beta step; not in icw5_seas, implemented, not book-tested) | dollar volume, price filters |
| `seas` (SEP `closeadj` month-ends; see below) | |

`seas` is built from `closeadj` (total return), not `close`. A data check (not an outcome) on WO-54's 242 applied
events showed `closeadj` already absorbs most of the spin (median |ln m_adj| 1.1% vs 22% for `close`) but not all
(91 of 242 have |ln m_adj| >= 2%). So `seas` gets its **own** factor `m_adj = (1 + r_closeadj) / (1 + r_C)` per
event, same threshold, applied to the month-end `closeadj` values dated before exdt **after**
`build_seas.splice_month_ends` (never to daily rows, so the 2005-01 splice ratio is untouched).

## Event source rule (frozen)

1. History (2007-2019): WO-54's CRSP event table `final/data/wrds/crsp/derived/spinfix_events.parquet`
   (dsedist distcd 3xxx, facpr > 0, crosswalk-mapped, CRSP and Sharadar guards). Candidates = the 274 events with
   status ok. Per price series apply when `|ln m| >= 0.02`: for `close` this is exactly WO-54's 242 applied events;
   for `closeadj` the same rule on `m_adj`. Events after 2019-12-31 are excluded (no 2020 return read).
2. Variant V1 (secondary, reported, not the verdict): add events whose offset-0 `|ln m| < 0.02` but whose largest
   |Sharadar - CRSP| one-day log gap within exdt±1 trading day is >= 0.02 at offset -1 or +1 (WO-54's SWY
   2014-04-15, TWX 2014-06-09, NEBLQ 2014-08-04 are the known cases); the factor is applied at the Sharadar drop day
   with `m = exp(gap)`.
3. Forward / live: Sharadar ACTIONS (`spinoff`, `spinoffdividend`, `spunofffrom`), pulled with a filtered API call
   for dates <= 2019-12-31 into the worktree (gitignored parquet; `final/data/sharadar/actions.csv` never touched).
   Test (2007-01-01..2019-12-31), match key = Sharadar ticker + date within ±1 trading day (exact-date counts also
   reported; parent-side rows `spinoff`/`spinoffdividend` keyed on `ticker`):
   - **recall (primary)** = share of the 242 applied CRSP events with an ACTIONS parent row; also reported on the 274
     candidates; ticker-mapping misses (event ticker absent from ACTIONS entirely) reported apart from "no row";
   - **precision** = share of ACTIONS parent rows on v2-grid tickers that match any crosswalk-mapped CRSP distcd 3xxx
     record of WO-54's event table (all statuses with a ticker, i.e. the 388 minus the unmapped) within ±1
     trading day; an ACTIONS row whose only CRSP counterpart is unmapped counts as unmatched (reported as a
     limitation);
   - the 3 known early-drop misses: is each present in ACTIONS within ±1 day?
   - descriptive: ACTIONS gives a ratio and a dividend value, not m; agreement of an ACTIONS-implied
     `m_A = close_ex / (close_ex + spinoffdividend value)` with CRSP m is reported, not judged.
4. Scope limit (stated, not fixed): no events before 2007 are available (no extra WRDS pull). Early-2007
   momentum/vol/high rows and `seas` (10-year lookback of monthly returns back to 1998) stay uncorrected wherever
   they cross a pre-2007 spin.

## Implementation (branch only)

- New `final/src/spinfix/adjust.py`: event loading, multiplier, `apply_spin_factors`, month-end adjustment.
- Opt-in hooks (default OFF, so nothing changes for the live refresh until Gabe decides a deploy + full rebuild):
  `build_features_sharadar` (features from adjusted prices, raw PRICE_COLS written), `quality_factors`
  (momentum_12_1), `build_beta_feature`, `build_outcome_cache` / `refresh_working_panel.step_outcome` (labels),
  `refresh_working_panel` (`--spinfix`), `seasonality/build_seas` (month-ends).
- No builder `main()` is run with its default output paths; nothing is written under the main checkout's
  `final/out`. The fixed panel is a patch panel in the worktree (`final/out/spinfix_builder/*.parquet`,
  gitignored): full-history recompute, through the hooked builder functions, of every ticker with an applied
  event (multiplier 1 elsewhere, so every other row is unchanged by construction), rows 2007-01-02..2019-12-31.
  Labels use OHLC through 2020-03-31 only (the WO-51 exit-leg convention for late-2019 labels).

## Checks (hard asserts unless marked)

- C1 unit check: on all affected tickers plus 50 random grid tickers, builder output with the hook on vs off has
  identical raw `open/high/low/close/volume`, identical `market_cap` from
  `build_features_fundamentals_sharadar.compute_fundamentals`, and on 20 sampled in-era dates the panel's
  `eligible_cap150/500/2000` and `market_cap` identical between unfixed and fixed panels.
- C2 recompute = stored: the unfixed (m = 1) recompute through the same path equals the stored
  `composite_panel_v2` `momentum_12_1` (float32), `volatility_60`, `pct_from_high_252`, the stored `seas`
  (WO-23 ext, == WO-18) and the stored `gross_return_40` (float32) on the affected rows. Any mismatch is reported
  by column; a mismatch in a book column is a fix-cycle trigger.
- C3 labels: fixed labels == WO-54 `label_fix` within 1e-6 on the shared rows.
- C4 the unfixed arm U, run through the same patch path, reproduces REF_V5 = +3.6442521% at 1e-10.
- C5 `find <main>/final/out -newer <this pre-reg> -type f` empty at the end.

## Book (pre-registered)

icw5_seas (PRODUCTION_WEIGHTS_V5_SEAS, unchanged), v2 column c, cap150, decile_volq, net 15bp, h=40, 40 offsets,
2007-01-02..2019-12-31, excess vs SPY; harness = WO-54 path (`signcheck/dropcheck.load("A")`, `score`,
`picks_fast`, `chains`), with the U frame patched before ranks and the Book are built. Arms:

- **U** unfixed (m = 1) — must equal +3.644% (C4);
- **L** labels only — expected to reproduce WO-54's +3.735% (Δ +0.091pp) within 1e-6;
- **F** features only (momentum_12_1, seas, volatility_60, pct_from_high_252 fixed; labels unfixed);
- **B** both — **the primary Δ = B - U**;
- **B1** = B plus variant-V1 events (secondary).

Reported per arm vs U: Δ (40-offset mean, pp/yr), offsets positive, min/max, LOYO, pick overlap
(mean over pick dates of |picks_arm ∩ picks_U| / |picks_U|).

## Verdict bars (frozen)

- **PASS (recommend for live)** iff all of: C1 identical; Δ(B) >= -0.10pp/yr; ACTIONS recall (±1 day, 242
  denominator) >= 90%. If recall < 90%, the verdict names the forward-source gap instead of PASS
  ("PASS-history, forward source gap").
- Re-derive ICW weights only if |Δ(B)| > 0.25pp (WO-54 bar); otherwise keep the weights.
- FAIL if Δ(B) < -0.10pp/yr or C1 fails.
- Kill / budget: at most 3 fix-and-rerun cycles (a C2/C4 failure triggers one); then stop and report
  "no result within budget".

## Rules

In-era 2007-2019 only; no 2020+ outcome (label exit legs through 2020-03-31 only, as every in-era book does);
no extension before 2007. No live deploy, no rebuild of the main checkout's panel, current_signal_* or ledgers.
NEVER TRADE: no code here places, modifies or cancels orders.
