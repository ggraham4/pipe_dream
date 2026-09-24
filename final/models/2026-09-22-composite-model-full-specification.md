# The factor composite, full specification — for reproduction by any agent

**2026-09-22.** This is a clean, self-contained SPEC, not a narrative. For
the dated, decision-by-decision history of how each piece was found, tested,
and (in some cases) rejected, read (in order): `2026-09-19-factor-composite-
reset.md` (the original reset), `2026-09-22-composite-model-physics.md` (the
theoretical audit), `2026-09-22-composite-model-corrections.md` (17 rounds of
corrections/extensions, same day). `final/src/reset2026/PREREGISTRATION.md`
is the append-only, dated record of every pre-registered decision. This
document is the *current state* those produced — if it conflicts with a
narrative doc, the narrative doc explains why the state changed; trust this
one for "what to actually run."

All code lives in `final/src/reset2026/`. All data referenced is either
already in that directory's outputs or in the paths named below.

---

## 1. What this model claims to do, and what it doesn't

**Objective, per Gabe's explicit reframing (2026-09-22): rank prediction,
not return prediction.** The model produces a cross-sectional score for
every eligible stock on a given date; its claim is that stocks with a
higher score subsequently outperform stocks with a lower score over the
next 40 trading days, in expectation, on average, across many dates. It
does **not** claim to predict:
- the market's absolute direction (no view on SPY's own return — see §4)
- the magnitude of any single stock's return with useful precision
- anything about tail/jump events (explicitly out of scope — see §7)

**Measured performance** (nomination era, 2007-2019, genuinely out-of-sample
via odd/even-year split-half): pooled Spearman rank correlation (rho, "IC")
between the score and realized 40-day return of **+0.03 to +0.05**, t-stats
2.8-5.6. This is the realistic range for a real cross-sectional equity
signal at this horizon in liquid markets — not a limitation specific to this
factor set (see the physics doc and corrections doc §13 for the evidence
that more data of the same type does not move this much).

---

## 2. The full equation

### 2.1 Per-factor signed rank

For each factor $k$ and eligible name $i$ on date $t$, with raw value
$x_{k,i,t}$:

$$
\text{rank}_z(x) = \frac{\text{rank}(x) - 1}{n - 1} - 0.5 \quad\in[-0.5,+0.5]
$$

($n$ = count of non-missing values for that factor among eligible names on
that date; rank is ascending, ties averaged.)

$$
\hat{x}_{k,i,t} = s_k \cdot \text{rank}_z(x_{k,i,t})
$$

where $s_k \in \{-1, +1\}$ is the factor's pre-registered sign (Table 1).

### 2.2 Composite score — IC-shrinkage weighted

$$
S_{i,t} = \frac{\sum_{k \in K_{i,t}} w_k \cdot \hat{x}_{k,i,t}}
               {\sum_{k \in K_{i,t}} |w_k|}
$$

$K_{i,t}$ is whichever factors are non-missing for name $i$ on date $t$
(coverage varies row to row; the denominator renormalizes by available
weight so a missing high-weight factor doesn't silently compress a row's
score toward zero — this fix mattered in practice, see corrections doc §12).

**Weights** (`ic_weighted_composite.PRODUCTION_WEIGHTS`, frozen, fit once
on the full nomination era, never re-fit):

$$
w_k = s_k \cdot \max(0.1,\ |t_k| - 1) \big/ \textstyle\sum_j \max(0.1,\ |t_j|-1)
$$

$t_k$ = factor $k$'s own pooled Spearman-IC Newey-West t-statistic
(lag 39), measured once, not searched.

### 2.3 Portfolio construction (confirmed)

Within each of 5 trailing-volatility quintiles (`volatility_60`, computed
separately from and not by the composite), take the top decile by $S_{i,t}$,
weight inverse-volatility:

$$
w_i = \frac{1/\sigma_i}{\sum_{j \in \text{picks}} 1/\sigma_j}
$$

**Tested refinement, not yet adopted as the confirmed default** (corrections
doc §15): replace the strict top-decile re-pick with a buffer — hold a name
already in the book unless it falls out of the top 20% (by $S$, within its
vol quintile); require top-decile for new entries. Cuts realized turnover
~3x (19.3% → 6.3% per rebalance) with no measured return penalty.

### 2.4 Point forecast (secondary; rank is primary per §1)

$$
\hat{r}_{i,t \to t+40} = \beta_{i,t} \cdot E[r_{\text{mkt}}] +
    \lambda \cdot (S_{i,t} - \bar{S}_t)
$$

The model has no view on $E[r_{\text{mkt}}]$ (see §1) — in practice only the
second, relative term is used as the point forecast (`prediction_ledger.py`'s
`predicted_idiosyncratic_return_40d`). $\lambda$ = 0.01628 (`fama_macbeth_
slope_nomination()`, fit on beta-adjusted returns, nomination era, causal).

### 2.5 Beta

$$
\beta_{i,t} = \frac{\text{Cov}_{60\text{-}252d}(r_i, r_{\text{mkt}})}
                    {\text{Var}_{60\text{-}252d}(r_{\text{mkt}})}
$$

Confirmed version: trailing 252-trading-day rolling window, SPY as market
proxy, causal. Tested alternative (corrections doc §17, marginal
improvement, not adopted as default): EWMA, RiskMetrics $\lambda=0.94$ daily.

### 2.6 The metric this whole model is scored on

$$
\rho_t = \text{Spearman}\big(\{S_{i,t}\}, \{r_{i,t\to t+40}\}\big),
\qquad
\bar\rho = \frac{1}{T}\sum_t \rho_t,\quad
\text{SE}(\bar\rho) \text{ via Newey-West, lag } 39
$$

---

## 3. Factors (Table 1)

| # | factor $k$ | sign $s_k$ | weight $w_k$ | pooled IC | source | citation |
|---|---|---:|---:|---:|---|---|
| 1 | `gross_profitability` = gp/assets | +1 | **+0.596** | +0.041 (t=5.58) | SF1 (ARY, filed-date) | Novy-Marx 2013 |
| 2 | `net_issuance_pct` (YoY Δ shares) | -1 | -0.140 | -0.014 (t=-2.07) | existing panel | Pontiff & Woodgate 2008 |
| 3 | `accruals` = (netinc-ncfo)/assets | -1 | -0.163 | -0.014 (t=-2.25) | SF1 (ARY) | Sloan 1996 |
| 4 | `momentum_12_1` (12mo, skip 1mo) | +1 | +0.050 | +0.019 (t=1.38) | price panel | Jegadeesh & Titman 1993 |
| 5 | `pct_from_high_252` | +1 | +0.013 | +0.013 (t=0.84) | existing panel | George & Hwang 2004 |
| 6 | `volatility_60` | -1 | -0.013 | -0.003 (t=-0.21) | existing panel | Ang et al. 2006 |
| 7 | `days_to_next_filing_seasonal` | -1 | -0.013 | -0.002 (t=-0.77) | existing (Round 16) | Frazzini & Lamont 2007 |
| 8 | `short_interest_days_to_cover` | -1 | -0.013 | **n/a — 0% coverage 2007-2019** | existing | Boehmer, Jones & Zhang 2008 |

`asset_growth` (Cooper, Gulen & Schill 2008) was in the original 9-factor
set, measured wrong-signed (stable across both halves of the sample), and
**dropped** (not flipped) 2026-09-22 — see corrections doc §3. Factor #8 is
real and correctly wired but structurally contributed nothing to every
confirmed nomination-era number in this project, because its data starts
2020-04-27 — only active in the live signal and the (spent) hold-out.

---

## 4. Universe and eligibility

`cap150` tier (`downcap_universe.py`): point-in-time market cap ≥ $150M
**and** trailing-20-day median dollar volume ≥ $250k, both evaluated at
every historical date (not today's roster applied retroactively). ~2,000
eligible names per rebalance, ~4,011 tickers ever eligible across the full
history.

---

## 5. Eras (do not reopen without reading this)

- **Nomination era: 2007-01-02 to 2019-12-31.** Every factor sign, every
  weight, every structural decision in this document was decided using
  only this window.
- **Hold-out: 2020-2026.** Spent, three times over, for three different
  model versions (baseline, `asset_growth`-dropped, IC-weighted) — all
  three show the identical failure mode: a strong 40/40-offsets-positive
  aggregate that fails leave-one-year-out on 2020 specifically (corrections
  doc §16). Any new number computed on this window is a fourth spend and
  needs its own explicit, logged justification before running.
- **Live ledger**: `prediction_ledger_v3.csv`, started 2026-09-08 — the
  only genuinely unspent test surface. Predictions are committed before
  the 40-day outcome exists; `prediction_ledger.py score` fills them in
  once real time passes and fresh data is pulled.

---

## 6. Reproduction, start to finish

```bash
cd final/src/reset2026
# Prerequisites already on disk (see AGENTS.md's reproduction table if not):
#   composite_panel.parquet, outcome_cache.parquet, sf1_fundamentals.parquet,
#   scripts/td_data_local/SPY.csv, data/rates/treasury_yields.csv

python3 downcap_universe.py          # cap150/500/2000 eligibility, ~35s
python3 quality_factors.py           # gross_profitability, accruals, momentum_12_1, ~17s
python3 build_panel.py               # assembles composite_panel.parquet, ~25s
python3 build_outcome_cache.py --verify-samples 500   # ~15s
python3 build_beta_feature.py        # beta_252, ~10s

# The confirmed composite (composite.py) needs no build step -- it's a
# pure function of composite_panel.parquet, computed on demand.
# ic_weighted_composite.py's PRODUCTION_WEIGHTS are a frozen constant
# (Table 1's weight column) -- also no build step.

python3 model_audit.py               # per-factor IC/sign audit, ~3min
python3 ic_weighted_composite.py     # reproduces the weight-fitting + OOS validation, ~5min
python3 prediction_ledger.py record  # commit today's blind predictions
python3 prediction_ledger.py score   # once ~40 trading days have passed
```

To score any candidate factor or variant against this model: `model_audit.py`
and `beta_diagnostic.py` show the exact pooled-IC, Newey-West, split-half
pattern every factor in Table 1 was tested with. Use the same pattern —
one trial, sign declared before running, split-half or genuinely
out-of-sample, nomination era only.

---

## 7. What this model explicitly does not attempt (see corrections doc §9d,
## §14 for the evidence)

- Jump/catalyst risk (short squeezes, merger-rumor repricings) — a
  structurally different, discrete-event process a linear rank score
  cannot represent. `short_interest_days_to_cover` identifies the
  population but only as a linear mean-return effect.
- A proper risk model (factor covariance) — position sizing is diagonal
  (vol-quintile bucketing + inverse-vol), not a real covariance-aware
  optimizer.
- Realistic transaction costs for the down-cap tail during stress —
  15bp is a convenience assumption, likely too cheap exactly when the
  model's best regimes (down markets, high-vol) occur.
