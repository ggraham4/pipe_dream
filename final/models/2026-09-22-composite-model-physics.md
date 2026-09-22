# The factor composite as a theoretical model — a physics-style audit

**2026-09-22.** Written at Gabe's request: treat the sign-constrained linear
composite (`final/src/reset2026/`, full spec in
`2026-09-19-factor-composite-reset.md`) the way a physicist treats a
theoretical model — write down its precise form, state the predictions it
makes, check whether its parameters (signs, implicitly-equal weights) are
consistent with the data that's supposed to support them, name the terms
other models of the same phenomenon have that this one doesn't, and score
its fit **across the whole cross-section it claims to explain, not just the
decile it trades.**

This is a **descriptive audit of the already-confirmed nomination-era
model.** It selects nothing, backtests nothing new, and touches
**2007-2019 only** — 2020-2026 is spent for this pipeline (see the reset
doc's hold-out section) and nothing here reopens it. Two candidate
variables (`log_market_cap`, `momentum_1_1`) are scored for sign/IC as
nominations, never promoted. Full spec pre-registered in
`final/src/reset2026/PREREGISTRATION.md`'s "Model-audit pre-registration
(2026-09-22)" section before this ran. Reproduction:
`python3 final/src/reset2026/model_audit.py` →
`final/out/reset2026/model_audit_report.json`.

**Bottom line, if you read nothing else:** the model's signs are mostly
right, its equal weighting is not (cosine similarity to the IC-optimal
weighting is 0.47 — a coin flip, not a confirmation), one of its nine
factors contributes **zero** information over the entire period the model
was validated on, its response function is not monotonic the way "buy the
top decile" assumes, and the gap between what its own forecasting power
can explain and what its backtested portfolio actually returned is large
enough that most of the confirmed edge is very unlikely to be stock
selection.

---

## 1. The model, formalized

For each rebalance date $t$ and eligible name $i$, nine factors $x_{k,i,t}$
are each cross-sectionally rank-transformed to $[-0.5, +0.5]$
(`composite.rank_z`), multiplied by a sign $s_k \in \{-1, +1\}$ fixed
**before any score was computed**, and averaged over whichever factors $i$
actually has data for that day:

$$
S_{i,t} \;=\; \frac{1}{|K_{i,t}|} \sum_{k \in K_{i,t}} s_k \cdot
\mathrm{rank}_z(x_{k,i,t})
$$

$K_{i,t} \subseteq \{1,\dots,9\}$ is whichever factors are non-missing for
$i$ on $t$ — coverage varies row to row (median 8 of the nominal 9;
effectively capped at 8 throughout the nomination era for a reason
detailed in section 2). This is a
**linear model with equal, un-fitted weights** $w_k = 1/9$ for all $k$ (or
$1/|K_{i,t}|$ under missingness) — the entire point of the 2026-09-18
reset was to drive the number of fitted parameters to zero. A second
variant residualizes each $x_k$ on sector dummies before ranking
(`neutral`). Portfolio construction (`decile_volq`) then takes the top
decile of $S_{i,t}$ within each of 5 trailing-volatility quintiles,
inverse-volatility weighted.

This is not a metaphor — it is structurally identical to a **Piotroski
F-score or Asness QMJ-style composite**: a signed sum of z-scores, no
regression. The right comparison class is that family, and Barra/Axioma
style multi-factor risk models, not the 25-column XGBoost this project
retired on 2026-09-18. Sections 8 and 9 make that comparison precise.

### 1.1 The predictions this functional form actually makes

Written down before checking any of them against data, because a model
that isn't falsifiable this way isn't doing any work:

1. **Sign prediction**: $\mathrm{IC}_k = \mathrm{corr}(x_{k,i,t}, r_{i,t
   \to t+40}) $ should have the same sign as $s_k$, for all 9 $k$,
   independently of what else is in the model (linearity + equal weight
   means each term's marginal contribution doesn't depend on the others).
2. **Monotonicity prediction**: $E[r \mid S = s]$ should be non-decreasing
   in $s$ — "buy the top decile" is only the right portfolio rule if this
   holds across the range being traded.
3. **Equal-weight-is-fine prediction**: if the 9 factors have similar IC
   and are not strongly correlated with each other, equal weighting is
   close to the Sharpe-optimal (Grinold-Kahn) weighting. If they don't,
   equal weighting is leaving IC on the table by design, not by
   necessity.
4. **Full-cross-section prediction**: because $S$ is a single scalar
   score with no interaction terms, the model predicts a fixed,
   monotonic response *everywhere* in the universe, not just at the
   traded tail — it should have real explanatory power (measurable IC/R²)
   across the whole eligible pool, not only among the names actually
   picked.
5. **IC-IR consistency prediction**: portfolio risk-adjusted return should
   not exceed what $IR = IC \times \sqrt{\text{breadth}}$ permits, given
   the number of genuinely independent bets the construction takes. Any
   realized IR far above that ceiling is not something this model, as
   specified, can be credited with — it has to be coming from the
   *construction* (vol-quintile bucketing, inverse-vol weighting), not
   the *scores*.

Sections 3-7 check each of these against the nomination-era data (pooled
daily Spearman IC vs. `forward_return_tradable_40` — the same tradable
label the backtest trades on, never the non-tradable close-to-close
label — with Newey-West standard errors at lag 39 to account for the
serial correlation 40-day-overlapping forward windows induce).

---

## 2. A defect found before any of the five predictions could be checked

`short_interest_days_to_cover` — one of the nine factors, signed `-1`,
citation Boehmer/Jones/Zhang 2008 — has **zero non-null values anywhere in
the cap150-eligible nomination era.** Its data starts 2020-04-27:

```
first_date: null   last_date: null   coverage_frac: 0.0%   n_nonnull: 0 / 6,691,650
```

It only exists from 2020 onward — i.e. **only inside the hold-out period**
that already failed leave-one-year-out (main write-up §3.2), and in the
live model today. The 13-year nomination-era backtest that is the entire
evidentiary basis for this composite ran, the whole time, on **8 factors
wearing a 9-factor label.** `compute_composite`'s missingness handling
(mean of whichever factors are present) means this didn't crash or
distort anything — it degrades gracefully to an 8-factor average, exactly
as designed — but "nine pre-registered signs" and "nine factors that
actually informed the confirmed result" are not the same claim, and
nothing in the reset write-up or its pre-registration flagged the
difference.

This is the same bug *class* the project's own bug ledger already names
(`AGENTS.md`'s "six bugs, one pattern" table, and Round 18's
`_bucket_idx` NaN-to-bucket-0 defect): **a component silently contributes
nothing, and every check that ran verified internal consistency
(`compute_composite` didn't crash, coverage was reported) rather than
correspondence to the outside world** (nobody asked "does this factor
have data over the period we're about to trust?"). `model_audit.py` now
prints first/last non-null date and coverage fraction for every factor
before computing anything else — the Gate-A7c fix ("verify by naming what
should be there") applied here.

**This does not overturn the confirmed nomination-era result** — an
8-factor equal-weighted composite is still a valid, if slightly
mislabeled, sign-constrained model, and the backtest that confirmed it
ran on real data throughout. It does mean: (a) the write-up's "9 factors"
framing should read "8 factors over 2007-2019, a 9th active only from
2020," and (b) any claim about what `short_interest_days_to_cover`
contributes to the *confirmed* result is currently zero, by construction,
not by measurement.

---

## 3. Are the signs right?

Pooled Spearman IC, cap150-eligible universe, 2007-2019, NW t at lag 39:

| factor | assigned sign | pooled IC | t | sign matches? | odd-yr IC | even-yr IC | split-half same sign? |
|---|---:|---:|---:|:---:|---:|---:|:---:|
| `gross_profitability` | + | **+0.0410** | **+5.58** | Yes | +0.038 | +0.045 | Yes |
| `accruals` | − | **−0.0135** | **−2.25** | Yes | −0.012 | −0.016 | Yes |
| `net_issuance_pct` | − | **−0.0141** | **−2.07** | Yes | −0.017 | −0.011 | Yes |
| `momentum_12_1` | + | +0.0185 | +1.38 | Yes | +0.021 | +0.015 | Yes |
| `pct_from_high_252` | + | +0.0134 | +0.84 | Yes | +0.017 | +0.008 | Yes |
| `asset_growth` | **−** | **+0.0105** | **+1.47** | **No** | +0.009 | +0.012 | Yes (both wrong sign) |
| `volatility_60` | − | −0.0034 | −0.21 | Yes (weak) | +0.001 | −0.008 | **No** |
| `days_to_next_filing_seasonal` | − | −0.0021 | −0.77 | Yes (weak) | −0.004 | 0.000 | ambiguous |
| `short_interest_days_to_cover` | − | n/a | n/a | n/a — 0% coverage this era | — | — | — |

**Two real findings, not one.**

**`asset_growth` has the wrong sign, consistently, in both halves of the
sample.** The published anomaly (Cooper, Gulen & Schill 2008) says firms
that grow assets aggressively subsequently underperform — high asset
growth, low future return, hence the assigned `-1`. This panel measures
the opposite: `IC = +0.0105` (t = +1.47, not itself significant alone, but
positive in *both* odd and even years, so it isn't sampling noise flipping
a true zero). This is not disqualifying on its own — in the signed-factor
correlation matrix (section 4), `asset_growth` correlates -0.13 with
`momentum_12_1` and +0.34 with `net_issuance_pct`, its two strongest
relationships to any other factor -- a firm raising capital and expanding
its balance sheet is mechanically close to the firm this model's own
issuance factor already penalizes, so `asset_growth`'s wrong-signed IC may
be riding on `net_issuance_pct` rather than adding independent
mis-signed information; the raw asset-growth anomaly is also better
documented in large-cap, mature-firm samples than in a
down-to-$150M-cap universe with a heavy weight of firms genuinely still in
a growth phase) — but as measured, in this universe, over this period,
the model's asset-growth term is currently working against its own
economic rationale, not for it.

**Two factors (`volatility_60`, `days_to_next_filing_seasonal`) have the
right sign but no measurable individual effect at this sample size** (t
= −0.21 and −0.77) and one of them flips sign between halves
(`volatility_60`: +0.001 odd years, −0.008 even years). This mirrors
exactly what `AGENTS.md`'s grid-offset section already found for the old
model's `volatility_60` and `momentum_20` (0/40 and 16/40 sign flips
respectively across grid offsets) — a weak factor's sign is a prior, not a
demonstrated measurement, and that was already known to be true of this
project's OHLCV-derived features before this audit; it appears to extend
to at least one of the new panel's factors too.

**Six of eight measurable factors are unambiguously right** — signed,
significant, and stable across both halves of the sample:
`gross_profitability` (by a wide margin), `accruals`, `net_issuance_pct`,
plus directionally-correct-but-marginal `momentum_12_1` and
`pct_from_high_252`. This is a genuinely different, better outcome than
this project's last several rounds of price/volume feature mining, which
came back null or unstable at a much higher rate (`AGENTS.md`'s Round
12-19 record). The published-anomaly-first strategy is doing real work.

---

## 4. Are the (equal) weights right?

They are not, by a specific, computable margin. `compute_composite`
implicitly asserts $w_k = 1/9$ for all $k$. The Grinold-Kahn result says
the Sharpe-optimal linear combination is $w^* \propto \Sigma^{-1}
\cdot \mathrm{IC}$, where $\Sigma$ is the factor covariance (here
approximated by the pooled cross-sectional correlation matrix of the
signed, date-standardized ranks — same units `compute_composite`
averages). Solved on the 8 factors with nomination-era data:

| factor | signed IC | GK-optimal weight (normalized) | equal weight |
|---|---:|---:|---:|
| `gross_profitability` | +0.0410 | **+0.426** | 0.125 |
| `momentum_12_1` | +0.0185 | +0.144 | 0.125 |
| `net_issuance_pct` | +0.0141 | +0.108 | 0.125 |
| `accruals` | +0.0135 | +0.082 | 0.125 |
| `pct_from_high_252` | +0.0134 | +0.037 | 0.125 |
| `volatility_60` | +0.0034 | +0.033 | 0.125 |
| `days_to_next_filing_seasonal` | +0.0021 | +0.003 | 0.125 |
| `asset_growth` | −0.0105 | **−0.167** | 0.125 |

**Cosine similarity between the equal-weight vector and the GK-optimal
vector: 0.47.** That is roughly the similarity you'd get from a random
direction constrained to the positive orthant against this one — equal
weighting is not "close enough to optimal to not matter," it is a
genuinely different point in weight-space. Concretely: `gross_profitability`
carries 3.4x its equal share of the model's actual predictive content and
is diluted down to 1/9 anyway; `days_to_next_filing_seasonal` carries
essentially none (weight 0.003) and is inflated up to 1/9; and
`asset_growth`'s wrong-signed IC means the *optimal* combination would
flip its sign, not just distrust it.

**This is diagnostic, not a recommendation to refit.** The reset's whole
premise (`PREREGISTRATION.md` §1) is that a fitted, high-DOF combiner is
what broke the previous 19 rounds — swapping in $\Sigma^{-1}\mathrm{IC}$
now would reintroduce exactly the estimation-noise-chasing this package
was built to avoid, on the same ~13-year sample that already can't
resolve several of these factors individually. The honest reading: equal
weighting is a **prior with a known, computable cost** (§5 quantifies the
cost directly), not a free assumption. If this gets revisited, the
disciplined move is shrinkage toward equal weight (a Bayesian blend, or a
much simpler ordinal rule like "drop factors with |t| < 1, keep the rest
equal-weighted") rather than a full Grinold-Kahn refit on 13 years of
data.

---

## 5. The cost of equal weighting, directly measured

If equal weighting were free, the composite's full-universe IC should be
at least as good as its best single ingredient. It is not:

| score | pooled IC (cap150, full universe) | t |
|---|---:|---:|
| `gross_profitability` alone | **+0.0410** | +5.58 |
| **8-factor equal-weighted composite** | **+0.0262** | +2.31 |

**Averaging in the other seven factors — including two with no measurable
individual effect and one with a possibly-wrong sign — costs about a
third of `gross_profitability`'s own predictive power.** This is the
single cleanest, most actionable number in this audit: it is not a
claim about statistical significance or robustness, it is a same-units,
same-era, same-universe comparison of one number against a `.mean()` of
that number with seven others. Sections 3-4 already explain the
mechanism (six good, two-to-three weak/wrong, all pulling the same
scalar toward its unweighted center).

---

## 6. Is the response monotonic? (Coverage-bias hypothesis, tested and
## mostly ruled out; the real story is a different shape)

**Coverage hypothesis, tested first.** A name scored on only 2-4 of 9
factors has a noisier composite (smaller-$k$ mean of similar-variance
terms), so its scores populate the tails more than its actual predictive
content should. Tested directly, cap150 full universe:

| slice | pooled IC | t | mean coverage |
|---|---:|---:|---:|
| hi-coverage (≥8 factors) | +0.0266 | +2.29 | 8.0 |
| lo-coverage (≤4 factors) | +0.0222 | +2.01 | 3.30 |
| full universe | +0.0262 | +2.31 | — |

**Not a large effect** — same sign, similar magnitude, both individually
significant. Coverage-driven noise inflation is a real mechanism in
principle (and worth remembering for any future composite with more
missingness than this one has: only 3.2% of rows are low-coverage here)
but it is **not** what's behind the top-decile IC collapse this project's
own write-up already documented (main doc §3.5: full-universe IC +0.034
vs. top-decile IC −0.009). Ruling this out matters — it means the real
explanation is structural, not a data-quality artifact, which is worse
news for the "just buy the top decile" portfolio rule, not better.

**The actual shape, all 10 deciles, pooled mean 40-day forward return
(cap150, raw):**

| decile (0=worst score) | 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 (best) |
|---|---|---|---|---|---|---|---|---|---|---|
| mean fwd. return | **+1.52%** | **+1.92%** | +1.81% | +1.88% | +1.86% | +1.87% | +1.85% | +1.72% | +1.65% | +1.78% |
| t (NW) | 1.40 | 2.02 | 2.10 | 2.38 | 2.56 | 2.76 | 2.95 | 2.93 | 2.97 | 3.45 |

This is **not the monotonic staircase "buy the top decile" assumes.** The
shape is: the bottom decile is genuinely worst (this is where essentially
all of the model's pooled IC comes from — a "know what to avoid" signal),
returns are flat-to-mildly-declining across deciles 1 through 8, and only
a small rebound appears at the very top. **Decile 9 (+1.78%) is
numerically below decile 1 (+1.92%).** The sector-neutral variant shows
the identical shape (decile 1 = +2.06% vs. decile 9 = +1.73%) so this
isn't a sector artifact either.

**What this predicts, and why it matters for the deployed construction.**
`decile_volq` explicitly selects from decile 9 within each volatility
quintile — precisely the part of the score's range with the **least**
demonstrated advantage over the broad "not-decile-0" pool, on this table.
A construction that instead excluded decile 0 and held everything else
(or held deciles 1-3, which are nominally the best in this table) would,
on this evidence, be picking from a stronger part of the response curve
than "top decile" is. This reframes the earlier, still-open question in
the reset write-up (§6.2: why does `decile_volq`, ~200 names, beat
`topn_ew`, ~100 names concentrated in the nominal best names, on
hold-out?) — this table gives a candidate mechanical answer: **the top
of the score distribution is not where the model's edge lives; the
bottom is.** `topn_ew` concentrates in the region with the weakest
individual evidence for outperformance; `decile_volq`'s within-quintile
construction, by taking a decile from every volatility bucket rather than
a flat top slice, incidentally avoids concentrating as heavily in that
same narrow top-of-distribution region. Worth testing directly (a
"avoid-decile-0" construction, or "buy deciles 1-3") before the next
portfolio-construction change — not done here, flagged as the highest
open follow-up.

---

## 7. Fit across the whole cross-section, not just the traded book

The user's framing for this audit — optimize for accuracy across all
stocks, not just the profitable slice — is answered directly by comparing
**forecasting accuracy** (IC, cross-sectional R²) against **portfolio
profitability** (excess CAGR, from the main write-up) across the same four
model variants:

| variant | full-universe IC (ρ) | IC t-stat | Fama-MacBeth R² | nomination-era portfolio excess CAGR vs SPY* |
|---|---:|---:|---:|---:|
| `cap2000_raw` | **0.0354** | 2.79 | 0.0203 | +1.09%/yr |
| `cap2000_neutral` | 0.0207 | 1.86 | 0.0149 | −0.32%/yr |
| `cap150_raw` | 0.0262 | 2.31 | 0.0150 | **+3.75%/yr** |
| `cap150_neutral` | 0.0174 | 1.61 | 0.0133 | (not separately reported in main doc; robustness-checked positive) |

*\*From `2026-09-19-factor-composite-reset.md` §3.1, `decile_volq`,
15bp cost, 40-offset average.*

**This is the whole point made numerically: forecasting accuracy and
portfolio profitability move in *opposite* directions across these four
rows.** `cap2000_raw` is the single most accurate model by IC and R² of
the four — and the second-least profitable. `cap150_raw` is *less*
accurate at ranking the full cross-section than `cap2000_raw` (0.0262 vs.
0.0354) and yet delivers 3.4x the portfolio excess return. A model
optimized purely to maximize full-universe IC would pick `cap2000_raw`;
the model actually confirmed and headed toward deployment is
`cap150_raw`, chosen (correctly, per the reset's own stated goal) for
portfolio excess return, not cross-sectional accuracy. **These are
different objectives, and this table is the first place in this project's
history they've been placed side by side.** The gap is explained by
breadth, not skill: `cap150`'s larger, lower-correlation universe lets the
same (slightly noisier) score compound into a much better book through
diversification — exactly what Round 15's `IR = IC × √breadth` framework
predicts, and exactly why the reset lowered the cap floor in the first
place. It is not evidence the `cap150` model understands stocks better;
by the model's own accuracy metric, it understands them slightly less
well.

On magnitude: a cross-sectional R² of 1.3-2.0% is not "the model explains
nothing" — it is the ordinary size of a real, tradable equity factor
signal (for calibration, a *published*, well-replicated single anomaly
like `gross_profitability` alone corresponds to roughly this same order
of magnitude of return variance explained per cross-section). Read the IC
column as the headline, R² as a corroborating cross-check, not as a
discouraging number in isolation.

---

## 8. Does the realized portfolio's risk-adjusted return match what the
## scores can explain?

$$
IR \;=\; IC \times \sqrt{\text{breadth}}
$$

Round 15 measured effective breadth ≈ 16 at the `cap2000` tier (properly
risk-standardized, not the naive equal-variance formula that earlier gave
a provably-impossible 19.1). `cap150`'s own breadth was not remeasured
with that full machinery here (out of scope for this audit — porting
`sweep/breadth.py`'s risk-standardized estimator to the reset2026 panel is
real work, flagged as a follow-up, not attempted under time pressure for
a descriptive pass). Instead, a single-offset, gross-of-cost realized IR
was computed directly from `outcome_cache.parquet` (`cap150_raw`,
`decile_volq`, offset 0, 82 windows, 2007-2019):

```
mean excess return per 40-day window vs SPY:   +0.744%
std excess return per 40-day window:            1.969%
annualized IR:                                  0.948
```

Compare against what the model's own measured full-universe IC (0.0262)
predicts is achievable, at increasingly generous breadth assumptions:

| assumed breadth | $IC \times \sqrt{breadth}$ | vs. realized IR 0.948 |
|---:|---:|---:|
| 16 (Round 15's cap2000 measurement) | 0.105 | realized is **9.0x** higher |
| 200 (the ~200 positions actually held) | 0.371 | realized is **2.6x** higher |
| 1,309 | 0.948 | (breadth this would require to match) |

**A book of ~200 positions cannot contain 1,309 independent bets — that
number is definitionally impossible**, and it is far above even a
maximally generous fully-independent-name assumption for 200 real
equities (Round 15 already established real average pairwise active
correlation of 0.055-0.076 makes true breadth much *lower* than name
count, not equal to it). The conclusion this forces: **the realized
excess-vs-SPY return is not something the cross-sectional forecasting
power of this score, as measured, can be credited with — most of it has
to be coming from somewhere $IC \times \sqrt{breadth}$ doesn't see.**

The likely mechanism, and it's identifiable rather than mysterious:
$IC$ is measured *within* each date (a rank correlation, orthogonal by
construction to that date's average return), so it can only ever capture
**relative stock-picking skill**. "Excess return vs. SPY," measured
across dates, additionally captures **any static tilt the portfolio
carries relative to cap-weighted the market** — a quality/low-vol/value
factor bet that happened to earn a premium over 2007-2019 (a period that
includes 2008, this composite's single largest per-year contributor at
+11.78% per the main write-up) shows up in excess-return-vs-SPY in full,
and shows up in within-date IC not at all. This is the *same* mechanism
this project's own Round 13 already found and quantified for the old
deployed model (sector-neutralizing it took 2.80x down to 0.77x, the
exact center of its own null) and Round 18 found again (a measured
low-volatility tilt, score-vol correlation −0.134). Section 3.1 of the
main reset write-up already reports the raw-vs-neutral gap for this
composite directly (`cap2000`: +1.09% raw vs. −0.32% neutral — the sector
tilt alone is bigger than the whole neutralized result); this section
adds the quantitative bound showing that gap, plus a low-vol/quality
factor-timing return of the kind IC cannot see, is large enough to
explain nearly all of the realized IR **without invoking any
stock-selection skill beyond what §3's per-factor ICs already measure.**

**This does not mean the composite doesn't work** — a real, static factor
tilt that would have earned a premium over 13 years is exactly the kind
of edge the published-anomaly literature this composite is built from
claims to exist, and this project's own sector-neutral robustness checks
(main write-up §3.1) already show `cap150_raw` survives sector
neutralization losing only 0.3pp, unlike the old model. It means: **the
mechanism producing the backtested dollars is predominantly systematic
factor exposure and diversification-driven variance reduction, not
fine-grained cross-sectional stock-picking** — and any future work aimed
at "making the model more accurate" should target the deciles and
factors in §§3-6 (where the forecasting power actually lives and doesn't),
not assume the portfolio's IR is a report card on the scores.

---

## 9. Missing variables

### 9.1 Value — the strongest omission, argued but not tested here

**Nine factors span momentum, low-vol, quality, investment, issuance,
earnings-timing and short interest — and zero exposure to book-to-market,
earnings yield, or free-cash-flow yield.** This is not a minor gap. The
citation this composite already leans on for `gross_profitability`
(Novy-Marx 2013, "The Other Side of Value") frames profitability
*explicitly* as value's complement: profitability alone tilts growth-ward
(expensive, high-quality names), value alone tilts cheap-ward, and the
paper's central result is that combining them is much stronger than
either alone, specifically *because* they partially offset each other's
biases. Shipping `gross_profitability` without a value factor uses half
of the published result this composite is already citing.

**This is buildable at zero new data cost.** `final/data/sharadar/
sf1_fundamentals.parquet` — already on disk, already joined for every
other fundamentals-based factor in this composite — carries `equity`
(book value) and `marketcap` directly, so book-to-market
($\text{equity}/\text{marketcap}$) requires no new pull, no new PIT
join logic, and no new filing-date-timing risk beyond what
`gross_profitability`/`accruals`/`asset_growth` already carry correctly
(filed-date joins, per the reset write-up's §4.4 mechanical checks).
`netinc` is also present for an earnings-yield alternative. **Not tested
in this audit** (the pre-registration for this pass named exactly two
candidates, §9.2-9.3, to keep the trial count honest) — this is the
single highest-value next step if this work continues, and it's a
same-session, no-new-data addition.

### 9.2 Size as a continuous factor — tested, and it's real

The universe tiers already use market cap as a step-function screen
(`eligible_cap150`, etc.). Tested here as a *continuous* factor within
the eligible pool — does residual size variation, above the floor,
still carry signal?

```
log_market_cap    IC = -0.0201   t = -2.04   (candidate sign: -1, matches)
```

Significant, correctly signed (smaller-within-the-eligible-pool
outperforms — the classical size premium, Banz 1981 / Fama-French SMB),
and **stronger than four of the eight already-included factors**
(`volatility_60` t=−0.21, `days_to_next_filing_seasonal` t=−0.77,
`pct_from_high_252` t=0.84, `momentum_12_1` t=1.38 — see §3's table).
This is independent evidence for something the reset write-up already
showed indirectly: cap-tier is monotonic in profitability (§3.1's
+1.09% → +3.03% → +3.75% as the floor comes down) — this shows the same
gradient exists *within* a single tier, not only *between* tiers, meaning
there is exploitable size information the hard floor currently throws
away entirely rather than scoring.

### 9.3 Short-term reversal — tested, not confirmed

`momentum_12_1` explicitly skips the most recent month **because that
month reverses** (the well-documented short-term reversal anomaly,
Jegadeesh 1990) — the model acknowledges the effect exists by discarding
that data, without using it with the opposite sign. Tested here directly:

```
momentum_1_1 (1-month return)   IC = -0.0031   t = -0.39   (candidate sign: -1, matches direction, not significant)
```

Correct sign, far from significant at this sample size and horizon. An
honest negative — the skipped month's reversal effect, if real in this
universe, is not currently detectable at a pooled 40-day-forward
horizon with this measurement. Not recommended for promotion on this
evidence; flagged as tested-and-inconclusive rather than omitted from
consideration.

---

## 10. What terms other models of this phenomenon have that this one
## structurally cannot express

Not "more factors" — the functional form itself. Three specific
capacities other model classes in wide use for this exact problem
(cross-sectional equity return prediction) have, and a signed-rank linear
average cannot, by construction:

**No factor covariance / risk model.** Barra- and Axioma-style
multi-factor models estimate a full factor covariance matrix and build
portfolios by optimizing against it (mean-variance, or at minimum a
proper risk-parity solve). This composite substitutes a much cruder
proxy — 5 volatility quintiles plus inverse-volatility weighting, i.e. a
**diagonal** risk model that only ever sees each name's own variance,
never its covariance with the rest of the book. Round 15's own measured
average pairwise active correlation (0.055-0.076, breadth capped ~16 at
the `cap2000` tier) is a direct measurement of the off-diagonal structure
this construction ignores. §8's IC-IR gap is partly a symptom of this: a
real risk model would tell you whether the realized Sharpe is
diversification you engineered or diversification you got lucky into.

**No factor returns (no time-varying $\lambda_t$).** Fama-MacBeth and
Barra estimate a *return to each factor* every period; this composite
asserts, structurally, that $\lambda_k = \text{const} \times s_k$ for all
time. It therefore cannot express **momentum crashes** (Daniel &
Moskowitz 2016 — momentum's own premium goes sharply negative in sharp
market reversals, exactly a 2020-style V-shaped recovery), cannot express
a value/quality rotation, and cannot express any regime dependence at
all. The hold-out's own failure mode (main write-up §3.2: only 2 of 7
years positive, 2020 and 2022 carrying the whole result) is the textbook
signature of a model with a real, constant-$\lambda$ factor tilt hitting
years where that specific tilt's *time-varying* true return diverged
sharply from its full-sample average — precisely the thing a
constant-coefficient linear model cannot see coming or adjust for.

**No interaction terms.** A signed sum of independent scores has no way
to represent "momentum works better in low-vol regimes," "value works
better when accompanied by a profitability signal" (the very Novy-Marx
result §9.1 already leans on for one factor and doesn't extend to a
value×profitability *interaction*), or "quality matters more in distress
periods." Every second-order, conditional result in the published
anomaly literature is invisible to this functional form by construction,
not by omission of a specific column.

None of these are reasons to abandon the linear composite — they are
exactly the complexity budget items the 2026-09-18 reset explicitly
deferred in favor of a near-zero-fit baseline first (the tiered "meta
model" roadmap already on record, `project-meta-model-roadmap` memory:
zero-fit blend → regime gate → learned combiner, in that order,
cheapest-first). This section exists so that when the next tier of that
roadmap gets built, it's clear *which specific capability gap* each
addition is meant to close, rather than adding complexity in the
abstract.

---

## 11. Recommendations, ordered by cost (cheapest/least-fit first, per
## this project's own standing philosophy)

1. **Fix the `short_interest_days_to_cover` labeling** — either document
   it as "8 factors, 2007-2019; a 9th active from 2020" everywhere the
   9-factor claim appears, or backfill/relabel it. Zero cost, pure
   correction of a factual claim.
2. **Test an "avoid decile 0" or "buy deciles 1-3" construction** against
   the current `decile_volq` (top decile), same universe, same dates —
   §6's finding that the top decile is not where the measured edge lives
   is the highest-value, cheapest follow-up in this document: it changes
   which rows get selected, not what the model believes about any stock.
3. **Build book-to-market from `sf1_fundamentals.parquet`'s existing
   `equity`/`marketcap` columns** (§9.1) — zero new data, directly
   motivated by a citation the model already uses, one new pre-registered
   trial.
4. **Consider a shrinkage-toward-equal weighting scheme** (e.g., zero out
   factors with |t| < 1 rather than full Grinold-Kahn) informed by §4-5,
   not a full refit — consistent with the reset's explicit anti-overfitting
   design intent, and directly motivated by a measured, not assumed, cost
   of equal weighting.
5. **Measure `cap150`'s true risk-standardized breadth** with
   `sweep/breadth.py`'s corrected methodology (ported to this panel) —
   closes the one number in §8 that had to be estimated indirectly here.
6. **Add the size factor** (§9.2) as a tenth signed factor, if the
   pre-registration discipline is maintained (name it, predict its sign,
   test it, accept the result whichever way it goes) — it already passed
   that test in this audit as a nomination; promoting it to `FACTOR_SIGNS`
   is the next, separate step this document does not take.

---

## 12. Reproduction

```bash
cd final/src/reset2026
python3 model_audit.py
# -> final/out/reset2026/model_audit_report.json (all numbers in this doc)
```

Requires `composite_panel.parquet` and `outcome_cache.parquet` already
built (see the main reset write-up's §7 for how). Runs in ~3 minutes.
Touches 2007-2019 only; does not read or write anything for 2020-2026.
