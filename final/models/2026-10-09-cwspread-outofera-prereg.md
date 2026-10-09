# WO-55: opt_cw_spread avoid-screen, fixed-rule out-of-era read on OptionMetrics (pre-registration)

Date: 2026-10-09. Commissioned by COO (WO-55; Gabe: "lets continue with WRDS work orders").
Branch `wo55-cwspread-outofera`, based on origin/integration d09101b.
Status: **pre-registration, written before any 2019+ outcome is computed.** When this file was
written, the 2019-2025 OptionMetrics quotes were being pulled. No 2019+ label, return, IC or
gate figure had been computed.

## 0. Hold-out read log (written before the run)

> **Hold-out read #22.** Date 2026-10-09. What it reads: `outcome_cache_v2.gross_return_40` for
> thin-slice and cap2000 names on the 80 WO-37 grid dates from 2019-01-16 to 2025-08-20
> (OptionMetrics ends 2025-08-29). The read is **unfitted**: a fixed rule, every constant copied
> from the frozen WO-37 pre-reg and WO-52 amendment, and one run.

Allowed under Gabe's 2026-09-27 rule: unfitted, fixed-weight hold-out reads are OK without
asking, but each one is logged. Fitting on 2020+ still needs Gabe. The same line is logged in
COO.md under the WO-55 entry.

- **Nothing is fitted or chosen on 2019+ data.** That rules out thresholds, deciles, windows,
  filters, slices, link rules and any code change made after seeing a 2019+ outcome.
- **One run.** A crash may be fixed: the crash only, logged in the results doc, no rule change.
  The iteration cap is 3 such fixes. After that the order reports "no result within budget".
- Nothing before 2019 is read. The in-era 2008-2018 result is WO-52's and is not recomputed.
  Nothing before 2007, ever.

## 1. Hypothesis

WO-52 Arm 1 passed in-era (2008-2018, 133 dates): avoiding the bottom decile of `opt_cw_spread`
in the thin slice gave M = +2.739% per 40 days with NW lag-39 t 12.17. The question here: does
the same fixed screen keep a positive, material edge out of era, on 2019-01 to 2025-08? It is
the same code on new dates.

## 2. Frozen constants (copied, not re-derived)

Sources:
- **WO-37 pre-reg:** `final/models/2026-10-01-thin-liquidity-prereg.md`, sha256
  ce6caf89e95e770d8a803d09400e234ba2c6d991222e3eb15338aed13e2eacd7 (on origin/integration).
- **WO-52 amendment:** `final/models/2026-10-08-thinliq-optionmetrics-amendment.md`, sha256
  a9a1c8c1083ebc69fb91b59da61b2c2a80bf1b4af88aabc8d0c5a15a78de98cf (frozen 2026-10-08T20:51:42Z,
  on origin/integration).
- Code: `final/src/thinliq/run_arm1.py` and `tl_common.py` on d09101b, imported and called
  unchanged.

| Constant | Value | Source |
|---|---|---|
| Thin slice | `eligible_cap150 AND NOT eligible_cap2000` in `downcap_universe_v2` on d | WO-37 l.65; `tl_common.universe_on` |
| cap2000 (descriptive comparison) | `eligible_cap2000` on d | WO-37 §3 last line; `run_arm1.load_frame` |
| Signal | `opt_cw_spread`, sign +1. All expiries, matched strikes, call IV minus put IV (Black-Scholes on mids, Sharadar spot, 3-month bill), OI-weighted | WO-37 l.115; amendment l.68 (`convert_av` recomputes IV/delta); `run_arm1.SIGNAL` l.31 |
| DTE / delta band for the signal | **none**: all expiries, all matched strikes. The 0.3-0.7 delta band appears only inside the descriptive `opt_spread_atm` | amendment l.33 ("no DTE or delta band") |
| Server-side filter | `ss_flag='0'`, `contract_size=100`, `exdate > date`, not index ('A') or ETF ('%') | amendment l.27-31; `wrds_optionm/pull_opprcd.py` |
| Identity filter | `av_keep`: kept only if \|secprd close / Sharadar closeunadj - 1\| < 5%; closer claim wins a shared secid | amendment l.93 |
| Bottom decile | lowest `round(0.10 x n)` by signal; ties by ticker order | WO-37 l.123; `run_arm1.DECILE` l.32 |
| Minimum pool | 100 names with signal and label per date | WO-37 §3; `run_arm1.MIN_NAMES` l.33 |
| Metric | M_d = mean label of the rest minus mean label of the bottom decile, equal-weighted; M = mean of M_d, % per 40 days | WO-37 l.125 |
| t | Newey-West, lag 39, on M_d | WO-37 l.128; `run_arm1.NW_LAG` l.34 |
| Shuffle null | 100 within-date signal shuffles, p80; seed 20261001 (WO-52's) | WO-37 l.134; `run_arm1.NULL_DRAWS` l.35 |
| Offsets | even-indexed and odd-indexed dates in time order | WO-37 l.143 |
| Horizon / label | h = 40: `outcome_cache_v2.gross_return_40`. Entry open[d+1], exit close[d+40], delisting floor (exit at last close) | WO-37 l.77 |
| Cost basis | gross stock return, no cost. Arm 1 is an avoid screen on the stock leg, so no option is traded | WO-37 §3 |
| Entry dates rule | the WO-37 grid: the `date=*.parquet` names in `alphavantage_full/options/monthly/`, reused as listed, not rebuilt. Here the 80 names in [2019-01-01, 2025-08-29] (2019-01-16 to 2025-08-20) | amendment §1 "Entry dates" |
| Holiday-expiry rule | `run_wo_o1.accepted_expiries`: Arm 2 only. Arm 1's signal uses all expiries, so it does not enter. Arm 2 (cash-secured puts) is a dead end and is **not** run | amendment §5 |
| Coverage gate per date | thin slice ≥ 99% terminal (`ok` or `no_data`; `unlinked` is not terminal) | WO-37 l.254; amendment §3; `tl_common.GATE_SHARE` |

**Labels complete.** An entry date is used only if close[d+40] exists on the Sharadar
calendar (`downcap_universe_v2` dates, which run to 2026-09-08). This is a presence check
(`run_oos.labels_complete`), and it keeps all 80 dates. CRSP is not used for labels. The label
source is WO-52's.

## 3. Data (Phase 1) and the link repair (fixed here, before the gate is computed)

**Pull.** `final/src/cwspread_oos/pull_oos.py` pulls `optionm.opprcd{YYYY}` for the 80 dates,
one query per entry date with chunked reads. It uses WO-52's filter and columns, imported from
`pull_opprcd.py`. It also pulls `secprd{YYYY}` closes on those dates and `optionm.secnmd` (the
CUSIP history).
- **Storage:** `final/data/wrds/optionm/oos2019/`, parquet only.
- WO-52's 2008-2018 store, `secprd.parquet` and `calls.parquet` are **not** written.
- Outputs go to `final/out/cwspread_oos/`, not `thinliq_om/`.

**Why a link repair is needed.** This was measured on presence only, from the universe and the
crosswalk, before any OptionMetrics gate figure:
- The WO-51 crosswalk (`permno_sharadar.parquet`) is built from legacy `crsp.stocknames`, whose
  `nameenddt` stops at **2024-12-31**. Under the frozen WO-52 chain every 2025 thin name is
  therefore `unlinked`: 0% linked on all 8 dates in 2025.
- 11 dates in 2020-08 to 2021-12 are also below 99% linked, at 94.1% to 98.9%. The unlinked
  names there are SPACs. Sharadar prices them from the unit split, but the CRSP permno starts
  later. OTC names fall in the same gap (FNMA, FMCC).
- So the frozen chain caps the gate at about 61 of 80 dates. That is below 72 for linking
  reasons alone, before any quote is read.

**Repair (mechanical, written before the repaired gate is computed).** It is applied in
`build_store_oos.py` and touches only name-dates the WO-52 chain leaves `unlinked`:
- **L1 (right-censoring).** A crosswalk row whose `valid_to` is exactly 2024-12-31 gets
  `valid_to` = Sharadar `lastpricedate` when that is later. This is WO-51's own rule,
  valid_to = min(nameenddt, lastpricedate), with the vintage-censored `nameenddt` dropped. The
  permno -> secid step is unchanged (`opcrsphist`, which runs to 2025-12-31).
- **L2 (independent path, fallback only).** A name-date still unlinked after L1 is linked from
  the Sharadar ticker's CUSIPs (`TICKERS.cusips`, first 8 characters) to OptionMetrics
  `secnmd.cusip`, then to secid (non-index, non-ETF).
  - If several secids match, take the one with the most rows on d, then the lowest secid.
  - Rows on d give `ok`. A secid with no rows on d gives `no_data`.
  - **No secid gives `unlinked`, which stays non-terminal.** Absence from OptionMetrics is
    never counted as `no_data`.
- **Identity check.** Every `ok` chain, whichever path linked it, must still pass `av_keep`'s 5%
  close check.
- **Both gates reported.** The log keeps `status_frozen`, the WO-52 chain unmodified, and the
  gate is reported under both the frozen and the repaired chains. The **repaired gate binds.**
  If it fails, the order reports BLOCKED with both numbers and stops. Link variants are not
  iterated against the gate count.

**Gate (WO-55 wording).** A date "passes" when the thin slice is ≥ 99% terminal on it. If fewer
than 90% of the 80 dates pass (fewer than 72), the order reports **BLOCKED** and the gate is not
relaxed. The read uses only the passing dates, as in WO-37 §2.

**Presence checks (WO-37 §5 rules, repointed to this window).** All of these block, as in the
WO-37 code:
- **Named dead names in window, chosen on presence only.** ATPAQ and SIGM have no thin date in
  2019-2025.
  - **BBBYQ** (Bed Bath & Beyond, bankrupt 2023): thin on 32 dates; must-date **2022-08-17**.
  - **RADCQ** (Rite Aid, bankrupt 2023): thin on 50 dates; must-date **2022-06-15**.
  - Each needs a kept chain on its must-date and on ≥ 90% of its gate-passing thin dates.
- **TXG** is now in-window. It needs a chain on every cap2000 date from 2019-12-18 and on every
  thin date from 2024-10-16 to 2025-08-20.
- **Pool integrity:** ≥ 99% of thin name-dates with a kept chain are in the panel and in the
  outcome cache.
- **Dead vs listed chain share:** later-delisted names trail still-listed ones by at most 5
  points.
- **Guard.** The `read` command refuses unless this doc's sha256 equals the frozen value in
  `run_oos.PREREG_SHA256`. The WO-37 guard (`tl_common.phase2_guard`, unchanged) then recomputes
  the gate and presence checks, requires fresh chains, and requires that no result file exists.

## 4. The read (Phase 2, one run)

`run_oos.py read` calls `run_arm1.load_frame`, `attach_labels`, `prep` and `evaluate`
unchanged:
- on the thin slice (binding);
- on cap2000 on the same dates (descriptive, scored against the same bars).

**Bars (WO-55; they bind on the thin slice):**

| Verdict | Rule |
|---|---|
| **PASS** | M ≥ +0.5% per 40 days AND NW lag-39 t ≥ 3.0 AND both offsets > 0 |
| **KILL** | M ≤ 0 OR the two offsets have opposite signs |
| **MIDDLE** | anything else |

The t bar of 3.0 is the nominal 2.0 times WO-37's null-sd scaling of 1.5.

**Also reported (descriptive, none can change the verdict):**
- **Null-seed sd:** 100 seeds of labels permuted within date (seeds 1000-1099, the `run_arm1
  --labels shuffled` convention), the sd of M and of the t, and the WO-55 verdict rates under
  the null.
- **LOYO:** M with each year left out, including M with 2020 left out.
- **Median spread:** median `opt_spread_atm` (% of mid) over the pool and over the bottom
  decile.
- WO-37's own S1-S8 and K1-K6, sector-neutral, size/vol residual, halves, year shares and OI
  terciles, all as `evaluate` returns them.

## 5. Trial tally and what happens next

- Options family: +1. **23 (29 including WO-36).** The null seeds, cap2000, LOYO and spreads
  are descriptive and add no trial.
- Phase 3 (down-cap long-book test) runs only if this read is a PASS. In that case only a
  DRAFT pre-reg is written (`final/models/2026-10-09-cwspread-downcap-book-prereg-DRAFT.md`) and
  nothing is computed for it. The COO and Gabe decide.
- These stay dead ends and are not touched: `opt_cw_spread` in the cap150 long book (WO-36),
  cash-secured puts, long calls, LEAPS, and any new option factor.

## 6. Commands

    PY=/opt/anaconda3/envs/pipe_dream/bin/python
    caffeinate -i $PY final/src/cwspread_oos/pull_oos.py         # quotes, secprd, secnmd
    caffeinate -i $PY final/src/cwspread_oos/build_store_oos.py  # links (frozen + L1/L2), AV-shaped store, log
    $PY final/src/cwspread_oos/run_oos.py gate                   # coverage gate + presence (no outcome)
    caffeinate -i $PY final/src/cwspread_oos/run_oos.py chain    # chain + features (thinliq/build_chain.py)
    caffeinate -i $PY final/src/cwspread_oos/run_oos.py read     # the one guarded run

Results go in `final/models/2026-10-09-cwspread-outofera-results.md` and
`final/out/cwspread_oos/wo55_read_results.json`, not here.
