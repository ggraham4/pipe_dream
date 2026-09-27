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

### Addendum A (iteration 2 of 3; committed before any live write)

Iteration 1 was a dry run with no live write, and it failed G6:
`AAPL firstpricedate 1986-01-01 -> 1997-12-31`. The 09-26 TICKERS pull
clamps `firstpricedate` at 1997-12-31 for 7,860 tickers: every base value
before that date becomes 1997-12-31, and the pull's minimum is 1997-12-31.
Examples: AAPL, MSFT, MMM, KMB. That is a vendor-side change (possibly the
subscription's history window), not a real revision.
- Nothing in the live refresh or Retrain path reads `firstpricedate`. Its
  only readers are the identity-map scripts and the downcap_grid research
  harness.
- Taking the new value would destroy the pre-1998 first-price information.

Amendment: `firstpricedate` joins the hold-back set for base tickers. The
hold-back set is now `category, siccode, sicsector, sicindustry,
famaindustry, sector, industry, firstpricedate`. G5 and G6 are checked
against that set. Nothing else changes: G6 still fails on any other
non-time column. The run reuses the staged 09-26 22:3x pull
(`--reuse-pull`), so the dry run and the live write see the same bytes.

---

## Results (2026-09-26, iteration 2 of 3)

**Verdict: SUCCESS.**
- Both tables are refreshed.
- (a) holds: 12/12 hashes are unchanged.
- The named checks pass.
- For eligible tickers, 0 held-back label changes would have touched
  already-stored rows. The other held-back changes are reported below, not
  applied.

### Run

- **Iteration 1** was a dry run that failed G6 (AAPL `firstpricedate`). It
  led to Addendum A (commit 134fbf5).
- **Iteration 2** ran the staged pull with `--reuse-pull`: dry run, then the
  live write, then a rerun. The rerun wrote nothing: both files were already
  current and both backups already existed. The run is idempotent.
- **Pulls, two only:**
  - TICKERS `table=stocks`: 20,989 rows, 3 pages. No duplicate rows or
    permatickers. Every base permaticker is present.
  - ACTIONS `date.gte=2026-09-01`: 6,050 rows covering 2026-09-01..2026-09-29.
    That includes 12 rows dated after today: announced dividends and splits.
- **tickers_master.csv**: 20,965 → 21,014 rows.
  - All 20,989 pulled rows are in it.
  - 25 base tickers the vendor has since renamed are kept verbatim.
  - 50 tickers are new against the base; 40 of them are DOMESTIC.
- **Held back.** 7,936 differences on 7,889 tickers were held back, all in
  `final/out/wo17/master_label_changes_pending.csv`:
  - `firstpricedate`: 7,876;
  - `industry`: 27;
  - `category`: 13;
  - `sector`: 6;
  - `siccode` / `sicsector` / `sicindustry`: 4 each;
  - `famaindustry`: 2.
- **actions.csv**: 48,558 → 51,625 rows. That is 45,575 base rows dated
  before 09-01 plus the 6,050 pulled rows.
- **Overlap 09-01..09-10** (`final/out/wo17/actions_overlap_diff.csv`):
  - 1,977 rows are only in the base: 1,966 of them are `relation` snapshot
    rows, which the vendor re-dates to its latest snapshot (2,011 rows dated
    09-25).
  - 277 rows are only in the pull, mostly 09-09/09-10 dividends and listings
    the base had not yet seen.
  - Real vendor edits:
    - IONZ split 0.2 → 0.1;
    - MGN split 0.025 (09-08) is gone;
    - CYCN's 09-09 split is gone (CYCN was renamed KRSA);
    - BURU 09-02 split added;
    - IGR 09-08 split added;
    - HLSQ 09-09 split added.
- **Consumer simulation on the written master:**
  - The DOMESTIC set loses nothing and gains 40.
  - The SPAC (Blank Check) set loses nothing and gains 11 (new SPAC common
    lines such as CATL and XIII).
  - Stored panel `sector` against the new master: **0 mismatches over all
    9,272 panel (ticker, sector) pairs**. So the next
    `refresh_working_panel.py` splice will not hit a sector RefreshError.

### (a) sha1, before → after (main checkout, final/)

| file | before | after |
|---|---|---|
| out/reset2026/composite_panel_v2.parquet | 0b69d8e5b483 | same |
| out/reset2026/beta_feature_v2.parquet | 592f7fdac0c4 | same |
| out/reset2026/outcome_cache_v2.parquet | 367a048e35fb | same |
| out/reset2026/backtest_equity_curve.csv | 00e905d1617e | same |
| out/reset2026/ledger_record_annotations.csv | 9c7130ee973b | same |
| out/reset2026/ledger_record_log.csv | 7ca3c8ada287 | same |
| out/reset2026/prediction_ledger.csv | 04b36814f9ee | same |
| out/reset2026/prediction_ledger_v2.csv | 3414fd8cbd9f | same |
| out/reset2026/prediction_ledger_v3.csv | 963d5e3b489b | same |
| out/reset2026/prediction_ledger_ext.csv | 1eba78b329e5 | same |
| out/reset2026/prediction_ledger_hedge.csv | 1c0738be12cd | same |
| out/reset2026/ledger_panel_manifest.json | 349f5605e771 | same |
| data/sharadar/tickers_master.csv | ff3703fdf67d | 5b5ae81e44d0 |
| data/sharadar/actions.csv | b81acccfb03e | d1aa663067ae |
| data/sharadar/tickers_master_through_2026-09-08.csv | (new) | ff3703fdf67d (= old live) |
| data/sharadar/actions_through_2026-09-10.csv | (new) | b81acccfb03e (= old live) |

Full hashes are in `final/out/wo17/wo17_sha1_{before,after}.txt` and `run_report.json`.

### (b) Stored-row label and eligibility changes

Scope: the 3,130 tickers eligible (any `eligible_cap*`, v2 or v1 flags) on
any panel date after 09-08.
- Label change (any held-back column): **0**.
- SPAC-flag change: **0**.
- DOMESTIC-membership change: **0**.
- Missing from the pull: **1, DOMO**. The vendor renamed it HUCK on
  2026-09-24 (tickerchange rows, same permaticker 116453). DOMO is kept
  verbatim, so its stored rows do not move. See the flag below.

Across all panel tickers (any date), held back and not applied:
- 11 tickers have label changes:
  - industry only: ACAS, MCGC, AACC (Asset Management → Credit Services) and
    ZEP;
  - category DCS → DCS Primary/Secondary Class, which stays DOMESTIC: NFE and
    the unit lines CATLU, XIIIU, MTAKU, AMACU, BRTMU;
  - RML: every label changes.
- 6 in-panel tickers were reused with a new permaticker. The SPAC units moved
  their old permaticker to the common line. RML went from Russell Corp
  (delisted 2006, now RML1) to Resolution Minerals (ADR, listed 2026-09-09).
  Because of the hold-back, **the new RML and HYAC.U carry the old company's
  labels**, and RML stays DOMESTIC. Correcting that is part of the
  exception below.

**Applying any of the held-back changes needs a WO-16-style acceptance
exception. That is Gabe's decision.** The data is in
`master_label_changes_pending.csv` and `acceptance_b_tickers.csv`.

**What the next Retrain will do anyway** (not a WO-17 write; reported as the
pre-reg requires). New DOMESTIC tickers enter the universe on the next
`refresh_working_panel.py` as `new_tickers`, and `splice` writes their rows
on every date, including dates ≤ 2026-09-24 that are already stored.
- 26 of them have SEP rows after 09-08.
- 14 of those also have DAILY marketcap ≥ $150M after 09-08: AMAC, ASBH, BRTM,
  CATL, ETRA, LEDRU, LOVIU, MTAK, OIG, QVCG, SVIA, SWRD, XIII, XTND.
- Existing rows are untouched, and the ledger CSVs are not written by this.
- 10 of the 26 are SPACs (AMAC, BRTM, CATL, LEDRU, LOVIU, MTAK, OCLT, RNAQ,
  TLAC, XIII), which the column-c rule drops at read time.

**Flag, DOMO → HUCK (an eligible name).**
- From 09-24, SEP rows arrive as HUCK. HUCK is a new ticker with no history
  under that symbol, and DOMO will go stale.
- This comes from the ticker-keyed panel design, not from this refresh.
- It is worth a COO look if continuity matters. The same pattern holds for
  WO-14's 8 "stale, kept" tickers.

### (c) Named checks. PASS

The internal check covers the new master row, the actions row, and the SEP
panel's first or last date. External sources are named.

| kind | ticker | Sharadar (master / actions / SEP) | external source | match |
|---|---|---|---|---|
| IPO | OIG | firstpricedate 09-18; `listed` 09-18; SEP from 09-18 | Nasdaq trading 2026-09-18 ([SEC 424B4](https://www.sec.gov/Archives/edgar/data/0002124472/000162828026062794/orion180-424b4.htm), [Investing.com](https://www.investing.com/news/stock-market-news/orion180-prices-ipo-at-12-per-share-on-nasdaq-432SI-4906558)) | yes |
| IPO | ETRA | 09-18 / `listed` 09-18 / SEP from 09-18 | Nasdaq trading 2026-09-18 ([SEC 424B4](https://www.sec.gov/Archives/edgar/data/0002088082/000119312526395670/d61940d424b4.htm), [Nasdaq PR](https://www.nasdaq.com/press-release/electra-therapeutics-announces-pricing-upsized-3500-million-initial-public-offering)) | yes |
| listing (uplist) | SWRD | 09-10 / `listed` 09-10 / SEP from 09-10 | Nasdaq open 2026-09-10 ([SEC 8-K](https://www.sec.gov/Archives/edgar/data/0001795851/000166357726000266/swrd_8k090926.htm), [GlobeNewswire](https://www.globenewswire.com/news-release/2026/09/09/3359111/0/en/stewards-to-begin-trading-on-nasdaq-capital-market-under-symbol-swrd.html)) | yes |
| acquisition | ATAI | isdelisted Y, last 09-11; `acquisitionby` LLY 09-11; SEP ends 09-11 | Lilly closed 2026-09-11 ([Lilly IR](https://investor.lilly.com/news-releases/news-release-details/lilly-completes-acquisition-ataibeckley-advance-therapies)) | yes |
| voluntary delisting | CSANY (was CSAN) | Y, last 09-18; `voluntarydelisting` 09-18; SEP ends 09-18 | last NYSE day 2026-09-18 ([Globe and Mail / company PR](https://www.theglobeandmail.com/investing/markets/stocks/CSAN-N/pressreleases/4523943/cosan-to-delist-nyse-adss-maintain-level-i-adr-in-u-s-otc-market/)) | yes |
| regulatory delisting | SOBR | Y, last 09-16; `regulatorydelisting` 09-16; SEP ends 09-16 | delisted at open 2026-09-16 ([SEC 8-K](https://www.sec.gov/Archives/edgar/data/0001425627/000147793226005610/sobr_8k.htm)) | yes |
| split | WHLR | `split` 2026-09-22, 0.11111 (1:9) | 1-for-9, split-adjusted open 2026-09-22 ([Nasdaq ECA2026-666](https://www.nasdaqtrader.com/TraderNews.aspx?id=ECA2026-666), [SEC 8-K](https://www.sec.gov/Archives/edgar/data/0001527541/000152754126000349/whlr-20260917.htm)) | yes |
| split | HUBC | `split` 2026-09-14, 0.04 (1:25) | 1-for-25, split-adjusted open 2026-09-14 ([GlobeNewswire](https://www.globenewswire.com/news-release/2026/09/10/3359495/0/en/hub-announces-reverse-share-split.html)) | yes |
| split | NRSN | `split` 2026-09-14, 0.05 (1:20) | 1-for-20, first post-split day 2026-09-14 ([SEC 6-K](https://www.sec.gov/Archives/edgar/data/0001875091/000121390026098414/ea0304823-6k_neurosense.htm)) | yes |
| mega caps | AAPL / MSFT / NVDA | G6: no non-time column differs; only lastupdated/lastpricedate moved (09-08 → 09-25) | — | yes |

The external sources were checked through web-search summaries of the linked
pages.
- Not counted: BRNS. Sharadar has its acquisition by Clywedog on 09-16 (SEP
  ends 09-16), but the company's August notice expected the scheme to take
  effect around 09-03. That is unresolved.
- WO-15's 12 names in the refreshed actions:
  - **10 are present**: BRTX 09-08 1:20, BURU 09-02 1:40, GAUZ 09-11 1:20,
    HUBC 09-14 1:25, IPDN 09-14 1:30, KITT 09-25 1:6, LRHC 09-08 1:6,
    NRSN 09-14 1:20, TNMG 09-08 1:8, WHLR 09-22 1:9.
  - **Absent**: BNTC and ASX (ADR-ratio change), even as `adrratiosplit`.
  - BRTX, LRHC, TNMG (09-08) and BURU (09-02) are dated inside the base
    window. The vendor posted them after the 09-08/09-10 pull.

### (d) The 8 split-blocked tickers

The refreshed actions list all 8 splits, and each matches the close ratio
WO-14 observed:

| ticker | actions | ratio | WO-14 observed |
|---|---|---|---|
| CTSO | 09-08 | 1:20 | ×20 |
| GOSS | 09-11 | 1:80 | ×80 |
| GTBP | 09-08 | 1:25 | ×25 |
| JAGX | 09-17 | 1:15 | ×15 |
| NFE | 09-14 | 1:50 | ×50 |
| NXXT | 09-14 | 1:10 | ×10 |
| OPTT | 09-14 | 1:30 | ×30 |
| VWAV | 09-22 | 1:20 | ×20 |

**This does NOT let `refresh_working_panel.py` extend them.**
- The refresh never reads `actions.csv`. Its block is price-based:
  `detect_changes` compares stored close with SEP on disk, band [0.8, 1.25].
- The Retrain SEP top-up only re-pulls from the resume month
  (`sharadar_pull_pit_panel.py --start <resume> --force`), so the months
  before September on disk stay on the old basis.
- Gabe's Retrain ALL will run this sequence unchanged and still block the 8:
  1. `features.py`
  2. `sharadar_pull_pit_panel.py --start <resume> --force`
  3. `build_pit_universe.py` … `build_app_benchmarks.py`
  4. `reset2026/refresh_working_panel.py --through latest --record-weekly`
  5. `downcap_universe.py`, `quality_factors.py`, `build_panel.py`,
     `current_signal_blend.py`
  6. `current_signal_composite.py`, `build_backtest_equity_curve.py`

  Every step that reads the master (`build_pit_universe`, `downcap_universe`,
  `build_panel`, the refresh) now gets the refreshed file.
- Unblocking needs WO-14's per-ticker re-pull (8 calls), plus a
  fold-into-`panel/stocks` step that doesn't exist yet. It is a new pull, so
  it is Gabe's call:
  `python3 final/scripts/sharadar_downcap_pull.py --pull-list final/out/reset2026/downcap_v2/wo14_split_pull_list.csv`

### Coupling and notes for the COO

- **WO-15.** `sue/sue_forward.split_names_since_basis()` reads live
  `actions.csv` splits after 09-08.
  - That set now also contains BRTX, BURU, GAUZ, HUBC, IPDN, KITT, LRHC,
    NRSN, TNMG and WHLR, plus the 8 above.
  - BNTC and ASX are still not listed.
  - This changes WO-15's allowed-split set. Recheck WO-15 before it deploys.
- **Vendor `firstpricedate`.** It is now clamped at 1997-12-31 for 7,860
  tickers. If the Sharadar plan's history window has changed, full-history
  SEP re-pulls, including the unblock recipe above, may also come back
  truncated. Check this before any bulk re-pull.
- **Other readers.** The v1 blend panel rebuild (`build_panel.py` in
  `bm.retrain_commands`) and `build_pit_universe.py` read the new master on
  the next Retrain. The hold-back keeps their labels identical for every
  existing ticker. Only new tickers add rows.
