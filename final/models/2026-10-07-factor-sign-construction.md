# WO-48: factor sign vs decile_volq construction check

2026-10-07. COO work order WO-48. Code: `final/src/signcheck/signcheck.py`.
Outputs: `final/out/signcheck/`. In-era 2007-01-02..2019-12-31 only, no
hold-out read, no live deploy, no weight change. Nothing here is promoted by
this order; a FLAG is a weight question for Gabe, whose call methodology is.

## 1. Pre-registration (committed and pushed before any outcome is computed)

**Question.** WO-46 (integration e1f598d, `state_interactions_report.json`)
found that for 3 live icw9_seas factors the pooled decile_volq long-short
payoff has the opposite sign to the factor's signed IC:
`pct_from_high_252` (LS −1.35 %/yr, signed IC t +2.09), `volatility_60`
(LS −2.80, +2.90), `days_to_next_filing_seasonal` (LS −1.68, +4.28). All
three sit at the floor weight |w| = 0.0105 (about 1% of the 0.9901 total
|w|). Does this disagreement matter to the live book?

**Harness (reused, imported read-only).** WO-46 `stateint.load_all` path:
`model_audit_wo23.load_theo("A", "cap150")` (v2 grid column c, cap150,
label `gross_return_40` = close[t+40]/open[t+1] from `outcome_cache_v2`,
the last 2019 windows ending in early 2020 unmasked per Gabe's WO-13
ruling), `screen_insider.rank_z` / `composite_score` (coverage-aware
weighted mean of signed rank_z), `pool_read.picks_w` (decile_volq picks),
`drag_decomp.chains` / `per_offset` / `loyo_vec`, `trailfilter.diff_stats`,
15 bp turnover cost, 40 grid offsets, excess vs SPY.

**Step 0: base reconcile (gate before anything else).** The base book is
icw9_seas with `ICW.PRODUCTION_WEIGHTS_V9_SEAS`. Its 40-offset mean excess
vs SPY must equal the published in-era number +0.0348652 (WO-31/WO-46) to
≤ 1e-6 and the WO-31 exact value to < 1e-10, or the run stops.

**Trials.** 3 related trials, one per factor k in
{`pct_from_high_252`, `volatility_60`, `days_to_next_filing_seasonal`}.

**Test 1: decile monotonicity (descriptive, explains the disagreement).**
Per factor, 2007-2019:

- Within date, decile the raw factor (ordinal, `pd.qcut` on rank, 10 equal
  groups, names with a finite value and a finite label). Label = 40-day
  `gross_return_40` minus its date cross-sectional mean (date-demeaned
  excess). Report mean demeaned return per decile (pooled over dates, each
  date weighted equally), Spearman of decile number (1..10) vs decile mean,
  and the pooled daily rank IC (`screen_insider.daily_corr`, NW(39) t).
  Signs are reported both raw and in the book's direction (sign of w).
- Same decile table computed within each `volatility_60` quintile and then
  averaged across quintiles (the decile_volq bucketing), and the equal- vs
  inverse-vol-weighted top-minus-bottom decile. This separates "the factor's
  ranking is non-monotone" from "the construction (vol bucketing,
  inverse-vol weights, top decile only) is what reverses it".
- Where the disagreement comes from: tails (D1, D10) vs middle (D2..D9
  slope), and per calendar year: IC, D10−D1, and the decile_volq LS payoff
  per year (WO-46 definition, `stateint.ls_chain`).

**Test 2: leave-one-out (LOO) book.** icw9_seas with w_k = 0 and the other
eight weights renormalised proportionally to the same total |w| (no refit;
`composite_score` divides by the covered |w| so the renormalisation does not
change ranks). Statistic D_LOO = LOO book − base book, %/yr net excess vs
SPY. Reported: 40-offset mean, offsets with D > 0 (of 40), sd40 of D,
LOYO min (min over dropped years of the 40-offset mean of D with that year
dropped, `diff_stats`), max single-year share (sum of per-window D with
rebalance date in year y ÷ total sum of per-window D over all offsets; a
zero or negative total fails the share rule), per-year D.

**Test 3: sign-flip control.** Same book with w_k replaced by −w_k (same
|weight|, all other weights unchanged). Same statistics as Test 2
(D_FLIP = flip − base). Reported, no gate.

**Null.** 100 draws, seeds 0..99 (factor k uses seeds 1000·j + s, j = 0, 1,
2 in the order listed above): factor k's column is permuted within date
among names with a finite value (`screen_insider_v2grid.shuffle_within_date`
applied to the raw column; rank_z of a permuted column equals the permuted
rank_z, which is what is used), kept at its live weight w_k; D_null = shuffled
book − base. **null p80 = 80th percentile of D_null** (40-offset means).

**Outcome rule (fixed in advance).** Factor k is **FLAGGED** for Gabe only if
all of:

1. D_LOO > max(sd40 of the base book's 40 per-offset excess numbers
   (ddof = 0), null p80);
2. D_LOO > 0 on ≥ 30 of 40 offsets;
3. LOYO min of D_LOO > 0;
4. max single-year share ≤ 0.45.

Otherwise **CLOSED**: the sign disagreement is a construction curiosity, no
action. A FLAG does not change weights; it is a question for Gabe.

**Multiple testing.** 3 trials. Any t reported for D_LOO or D_FLIP is a
year-block jackknife t (13 leave-one-year-out 40-offset means; SE_jk =
sqrt((Y−1)/Y · Σ(loyo_y − mean loyo)²)), two-sided normal p, Holm-adjusted
across the 3 factors. t's are descriptive; they are not in the outcome rule.

**Descriptive sub-window.** 2011-10-01..2019-12-31: the same D_LOO and
D_FLIP 40-offset means and offsets-positive, computed from the full-era
chains restricted to windows with rebalance date ≥ 2011-10-01 (the window of
the icw8 ≈ +0.00 %/yr vs SPY construction number). No gate.

**Expectation, stated now.** Each factor has ~1% of the weight, so LOO and
flip books will differ from base in only a few names per date; |D| is
expected to be small relative to base sd40 (≈ 0.5 pp), and CLOSED is the
likely outcome for all three. The work is to explain the sign disagreement
and confirm it is immaterial, or to show it is not.

**Checks before trusting a number.** Base reconcile (Step 0); LOO/flip books
built through the same `picks_w` path as base; hold-out assert on universe,
dates and SPY (< 2020-01-01); null draw 0 of each factor re-run gives the
identical number; D for the identity book (w unchanged) = 0 exactly.

## 2. Results (computed 2026-10-07, after the pre-registration above was pushed as 5d3f5e3)

Report: `final/out/signcheck/signcheck_report.json`; logs in
`final/out/signcheck/logs/`. Units: %/yr net excess vs SPY unless noted.

**Verdict: all three CLOSED.** The sign disagreement is a construction
curiosity. It does not touch the live book in any material way, so there is no weight question for Gabe.

**Checks.** All of these passed:
- Base reconcile: +0.0348652 equals the WO-31 exact value (diff 0.0, and 5.8e-10 vs the spec).
- icw8 reconcile: exact.
- Numpy score equals `composite_score` (< 1e-15).
- The fast picker matches `picks_w` on every date.
- The identity book gives D = 0 exactly.
- The hold-out assert passed.
- WO-46 pooled LS payoffs reproduced to < 1e-10.
- Null draw 0 of each factor, re-run, gives the identical number.

### Gate (Test 2: leave-one-out book, pre-registered rule)

| factor | w | D_LOO | offsets > 0 | LOYO min | max yr share | null p80 | bar | verdict |
|---|---|---|---|---|---|---|---|---|
| pct_from_high_252 | +0.0105 | +0.014 | 25/40 | −0.044 | 4.0 (2009) | +0.011 | 0.223 | CLOSED |
| volatility_60 | −0.0105 | −0.035 | 13/40 | −0.076 | n/a (total ≤ 0) | +0.051 | 0.223 | CLOSED |
| days_to_next_filing_seasonal | −0.0105 | +0.033 | 24/40 | −0.006 | 1.18 (2018) | +0.078 | 0.223 | CLOSED |

The bar is base sd40 = 0.223 pp/yr. That is 7 to 16 times every |D_LOO|, so all four
conditions fail for every factor. Jackknife t's are 0.18, −0.43 and 0.57,
and each Holm p = 1.0. This matches the stated expectation: at about 1% of total
|w|, each factor changes only a handful of picks.

### Sign-flip control (Test 3, no gate)

| factor | D_FLIP | offsets > 0 | LOYO min | jk t (Holm p) | null pct | 2011-10+ D_FLIP |
|---|---|---|---|---|---|---|
| pct_from_high_252 | +0.012 | 21/40 | −0.115 | 0.08 (1.0) | 84 | −0.055 |
| volatility_60 | +0.067 | 29/40 | +0.006 | 0.62 (1.0) | 97 | −0.013 |
| days_to_next_filing_seasonal | +0.167 | 34/40 | +0.098 | 1.53 (0.38) | 100 | +0.103 |

Flipping `days_to_next_filing_seasonal` is the largest effect in the
order: +0.17 pp/yr, 34/40 offsets, every LOYO positive, above all 100
null draws. It is descriptive only: no gate was pre-registered for it, and the LOO gate
applied to it would fail anyway, on condition 1 (0.167 < 0.223) and on
condition 4 (max year share 0.457 > 0.45). Its year-block t is 1.53 (Holm
0.38). It is not a finding, and nothing changes.

**Null shape.** For `volatility_60` and `days_to_next_filing_seasonal`,
the shuffled-column null is centred above zero (means +0.035 and +0.066).
Replacing either factor with noise at the same weight slightly beats the
base, and dropping it is worse than noise (D_LOO sits at null percentile 0 and 1).
The effect is tiny either way. One untested reading: a floor-weight factor
mostly acts as a small tie-breaker, and noise of the same size may add a
little diversification inside the top decile. This is not a weight question;
under the pre-registration only a FLAG raises one.

### Why the signs disagree (Test 1, descriptive)

Decile tables are 40-day date-demeaned returns (%), D1 (low) to D10 (high),
raw factor direction.

- **pct_from_high_252** (book long high):
  - Deciles: −0.34, −0.03, −0.08, +0.04, +0.07, +0.05, +0.05, +0.04, +0.17, +0.03.
  - Where the IC comes from: almost all of it is the D1 tail, names far below their high doing badly. D10 is flat, and D9 is best.
  - Effect of weighting: book-direction top-minus-bottom is +0.36 equal-weight but only +0.04 inverse-vol-weight. The inverse-vol weights remove most of the spread.
  - Where the negative LS comes from: one year. 2009 is −70 %/yr (the junk rally); 9 of 13 years are positive.
- **volatility_60** (book long low vol):
  - Deciles: −0.05, +0.09, −0.01, +0.11, +0.10, +0.09, +0.15, +0.06, −0.06, −0.48.
  - Shape: hump-shaped. The IC is the D10 (highest-vol) crash tail. The lowest-vol decile is not the best.
  - Within volatility quintiles, D10−D1 runs from +0.46 in the lowest quintile to −0.46 in the highest. Bucketing by vol and then ranking by vol again leaves mostly the reversed part.
  - LS is negative on 0/40 offsets, but it is concentrated in 2009, 2010, 2013 and 2016.
- **days_to_next_filing_seasonal** (book long few days to filing):
  - Deciles: −0.11, +0.30, +0.18, +0.08, +0.05, −0.02, −0.02, −0.13, −0.24, −0.09.
  - Where the IC comes from: the middle. The D2..D9 Spearman is −0.98, but both tails fold back. D1, the names filing soonest, is negative, while D2 is the best decile.
  - The book's top decile is exactly that folded tail, so book-direction top-minus-bottom is −0.05 (equal) / −0.01 (inverse-vol).
  - The LS is small and steady: −1.7 %/yr, negative in 10 of 13 years.

So the reversal comes from the construction: decile_volq trades only the extreme decile, inside vol buckets, with inverse-vol weights. The factors' rankings are real but non-monotone at the
tails, and the long-short takes the tail that reverses. The signed IC uses the whole ranking, and it is not wrong.

### Deviations from the pre-registration (none touch the outcome rule)

- Deciles use `floor((rank−1)·10/n)+1` on the ordinal rank, not `pd.qcut`. It is the same equal-count split; Test 1 is descriptive.
- The first `--real` run crashed on `volatility_60` because selecting the column list duplicated the factor column (`logs/real_crash1.log`). I fixed the column selection and re-ran everything from scratch. the `pct_from_high_252` LOO and flip log lines were identical in both runs (the first run's Test 1 output was overwritten, not compared).
- The pre-registered "null draw 0 re-run identical" check was missing from the pushed code. I added it as `--recheck`, writing `parts/null_recheck.json`, and ran it after the nulls.
- Max-year-share is > 1 when the per-window D total is small and mixed in sign. That condition fails either way.

### Docs for README

This doc. WO-48 CLOSED all three factors; no action.
