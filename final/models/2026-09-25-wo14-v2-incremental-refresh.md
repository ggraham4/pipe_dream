# WO-14: incremental refresh of the v2 working panel + weekly forward records (2026-09-25)

Commissioned by pipe-dream-coo (Gabe priority, 2026-09-25). Engineering; no
research trial spent. Branch `worktree-agent-aa98b33b56140c58d`, based on
integration 8f47808.

## Why

`composite_panel_v2.parquet` is the working panel for every live and forward
model (WO-11), but `build_downcap_grid_v2.py` never overwrites anything and the
app's Retrain rebuilds only v1. Once base data passes 2026-09-08,
`current_signal_blend.py` stops with "no eligible rows" and Today's Picks
breaks. This adds the refresh path.

## The command (for the app's Retrain chain)

    python final/src/reset2026/refresh_working_panel.py --through latest --record-weekly

| | |
|---|---|
| exit 0 | refreshed, or already up to date (a no-op run writes nothing) |
| exit 1 | failed, message on stderr; the panel/beta/outcome files are only swapped in after every temp passes validation, so a failure leaves them untouched |
| runtime | ~250 s when there is new data (measured 247 s for 12 new dates), ~2 s when up to date; `--record-weekly` adds the Form 4 refresh (~60 s) and records (~10 s) |
| `--check` | says whether new SEP data exists; writes nothing |
| `--no-swap` | full build + validation into `*.wo14tmp`, never replaces anything |

Files it writes (main checkout):
- `out/reset2026/composite_panel_v2.parquet`, `beta_feature_v2.parquet`,
  `outcome_cache_v2.parquet` (swapped in; the previous file is kept as a
  hard-linked `*_through_<old_end>.parquet`)
- `scripts/td_data_sharadar_downcap_v2/*.csv` (replaced CSVs go to
  `_backup_through_<old_end>/` inside the same ignored dir)
- `out/reset2026/downcap_v2/refresh_report_<new_end>.json`
- with `--record-weekly`: `out/insider/insider_events_live.parquet` +
  `form4_refresh_state/` (edgar_form4_refresh.py), appends to
  `prediction_ledger_v3.csv`, `prediction_ledger_ext.csv`,
  `prediction_ledger_hedge.csv`, `ledger_panel_manifest.json`,
  `ledger_record_log.csv`

It never touches v1 files (`composite_panel.parquet`, `downcap_universe*.parquet`,
`features_*_sharadar_pit.parquet`, `pit_universe.parquet`, `td_data_sharadar/`).

**Where it goes in Retrain:** after `sharadar_pull_pit_panel.py` (and the rest
of the v1 data steps through `export_sharadar_ohlc.py`), before
`current_signal_blend.py` / `current_signal_composite.py`. The blend takes its
`as_of` from the v1 base panel, so the v1 data steps must run first, or the
blend stays on the older date (which still works, see §5).

**Pull-script gap (must fix for Retrain to move at all).**
`sharadar_pull_pit_panel.py` skips any month already on disk, so the current
month is never re-pulled; every Retrain was a no-op for September. For this
run I used `--start 2026-09 --end 2026-09 --force` (21 calls). The Retrain
step should pass `--start <current month> --force` (or the script should
always re-pull the last month). Same script, same key; the cost is about 21 calls.

## How (same point-in-time rules as the v2 build: the same builder code, paths repointed)

| step | code | window |
|---|---|---|
| universe | `downcap_universe.main()` → temp (full rebuild, 35 s) | all |
| prices | `build_features_sharadar.features_for` | each ticker's FULL SEP history. A buffer is not bit-stable: 30,661 of 35,900 volatility_60 values differed in the last bit when rolled from a 330/600-day buffer |
| fundamentals | `build_features_fundamentals_sharadar.main()` | rows from buffer start (60 trading dates before old end); as-of on SF1 `date` ≤ row date, exact on a buffer |
| issuance / short interest / events | `sweep.issuance`, `sweep.short_interest`, `sweep.events` library functions | same rows (as-of joins) |
| quality | `quality_factors.main()` | full close history |
| panel | `build_panel.main()`; `eligible_cap*_v1` on new dates = the v1 builder's flags (`downcap_universe.py`; since the 2026-09-22 split-basis fix its output is byte-identical to the v2 universe) | |
| beta | `build_beta_feature.main()` | full close history |
| outcome | `build_outcome_cache.vectorized_outcomes` on full SEP OHLC (the same data `td_data_sharadar*/` is exported from) | full |

Splice: rows on new dates are added. On old rows only NaN labels are filled.
Every other recomputed old value must equal the stored one, or the run fails.
The exception is eligible_* flags, which are kept as stored.

**Corporate actions / vendor revisions.** The last 3 months ≤ old end of
stored open/close are compared with SEP on disk:
- split-like (a close ratio outside [0.8, 1.25]): not extended, BLOCKED (below)
- revised: full history recomputed; it replaces the stored rows, as a full
  rebuild would
- stale (changed, no SEP rows after old end): left as stored

## Results (run 2026-09-25, through 2026-09-24)

Panel: 2026-09-08 → **2026-09-24** (12 new dates). Rows 22,535,814 → 22,584,099
(+48,285: 46,858 on new dates, +1,427 net from revised/new tickers on old dates).
Beta rows = panel rows. Outcome 22,544,773 → 22,593,060. Report:
`out/reset2026/downcap_v2/refresh_report_2026-09-24.json`.

**Sharadar calls: 21** (`sharadar_pull_pit_panel.py --start 2026-09 --end 2026-09
--force`: daily 93,804 rows = 10 pages, stocks 107,519 rows = 11 pages, 0
retries). Backup of the replaced month: `data/sharadar/panel_backup_wo14_2026-09-25/`.

### Acceptance

| # | check | result |
|---|---|---|
| 1 | overlap identity, dates ≤ 2026-09-08, all tickers except the 80 revised + 6 new: 22,309,377 rows, row sets equal | **PASS**: 0 mismatches on all 19 non-label columns (flags included); labels only NaN→value: 45,571 per label, 0 other changes |
| 1b | recomputed-vs-stored on the 60-date buffer (228,122 rows), the evidence that the extension is the same function | 0 mismatches on every price/factor/label column and beta. Only `eligible_cap500_v1` (7) and `eligible_cap150_v1` (177) differ: the stored v1 flags predate the split-basis fix. Kept as stored |
| 2 | idempotence: immediate second run | **PASS**: "up to date", exit 0, all three sha256 unchanged (panel 796eb808…) |
| 3a | rows per new date within ±5% of 3,901 | **PASS**: 3,904–3,906 |
| 3b | AAPL, MSFT, NVDA, NATH, WLKP on all 12 new dates, eligible_cap150, kept by the SPAC rule | **PASS** |
| 3c | close vs raw SEP, AAPL/NATH/WLKP × 12 dates | **PASS** 36/36 exact |
| 3d | no look-ahead: market_cap = close × sharesbas of the latest SF1 filing with date ≤ row date (2026-09-24) | **PASS**: AAPL filing 2026-07-31 (period 2026-06-27), NATH 2026-08-07, WLKP 2026-08-05; all exact. Caveat: SF1 on disk ends 2026-09-08, so this passes trivially for filings after that (see stale inputs) |
| 4 | reproduction: NATH rebuilt from full history with the original builders (module mains, one-ticker universe) vs the refresh on the new dates | **PASS**: 12/12 rows, 0 mismatches on 15 panel columns + beta |
| 5 | live scorers from integration on the refreshed panel | **PASS**: composite as-of 2026-09-24, 3,048 eligible cap150 (27 SPAC rows dropped by the rule), book 300. Blend as-of 2026-09-08 (see below), 1,665 scored, 165 picks. 0 non-old-grid SPACs in either |
| 6 | ledger blindness: sha256 of v1/v2/v3/ext/hedge + manifest before and after the refresh and scorers | **PASS**: all unchanged |

Script: `final/src/reset2026/wo14_acceptance.py 2026-09-08` →
`out/reset2026/downcap_v2/wo14_acceptance_2026-09-24.json`.

### Corporate-action / revision tickers

- **BLOCKED, split-like (8)**: CTSO (×20), GOSS (×80), GTBP (×25), JAGX (×15),
  NFE (×50), NXXT (×10), OPTT (×30), VWAV (×20). These are reverse splits after
  2026-09-08, and the SEP months before September on disk are still on the old
  basis. None was eligible at any tier on 2026-09-08 (all < $100M). They get no
  rows after 2026-09-08 until their history is re-pulled. Command (existing script;
  not run, since it's a new per-ticker pull, and folding its CSVs into
  `panel/stocks` is a step that doesn't exist yet):
  `python3 final/scripts/sharadar_downcap_pull.py --pull-list final/out/reset2026/downcap_v2/wo14_split_pull_list.csv`
  = **8 calls**. The alternative, re-pulling every month with the Retrain script, is
  `sharadar_pull_pit_panel.py --start 2005-01 --end 2026-08 --force`: about
  6,300 calls (bulk).
- **Revised, recomputed (80)**: small vendor corrections to one bar (mostly the
  09-08 open, e.g. ETSY +4.5%, BG −3.0%) or a row added or removed, e.g. AMZN,
  META, NOW, WFC, PFE. Full list in the report.
- **Stale, kept (8)**: ANY, BRR, BTAI, CYCN, JFB, KWM, LPSN, PHGE (vendor dropped
  their Sep rows, and they have no later rows).
- **New tickers (6)**: BAFN, ETSS, GSRV, IPHXU, TCGX, VII (now in the universe,
  not in the grid; full history added, 1,505 rows).
- Outcome cache: SPY 2026-07-27/28 non-truncated values differ from the current
  SPY.csv (yfinance refresh-recent rewrote late-Sept closes). Kept as stored.

### Stale inputs (not refreshed by any Retrain step)

`sf1_fundamentals.parquet` and `sf1_shares.csv` end at filings dated
2026-09-08; `tickers_master.csv` and `actions.csv` date from 2026-09-08. So new
dates carry forward the last filing ≤ 09-08. That is point-in-time correct but
stale, and IPOs after 09-08 aren't "domestic common" in the master yet. The top-up
is `sharadar_pull_fundamentals.py` / `sharadar_pull_shares.py` over the date
range since 2026-09-08. They are not Retrain scripts, so they were not run. Estimate: about 2–4 calls each for a
2-week date range (≈ <10k rows per table).

### Live scorers

- `current_signal_composite.py` (v2, cap150): latest date 2026-09-24,
  **cap150 book 300** of 3,048 eligible.
- `current_signal_blend.py`: **165 picks, as-of 2026-09-08**. It takes `as_of`
  from the v1 base panel (`features_with_fundamentals_sharadar_pit.parquet`),
  which this work order did not rebuild: running the Retrain's v1 data steps
  here was denied (they rewrite shared v1 files). With the v1 steps in the
  Retrain in front of it, the blend reads v2 on the new date. v2 now has rows
  through 2026-09-24.
- Pre-run outputs were backed up as `out/current_signal_{blend,blend_meta,blend_full,composite,composite_meta,compare}_pre_wo14.*`.
- No ledger was touched by the scorers.

## Weekly forward records (Gabe ruling 2026-09-25, recorded in COO.md)

Rules, verbatim from the COO's implementation of the ruling:

1. **Weekly record date** = the latest panel date in each ISO week. The hook records every ISO week after 2026-09-08 that has no record yet in each ledger. It is idempotent through the existing duplicate-date guards.
2. **Order of steps:** refresh insider data first (`final/scripts/edgar_form4_refresh.py`, as the ext record expects), then the panel, then the records. If a step fails, write nothing and exit non-zero.
3. **Late records.** Add `recorded_late=True` to any record whose `recorded_at` is more than 7 calendar days after its panel_date. This includes the catch-up weeks written on the first run. Late records are DESCRIPTIVE ONLY and can never be counted dates.
4. **WO-10 kill rule is unchanged.** Counted dates are still greedy from 2026-09-08, each at least 40 trading days after the previous counted date. Only on-time records are eligible. Weekly records between counted dates are descriptive (overlapping 40-day windows).
5. **Schema.** Existing CSV rows are not rewritten. `recorded_late` lives in the sidecar `out/reset2026/ledger_record_log.csv` (ledger, panel_date, iso_week, recorded_at, recorded_late, rows).

Implementation: `final/src/reset2026/record_weekly.py` (`--plan` writes nothing).
`prediction_ledger.record(date=None)` and `forward_hedge.record_hedge(date=None)`
gained an optional date; with none they behave exactly as before. A preflight
writes nothing unless every target date is blind, the hedge book guards
pass, and the insider data is fresh. "Late" = calendar-date difference > 7.

### Addendum to WO-10 (2026-09-25, citing Gabe's weekly-cadence ruling)

WO-10's registered text is not edited. `forward_hedge.status()` now drops
records flagged `recorded_late` in `ledger_record_log.csv`, and records
annotated `incomplete_week` in `ledger_record_annotations.csv`, before
applying the unchanged greedy counted-date rule. Weekly records between
counted dates are descriptive only.

COO rulings 2026-09-25 (after the first run):
- `record_weekly.py` targets complete ISO weeks only (see the deviation below).
- The 2026-09-24 / W39 records in v3, ext and hedge are annotated append-only in
  `out/reset2026/ledger_record_annotations.csv` (ledger, panel_date, iso_week,
  annotation, annotated_at, source): "incomplete_week: recorded before W39
  closed (09-25 trades); descriptive only, never a counted date; COO
  2026-09-25". No ledger or log row is rewritten, and no 09-25 record is added
  for W39 (one record per ISO week).
- The 8 split-like tickers stay blocked as a known gap (no pull).
  `refresh_working_panel.py` now fails (exit 1) if any of them becomes
  eligible at any tier after the old end, instead of silently omitting it.

### First run (2026-09-25)

| ledger | week | panel_date | rows | late |
|---|---|---|---:|---|
| v3 | 2026-W38 | 2026-09-18 | 3,053 | False |
| ext | 2026-W38 | 2026-09-18 | 3,053 | False |
| v3 | 2026-W39 | 2026-09-24 | 3,048 | False |
| ext | 2026-W39 | 2026-09-24 | 3,048 | False |
| hedge | 2026-W38 | 2026-09-18 | 464 (cap150 book 302, cap2000 160, 2 IWM legs) | False |
| hedge | 2026-W39 | 2026-09-24 | 462 (300 / 160 / 2) | False |

**Deviation, disclosed:** W39 was recorded at 2026-09-24 while W39 was still
open (2026-09-25 is a trading day, so W39's final panel date will be 09-25). The
first-run code treated the latest date seen so far as the week's date. Fixed
after the run: `record_weekly.py` now only targets COMPLETE ISO weeks (the week
holding the panel's max date waits until a later week's date exists), so a
daily Retrain can't lock in a Monday. The 09-24 rows are not rewritten (rule 5).
They can never be a counted date (09-24 is 12 trading days after 09-08, and the
next counted date must be ≥ 40), so the WO-10 kill rule is unaffected. Whether
to annotate them in the sidecar is the COO's call.

W37 already held 2026-09-08 in every ledger and was skipped. 2026-09-18 was
recorded exactly 7 calendar days later, so it is not late (rule: more than 7). Insider data
before recording: Form 4 live refresh through 2026-09-25 (451 filings; SEC
EDGAR, not Sharadar). ext opp fire rate 3.60% / 3.58%, leverage coverage 79%.

Checks: every pre-existing ledger byte unchanged (sha256 of the prefix; the git
diff of v3/hedge is 6,101 / 926 lines added, 0 removed). One record per ISO
week per ledger. A second run added nothing (hashes identical). `score` and
`score_hedge` report "still blind" for 09-08, 09-18 and 09-24 (hedge exits
~11-03, 11-13, 11-19).
