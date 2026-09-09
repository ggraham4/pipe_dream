# Data pipeline handoff — how the point-in-time dataset was built

**Written:** 2026-09-09 (Round 11) · **Audience:** the next agent on this project
**Purpose:** reproduce this dataset from scratch, understand why each decision was
made, and never have to re-litigate the data layer. Modelling effort should start
from here.

Read this before touching `final/data/sharadar/` or any `*_sharadar_*` script.
A copy also lives in the Claude Project as `claude/DATA-PIPELINE-HANDOFF.md`.

---

## 0. One-paragraph summary

Every backtest before 2026-09-09 was measured on a candidate universe that was
**hindsight-determined**: "companies worth >$2B *today*, plus a partial patch of S&P
500 leavers." Against a genuinely point-in-time universe, that pool was missing a
third of eligible names in the early era, and 89% of what was missing had since
died. Four separate data defects were found and fixed. The dataset is now rebuilt
from Sharadar: 30M price rows, 30M daily market caps, 631k as-reported filings, a
6.9M-row point-in-time universe, and a 12.3M-row feature panel over 4,011 tickers.
**None of this improved the model.** It replaced the ground the model stands on.

**Result on the rebuilt data (124 windows, 2007-2026, augmented model):**
excess return over SPY **−0.11% per window, t = −0.09**; compounded **1.00x vs SPY
5.23x**; beat rate 49% in both eras. The edge was the survivorship artifact.

---

## 1. The four defects, and how each was found

Three of the four were invisible to every automated check in place at the time.

### 1.1 The universe was survivorship-determined (the big one)

Gate B4 failed at IC +0.1262 against a 0.10 ceiling — failing for being *too high*.
A three-way ablation showed why:

| gap tickers | mean IC |
|---|---|
| waved through the eligibility floor | +0.1350 |
| facing the same floor | +0.1262 (barely moved) |
| removed entirely | **-0.0013** (collapses) |

The screen was irrelevant; *presence* was everything. The pool was survivors plus a
partial sample of losers, and group membership is only knowable after the fact — so
the model could separate the two groups without learning anything about selection.

Quantified after the rebuild, restricted to domestic common stock:

| date | eligible | old pool had | missing | of which dead |
|---|---|---|---|---|
| 2008-06-30 | 981 | 666 | 315 | 281 (89%) |
| 2014-06-30 | 1,418 | 923 | 495 | 396 (80%) |
| 2020-06-30 | 1,344 | 1,050 | 294 | 177 (60%) |
| 2026-06-30 | 1,701 | 1,576 | 125 | 11 (9%) |

Missing names: Genentech, Monsanto, Anheuser-Busch, Dell, DuPont, Wachovia,
Schering-Plough, EMC, DIRECTV, Praxair, Yahoo, Sprint, Anadarko, Baker Hughes.

### 1.2 41 of 264 "gap ticker" price files were the wrong company

Ticker symbols get reissued. A pull keyed on symbol returns whoever holds it now.

```
FB    price series from 2025-06-26   left the index 2022-06-08
EMC   from 2023-05-15                left 2016-09-06
APC   from 2026-02-12                left 2019-08-08
```

46,854 wrong-issuer bars, 68% of them inside the 2020-2026 hold-out. Zero reached a
pick, but they were 7.8% of the gap candidate pool, rising to **41% by 2026**.

**Found by** a test needing no vendor data — a gap ticker is in the panel *because*
it was in the index, so its price history must overlap its index membership. If the
series starts after the company left, it cannot be that company.
`final/src/audit_gap_ticker_identity.py`, offline, exits 1 on failure.

**Why nothing caught it earlier:** every prior check tested *internal* coherence.
A wrong-issuer series passes all of them — it is a real, clean, correctly-adjusted
price series; it is just someone else's. **Coherence checks cannot detect identity
errors.**

### 1.3 The $10 price floor was look-ahead

`MIN_PRICE` was applied to `close`, which is *split-adjusted*.

```
AAPL 2008-06-30   close (adjusted) $5.98   closeunadj (actual) $167.44   mcap $147.6B
```

Apple's 7:1 (2014) and 4:1 (2020) splits give a 28x divisor — so its eligibility in
**2008** was decided by a corporate action announced in **2020**.

The bias runs the wrong way: companies split *because* the stock rose, so the floor
retroactively removes the biggest future winners. On 2008-06-30 it excluded 44 names
worth **$708B** — AAPL, AMZN, NVDA, CMCSA, CSX, TJX, INFY.

**This is inherited.** The old pipeline screens `test_rows["close"] > MIN_PRICE` the
same way, so every prior backtest excluded Apple, Amazon and NVIDIA from its early
windows.

**Found by** printing the 2008 universe and noticing Apple was missing. Every
automated check passed — 928 names, correct megacaps at the top.
**Count checks cannot detect a missing member.**

### 1.4 Features computed on not-yet-existing corporate actions

~240 tickers' old features used prices carrying spinoff adjustments that had not
happened at the feature date. AIV (spun off AIR in 2020) shows old close $0.8850
against Sharadar's $54.6480 on 2006-02-01, with **identical volume**. Materially
small — 97% of shared rows agree to better than 1e-4 — but real.

---

## 2. What exists now

All paths relative to `final/`. Bulk data is gitignored; regenerate with §3.

| artifact | rows | what it is |
|---|---|---|
| `data/sharadar/panel/daily/YYYY-MM.parquet` | 30,000,256 | market cap + EV/PE/PB/PS per ticker per day, 2005-01-03 .. 2026-09-08 |
| `data/sharadar/panel/stocks/YYYY-MM.parquet` | 32,545,767 | OHLCV + closeadj + closeunadj, same span |
| `data/sharadar/tickers_master.csv` | 20,965 | equity master; permaticker, isdelisted, first/lastpricedate, category |
| `data/sharadar/actions.csv` | 48,558 | corporate actions — **rolling 1 year only**, not an archive |
| `data/sharadar/sf1_shares.csv` | 630,960 | filed share counts (ARQ+ARY) |
| `data/sharadar/sf1_fundamentals.parquet` | 631,185 | as-reported fundamentals, 13,864 tickers |
| `data/sharadar/pit_universe.parquet` | 6,888,686 | **the universe** — 5,454 trading days, 4,011 tickers |
| `data/sharadar/identity_map_v2.csv` | 264 | old gap symbol -> permaticker (largely superseded) |
| `scripts/td_data_sharadar/{TICKER}.csv` | 12,270,047 | per-ticker OHLCV for execution, 4,011 files |
| `out/features_sharadar_pit.parquet` | 12,335,243 | 11 price features + 2 labels |
| `out/features_with_fundamentals_sharadar_pit.parquet` | 12,335,243 | + 14 fundamental features |

---

## 3. Reproduction sequence

**All API pulls must run in Gabe's own terminal.** `api.sharadar.com` is unreachable
from both the Claude cloud sandbox and the device-bridge VM (curl returns `000`).
The key lives in the Claude Project, never in this repo.

```
export SHARADAR_API_KEY="<from the Claude Project>"
cd ~/pipe_dream/final/src
```

One command per line. A trailing `# comment` parses as an argparse argument and has
silently skipped probes before.

| # | command | runtime | produces |
|---|---|---|---|
| 1 | `python3 sharadar_build_identity_map.py` | ~3 min | tickers_master.csv, actions.csv, identity_map.csv (**superseded — use v2**) |
| 2 | `python3 resolve_identity_map.py` | <1 min | identity_map_v2.csv (offline) |
| 3 | `python3 sharadar_pull_pit_panel.py` | ~73 min | panel/daily + panel/stocks |
| 4 | `python3 sharadar_pull_shares.py` | ~3 min | sf1_shares.csv |
| 5 | `python3 sharadar_pull_fundamentals.py` | ~2.5 min | sf1_fundamentals.parquet |
| 6 | `python3 build_pit_universe.py` | ~5 min | pit_universe.parquet |
| 7 | `python3 build_features_sharadar.py` | ~10 min | features_sharadar_pit.parquet |
| 8 | `python3 build_features_fundamentals_sharadar.py` | ~15 min | features_with_fundamentals_sharadar_pit.parquet |
| 9 | `python3 export_sharadar_ohlc.py` | ~10 min | scripts/td_data_sharadar/ |

Step 3 is resumable to the month. Peak RSS for 7-9 is a few GB.

Then:

```
python3 continuous_walkforward_pit.py --mode augmented --universe pit
python3 current_signal_pit.py                 # live signal, PIPE_DREAM_UNIVERSE=pit by default
```

---

## 4. Acceptance tests — run these

Row counts looked right while Apple was missing. Do not skip.

**4.1 Issuer identity** (offline, exits 1): `python3 audit_gap_ticker_identity.py`

**4.2 Known-member spot check** — catches what counting cannot:

```python
import continuous_walkforward_pit as W
m = W.load_pit_universe()
for t in ["AAPL","AMZN","NVDA","CMCSA","TJX","CSX","MSFT","XOM",
          "WB1","SGP1","DNA1","MON2","POT"]:
    assert t in m["2008-06-30"], t
assert "WB1"  not in m["2012-06-29"]   # Wachovia, gone 2008
assert "MON2" not in m["2020-06-30"]   # Monsanto, gone 2018
```

**4.3 Two market caps reconcile** — for real companies they agree to 6 decimals:

```
2008-06-30  XOM   daily 465,652.0   close x shares 465,651.992672
2008-06-30  GE    daily 266,029.9   close x shares 266,029.906000
```

**4.4 Corrupt tickers excluded** — DIGA, COR3, CHIO, ICLD, RAMR, CERPQ, FDNHQ,
AXPWQ, MERR eligible on **0** of 5,454 days (NBRVF on 2).

**4.5 Feature parity**: `python3 build_features_sharadar.py --verify`
Expect ~89% of shared rows identical to float32 noise and **97% within 1e-4**. Do
NOT expect a clean pass — see §6.3. Investigate only if the *distribution* shifts,
not the count above 1e-6.

---

## 5. Sharadar API facts that took real work to learn

`GET https://api.sharadar.com/v1.0/data/{table}?api_key=...&format=csv`

- **Paging:** `offset=` works (so does `skip=`). `page=`, `start=`, `cursor=` are
  ignored. A short page means done. `format=json` returns `{"count":N,"data":[...]}`.
- **Date-keyed queries need no ticker filter** — `stocks?date=2015-06-30` returns the
  whole cross-section. This is what makes a PIT universe possible at all.
- **`tickers` must be filtered to `table=stocks`.** Unfiltered it is 50,000+ rows
  dominated by institutional investors, insiders and funds, and truncates at the
  limit — which produced a false "41 of 41 symbols not in master" result.
  **A query returning exactly its own limit has not answered the question.**
- **`daily.marketcap` is in MILLIONS. `fundamentals.marketcap` is in DOLLARS.**
  Nothing in either schema says so. **The screen is `marketcap >= 2000`.** Off by
  1e6 and the universe is silently the wrong ~5,000 companies while every downstream
  number still looks reasonable.
- **`sharesbas` and SF1 `price` are retroactively split-adjusted**, matching the
  panel's `close`. AAPL's 2008 filing reads 24.6B shares, not the ~890M actually
  outstanding. So `close x sharesbas` is internally consistent.
- **Dead companies are addressable two ways:** a numeric suffix on the older holder
  of a reused symbol (`BSC1`, `CA1`, `EMC1`, `SPLS1`, `APC1`, `SGP1`, `WB1`), or a
  bankruptcy `Q` symbol (`LEHMQ`, `WAMUQ`, `ENRNQ`, `SHLDQ`, `BBBYQ`, `SIVBQ`).
  `relatedtickers` cross-links them.
- **The suffix number is recency-ordered, not semantic.** `MON1` is the Money Store;
  `MON2` is Monsanto. `WB1` and `WB2` are both Wachovia. **Use date containment
  against index membership, never the suffix.**
- **`actions` is a rolling ~1-year window**, not a historical archive. Use
  `tickers.lastpricedate` as the death-date proxy.
- **`stocks` gives `close` (split-adjusted), `closeadj` (total return) and
  `closeunadj` (raw) as separate columns.** Explicit basis — the main reason to
  prefer this vendor over a consumer feed.
- **SF1 `date` is the filing date; `calendardate` is the period end**, ~4-6 weeks
  earlier. Using `calendardate` puts a month of look-ahead into every fundamental.
- **Use ARQ/ARY only** (as-reported). MR* carry later restatements.
- SPY is an ETF and **not** in the `table=stocks` panel; it comes from
  `scripts/td_data_local/SPY.csv`, unchanged from every prior result.

---

## 6. Design decisions, and why

### 6.1 The universe screen is an *agreement* rule, not a blocklist

Two independently populated columns give a market cap: `daily.marketcap`, and
`close x sharesbas`. Where both exist and **`daily` exceeds the computed value by
more than 10x**, the row is dropped. No plausibility threshold, no curated list.

Two earlier attempts failed, and how they failed is the lesson:

1. **A threshold on implied share count (30bn).** Arbitrary. RAM Holdings sat at
   27.25bn — just under — with a real count of 27.3 *million*, and at $27B it walks
   into a $2B screen. CHIO at exactly 32bn sat just above.
2. **A symmetric ratio band.** Flagged 527,476 rows across 354 tickers, **93% of
   them ADRs behaving correctly** — an ADR's price is per depositary share while
   `sharesbas` counts ordinary shares (TSM 0.2 = 5:1, TM 0.1 = 10:1).

Both were **magnitude rules on a derived quantity, and those cannot separate a wrong
value from a large one.** Only comparing two independently recorded quantities can.

**The test is one-sided** because direction is informative. `daily` >> computed means
`daily` is wrong (DIGA, RAMR, CERPQ, FDNHQ, AXPWQ, MERR, NBRVF — all corrupt).
Computed >> `daily` is always a depositary-ratio artefact (ONC/BeOne ~$40B real,
GWPH acquired for $7.2B, MTBLY/Renren ~$7B). A symmetric band discarded three real
companies to catch nothing extra.

**A missing filing is not a disagreement.** Requiring both to clear $2B would drop
Lorillard ($12,029M), Freddie Mac ($10,611M) and IHS Markit ($4,783M).

### 6.2 The price floor uses `closeunadj`

See §1.3. Unplanned bonus: this removed the corrupt micro-caps directly (their
reverse splits had inflated their *adjusted* historical prices above $10), so the
agreement rule now only has to catch RAMR.

### 6.3 Features use `close`, not `closeadj`

`closeadj` (total return) would be more economically correct. Deliberately not used:
switching now would confound the universe change with a label change across every
dividend payer. **The labels exclude dividends, as they always have.**

The old CSVs matched Sharadar's `close` to four decimals for AAPL and XOM — but that
generalisation came from two tickers that happen not to expose the difference, and
was **wrong for ~13% of tickers** (§1.4). Do not repeat that inference.

### 6.4 Feature definitions are imported, never restated

`build_features_sharadar.py` imports from `features.py`;
`build_features_fundamentals_sharadar.py` imports `process_ticker` from
`fundamentals_features_beta.py`. A downstream difference can then come from the data
or the universe, but not from two copies of a formula drifting apart.

### 6.5 Execution reads the Sharadar export *alone*

`PRICE_DIRS_PIT = [td_data_sharadar]` — not first-in-list. "Earliest directory wins"
covers a ticker present in both, but not one present *only* in the old dirs, where
`td_data_delisted` still holds the 41 wrong-issuer files. The export uses the schema
`execution.py` already expects, so **no execution code changed**.

### 6.6 The old eligibility floor is skipped on the `pit` path

`pit_universe.parquet` already encodes market cap, price and the agreement rule as of
each date. Re-applying the floor would use the panel's `market_cap` column, a
*different quantity* (`close x sharesbas`), and would reimpose a survivor screen on a
pool built to avoid one. Same reasoning applies in `current_signal_pit.py`.

---

## 7. Known limitations carried forward

1. **Labels exclude dividends** (§6.3).
2. **`actions` has no history** beyond ~1 year (§5).
3. **The identity map is one permaticker per symbol.** `WB` spans old Wachovia and
   the post-2001 merged entity. Moot now the universe builds from the panel directly.
4. **`CCEP` unresolved** — a successor entity, not symbol reuse; the date rule cannot
   catch it.
5. **123 of 4,011 universe tickers never get complete features** — short series
   (25-229 rows), excluded by the 252-day `pct_from_high_252` requirement.
6. **ADRs and Canadian listings are out of scope** by choice. Whether they *should*
   be in is a design question, not a bias.
7. **`gap_picks` / `n_gap_tickers_eligible` in the walk-forward JSON are meaningless
   on the `pit` path** — computed against the old list. Cosmetic.

---

## 8. Traps that cost time

- **Schema drift in streaming writes.** Three bugs, same shape: `sharesbas` inferred
  `int64` in a month with no nulls and `float64` elsewhere; string dates in a
  `merge_asof`; `datetime64[us]` from parquet against `[ns]` (pandas 2 preserves the
  stored unit; `merge_asof` requires an *exact* dtype match). **Declare one schema up
  front and cast every batch to it.**
- **Accumulate-then-concat OOMs.** Stream to `pq.ParquetWriter` instead.
- **The device-bridge VM has ~3.9GB**, background processes do not reliably survive
  between calls, and logs written to `$HOME` there are invisible across calls. Long
  runs belong in a real terminal.
- **`--help` on `continuous_walkforward_pit.py` is broken** by a pre-existing `%` in
  a help string. Not from this round; unfixed.

---

## 9. What is NOT done

- **The gates have not been re-run.** `claude/validation-gates.md`'s B4/B6 FAIL was
  measured on defective data — untrustworthy in *either* direction.
- `tail_null.py`, `gates_b4_b6.py`, `validate2.py`, `xsec_test.py` still read the old
  panel paths and need pointing at `out/features_with_fundamentals_sharadar_pit.parquet`.
- **Three comparability breaks must be declared** whenever a new number sits beside
  an old one: different universe; ~13% of tickers on a different corporate-action
  basis; much denser fundamentals (`gross_margin` 21-26% -> 96.2%).

---

## 10. The three sentences worth remembering

**Coherence checks cannot detect identity errors.** A wrong-issuer price series is
real, clean and correctly adjusted; it is just someone else's.

**Count checks cannot detect a missing member.** The 2008 universe had 928 names and
the right megacaps at the top, and no Apple.

**A magnitude threshold on a derived quantity cannot separate a wrong value from a
large one.** Only comparing two independently recorded quantities can.
