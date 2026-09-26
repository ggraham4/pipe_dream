# WO-15: icw9-with-SUE forward ledger column (forward confirmation #1 of WO-13)

Date: 2026-09-26. Work order WO-15 (COO), approved by Gabe 2026-09-26 ("yes
add the SUE column"). Branch `worktree-agent-a505179eca9ed9bf2`, based on
`integration` 079fa26 (contains f0e750a: WO-13 + WO-14).

Status: **PRE-REGISTERED.** Everything above the "Results" line was committed
before any SUE forward-ledger record was written and before the full live SF1
pull. After that commit these sections are not edited; results go only in the
separated section at the end.

## What this is, and what it is not

- WO-13 (`final/models/2026-09-25-sue-drift-screen.md`) nominated `sue`
  (seasonal-random-walk SUE, sign +1): pooled IC t +2.17, 6/6 gates, but the
  portfolio increment icw9 − icw8 was only **+0.073pp/yr**.
- This work order records an **icw9_sue** score next to the v3 ledger's icw8
  score on every weekly forward record, on LIVE data only. It is **forward
  confirmation #1** of the SUE family. The family's in-era trial count stays
  k = 1 (spent in WO-13).
- **No promotion ever rests on the 2007-2019 result.** No new in-era test of
  icw9_sue at the forward weight is run. A nomination-era date (2015-06-15) is
  used ONLY for a code-reproduction selftest; no IC or return statistic is
  computed on it.

## 1. Frozen weights (ICW9_SUE_WEIGHTS)

Rule (the frozen ICW rule, `prediction_ledger.icw_rule`):
`w_k = s_k · max(0.1, |t_k| − 1) / Σ_j |s_j · max(0.1, |t_j| − 1)|`, a NaN t
gets the 0.1 floor, weights rounded to 4 dp (the ICW9_WEIGHTS pattern).

- **Reproduction first.** The same rule on the 8 production t's in
  `prediction_ledger.ICW9_T_USED` reproduces `ic_weighted_composite.PRODUCTION_WEIGHTS`
  to 4 dp exactly (checked 2026-09-26, all 8 equal):
  0.0497 / 0.0130 / −0.0130 / 0.5956 / −0.1627 / −0.1399 / −0.0130 / −0.0130.
- **Add `sue`** with t = **+2.169917640299337** (`final/out/sue/sue_screen_report.json`
  → `ic.pooled.t`), sign +1.

| factor | t used | sign | weight (4 dp) |
|---|---|---|---|
| momentum_12_1 | +1.3823405236334954 | +1 | **+0.0432** |
| pct_from_high_252 | +0.836261428518942 | +1 | **+0.0113** |
| volatility_60 | −0.2095936566027876 | −1 | **−0.0113** |
| gross_profitability | +5.5775328355615095 | +1 | **+0.5169** |
| accruals | −2.2508107695974884 | −1 | **−0.1412** |
| net_issuance_pct | −2.0749393150150004 | −1 | **−0.1214** |
| days_to_next_filing_seasonal | −0.7703417716508143 | −1 | **−0.0113** |
| short_interest_days_to_cover | NaN (floor) | −1 | **−0.0113** |
| **sue** | **+2.169917640299337** | **+1** | **+0.1321** |

Unrounded sue weight 0.13211136724316097; Σ|w| of the rounded weights = 1.0000.

**Disclosure.** The forward sue weight +0.1321 is **2.2× to 5.1×** the WO-13
split-half weights behind the in-era +0.073pp/yr (+0.060 fit on odd years,
+0.026 fit on even years). The brief's "2–4×" understates the upper end. The
forward test is therefore of a larger SUE tilt than the one whose portfolio
increment was measured in-era.

Scoring: `ICW.compute_composite_ic_weighted(cross, weights=ICW9_SUE_WEIGHTS)`
on the SAME eligible cap150 cross-section (SPAC rule applied first,
`working_panel.working_cross_section`) that v3's `record()` scores, with the
live `sue` column added. rank_z runs over the whole eligible cross-section, as
in v3; rows are then subset to v3's rows.

## 2. The live `sue` value (PIT filters)

Definition = WO-13's frozen definition (`final/src/sue/build_sue.py`), imported,
not re-implemented: ARQ only; first ARQ row per (ticker, reportperiod) by
`date`; D = EPS_q − EPS_{q−4}; SUE = D / sd of 8 prior D's (≥ 6, ddof 1,
sd > 0), clipped ±10; panel value on t = SUE of the latest filing with
`date` ≤ prev_td(t) (ties: latest reportperiod), NaN if t − filing date > 100
calendar days. `build_sue.py` gets a source-path parameter; its default
behaviour does not change (proved by regenerating `sue_factor_v2.parquet` and
comparing it with WO-13's copy).

Live source: `final/data/sharadar/sf1_arq_eps_live.parquet` (section 4), one
pull, one split basis, never unioned with the 2026-09-08 file.

PIT row filters, applied to the live rows BEFORE `build_filings` (so before
the first-by-date dedup):
- `date` (datekey) ≤ prev_td(t), where prev_td is the previous date on the
  working panel's date calendar (all tickers), as in build_sue;
- `lastupdated` ≤ t.

**Pre-registered fallback for the lastupdated filter** (added at commit time,
2026-09-26, from the COO's stated condition; nothing beyond it). On the first
live pull, before any record is written, compute the section 7 check (b)
metric (share of v3 tickers whose `sue` differs between the filtered and the
datekey-only live rows) for W38 and W39. If it is **> 5%** for either date,
the `lastupdated` ≤ t filter is replaced, for every record from then on, by:
filing date (`date`/datekey) ≤ prev_td(t), first-reported row only. This is
decided once and recorded in the handoff; it is not revisited later.

The count of rows excluded by the lastupdated filter (and not already by the
datekey filter) is recorded per date (ledger column
`sf1_rows_excluded_lastupdated`) and reported.

**Disclosure: the lastupdated filter is conservative.** A probe on 2026-09-26
(AAPL, 1 API call) showed rows filed 2026-01-30 and 2026-05-01 carrying
`lastupdated` 2026-07-31: a new filing appears to re-stamp a ticker's older
rows. So a name that filed (or was otherwise touched) after t can lose rows
that were visible at t, usually turning its `sue` into NaN (its latest
surviving filing is then > 100 days old) rather than a wrong value. The pull
reports the share of tickers whose ARQ rows all share one `lastupdated`, to
confirm or refute wholesale re-stamping. The effect grows with the gap between
t and the pull, so it is largest for the late backfill and small for on-time
weekly records.

## 3. New side ledger `prediction_ledger_sue.csv`

In `OUT_DIR` (= `/Users/ggraham/pipe_dream/final/out/reset2026`, the live
store). The v3 and ext schemas are not touched. Version tag
`sue1_icw9sue_2026-09-26`. Columns:

`panel_date, recorded_at, sue_version, ticker, sue, sue_filing_date,
sue_reportperiod, sue_age_days, icw8_score, icw9_sue_score, icw9_sue_rank_pct,
sf1_live_pulled_at, sf1_rows_excluded_lastupdated`

- Append-only. Duplicate-date guard (refuses a panel_date already present).
  Blindness guard: refuses if any eligible cap150 name has a matured
  `forward_return_tradable_40` on that date.
- A manifest entry via `working_panel.record_manifest`.
- **Pairing with v3.** SUE record dates = the v3 `panel_date`s after
  2026-09-08 that have no SUE record yet, written in the same run right after
  v3. The ticker list must equal v3's rows for that date (same order), and the
  recomputed icw8 must equal v3's `ic_weighted_score` to within 1e-12
  (asserted).
- `sue_age_days` is the calendar age of the filing used (kept even when the
  value is stale-NaN); `icw9_sue_rank_pct` is the percentile rank over the
  recorded rows.

## 4. SUE-only SF1 refresh

`final/data/sharadar/sf1_fundamentals.parquet` ends 2026-09-08 and is **not
modified** (WO-14's overlap check and ext's leverage depend on it).
`sharadar_pull_fundamentals.py` is never run with SHARADAR_START/END.

New script `final/src/sue/sf1_eps_live_pull.py`:
- endpoint `https://api.sharadar.com/v1.0/data/fundamentals` (the one the
  existing script uses; the probe confirmed it returns `lastupdated`),
  `dimension=ARQ`, `date.gte` = pull date − 4 years (≥ 12 quarters of history
  for the 8-D sd), `limit` 10,000 with offset paging;
- keeps ticker, dimension, date, reportperiod, eps, lastupdated; adds
  `pulled_at` (local wall-clock ISO time of the pull);
- one fresh pull = one consistent split basis; never unioned with the
  09-08 file;
- hard cap **15 API calls per pull**: if paging would need a 16th call it
  aborts and writes nothing;
- writes `final/data/sharadar/sf1_arq_eps_live.parquet` atomically: temp
  file → validate (ARQ only, non-empty, no null keys, max date ≥ the pull
  date − 7 days, row count sane) → replace, with a dated backup
  `sf1_arq_eps_live_<old pulled_at date>.parquet` when replacing;
- the API key comes only from `SHARADAR_API_KEY` in the environment, is never
  printed or written; missing key → BLOCKED with the command to run.

**Weekly path.** `record_weekly.py` runs the pull itself (subprocess) only
when there is at least one SUE date to record AND the live file is missing or
its `pulled_at` date does not postdate the latest SUE target date. It pulls at
most once per run. A run with nothing to record never pulls.

**Freshness (preflight, per SUE date t):** live file `pulled_at` date > t, and
the live file's max `date` ≥ prev_td(t).

**Basis validation (preflight, once per run):** on (ticker, date,
reportperiod) keys present in both the live pull and the 09-08 file (ARQ,
first row per key), eps must agree (both NaN, or |live/old − 1| ≤ 1e-9, or
both 0). A disagreement is allowed ONLY for tickers with a split or reverse
split since 2026-09-08: `action == split` rows in
`final/data/sharadar/actions.csv` dated after 2026-09-08, or WO-14's
`split_like_blocked` list (`out/reset2026/downcap_v2/refresh_report_2026-09-24.json`).
Any other mismatch → STOP (nothing written) and report. Keys present in only
one file are counted and reported, not failed.

## 5. record_weekly.py hook (WO-14 path)

`refresh_working_panel.py --record-weekly` → `record_weekly.py`:
- v3/ext/hedge rules unchanged (complete ISO weeks only).
- SUE dates as in section 3; one SUE record per ISO week.
- `recorded_late` (> 7 calendar days between panel_date and the SUE record's
  own `recorded_at`) goes to the `ledger_record_log.csv` sidecar with ledger
  `prediction_ledger_sue.csv`.
- If v3's record for that date carries an `incomplete_week` annotation, an
  append-only `incomplete_week` row for `prediction_ledger_sue.csv` is added to
  `ledger_record_annotations.csv`.
- The sue CSV (and the annotations CSV) join the prefix-hash set; the sue CSV
  joins the one-record-per-ISO-week check and the "weeks still missing" check.
- PREFLIGHT, before anything is written, for every date this run will record
  (existing v3 dates and new v3 dates): SF1-live freshness, basis validation,
  blindness, the backfill gate (section 7) where it applies, and the full SUE
  rows are built. If SUE cannot be recorded, nothing is written.
- `ledger_panel_manifest.json` cannot pass a byte-prefix check
  (`record_manifest` rewrites the whole JSON, so closing braces move). It is
  checked key by key instead: every pre-existing (ledger, panel_date) entry is
  unchanged and the only additions are `prediction_ledger_sue.csv` entries.

## 6. Scoring and status (`final/src/sue/sue_forward.py score|status`)

**Primary statistic, per matured date d:**
gain(d) = Spearman(icw9_sue_score, r) − Spearman(icw8_score, r), on the
recorded rows where both scores are finite and r is finite (≥ 20 names),
r = raw `forward_return_tradable_40` for d from the working panel.

Descriptive only (never a gate): the same difference on beta-adjusted
returns (r − beta_252 · SPY 40d, beta_252 from v3's row, SPY from the working
outcome cache) and on both-sides sector-demeaned data (score and r demeaned
within sector, then Spearman).

**Counted dates.**
- Anchor = the first SUE record that is not `recorded_late`, not annotated
  `incomplete_week`, and has finite-`sue` coverage ≥ **70%** of its rows (the
  screen had 82.5%).
- After the anchor, greedy: each counted date is the earliest eligible record
  ≥ 40 trading days after the previous counted date (the WO-10 rule).
- Records that are late, incomplete_week, or below the 70% coverage floor
  are never counted (they are descriptive only).
- Trading calendar: the dates of `data/benchmarks/IWM_live.csv` (forward_hedge's
  calendar) when that file exists; otherwise the working panel's date
  calendar. When both exist they must agree on their overlap, else status
  refuses.

**Verdict,** read ONCE, on the first 6 counted dates, when all 6 have matured:
- mean gain > 0 → **PROMOTE-CANDIDATE question to Gabe**;
- mean gain ≤ 0 → **KILL / DEAD** (SUE family closed);
- fewer than 6 matured counted dates → **INSUFFICIENT**.
Counted dates after the sixth are descriptive.

Scoring is blind on every current date: `score` refuses a date with no matured
label and writes nothing for it.

## 7. Backfill decision rule (W38 = 2026-09-18, W39 = 2026-09-24)

These two v3 dates predate WO-15. Both are backfilled through the
record_weekly hook ONLY if ALL of these hold for BOTH dates:
- (a) the SUE ticker set equals v3's rows for that date, and icw8 matches v3's
  `ic_weighted_score` to 1e-12;
- (b) the lastupdated filter is small: the share of that date's v3 tickers
  whose `sue` changes (finite/NaN status, or value by more than 1e-12) between
  the filtered and the unfiltered (datekey-only) live rows is **≤ 5%**; the
  excluded row count is reported alongside;
- (c) basis validation passes.

If any check fails, nothing is backfilled and the ledger starts at the next
complete week. Either way W38 is `recorded_late` (recorded ≥ 8 days after
09-18) and W39 is `incomplete_week`, so both are descriptive only and can
never be counted dates. Expected first countable record: W40 (panel date
~2026-10-02), recordable once the panel has a W41 date (~10-05).
`refresh_working_panel.py` is not run by this work order.

## 8. Checks reported with the results

Weights reproduction; selftest reproduction (max abs diff vs
`sue_factor_v2.parquet` on 2015-06-15 with the 09-08 file as source); AAPL
hand-check on the live file (latest ARQ filing date matches its 10-Q cadence);
API calls used; basis-validation mismatches; lastupdated exclusions; rows and
coverage per recorded date; prefix hashes unchanged for every pre-existing
ledger/sidecar (and key-by-key for the manifest); a second record_weekly run
is a no-op; score/status say blind / INSUFFICIENT. Every sue `recorded_at` is
later than this document's commit time.

---

## Results

(Written after the pre-registration commit. Not yet filled in.)
