# Overnight vs intraday return decomposition (`io_gap`), v2 grid, nomination era

Date: 2026-09-29. Requested by Gabe ("Lets proceed with it since its cheap").
Branch `worktree-overnight-intraday`, based on `integration` 0dd6908.
Code: `final/src/overnight/`. Outputs: `final/out/overnight/`.

Status: **PRE-REGISTERED.** This part was committed before any IC or portfolio
number for `io_gap` was computed. Results are appended below the line at the end.

## Motivation and mechanism

Gabe's prompt: an analysis showing MU's gains came almost entirely during
trading hours (open → close), not overnight (close → open). Does a stock's
split between intraday and overnight returns predict its future return?

Literature:
- Cliff, Cooper & Gulen (2008). The US equity premium since the 1990s was
  earned mostly overnight. Intraday returns were close to zero.
- Berkman, Koch, Tuttle & Zhang (2012, JFQA). Retail attention pushes up the
  open, and that move reverses during the day.
- Aboody, Even-Tov, Lehavy & Trueman (2018, JFQA). High overnight returns
  measure firm-specific investor sentiment. They predict short-run
  continuation, then a longer-run reversal.
- Lou, Polk & Skouras (2019, JFE), "A tug of war". Each of the overnight and
  intraday legs persists within a stock for years. The overnight clientele is
  individual investors; the intraday clientele is institutions. Most
  anomalies other than momentum pay off intraday.
- Akbas, Boehmer, Jiang & Koch (2022, JFE), and Bogousslavsky (2021, JFE).
  Mispricing is corrected intraday.

**Registered mechanism.** Stocks that institutions accumulate during the day,
while overnight sentiment demand stays muted, are underpriced. Stocks whose
gains come overnight are sentiment-overpriced and later reverse. So a high
`io_gap` (intraday minus overnight) predicts higher forward returns. **Sign +1.**

The literature does not agree on the sign of the net effect on total returns
(the two legs partly offset each other). This is a one-sided test: a negative
t is a KILL, and the flipped sign is **not** run, because that would be a
second trial.

An argument that "the strategy buys at the open, so it captures intraday
gains" is **not** part of the mechanism. The label runs from open[t+1] to
close[t+40], so it excludes only 1 of 40 overnight legs.

**Prior trials.** None. A grep of `final/src`, the model docs and the
XGBoost-era `FEATURE_COLS` found no overnight, gap or intraday feature ever
screened or admitted. The hits in `features.py:109` and `sweep/gridspec.py:98`
are comments about label inflation from close-to-close labels, not a feature.
So this is a **NEW family, "overnight/intraday decomposition", trial 1, k = 1.**

## Definition (frozen)

Prices come from Sharadar SEP `data/sharadar/panel/stocks/2005-01..2019-12`.
SEP `open/high/low/close` are split-adjusted, and `closeadj` is split- and
dividend-adjusted.

For ticker i on trading day d, where prev is i's previous SEP row:

- `r_id(d) = log(close_d / open_d)` is the intraday return.
- `r_on(d) = log(closeadj_d / closeadj_prev) − r_id(d)` is the overnight
  return. It is net of dividends and splits, because the same-day ratio
  close/open has no basis issue.

Day d is **VALID** only if all of the following hold:
- open, close, closeadj and closeadj_prev are finite and > 0;
- volume > 0;
- low·(1−1e-6) ≤ open ≤ high·(1+1e-6);
- the prev row is at most 7 calendar days before d;
- |r_id| ≤ 0.7 and |r_on| ≤ 0.7 (bad-print guard).

`io_gap(i, t) = 252 × mean over VALID days in W of (r_id − r_on)`

- W is the 252 market trading days ending at t, inclusive. The market
  calendar is the set of SEP dates with at least 1,000 tickers.
- `io_gap` is NaN when W has fewer than 200 VALID days.
- There are no lookback, skip-month or weighting variants.
- PIT: every price is dated ≤ t, asserted row by row. close_t is known before
  the label's entry at open[t+1].

The 2007-01 dates need prices from 2005-12-30 onward, so no pre-2005 pull is
needed.

**Days where the open equals the prior close (kept, frozen before any IC).**
These are 15.5% of added-ticker days and 6.4% of old-grid days (SEP
2006–2019). The rate falls with dollar volume, from 24% in the lowest decile
to 3% in the highest.

They could be stale placeholder opens. If so, the whole daily return would
land in `r_id`, and |r_id| would be inflated on those days. It is not: on
lowest-decile days, |r_id| is 0.0194 on equal-open days vs 0.0263 on other
days (2015 H1 check). They look like real flat opens, for example
opening-auction prints at the prior close. So they stay VALID. As a
descriptive robustness check, `io_gap_noeq` drops them; its rank correlation
with `io_gap` is 0.985.

## Screen (frozen; identical stack to WO-13 and WO-18)

- **Grid.** v2 column c, cap150, h = 40, label `forward_return_tradable_40`
  (close[t+40]/open[t+1]), nomination era 2007–2019, SPAC rule applied via
  `downcap_v2_readout.load_column("c")`.
- **Reconcile first.** The harness icw8 decile_volq net 15bp over 40 offsets
  must reproduce readout.json cap150 (+0.0285416) to 1e-6, and both
  split-half OOS ICs must match, before any `io_gap` number. This is a hard
  assert.
- **Bar.** k = 1: pooled NW(39) IC t ≥ +1.96, sign +1.
- **PASS requires ALL of:**
  1. NW(39) t ≥ +1.96;
  2. both halves (odd and even years) positive;
  3. both-sides sector-demeaned t ≥ +1.0;
  4. 0/40 grid-offset sign flips;
  5. max single-year share of the summed daily IC ≤ 0.45;
  6. icw9 vs icw8, decile_volq net 15bp, split-half OOS, above the 80th
     percentile of a 20-draw within-date shuffle null (seeds 0..19);
  7. the frozen weight rule `w_k = s_k·max(0.1, |t_k|−1)/Σ` reproduces
     `PRODUCTION_WEIGHTS` to 4dp.
- **PASS = nomination only.** A PASS goes to the COO and Gabe for a forward
  column; there is no in-era promotion. **KILL = any gate fails**, and the COO
  certifies the family dead.
- **Descriptive only, never gated, not trials:**
  - coverage;
  - median cross-sectional Spearman of `io_gap` with icw8 (frozen weights),
    momentum_12_1, volatility_60, amihud_20, and each leg;
  - NW IC of each leg on its own (`io_intraday`, `io_overnight`) and of
    `io_gap_noeq`;
  - the descriptive full-era icw9 weight.

  The per-leg ICs explain which leg drives the result. They cannot rescue a
  KILL, and a strong leg would need its own pre-registered trial.
- **Hold-out.** Rebalance dates 2007-01-02..2019-12-31 only, asserted. SEP
  files after 2019-12 are never opened, asserted per file. Late-2019 labels
  that run into 2020 are kept unmasked, as in WO-13 and WO-18.
- **Iteration cap 3**, for bug fixes only, never for definition changes.

## Implementation

- `build_io_gap.py`: factor, legs and flag tables →
  `io_gap_factor_v2.parquet` (gitignored) and `build_io_gap_meta.json`.
  The window is computed with per-ticker cumulative sums indexed on the
  market calendar.
- `hand_check_io_gap.py`: an independent recompute from the raw SEP month
  files, with a row-by-row loop and no import of the builder.
- `screen_io_gap.py`: a copy of `seasonality/screen_seas.py`, with
  `COL = "io_gap"` and the harness `OUT_JSON` pointed at this worktree.
  `mapping_agreement` (seas-only) is removed, and the descriptive block adds
  amihud_20 and the legs.
- Python: `/opt/anaconda3/envs/pipe_dream/bin/python`.

**Input hashes** (recorded in `build_io_gap_meta.json` and re-checked at
screen start):
- `composite_panel_v2.parquet` sha256
  `30f636fd4802b4f13278322bc0c6e766a4623853edf15e92b60c2b672e97e0ff`. This
  is newer than WO-18's `796eb808…` because of the weekly refresh. The
  reconcile below still reproduces readout.json exactly on the same 9,756,141
  rows.
- SEP 2005-01..2019-12 digest
  `83e7b89085665b0722d1be1bd41b6f37defb2b285b79777adb3892e15f36ab44`,
  identical to WO-18's.

## Data validation (run before this commit; no IC computed)

**Harness reconciliation: PASS (hard assert).**

| check | harness | readout.json |
|---|---|---|
| icw8 decile_volq net 15bp, mean of 40 offsets | +0.028541633 | +0.028541633 |
| split-half OOS IC, fit odd → test even | 0.0404111057 | 0.0404111057 |
| split-half OOS IC, fit even → test odd | 0.0553979834 | 0.0553979834 |

**Gate 7: PASS.** The frozen rule reproduces all 8 `PRODUCTION_WEIGHTS` to 4dp.

**Universe.** Column c cap150, 2007–2019: 9,756,141 rows, 6,508 tickers and
2,987,605 added-ticker rows. These match WO-13 and WO-18. All panel tickers
have SEP rows.

**Day flags** (SEP ticker-days 2006–2019; `build_io_gap_meta.json` has the
by-year table):

| group | zero volume | open outside [low, high] | open or close ≤ 0 | no prev ≤ 7d | \|log\| > 0.7 | open = prev close | VALID |
|---|---|---|---|---|---|---|---|
| old grid | 0.29% | 0 | 0 | 0.02% | 0.01% | 6.4% | 99.69% |
| added | 2.90% | 0 | 0 | 0.02% | 0.04% | 15.5% | 97.03% |

The share of VALID days by year runs from 97.7% to 99.2%. The zero-volume
share falls from 2.2% in 2008–09 to 0.9% in 2017–19.

**Coverage of finite `io_gap`** among eligible cap150 column-c rows is
**96.5% overall**: 97.1% on the old grid and 95.1% on added tickers. It ranges
from 94.4% to 98.9% by year and is flat. The median number of VALID days is
252 (5th percentile 252).

**Distribution** (cap150 rows, annualized log):
- `io_gap` quantiles at 1%, 5%, 50%, 95% and 99% are −2.52, −1.21, −0.04,
  +0.75 and +1.31.
- Over all 13.25M panel rows, the median intraday leg is ≈ 0.00 and the
  median overnight leg is +0.068/yr. This matches Cliff-Cooper-Gulen, where
  the premium is earned overnight.

**Name checks: PASS.** `hand_check_io_gap.py` matches the build to 1e-9, with
252 VALID days each:
- MU, t = 2015-06-15: **io_gap = −0.3921234310**. Over that year MU's
  intraday leg lagged its overnight leg.
- RSHCQ (RadioShack, delisted 2015), t = 2012-06-15: **io_gap = −0.6302951167**.

PIT assert (last price used ≤ t) holds on all 12,424,924 finite panel rows.

---

## Results
