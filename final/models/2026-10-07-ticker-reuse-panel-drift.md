# WO-47: ticker reuse and panel drift (Gate A, correctness)

Work order WO-47 from the COO, 2026-10-07. Branch `worktree-agent-a9e713aa99499f834`, based on integration b1bb895.
Scope: correctness only. No hold-out read (nothing here computes or ranks a 2020+ outcome statistic),
no fit, no live deploy. Follows WO-43 FLAG 1 and FLAG 2 (`final/models/2026-10-06-xgb-batch-retrain.md`).

## Pre-registration (committed before any detection, rebuild or diff is run)

### 0. Pinned inputs

The live data files can be rebuilt by "Retrain ALL" at any time, so they were copied to scratch
(`~/.cache/wo47/frozen/`, 2026-10-07 08:57) and every step reads the copies.

| role | file | sha256 (first 16) | notes |
|---|---|---|---|
| "current" price panel | `final/out/features_sharadar_pit.parquet` | `4168d02ac451fd36` | built 2026-10-06 14:18, 12,323,942 rows, 4,015 tickers |
| "current" XGB panel | `final/out/features_with_fundamentals_sharadar_pit.parquet` | `7323d88c22f8b956` | built 2026-10-06 14:22, same rows |
| "current" v2 working panel | `final/out/reset2026/composite_panel_v2.parquet` | `52f634ac3eeed20c` | built 2026-10-06 14:35 |
| current PIT universe | `final/data/sharadar/pit_universe.parquet` | `afde7bb64f668ddd` | built 2026-10-06 14:15, 4,015 tickers ever |
| SPY | `final/scripts/td_data_local/SPY.csv` | `6897073c29a34f94` | 2026-10-06 14:13 |
| Sep-11 build (cache input) | `final/out/features_with_rates_sharadar_pit.parquet` | `18fa37b9a876fab0` | 2026-09-11, 12,335,243 rows, 4,030 tickers; WO-43 reproduced the q75 cache bit-exactly from it |
| Sep v2 working panel | `final/out/reset2026/composite_panel_v2_through_2026-09-08.parquet` | `4baff1d7e9478829` | the factor half of B |
| fresh Sharadar TICKERS | `~/.cache/wo47/tickers_fresh_2026-10-07.csv` | `b2f01c836f8ae377` | read-only API pull 2026-10-07, 22,598 `stocks` rows; scratch only, not written to `final/data` |

**Panel identity caveat.** WO-43 audited an "Oct-5" panel with 12,321,653 rows. That file was rebuilt
on 2026-10-06 (12,323,942 rows); the Oct-5 bytes no longer exist. The raw SEP months before 2026-09
were last written 2026-09-09 (all 260 pre-Oct-2026 monthly files in `panel/stocks` and `panel/daily`),
so nothing pre-2020 in the raw data moved between Oct 5 and Oct 6. Everything below is about the
Oct-6 build; the report will say whether the WO-43 counts (ADRX 6 rows, 4,015 tickers, CLGX in 2007)
reproduce on it.

**Mechanism already seen during orientation (not a result, a reason for the design).**
Fresh TICKERS shows `ADRX` = permaticker 6401389 (Adarx Pharmaceuticals, first price 2026-09-25) and
`ADRX1` = permaticker 170871 (Andrx, 1997-12-31..2006-11-03, renamed on 2026-09-27). The panel's
2005-2006 monthly files were pulled on 2026-09-09, before the rename, so they still say `ADRX`. The
2026-09/10 months were pulled after the new listing, so they also say `ADRX`. Sharadar's convention
is that the old entity of a reused symbol gets a numeric suffix. The local `tickers_master.csv`
(2026-09-26) still lists ADRX = Andrx and does not contain Adarx at all.

### A. Ticker reuse

**A1. Detectors**, run on the raw SEP panel (`panel/stocks`, every symbol, 2005-01..2026-10).

- **D1 (primary, identity).** For each symbol S, the candidate entities are every TICKERS row (fresh
  2026-10-07 pull, plus `tickers_master.csv` and `tickers_master_through_2026-09-08.csv`), table
  `stocks`, whose ticker is S or matches `^S[0-9]+$` (Sharadar's renamed-old-entity form), keyed by
  permaticker. Between two consecutive panel rows of S with dates a < b, a **reuse boundary** is
  declared when some candidate entity E has
  `lastpricedate ∈ [a − 5 cal. days, a]` and `b > E.lastpricedate + 5 days`, or
  `firstpricedate ∈ [b, b + 5 cal. days]` and `a < E.firstpricedate − 5 days`,
  AND the entity covering a (by [firstpricedate, lastpricedate] ± 5 days) differs from the one covering b,
  or one of the two sides is covered by no entity of S.
  A symbol with ≥ 1 boundary is a **reuse**.
- **D2 (cross-check, gap).** A within-symbol gap of more than **N = 20 trading days** (trading calendar =
  union of all SEP dates). Every D2 gap is classified: (a) also a D1 boundary; (b) same permaticker on
  both sides (halt / relisting of the same company: not reuse); (c) unresolved (no entity covers one
  side). D1-only boundaries (reuse with a gap ≤ 20 days) are listed too.

**A2. Reach.** For every reuse symbol, report:
1. presence in the 4,015-ticker price/XGB panel and in the v2 working panel (`composite_panel_v2`);
2. **backtest label rows 2007-2019**: rows dated 2007-01-01..2019-12-31 whose 40-row tradable label
   window (rows i+1..i+40 of the ticker block) crosses a reuse boundary; and rows in that window whose
   trailing features (windows up to 252 rows) cross a boundary;
3. **forward ledgers** since 2026-09-08 (`prediction_ledger_{v3,ext,sue,seas,io,r252,blend_seas}.csv`):
   rows with ticker = S and `panel_date` on or after the later segment's start (features contaminated
   by the earlier entity), with rank_pct and whether the row was a pick.

**A3. Fix (worktree only).** One helper, `segment_reused_symbols(px, entities)` in
`final/src/build_features_sharadar.py`, splits each reuse block at its D1 boundaries and renames every
later segment `S__post<YYYYMMDD>` (first date of the segment), the convention `price_discontinuity.py`
already uses and that downstream code already strips with `split("__post")[0]`. The earliest segment
keeps the plain symbol, so every row of the old entity keeps its name. Called from
`build_features_sharadar.build()` and from the v2 price step (`reset2026/refresh_working_panel.step_prices`,
and `build_downcap_grid_v2.py` if it groups the same way). Segmentation is on D1 only; D2 gaps that are
not D1 boundaries are not split (halts are real history of one company).

Consequence stated up front: the new listing appears as `ADRX__post20260925` in the rebuilt panels. Its
SF1 and daily-marketcap joins are keyed by plain ticker, so it gets no fundamentals and no cap flag,
and it drops out of live scoring until it has its own history under a stable name. That is the
intended conservative behaviour for a fix; the handoff names it.

**A4. Checks (pass/fail).**
- A4a: in a scratch rebuild of `features_sharadar_pit.parquet` with the fix (same frozen SEP/universe/SPY
  inputs, output to `~/.cache/wo47/`), no rolling feature and no label of any reuse symbol uses a row
  from the other side of a boundary. Tested directly: on each affected block, recompute the features
  per segment and require equality; and the 6 ADRX 2006-09 rows must have a NaN 40-day label.
- A4b: every (ticker, date) row of every non-reuse ticker is **byte-identical** (all 20 columns, NaN = NaN)
  to the pinned current panel, joined on (ticker, date), not by position. Required sample ≥ 200k rows;
  the check runs on the full panel.
- A4c: an unfixed scratch rebuild reproduces the pinned current panel bit-exactly (proves the scratch
  build is the live build and the diff in A4b comes from the fix alone).
- The v2 path change is checked by a unit test on the ADRX extract (no full v2 rebuild).

### B. Panel drift

**Scope.** Pre-2020 rows (date < 2020-01-01).
- **B-XGB:** Sep-11 build (`features_with_rates…`) vs current (`features_with_fundamentals…`) on the
  common columns: open/high/low/close/volume, the 14 price features and 2 labels, `market_cap`, and the
  13 fundamental ratios + `fundamentals_age_days`. Derived cap flag: `market_cap ≥ 2e9` and the
  ticker-date in the PIT universe.
- **B-v2 (factor half):** `composite_panel_v2_through_2026-09-08` vs current `composite_panel_v2` on
  eligibility columns (market_cap, price, `eligible_cap*` flags) and the live composite factors (the
  icw8/icw9 inputs, ≥ 8 columns), named in the results.

**Differing row:** a (ticker, date) present on only one side, or present on both with any compared
column not bit-equal (NaN equals NaN).

**Named causes, assigned by counterfactual rebuild in scratch (one input swapped at a time),
not by inspection:**
- U-master: PIT universe membership change from `tickers_master.csv` (2026-09-08 → 2026-09-26 snapshot,
  `category` / ticker changes). Test: rebuild `pit_universe` in scratch with the 09-08 master.
- U-shares: membership change from `sf1_shares.csv` top-ups (agreement rule). Test: rebuild with
  `sf1_shares_through_2026-09-08.csv`.
- F-sf1: fundamental columns / market_cap change from the SF1 top-up/refresh (WO-16). Test: recompute
  fundamentals with `sf1_fundamentals_through_2026-09-08.parquet`.
- F-builder: residual fundamental differences after F-sf1, from the global-asof rewrite of
  `build_features_fundamentals_sharadar.py` (0ad9c8f, 2026-09-22; the Sep-11 panel predates it).
- S-spy: `relative_strength_20` change from the SPY.csv refresh (app 4e57353, 2026-09-29). Test: the
  implied SPY momentum (`momentum_20 − relative_strength_20`) differs by one common amount per date
  across all tickers.
- R-reuse: the ADRX merge (labels).
- Any other cause found must be named with a test of the same kind; anything without a test is
  "unexplained".

**Success bar (fixed now):** ≥ 95% of differing pre-2020 rows assigned to a named cause, computed
separately for B-XGB and B-v2 (both must pass). Hand-check ADRX, CLGX and RSHCQ against raw SEP and
TICKERS. Fail = list what stays unexplained.

### C. Fold-in: holiday-expiry fix in thinliq arm 2

`final/src/thinliq/run_arm2.py` `build_entries` still filters expiries with the pre-fix rule
(3rd Friday or the Saturday after). Switch it to `W.accepted_expiries(exp, trading_days)` exactly as
`options_wo25/run_wo_o1.py` does (WO-35 fix, 82fc8db). Add a small offline test (Good Friday
2019-04-19 accepts 2019-04-18). Arm 2 is not run on real data.

## Results

(appended after the pre-registration commit)
