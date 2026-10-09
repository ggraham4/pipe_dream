# WO-55 results: opt_cw_spread avoid-screen, out-of-era read on OptionMetrics (2019-01..2025-08)

Date: 2026-10-09. Branch `wo55-cwspread-outofera`.
- **Pre-reg:** `final/models/2026-10-09-cwspread-outofera-prereg.md`, sha256 72b06653…c7cc. It
  was frozen at 2026-10-09T16:03:46Z and committed and pushed in 728740d before any 2019+
  outcome was computed.

## Verdict: BLOCKED (a pre-registered presence check failed). The read did not run.

| Check (pre-reg §3; all block) | Value | Bar | Pass |
|---|---|---|---|
| Coverage gate, repaired chain (L1+L2), binding | **80 of 80** dates ≥ 99% terminal (min 99.95%, median 100%) | ≥ 72 of 80 (90%) | yes |
| Coverage gate, frozen WO-52 chain (descriptive) | 61 of 80 | (would be BLOCKED) | — |
| BBBYQ (must-date 2022-08-17) | present; kept chain on 32 of 32 thin dates | must-date + ≥ 90% | yes |
| RADCQ (must-date 2022-06-15) | present; 50 of 50 | must-date + ≥ 90% | yes |
| TXG | chain on 58 of 58 cap2000 dates and 11 of 11 thin dates | all | yes |
| Pool integrity | 111,808 thin name-dates with a kept chain; 100% in the panel and 100% in the outcome cache | ≥ 99% | yes |
| **Dead vs listed chain share** | **later-delisted 79.53% vs still-listed 85.34%: gap 5.81 points** | gap ≤ 5 points | **NO** |

`phase2_allowed` = false. The WO-37 guard therefore refuses `run_oos.py read`, and under the
frozen pre-reg the order stops. No rule was changed.

**Not computed:** M, NW39 t, offsets, null-seed sd, LOYO, median spread, and the cap2000
comparison. No `gross_return_40` value from 2019 on was read; pool integrity read only the
(ticker, date) presence of the outcome cache.

**Hold-out read #22: logged, NOT consumed.** COO.md and LEDGER.md are updated to say so.

Trial tally: no real-label number exists, so no trial is spent. Options stay at 22, or 28
including WO-36. The WO-55 trial is spent only if the read runs.

Fix cycles used: 0 of 3. Phase 3 draft: not written, because it is written only on a PASS.

## Store facts (quotes and presence only; `final/out/cwspread_oos/store_build_report.json`)

- **Pull:** 80 of 80 dates, 0.63M to 1.07M contract rows per date (3,520 to 3,810 secids). That
  is 677 s of wall time. `secprd` has 751,816 rows. Data is in
  `final/data/wrds/optionm/oos2019/`, parquet only. WO-52's 2008-2018 store was not touched.
- **Name-dates:** 254,463 (thin plus cap2000). Under the frozen WO-52 chain 9.79% are
  unlinked; after the repair the share is 0.0004%.
  - **L1:** extended 3,928 crosswalk rows that had been censored at 2024-12-31.
  - **L2:** the CUSIP fallback linked 1,192 name-dates. 97 of them are `ok`, and 98.97% of those
    `ok` chains are within 5% on close; the rest are `no_data`.
- Of the `ok` chains, 99.99% have the OptionMetrics close within 5% of Sharadar's.

## Post-hoc diagnosis (DESCRIPTIVE, computed after the check failed, NOT a fix)

The repair and the check interact:
- Under the frozen chain, the 2020-08 to 2021-12 dates (the SPAC wave) never became
  thin-complete, so the check never saw them.
- L2 made those dates complete, and that pulled the delisted SPACs into the check.

**Thin `ok` share by delisting status and year (presence only):**

| Year | still-listed | later-delisted |
|---|---|---|
| 2019 | 81.9% | 80.2% |
| 2020 | 81.6% | 77.8% |
| 2021 | 78.2% | 70.0% |
| 2022 | 87.5% | 80.9% |
| 2023 | 90.8% | 87.9% |
| 2024 | 89.2% | 91.0% |
| 2025 | 87.0% | 91.3% |

**Split by a SPAC flag, defined AFTER the fail.** The flag is a name regex
(ACQUISITION / CAPITAL CORP / HOLDINGS CORP I / MERGER, or `sicindustry == 'Shell Companies'`,
which matches 0 rows in Sharadar):

| | still-listed | later-delisted |
|---|---|---|
| non-SPAC | 85.41% (n 96,024) | 82.09% (n 35,025) |
| SPAC | 77.12% (n 730) | 28.51% (n 1,754) |

- Without SPACs the gap is 3.3 points, which would be inside the bar.
- **Reading:** this is not a survivorship hole in OptionMetrics. Pre-deal SPACs rarely have
  listed options, and most of them later delist (they liquidate or merge). The regex was chosen
  after seeing the fail, so it is **not** adopted.

## Proposed amendment (NOT applied; the COO or Gabe decide)

Either option would be hash-frozen before the read. The read would stay hold-out #22, unfitted,
with every other constant unchanged.

- **(a)** The dead-vs-listed check becomes descriptive for this window. Survivorship is still
  covered by the named dead names (BBBYQ and RADCQ, both 100%) and by pool integrity.
- **(b)** Blank-check and shell companies are excluded from this check only, using a vendor
  field fixed in advance. Sharadar has no `Shell Companies` industry value, so the candidate is
  SIC 6770 (blank checks) from Sharadar `siccode`. Its effect on the gap would be measured once
  the field is frozen. This restricts the check, not the thin slice, which stays a frozen
  constant.

The trade-off: (a) is simpler but drops a survivorship guard for 2019-2025. (b) keeps the guard
but needs a vendor classifier frozen before anyone looks at its effect.

## Files

- Code: `final/src/cwspread_oos/{oos_paths,pull_oos,build_store_oos,run_oos}.py`
- Outputs: `final/out/cwspread_oos/{gate_summary,arrival_gate,store_build_report}.json`
