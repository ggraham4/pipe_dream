# Alpha Vantage premium key — first spin (2026-09-22)

Gabe bought the $49.99/mo plan (75 req/min) to unblock the options
volume/open-interest gap (`project-thin-liquidity-options-edge-idea`), and asked
where AV can also fill gaps in Sharadar. Everything below was measured live
against the purchased key. Probe script: `final/models/av_probe/av_coverage_probe.py`
(reads `ALPHAVANTAGE_API_KEY` from the environment — **keep the key out of the
repo**, same rule as `SHARADAR_API_KEY`). Raw sample: `av_probe/coverage_sample.csv`.

## Headline

**`HISTORICAL_OPTIONS` is the only AV endpoint that is survivorship-safe, and it
is very good** — provided each name is queried under the symbol it traded
as on the date (with that mapping, dead-name coverage matches live-name
coverage within sampling noise). Every fundamentals-style endpoint (EARNINGS, EARNINGS_ESTIMATES,
SHARES_OUTSTANDING, INSIDER_TRANSACTIONS, NEWS_SENTIMENT) maps to *today's*
issuer and returns nothing for dead companies — usable live, never as a
backtest feature.

## 1. HISTORICAL_OPTIONS — what we now have

- **Raw per-contract `volume` and `open_interest`**, plus bid/ask, bid/ask
  *size*, last, mark, IV, greeks. Closes handoff open item #6 (the earlier
  check only saw the *ratio* endpoint).
- **History from 2008-01-02** (AAPL 2008-01-02: 396 contracts, 278k volume).
  The DoltHub chain on disk starts 2019-02-09.
- **Symbol-as-of-date, so dead issuers are present**: LEH and WB=Wachovia (2008),
  DELL (2012), YHOO (2015), MON (2016), CELG (2018), TWTR/BBBY (2021), SIVB/FRC
  (2022–23). None of these are in the DoltHub chain. **This closes the AGENTS.md
  known gap "options universe built from today's roster" for 2008-onward.**
- **Unadjusted strikes** (AAPL 2008 ATM ≈ $200) — same convention as DoltHub, so
  the existing `build02c_v3_properrescale.py` split-rescale logic applies.
- **Same feed as DoltHub**: on 4 ticker-days both hold (MSFT 2023-03-08, AAPL
  2022-06-10, AMD 2022-06-10, ETSY 2022-08-08), 98–100% of overlapping
  contracts have identical bid *and* ask (538 contracts). DoltHub just stores
  ~7% of the strikes (e.g. 162 vs 2,188) and no volume/OI. Note this shows a
  shared source, not correct quotes — the stale-quote problem found in the
  puts diagnosis carries over (see cleaning caveat below).
- **Open interest is point-in-time safe (tested, not assumed).** OI changes
  only through trades (plus exercise — the 2021-06-18 expiry was dropped), so
  |OI(d+1) − OI(d)| must be ≤ the volume of whichever day lies between the two
  snapshots. Against volume on **d**: 0.6–1.4% violations (AAPL, ~900
  changed contracts per pair), 0% (TXG). Against volume on d+1: 27–71%
  violations. So the row dated d carries the **prior-close** OI, knowable at
  d's open; `volume` on row d is day d's own volume (EOD).
  Script: `av_probe/av_oi_timing_and_overlap.py`.

### Coverage over the down-cap universe (300 random name-dates, ≥2008)

Stratified 50 per (tier × Sharadar `isdelisted`), random eligible date per name.

| tier | alive, Sharadar ticker | alive, as-traded symbol | dead, Sharadar ticker | dead, as-traded symbol |
|---|---|---|---|---|
| cap2000 | 88% | **96%** | 64% | **94%** |
| cap500  | 74% | **82%** | 56% | **74%** |
| cap150  | 54% | **56%** | 34% | **48%** |

- **The raw dead-vs-alive gap (~20 pts in every tier) was a symbol-mapping
  artifact, not AV coverage.** Sharadar stores a company under its *final*
  ticker (`NVTAQ`, `WFTIQ`, `APC1`, `CZR2`, `TGNA` for Gannett-as-GCI…); AV
  indexes by the symbol it traded as on that date. Re-querying every miss under
  its `tickers_master.relatedtickers` / `actions.csv` ticker-change symbols
  recovered **40 name-dates, all identity-checked** (parity spot within 10% of
  Sharadar `closeunadj`). Remaining dead/alive differences (2, 8, 8 pts) are
  inside the ~7-pt sampling noise at n=50 per cell. Many remaining cap150
  misses are SPACs (price ≈ $10, typically no listed options).
  Script: `av_probe/av_symbol_remap.py`, results `av_probe/remap_sample.csv`.
- **A real pull must query the as-traded symbol**, resolved from
  `relatedtickers` + `actions.csv` and verified per name with the parity-spot
  check. The check matters: first-candidate mapping picked the wrong issuer 3
  times in 43 hits (VIA2→VIA, OCSL→FSC, HK1→HK on an old date).
- **Issuer identity on raw hits**: 181/185 parity-spot matches. Misses: GOLD
  2021 (Sharadar/AV disagree on which issuer), NNDM, PRLD, GFIG.
- cap150 coverage by era (as-traded): 69% / 50% / 20% / 50% for
  2008–12 / 13–16 / 17–20 / 21–26 — the 2017–20 cell is n=10, not a finding
  yet.
- **Liquidity, among covered name-dates (median)**:

  | tier | contracts | day volume | total OI | quoted spread (of mid) | zero-bid share |
  |---|---|---|---|---|---|
  | cap2000 | 145 | 136 | 7,306 | 17.8% | 23% |
  | cap500  | 82  | 45  | 2,892 | 19.6% | 27% |
  | cap150  | 54  | 22  | 4,347 | 26.4% | 32% |

  The thin-liquidity hypothesis is now **testable** — and the spreads say
  execution cost is the first-order problem, exactly as the memory warned.

### Data-quality caveats for the pipeline

- **Do not trust AV's IV/greeks.** DELL 2012-06-15: every call delta = 1.000,
  IV = 0.015 while bid/ask are clearly correct. BBBY/FRC/LEH dates return `"-"`
  for all greeks. Recompute IV/greeks from mids + our own spot/rates.
- Zero bids are common (23–32%). Apply the existing richness-ratio /
  stale-quote cleaning (`build_pit_puts_cleaned.py`) before any backtest.
- Burst limit: ~5 req/s trips an `Information: Burst pattern detected` reply
  (HTTP 200 with no data — must be detected and retried, not treated as "no
  chain"). ~1 req/s sustained is clean.

### What one month of the plan can pull (Gabe's call)

75 req/min ≈ 108k/day ≈ 3.2M/month theoretical; ~60/min observed with safe
pacing. cap150 is ~3,000 names at any date; 2008-01 → 2026-08.

| option | calls | wall clock @60/min |
|---|---|---|
| A. 40-day rebalance grid, cap150 (~117 dates) | ~350k | ~4 days |
| B. Monthly snapshots, cap150 (~224 months) | ~670k | ~8 days |
| C. Weekly, cap500-and-below only (~1,500 names) | ~1.5M | ~17 days |
| Full daily chains, whole universe | ~15–20M | impossible on this plan |

**Grid-offset constraint (AGENTS.md):** any feature must pass
`check_grid_offset.py` before promotion, and a single snapshot grid (A, or B's
one date per month) cannot. Weekly sampling gives several offsets. A hybrid —
**weekly for cap500-and-below, monthly for cap2000** (~1.2M calls, ~14 days) —
buys offsets where the thin-liquidity hypothesis lives. B (~8 days) is the
cheaper choice if a single grid is acceptable for a first read.
It is a multi-day spend of the subscription window, so nothing is started —
Gabe's call.
Data size: ~100–1,000 contracts × ~670k snapshots → store as partitioned
parquet, not CSV.

## 2. Where AV can (and can't) fill Sharadar gaps

The deciding question for every endpoint: **does it resolve a symbol as of the
date, or to today's company?**

| Sharadar gap | AV endpoint | verdict |
|---|---|---|
| No options at all | HISTORICAL_OPTIONS | **Fills it.** As-of-date, dead names, 2008+. |
| No analyst estimates / EPS surprise | EARNINGS (reportedDate, reportTime pre/post, estimatedEPS, surprise; AAPL back to 1996) | **Live-only.** SIVB, CELG, BBBY → empty; WB → Weibo, not Wachovia. 1 of 150 sampled dead names has any history. Backtest use reintroduces survivorship bias. |
| Estimate revisions | EARNINGS_ESTIMATES | Live-only, and history starts ~2017 anyway. |
| Earnings *announcement* dates (Round 16 used filing dates) | EARNINGS.reportedDate | Live-only. **Better backtest source: EDGAR 8-K Item 2.02.** `data/edgar/8k_events_raw.csv` only kept flagged filings (5.02/4.02/going-concern), so 2.02 appears incidentally (~15k rows); extending `edgar_8k_events_pull.py` to keep Item 2.02 gives survivorship-safe announcement dates. |
| Market-cap quarantine (354 tickers) | SHARES_OUTSTANDING | **Doesn't help.** Today's-issuer-only (SIVB empty) and the worst offenders are ADRs. |
| 52 ambiguous / reused symbols in identity map | LISTING_STATUS (`state=delisted`, optional `date`): 9,511 delisted with ipoDate/delistingDate | **Useful cross-check**, cheap (1 call). |
| 0.81% of rows with no price bar | TIME_SERIES_DAILY_ADJUSTED | Partial: CELG, SIVB present; LEH absent. **SIVB's series runs to 2026-09-21** — the OTC continuation under the old symbol — so any fill must be cut at Sharadar's delisting date. |
| Insiders | INSIDER_TRANSACTIONS | No (already decided — use EDGAR Form 4). |
| News / events (meta-model tier 3) | NEWS_SENTIMENT | **0 articles for SIVB in 2023-03-01..15** — the SVB collapse. Today's-issuer-only; AAPL 2010 has only 18 items/month. Not a backtest source; revisit the tier-3 plan's data assumption. |
| Earnings-call text | EARNINGS_CALL_TRANSCRIPT | AAPL 2010Q1 present; not tested on a dead name — assume live-only until shown otherwise. |

**Legitimate uses of the live-only endpoints**: (1) features in the *live*
signal only if the backtest has a survivorship-safe equivalent; (2) validating
a causal estimator on surviving names — e.g. how well the Round 16
`_seasonal` next-earnings estimator predicts AV's `reportedDate`, and what AV's
`reportTime` adds.

## Next steps (in order)

1. Gabe: pick a pull (B, or the weekly-down-cap/monthly-large-cap hybrid).
   Pull script = the probe's `chain()` + as-traded symbol resolution
   (`av_symbol_remap.py`'s `relatedtickers`/`actions.csv` logic) + per-name
   parity-spot identity check + burst-reply detection + partitioned parquet,
   run on Gabe's machine with `ALPHAVANTAGE_API_KEY` set.
2. Recompute IV/greeks from mids; apply stale-quote cleaning before any
   backtest.
3. Extend `edgar_8k_events_pull.py` to keep Item 2.02 (free, not AV).
4. `LISTING_STATUS` cross-check against `identity_map_v2.csv` ambiguities.
