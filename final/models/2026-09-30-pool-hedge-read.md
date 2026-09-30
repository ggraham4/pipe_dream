# WO-31: descriptive pool and hedge read (2026-09-30)

COO work order WO-31, approved by Gabe 2026-09-30. **Descriptive only.** There is no trial, no gate, no success or kill rule, and no decision in this doc.

**Any pool or hedge choice made after this read is in-sample for 2020+ (09-27 rule); this read does not choose.**

Period B (2020-01-02 .. 2026-07-30) is **hold-out read #11**. It is an unfitted read under Gabe's standing 09-27 policy. The weights are the frozen live ones and nothing was fit or chosen on B. The 0.8x IWM ratio was set beforehand from the era-A pool beta in WO-21 (about 0.82); it was not fit on B.

## Why this read

WO-21 (era A after 2011-10) and WO-24 (period B) found that the live book's result against SPY is driven mostly by the **pool**. On cap150, the no-score book lagged SPY by −1.99%/yr after 2011 and by −4.85%/yr in 2020-26. Selection over the pool added +2.00 / +2.85 (icw8).

**Selection definition.** Throughout this doc, selection means book − pool (the no-score book), as in WO-24. The +2.78 quoted for post-2011 in the work order is WO-21's score − random-book figure (+0.01 − (−2.76)). Score − pool on the same window is +2.00 for icw8 (reconciled) and +2.50 for icw9_seas. Gabe keeps SPY as the headline benchmark and leaves the live universe unchanged. The live test of the hedge is the forward bet in WO-10 (IWM-hedged). This read only shows what the alternatives would have looked like.

## Setup

| item | value |
|---|---|
| grid | v2 grid, column c (`composite_panel_v2` `eligible_cap150/500/2000`) |
| pools | cap150: mcap ≥ $150M and 20d median $vol ≥ $0.25M · cap500: $500M and $0.5M · cap2000: $2B and price > $10 |
| model | **icw9_seas** at frozen live weights (`ICW.PRODUCTION_WEIGHTS_V9_SEAS`); icw8 is used for reconciling (full icw8 tables are in the JSON) |
| construction | decile_volq, net 15 bp, 40 offsets, h = 40, label close[t+40]/open[t+1] (outcome_cache_v2) |
| book | `V.Book.picks` on the score, loaded with `model_audit_wo23.load_theo(period, pool)`. Ranks are taken within the pool. |
| pool | the WO-7 no-score construction (`drag_decomp.noscore_picks`) |
| selection | book − pool, per offset |
| hedged book | WO-9 ITERATE #1 / WO-10 arithmetic on a total-return basis: book_net + book_div − k·(ETF_px40 + ETF_div40 + 10 bp). book_div comes from Sharadar SEP closeadj/close. ETF dividends are adj_close/close from a fresh yfinance pull (auto_adjust=False). The SPY price leg is the outcome_cache_v2 SPY series, the same one "book vs SPY" uses. |
| periods | A = 2007-2019, split into pre / post at 2011-10-01 using sub-calendars (as in WO-21). B = 2020-01-02 .. 2026-07-30. |
| units | %/yr = annualised mean over the 40 offsets (×252/40). (n) = offsets positive out of 40. LOYO = leave-one-year-out minimum. |

**How to read "SPY-hedged".** SPY-hedged equals book vs SPY plus (book div − SPY div − 10 bp), annualised. This is asserted per offset to 1e-12. The SPY-hedged column is therefore always about 0.7-1.0 pp below book vs SPY: the book yields less than SPY, and the short costs 10 bp per rebalance (about 0.63%/yr).

**How to read "0.8×IWM".** The 0.8x variant keeps 20% net long exposure to IWM. It is **not** a neutral excess. It sits roughly 0.2 × (IWM total return + 10 bp) above the 1x IWM column. When IWM rose, that residual long exposure is most of the gap.

## Reconcile (hard assert, done first; tolerance 0.01 pp)

Every check passed. Most match to about 1e-9 or better.

- WO-21, A cap150 icw8: full +2.85416 (target +0.0285416, diff 0), pre +7.75258, post +0.01218. Pool post −1.98815 and pool pre +2.73451 match exactly.
- WO-23, A cap150 icw9_seas: +3.48652, exact.
- WO-24, B cap150 icw8: book −1.99180, pool −4.84553, selection +2.85373. icw9_seas: book −2.01637, selection +2.82917. Every diff is below 1e-8.
- Extra checks, all exact: the readout col c icw8 and the WO-7 pool on cap500 and cap2000 (era A). WO-9 `primary_15bp` and WO-9 `tradable_15bp` (full and common) were reproduced on all three pools using the old IWM.csv and WO-9's end-of-era mask. This confirms the hedge arithmetic is the same as WO-9's.
- Book gross basis: SEP close[x]/open[e] matches the harness gross to below 5e-9 on every date. There is one exception. In B, the icw8 cap150 book holds DOMO on 15 dates in 2026-07, and DOMO's SEP series ends on 2026-08-31 while the outcome-cache label has later bars. This is at most 9e-5 on one date. DOMO pays no dividend, so its dividend leg is unaffected.

## Gate A (data sanity, `final/out/pool/gate_a.json`)

- **cap2000-only name.** On 2023-06-15, **CAVA** had mcap $4.88B and close $43.78. It was in cap2000 but not in cap150 or cap500. 2023-06-15 was its first price date: cap2000 has no dollar-volume floor, while cap150 and cap500 need a trailing 20d median $vol. CAVA entered cap150 on 2023-06-29. Between 1 and 6 names per sample date are like this, all new listings.
- **cap150-only name.** On 2023-06-15, **SCM** (Stellus Capital) had mcap $292M. It was in cap150 only.
- **Dead names.**
  - Period A: **SHPG** (Shire, delisted 2019-01-07) is in all three pools up to 2019-01-07.
  - Period B: **FYBR** (Frontier, delisted 2026-01-20) is in all three pools up to 2026-01-20.
  - A small dead name, **SPA** (Sparton, delisted 2019-03), is in cap150 only (1,359 days).
- **PIT.** Pool membership is point-in-time.
  - **AB** first enters cap2000 on 2013-01-07, the day its mcap crosses $2B ($1.96B → $2.02B). Its cap2000 flag flips 15 times between 2012-06 and 2015-06. It is never flagged while below $2B.
  - On 7 sample dates, no cap500 or cap2000 row sits below its floor.
  - Two cap150 rows on 2008-06-16 (ASTI and WINT) carry `market_cap` 0.0 in the panel. The flags come from Sharadar daily marketcap, so these are quirks in the panel's market_cap column, not PIT breaks.

## Results: icw9_seas (live Theoretical), %/yr

### Period A post-2011 (2011-10-01 .. 2019-12-31)

| pool | book vs SPY (n) | LOYO min | pool vs SPY (n) | selection (n) | SPY-hedged (n) | IWM-hedged (n) | 0.8×IWM-hedged (n) |
|---|---|---|---|---|---|---|---|
| cap150 | +0.51 (38) | −0.71 (2018) | −1.99 (0) | +2.50 (40) | −0.50 (1) | +1.42 (40) | +4.05 (40) |
| cap500 | +0.43 (36) | −0.74 (2018) | −1.89 (0) | +2.33 (40) | −0.65 (2) | +1.27 (40) | +3.90 (40) |
| cap2000 | +0.57 (37) | −0.21 (2018) | −1.95 (0) | +2.53 (40) | −0.41 (10) | +1.51 (40) | +4.14 (40) |

### Period A, full era and pre-2011 (context)

| pool | full: book / pool / sel / IWM-h / 0.8×IWM-h | pre-2011: book / pool / sel / IWM-h / 0.8×IWM-h |
|---|---|---|
| cap150 | +3.49 / −0.25 / +3.74 / +3.06 / +4.96 | +8.63 / +2.73 / +5.89 / +5.87 / +6.51 |
| cap500 | +3.23 / −0.17 / +3.39 / +2.75 / +4.66 | +8.05 / +2.79 / +5.26 / +5.30 / +5.94 |
| cap2000 | +2.86 / −0.41 / +3.27 / +2.50 / +4.41 | +6.80 / +2.22 / +4.58 / +4.21 / +4.85 |

In era A, all 40 offsets are positive for book, selection, IWM-hedged and 0.8×IWM-hedged on every pool, both full era and pre-2011.

### Period B (2020-01-02 .. 2026-07-30), hold-out read #11

| pool | book vs SPY (n) | LOYO min | book, 2020 dropped | pool vs SPY (n) | selection (n) | SPY-hedged (n) | IWM-hedged (n) | 0.8×IWM-hedged (n) |
|---|---|---|---|---|---|---|---|---|
| cap150 | −2.02 (0) | −8.39 (2020) | −8.39 | −4.85 (0) | +2.83 (40) | −2.77 (0) | +0.26 (24) | +2.94 (40) |
| cap500 | −1.10 (4) | −6.52 (2020) | −6.52 | −4.81 (0) | +3.71 (40) | −1.85 (2) | +1.18 (35) | +3.86 (40) |
| cap2000 | −1.92 (1) | −5.12 (2020) | −5.12 | −4.87 (0) | +2.94 (40) | −2.71 (0) | +0.32 (22) | +3.00 (40) |

Period B, with 2020 dropped (for every column below, 2020 is also the LOYO-minimum year, except IWM-hedged and 0.8×IWM-hedged on cap2000, whose minimum is at 2021: −2.38 and +0.91):

| pool | selection | IWM-hedged | 0.8×IWM-hedged | SPY-hedged |
|---|---|---|---|---|
| cap150 | −0.94 | −2.46 | −0.70 | −9.08 |
| cap500 | +0.35 | −0.60 | +1.16 | −7.21 |
| cap2000 | +1.16 | +0.77 | +2.53 | −5.84 |

### Annual dividend yields

| | book | SPY | IWM |
|---|---|---|---|
| A post-2011 | 1.56-1.65 | 2.01 | 1.46 |
| B | 1.24-1.28 | 1.40 | 1.21 |

## What the numbers show (descriptive)

1. **In B, the pool lags SPY by the same amount on all three pools:** −4.85 (cap150), −4.81 (cap500), −4.87 (cap2000). The same holds after 2011 in A: −1.99 / −1.89 / −1.95. The drag against SPY is not a small-cap effect that raising the cap floor removes. The $2B-and-up inverse-vol decile construction lags the cap-weighted SPY just as much. The likely cause is equal- or inverse-vol weighting against a mega-cap-weighted index, but this read does not test that.
2. **Selection over the pool is positive on all 40 offsets for every pool and period.** It is +2.3 to +2.5 after 2011 (A) and +2.8 to +3.7 in B. With 2020 dropped, B selection is −0.94 on cap150, +0.35 on cap500 and +1.16 on cap2000. 2020 is the LOYO-minimum year for selection on every pool.
3. **Hedging with IWM 1:1** turns B from about −2 to roughly 0 to +1: +0.26 (24/40) on cap150, +1.18 (35/40) on cap500, +0.32 (22/40) on cap2000. After 2011 in A it gives +1.3 to +1.5 with 40/40 offsets positive. **Hedging with SPY** is worse than the unhedged book vs SPY by about 0.7-1.0 pp on every row, because of the identity above.
4. **0.8×IWM** is the highest column everywhere, but only because it keeps 20% net long exposure while IWM rose. It measures that exposure plus selection, not a neutral excess.
5. **2020 matters a lot in B.** Without 2020, book vs SPY falls to −5 to −8. The IWM-hedged book goes negative on cap150 (−2.46) and cap500 (−0.60) and stays positive on cap2000 (+0.77). cap2000's IWM-hedged LOYO minimum is −2.38, with 2021 dropped.

## Data notes

- **SPY and IWM, 2006-01 .. 2026-09-30.** Pulled by yfinance into `final/out/pool/bench/*.parquet` (gitignored; sha256 in `pull_meta.json`). This did **not** touch `data/benchmarks/IWM_live.csv`, WO-10's blind forward file.
  - IWM matches WO-9's IWM.csv exactly on open and close; the 40d total-return diff is at most 2e-6.
  - SPY price ret40 matches outcome_cache_v2 to 1e-6 on every panel date before 2026-07, with three exceptions: 2026-07-27, 07-28 and 07-30 (up to 0.32 pp per 40 days). On those dates the cache was built from earlier SPY bars than today's SPY.csv. The harness SPY (the cache) is kept as the price leg, so the reconciles hold.
- **No betas are computed or reported for B.**

## Reproduction

```
python final/src/pool/pull_bench.py   # SPY/IWM pull + checks (network)
python final/src/pool/gate_a.py
zsh    final/src/pool/run_all.sh      # 6 jobs (one process each) + aggregate; ~6 min
```

Outputs:

- `final/out/pool/pool_hedge_read.json`: reconcile, tables for icw9_seas and icw8, and every part.
- `final/out/pool/parts/*.json`
- `final/out/pool/gate_a.json`
- `final/out/pool/logs/`

Harness modules are imported read-only: drag_decomp, model_audit_wo23, screen_insider_v2grid, hedged_composite, run_backtest. `seas_factor_ext.parquet` is read from the WO-24 worktree.
