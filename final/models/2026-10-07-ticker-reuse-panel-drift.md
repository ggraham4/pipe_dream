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

## Results (2026-10-07)

**Pre-registration timing.** The integrator's commit of this pre-registration was blocked by the
permission classifier, so it was not committed before the work ran. Evidence of the order: the
pre-registration text was hashed and snapshotted before any detection or diff ran
(`~/.cache/wo47/prereg_sha256.txt`, sha256 `fab878c8…0671f2`; snapshot `~/.cache/wo47/prereg_snapshot.md`).
Everything above "## Results" is that text unchanged.

Scripts: `final/src/tickerreuse/`. Outputs: `final/out/tickerreuse/`. All runs read the frozen copies
pinned in section 0.

**Panel identity.** The Oct-6 build reproduces WO-43's findings. It has 4,015 ticker blocks against
the Sep-11 build's 4,030. ADRX is still one merged block. It now has 7 label rows crossing into 2026
(2006-09-11..19) where WO-43 found 6, because the Oct-6 build has one more 2026 trading day (10-05).

### A. Ticker reuse

**A1. Count.** The raw SEP panel has 16,360 symbols and 32,666,126 rows (2005-01..2026-10).
- **D1 finds 4 symbols, with 1 boundary each** (`reuse_boundaries.csv`):

| symbol | old entity (permaticker), last price | new entity, first price | rows after | real reuse? |
|---|---|---|---|---|
| ADRX | Andrx (170871, now `ADRX1`), 2006-11-03 | Adarx Pharmaceuticals (6401389), 2026-09-25 | 7 | yes |
| RML | Russell Corp (170615, now `RML1`), 2006-08-01 | Resolution Minerals (6401339), 2026-09-09 | 19 | yes |
| HYAC.U | Suncrete / Haymaker IV units (640462, now `HYAC.U1`), 2026-04-08 | Haymaker Acquisition V units (6401345), 2026-09-18 | 12 | yes |
| AXPWQ | Axion Power (196940), 2016-02-05 | none | 2 | no: post-delisting vendor stub (close 0.30 → 100.00, zero volume) |

- **So there are 3 real reuses plus 1 stub.** All three real reuses are new listings since 2026-09-09 on symbols Sharadar recycled after our historical months were pulled (2026-09-09). Sharadar renamed each old entity `S1`. Our 2005-2026 monthly files still carry the bare symbol.
- **D2** (gaps over 20 trading days) finds 10 gaps:
  - 3 are the D1 boundaries.
  - 1 is the same entity on both sides (BURU, 2026 halt).
  - 6 are unresolved, all AXPWQ from 2010-2013. That is thin trading by one company, with no other entity.
  - There are no D2-only reuses.
- **Two extra cross-checks, not pre-registered and reported for completeness:**
  - `uncovered_rows.csv` / `uncovered_edges.csv`: 23 symbols have more than 5 SEP rows outside every entity's span. Every coverage edge is price-continuous (close ratio 0.85-1.25), apart from the AXPWQ stub. These are vendor date-range mismatches, not reuse.
  - `adjacent_entities.csv`: 3 symbols have entities less than 10 days apart. IPHXU and TBCVU are SPAC-unit handovers on 2026-10-05; STRRP is a preferred-stock ticker move. None is a recycled symbol.
- **Known limit of the pre-registered rule:** a reuse where the new entity starts within 5 calendar days of the old one is not split (unit test). None exists in the panel today.
- **Using the live `tickers_master.csv` (2026-09-26) alone, D1 finds only ADRX and AXPWQ.** HYAC.U and RML need a fresh TICKERS pull.

**A2. Reach** (`reach_labels.csv`, `reach_ledgers.csv`).
- **Price/XGB panel (4,015 tickers):**
  - Only ADRX reaches it.
  - **(i) Backtest label rows dated 2007-2019: 0.** The 7 crossing labels are dated 2006-09-11..19. Their only route into 2007+ is the XGB training window of 2007 score dates, which is WO-43's 36 row-uses. The live q75 trains on 2025-26, so it is not affected.
  - All 7 new-listing rows carry trailing features computed partly from 2006 Andrx prices. For example, ADRX momentum_120 on 2026-10-02 is -0.228, which is Andrx's 2006 price against Adarx's.
- **v2 working panel:**
  - ADRX, RML and HYAC.U are all present.
  - 0 crossing labels dated 2007-2019.
  - Crossing labels on old rows: ADRX 7 (2006), RML 19 (2006-06), HYAC.U 12 (2026-02, old SPAC exiting into the new one).
  - Trailing-feature contamination on every new-listing row: ADRX 7, RML 19, HYAC.U 12.
  - The v2 factors on new ADRX rows also join Andrx-era SF1. For example, net_issuance_pct is 0.383 and accruals is -0.735 on 2026-09-25..10-05.
- **Forward ledgers since 2026-09-08: 12 rows, all on panel_date 2026-10-02, none a pick:**

| ledger | ADRX rank_pct | HYAC.U rank_pct |
|---|---|---|
| v3 (rank_pct / ic_weighted_rank_pct) | 0.205 / 0.182 | 0.152 / 0.416 |
| ext | 0.306 | 0.414 |
| sue | 0.155 | 0.413 |
| seas | 0.123 | 0.411 |
| io | 0.100 | 0.385 |
| r252 | 0.106 | 0.077 |
| blend_seas | absent | absent |

  - The ledgers carry no pick flag, so I checked the direction against the 2026-10-05 picks files (`pick_direction.py`):
    - On every ledger, the live composite picks have median rank_pct 0.90-0.93. The r252 picks have median 0.85 on the r252 ledger.
    - On every ledger, both names rank below the lowest-ranked pick: composite min 0.50-0.64; r252 min 0.158 on the r252 ledger, against 0.077 and 0.106.
    - Neither name is in any picks file.
  - ADRX is `INELIGIBLE_TODAY` in `current_signal_blend_full.csv`.
  - RML is in no ledger, and neither are IPHXU, TBCVU or STRRP.

**A3. Fix (worktree only).** Changes to `final/src/build_features_sharadar.py`:
- New `load_reuse_entities`, `reuse_boundaries` (rule D1) and `segment_reused_symbols`.
- `build()` now splits reused symbols right after `load_prices`. The later segment is renamed `S__postYYYYMMDD`.
- Entities are read from `data/sharadar/tickers_master.csv`.

Changes to the v2 path:
- `final/src/reset2026/refresh_working_panel.step_prices` calls the same helper before any per-ticker work. That covers features, `closes_full` (quality/beta inputs), and the `px` that `step_outcome` uses.
- `build_downcap_grid_v2.step_prices` calls `build()`, so it is covered too.

**A4. Checks: all pass** (`fix_checks.json`, `test_segment.py`).
- **A4c:** the unfixed scratch rebuild equals the pinned current panel on all 12,323,942 rows. It is byte-identical (float64 bit patterns) across all 18 value columns, with identical row order.
- **A4b:** the fixed rebuild against current, over all 4,014 non-reuse tickers (12,323,470 rows), has 0 rows that differ in bytes. The sample bar was ≥ 200k rows.
- **A4a:**
  - ADRX (465 rows) and `ADRX__post20260925` (7 rows) each equal `features_for()` run on that segment alone.
  - The 7 ADRX 2006-09-11..19 tradable labels are now NaN. Before the fix they were -0.20..-0.25.
  - The new listing's momentum_120 and pct_from_high_252 are NaN, since it has fewer than 120 rows. Before the fix, momentum_120 was -0.13..-0.23.
  - The old entity's other 458 rows are byte-identical. Only the 7 label rows changed.
- **Unit tests:** `test_segment.py` passes on synthetic blocks and on the real SEP extracts of all three reused symbols (ADRX, RML, HYAC.U):
  - each splits once;
  - each old segment's last 40 tradable labels are NaN;
  - each new segment's 120/252-row trailing features are NaN;
  - the stale live master alone still catches ADRX.

  The synthetic tests cover:
  - stale master and fresh master give the same split;
  - a halt of one company is not split;
  - a short-gap reuse is split;
  - the v2 `step_prices` segments before it groups;
  - outcomes for the old entity exit at its own last close.
- **v2 path:** no full v2 refresh was run, as pre-registered.

### B. Panel drift

**B-XGB (Sep-11 build vs current, pre-2020).**

| | rows | tickers |
|---|---|---|
| Sep-11 | 8,225,594 | 3,372 |
| current | 8,191,288 | 3,361 |
| shared (ticker, date) | 8,183,273 | |

- **On the 8,183,273 shared rows, all 32 common columns are identical:** prices, 14 price features, 2 labels, market_cap, 13 ratios and fundamentals_age_days. So there is no drift from SPY, SF1 or the builder rewrite before 2020, and causes S-spy, F-sf1 and F-builder have 0 rows.
- **All 50,336 differing rows are whole tickers present on only one side:**

| cause | test | rows | tickers |
|---|---|---|---|
| U-floor: the Sep-11 universe applied the $10 floor to split-adjusted `close`; the current one uses `closeunadj` | the screen with the adjusted floor and Sep inputs reproduces the Sep-11 4,030-ticker set exactly; the unadjusted floor drops these 14 (+5 post-2020). All are reverse-split names: median close/closeunadj 4-2400 | 42,321 (Sep-11 only) | ABTC ADAM CPHI FLNT GRCE GTE HGLI HKRSQ MFA NVTP RADCQ RBBN UIS VTNRQ |
| U-master: CLGX is absent from `tickers_master_through_2026-09-08.csv` and present in the 2026-09-26 master | swapping only the master adds exactly CLGX | 3,775 (current only) | CLGX |
| U-dates: first eligible after the Sep-11 build | swapping only the date cutoff adds ALNT (eligible 2026-10-02), SECZ (post-2020 only) and ADRX | 3,775 (current only) | ALNT |
| R-reuse: Adarx's 2026-09-28..30 ≥ $2B days made the symbol "ever eligible", which pulled in Andrx's 2005-06 rows | same swap, plus the A1 identity | 465 (current only) | ADRX |

- **Explained: 50,336 / 50,336 = 100%.**
- The current universe is reproduced exactly from current inputs (4,015 tickers).
- **Swapping only `sf1_shares` changes nothing** (U-shares has 0 rows).
- **Unexplained:** the builder in git (db38b25, 2026-09-09) already uses `closeunadj`. So I cannot say which script or file version produced the adjusted-floor universe behind the Sep-11 panel. The rule is identified by exact reproduction. The provenance of the file is not.

**B-v2 (`composite_panel_v2_through_2026-09-08` vs current, pre-2020).**
- Same 15,420,963 rows and 7,284 tickers.
- **Live eligibility flags (`eligible_cap2000/500/150`), market_cap, price and every factor column are identical:** net_issuance_pct, short_interest_days_to_cover, days_to_next_filing_seasonal, gross_profitability, accruals, asset_growth, momentum_12_1, pct_from_high_252, volatility_60, sector.
- **38,945 rows differ, 100% explained:**
  - **38,942 rows, 62 tickers:** only `eligible_cap500_v1` (12,962) and `eligible_cap150_v1` (34,531) changed.
    - On every changed row, the current `_v1` flag equals the unchanged v2 flag. Before, it did not.
    - 98% of the rows are reverse-split names.
    - Cause V1-flags: the legacy `_v1` columns were rewritten with the v2 eligibility rule. This matches `refresh_working_panel.py`'s note "v1 builder == v2 flags since 2026-09-22".
  - **3 rows:** ADRX 2006-09-11..13 forward labels, which now exit in 2026 (R-reuse).

**Success bar: PASS.** B-XGB is 100% and B-v2 is 100%, against ≥ 95% required for each.

**Hand-checks** (`hand_check.json`):
- **ADRX:**
  - SEP has 472 rows: 2005-01-03..2006-11-03, then 2026-09-25..10-05. The gap is 5,001 trading days.
  - TICKERS has `ADRX1` = Andrx 170871 (to 2006-11-03) and `ADRX` = Adarx 6401389 (from 2026-09-25).
  - The ticker is in the current XGB panel only.
- **CLGX:**
  - SEP has 4,133 rows, 2005-01-03..2021-06-03, with no gap over 5 days.
  - TICKERS has 199728 CoreLogic, 1997-12-31..2021-06-03, one entity. It is not reuse.
  - Closes equal SEP on 4,133/4,133 rows.
  - It is absent from the 09-08 master, so it is absent from the Sep-11 panel. It is in neither v2 panel.
- **RSHCQ:**
  - SEP has 2,570 rows, 2005-01-03..2015-03-19. TICKERS has 199304 RadioShack, last price 2015-03-19.
  - It is identical in all four panels: 2,570 rows, closes equal to SEP, 0 differing rows.

### C. thinliq arm 2 expiry rule

`run_arm2.build_entries` now filters with `W.accepted_expiries(exp, trading_days())`. That is the WO-35 rule,
and trading days come from SPY dates, as `run_wo_o1` uses them. `test_expiry.py` passes:
- the Good Friday 2019-04-19 expiry accepts 2019-04-18;
- an ordinary month is unchanged;
- the old filter would have missed 2019-04-18.

Arm 2 was not run.

### What this means
- **The backtest record (2007-2019) is clean.**
  - No reused symbol puts a crossing label on a 2007-2019 row in either panel.
  - The live composite's factors and eligibility before 2020 have not drifted since Sep-8.
  - The q75 cache's Sep-11 input differs from today's panel only by universe membership: 14 reverse-split names out, CLGX, ALNT and ADRX in.
- **The forward side has 12 contaminated ledger rows** (ADRX and HYAC.U, 2026-10-02, none a pick; see `pick_direction.json`).
  - Every recycled symbol Sharadar issues from now on will do the same until the fix is deployed.
  - It can also turn a past entity's history into "ever eligible" history (ADRX).
- **The live q75's training universe differs from the cache's** by the U-floor names. That explains WO-43's non-reproduction. It is not leakage.
