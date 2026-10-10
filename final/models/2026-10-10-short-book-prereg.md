# WO-60 pre-registration: bottom-decile hedged SHORT book (composite short book, formal trial 1)

Date: 2026-10-10. Branch: `wo60-short-book`. Work order: `~/.claude/pipe_dream-coordination/wo/wo60.md` (COO, requested by Gabe 2026-10-10).
Frozen BEFORE any outcome (forward return) is computed. Its sha256 is in the ledger row.

**Trial count.** Family "composite short book": this is formal trial 1. Informal looks already spent: 3 (COO 2026-10-09/10; one of them was hold-out read #24). Iteration cap: 3 fix-and-rerun cycles, counted from launch.

**Hard rules.** No code here can place, modify or cancel an order; picks are recommendations only (AGENTS.md constraint #7). No 2020+ outcome is read: signal dates are cut at 2019-10-24 (asserted in code) before any return column is joined, and no price later than 2019-12-31 is read. Era 2007-01-01..2019-12-31. Universe columns come from `composite_panel_v2.parquet` (the v2 grid, survivorship-safe).

What was done before freezing (no outcome touched): the in-era short-interest pull (Compustat, see section D below), the Markit fee-unit check, and Gate A5. These are in `final/out/shortbook/prechecks.json`:
- Markit fees are annual fractions. The median `indicativefee` by DCBS runs from 0.00375 at DCBS 1 to 0.60 at DCBS 10.
- In-era SI coverage of the tier universe is 96-99% every year.
- A5: max abs score diff is 0.0 and bottom-decile overlap is 100%, on 3 dates × 2 tiers.

---

## A. Verbatim from WO-60: Borrow-cost model (pre-declared; this is the deciding input)

Build, in order:
B1. **Markit calibration (one date).** WRDS `mrktsamp_msf.amereqty2011` (accessible sample, 2011-03-21, ~8,581 US equities, fields indicativefee, dcbs, utilisation). Link via CUSIP to the panel. Report the fee distribution (median, p75, p90, share with DCBS ≥ 3) for the cap2000 bottom decile, the cap150 bottom decile, and the full universes on that date. Fit ONE pre-declared tier map: fee tier by (utilisation proxy = short_interest_days_to_cover quintile within date) × (price < $5). Use the 2011 fit tier medians as fees for all dates. No other specification.
B2. **Option-implied borrow (cross-check, optionable names only).** From OptionMetrics opprcd (final/data/wrds/optionm/opprcd/), compute put-call-parity implied borrow on the WO-37 grid dates for bottom-decile names. Use it only to check that the B1 tiers are not too low: report the median B2 vs B1 fee by year. This is a cost input, NOT a factor test; it does NOT count toward the options tally.
B3. **Stress:** B1 fees + 3%/yr flat on every short.
Not shortable: any name with B1-tier fee > 10%/yr or price < $5 at entry is excluded from the short book. Report the excluded share.

## B. Verbatim from WO-60: Primary metric and null; SUCCESS and KILL criteria

M = mean annualized net return of the cap2000 short book, hedged with H1, net of 15bp/side and B1 fees, averaged over 40 offsets, 2007-2019.
Null = the same statistic for 200 within-date score shuffles (A3).

### SUCCESS criteria (all must hold → PROMOTE-CANDIDATE to Gabe for a forward paper ledger)
S1 M ≥ +3.0%/yr.
S2 M under B3 stress ≥ +1.0%/yr.
S3 M > p95 of the shuffle null.
S4 ≥ 36/40 offsets with M > 0.
S5 LOYO: minimum over dropped years of M ≥ +1.5%/yr, and no single year > 35% of the summed annual effect.
S6 Attribution: (a) sector-neutral variant (bottom decile within sector) M > 0; (b) H2 beta-matched book net > 0; (c) M on the lower-half-SIR names (easy-to-borrow subset: below the within-date median of short_interest_days_to_cover) under B1 fees > 0.
S7 Construction sensitivity: bottom 5% and bottom 20% (same construction) both M > 0.
S8 Gate A all pass.

### KILL criteria (any → DEAD, record in COO.md certified dead ends)
K1 M ≤ 0.
K2 S6(c) ≤ 0, i.e. the edge exists only in hard-to-borrow names: not tradeable at retail.
K3 M ≤ p80 of the shuffle null.
K4 LOYO minimum ≤ 0.
Anything between success and kill → ITERATE: name the one fix and report it to COO. Do not run it without COO sign-off.

---

## C. Implementation (pre-declared here; the WO leaves these open)

**Score (Gate A5).** This is the live icw5_seas model, `ICW.PRODUCTION_WEIGHTS_V5_SEAS`. Each factor is rank_z'd within date over the tier's eligible universe (cap2000 or cap150) after the v2 universe rule (old 4,011-ticker grid OR not a SPAC). The score is the coverage-aware weighted mean. `seas` is the WO-18/WO-23 extension file, which A5 shows equals `seas_live.seas_asof` exactly.

**Construction.**
- Picker: `composite.pick_decile_volq` logic on the NEGATED score, which selects the lowest scores. Within each of 5 `volatility_60` quintiles of the date's valid names (finite vol and score), it takes k = max(1, round(0.10·n_bucket)) names.
- Weighting: EQUAL weight. The inverse-vol weights are discarded.
- Shortability filter: applied after picking. A name is dropped (not replaced) when its next-day open (entry price) is < $5 or its B1 tier fee is > 10%/yr. The remaining names are equal-weighted. The same filter applies in the real run, all 200 shuffles, and every variant.
- Schedule: 40-trading-day hold, rebalanced every 40 rows of the panel's date grid. Results are averaged over all 40 offsets.
- Signal dates: 2007-01-03..2019-10-24.

**Returns (total return, all legs).**
- Stock leg: `outcome_cache_v2.gross_return_40` = close[t+40]/open[t+1] − 1, which floors at the series' last close when the series ends inside the window (flag `truncated`). On top of that comes the dividend leg, close[x]/open[e]·(f[x]/f[e] − 1) with f = SEP closeadj/close, which is the `pool_read.book_divs` arithmetic. The short pays −(price + dividend) return.
- Dividend cleaning: a dividend leg is set to 0 (and counted) when it is non-finite or |div| > 0.25.
- SPY (H2/H3): total return from the yfinance bench file (open/close/adj_close), close[t+40]·f / open[t+1]·f − 1.

**Delistings / NaN labels (not dropped).**
- Which positions count: every pick whose price series ends inside the hold, i.e. `truncated` in the cache. This is the set where the panel's `forward_return_tradable_40` is NaN. A pick whose cache return is NaN (no bar after t) counts too, at a price return of 0 to the last close.
- CRSP link: these positions are linked ticker → permno via `permno_sharadar.parquet`, then to a CRSP `dsedelist` record with dlstdt in [series last date − 5d, series last date + 60d].
- Delisting return: the stock return becomes (1 + r_to_last_close)·(1 + dl) − 1. dl = CRSP dlret when non-null. When dlret is null: −0.30 for dlstcd 400-599 (Shumway 1997), 0 for dlstcd 200-399. Unlinked positions and CRSP-active ones (dlstcd < 200) get dl = 0.
- Classes reported (counts and P&L contribution): cash/stock merger (200-299), exchange (300-399), liquidation (400-499), performance/bankruptcy drop (500-599), CRSP-active/still trading, unlinked.
- The same rule is applied to every row of the H1 universe leg.

**Hedges.**
- H1 (primary): long the equal-weight eligible tier universe on the same date, dollar-neutral, using every eligible row, with the same delisting rule.
- H2: long SPY × book beta, where book beta is the mean of the book names' `beta_252` (trailing 252d vs SPY, data ≤ t) at t.
- H3: long SPY 1:1.

**Costs.**
- Per offset chain, 15bp × Σ|Δw| on each leg at each rebalance. Weights are undrifted target weights. The first period pays entry, and the final exit is charged in the last period.
- H1 universe leg: same rule on its EW weights.
- SPY legs: 15bp × |Δk|.
- Short credit 0. No margin interest.

**Borrow.** fee_i × 40/252 on short notional, for every name in the short book, including truncated ones (charged for the full window).

**Net per-period return (H1).** R = −r_short_book + r_universe − costs − borrow. M is the per-offset mean of R × 252/40, averaged over the 40 offsets. H2 and H3 replace r_universe with k·r_SPY.

**Statistics.**
- LOYO: per offset, mean with year y removed, then averaged over offsets. S5 and K4 use the minimum over y.
- Year share: the year's sum of offset-averaged per-period R divided by the total sum, computed only when the total is > 0.
- S4: per-offset M > 0.

**Null (A3).** 200 draws, seeds 60000..60199. The finite scores are permuted uniformly within date (`shuffle_within_date` logic), followed by the identical picker, filter, hedge H1, costs and B1 fees. S3 uses p95 and K3 uses p80 of the 200 draw-level M's.

**Variants.**
- S6(a): bottom 10% within each `sector` (date × sector cells, k = max(1, round(0.1 n)), Unknown/NaN sector treated as its own cell). Equal weight, H1.
- S6(c): the real book restricted to picks with days_to_cover below the within-date median of the tier universe. Picks with missing SI are excluded from the subset. H1, B1 fees.
- S7: book_frac 0.05 and 0.20.
- Per-name cap: positions resized so no name exceeds 2× equal weight at any mark. Only the 40-day grid marks exist, so at the open weights are equal and the cap is non-binding. The variant reports clipping each name's period P&L contribution at 2× its equal weight × its loss. This is descriptive only.

## D. Implementation: data substitution (WO assumed a field that does not exist pre-2020)

The panel's `short_interest_days_to_cover` is 0% non-null for 2007-2019, because the FINRA pull starts 2020-04. B1's tier map, S6(c), K2 and the SI-top-decile overlap therefore use Compustat `comp.sec_shortint`, built by `final/src/shortbook/build_si.py`:
- days_to_cover = shortint / mean CRSP dsf `vol` over the 20 trading days ending at datadate (the settlement date).
- Available at datadate + 8 business days (FINRA publication lag, the same rule as `sweep/short_interest.py`). Attached as-of, at most 45 days stale.
- Linked gvkey/iid → permno via `crsp.ccmxpf_lnkhist` (LC/LU, P/C), then permno → Sharadar ticker.
- Coverage of the tier universe: 96-99% every year.

**B1 tier map.**
- Calibration set: Markit 2011-03-21, US Equity marketareas only (7,299 rows; the WO's ~8,581 is not what this sample holds). Rows are linked by CUSIP(8) → CRSP stocknames.ncusip valid that date → permno → ticker, then joined to the cap150 eligible universe on 2011-03-21.
- Cells: DTC quintile (within date, over the tier universe) × (close < $5).
- Missing-SI rule: a name with missing SI is assigned the highest tier fee in the map (conservative).
- Fee: the cell median indicativefee (annual fraction).
- Applied to all dates: each name's within-date DTC quintile (cap150 universe quintiles for both books) × price bucket gives its fee.

**Gate A pass rules.**
- A1: a code assertion that SI availability is ≥ datadate + 8 business days and that seas months end before t. The A5 identity confirms seas.
- A2: no NaN-label pick dropped (count = 0). Report later-delisted share in the bottom decile vs the universe.
- A3: the null runs and its p50 ≤ 0 (a random hedged short book should not earn money after costs).
- A4: the 20 largest winning short positions are re-priced from CRSP dsf (openprc on t+1 to prc on the exit date, cumulated with ret/retx ratios) and match within 5pp, with any delisting explained. A ticker-reuse splice or reverse-split artifact fails A4.
- A5: max abs score diff < 1e-9 and bottom-decile overlap = 100% on all 3 dates.
