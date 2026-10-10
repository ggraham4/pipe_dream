# WO-55 results: opt_cw_spread avoid-screen, out-of-era read on OptionMetrics (2019-01..2025-08)

Dates: 2026-10-09 to 10. Branch `wo55-cwspread-outofera`.

**Frozen inputs, both committed before any 2019+ outcome:**
- Pre-reg: `final/models/2026-10-09-cwspread-outofera-prereg.md`, sha256 72b06653…c7cc.
  Committed in 728740d.
- Amendment 1: `final/models/2026-10-09-cwspread-outofera-amendment.md`, sha256 12a5e572…f453.
  Gabe chose (b). Committed in 6406495.

**Hold-out read #22.** Unfitted, one run (2026-10-10 14:18), 0 of 3 fix cycles used. The guard
checked both sha256 values and recomputed the gate before reading.

## Verdict: PASS (WO-55 bars, thin slice)

| | Thin (binding) | cap2000 (descriptive) |
|---|---|---|
| Entry dates | 80 (2019-01-16 to 2025-08-20) | 80 |
| Names per date (median) | 1,322 | 1,476 |
| **M, % per 40 days** | **+2.364** | +1.448 |
| **NW lag-39 t** | **5.91** | 3.25 |
| **Offsets (even / odd dates)** | **+2.83 / +1.90** | +1.58 / +1.31 |
| Shuffle-null p80 | +0.162 | +0.112 |
| WO-55 verdict | **PASS** | PASS (bars met; descriptive) |
| WO-37 S1-S8 rules (descriptive) | PASS, all 8; no kill trigger | MIDDLE (fails S2 t ≥ 3.75 and S8) |

**Bars:** PASS needs M ≥ +0.5, t ≥ 3.0 and both offsets > 0. All three hold on the thin slice.

**Null-seed calibration.** Thin slice, 100 seeds, labels permuted within date:
- M has mean −0.038 and **sd 0.265**. Real M is about 9 null sd out.
- The lag-39 t has mean −0.19 and **sd 1.86**. That is larger than the 1.5 assumed in WO-37, so
  the real t of 5.91 is about 3.2 null sd out.
- Under the null, the WO-55 verdict rates are PASS 1%, MIDDLE 21% and KILL 78%.

**LOYO, thin slice:**

| Year left out | 2019 | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 |
|---|---|---|---|---|---|---|---|
| M, % per 40 days | 2.31 | **2.92** | 1.95 | 1.94 | 2.33 | 2.59 | 2.50 |

- The minimum is **+1.94** (2022 left out).
- Leaving 2020 out *raises* M, to +2.92. So 2020 is a weak year, not the driver.
- The largest single year carries 30% of the total.

**Robustness, thin slice:**
- Halves: odd years +2.91, even years +1.69; first half +2.13, second half +2.60.
- Sector-neutral: M +1.92, t 4.03.
- Size and volatility removed: M +2.45, t 9.55.

**Median spread** (`opt_spread_atm`, % of mid):
- Thin pool 40.5%; thin bottom decile 46.8%.
- cap2000 pool 14.6%; cap2000 bottom decile 21.6%.

Spreads in 2019-2025 are wider than WO-37's 2008 figures. Arm 1 is a stock-side avoid screen,
so no option is traded and the spread is not a cost here.

**Open-interest terciles, thin slice (descriptive):** thinnest +0.44, middle +1.81, thickest
+4.46. This matches WO-52 (+1.18 / +1.76 / +4.41): the effect grows with option liquidity. It is
a CW-spread effect in smaller names, not a thin-quote effect.

**Compared with in-era (WO-52, 2008-2018):**

| | In-era | Out-of-era |
|---|---|---|
| Thin M, % per 40 days | +2.74 | +2.36 |
| Thin t | 12.2 | 5.9 |
| cap2000 M | +1.15 | +1.45 |

The out-of-era result is about 86% of the in-era thin M.

## Gate and presence checks (recomputed by the guard at read time)

| Check | Value | Bar | Pass |
|---|---|---|---|
| Coverage gate, repaired chain (L1+L2) | 80 of 80 dates | ≥ 72 | yes |
| Coverage gate, frozen WO-52 chain (descriptive) | 61 of 80 | | |
| BBBYQ / RADCQ | 32 of 32 / 50 of 50 dates with a kept chain; must-dates present | | yes |
| TXG | 58 of 58 cap2000 dates, 11 of 11 thin dates | | yes |
| Pool integrity | 100% in panel, 100% in outcome cache | ≥ 99% | yes |
| Dead vs listed, amendment 1 (SIC 6770 excluded; 2,418 name-dates out) | 83.04% vs 85.48%, gap 2.44 points | ≤ 5 | yes |
| Dead vs listed, unamended (it blocked the first attempt) | 79.53% vs 85.34%, gap 5.81 points | | |

**History.** The first attempt (results commit f709dfe) stopped as BLOCKED on the unamended
check, before any outcome was read. The diagnosis then was that pre-deal SPACs rarely have
options and most later delist, so they widen the gap without signalling a survivorship hole.
Gabe chose amendment (b). It was hash-frozen and committed before the gate was recomputed and
before the read.

**Store facts:**
- 80 of 80 dates pulled; 254,463 name-dates.
- L1 extended 3,928 crosswalk rows.
- L2 linked 1,192 name-dates, 97 of them `ok`.
- 99.99% of `ok` chains are within 5% on close.
- Data is in `final/data/wrds/optionm/oos2019/` (parquet; WO-52's store untouched).

## Trial tally and next step

- Options family: **23 (29 including WO-36).**
- Per the WO, Phase 3 (a down-cap long-book test) is only a **DRAFT**:
  `final/models/2026-10-09-cwspread-downcap-book-prereg-DRAFT.md`. Nothing was computed for it.
  The COO and Gabe decide whether to launch it.
- Dead ends stay dead: cw_spread in the cap150 long book (WO-36), CSP, long calls, LEAPS.

## Files

- Code: `final/src/cwspread_oos/{oos_paths,pull_oos,build_store_oos,run_oos}.py`
- Outputs: `final/out/cwspread_oos/{wo55_read_results,gate_summary,arrival_gate,store_build_report}.json`
