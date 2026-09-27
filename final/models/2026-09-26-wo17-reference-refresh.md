# WO-17: refresh of the Sharadar reference tables (tickers_master.csv, actions.csv)

Commissioned by the COO, 2026-09-26. Branch `worktree-agent-ad4bd448e791c3c85`
(based on integration 2009552). This doc is committed BEFORE any write to the
main checkout. The results sections below the "Pre-registration" line are
filled in afterwards.

## Pre-registration (fixed before any live write)

### Problem

In the main checkout, `final/data/sharadar/tickers_master.csv` dates from
2026-09-08 (`lastupdated` max 2026-09-08). `actions.csv` covers
2025-09-09..2026-09-10. The v2 working panel now runs to 2026-09-24.

### What reads these tables (grep, 2026-09-26)

| consumer | column(s) | when |
|---|---|---|
| `reset2026/build_panel.py` | `sector` (one label per ticker, `drop_duplicates(keep="first")`) | panel build, incl. the refresh's 60-date tail buffer |
| `reset2026/downcap_universe.py`, `build_pit_universe.py` | `category` in DOMESTIC | universe / eligibility |
| `reset2026/working_panel.spac_tickers()` | `sicindustry` contains "Blank Check" | read time, on ALL dates incl. stored ones |
| `sweep/factors.load_sector_map` | `sector`, `sicsector`, `famaindustry` | read time |
| `sweep/taxonomy.py` | `sector`, `famaindustry`, `siccode`, `industry`, `sicindustry` | read time |
| `sue/sue_forward.py` (WO-15, not landed) | `actions.csv` rows with `action=split`, date > 2026-09-08 | forward SUE basis check |
| `sue/validate_sue.py`, `reset2026/downcap_grid_inventory.py` | actions | offline |

`refresh_working_panel.py` does NOT read `actions.csv`. Its split block is
price-based: stored close vs SEP on disk, with a ratio outside [0.8, 1.25].

**Verified fact that drives the method.** `composite_panel_v2` stores
`sector`. On 2026-06-01..2026-09-24 (317,805 rows, 3,988 tickers), the stored
`sector` equals the 09-08 master's label for every row (0 mismatches). Each
ticker has exactly one label. `refresh_working_panel.splice()` compares every
stored column on the 60-date tail buffer and exempts only `eligible_*`. So if
the new master gives any panel ticker a different `sector`, the next
`refresh_working_panel.py` (Retrain ALL) raises `RefreshError` and stops.
Under the current code, one ticker cannot take a new label on new dates only.

### Method

Script: `final/scripts/sharadar_reference_refresh.py` (new; branch only).
- It reuses the existing pull code: it imports `get` / `get_all` from
  `final/src/sharadar_build_identity_map.py`, the script that built both
  files. It never calls that module's `main()`, which would also overwrite
  identity_map.csv, units_report.txt and build_report.json.
- It writes only explicit main-checkout paths.
- The key comes only from env `SHARADAR_API_KEY`. Every request error is
  re-raised with the URL and key scrubbed.

Pulls (the only two):
1. `tickers?table=stocks`, full table (it ignores date filters), paged with
   offset at 10,000.
2. `actions?date.gte=2026-09-01`, paged.

Nothing else is pulled. A per-ticker SEP re-pull would be needed to unblock
the 8 split-blocked tickers. That is a new pull: it is reported, not run.

Build `tickers_master.csv`:
- **Base.** The base is `tickers_master_through_2026-09-08.csv`. If it does
  not exist yet, the run first creates it as a byte copy of the live file.
  Building from the backup makes reruns idempotent.
- **Row set.**
  - Take every row of the new pull, deduplicated on exact duplicate rows.
  - Also keep verbatim every base row whose ticker is missing from the new
    pull. Otherwise that ticker falls to `sector="Unknown"`, which triggers
    the same RefreshError.
- **Label hold-back.** This applies to every ticker present in the base
  (keyed by ticker, first base row, matching `build_panel`'s
  `drop_duplicates(keep="first")`). These label columns keep the base's
  value: `category, siccode, sicsector, sicindustry, famaindustry, sector,
  industry`. All other columns (isdelisted, lastpricedate, exchange,
  relatedtickers, scalemarketcap, ...) take the new values.
  - A ticker that is new since 09-08 takes all of its new values.
  - Every held-back difference goes to `final/out/wo17/master_label_changes_pending.csv`
    on the branch. Applying any of them needs a WO-16-style acceptance
    exception, which is Gabe's decision.
- The column set and order are identical to the base.

Build `actions.csv`:
- The base is `actions_through_2026-09-10.csv`, created as for the master.
- New file = the pulled rows (date >= 2026-09-01, API order) + the base rows
  with date < 2026-09-01 (base order), with exact duplicate rows dropped.
- Differences between base and pull in the overlap 2026-09-01..2026-09-10 are
  reported in `final/out/wo17/actions_overlap_diff.csv`.

Validation gates. The run aborts with nothing written if any fails:
- G1: the pulled master has ≥ 20,965 rows, and after dedupe no permaticker
  repeats (except repeats the base itself had).
- G2: every base permaticker appears in the pulled master, or its row is
  kept verbatim by the row-set rule.
- G3: the header equals the base header, for both files.
- G4: the pulled actions have min date ≥ 2026-09-01, and the max date is
  after 2026-09-10.
- G5: in the output master, for every ticker in the base, the label columns
  equal the base's.
- G6: AAPL, MSFT and NVDA are compared on every column EXCEPT `lastupdated,
  lastpricedate, lastquarter, firstquarter, scalemarketcap, scalerevenue`
  (fields that move with time). Any difference fails.
- G7: output row counts: master ≥ base rows − 1 (the base's JWS.U duplicate),
  and actions ≥ base rows with date < 09-01.

Write: temp file in the same directory → re-read and re-validate → `os.replace`.
- Backups `tickers_master_through_2026-09-08.csv` and
  `actions_through_2026-09-10.csv` are made once and never overwritten.
- If a backup already exists, it must not be changed.
- If the live file already equals the rebuilt output, nothing is written.

### Acceptance criteria

- **(a)** These stay byte-identical (sha1 before and after):
  `composite_panel_v2.parquet`, `beta_feature_v2.parquet`,
  `outcome_cache_v2.parquet`, every `*.csv` in `final/out/reset2026/`, and
  `ledger_panel_manifest.json`. A hash that moves is attributed by mtime. A
  concurrent WO-15 append is not a WO-17 write. Any other move fails the WO.
- **(b)** Report the tickers eligible (any `eligible_cap*`) on any panel date
  after 2026-09-08 whose held-back labels differ between the base and the new
  pull. Report separately:
  - their SPAC flag;
  - DOMESTIC-category membership changes;
  - base tickers missing from the pull.

  Also report new tickers since 09-08 that the next refresh would add as
  `new_tickers`, which adds rows on already-stored dates. If the held-back
  count is > 0, those changes are NOT applied (see Method). New tickers use
  the new tables.
- **(c) Named checks**
  - ≥ 3 listings/IPOs after 09-08 and ≥ 3 delistings/acquisitions after
    09-08 are present in the new master and actions, with consistent
    firstpricedate/isdelisted/lastpricedate.
  - ≥ 3 of WO-15's post-09-10 split names (BNTC, BRTX, BURU, GAUZ, HUBC,
    IPDN, KITT, LRHC, NRSN, TNMG, WHLR, ASX) appear in actions. Their date
    and ratio must match an external source: an SEC filing or exchange
    notice, or failing that a second vendor. The source is named per check.
  - AAPL/MSFT/NVDA: G6.
- **(d)** Report whether the refreshed actions would let
  `refresh_working_panel.py` extend CTSO GOSS GTBP JAGX NFE NXXT OPTT VWAV.
  The refresh code is not changed, and no panel refresh or Retrain is run.
  Each ticker's split value in actions is cross-checked against the observed
  close ratio from `refresh_report_2026-09-24.json`.

KILL / BLOCKED: a needed pull falls outside the two above, or (a) cannot be
guaranteed. Iteration cap 3.

---

## Results

(to be filled after the run)
