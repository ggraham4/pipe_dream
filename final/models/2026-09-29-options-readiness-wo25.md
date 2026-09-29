# WO-25: options readiness, Phase 1 (pre-registration)

Date: 2026-09-29. Commissioned by COO. Branch `wo25-options-readiness`.
Status: **pre-registration**. This doc is committed before any Phase 2 number
exists. Phase 2 runs once the Alpha Vantage (AV) monthly cap2000 pass has been
copied from Gabe's Windows machine to this Mac.

## 0. What Phase 1 may and may not compute

The Mac holds 33 monthly AV dates (2008-01-02 .. 2010-08-18). That is
nomination-era data. **Phase 1 computes no statistic that relates an option
factor or put P&L to realized forward returns on real labels.** That rules out
IC, t, portfolio return, Sharpe and excess return.

- The runners are exercised only on within-date shuffled labels or on pure
  noise labels. Every file those runs write carries `_SHUFFLED_TEST` in its
  name.
- The WO-O1 aggregate P&L is tested only on noise labels. A within-date
  shuffle of stock returns keeps each date's market move, so aggregate
  short-put P&L on shuffled labels would still show the real 2008 crash.
- **Exception (required by the WO):** the named LEH, WM and WB settlement
  check computes real payoffs for those three names' contracts only, and
  never an aggregate. It is a data-integrity check (survivorship), not a
  performance number.
- The Gate A checks are descriptive facts about the chain and its features.
  None of them uses returns. The label-basis check recomputes the formula
  and reports only a match rate, never a label value.

## 1. Data-arrival checklist (Windows -> Mac)

**Before copying:**
1. On Windows, stop the pull first (`pkill -f av_options_pull.py`, or end the
   task). A date's parquet is written before its log rows are committed.
   Copying mid-write can give a parquet that doesn't match the log.
2. On the Mac, back up the current 33 dates and the log:
   `cp -a final/data/alphavantage/options final/data/alphavantage/options_backup_2026-09-29`
   and
   `cp -a final/data/alphavantage/pull_log.sqlite final/data/alphavantage/pull_log_backup_2026-09-29.sqlite`.

**Copy exactly these paths** (Windows data root = the pull's `--data-root`,
default `final/data/alphavantage`):

| Windows source | Mac destination |
|---|---|
| `<data-root>/options/monthly/date=*.parquet` (all files) | `/Users/ggraham/pipe_dream/final/data/alphavantage/options/monthly/` |
| `<data-root>/options/weekly/date=*.parquet` (if any) | `/Users/ggraham/pipe_dream/final/data/alphavantage/options/weekly/` |
| `<data-root>/pull_log.sqlite` | `/Users/ggraham/pipe_dream/final/data/alphavantage/pull_log.sqlite` |
| `<data-root>/pull.out` (optional, for the record) | `/Users/ggraham/pipe_dream/final/data/alphavantage/pull_windows.out` |

Don't copy any `*.tmp` file. If one exists, the date it belongs to was in
progress. Resume the pull on Windows for that date, or leave it out.

**Then run the integrity script:**

    /opt/anaconda3/envs/pipe_dream/bin/python final/src/options_wo25/check_arrival.py

It writes `final/out/options_wo25/arrival_report.json` and exits non-zero on
any FAIL. Its checks:
- It counts dates per pass on disk and in `pull_log`, and finds the first and
  last date.
- It lists missing monthly dates against the pull's own plan
  (`av_options_pull.build_dates`). Results are split into two segments:
  2008-01..2019-01 (Exp B nominate, WO-O1 pre-2020) and 2019-02 onward
  (Exp B confirm, WO-O1 2020+).
- For each monthly date, it gives the share of v2 cap2000-eligible names that
  have a terminal log status (`ok` or `no_data`). A date is complete when
  that share is at least 0.99.
- It counts `error` rows in `pull_log`.
- It checks for half-written dates in four ways:
  - no leftover `*.tmp`;
  - every parquet footer reads, and every file has more than 0 rows;
  - no exact duplicate rows within a date (a crash between the parquet
    replace and the log commit makes resume re-append);
  - the set of tickers in each parquet equals the set logged `ok` for that
    date.
  - Exact duplicate rows are a FAIL. A (ticker, contractID) key that repeats
    with different quotes is only a WARN: it is vendor data, handled by F0 in
    section 4.
- It runs `PRAGMA integrity_check` on `pull_log.sqlite`.

Phase 2 gates on it: Exp B's screen needs at least 120 of the ~132
nominate-era monthly dates complete at cap2000 (pre-registered in
`era_transfer.py`). The confirm stage needs the 2019-02..2026-08 segment
complete. WO-O1 runs on whatever is complete and reports the date list.

## 2. Gate A (on the 33 Mac dates, then again in Phase 2 on all dates)

Script: `final/src/options_wo25/gate_a.py`. It rebuilds the unified chain and
the features into `final/out/options_wo25/` (chain/, features parquet). It
imports `build_option_chain_unified.py` and `build_av_options_features.py`
without editing them, and never writes into `final/data/`. Each item is
named before it runs, with its expected value:

| id | check | expected |
|---|---|---|
| A1 | AAPL present with a verified chain on every 2008 date | 13/13 dates |
| A2 | LEH (Sharadar LEHMQ, AV LEH), WM (Sharadar WAMUQ, AV WM) and WB (Sharadar WB1, AV WB) present on 2008-08-20; WAMUQ and WB1 also on 2008-09-17 | present |
| A3 | identity of A2 names: put-call-parity spot vs Sharadar closeunadj, from `pull_log` | abs err < 5% (the chain's STRICT_TOL) |
| A4 | symbol reuse: 2008-08..2009-01, Sharadar WM (Waste Management) must map to AV WMI, never WM; AV WM must map only to WAMUQ; no (date, AV symbol) claimed by two Sharadar tickers after `av_keep` | no cross-assignment |
| A5 | rr25 > 0 share of non-null name-dates | majority (> 0.5) |
| A6 | pc_vol_ratio median | 0.30 to 0.45 |
| A7 | cw_spread median | slightly negative (builder documents about -0.022 in 2008) |
| A8 | coverage by tier: share of eligible names with a chain, **only on dates where that tier was attempted** (cap150/cap500 on the first 9 dates; cap2000-only from 2008-09-17) | cap2000 high (report); lower tiers lower |
| A9 | median ATM relative spread (`opt_spread_atm`) by tier | rises as cap falls |
| A10 | label basis: `forward_return_tradable_40` equals close[t+40]/open[t+1]-1, recomputed from SEP per ticker (own trading days), sampled rows on the AV dates | match rate >= 0.99 (no label values printed) |

Results are in section 8. They are chain facts, not outcome statistics.

## 3. Experiment B (AV option factors): runner and clarifications

Script: `final/src/options_wo25/run_expB.py`. It implements the text in
`PREREGISTRATION.md` "Experiment B" and "Amendment 1" (cap2000 primary). k=5:
`opt_cw_spread` +1, `opt_rr25` -1, `opt_os_ratio` -1, `opt_pc_vol_ratio` -1,
`opt_vrp` -1. Nominate 2008-01..2018-12, confirm 2019-01..2026-08,
`av_monthly` rows only, label `forward_return_tradable_40`.

**Clarifications.** The pre-reg text is silent on these points, or the
earlier `era_transfer.py` implementation deviates from it. Each is stated
here before any number exists:

1. **Panel:** `composite_panel_v2.parquet` with the v2 `eligible_cap2000`
   flag (the working panel since WO-11). `era_transfer.py` used v1. The
   Amendment 1 pool-integrity check is kept: at least 99% of v2
   cap2000-eligible name-dates must be in the panel.
2. **Base composite:** the 8 factors of `era_transfer.BASE_SIGNS` (audit set,
   asset_growth dropped). Weights come from the IC-shrinkage rule
   `w = s * max(0.1, |t| - 1)`, normalised. They are fit on the matched
   optionable rows of the nominate era, using raw pooled NW t, as the
   pre-reg's "composite" was defined.
3. **Admission weight (bug fix vs `era_transfer.py`):** that code divides the
   candidate's weight by the sum of the already-normalised base weights,
   which is 1. So the candidate entered with a raw t-unit weight (for
   example 2.0) next to unit-sum base weights. Here all 9 weights (8 base +
   candidate) are refit together with the same rule and normalised. The
   candidate's t is its raw pooled NW t, the same basis as the base factors.
   Sector-neutral t is used only for the screen (Holm).
4. **Null (fix vs `era_transfer.py`):** each of the 20 within-date shuffle
   draws recomputes the shuffled candidate's t and refits all 9 weights, as
   WO-4 and WO-18 do. `era_transfer.py` kept the real candidate's weight on
   the shuffled column, which depresses the null.
5. **NW lag:** kept at 39 as implemented. **Flag for COO:** on ~132 monthly
   observations, a 40-trading-day label overlaps only about 1 to 2 adjacent
   dates. Lag 39 makes the t very conservative (at most, it inflates the
   standard error). It is not changed silently. If COO wants lag 2, that is
   an amendment and must be committed before Phase 2.
6. **Holm:** two-sided normal p on the sector-neutral t, Holm step-down at
   0.05 over k=5, and the sign must match the table (as in the pre-reg).
7. **Companion portfolio check (added by WO-25; both it and the IC admission
   are required for admission):**
   - Books: composite (8, refit on matched rows) vs composite+candidate (9,
     refit), on the same optionable cap2000 name-dates. Rows where the
     candidate is NaN are dropped from both.
   - Construction: `composite.pick_decile_volq` (the project's usual
     construction, decile within volatility quintile, inverse-vol weights),
     net 15bp via `run_backtest.turnover_net_return`.
   - Returns: `gross_return_40` from `outcome_cache_v2.parquet` (entry at
     open[t+1], exit at close[t+40], delisting floor).
   - Benchmark: SPY 40-day return from the same cache.
   - Offsets: monthly dates are ~20-25 trading days apart, so non-overlapping
     40-day windows are every other monthly date. The metric is the mean over
     the 2 interleaved offsets of mean(net - SPY) x 252/40.
   - Null: 20 within-date shuffles of the candidate, weights refit per draw.
   - **Pass:** composite+candidate > null p80.
   - Confirmation (one shot, frozen weights, 2019-01..2026-08): the IC gain
     rule as pre-registered, AND the companion difference (9 minus 8) > 0.
8. **Phase 2 guards:** real labels run only with `--phase2`. That flag
   requires:
   - this doc tracked in git (`git ls-files --error-unmatch`);
   - `arrival_report.json` with overall PASS;
   - at least 120 nominate-era dates.
   The confirm stage refuses to overwrite its output (one shot).

## 4. WO-O1: put-selling backtest spec

Script: `final/src/options_wo25/run_wo_o1.py`.

**Universe and entry.**
- cap2000 only: v2 `eligible_cap2000` on the entry date t, and an AV monthly
  chain that passes the identity filter (`av_keep`) on t.
- Entry dates are every monthly date in the pull's plan (3rd Friday - 30 days,
  rolled forward), as pulled.

**Expiry.** The first standard monthly expiration (3rd Friday; pre-2015 listed
as the Saturday after) with at least 14 calendar days to expiry. For every
date except 2008-01-02 (17 DTE), this is the ~30 DTE target of the pull
calendar.

**Arms.**
- (a) All eligible names with a tradable contract in the bucket.
- (b-icw8) Top quintile by the icw8 score.
  - The score is computed on the t-1 cross-section, the previous trading
    day in the panel. The option fill is the EOD quote of t, and a score
    built from close[t] can't also be traded at close[t].
  - The score is ranked over all v2 cap2000-eligible names on t-1, then the
    top quintile is cut within arm (a)'s tradable pool for that bucket.
- (b-blend) **BLOCKED** (section 4.1).

**icw8 out of sample.**
- For entry dates before 2020: split-half OOS weights, exactly WO-18's
  (weights fit on odd years score even years, and vice versa). They are
  read, not refit, from `final/out/seasonality/seas_screen_report.json`
  (`portfolio.weights8_fit_odd` / `weights8_fit_even`, fit on v2 col c
  cap150, 2007-2019). Reusing them means no new fit and no new label read.
- For entry dates in 2020 or later: frozen `PRODUCTION_WEIGHTS` (fit
  2007-2019, out of sample in time).

**Strikes.** Put-delta targets -0.20, -0.30 and -0.45. The delta is Black-Scholes
recomputed from the mid (the unified chain; AV's own greeks aren't trusted).
The strike is the listed put on the chosen expiry nearest the target, with
|delta - target| <= 0.075. If that contract fails the stale filter, take the
next-nearest one inside the tolerance. If none qualifies, there is no trade
for that name-date-bucket.

**Stale and implausible quote filter (defined before any run).** AV quotes
carry no quote or last-trade timestamps, so a staleness date can't be
checked. That is stated, not worked around. A contract is dropped when:
- F0: its (sharadar_ticker, contractID) repeats on that date with different
  quotes. AV returns adjusted-deliverable contracts (AIG's 2009 1:20 reverse
  split, CAH's CareFusion spin-off, ...) under the standard OCC id: 1, 45 and
  38 such rows on 2008-07-16, 2010-02-17 and 2010-04-21. The standard row
  can't be told apart, so all rows of the key are dropped.
- F1: bid <= 0, or ask <= bid;
- F2: `bid_size` = 0. This proxies a non-live bid, in place of a quote
  timestamp. **Amended (Amendment 1, below): F2 applies only on name-dates
  where AV populates bid_size.**
- F3: no mid IV solves (mid outside the no-arbitrage band);
- F4: bid < intrinsic (K - S)+ - 0.05. A bid below intrinsic means the quote
  or spot is stale.
- F5 (monotonicity): bid(K) > ask(K_next), where K_next is the next higher
  strike of the same put expiry. A lower-strike put can't be worth more.
- F6 (surface smoothness, same put expiry): |IV(K) - IV_nb| > max(0.10,
  0.30 x IV_nb), where IV_nb is the mean mid-IV of the adjacent listed
  strikes that have an IV.

Put-call parity is deliberately NOT used as a richness test. Hard-to-borrow
financials, and the SEC short-sale ban of 2008-09-19, break parity on exactly
the puts that later blow up. A parity filter would be survivorship-flattering.

The filter's drop rate is reported by ATM-IV quintile (no outcome data). If
drops concentrate in the top IV quintile, that is a flag.

**Fill and margin.**
- Sell 1 contract at the bid on t (EOD). That pays the half-spread against
  the mid.
- Cash-secured: collateral = 100 x K. Collateral earns the 3m T-bill rate
  (`treasury_yields.csv` y3m on t) over the holding days.

**Settlement.**
- S_T = Sharadar `closeunadj` on the last trading day on or before the
  expiration date.
- Payoff per original contract = 100 x max(K - r x S_T, 0).
- r = cumulative split ratio from t to the settlement day:
  r = (close_T / closeunadj_T) / (close_t / closeunadj_t), from Sharadar
  split-adjusted `close`.
- This is the OCC contract adjustment. For an n:m split the deliverable
  becomes 100 x r shares and the strike K/r, which gives the same payoff.
- Special dividends and spin-off deliverables are not adjusted (limitation).

**Assignment.**
- If r x S_T < K, the put is assigned. The seller buys 100 x r shares at K,
  and they are liquidated at S_T less 7.5bp (half the project's 15bp round
  trip).
- Early assignment of American puts is not modeled separately. For a
  cash-secured put held to expiry, early assignment then holding to T has the
  same P&L up to dividends received, which are ignored (conservative).

**Delisting during the holding period.** If the Sharadar series ends before
the settlement day, S_T is the last available `closeunadj` and r is measured
to that day. This is the `execution.py` delisting exit floor.

**Named survivorship check (hard fail).**
- The following puts must be present in arm (a)'s pool, in at least one
  bucket, or the run fails loudly:
  - LEHMQ (AV LEH), WAMUQ (AV WM) and WB1 (AV WB), entry 2008-08-20, expiry
    2008-09-20;
  - WAMUQ and WB1, entry 2008-09-17, expiry 2008-10-18, where each is
    cap2000-eligible with a chain that day.
- The check verifies:
  - S_T equals the expected Sharadar close;
  - payoff = 100 x max(K - r x S_T, 0) exactly;
  - LEH (entry 2008-08-20) loses at least 90% of (K - premium) (LEHMQ closed
    0.22 on 2008-09-19).
- **Spec mismatch reported to COO:**
  - WAMUQ closed 4.25 on 2008-09-19 (entry close 4.10). WB1 closed 18.75
    (entry close 14.90). So the WM and WB puts sold 2008-08-20 do NOT lose
    near-totally at the September expiry. WaMu was seized on 2008-09-25,
    after that expiry, and WB was bought by Wells Fargo, never going to 0.
  - The WM near-total loss shows up in the 2008-09-17 entry (October expiry),
    which is why that cycle is in the check.
  - The check asserts presence and exact settlement for all of them, and
    near-total loss only where the Sharadar close implies it. It is not bent
    to pass.

**Metrics.**
- Per entry date and arm: R = sum(P&L incl. collateral interest) /
  sum(collateral), which is equal collateral weight per contract.
- Benchmark: SPY total return from close[t] to close[settlement day]. This is
  SPY price return (`scripts/td_data_local/SPY.csv`, price-only) plus a fixed
  2.0%/yr dividend yield, prorated by calendar days.
- Bias statement: the collateral earns T-bills and SPY gets its dividend, so
  both carries are included. The fixed 2.0% is an approximation (SPY's
  trailing yield was 1.3 to 2.9% over 2008-2026). The error is a few tenths
  of a %/yr, not directional toward puts.
- Excess per cycle = R - SPY_tr. Annualized = mean per-cycle excess x (365.25
  / mean holding calendar days).
- **Halves = odd years vs even years.** These are the split-half OOS folds,
  and the project's gate-2 convention. Chronological halves (split at the
  median entry date) are reported as descriptive only.
- **LOYO:** 2008 stays in the sample and is dropped in turn like every other
  year. LOYO min = min over years y of the annualized excess with y removed.
  It is not excluded.
- Null for the filter: 20 draws. Each draw permutes the icw8 score within
  each entry date across arm (a)'s tradable pool for the bucket, and takes
  the top quintile (a random 20% of the same pool), seeds 0..19.
  p80 = 80th percentile of the draws' annualized net excess.

### Amendment 1 (2026-09-29, Phase 1, before any Phase 2 number): F2 and the named pool

This was found by the Phase 1 plumbing run on noise labels. It surfaced as a
**presence** failure of the named check. No outcome was looked at.

- **F2 is scoped.** AV leaves `bid_size`/`ask_size` unpopulated (stored as 0)
  for whole chains in 2008-2009. Among puts with bid > 0, 51% have size 0 on
  2008-08-20, and on 2008-01-16 968 of 2,224 names are all-zero. By
  2010-08-18 it is 0.3%.
  - Every LEH put on 2008-08-20 has size 0, despite volume of 21,157 at the
    10 strike. As written, F2 removed LEH from the pool, which is the exact
    survivorship flattering the named check exists to catch.
  - Sizes are missing at random within a chain (for all names on 2008-08-20,
    each listed expiry has 56-61% of bid>0 contracts with a size). So a zero
    before ~2010 means "unknown", not "no bid". LEH has sizes on 2% of its
    contracts.
  - An "any contract has a size" scope was tried first on the same noise
    run. LEH still failed, so it was rejected.
  - **F2 now applies only when at least 90% of the name's bid>0 contracts
    (calls and puts, all expiries) carry a nonzero size on t.** Then a zero
    is meaningful. Elsewhere F1 and F3-F6 still apply.
- **Named pool vs the cap2000 price floor.** v2 `eligible_cap2000` is
  marketcap >= $2B **and** closeunadj > $10 on t
  (`reset2026/downcap_universe.py`).
  - WAMUQ (mcap $7.0B, $4.10) is therefore NOT in the cap2000 pool on
    2008-08-20.
  - Neither WAMUQ ($2.01) nor WB1 ($9.12) is in it on 2008-09-17. The Windows
    pull was cap2000-only from 2008-09-17, so no chain exists for them.
  - LEHMQ ($13.73) and WB1 ($14.90) are in the pool on 2008-08-20.
  - The rule is point in time (no look-ahead), so it is a legitimate
    tradable universe. But it keeps a short-put book out of sub-$10
    distressed names by construction.
  - The named check now fails loudly only when a name is cap2000-eligible
    with a verified chain and still missing from arm (a). LEH on 2008-08-20
    is required. WM is reported as "not in pool: price floor".
  - **Open for COO:** whether WO-O1 should also run a no-price-floor cap2000
    variant (mcap >= $2B only) as a descriptive stress. That needs the
    Windows pull to cover sub-$10 $2B+ names, which it did not do after
    2008-09-17. This is not added as a trial here.

### 4.1 Blend arm: BLOCKED

The live blend's historical q75 leg is the sweep cache
`out/sweep/scores/price_fund_h40_q75_trd_xgb_d3e01r100_expanding_cap500k_pit_s40.parquet`.

- The file is dated 2026-09-10.
- The purged-training code in `sweep/scorecache.py` (training rows <= date
  index tp-40, so labels end by tp) was first committed on 2026-09-18
  (e94cfe0).
- So it can't be shown that the cache was built with purged training (WO-23's
  flag). The live model `out/models/xgb_pit_augmented_model.json` is a single
  fit and leaks into every historical date.
- The cache also has scores only every ~60 calendar days (124 timepoints), so
  monthly entries would use scores up to 2 cycles stale.

**Unblock path:**
1. Re-run the cell with the current committed code (single-threaded,
   deterministic per Gate A3), and byte-compare the scores against the cache.
2. If they match, the purge is proven.
3. For monthly freshness, score at each entry's t-1 with the expanding model
   whose training cutoff is <= t-1-40 trading days.

Spec when unblocked: identical to (b-icw8), with score = mean(rank_z(icw
composite), rank_z(q75)) on t-1. Its 3 cells count in the tally (section 5)
whether or not they run.

## 5. Decision rules, tally and hold-out logging

**Primary cell (multiplicity).**
- Six score-arm cells (2 arms x 3 buckets) judged against a p80 null would
  give about a 74% chance that at least one passes by luck.
- So **the primary cell is (b-icw8, delta 0.30).** The verdict is taken on
  that cell alone.
- The 0.20 and 0.45 buckets (and blend, if ever unblocked) are reported with
  the same metrics. They are counted in the tally but cannot create a PASS.

**Success (all must hold, primary cell, full run 2008-01..2026-08):**
1. Net-of-spread excess > 0 vs SPY in both halves (odd years and even years),
   for the filter arm.
2. LOYO min > 0 (2008 included, see section 4).
3. The filter arm beats arm (a) by more than the shuffle null does. That is:
   filter > null p80, equivalently (filter - a) > (null p80 - a).

**Kill (either one):**
- arm (a) and arm (b-icw8) both have net excess <= 0 at the primary bucket;
- or the filter's net excess <= null p80.

Otherwise the verdict is MIDDLE (COO decides).

**Iteration cap: 3.**
- Any change to this spec after a Phase 2 number exists is an iteration.
- It must be written into this doc and committed before it runs.
- Each iteration past the first is logged as an extra look in the tally.

**Trial tally.**
- Options dead-end count before WO-25: **7**.
- Exp B adds **k = 5**.
- WO-O1 adds **2 score arms x 3 delta buckets = 6**:
  - Each delta bucket counts as a separate trial; buckets are not pooled into
    one trial, even though only the 0.30 bucket can pass.
  - The 3 blend cells count now, although the arm is BLOCKED, so unblocking
    later doesn't add trials silently.
  - Arm (a) is the baseline of the comparison and is not counted separately.
- Running total after Phase 2: **7 + 5 + 6 = 18**.

**Hold-out reads (Gabe's standing OK: fixed-weight, unfitted reads of
2020-2026 are allowed and logged):**
- **#7 = Exp B confirm window 2019-01..2026-08.** Unfitted: the admitted
  factors and all 9 weights are frozen from the 2008-2018 nominate fit. The
  run is one shot, and `run_expB.py --stage confirm` refuses a second run.
  If nothing is admitted at the screen, the read does not happen, and #7 is
  recorded as not used.
- **#8 = WO-O1 entry dates >= 2020-01-01.** Unfitted: icw8 uses the frozen
  `PRODUCTION_WEIGHTS`. Arms, buckets, filter and costs are fixed by this
  doc, and nothing is fit on 2020+. WO-O1 results are also broken out
  2008-2019 vs 2020+.
- WO-24 used #6.

## 6. Phase 2 commands (one per experiment)

**Run from a checkout that has branch `wo25-options-readiness`**, not from the
main checkout (`/Users/ggraham/pipe_dream` is on `round18-app-two-models` and
has neither `final/src/options_wo25/` nor `final/out/seasonality/`). Use either:
- this worktree, `/Users/ggraham/pipe_dream/.claude/worktrees/agent-a8b6bd6512a6407cf`;
- or any integration checkout once the branch has landed.

The scripts read data from the main checkout by absolute path
(`/Users/ggraham/pipe_dream/final/data`, `.../final/out/reset2026`). They write
to `final/out/options_wo25/` of the checkout they run from. The chain and
feature parquets are gitignored. If the worktree is deleted, `gate_a.py`
rebuilds them (~5 minutes for 33 dates, proportionally longer for 225).

Guards (pre-stated here):
- Exp B screen needs at least 120 nominate dates complete. Confirm needs
  2019-02..2026-08 complete, and it refuses a second run.
- **WO-O1 `--phase2` needs every planned monthly date through 2026-08
  complete at cap2000, and the chain partitions must equal that list** (so
  `gate_a.py` has been re-run). It refuses to overwrite
  `wo_o1_results.json`, because a re-run is an iteration.

Use the `pipe_dream` conda env (base anaconda's pandas is broken on this
Mac). Commands, from the checkout root:

    cd /Users/ggraham/pipe_dream/.claude/worktrees/agent-a8b6bd6512a6407cf
    # 0. arrival integrity (must PASS)
    /opt/anaconda3/envs/pipe_dream/bin/python final/src/options_wo25/check_arrival.py
    # 1. Gate A on all dates (rebuilds chain + features under final/out/options_wo25/)
    /opt/anaconda3/envs/pipe_dream/bin/python final/src/options_wo25/gate_a.py
    # 2. Experiment B: screen + admission + companion (nominate era), then the one-shot confirm (hold-out read #7)
    /opt/anaconda3/envs/pipe_dream/bin/python final/src/options_wo25/run_expB.py --phase2 --stage screen
    /opt/anaconda3/envs/pipe_dream/bin/python final/src/options_wo25/run_expB.py --phase2 --stage confirm
    # 3. WO-O1 (hold-out read #8 for entries >= 2020)
    /opt/anaconda3/envs/pipe_dream/bin/python final/src/options_wo25/run_wo_o1.py --phase2

## 7. Files

- `final/src/options_wo25/check_arrival.py`: data-arrival integrity.
- `final/src/options_wo25/gate_a.py`: chain and features rebuild, plus Gate A.
- `final/src/options_wo25/run_expB.py`: Exp B screen, admission, companion
  and confirm.
- `final/src/options_wo25/run_wo_o1.py`: WO-O1 put-selling backtester.
- `final/out/options_wo25/`: outputs (parquets gitignored; small JSON
  committed).

## 8. Phase 1 results (2026-09-29; chain facts and null-label plumbing only)

### 8.1 Arrival check on the current Mac store

`check_arrival.py`: overall **PASS**.
- 33 monthly dates on disk (2008-01-02..2010-08-18), against a plan of 225.
- Nominate segment (2008-01..2019-01): 33 of 134 dates complete at cap2000.
- 2019-02 onward: 0 of 91 complete.
- 1 error row, on 2008-12-17.
- WARN: adjusted-deliverable key duplicates on 2008-07-16 (1 row),
  2010-02-17 (45) and 2010-04-21 (38).
- The Phase 2 guards correctly refuse (`--phase2 refused: fewer than 120
  nominate-era dates complete at cap2000`).

### 8.2 Gate A: 10/10 PASS (`final/out/options_wo25/gate_a_report.json`)

| id | result | numbers |
|---|---|---|
| A1 | PASS | AAPL present on 13/13 dates in 2008 |
| A2 | PASS | 2008-08-20: LEHMQ via AV LEH, WAMUQ via AV WM, WB1 via AV WB, all in the chain. 2008-09-17: WAMUQ ($2.01) and WB1 ($9.12) are not cap2000-eligible (price floor), so not attempted by the cap2000-only pull: N/A |
| A3 | PASS | parity spot / closeunadj: LEH 13.645/13.73 (0.6%), WM 4.06/4.10 (1.0%), WB 14.87/14.90 (0.2%); all `verified` |
| A4 | PASS | Sharadar WM (Waste Mgmt) maps to AV WMI on every date 2008-08..2009-01. AV WM maps only to WAMUQ. 0 (date, AV symbol) pairs claimed twice after `av_keep` |
| A5 | PASS | rr25 > 0 on 95.4% of 25,210 name-dates (2008 92.4%, 2009 99.0%, 2010 98.6%) |
| A6 | PASS | pc_vol_ratio median 0.395 (n = 35,779) |
| A7 | PASS | cw_spread median -0.0169 (2008: -0.0135). Slightly negative, and less so than the builder's -0.022 note |
| A8 | PASS | Share of eligible names with a chain, on tier-attempted dates only: cap2000 **0.957** (33 dates, min date 0.930); cap500-only 0.771; cap150-only 0.465 (first 9 dates) |
| A9 | PASS | median ATM relative spread: cap2000 0.084 < cap500-only 0.150 < cap150-only 0.224 |
| A10 | PASS | `forward_return_tradable_40` = close[t+40]/open[t+1]-1 on 400/400 sampled cap2000 rows (own trading days in SEP). The label basis is tradable |

### 8.3 Exp B runner on null labels (`expB_*_SHUFFLED_TEST_*.json`)

- Pool integrity: 100.00% of v2 cap2000-eligible name-dates are in panel v2.
  There are 26,549 optionable cap2000 name-dates over 33 dates.
- Shuffled labels:
  - 0/5 factors pass the Holm screen, and 0/5 beat the IC null p80.
  - The companion passes on 1/5 (opt_os_ratio). With a p80 null, about 20%
    are expected to pass under the null.
- Noise labels: 0/5 screen, 0/5 IC; the companion passes 1/5
  (opt_cw_spread).
- The 9-factor weights are normalized (candidate weights between -0.006 and
  -0.203, not t-units). The null refits the candidate weight on every draw
  (null weights vary by draw).
- Confirm stage: exercised on nominate dates with one factor forced through.
  It ran end to end, and hold-out read #7 is not used.

### 8.4 WO-O1 on noise labels (`wo_o1_results_SHUFFLED_TEST_labels-noise_seed{7,8}.json`)

- **Named survivorship check: PASS.**
  - LEHMQ, 2008-08-20 entry: strikes 10 / 13 / 14 for the 0.20 / 0.30 /
    0.45 buckets. Settled at Sharadar close 0.22 on 2008-09-19, status
    normal, r = 1. Net loss / max loss = 0.976 / 0.980 / 0.981. The payoff
    formula check is exact.
  - WB1, 2008-08-20: in the pool (0.20 bucket, K 12.5), settled at 18.75,
    and expired worthless. That is the real outcome, as section 4 predicted.
  - WAMUQ: not in the pool on either date (price floor), so it is reported
    rather than failed.
- These are the only real-price numbers in Phase 1. They cover 4 contracts
  and are never aggregated.
- **Quote filter:**
  - The nearest-delta contract fails on 1.5% of name-date-buckets, and 1.5%
    end up with no trade. Reasons: F6 691, F1 10, F5 6, F4 5, F2 2.
  - The no-trade share by ATM-IV quintile (low to high) is 1.5%, 1.1%,
    0.9%, 0.6%, 0.4%. Drops do NOT concentrate in high-IV names, so there is
    no survivorship-flattering sign.
- Positions (arm a / arm b-icw8), per delta bucket: 0.20: 18,342 / 3,640;
  0.30: 15,377 / 3,051; 0.45: 13,348 / 2,644.
- **Arithmetic unit test:**
  - Realized noise-label cycle excess minus the analytic expectation
    (forward BS value at the contract's IV at settle-T).
  - Seed 7 z: 0.20 -1.80, 0.30 +1.20, 0.45 -0.14. Seed 8 z: -0.04, +1.89,
    -0.77. This is consistent with pure sampling noise.
  - The rough "-half-spread/K" predictor was about 0.0015/cycle too
    pessimistic. That comes from the 1-day T gap (chain T runs to the
    Saturday listed expiry, settlement is Friday) and the American premium in
    the mid. Both are real and small, and both favour the seller.
- The icw8 score comes from t-1. Before 2020 it uses split-half weights by
  score-date year parity. For example, entry 2008-01-02 is scored on
  2007-12-31 with the even-year fit.

### 8.5 Blocks and open items for Phase 2

1. **Data:** the Windows copy per section 1. Exp B needs at least 120 of 134
   nominate dates complete at cap2000, and the confirm stage needs all of
   2019-02..2026-08.
2. **Blend arm BLOCKED** (section 4.1). The unblock is a deterministic re-run
   of the q75 cell with a byte comparison.
3. **COO decision:** whether the cap2000 $10 price floor is the right short-put
   universe (Amendment 1). WaMu is excluded by it. A floor-free variant
   needs sub-$10 $2B+ chains that the cap2000-only pull did not fetch after
   2008-09-17.
4. **COO flag:** NW lag 39 on monthly observations (section 3, item 5).
5. The unified-chain builder and feature builder on integration also see the
   F0 adjusted-deliverable duplicates (`pivot_table(aggfunc="first")`). This
   affects `opt_cw_spread` on a handful of names on 3 dates. It is not fixed
   here: those files are not WO-25's to edit.
