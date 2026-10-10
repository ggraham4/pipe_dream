# WO-63 pre-registration: 1998-2006 out-of-era confirmation of the WO-60 short book (Phase 1 freeze)

Date: 2026-10-10. Branch: `wo63-shortbook-1998`. Work order: `~/.claude/pipe_dream-coordination/wo/wo63.md` (COO). Gabe approved using 1998-2006 CRSP/Compustat data for this question on 2026-10-10 ("Use the old data").
Frozen BEFORE any feature code is written and before any 1998-2006 outcome is computed. Its sha256 is in the ledger row.

**Trial count.** Short-book family: WO-60 is formal trial 1. This is its confirmation read, not a new trial. Informal looks before WO-60: 3 (COO, including hold-out read #24). The 1998-2006 window gets ONE read (Phase 2), only after the COO creates `final/out/shortbook1998/PHASE2_RELEASED`.

**Hard rules.** No code here can place, modify or cancel an order (AGENTS.md constraint #7). No 2020+ data of any kind (every WRDS query is bounded at 2010-12-31). Phase 1 computes no portfolio, decile, IC or factor-vs-forward-return statistic on 1998-2006: label columns are built and stored, never aggregated by score. The Phase 2 script refuses to run unless `PHASE2_RELEASED` exists; the worker never creates it. The 2007-2009 bridge uses features only, never labels.

What was looked at before freezing (no outcome touched): WRDS table access and row counts (CRSP dsf, Compustat funda/fundq/co_filedate, sec_shortint, sec_shortint_legacy), the Sharadar `sharesbas` split basis (AAPL 2013-2015: split-adjusted to the current basis), the short-interest coverage table in section E (universe x SI only, no returns).

---

## A. Verbatim from WO-63: BRIDGE CHECK (Gate A5)

5. **BRIDGE CHECK (Gate A5, decisive, no outcomes):** build the same CRSP/Compustat features for 2007-01..2009-12, and compare them with the Sharadar panel (/Users/ggraham/pipe_dream/final/out/reset2026/composite_panel_v2.parquet plus the seas source) on the same dates and tickers (link: final/data/wrds/link/permno_sharadar.parquet). Pass, pre-declared: per-factor within-date Spearman ≥ 0.85 (median over dates) for momentum, gross_profitability, accruals and net_issuance; ≥ 0.80 for seas; composite score Spearman ≥ 0.90; bottom-decile cap2000 overlap ≥ 70%; cap2000 eligibility agreement ≥ 95%. Any fail → fix the mapping (max 3 cycles), then BLOCKED to COO. The 2007-09 overlap uses features only, never labels.

## B. Verbatim from WO-63: Phase 2

## Phase 2 (only after COO writes PHASE2_RELEASED): ONE read
Run WO-60's frozen final construction (primary: cap2000, bottom decile within vol quintiles, EW, universe-hedged H1, 15bp/side, WO-60 B1 borrow-fee tier map, 40 offsets) on 1998-01..2006-12 entries. Also report H2 (beta-matched SPY via CRSP vwretd or SPY from CRSP) and cap150. Compute once and report everything; no reruns with changes.

## C. Verbatim from WO-63: success / kill

CONFIRM (pre-declared): M_1998 ≥ +2.0%/yr net AND ≥ 32/40 offsets positive AND LOYO min > 0 AND no year > 40% of the effect.
FAIL: M_1998 ≤ 0 → the short book is not confirmed; COO recommends DEAD regardless of WO-60.
Between: report as "weak confirmation"; Gabe decides.
Note: 1998-2002 includes the dot-com bubble and bust, the hardest known period for value/quality short books (junk rallied hard in 1999-2000). That is part of the test, not a reason to drop years.

---

## D. Implementation, pre-declared here (the WO leaves these open)

### D1. Model
icw5_seas, frozen, no refit: `ic_weighted_composite.PRODUCTION_WEIGHTS_V5_SEAS` (momentum_12_1 +0.0420, gross_profitability +0.5019, accruals −0.1372, net_issuance_pct −0.1178, seas +0.2013). Score = `ic_weighted_composite.compute_composite_ic_weighted` applied per date over the tier's eligible universe (imported, not copied). Rank_z is within date over the tier universe, exactly as WO-60 section C.

### D2. Universe (CRSP, all names incl. later-delisted)
- Security rows: CRSP dsf rows with a valid price (`prc` non-null and ≠ 0). Security filter from `crsp.stocknames` valid on the date: `shrcd` in {10, 11}, `exchcd` in {1, 2, 3}.
- SPAC rule (mirror of the v2 "not a SPAC" rule): exclude `siccd` 6770 (blank checks).
- **Market cap (primary): permco-summed** `|prc| × shrout / 1000` ($M) over the permco's valid security rows that day. Reason: Sharadar `daily.marketcap` is company-level (it is `sharesbas`-based), so dual-class names carry the whole company's cap. Fallback F-cap: permno-level cap.
- Tiers (nominal, same thresholds as the live v2 grid): `cap2000` = cap ≥ $2,000M AND unadjusted price `|prc|` > $10 (mirror of `closeunadj > 10`; CRSP `prc` is unadjusted; negative `prc` is a bid/ask midpoint, so `abs()`). `cap150` = cap ≥ $150M AND trailing 20-trading-day median dollar volume ≥ $0.25M (min 10 obs), dollar volume = `|prc| × vol / 1e6` (CRSP `vol` is unadjusted shares and `prc` unadjusted, so their product is actual dollars, matching the v2 fix). $2B in 1998 is larger in real terms than $2B in 2019 (roughly 1.4-1.6x by CPI, 1998 vs 2013-2019); the tier is still nominal, as pre-declared by the WO.
- The `cxs_marketcap` disagreement drop in `downcap_universe.py` is a Sharadar data-cleaning rule with no CRSP analog (cap is computed directly from price × shares); not applied.
- NASDAQ volume double counting (Gao-Ritter): NOT applied to the cap150 dollar-volume floor (the live definition has none; the floor is ~never binding at ≥$150M; the binding count is reported). It IS applied to the days-to-cover denominator (D5), because DTC quintiles set fees.
- Eligibility fallback F-reit: if the bridge eligibility check fails and the decomposition shows CRSP shrcd 18 (REIT-type shares, which Sharadar's "Domestic Common Stock" includes) is a main cause, add shrcd 18.

### D3. Prices and labels
- Split-adjusted price `P = |prc| / cfacpr` (mirror of Sharadar `close`: split-adjusted, NOT dividend-adjusted). Open `O = |openprc| / cfacpr`.
- Total-return index `TRI = cumprod(1 + ret)` per permno (ret NaN → 0 within the cumprod), price index `PI = cumprod(1 + retx)`, factor `f = TRI / PI` (the analog of SEP closeadj/close).
- Row index i over a permno's valid-price rows (the analog of the Sharadar series). Entry e = i+1, exit x = min(i+40, n−1), `truncated` = series ends inside the hold, `has_next` = i+1 ≤ n−1.
- Stored label columns (Phase 1 builds, never aggregates): `forward_return_tradable_40 = P[i+40]/O[i+1] − 1` (NaN when truncated, as in the Sharadar panel); WO-60 row-schema columns `r_px = P[x]/O[e] − 1` (to the last close when truncated), `div = P[x]/O[e]·(f[x]/f[e] − 1)` (zeroed and flagged when non-finite or |div| > 0.25, WO-60 rule), entry date/open, `d_x`, `d_last`, CRSP `dlstcd`/`dlret` for the permno's delisting when `dlstdt` is within [d_last − 5d, d_last + 60d], and `dl` per WO-60's rule (dlret when non-null; −0.30 when null and dlstcd 400-599; 0 when null and 200-399; 0 for active), `r_tot = (1 + r_px + div)(1 + dl) − 1`.
- **openprc fallback (declared before measuring its share):** when `openprc` is missing or 0 on day e, the entry price is `P[i]` (the signal-day close), i.e. a close-to-close label for that row. The share of rows using the fallback is reported by year and tier. Same rule for `forward_return_tradable_40`.
- beta_252: mirror of `build_beta_feature.py`: trailing 252-row (min 126) OLS beta of daily `P` returns on SPY daily returns, SPY = CRSP permno 84398 (`prc`/`cfacpr` price return, as the live SPY.csv close). SPY exists from 1993-01-29, so 1998 betas are fully covered. SPY for H2/H3 is built in WO-60's bench format (open, close, adj_close) from CRSP 84398 (adj_close = close × f).
- sector: Sharadar `tickers_master.sector` via the permno→ticker link when linked; otherwise the modal Sharadar sector among linked permnos with the same 2-digit SIC (CRSP `siccd`); otherwise "Unknown".

### D4. Factors (primary mapping, Sharadar SF1 → Compustat)

| live factor | live definition (Sharadar) | Compustat / CRSP port (primary) | PIT rule |
|---|---|---|---|
| momentum_12_1 | close(t−21)/close(t−252) − 1, rows within ticker, split-adj close | `P` (= abs(prc)/cfacpr) shifted 21 / 252 rows within permno | data ≤ t (row t−21) |
| gross_profitability | gp(latest ARY filed ≤ t) / assets(latest ARQ/ARY filed ≤ t) | `funda.gp` (= revt − cogs; when null, revt − cogs) / assets | gp: funda datadate + 90d; assets: see below |
| accruals | (netinc − ncfo)(latest ARY) / assets | (`funda.ni` − `funda.oancf`) / assets | funda datadate + 90d |
| net_issuance_pct | sharesbas(latest ARQ/ARY ≤ t) / sharesbas(latest ≤ t−365d) − 1, split-adjusted basis | adjusted shares = `cshoq × ajexq` (fundq) and `csho × ajex` (funda), same ratio | fundq: rdq (fallback datadate + 90d when rdq is null); funda: datadate + 90d |
| assets (stock) | ARQ + ARY, latest filed ≤ t | `atq` (fundq, at rdq; fallback datadate + 90d) ∪ `at` (funda, datadate + 90d), latest available ≤ t | as stated |
| seas | mean over y = Y−10..Y−1 of r(i,y,m), r = ME(m)/ME(m−1) − 1 on closeadj (total return), ≥5 finite, target month of t+28d | same, on CRSP `TRI` month-ends (last valid-price day of each calendar month), per permno | last month used ends before t (asserted) |
| volatility_60 (construction) | rolling 60-row std of daily close pct_change | same on `P` | data ≤ t |
| days_to_cover (S6(c)/fees) | WO-60 build_si: shortint / mean CRSP vol over 20 days ending at datadate | same; NASDAQ vol ÷ Gao-Ritter divisor (2.0 before 2001-02-01, 1.8 to 2001-12-31, 1.6 in 2002-2003, 1.0 from 2004) | datadate + 8 business days, ≤ 45 days stale |

- Compustat filters: `indfmt='INDL' and datafmt='STD' and popsrc='D' and consol='C'`. Duplicates per (gvkey, datadate) keep the last row. Filed observations with the same available date keep the last (mirror of `drop_duplicates(keep='last')`).
- Link permno → gvkey: `crsp.ccmxpf_lnkhist` LC/LU, linkprim P/C, valid on t. All permnos of a gvkey get its fundamentals.
- Ordered fallbacks for the fix cycles (one fix cycle = one mapping change followed by one bridge rerun; at most 3; chosen in this order for whichever check fails, most-failing check first):
  - PIT fallback F-file (all fundamentals): available date = `comp.co_filedate` 10-K/10-Q `filedate` for that (gvkey, datadate) when present, else the primary rule. This mirrors Sharadar's datekey (SEC filing date) more closely.
  - gross_profitability F-gp: gp − dp (Sharadar cor often includes D&A).
  - accruals F-acc: `ib` in place of `ni`.
  - net_issuance F-shr: CRSP `shrout × cfacshr` as-of the fundq available date.
  - market cap F-cap, universe F-reit: see D2.
  - seas F-seas: CRSP `ret` compounded within month without the valid-price-day restriction.

### D5. Short interest
- 1998-2006: `comp.sec_shortint_legacy` (monthly settlement dates); from 2006-10-01: `comp.sec_shortint` (the file WO-60 uses). Legacy rows with datadate < 2006-10-01, current rows ≥ 2006-10-01.
- Same as WO-60 build_si otherwise: link gvkey/iid → permno via ccmxpf_lnkhist (iid = liid, datadate in link range), dtc = shortint / adv20 (20-day mean of CRSP vol ending at datadate, Gao-Ritter divided for exchcd 3), available = datadate + 8 business days, as-of attach with ≤ 45 days staleness.
- Coverage before 2003 is NYSE/AMEX only (section E). The consequence for WO-60's "missing SI → highest tier fee → >10%/yr not shortable" rule is a COO decision, flagged in the handoff. Phase 1 does not decide it.

### D6. Bridge mechanics (Gate A5)
- Dates: every CRSP trading date 2007-01-03..2009-12-31.
- Sharadar side: `composite_panel_v2` rows with the WO-60 universe rule (old 4,011-ticker grid OR not a Blank Check SIC), `eligible_cap2000`, factors from the panel, seas from WO-60's `SEAS_EXT` file. CRSP side: this build. Link: `permno_sharadar.parquet` (ticker, permno, valid range ± 31 days, WO-60's tolerance).
- Factor Spearman: per date over the intersection (linked, cap2000-eligible on both sides, factor finite on both sides), raw factor values; median over dates. Dates with < 50 pairs are skipped.
- Composite Spearman: each side scores its OWN cap2000 universe with icw5_seas; Spearman on the intersection; median over dates.
- Bottom-decile overlap: each side runs WO-60's picker (bottom 10% within 5 volatility_60 quintiles of its own cap2000 universe, finite vol and score) on its own universe; overlap = |CRSP picks ∩ Sharadar picks (mapped)| / |Sharadar picks|; median over dates.
- cap2000 eligibility agreement: pooled over dates, |both eligible| / |eligible on either side| (Jaccard; a Sharadar-eligible ticker with no permno link, or a CRSP-eligible permno with no ticker link, counts as a disagreement). Disagreements are decomposed by cause (unlinked, shrcd, exchange, cap below/above threshold, price floor, SPAC rule).
- Context only (no threshold): the same statistics on cap150, and per-year medians.

### D7. Gate A on the 1998-2006 panel
Names per year vs CRSP shrcd 10/11 totals; named checks (Enron, WorldCom present before failure and leaving with a dlret; Lehman present 1998-2006; Apple in cap2000 1998-2006 at its real cap); a column assertion that every feature's as-of date (`fund_avail`, `si_avail`, `seas_last_month_end`, momentum source row date) is ≤ t (seas: < t).

## E. Short-interest coverage measured before freezing (universe x SI only, no returns)

Probe: last trading day of June each year, CRSP shrcd 10/11, exchcd 1/2/3, not SIC 6770, permco cap; SI = a linked Compustat SI record (legacy < 2006-10-01, current after) with datadate in [t − 45d, t]. Raw table: `final/out/shortbook1998/prefreeze_si_coverage.csv`.

| June of | cap2000 n NYSE / AMEX / NASDAQ | cap2000 SI coverage NYSE / AMEX / NASDAQ | cap150 SI coverage NASDAQ |
|---|---|---|---|
| 1998 | 631 / 11 / 148 | 0.95 / 0.91 / 0.00 | 0.00 |
| 1999 | 591 / 6 / 179 | 0.94 / 1.00 / 0.00 | 0.00 |
| 2000 | 535 / 6 / 309 | 0.94 / 1.00 / 0.00 | 0.00 |
| 2001 | 564 / 6 / 184 | 0.97 / 1.00 / 0.00 | 0.00 |
| 2002 | 526 / 5 / 110 | 0.98 / 1.00 / 0.00 | 0.00 |
| 2003 | 514 / 5 / 128 | 0.97 / 1.00 / 0.00 | 0.00 |
| 2004 | 623 / 6 / 172 | 0.98 / 1.00 / 0.98 | 0.99 |
| 2005 | 684 / 7 / 182 | 0.98 / 0.86 / 0.98 | 0.98 |
| 2006 | 712 / 6 / 199 | 0.98 / 0.83 / 0.97 | 0.98 |

**NASDAQ short interest is absent from Compustat through mid-2003** (legacy file is NYSE/AMEX only before then; NASDAQ appears in the 2003-2004 data). In 1998-2003, 19-36% of cap2000 names (NASDAQ) have no days_to_cover. Under WO-60's frozen rule (missing SI → highest B1 tier fee; fee > 10%/yr → not shortable) applied mechanically, every NASDAQ name would drop out of the 1998-2003 short book, including the dot-com names the WO says are part of the test. **This is a COO decision before Phase 2** (options include: apply WO-60's rule mechanically and report it; assign NASDAQ-missing names the fee from their within-date NYSE/AMEX-calibrated DTC-quintile-free price bucket; or report S6(c) as not computable for 1998-2003). Phase 1 does not decide it; the Phase 2 adapter exposes the choice as an explicit parameter with no default, so it cannot run until the COO sets it in PHASE2_RELEASED.
