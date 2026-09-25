# WO-10: forward record of the IWM-hedged icw8 composite, on the v2 panel (2026-09-25)

Work order WO-10 (inside WO-11), commissioned by the pipe_dream COO.
Gabe approved it on 2026-09-25. **Nothing is promoted by this document.**
Worker branch `worktree-agent-ab25d6868c8fadc1a` (based on integration e11d37e).
Code: `final/src/reset2026/forward_hedge.py` (`record_hedge()`, `score_hedge()`,
`selftest`, `status`). Ledger: `final/out/reset2026/prediction_ledger_hedge.csv`,
scores in `prediction_ledger_hedge_scores.csv`.

Sections: 1 pre-registration (committed before the first record), 2
clarifications fixed before the record, 3 checks, 4 the first record.

## 1. Pre-registration (verbatim from the work order, frozen before any record)

> 1. Bet: long the icw8 decile_volq book (build_books construction), cap150, v2 panel; short IWM at equal notional. Registered tier cap150 only. cap2000 may be recorded, labelled DESCRIPTIVE, no kill rule.
> 2. Return basis: hedged = [book price-only 40d + book dividends over the hold] − [IWM price-only 40d + IWM dividends over the hold] − costs; entry open[t+1], exit close[t+40]; as WO-9 ITERATE #1 (book dividends from SEP closeadj/close; IWM yfinance adj vs unadj). Delistings: the execution.py exit floor.
> 3. Costs: read backtest_vectors for the exact 15bp rule; a standalone forward record has no prior book, so charge full entry + exit on the long book under that rule, plus 10bp for the short. State both.
> 4. Non-overlapping subset rule (cadence pending with Gabe; don't invent one): counted dates are chosen greedily from 2026-09-08; each is the earliest recorded panel date ≥ 40 trading days after the previous counted one.
> 5. Kill: mean hedged return over counted dates ≤ 0 after ≥ 6 matured counted dates. Pass: > 0 after ≥ 6 → to Gabe as a PROMOTE-CANDIDATE question. First maturity ~2026-11-04; no verdict possible before ~mid-2027. Forward test, not an in-era trial (composite family ≥ 14 in-era trials so far).

## 2. Clarifications, fixed before the first record

**C1. The book.** icw8 = `ic_weighted_composite.compute_composite_ic_weighted`
with the frozen `PRODUCTION_WEIGHTS` (not re-derived on v2), then
`composite.pick_decile_volq` (top 10% by score within each of 5
`volatility_60` quintiles of the valid names, inverse-vol weighted). That is
`noscore_control_v2.build_books`' icw8 book. `forward_hedge.book_one_date`
wraps `pick_decile_volq` only to carry the vol bucket and score; it asserts
its tickers and weights equal `pick_decile_volq`'s.

**C2. The universe (v2 panel).** v2's `eligible_cap150` flag, with SPACs
excluded unless the ticker is in the old 4,011-ticker grid, applied BEFORE
scoring. This is exactly `downcap_v2_readout.load_column("c")`, the universe
WO-6, WO-7 and WO-9 measured. The rule lives in
`final/src/reset2026/working_panel.py`; the old-grid list is frozen in
`old_grid_tickers_4011.txt` (sha256 474f0c0b...). On 2026-09-08 the rule
removes 19 cap150-eligible SPAC rows.

**C3. Costs, both stated.**
- Long book: `run_backtest.turnover_net_return` with cost 15bp and
  f_new = 1: net = (1+g)(1 − 0.00075)/(1 + 0.00075) − 1, i.e. the full
  15bp round trip on every record. WO-9's backtest charged the same rule
  with each offset chain's own f_new (turnover against the previous book,
  well under 1), so **the forward number is costed more heavily than the
  WO-9 backtest** (at f_new = 1 the book pays ~15bp per record vs WO-9's
  chain-average f_new × 15bp).
- Short leg: 10bp per record (`SHORT_COST = 0.0010`), as WO-9. ETF borrow
  assumed ≈ 0.
- Book dividends are not costed (as WO-9 ITERATE #1).

**C4. Formula.** Per recorded panel date t, on each name's own bars,
e = t+1 (entry at the open), x = t+40 (exit at the close):
- g = Σ w_i · close_i[x]/open_i[e] − 1 (split-adjusted, price only, Sharadar SEP)
- book_div = Σ w_i · close_i[x]/open_i[e] · (f_i[x]/f_i[e] − 1), f = closeadj/close
- IWM: price = close[t+40]/open[t+1] − 1 (yfinance `auto_adjust=False`),
  div = total − price with f = Adj Close/Close (HC.ret40's two bases)
- hedged = net_book(g) + book_div − IWM price − IWM div − 0.0010

This is WO-9 ITERATE #1's per-date tradable value with f_new = 1:
`net − (IWM40 + 10bp − (book_div − iwm_div))`.

**C5. Delistings and names that never trade.** A name whose series ends
before x exits at its last close (execution.py's delisting exit floor), with
the dividends earned to then. A name with no bar after t was never opened;
its weight is renormalised over the rest (`noscore_control_v2.realise`'s
rule). Both counts are written to the scores CSV.

**C6. Maturity ("still blind").** `score_hedge()` refuses a date:
- before panel_date + 56 calendar days (40 NYSE days is at least that), with
  no file read at all;
- if `final/data/benchmarks/IWM_live.csv` (an IWM pull made after maturity;
  it does not exist today) lacks bar t+40;
- if the SEP stock panel does not reach IWM's exit date. Only once it does is
  a series that ends early treated as a delisting, not as data not yet
  pulled.

**C7. Counting trading days (rule 4).** "40 trading days" is counted on
IWM's daily bars (IWM trades every NYSE session). Only recorded panel dates
≥ 2026-09-08 are eligible, and the chain starts at 2026-09-08.

**C8. Tiers recorded.** cap150 (REGISTERED) and cap2000 (DESCRIPTIVE, no
kill, no pass). cap500 is not recorded.

**C9. Ledger schema.** One row per book constituent per (panel date, tier):
panel_date, recorded_at, hedge_version, panel_source (= composite_panel_v2),
tier, role, leg (long), ticker, icw8_score, vol_bucket, volatility_60,
market_cap, weight; plus one short-leg row (leg short, ticker IWM,
weight −1.0). The v3 and ext ledgers and their schemas are untouched.
`ledger_panel_manifest.json` records {ledger: {panel_date: panel file}}.

**C10. Record cadence.** Pending with Gabe; this work order does not
schedule one. Only 2026-09-08 is recorded now.

## 3. Checks

**Pre-registration commit: BLOCKED.** The integrator's commit + push of this
doc (with the code) was denied by the auto-mode permission classifier
("[Modify Shared Resources]") on 2026-09-25, and was not retried. As the work
order allows, the record went ahead with the pre-registration pinned by hash
instead. At 2026-09-25 14:55:23, before `record_hedge()` ran, sections 1-2
of this file (the whole file as it stood, mtime 14:41:39) had sha256
`29438c7acef02704fd4207a8e8b75c9286ede7156a35577e99df9bae450dc462`;
`forward_hedge.py` `084e741b4218598c4f8a334c304058af2cf6b9bda93bd7d621c99555dbc0ec57`;
`working_panel.py` `2cdd5a5ee6ad3345d6eb1149d9ee07b954f43dcd062aa2a04587e7cf32bc4ad0`.
Sections 1-2 have not been edited since; only sections 3-4 were filled in. The byte-exact
pre-image is saved as `final/models/2026-09-25-forward-hedged-icw8.PREREG-PREIMAGE.md`
(`shasum -a 256` on it gives 29438c7a...).

All passed. Logs: `final/out/reset2026/downcap_v2/forward_hedge_selftest_{2015-06-15,2009-03-16}.txt`,
`forward_hedge_record_2026-09-08.txt`.

| check | result |
|---|---|
| construction: `book_one_date` == `build_books` on `load_column("c")` cap150, 2015-06-15 | same 315 tickers, max \|Δw\| 3.5e-18 (0 dropped names that date) |
| same, 2009-03-16 | same 225 tickers, max \|Δw\| 5.2e-18 |
| `working_cross_section` (v2 + universe rule) == column c cross-section | 3,189 = 3,189 names (2015), 2,272 = 2,272 (2009); books identical |
| scoring: `hedged_return` vs WO-9 per-date tradable value at f_new = 1 (outcome_cache_v2 gross, `HC.ret40` IWM price/total, `hedged_tradable.load_panel` dividends, `RB.turnover_net_return`) | 2015-06-15: +0.02258545 vs +0.02258545; 2009-03-16: +0.02148353 vs +0.02148353 (both < 1e-6; book gross also equals the cache to 1e-6; 5 delisting-floor names on 2015-06-15 handled identically) |
| live scorer's v2 book (out/current_signal_composite.csv) == the hedge record's cap150 book | 305 = 305 names, weights equal to 1e-12 |
| blindness: record | every cap150/cap2000-eligible name on 2026-09-08 has NaN `forward_return_tradable_40`; no price file read; SEP panel ends 2026-09-08 |
| blindness: `score_hedge()` | "still blind (exit ~2026-11-03 not reached; nothing read)" for both tiers; no scores file written |
| duplicate-date guard | a second `record` refused; ledger sha256 unchanged |
| NaN-vol trap | no NaN/inf `volatility_60` or score in either book, all vol > 0, weights sum to 1 |
| book size | cap150: 305 of 3,033 valid (10.06%); 3,065 eligible; 61 per vol quintile. cap2000: 165 of 1,655 valid (9.97%); 1,665 eligible |
| SEP coverage of the recorded books on 2026-09-08 (so the record is scorable) | 305/305 cap150 and 165/165 cap2000 long names have a SEP bar with finite open/close/closeadj |
| existing ledgers | prediction_ledger{,_v2,_v3,_ext}.csv sha256 identical before and after |

## 4. The first record (2026-09-08)

`final/out/reset2026/prediction_ledger_hedge.csv`: 472 rows = cap150 305
long + 1 short (IWM, −1.0), cap2000 165 long + 1 short. Manifest entry
`prediction_ledger_hedge.csv: {2026-09-08: composite_panel_v2.parquet}`.
Universe: 3,901 v2 rows on the date; the rule removed 201 rows, 19 of them
cap150-eligible SPACs (0 at cap2000).

Name-check, top 5 cap150 weights (all Domestic Common Stock, all v2
cap150-eligible, none SIC "Blank Check"):

| ticker | company | weight | vol bucket | volatility_60 | market cap |
|---|---|---|---|---|---|
| SLAB | Silicon Laboratories | 3.14% | 0 | 0.0024 | $7.34B |
| RAMP | LiveRamp Holdings | 2.40% | 0 | 0.0032 | $2.29B |
| PEN | Penumbra | 1.86% | 0 | 0.0041 | $12.58B |
| NATH | Nathan's Famous | 1.01% | 0 | 0.0076 | $0.40B |
| WLKP | Westlake Chemical Partners | 0.97% | 0 | 0.0078 | $0.77B |

**Caveat for the COO (not a construction change; the construction is
registered).** SLAB, RAMP and PEN have daily vol of 0.24-0.41% and have
traded in a pinned range since June (SLAB $216.4-220.7, RAMP $37.4-38.0,
PEN $315-327), the profile of pending-acquisition targets. Inverse-vol
weighting gives the three 7.4% of the book. They were also the top 3 on
the v1 panel. Their 40-day return will be roughly a deal spread. This is a
known property of decile_volq, present in every backtest; it is recorded
here so a later reader does not mistake it for a data error.

First maturity: 2026-09-08 + 40 NYSE sessions (about 2026-11-03/04). To
score: pull IWM daily bars (yfinance, `auto_adjust=False`, with Adj Close)
into `final/data/benchmarks/IWM_live.csv`, refresh the SEP panel past the
exit date, then run `forward_hedge.py score` and `status`. Verdict needs ≥ 6
matured counted dates (about mid-2027 at the earliest), and the record
cadence is Gabe's call.
