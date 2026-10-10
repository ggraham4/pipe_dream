# WO-58 results: `opt_cw_spread` avoid screen in a thin-slice long book

Pre-registration: `final/models/2026-10-10-cwspread-downcap-book.md`
- commit 595432e, pushed before any outcome statistic;
- sha256 `0f4d5fb63e9d53ba719cbb37eb0b901cc71b6ba8e8d1066d667d6ac0e57c92a3`;
- copy and sha in `~/.claude/pipe_dream-coordination/wrds-frozen-2026-10-10/`, frozen 2026-10-10T21:42:31Z.

Code: `final/src/cwbook/`. Outputs: `final/out/cwbook/*.json`. Iterations used: **0 of 3**. Trial count:
options **25 (31 incl. WO-36)**.

All figures are % per year, net of 15 bp, minus SPY, mean of the 2 interleaved monthly-date offsets,
unless marked otherwise.

## Reproductions (run after the commit, before any real-label book number)

`reproduce.json`. Both pass with error 0.0.
- **WO-52 thin M:** 2.7394 %/40d on 133 dates, the same as the stored figure.
- **WO-36 base excess_ann:** 0.053650011496056194, identical to the full precision of
  `stage1_nominate.json`.

## Stage 1: 2008-01-02 to 2018-12-19, 133 dates, in era

`stage1_result.json`. Step 0 (label-free, from the pre-reg): the base holds 5.40% of its weight in the
bottom decile, so the implied max Δ is 0.92 %/yr. The test was informative.

| | base (icw5_seas, thin) | variant (screen) | Δ |
|---|---|---|---|
| net vs SPY | 8.06 | 8.56 | **+0.504** |
| offset 1 / 2 | 7.26 / 8.85 | 7.85 / 9.28 | **+0.585 / +0.423** |
| gross vs SPY | 8.51 | 9.03 | +0.524 |
| turnover f_new | 0.463 | 0.483 | |
| median names held | 175 | 160 | |

**Null and criteria:**
- **Null:** 100 draws of paired random removal (median 134 names per date, drawn from names with a
  kept chain). p50 **−0.153**, p80 **+0.038**. 1 of 100 draws reached the real Δ, an empirical p of
  about 0.01.
- **LOYO:** min **+0.385** (2015 dropped). The range is +0.385 to +0.664.
- **Max single-year share:** **30.6%** (2015). 2009 contributed −20% and 2008 −0.4%.
- **Δ by year (descriptive):** 2008 −0.02, 2009 −1.12, 2010 +0.99, 2011 +0.92, 2012 +1.36,
  2013 +0.03, 2014 +0.92, 2015 +1.71, 2016 +0.53, 2017 +0.09, 2018 +0.17.
- **Halves (descriptive):** odd years +0.33, even years +0.65.

**Verdict Stage 1: PASS.** All five criteria hold:
- Δ > 0;
- Δ > p80;
- both offsets > 0;
- LOYO min > 0;
- max share ≤ 45%.

No kill fired.

**Descriptive:**
- **50 bp stress:** base 7.01, variant 7.47, Δ +0.458 (offsets +0.539 / +0.376).
- **Equal-weight pool:** the no-score thin-slice equal-weight pool is +2.69 vs SPY gross. The base
  beats it by +5.82 gross and the variant by +6.34.
- **Capacity:** at a $100k book the mean position is $565 (base) and $610 (variant). The held names'
  median 20-day dollar volume is $3.9M. Position / dollar volume averages 0.031% (p95 0.12%), so
  capacity is not a constraint at this size.
- **Variant book size:** the variant holds fewer names (160 against 175). It picks 10% per volatility
  quintile of a pool about 134 names smaller. That is the pre-registered construction.

## Stage 2: hold-out read #23

HOLD-OUT READ #23 LOGGED

- **Logged:** 2026-10-10, before the run.
- **What is read:** `outcome_cache_v2.gross_return_40` and SPY on the 80 WO-55 option dates, 2019-01-16
  to 2025-08-20. The run covers thin-slice names only: base and variant icw5_seas books and the
  100-draw paired-removal null (seeds 20271010+k).
- **Unfitted:** the weights, screen, construction, costs and bars are all frozen from the pre-reg and
  Stage 1. Nothing is chosen on 2019+.
- **One run.** Only crash fixes are allowed, and each one is logged here.
- **Before the read (label-free):** the Stage-2 load gave 80 dates. The book pool is 98.2% of thin
  name-dates; the blank-check exclusion is larger in 2020-21. seas coverage is 69%. The base's weight in
  the bottom decile is 6.5%.
- **Caveats (from the pre-reg):**
  - WO-55 already read the cw screen on this window (hold-out read #22). So Stage 2 tests whether the
    pool effect carries into the book. It is not an independent confirmation of the screen.
  - icw5_seas was chosen after hold-out read #21, so the base book is in-sample for 2020+.

### Stage 2 result (one run, no crash fixes; `stage2_result.json`)

80 dates, 40 per offset.

| | base | variant | Δ |
|---|---|---|---|
| net vs SPY | −4.74 | −4.04 | **+0.697** |
| offset 1 / 2 | −4.75 / −4.72 | −4.40 / −3.67 | **+0.346 / +1.047** |
| gross vs SPY | −4.27 | −3.55 | +0.720 |
| turnover f_new | 0.478 | 0.501 | |
| median names held | 160 | 145 | |

**Null and robustness:**
- **Null:** p50 **+0.056**, p80 **+0.324**. 4 of 100 draws reached the real Δ.
- **ex-2019:** **+0.603**.
- **ex-2020:** **+0.981**.
- **LOYO:** min +0.535 (2023 dropped).
- **Max year share:** 34.8% (2023).
- **Δ by year (descriptive):** 2019 +1.23, 2020 −0.91, 2021 +0.49, 2022 −0.03, 2023 +1.62,
  2024 +1.39, 2025 (to 08) +1.31.
- **Halves (descriptive):** odd years +1.15, even years +0.15. Offset 1 carries less than offset 2.

**Verdict Stage 2: PASS.** Δ > 0, Δ > p80, and both offsets > 0.

**Descriptive:**
- **50 bp stress:** Δ +0.643 (offsets +0.287 / +0.998).
- **Equal-weight pool:** the no-score thin-slice equal-weight pool is −6.36 vs SPY gross. The base
  beats it by +2.09 and the variant by +2.81, but both books trail SPY on this window.
- **Capacity:** mean position $623 against a median dollar volume of $4.3M; position / dollar volume
  averages 0.035%.

## Overall

**PASS at both stages. PROMOTE-CANDIDATE recommendation only.** Promotion, or any live change, is
Gabe's decision.

**What the result says:**
- In a thin-slice icw5_seas book, removing the bottom `opt_cw_spread` decile before ranking added:
  - **+0.50 %/yr in era** (null p80 +0.04);
  - **+0.70 %/yr on 2019-2025** (null p80 +0.32).
- Both stages are net of 15 bp, and the gain survives 50 bp.

**Caveats:**
- **The thin book itself is not a live book.** It is −4.7 %/yr vs SPY on 2019-2025, although it was
  +8.1 in era. Any use of this screen needs a decision about the down-cap book itself, which is a
  separate question for Gabe and the COO.
- **Stage 2 is not independent of WO-55.** The pool effect on the same window was already read
  (#22), and the icw5_seas base is in-sample for 2020+.
- **Gains are uneven by year.** 2020 (−0.91) and 2009 (−1.12) are negative years for Δ.
- **This is a stock-side test only.** It uses no down-cap cost model.

**Hold-out read #23: used** (2026-10-10, unfitted, once).

## Checks run

- `check_score.json`: the icw5_seas fast score equals `compute_composite_ic_weighted` exactly (error 0.0)
  on all 133 dates, on both the full and the screened pool.
- In-run assert: the cost-parameterised `evaluate` equals `cw_core.evaluate` at 15 bp to 1e-12, for
  base and variant, in both stages.
- `reproduce.json`: WO-52 M and the WO-36 base are both exact.
- Shuffled-label smoke run before the freeze: `smoke_SHUFFLED_TEST_labels-shuffled.json` (KILL, as
  expected).
- The runner asserts the pre-reg sha256 and that it is tracked in git, refuses to overwrite a stage
  result, and refuses Stage 2 unless Stage 1 = PASS and this log line exists.
