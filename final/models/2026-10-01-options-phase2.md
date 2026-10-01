# WO-35: options Phase 2 results

Date: 2026-09-30 (doc dated 2026-10-01 per the work order). Commissioned by
COO. Branch `worktree-agent-a2af378619405ac32`. Pre-registration:
[`2026-09-29-options-readiness-wo25.md`](2026-09-29-options-readiness-wo25.md)
(sections 3, 4, 5, 6). Nothing in the spec was changed. Iterations used: 0 of 3.

## Update, later on 2026-09-30: retry of 2018-10-17, and a second WO-O1 stop

**State now: WO-O1 still has no number.** The completeness guard passes after
the COO's retry, but the runner crashed part-way through on a holiday-expiry
bug. Nothing was aggregated or written. Sections below this one describe the
first pass and are kept as written, except where marked.

**Retry (data fact, from the COO, with the arrival check re-run here).**
- The COO re-pulled the 10 errored names on 2018-10-17 (COLB, DOV, ENV, EOG,
  EPAM, EPAY, EPC, EPD, EPR, EQC) into `alphavantage_full` with the project's
  pull script. All 10 came back `ok`, identity `verified`. The date's parquet
  went from 460,730 to 463,504 rows (COO's figures, not re-counted here).
- 6 names were never attempted and are still absent (ALLO, ESTC, LEXEB, LTHM,
  PLAN, REZI).
- `check_arrival.py` re-run: overall PASS, **134 of 134** and **91 of 91**
  complete. 6 `error` rows remain (2008-12-17 and 2018-09-19).
- Gate A re-run on the same 225 dates (2026-09-16 still excluded): **11 of 11
  PASS**. Only 2018-10-17 was rebuilt: its chain went from 1,391 to 1,401
  names. Chain partitions now equal the complete-date list (225 and 225).
- **Exp B was not re-run.** Its screen ran with those 10 names missing on that
  one date and was not repeated after the retry. The result stands as
  recorded: 0 of 5 admitted, hold-out read #14 not used.

**WO-O1 second stop: the runner cannot find the expiry when the 3rd Friday is
Good Friday.**
- `run_wo_o1.py --phase2` passed every guard and started. It crashed at entry
  date 2019-03-20 with `ArrowTypeError: ... large_string vs null`, after
  processing 135 of 225 entry dates. The crash is an empty ticker list passed
  to the price loader.
- Cause: `target_expiry` returns the 3rd Friday, and the runner keeps
  contracts expiring on that day or the day after (the pre-2015 Saturday
  listing). On 2019-04-19, 2022-04-15 and 2025-04-18 the 3rd Friday was Good
  Friday, so the monthly contracts are listed as expiring the Thursday
  before. No put matches, and the name list is empty.
- Verified in the chain: 1,373 names have puts expiring 2019-04-18 on entry
  2019-03-20; 1,594 expiring 2022-04-14 on entry 2022-03-16; 1,473 expiring
  2025-04-17 on entry 2025-03-19. The earlier Good Friday cases (March 2008,
  April 2014) are listed as the Saturday and work.
- Phase 1 did not catch this because its 33 dates end in 2010.
- **No WO-O1 number exists.** The crash came before any aggregation.
  `wo_o1_results.json` and the positions file were not written, and the log
  holds only per-date name counts. Entries from 2020 on were never reached,
  so **hold-out read #15 is still not used**.
- **Not fixed here.** The fix touches expiry selection in the frozen runner,
  and there are two candidate behaviours that give different results. That is
  the COO's call, and it must be written into the pre-reg doc and committed
  before the run:
  1. **Accept the holiday-adjusted expiry** (the Thursday, when the 3rd
     Friday is a market holiday). This matches the spec's wording, "the first
     standard monthly expiration", and keeps all 225 entry dates. Settlement
     already resolves to the Thursday close. Recommended.
  2. **Skip the three entry dates.** This runs on 222 dates and departs from
     "entry dates are every monthly date in the pull's plan".
- Whether this counts as an iteration is the COO's ruling. No WO-O1 number
  existed when it was found.

## Update 2, 2026-09-30: holiday-expiry bug fixed; presence scan triggered its stop rule

**State now: WO-O1 still has no number, and hold-out read #15 is still not
used.** The real-label run was not started after the fix.

- **COO ruling:** accept the holiday-adjusted expiry, as a bug fix, not an
  iteration (0 of 3 used). Written into the pre-reg doc, section 4, "Bug
  fix 1". `run_wo_o1.py` now accepts contracts listed on the 3rd Friday, the
  Saturday after it, or, when that Friday is a market holiday, the trading
  day before it. That is the only code change.
- **Four entry dates were affected, not three.** The scan found a fourth:
  2026-05-20, whose 3rd Friday (2026-06-19) is Juneteenth, with the expiry
  listed on 2026-06-18. All four now match: 1,370 names (2019-03-20), 1,592
  (2022-03-16), 1,473 (2025-03-19), 1,579 (2026-05-20).
- **Presence scan** (`presence_scan.py`, `wo_o1_presence_scan.json`, no
  outcomes): names with at least one put at the selected expiry, per entry
  date. Median 1,335. **Minimum 548, on 2008-11-19.**
- **The COO's stop rule (any date below half the median) triggered on seven
  dates:**

| entry date | names with a put | cap2000-eligible names | share |
|---|---|---|---|
| 2008-10-22 | 655 | 687 | 95.3% |
| 2008-11-19 | 548 | 569 | 96.3% |
| 2008-12-17 | 633 | 661 | 95.8% |
| 2009-01-21 | 601 | 630 | 95.4% |
| 2009-02-18 | 567 | 592 | 95.8% |
| 2009-03-18 | 578 | 599 | 96.5% |
| 2009-04-15 | 643 | 665 | 96.7% |

- **Reading:** these are low because the eligible universe shrank in the
  2008-09 crash ($2B and $10 floors), not because puts are missing. As a
  share of eligible names, no date in the 225 is below 92.9% (median
  97.2%). The largest date-to-date fall is 2020-03-18 (961 names, 67% of
  the previous date, 94.5% of eligible), again a universe effect.
- **Stopped as instructed.** The rule was not reinterpreted. The COO decides
  whether the run proceeds.

## Summary (first pass)

| experiment | verdict | deciding number |
|---|---|---|
| Exp B (5 AV option factors) | **KILL (no factor admitted, 0 of 5)** | Best candidate `opt_cw_spread`: composite+candidate earns 3.65%/yr excess, below its shuffle-null p80 of 5.28%/yr (and below the 8-factor composite's 5.36%/yr) |
| WO-O1 (cash-secured puts) | **NOT RUN: stopped at the `--phase2` guard** | 2018-10-17 is 0.989 complete at cap2000 (1,432 of 1,448 names terminal; the bar of 0.99 needs 1,434) |

- Gate A: **11 of 11 PASS** on the 225 planned dates (A1 to A10, plus the new
  presence check A11).
- Hold-out reads: **#14 not used** (nothing admitted, confirm not run).
  **#15 not used** (WO-O1 refused before reading any data).
- **On the Exp B label.** The pre-registration defines no KILL or MIDDLE
  term for Exp B (`PREREGISTRATION.md` "Experiment B" gives screen, admission
  and confirmation only). The pre-registered outcome is "no factor admitted,
  confirmation not run". KILL is this doc's label for that outcome, as the
  work order asks for one of PASS, KILL or MIDDLE.
- **Which rule decided it.** Admission needs three things: the Holm screen,
  the IC gain over the null (both from `PREREGISTRATION.md`), and the
  companion portfolio check (added by the WO-25 doc, section 3 item 7, before
  any number existed, "both it and the IC admission are required").
  `opt_cw_spread` and `opt_os_ratio` pass the first two and fail the third.
  Under the original `PREREGISTRATION.md` text alone, those two would have
  gone to confirmation. See "Notes for the COO".
- Trial tally: Exp B's 5 trials are spent. WO-O1's 6 cells are still
  counted in the pre-registered total of 18, but no number exists for them.

## 1. Data and plumbing

- Data root: `/Users/ggraham/pipe_dream/final/data/alphavantage_full/`
  (read-only). `gate_a.py` now reads `AV_DATA_ROOT`, defaulting to that path.
  That is the only path change. `run_expB.py` and `run_wo_o1.py` read only
  the chain and features that `gate_a.py` writes, so they are unedited.
- `gate_a.py` was run with `--dates` listing the 225 planned dates. The
  off-plan file `date=2026-09-16.parquet` was never built into a chain or
  feature partition.
- Hold-out reads were renumbered in the pre-reg doc before any real-label
  run (#7 becomes #14, #8 becomes #15). The runner code keeps the old strings.

**Facts the COO found when checking the data (recorded as asked, not
re-verified here except where the arrival check covers them):**
- The data came from two machines, joined between 2010-08-18 (Mac) and
  2010-09-15 (Windows). Parquet schemas are identical. 99.5% of names `ok`
  on the last Mac date are `ok` on the first Windows date.
- The COO removed 32 exact duplicate rows (resume re-append) from 2012-11-21
  (DTGF, 2 rows) and 2019-12-18 (ONCE, 30 rows) in the merged copy only.
- 2026-09-16 is on disk but outside the 225-date plan and every window.

**Arrival check (re-run here, `arrival_report.json`): overall PASS.**
- 226 monthly dates on disk, plan 225 (2008-01-02 to 2026-08-19).
- 2008-01 to 2019-01: 133 of 134 complete at cap2000. The one partial date is
  2018-10-17 at 0.989.
- 2019-02 on: 91 of 91 complete.
- 16 `error` rows: 1 on 2008-12-17, 5 on 2018-09-19, 10 on 2018-10-17.
- No exact duplicate rows. Adjusted-deliverable key duplicates (WARN only) on
  5 dates: 2008-07-16, 2010-02-17, 2010-04-21, 2010-11-17, 2019-12-18.
- Exp B screen ready: yes. Confirm ready: yes.

## 2. Gate A on all 225 dates: 11 of 11 PASS

`final/out/options_wo25/gate_a_report.json`. 296,645 name-dates of features.
These are chain facts, not outcome statistics.

| id | result | numbers |
|---|---|---|
| A1 | PASS | AAPL present on 13 of 13 dates in 2008 |
| A2 | PASS | LEHMQ (AV LEH), WAMUQ (AV WM), WB1 (AV WB) in the chain on 2008-08-20; 2008-09-17 N/A (price floor), as in Phase 1 |
| A3 | PASS | parity spot vs closeunadj: LEH 0.6%, WM 1.0%, WB 0.2%; all `verified` |
| A4 | PASS | no WM/WMI cross-assignment; 0 (date, AV symbol) pairs claimed twice |
| A5 | PASS | rr25 > 0 on 92.8% of 218,767 name-dates. By year: lowest 81.3% (2021), 84.6% (2026), 85.4% (2024); highest 99.0% (2009) |
| A6 | PASS | pc_vol_ratio median 0.360 (n = 275,965) |
| A7 | PASS | cw_spread median -0.0197 (2008: -0.0135) |
| A8 | PASS | cap2000 share with a chain 0.974 over 225 dates (min date 0.930); cap500-only 0.771 and cap150-only 0.465 on the first 9 dates |
| A9 | PASS, narrowly | median ATM relative spread: cap2000 0.146 < cap500-only 0.150 < cap150-only 0.224. The cap2000 figure is over 225 dates and the other two over 9 dates in 2008, so this is not a like-for-like comparison |
| A10 | PASS | label formula matches on 400 of 400 sampled rows |
| A11 | PASS | Windows-era named presence, below |

**A11 (new in WO-35, presence only).**
- **SIVB: present.** Sharadar `SIVBQ`, AV symbol `SIVB`, on 2023-02-15.
  Identity `verified` in the pull log (parity spot 317.28 vs closeunadj
  316.75). cap2000-eligible, market cap $18.7B.
- **BBBY: absent, for a legitimate reason.** Sharadar `BBBYQ` was never
  attempted by the cap2000-only pull. It fails both parts of the cap2000 rule
  on every monthly date in the window: 2023-01-18 $3.94 and $317M; 2023-02-15
  $1.93 and $226M; 2023-04-19 $0.46 and $259M. It has no universe row on
  2023-03-22. This is the same price-floor exclusion as WaMu in 2008.

## 3. Experiment B: screen (nominate era, real labels)

`final/out/options_wo25/expB_screen.json`, plus the descriptive breakdown in
`expB_screen_descriptive.json` (written by `expB_descriptive.py`, nominate era
only, no decision taken from it).

- Window 2008-01-02 to 2018-12-19, 133 monthly dates, 147,596 optionable
  cap2000 name-dates. Pool integrity 100.00%.
- The 133 dates include 2018-10-17 (0.989 complete). The pre-reg allows this
  for Exp B (it needs at least 120 complete dates; 132 of these are).
- Binding t is Newey-West lag 39. Lag 2 is shown as descriptive only.
- "IC" is the mean per-date Spearman IC. The screen uses the sector-neutral
  IC. The sign column is the pre-registered direction.

**Screen and IC admission.**

| factor | pre-reg sign | neutral IC | NW-39 t (binding) | NW-2 t (descriptive) | Holm screen | IC gain of 9 vs 8 | IC-gain null p80 | IC admission |
|---|---|---|---|---|---|---|---|---|
| `opt_cw_spread` | + | +0.0158 | +3.54 | +2.16 | pass | +0.00729 (t 2.98) | +0.00012 | yes |
| `opt_rr25` | - | -0.0040 | -0.49 | -0.65 | fail | +0.00025 | +0.00008 | no (failed screen) |
| `opt_os_ratio` | - | -0.0217 | -4.77 | -3.19 | pass | +0.00221 (t 2.55) | +0.00009 | yes |
| `opt_pc_vol_ratio` | - | +0.0079 | +2.94 | +2.47 | fail (wrong sign) | -0.00373 | +0.00009 | no |
| `opt_vrp` | - | -0.0007 | -0.07 | -0.10 | fail | -0.00023 | +0.00004 | no |

Raw (not sector-neutral) NW-39 t: cw_spread +6.09, rr25 -0.84, os_ratio
-2.23, pc_vol_ratio +2.53, vrp +0.33.

**Companion portfolio (required for admission).** Excess vs SPY, %/yr, net
15bp, mean of the 2 interleaved offsets. The 8-factor composite is refit on
each factor's own non-missing rows, so its value differs slightly by row.

| factor | 8-factor composite | composite + candidate | null p80 | companion | **admitted** |
|---|---|---|---|---|---|
| `opt_cw_spread` | 5.36 | 3.65 | 5.28 | fail | **no** |
| `opt_rr25` | 5.12 | 5.10 | 5.13 | fail | **no** |
| `opt_os_ratio` | 5.32 | 5.12 | 5.29 | fail | **no** |
| `opt_pc_vol_ratio` | 4.91 | 3.89 | 5.01 | fail | **no** |
| `opt_vrp` | 5.18 | 5.03 | 5.20 | fail | **no** |

In all five cases adding the candidate lowered the portfolio's excess return
below the 8-factor composite, not just below the null.

**Robustness breakdowns (descriptive).** IC here is sign-aligned: positive
means the pre-registered direction.

| factor | sign-aligned neutral IC by offset | offset sign flips (IC) | companion (9 minus 8) by offset, %/yr | offset sign flips (companion) | years against the sign | largest single-year share of summed IC |
|---|---|---|---|---|---|---|
| `opt_cw_spread` | +0.0099, +0.0217 | 0 | -1.41, -2.02 | 0 | 3 of 11 | 2013: 22% |
| `opt_rr25` | -0.0025, +0.0106 | 1 | -0.15, +0.13 | 1 | 5 of 11 | 2008: 120% (the other years net negative) |
| `opt_os_ratio` | +0.0171, +0.0264 | 0 | -0.40, -0.01 | 0 | 3 of 11 | 2008: 30% |
| `opt_pc_vol_ratio` | -0.0045, -0.0114 | 0 | -1.01, -1.04 | 0 | 8 of 11 | not meaningful: the effect runs against the pre-registered sign |
| `opt_vrp` | +0.0026, -0.0012 | 1 | -0.19, -0.12 | 0 | 7 of 11 | not meaningful: the summed IC is about zero |

**Verdict: no factor admitted, 0 of 5 (KILL).** The confirm stage was not run, and
hold-out read #14 is recorded as **not used**. No 2019+ label was read.

## 4. WO-O1: stopped at the guard, no number exists

Command: `run_wo_o1.py --phase2`, run once. It refused with:

    --phase2 refused: 1 planned monthly dates <= 2026-08 incomplete at cap2000 (first: ['2018-10-17 (0.989)']); WO-O1 runs once, on the full store

The guard was not loosened. No position, P&L or excess number was computed,
and `wo_o1_results.json` does not exist. The per-arm, per-bucket table the
work order asks for is therefore empty.

**What the guard checks (in order, `run_wo_o1.py` `main`):**
1. The pre-reg doc is tracked in git. Passed.
2. `arrival_report.json` exists with overall PASS. Passed.
3. **No planned monthly date on or before 2026-08-31 appears in
   `missing_or_partial`.** A date is complete when at least 0.99 of its v2
   cap2000-eligible names have a terminal log status (`ok` or `no_data`).
   **This is the check that refused.**
4. The chain partitions on or before 2026-08-31 equal the arrival report's
   complete-date list exactly. Not reached. It would also refuse as things
   stand: the chain has 225 partitions and the complete list has 224.
5. `wo_o1_results.json` does not already exist. Not reached.

**The gap on 2018-10-17.** 1,448 cap2000-eligible names. 1,401 `ok`, 31
`no_data`, 10 `error`, 6 never attempted. That is 1,432 terminal, and 0.99
needs 1,434. The date is 2 names short.

**The pre-reg contradicts itself here.** Section 1 says WO-O1 "runs on
whatever is complete and reports the date list". Section 6 and the code say
every planned date through 2026-08 must be complete. The code follows
section 6.

**Second gap, not yet hit: unmatured expiries.** The ruling is to drop
entries whose expiry has not matured in the data. The runner has no such
rule. `SPY.csv` ends 2026-09-30 and Sharadar SEP ends 2026-09-29 (6,338 rows
on 2026-09-18). The last entry (2026-08-19) expires 2026-09-18, so every one
of the 225 entries has matured in both sources and nothing needs dropping. This holds only while 2026-09-16 stays excluded: its
expiry is 2026-10-16, and the runner would settle it early instead of
dropping it.

**Other WO-O1 prerequisites, checked and fine:**
`final/out/seasonality/seas_screen_report.json` is in the worktree, and the
chain and features for all 225 dates are built.

## 5. Notes for the COO

1. **Unblocking WO-O1 needs a COO decision. Two routes:**
   - **Data fix (no spec change).** Re-pull the 10 `error` and 6 unattempted
     names on 2018-10-17 into `alphavantage_full`. Two terminal results clear
     the bar. Then re-run `check_arrival.py`, `gate_a.py` for that date, and
     `run_wo_o1.py --phase2`. Whether a re-pull returns terminal statuses is
     not verified.
   - **Amendment (iteration 1 of 3).** Write into the pre-reg doc that WO-O1
     runs on the 224 complete dates and excludes 2018-10-17, commit it, then
     change the guard to match and remove that chain partition. No WO-O1
     number exists yet, so this would be a pre-result amendment in substance,
     but the doc's rule counts any change after a Phase 2 number exists, and
     the Exp B numbers now exist.
2. **Exp B: what the kill does and does not show.** `opt_cw_spread` and
   `opt_os_ratio` have real rank-IC in the nominate era (neutral NW-39 t of
   3.54 and -4.77, right sign, no offset flips, no single year above 30%).
   Neither improves the decile-within-volatility-quintile book: both lower
   it. The pre-registered rule required both, so neither is admitted. Any
   re-test with a different construction is a new trial.
3. **`short_interest_days_to_cover` has t = NaN in the base composite** on
   these rows, so it enters at the floor weight. This is how the harness
   behaves when a base factor has no usable IC, and it applied equally to
   the 8-factor and 9-factor books. Cause not investigated (inferred: the
   column is empty on the option dates in this window).
4. **NW lag.** The lag-2 t is smaller in magnitude than the lag-39 t for the
   two screening factors (2.16 vs 3.54, 3.19 vs 4.77). Lag 39 was expected to
   be the conservative choice and is not here. This does not change the
   outcome, since the companion check decided it.

## 6. Files

- `final/src/options_wo25/gate_a.py`: `AV_DATA_ROOT` plumbing and check A11.
- `final/src/options_wo25/expB_descriptive.py`: new, nominate-era breakdowns.
- `final/out/options_wo25/arrival_report.json`: arrival check on
  `alphavantage_full`.
- `final/out/options_wo25/gate_a_report.json`: Gate A on 225 dates.
- `final/out/options_wo25/expB_screen.json`: Exp B screen (real labels).
- `final/out/options_wo25/expB_screen_descriptive.json`: breakdowns.
- Not produced: `expB_confirm.json`, `wo_o1_results.json`.

Reproduce, from the checkout root:

    P=/opt/anaconda3/envs/pipe_dream/bin/python
    $P final/src/options_wo25/check_arrival.py --data-root /Users/ggraham/pipe_dream/final/data/alphavantage_full
    $P final/src/options_wo25/gate_a.py --dates <the 225 planned dates, comma separated; omit 2026-09-16>
    $P final/src/options_wo25/run_expB.py --phase2 --stage screen
    (cd final/src/options_wo25 && $P expB_descriptive.py)
