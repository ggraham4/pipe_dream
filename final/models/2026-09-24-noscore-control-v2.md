# WO-7: how much of the v2-grid composite excess is the ranking? (2026-09-24)

Work order WO-7 (COO). **Descriptive, not a new trial, and it has no kill.**
Script: `final/src/reset2026/noscore_control_v2.py`.
Output: `final/out/reset2026/downcap_v2/noscore_control.json`.

## Pre-registration (frozen 2026-09-24, before any result was computed)

### Question

On the survivorship-safe v2 down-cap grid (column `c` of
`downcap_v2_readout.py`), icw8 `decile_volq` earns about +2.8%/yr excess vs
SPY in the nomination era. That figure is net of 15bp, averaged over 40 offsets
(see `readout.json` and `2026-09-24-downcap-grid-rebuild.md`). How much of it
comes from the composite **ranking**, how much from **concentration and
construction**, and how much from simply **holding the eligible universe**
inverse-vol weighted?

### Data and era

- Column `c` from `downcap_v2_readout.load_column("c")`: the v2 grid with v2
  flags, the old tickers, and the added non-SPAC tickers. Column `a` (the old
  grid) is used only for the reconcile.
- 2007-01-02 to 2019-12-31. Every frame asserts `max(date) < 2020-01-01`.
  Nothing is evaluated on 2020 or later.
- Tiers: cap150 (primary), cap500 and cap2000.
- Cost: 15bp via `run_backtest.turnover_net_return`, using name-count `f_new`
  as in `downcap_v2_readout.backtest`.
- 40 grid offsets (`dates[off::40]`). Excess is annualised ×252/40, as in
  `backtest`.

### Books (per tier, per date, on that tier's eligible rows; minimum 20 rows)

1. **icw8**: `ic_weighted_composite.compute_composite_ic_weighted(elig)` with
   frozen PRODUCTION_WEIGHTS, then `composite.pick_decile_volq`. This is the
   same code path as `per_date_picks`.
2. **no-score**: `no_exclusion_control.pick_full_universe_volq(elig)`. Every
   eligible name with finite `volatility_60` is held, inverse-vol weighted, with
   no score input. The construction is imported, not re-implemented.
3. **null** (20 draws, seeds 0..19): the icw8 composite, **permuted within the
   date** and pushed through the same `pick_decile_volq`.
   - The permutation runs only among rows that `pick_decile_volq` treats as
     valid (finite `volatility_60` AND finite composite). NaN positions stay
     fixed, so the candidate set is identical to icw8 and only the ranking is
     random.
   - RNG: `np.random.default_rng([seed, date.toordinal(), tier_index])`. Each
     draw is therefore one book per date, independent of iteration order, and
     is reused across all 40 offsets.
   - The composite is computed per tier (rank_z runs within the tier's `elig`),
     so it is permuted per tier.

In every book, picks with NaN `gross_return_40` are dropped and the remaining
weights are renormalised, exactly as `per_date_picks` does. This is audited
below.

### Window alignment

For a paired difference, every book must cover the same rebalance dates in each
offset.
- icw8 and null need a finite composite.
- no-score needs only a finite vol.
- A date is skipped if any book's pick list is empty.

The script therefore takes the intersection of dates covered by all 22 books,
uses it for every book, and reports how many dates were dropped. If a date were
removed from the chain, the neighbouring window's `f_new` would change, so the
intersection is applied before costing.

**Known asymmetry, attributed to the concentration term.** The no-score book
admits names with finite vol but NaN composite, and the icw8/null books cannot.
That membership difference sits inside "concentration/construction".

### Statistics (all on PAIRED per-offset excess vectors)

`backtest_vectors()` copies the arithmetic of `downcap_v2_readout.backtest`
(imported; not edited) but returns:
- `per_off[40]`: annualised mean excess per offset;
- `loyo[off][year]`: the annualised mean excess of that offset with that year
  dropped.

It is asserted equal to `backtest()`'s summary (mean40, sd40, loyo_min and its
year) to 1e-12 on the icw8 book of every tier.

- **Null median per offset**: the elementwise median across the 20 draws of
  `per_off[draw, off]`. The null median LOYO is likewise the elementwise median
  across draws of `loyo[draw, off, year]`.
- **Gaps:**
  - selection[off] = icw8[off] − nullmed[off]
  - concentration[off] = nullmed[off] − noscore[off]
  - total[off] = icw8[off] − noscore[off]

  So selection + concentration = total exactly.
- For each gap, report:
  - mean over the 40 offsets;
  - sd across offsets;
  - count of offsets > 0;
  - LOYO: for each year y, mean over offsets of (A.loyo[off,y] − B.loyo[off,y]),
    then the min and max over years (with the year).
- **Percentile**: icw8's 40-offset mean against the 20 draws' 40-offset means.
  - Report the rank k/20.
  - Report null p50, p80 and p95 from `np.percentile` (linear interpolation).
    With 20 draws, p95 interpolates between the 19th and 20th order
    statistics.

### Benchmarks

Every book is reported vs SPY over the full era, 2007-01-02 to 2019-12-31. On
the **common window 2011-10-20 to 2019-12-31** it is reported vs SPY and vs
USMV, labelled as such. The two eras are never spliced together.

- USMV is `gross_return_40` for ticker USMV in `outcome_cache_v2.parquet`,
  filtered to 2019-12-31 or earlier and guarded.
- Common-window numbers are computed by costing the full chain and then masking
  windows whose benchmark is NaN. For vs-SPY, this means SPY is set to NaN
  before 2011-10-20.
- The script asserts that USMV has no NaN on any rebalance date from
  2011-10-20 on.

### Reconcile gates (hard stops)

1. The no-score book on column `a`, cap150, must reproduce +2.40%/yr
   (`2026-09-22-composite-model-corrections.md` §2a). Tolerance is 0.05pp. The
   expected match is much tighter, because the panel, date set and 20-name
   floor are the same.
2. icw8 on column `c` must reproduce `readout.json`: cap150 +2.854%/yr,
   cap500 +2.660%/yr, cap2000 +2.837%/yr, to 1e-6, together with sd40,
   loyo_min and offsets_positive.
3. `volatility_60` must be among the loaded columns.

If gate 1 fails, stop and diagnose before touching column `c`.

### Pool integrity

For each book and tier, count the picks dropped because `gross_return_40` is
NaN, and the **pre-renormalisation weight** they carried.
- Report the mean weight per date, the maximum, and the total over dates.
- Split drops into three categories: pick date is the ticker's last bar in the
  outcome cache; (ticker, date) is absent from the cache; other bad price.
- For each dropped name, check whether Sharadar `tickers_master.lastpricedate`
  falls within 60 calendar days of the pick date, which is roughly 40 trading
  days.

If the dropped weight exceeds 0.5% in any book and is concentrated in
delistings, it is reported prominently as a **survivorship leak**.

### Turnover caveat

`turnover_net_return` uses name-count `f_new`. For the all-universe inverse-vol
no-score book this understates weight turnover. The script reports the
no-score book's mean `f_new` next to a weight-based estimate,
0.5·Σ|w_t − w_{t−1}| on each offset's chain, with drift ignored and labelled as
an estimate. It also reports the net excess recomputed with that turnover as a
sensitivity. Headline numbers are unchanged by it.

### Frozen reading (cap150 primary)

- **SELECTION MATERIAL** if all of these hold:
  - icw8 − null-median ≥ 1.0pp/yr;
  - icw8 ≥ null p95;
  - the paired selection gap is > 0 in ≥ 36/40 offsets;
  - the LOYO min of the selection gap is > 0.
- **MOSTLY UNIVERSE BETA** if icw8 − no-score < 0.5pp/yr, OR icw8 < null p80.
- **MIDDLE** otherwise.

Both labels can trigger together, but only in one way: selection ≥ 1.0pp and
total < 0.5pp at once. That combination means a strongly negative
concentration term. If it happens, both labels are reported, the case is
named, and neither takes silent precedence. cap500 and cap2000 are reported descriptively under the same rule.
Only cap150 decides the verdict.

## Results (run 2026-09-24, 436s)

**Disclosure: two supplementary blocks were not pre-registered.** They were
added after the first run, which already gave these same headline numbers and
this verdict:
- `supp_vs_spy_full_gross_0bp` decomposes the returns at 0bp.
- `supp_vs_spy_full_dropped_as_minus100pct` is a worst-case bound on the
  NaN drops.

Both are descriptive only and never enter the frozen reading.

All numbers are nomination-era, 2007-01-02 to 2019-12-31. They are annualised
excess returns, net of 15bp, averaged over 40 offsets, unless labelled
otherwise. No date from 2020 or later was read into any frame.

### Reconcile gates: all passed

| gate | expected | got |
|---|---|---|
| 1. no-score, column a, cap150 | +2.40%/yr (§2a), sd 0.20, 40/40 | **+2.398%/yr**, sd 0.20, 40/40 |
| 1b. icw8, column a, cap150 vs readout.json | +5.254% | match to 1e-9 |
| 2. icw8, column c vs readout.json (mean, sd40, loyo_min, offsets+) | cap150 +2.854 / cap500 +2.660 / cap2000 +2.837 | match to 1e-6, all three tiers |
| oracle: `backtest_vectors` == `backtest` | | match to 1e-12 on icw8, every tier |
| window alignment | | 3,272 common dates; 0 dates removed from any of the 22 books |

### Headline: column c vs SPY, full era (the pre-registered basis)

| tier | icw8 | null median (20 draws) | null p80 / p95 | no-score | icw8 beats |
|---|---:|---:|---:|---:|---:|
| **cap150** | **+2.85** | −1.09 | −1.03 / −0.93 | **−0.25** (6/40 offsets > 0) | 20/20 |
| cap500 | +2.66 | −0.98 | −0.96 / −0.84 | −0.17 (9/40) | 20/20 |
| cap2000 | +2.84 | −1.28 | −1.17 / −1.11 | −0.41 (1/40) | 20/20 |

**The universe book has no excess on the survivorship-safe grid.** On the old
grid (column a) the same no-score construction earned +2.40%/yr. On column c
it earns −0.25%/yr. The v2 grid rebuild removed essentially all of the
"universe beta" that §2a found.

### Decomposition (paired per-offset gaps, pp/yr, vs SPY full era)

| tier | component | mean | sd over offsets | offsets > 0 | LOYO min (dropped yr) | LOYO max |
|---|---|---:|---:|---:|---:|---:|
| cap150 | selection = icw8 − null median | **+3.95** | 0.25 | 40/40 | +3.32 (2018) | +4.79 |
| cap150 | concentration = null median − no-score | −0.84 | 0.12 | 0/40 | −0.86 | −0.82 |
| cap150 | total = icw8 − no-score | +3.10 | 0.21 | 40/40 | +2.47 (2018) | +3.96 |
| cap500 | selection | +3.64 | 0.22 | 40/40 | +3.04 (2008) | +4.49 |
| cap500 | concentration | −0.81 | 0.15 | 0/40 | | |
| cap500 | total | +2.83 | 0.21 | 40/40 | +2.23 | +3.68 |
| cap2000 | selection | +4.12 | 0.32 | 40/40 | +3.38 (2008) | +5.01 |
| cap2000 | concentration | −0.87 | 0.18 | 0/40 | | |
| cap2000 | total | +3.25 | 0.23 | 40/40 | +2.51 | +4.12 |

The per-year LOYO gaps add exactly. The LOYO min and max columns do not add
across components, because each one is taken at a different year.

**The concentration term is the null's turnover cost.** In the supplementary
0bp (gross) run the concentration term is **−0.02pp** at cap150 (cap500
+0.01, cap2000 −0.05). A random decile is re-drawn every window. The gap between the gross and net
runs implies about 0.85pp/yr of turnover cost; name turnover itself was not
measured for the null. Before costs,
concentrating into a random decile per vol quintile is worth nothing relative
to holding the whole tier.

The gross decomposition, which is supplementary and not the frozen basis:

| tier | icw8 | null median | no-score | selection | concentration | total | selection LOYO min |
|---|---:|---:|---:|---:|---:|---:|---:|
| cap150 | +3.05 | −0.20 | −0.21 | +3.28 (40/40) | −0.02 | +3.26 | +2.65 |
| cap500 | +2.86 | −0.12 | −0.12 | +2.98 (40/40) | +0.01 | +2.99 | +2.38 |
| cap2000 | +3.05 | −0.43 | −0.36 | +3.47 (40/40) | −0.05 | +3.42 | +2.73 |

So about 0.65pp of the net selection figure at cap150 (3.95 − 3.28) is
icw8's **lower turnover** relative to a random decile. That is a genuine net
benefit of a persistent ranking, but it is not return prediction. Read the
gross column as the return-prediction share.

### USMV and SPY on the common window, 2011-10-20 to 2019-12-31 (not spliced with the full era)

| tier | book | vs SPY (common) | vs USMV (common) |
|---|---|---:|---:|
| cap150 | icw8 | **+0.00** (19/40 offsets > 0) | **+0.59** (37/40) |
| cap150 | null median | −2.83 | −2.24 |
| cap150 | no-score | −2.03 | −1.44 |
| cap500 | icw8 | −0.21 (6/40) | +0.38 (32/40) |
| cap500 | no-score | −1.93 | −1.34 |
| cap2000 | icw8 | +0.45 (39/40) | +1.04 (40/40) |
| cap2000 | no-score | −1.96 | −1.37 |

The paired gaps are identical against either benchmark, because a common
benchmark cancels out of a paired difference. At cap150 on the common window,
selection is +2.83 (40/40, LOYO min +1.65), concentration is −0.80, and total
is +2.03. **The whole of icw8's full-era excess over SPY comes from before
2011-10-20.** From late 2011 onward it matches SPY exactly and beats USMV by
0.6pp/yr, only because the eligible universe itself lagged SPY by about
2pp/yr there and the ranking made that up.

### Pool integrity

| tier | book | picks | NaN-return drops | dropped weight, mean per date | max on one date | pick date == ticker's last bar |
|---|---|---:|---:|---:|---:|---:|
| cap150 | icw8 | 966,843 | 264 | 0.096% | 10.3% | 264/264 |
| cap150 | no-score | 9,668,786 | 1,966 | 0.062% | 1.7% | 1,966/1,966 |
| cap150 | null (mean of draws) | | | 0.062% | | all |
| cap500 | icw8 | 715,011 | 175 | 0.095% | 11.1% | 175/175 |
| cap2000 | icw8 | 377,934 | 79 | 0.075% | 17.0% | 79/79 |

- The measured categories, in every book and tier:
  - 0 drops are absent from the cache.
  - 0 are "other bad price".
  - **100% are the ticker's last bar in the outcome cache**, where no
    next-open entry exists.
  - For 100% of them the pick date **equals** Sharadar `lastpricedate`
    exactly. For cap150 icw8 that is 264/264; for no-score it is
    1,966/1,966.
- The mean dropped weight is below the 0.5% materiality threshold in every
  book, so by the pre-registered test this is **not a material leak**.
- It is, however, 100% concentrated in delisting eves, and icw8 drops about
  1.5× the null's weight.
- The supplementary bound credits every dropped name with −100% at its
  pre-renormalisation weight. On that bound, cap150 icw8 falls to +2.24,
  no-score to −0.64, and the null median to −1.46. Selection becomes **+3.71**
  (40/40, LOYO min +3.06) and total becomes +2.88. Even this worst case, which
  is unrealistic because many of these delistings are cash takeovers, does not
  move the verdict.

### Turnover caveat (spec item 7)

For the no-score book at cap150, the mean name-count `f_new` is 0.043. The
weight-based turnover estimate, 0.5·Σ|Δw| with drift ignored, is 0.125, or
0.114 excluding each chain's first window. That is about 3× higher. Re-costing
the no-score book with the weight turnover moves it from −0.25 to **−0.33%/yr**
(cap500 −0.17 → −0.24; cap2000 −0.41 → −0.48). icw8's own weight-turnover
estimate is 0.28 at cap150. The headline numbers use name-count `f_new` as
specified, and on weight-based costs total and concentration would each shrink
by about 0.1pp. Neither changes the reading.

## Frozen reading (cap150 primary)

| condition | value | met |
|---|---|---|
| icw8 − null median ≥ 1.0pp/yr | +3.95 | yes |
| icw8 ≥ null p95 | +2.85 ≥ −0.93 (beats 20/20) | yes |
| paired selection gap > 0 in ≥ 36/40 offsets | 40/40 | yes |
| LOYO min of the selection gap > 0 | +3.32 (2018 dropped) | yes |
| icw8 − no-score < 0.5pp/yr (universe beta) | +3.10 | no |
| icw8 < null p80 | no | no |

**Verdict (cap150): SELECTION MATERIAL.** cap500 and cap2000 read the same
way, descriptively.

**Two consistency checks, using numbers already computed:**
- **Across grids.** icw8 − no-score is +2.86pp on column a (5.254 − 2.398)
  and +3.10pp on column c. The ranking's increment over its own universe is
  stable across the two grids. What moved is the level of the universe,
  +2.40 → −0.25.
- **The null checks itself.** At 0bp the null median (−0.20) equals no-score
  (−0.21) at cap150. The permutation null behaves as a fair random sample of
  the tier, so what separates icw8 from it is the ranking.

### What this says, in plain terms

- On the survivorship-safe grid, **holding the eligible universe
  inverse-vol weighted earns nothing over SPY** (−0.25%/yr). The +2.40%/yr
  "universe beta" from §2a was a property of the old, survivorship-selected
  grid.
- **Concentrating into a random decile per vol quintile adds nothing before
  costs** and costs about 0.85pp/yr in turnover after them.
- So the whole of icw8's ~+2.85%/yr, plus about 1pp/yr of headroom, is
  attributable to the composite **ranking**: +3.28pp gross, and a further
  ~0.65pp from the ranking's persistence (lower turnover than random).
- Caveat that bounds the reading: on the common window 2011-10-20 to
  2019-12-31, icw8 only ties SPY (+0.00) and beats USMV by +0.59. Selection
  there is still +2.83 (40/40), but it is offsetting a universe that lagged
  SPY by about 2pp/yr, not producing excess over the index.
- This is a nomination-era, descriptive decomposition. It is not a new trial,
  and it says nothing about 2020 onward.
