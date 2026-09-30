# WO-27-io-fwd: icw10_io forward side ledger (io_gap recorded next to icw9_seas)

Date: 2026-09-29. Work order WO-27-io-fwd (COO). Branch
`worktree-agent-a666100e5ef9db728`, based on `integration` 9bdbfa7 (contains
the io_gap screen b451e52/b6b6b64 and the WO-26-io hold-out read 9bdbfa7).

**Status: PRE-REGISTERED.** Sections 0 to 8 were committed before any io
forward-ledger record was written anywhere, including the scratch store of
the isolation harness. After that commit they are not edited. Results go only
in the Results section at the end.

## 0. Decision and scope (Gabe, D-IO, 2026-09-29)

Gabe's words, relayed by the COO: **"push it this is very good"**.

This is his in-the-moment OK to deploy the forward-column **recording path**
to the live checkout, following the WO-15 SUE precedent. It covers nothing
else:
- **Live picks: unchanged.**
- **Live weights: unchanged.** The Theoretical model stays icw9_seas; icw8 and
  the blend are untouched.
- **App primary view: unchanged.** An optional side-ledger display may be
  landed on `app` but is **not** deployed (left for Gabe).

Trial count: family "overnight/intraday decomposition", **trial 1** (spent in
the b451e52 screen; read #9 was a read of the same trial). This forward ledger
is forward confirmation of that trial. It is **not a new trial**, and no
variant, lookback, sign or weight is chosen here.

**What ran before this commit.** None of these read a label value (the only
label touch is the blindness count inside `seas_forward.v3_cross`), and none
wrote a record:
- `io_gap_live.py`: selftest, AAPL/TPB/WHLR hand checks, the steady-state
  check, and Gate A;
- `io_forward.py selftest`;
- `record_weekly.py --plan`.

Gate A used 9 Sharadar API calls (cap 10). Numbers are in section 7.

## 1. Live `io_gap` (`final/src/overnight/io_gap_live.py`)

**Definition.** The frozen b451e52 definition in
`final/src/overnight/build_io_gap.py`, **imported, not re-implemented**.
`git diff b451e52 9bdbfa7 -- final/src/overnight/build_io_gap.py` is empty.
- Imported functions: `daily_components` (r_id, r_on and every validity
  filter), `market_calendar` (SEP dates with ≥ 1000 tickers) and
  `io_gap_for`.
- Imported constants: WINDOW 252, MIN_VALID 200, MAX_ABS_LOG 0.7,
  MAX_GAP_DAYS 7 and CAL_MIN_TICKERS.
- The factor: io_gap(i, t) = 252 · mean over valid days in the 252 market
  days ending at t of (r_id − r_on). NaN when fewer than 200 days are valid.
  Sign +1.

**Where it runs.** At score time, from the live SEP month files
`data/sharadar/panel/stocks/<YYYY-MM>.parquet` for months t−14 .. t. No panel
column is added and no stored row changes.

**Loader.** Local, because the frozen `load_sep` is bound to 2005-01..2019-12
and asserts rows < 2020-01-01. It uses the same columns, dtype, sort and
`drop_duplicates(keep="last")`. The selftest asserts it equals `B.load_sep`
row for row on in-era files.

**PIT.**
- Rows are filtered at read to date ≤ t. The frozen definition uses close_t,
  which is known before the label's entry at open[t+1].
- On the materialized frame, every row is asserted ≤ t, and the last price
  date of every finite value is asserted ≤ t.
- Also asserted: ≥ 253 market days are loaded before t, and the load starts
  more than 7 days before the first in-window day.
- A missing month file, or a t that is not a market date, raises.

### Basis guard (Gate A; the selftest cannot see this)

A month file is written whole by one pull (`sharadar_pull_pit_panel.write_month`).
`open`, `close` and `closeadj` are re-based to that pull. The Retrain top-up
re-pulls only from the resume month. Today, 2005-01..2026-08 come from the
2026-09-09 bulk pull (mtimes 05:03-05:05 UTC) and 2026-09 was re-pulled later
(several times on 2026-09-29).

The only cross-row quantity in io_gap is closeadj_prev in r_on. A
**mismatched boundary** is a row d whose ticker's previous SEP row sits in a
different month file whose mtime differs from d's file by more than
**6 hours**. On such a row:
- R_un = log(closeunadj_d / closeunadj_prev). Raw prices carry no basis.
- R_adj = log(closeadj_d / closeadj_prev), as stored, on mixed bases.
- **Splice.** If R_adj − R_un is inside [log 0.8, log 1.25] (WO-14's
  split band; this is dividend-scale basis drift), then r_tot(d) := R_un and
  r_on = R_un − r_id. The frozen validity rules are then re-applied: open/close
  finite > 0, volume > 0, open within [low, high], a prev row ≤ 7 days back,
  |r_id| ≤ 0.7, |r_on| ≤ 0.7, and closeunadj finite > 0 on both rows.
- **Drop.** Otherwise the discrepancy is split-like or ADR-ratio-like, or
  closeunadj is missing. Row d is then NOT VALID, like `no_prev`.

Every other row lies within one file, so on one basis. The splice is exact
unless an event goes ex on d itself: a dividend on d is then missed for that
one day, and a split on d is dropped.

In-era, all files come from one bulk pull, so the guard never fires there;
the selftest asserts 0 guarded rows. The guard is part of the frozen live
implementation. It is not a new variant of the factor, because it reproduces
the frozen value computed on a consistent basis (section 7, Gate A).

## 2. Frozen weights (ICW10_IO_WEIGHTS)

Copied **verbatim** from integration's
`final/out/overnight/io_gap_holdout_report.json` → `weight_rule_check.icw10`.
They are not re-derived. The icw9_io dict is not used.

| factor | icw10_io | live icw9_seas |
|---|---|---|
| momentum_12_1 | +0.0305 | +0.0402 |
| pct_from_high_252 | +0.0080 | +0.0105 |
| volatility_60 | −0.0080 | −0.0105 |
| gross_profitability | +0.3657 | +0.4808 |
| accruals | −0.0999 | −0.1314 |
| net_issuance_pct | −0.0859 | −0.1129 |
| days_to_next_filing_seasonal | −0.0080 | −0.0105 |
| short_interest_days_to_cover | −0.0080 | −0.0105 |
| seas | +0.1467 | +0.1928 |
| **io_gap** | **+0.2393** | — |

Checks, asserted by `io_forward.weight_checks()` on every plan. A failure
skips io, isolated, and never touches the other ledgers.
- (a) The frozen rule (`prediction_ledger.icw_rule`) on the in-era t's
  (8 × `ICW9_T_USED`, `ICW.SEAS_T` 2.83557806966033, io_gap
  3.9953088782434265) reproduces ICW10_IO_WEIGHTS to 4 dp.
- (b) The same rule without io_gap reproduces the live
  `PRODUCTION_WEIGHTS_V9_SEAS` to 4 dp.
- (c) Exact: the unrounded icw10 with io_gap dropped and renormalized equals
  the unrounded icw9_seas rule to 1e-12.
- (d) The **rounded** icw10 with io_gap dropped and renormalized is within
  **2e-4** of the live icw9_seas weights. The bound is derived from 4 dp
  rounding amplified by 1/0.7607. The factor order must also equal
  icw9_seas's.

Results before this commit:
- (a), (b) and (c) are all 0.0.
- (d) max 1.05e-4 (momentum 0.040095 vs 0.0402). Seas renormalizes to
  0.192849 (live 0.1928) and gp to 0.480741 (live 0.4808). **PASS.**

Scoring: `ICW.compute_composite_ic_weighted(cross, weights=ICW10_IO_WEIGHTS)`
over the WHOLE eligible cap150 cross-section (SPAC rule, rank_z as in v3). Rows
are then subset to v3's rows. icw9_seas is recomputed in the same file with
`seas_forward.WEIGHTS`, the same object the seas ledger uses.

## 3. Side ledger `prediction_ledger_io.csv`

In `OUT_DIR` (= `/Users/ggraham/pipe_dream/final/out/reset2026`, the live
store). Version tag `io1_icw10io_2026-09-29`. Columns:

`panel_date, recorded_at, io_version, ticker, sector, seas, io_gap, io_nvalid,
icw8_score, icw9_seas_score, icw10_io_score, icw10_io_rank_pct`

**Rows.** The same cap150 v3 rows the seas ledger scores
(`seas_forward.v3_cross`), in the same order.

**Pairing.**
- icw8 must equal v3's `ic_weighted_score` to 1e-12 (`seas_forward.check_pairing`).
- icw9_seas must equal the seas ledger's `icw9_seas_score` for the same date
  **exactly** (diff 0.0, NaN pattern equal, same tickers in the same order).
  The CSV is read with `float_precision="round_trip"`.
- The seas pairing is **mandatory at record time**, so an io record for date
  d exists only if the seas record for d exists.

**Dates.** Each v3 panel date **after 2026-09-24** with no io record, which is
seas's START_AFTER. That means complete ISO weeks only, one record per ISO
week, following v3 under the WO-14 rules.
- **No backfill.** The seas ledger has no record yet, and 2026-09-18 and
  2026-09-24 would be `recorded_late` in any case.
- **Target first week: 2026-W40.** Its panel date is expected to be
  2026-10-02. It can be recorded once the panel has a W41 date (about 10-05).
- **The W40 on-time window closes about 2026-10-09.** `recorded_late` means
  more than 7 calendar days between `panel_date` and `recorded_at`.

**Guards.** Each of these, if it fails, produces a skip; none stops the run.
- Duplicate-date guard.
- Blindness guard: any eligible cap150 name with a matured label refuses the
  date.
- Seas coverage ≥ 60% (seas's own floor).
- At least 100 rows.
- **io_gap coverage ≥ 70% of the date's rows**, else the date is SKIPPED.
  In-era coverage was 96.5%; live on 2026-09-24 it is 96.7%.
- A manifest entry.

**Sidecars.**
- `recorded_late` goes to `ledger_record_log.csv`.
- `incomplete_week` (when v3's record carries it) goes to
  `ledger_record_annotations.csv`, with a WO-27 note.
- The io CSV and `ledger_io_guard_log.csv` join record_weekly's prefix-hash
  set and its one-record-per-ISO-week check.

## 4. Isolation (the WO-15 Addendum A / WO-20 pattern, per ledger)

`record_weekly.py` imports io in its **own** `try`, separate from seas. The
live checkout has no `final/src/overnight/` until deploy. Any io failure
skips only the io record, for the run or for one date, is appended to
`out/reset2026/ledger_io_guard_log.csv` (event `io_skipped`), and **never**
stops v3/ext/hedge/sue/seas/blend_seas. That covers:
- import or plan failure;
- the weights check;
- a missing SEP month file;
- any exception;
- coverage below the floor;
- pairing;
- the record step;
- the sidecar step.

The guard log is written by record_weekly itself, so it works even when
io_forward cannot be imported. A skipped date stays on io's to-do list, is
retried on the next run, and is `recorded_late` if it is more than 7 days
old. A record step that raises after appending is reported at the end,
after hedge has recorded (rc 1), as in WO-20.

**Harness** (`final/src/overnight/wo27_isolation_test.py`, run AFTER this
commit, on a scratch copy of the store; never main).
- **Baseline.** Integration's pre-WO-27 `record_weekly.py` on the same
  scratch inputs.
- **Modes:**
  - happy;
  - io import failure;
  - io plan failure;
  - build exception;
  - missing SEP month file;
  - coverage below the floor;
  - record raise;
  - half-write (append, then raise);
  - guard-log failure;
  - seas skipped (so io must skip);
  - a second run, where seas already holds d from an earlier run and io
    records against the CSV.
- **Pass** requires all of the following in every mode:
  - v3/ext/hedge/sue/seas/blend_seas content is identical to the baseline,
    compared with `recorded_at` removed: the same dates, rows and values;
  - v3/ext/hedge are recorded;
  - rc 0, except the half-write mode, where rc 1 is expected;
  - the main store is unchanged, by fingerprint of `out/reset2026`,
    `data/sharadar` top level, `out` top level and the SEP month dir mtimes,
    plus sha1 of the live v3/ext/hedge.

## 5. Metric and decision rules (pre-registered)

- **Label.** r = `forward_return_tradable_40`, which is open[t+1] → close[t+40],
  taken from the working panel.
- **Matured.** The trading calendar (IWM_live dates, which agree with the
  working panel, as in seas) has ≥ 41 dates after `panel_date`, and ≥ 20 of
  the record's rows carry a finite label.
- **Primary, per matured record d:**
  `gain(d) = Spearman(icw10_io_score, r) − Spearman(icw9_seas_score, r)`,
  on the record's rows where both scores and r are finite.
- **Counted records.** Every matured weekly record that is not
  `recorded_late`, not `incomplete_week`, and has io_gap coverage ≥ 70%, in
  record order. Weekly records are all counted. There is no 40-day greedy
  spacing.
- **Paired mean** = the mean of gain(d) over counted records.
- **Read 1 (first review), once,** when 26 counted records have matured:
  - mean over the first 26 **> 0 → KEEP** (report to Gabe; recording
    continues);
  - **≤ 0 → CONTINUE** to read 2.
- **Read 2 (drop check), once,** when 52 counted records have matured:
  - mean over the first 52 **≤ 0 → DROP** (the icw10_io candidate is dead;
    report to Gabe);
  - **> 0 → KEEP** (report to Gabe).
- A KEEP at read 1 does not cancel read 2.
- **No automatic promotion.** Any change to live weights is Gabe's decision.
- **Descriptive only, never a gate:**
  - the both-sides sector-demeaned rank-IC of each score (score and r
    demeaned within sector) and their difference `gain_sector_both`;
  - Newey-West t of the gains with lag 8;
  - per-record rhos.
- **Disclosure.** Weekly records overlap: about 8 per 40-day label window.
  26 records span about 3.3 independent label windows, so read 1 is weak
  evidence and read 2 about twice as strong.
- **Expected timing.** The first counted record is W40 (10-02) and matures
  about 2026-11-30. Read 1 is due about 2027-05; read 2 about 2027-11.
- `io_forward.py score` refuses unmatured dates. `status` prints the state.

## 6. Deploy (after landing on integration)

Additive `git checkout <integration sha> -- <paths>` into the live main
checkout, like 562dab9 (WO-15) and the WO-20-seas-final deploy.
- `final/src/overnight/build_io_gap.py`. It is new in live, the frozen
  definition, and is imported.
- `final/src/overnight/io_gap_live.py`
- `final/src/overnight/io_forward.py`
- `final/src/overnight/wo27_isolation_test.py`
- `final/src/reset2026/record_weekly.py`
- `final/models/2026-09-29-wo27-io-forward-ledger.md`

**Pre-checks:**
- live `record_weekly.py --plan` rc 0;
- live ledger sha1 unchanged (v3 963d5e3b, ext 1eba78b3, hedge 1c0738be);
- every module the new files import is identical between live and
  integration.

The same checks are repeated after the deploy. No Retrain and no Streamlit
restart.

## 7. Checks run before this commit (no labels, no records)

| check | result |
|---|---|
| selftest vs `io_gap_factor_v2.parquet` (guard ON) on 2008-01-02, 2012-12-31, 2015-06-15, 2019-01-02, 2019-12-31 (windows cross year boundaries), every panel ticker | **PASS**: max abs diff 2.5e-14, NaN pattern and io_nvalid exact, 0 guarded rows; loader == frozen `load_sep` |
| AAPL hand check (independent loop code on raw SEP, t = 2026-09-25) | **PASS**: hand 0.2198023193955565 = live, diff 0.0; one spliced boundary day (2026-09-01) |
| TPB hand check (dividend 09-18, splice) / WHLR (1:9 split 09-22, drop) | **PASS**: diff 3.3e-16 / 8.9e-16 |
| steady state, in-era, guard at EVERY month boundary (worst case once all months are re-pulled) | Spearman vs frozen 0.99982-0.99987, coverage unchanged, median abs diff ≤ 1.9e-5; 13-32 split-like drops per date |
| Gate A: cap150 cross-section 2026-09-25 (3,048 names), guarded vs raw | coverage 96.6% both; 460 names changed, median 0, max 0.058 (TPVG, dividend 09-16); Spearman 0.99995; 1 split-like drop (RUSHA, 3:2 split ex 2026-09-01, on the boundary day) |
| Gate A: fresh single-pull consistent-basis recompute (8 calls) | Dividend names in cap150: live guarded vs fresh = INSW 4.8e-6, RWT 2.1e-5, TPVG 1.4e-4 (raw was off by 0.048 / 0.047 / 0.058). AAPL, BNTC, ASX 0.0. Split names (not in cap150): WHLR (1:9) 0.0022 and HUBC (1:25) 0.0004 vs fresh with the same day dropped (penny prices, 3 dp rounding). **PASS** at the tolerance: ≤ 1e-3 for names with window min close ≥ $5; penny names descriptive |
| Gate A: \|overnight return\| > 50% on valid days in the cap150 windows | 51 of 750,979 valid days. Every one is explained: 49 are raw price gaps (open/prev close equal r_on); 2 are VISN special dividends ($10, $5). Of the 51, GPRO 2026-09-01 is on the spliced boundary and equals the fresh pull (0.876 → 1.35). Rate 6.8 per 100k vs in-era 1.7 (2015) and 2.3 (2019), a more volatile recent small-cap set. The rows are in `out/overnight/io_gap_live_outliers_2026-09-25.csv` |
| `open` populated in the live month files 2026-05..09 | 0% NaN, 0% ≤ 0 |
| `io_forward.py selftest` on v3 2026-09-24 (record-time panel backup) | **PASS**: 3,048 rows; icw8 vs v3 9.97e-17; icw9_seas == `seas_forward.build_seas_rows` (diff 0); icw10 == independent score; CSV round trip exact; io coverage 96.7%; Spearman(icw10, icw9_seas) 0.902; top-300 overlap 201/300 |
| `record_weekly.py --plan` (worktree code, live store) | rc 0; every ledger incl. io: missing weeks [] |

## 8. Landmines and disclosures

- **The basis guard depends on file mtime.** Copying month files without
  preserving mtime would hide a mismatched boundary. Re-pulling every month
  (a consistent store) removes the need for the guard.
- **A split with ratio ≤ 2x that goes ex on a mismatched boundary day** is
  dropped. **A dividend that goes ex on that day** is missed for that one
  day. The steady-state check bounds the effect.
- **The 2026-09 month file was re-pulled several times on 2026-09-29** by
  another session, at 20:40 and 20:52 local. Gate A was run against the
  20:52 version.
- **io_gap is not added to the app, the picks or any meta.**

---

## Results

(Written after the pre-registration commit. Sections 0-8 above are unchanged.)

### 2026-09-29 evening: isolation harness PASS 12/12; no live record yet

The pre-registration was committed as **ebd1633** at 2026-09-29T21:12:18-04:00.
Every io row written since then went to scratch stores under
`/tmp/wo27_iso/runs/`. **No io record exists in the live store.**
`prediction_ledger_io.csv` is absent there, and so is `prediction_ledger_seas.csv`:
the seas ledger's first record is also W40.

**Harness** (`final/src/overnight/wo27_isolation_test.py all`), output
`final/out/overnight/wo27_isolation_test.json`:
- The baseline is integration 9bdbfa7's pre-WO-27 `record_weekly.py` on the
  same scratch inputs.
- **All 12 modes PASS.**
- In every mode, v3/ext/hedge/sue/seas/blend_seas content (`recorded_at`
  removed) is identical to the baseline, and so are the record-log rows of
  those ledgers.
- In every mode, v3/ext/hedge recorded 2026-09-18 and the main store is
  unchanged. The fingerprint covers out/reset2026, data/sharadar top level,
  out/ top level, the SEP month dir mtimes and sha1 of v3/ext/hedge.

Mode by mode (the expected skip or record happened in each):
- **happy:** io recorded 3,057 rows, icw9_seas vs the seas CSV max |d| 0.0,
  io coverage 96.5%.
- **io_import / io_plan:** skipped, logged as `plan: …`.
- **io_build:** skipped, logged.
- **io_missing:** the real missing-file path was exercised (2026-03 removed),
  skipped, logged.
- **io_lowcov:** the real 70% floor fired at 48.1%, skipped, logged.
- **io_record:** skipped, logged.
- **io_half:** reported at the end, rc 1, after every other ledger had
  recorded.
- **io_guardfail:** rc 0 with the guard-log path unwritable.
- **seas_skip:** the seas record was missing, so io was skipped at record time
  ("seas ledger has no rows"), logged.
- **second_run:** run 1 skipped io; run 2 recorded io against the seas CSV
  (diff 0.0) and added nothing to any other ledger.

**Iteration 1 of 3** was a code fix to match section 4. It changes no rule.
- The first harness run found two problems:
  - an io import or plan failure was only printed, never written to
    `ledger_io_guard_log.csv`;
  - a non-file guard-log path crashed `prefix_hashes`.
- The fix, in `record_weekly.py`:
  - `plan()` keeps the io plan error, and a real (non-`--plan`) run logs it
    as `io_skipped` with no date;
  - `prefix_hashes` uses `is_file()`.
- Re-run: 12/12.

**Live plan** (worktree code on the live store, 2026-09-29 21:28):
- `record_weekly.py --plan` rc 0. Every ledger, io included, shows missing
  weeks [].
- Live ledger sha1: v3 963d5e3b, ext 1eba78b3, hedge 1c0738be (unchanged).

**First record week: 2026-W40.** The expected panel date is 2026-10-02. It can
be recorded by the first Retrain / `refresh_working_panel.py --record-weekly`
after the panel has a W41 date (≥ 10-05). It is on time only if recorded by
about 2026-10-09.

**Disclosure: a skipped io week is usually lost, not deferred.**
- `second_run` retried on the same panel.
- In live, a skipped io date is retried at the next Retrain, which first
  refreshes the panel. A refresh can change past cross-sections (the
  seas_forward docstring: 5 names added to 09-24).
- The retry then fails v3/seas pairing and logs `io_skipped` on every later
  run. This is conservative, and such a retry would be `recorded_late` and
  never counted anyway.
- **Action:** a Retrain / `--record-weekly` must run between about 10-05 and
  10-09. Otherwise the W40 seas and io records are both late and never count.
