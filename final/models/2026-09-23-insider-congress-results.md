# Insider and congressional trading vs the composite — results

**2026-09-23.** Pre-registration:
`2026-09-23-insider-congress-preregistration.md`, written before any return
was computed. Nomination era 2007-2019, cap150, `forward_return_tradable_40`.
2020-2026 is not touched.

Reproduction (conda env `pipe_dream`):

```
# download: 81 quarterly zips, 868 MB, to final/data/edgar/form345/
# URL pattern: https://www.sec.gov/files/structureddata/data/insider-transactions-data-sets/YYYYqN_form345.zip
python3 final/src/insider/build_insider_panel.py   # -> out/insider/insider_{events,features}.parquet
python3 final/src/insider/screen_insider.py        # -> out/insider/insider_screen_report.json
python3 final/src/insider/posthoc_insider.py       # -> out/insider/insider_posthoc_report.json
```

## Bottom line

1. **The premise that these data only record execution date is wrong for
   both sources.**
   - The SEC's structured Form 4 data sets carry `FILING_DATE` beside
     `TRANS_DATE`. The median gap is 2 days (IQR 1-4), so insiders are
     tested here on when the trade became public.
   - Alpha Vantage's congress feed carries `filed_date` and
     `notification_date`. The median lag is 28 days.
   - Only AV's `INSIDER_TRANSACTIONS` lacks a filing date. It is also
     unusable for other reasons: it has no P/S transaction code, and it is
     today's-issuer-only.
2. **Insider buying does not belong in the composite as a 9th factor.**
   - **Registered trials:** neither passes. `ins_buyers_90` has raw IC
     −0.0006 (t −0.16) and its two halves disagree in sign.
     `ins_sellers_90` is wrong-signed.
   - **Adding either to the composite:** buyers change its IC by +0.0004,
     sellers by −0.0033. Out of sample, the IC-weighted halves disagree in
     sign. The decile_volq book gains 0.1-0.2%/yr, within noise.
3. **Nearly all of the cross-sectional structure in insider activity is a
   sector bet.** Insiders buy most in Financials, Energy and Real Estate,
   and those sectors then underperform. Within a sector, buyers carry
   IC +0.0018 (t 0.65).
4. **One sub-population is live, as a lead rather than a result.**
   *Opportunistic* purchases (Cohen, Malloy & Pomorski 2012) are followed by
   **+0.71% sector-demeaned 40-day return (Newey-West t 1.92, n = 10,419
   events)**. *Routine* purchases are followed by −0.70% (t −1.06). The
   sign split matches the literature, but it is post-hoc, below t = 2, and
   measured on the survivorship-selected cap150 grid (§6). It is a weak
   lead that needs its own pre-registration and new data.
5. **Congress cannot be tested under this project's era rules.** AV's House
   coverage starts mid-2018, and 2020+ is spent. It is a forward-only
   candidate.

## 1. Data

**Insiders:** SEC Insider Transactions Data Sets, 2006Q1-2026Q1.
- **Rows:** original Form 4s only, non-derivative `P`/`S` codes. This gives
  1,456,667 (filing, owner, code) rows.
- **Issuer join:** `ISSUERCIK` → `tickers_master.secfilings` CIK. All 4,011
  panel tickers map, one CIK each.
- **Owners:** officer or director only. Pure 10% owners are excluded.
- **No filing = 0.**

| check (Gate A7c: named, not counted) | expected | found |
|---|---|---|
| filing − trade lag | ≤ 2 business days by rule | median 2 d, IQR 1-4 |
| biggest insider-buy quarter | 2008Q4 (crisis buying) | 2008Q4, 10,011 P rows |
| Dimon JPM purchase, early 2016 | on its filing date | 2016-02-11, $26.6M, column turns on that day |
| dead companies carry buyers | survivorship-safe join | 1,423 of 1,720 delisted panel tickers |
| share of raw P rows in the panel | minority (funds, OTC and micro issuers dominate) | 25-37% per year, no trend break |

**Coverage on the test set** (6.69M cap150 rows, 3,272 dates):
- `ins_buyers_90 > 0` on 19.7% of rows.
- `ins_sellers_90 > 0` on 58.1%.
- Cluster (≥ 2 buyers) on 7.7%.
- Zero-mass `rank_z` is −0.090 for buyers and −0.290 for sellers. A name
  with no activity sits just below the middle, and a buyer scores up to
  +0.5.

**Congress (AV `CONGRESS_TRADES`), coverage only:**
- **By chamber (AAPL, the most-traded name):** 2014-2017 has 0 House rows
  and 14-21 Senate rows a year. House rows begin in 2018 (5 that year).
  Pre-2020 AAPL rows are dominated by two senators (Perdue, Roberts).
  Pelosi has 0 rows before 2020.
- **Lag:** median `filed_date − transaction_date` is 28 days.
- **Pull limits:** the MCP connector's key is free tier (25 requests a day),
  which was hit during this probe, so a full ~1,150-member pull is not
  possible from a session. `final/scripts/av_congress_pull.py` does it with
  the premium key used by the options pull.

## 2. Registered trials

| | `ins_buyers_90` (+) | `ins_sellers_90` (−) |
|---|---|---|
| IC raw, pooled | −0.0006 (t −0.16) | +0.0136 (t +1.95), **wrong sign** |
| odd / even years t | −1.76 / +1.61 | +2.44 / +0.16 |
| IC beta-adjusted | t −0.17 | t +1.84 |
| IC, factor sector-demeaned | t **+3.10** (see §3: artefact) | t −0.39 |
| partial IC given ew8 composite | t +1.88 | t +0.93 |
| partial IC given IC-weighted composite | t +2.30 | t +1.05 |
| corr with ew8 composite (daily Spearman) | −0.169 | +0.270 |
| decile_volq ew9, **gross** excess vs SPY/yr (ew8 baseline +4.82%) | +4.94% | +5.00% |
| 20-draw within-date shuffle null p50 / p80 | +4.83% / +4.86% | +4.75% / +4.81% |
| null percentile of real | 100% (passes gate) | 100% (passes gate) |
| **nominated?** | **no** (fails raw t, fails halves) | **no** (wrong sign) |

**The portfolio gate passes, but it doesn't rescue either column.**
- **Size of the gain:** +0.12%/yr (buyers) and +0.18%/yr (sellers) over
  the 8-factor book. That is about a quarter of the offset-to-offset sd of
  the same book (0.55%/yr).
- **What the null measures:** permuting one column within date moves the
  composite very little, so the null's spread (±0.05%/yr) reflects the
  cost of noise in 1/9th of the score, not how uncertain the book's return
  is. Beating it shows the column is not *pure* noise inside the
  composite. It does not show the gain is material.
- **Why sellers help (unexplained):** sellers are wrong-signed by IC yet
  still improve the book. Selling correlates +0.27 with the composite, so
  the −1 sign partly offsets the composite's own ranking. The mechanism
  inside the volatility buckets was not measured, and a gain whose IC
  points the other way should not be read as insider information.

**Portfolio reconciliation.**
- **Match:** the ew8 book's +4.82%/yr gross (offset sd 0.55%) matches
  `correction_variants_report.json`'s `asset_growth_dropped` cell
  (+4.32%/yr at 15 bp with turnover, sd 0.553%). The gap is the cost drag.
- **Costs not applied:** the ew9 gains are also gross. A 90-day insider
  window adds turnover, so the 0.1-0.2%/yr gain may not survive costs.

**Harness check.** The vectorized composite equals
`composite.compute_composite` exactly on 13 sampled dates. It reproduces
the corrections doc §9b to the fourth decimal: ew8 IC +0.0317 (t 2.53), and
+0.0450 (t 4.25) beta-adjusted.

## 3. Why the sector-neutral t of +3.10 is not a pass

The registered sector test demeans the **factor** within sector and
correlates it with the **raw** return. Here that setup manufactures a
signal:

| sector | fire rate | mean 40d return vs cross-section |
|---|---|---|
| Technology | 11.9% | +0.87% |
| Healthcare | 16.6% | +1.52% |
| Energy | 23.6% | −1.53% |
| Real Estate | 24.0% | −1.06% |
| Financial Services | 30.2% | −0.52% |

Across sectors, corr(fire rate, return) = **−0.79**. Demeaning the factor
alone gives every name in a low-buying sector a small positive score and
every name in a high-buying sector a small negative one. That is a long
Tech/Healthcare, short Energy/Financials tilt, which is the composite's
existing sector bet (Round 13, sector enrichment), reached from the
opposite side. With **both** factor and return sector-demeaned:

- IC +0.0018, **t 0.65**.
- Leave-one-year-out t ranges 0.12-1.29.
- The per-year sign is positive in 7 of 13 years.

Within-sector stock picking by insider buying is indistinguishable from
zero in this universe at a 40-day horizon.

**The raw-IC ≈ 0 is two effects cancelling.** One is a mildly positive
within-sector effect. The other is a negative sector-timing effect:
insiders buy into sector drawdowns that keep going for another 40 days.

**Rule worth keeping.** The `neutralize_on_sector` convention (factor
only) is safe when the factor's sector means are unrelated to sector
returns. For any factor whose sector concentration is itself informative,
report the both-sides number beside it.

## 4. Composite ablation (IC)

| | IC raw | IC beta-adj |
|---|---|---|
| ew8 (current theoretical model) | +0.0317 (t 2.53) | +0.0450 (t 4.25) |
| ew9 + buyers | +0.0321 (t 2.60) | +0.0454 (t 4.40) |
| ew9 + sellers | +0.0284 (t 2.42) | +0.0427 (t 4.37) |
| IC-weighted production (in-sample weights) | +0.0421 (t 5.88) | +0.0422 (t 5.69) |

IC-weighted, out of sample (weights fit on one half, IC on the other):

| fit → test | weight on buyers | icw9 vs icw8 raw | beta-adj |
|---|---|---|---|
| odd → even | +0.099 | +0.0315 vs +0.0304 | +0.0315 vs +0.0305 |
| even → odd | +0.167 | +0.0491 vs +0.0496 | +0.0492 vs +0.0500 |

The two halves disagree (one +0.0011, the other −0.0005): there is no
reliable IC gain. Sellers lose IC in both halves.

## 5. Event study (all officer/director purchases, filing date → next panel date)

t is Newey-West (lag 2) on monthly means: 40-day windows overlap
adjacent months, so an iid t overstates the evidence. The iid version gave
1.80 / 0.63 / 2.10.

| events | n | 40d excess vs cap150 cross-section | beta-adj |
|---|---|---|---|
| all | 40,507 | +0.66% (t 1.51) | +0.65% (t 1.48) |
| cluster, ≥ 2 insiders same filing date | 6,950 | +0.89% (t 0.53) | +0.77% (t 0.27) |
| ≥ $100k | 18,075 | +0.70% (t 1.74) | +0.65% (t 1.55) |

These are raw cross-sectional excess returns, so they include the sector
effect, which here works *against* buyers. The post-hoc split below
demeans within sector.

## 6. Post-hoc (not trials; `insider_posthoc_report.json`)

- **Opportunistic vs routine** (CMP 2012: *routine* = the same insider
  bought in the same calendar month in each of the prior 3 years; only
  insiders with ≥ 3 years of history are classifiable). Sector-demeaned
  40-day return:
  - **Opportunistic:** +0.71% (Newey-West t 1.92, n 10,419; the iid t
    was 2.08).
  - **Routine:** −0.70% (t −1.06, n 2,221).

  This matches the published direction and is the only lead from this
  round, a weak one.
- **Size.** Both-sides-neutral IC by per-date market-cap tercile:
  - **Small:** +0.0120 (t 3.67).
  - **Mid:** −0.0092 (t −2.33).
  - **Large:** −0.0050 (t −1.01).

  The small-cap result matches the literature (insider information is
  worth more where analyst coverage is thin). But the size effect is not
  monotonic, and the mid tercile is significantly the wrong way, so this
  is not yet a result.
- **Survivorship caveat on both bullets.** The reset2026 cap150 grid only
  contains tickers that were cap2000 at some point (memory note,
  2026-09-22). Its "small-cap" tercile is therefore mostly fallen
  large-caps, not true small caps. Neither the size split nor the
  opportunistic split says anything yet about the genuinely small names
  where the literature places the effect.

## 7. Verdict

- **Insider buying/selling as a composite factor:** does not pass.
  Recommended: **certified dead end** for the plain count form in the
  cap150 universe at h = 40. Do not re-screen other windows (30/180 days)
  without a new reason; that would be a search.
- **Opportunistic small-cap insider buying:** a live lead. It needs its own
  pre-registration, and a confirmation on data not yet seen.
- **Congress:** untestable in-era and underpowered. Forward-only.
  - **Evidence behind this:** the coverage conclusion rests on two probes,
    AAPL and Pelosi. The free-tier MCP key allowed no more.
  - **One command unblocks the full dataset:** Gabe runs
    `av_congress_pull.py` with the premium key, about 20 minutes at 60
    requests a minute.
  - **The script is untested** against the REST response shape, because
    this session had no premium key.
  - **After the pull:** a descriptive 2014-2019 read (mostly Senate) is
    possible, if wanted, without touching the spent hold-out.

## 8. Future directions, ranked

1. **Opportunistic-buyer factor, pre-registered.** Define it once:
   CMP-routine exclusion, officer/director, filing-date keyed, sector-
   demeaned. Screen it on the nomination era. The weakness is that §6 has
   already seen the nomination era, so:
   - **(a) Default:** confirm on forward data only, from 2026-09 onward,
     via a prediction-ledger entry.
   - **(b)** Test on genuinely small names outside the ever-cap2000 grid.
     This is where the literature places the effect, but the data doesn't
     exist yet. It needs the down-cap Sharadar price and fundamentals pull
     for the ~5,000 names the feature panel lacks (reset doc gap item 4)
     before it is survivorship-clean. The Form 4 side is ready: the SEC
     data is CIK-keyed and covers every issuer.
2. **Insider sector buying as a sector-timing signal, not a stock signal.**
   The strongest structure found is that sector-level buying intensity
   predicts sector *underperformance* over 40 days. That is a different
   model (sector rotation), and Round 13 found sector timing worth ~0 in
   the old model. Worth one screen at the sector level only if a sector
   overlay is ever on the table.
3. **Form 144 (proposed sales, filed before the sale).** Structured on EDGAR
   from 2023 only, so forward-only. It is the one insider dataset that
   leads the trade instead of lagging it.
4. **Role weighting** (CEO/CFO vs director) and **purchase size relative to
   holdings** (`SHRS_OWND_FOLWNG_TRANS` is in the data set). Standard
   refinements. Try them only inside item 1's pre-registration, not as
   extra searches.
5. **Congress, forward.** Run `av_congress_pull.py` with the premium key.
   Build `cong_net_buyers_90` keyed on `filed_date` and log it in the
   prediction ledger from today. The published-evidence prior is weak:
   vendor claims, no peer-reviewed durable alpha net of the 45-day lag.
   Committee-jurisdiction matching (a member trading in a sector their
   committee oversees) is the one variant with a mechanism.
6. **Insider selling × short interest.** Both are "informed pessimism"
   proxies, and `short_interest_days_to_cover` is already in the
   composite. Sellers here are wrong-signed and sector-driven, so this is
   low priority.

## Files

```
final/src/insider/build_insider_panel.py
final/src/insider/screen_insider.py
final/src/insider/posthoc_insider.py
final/scripts/av_congress_pull.py
final/models/2026-09-23-insider-congress-preregistration.md
final/models/2026-09-23-insider-congress-results.md
gitignored outputs: final/data/edgar/form345/*.zip, final/out/insider/*
```
