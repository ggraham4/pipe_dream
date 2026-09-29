# WO-25: re-derive the Theoretical composite's ICW weights on the v2 panel ("icw9_v2")

Date: 2026-09-29. Work order WO-25 (COO). Branch
`worktree-agent-aa9609e4d8a64a036`, based on `origin/integration` 0dd6908 with
`origin/worktree-wo23-model-audit` 9106bef merged in (86c8b39) for the WO-23
harness (`final/src/audit/`).

**Status: METHOD PINNED.** Sections 1-3 are committed before any backtest,
split-half t, or pick-overlap number is computed. After that commit they are
not edited. Results go in section 4 onward.

## 1. Gabe's decision (2026-09-29, verbatim)

> "re derive on v2, fit on 2020-26"

- Re-derive the IC-shrinkage (ICW) weights on the v2 working panel.
- `short_interest_days_to_cover` has no data before 2020, so its weight is FIT
  on 2020-2026. Gabe explicitly approved fitting on the hold-out for this.
- All other factors' t's come from v2 column c, 2007-2019.

**Hold-out read #7.** This read FITS one weight on 2020-2026. Once SI is fit
on 2020-26, **no untouched historical test remains for this model**. Only the
forward ledgers can confirm it.

Nothing live changes in this work order. `PRODUCTION_WEIGHTS*` are not edited,
no live file is edited, nothing is deployed. The proposed weights are
delivered as a JSON plus the ready-to-paste block in section 3.3.

## 2. Method (fixed before any backtest)

### 2.1 Rule: unchanged

The EXACT ICW rule of the live constants:
`w_k = sign_k * max(0.1, |t_k| - 1) / sum_j |.|`, i.e. `screen_insider.fit_weights`
(`SI.fit_weights`, identical to `ic_weighted_composite.fit_weights`), with the
live signs `ic_weighted_composite.SIGNS_V9_SEAS` (unchanged). A NaN t gets the
floor 0.1. Only the input t's change.

### 2.2 Inputs

| factor | t source |
|---|---|
| momentum_12_1, pct_from_high_252, volatility_60, gross_profitability, accruals, net_issuance_pct, days_to_next_filing_seasonal, seas | pooled daily Spearman IC vs `forward_return_tradable_40`, Newey-West lag 39 t (`screen_insider_v2grid.ic_gates` pooled t), v2 col c, cap150, **2007-01-02..2019-12-31** = WO-23 period A |
| short_interest_days_to_cover | the same t on **2020-01-02..2026-07-30** = WO-23 period B (IN-SAMPLE for the SI weight) |

The t's are taken from WO-23's JSONs (`final/out/audit/model_audit_wo23_{A,B}.json`,
`theoretical.factors[k].t`, full precision) and **recomputed** from the panel
with the WO-23 loader (`model_audit_wo23.load_theo` + `factor_ic`); the
recomputation must match to 1e-6. Pinned fallback: if it does not match, stop,
report the gap, and use WO-23's published t's (stated as such). The loader is
not tweaked to force a match.

Data provenance: `composite_panel_v2.parquet` and `outcome_cache_v2.parquet` in
the main checkout, mtime 2026-09-26 22:44 (before WO-23's 2026-09-28 run).
`seas_factor_ext.parquet` copied from the wo23 worktree, sha256
`ca9721d3879bca0b2340bea660ca43949a485fb9bd9cd2513614dd4137f52e2c` (identical).

WO-23's A seas t equals `ic_weighted_composite.SEAS_T` exactly (diff 0.0).

### 2.3 Name-check (done; reads only published numbers)

The same functions reproduce the CURRENT live weights from the CURRENT (v1)
t's (`final/out/reset2026/ic_weighted_composite_report.json`
`per_factor_t.full`, v1 panel, + `SEAS_T`):

- `ICW.fit_weights` → 4 dp == `PRODUCTION_WEIGHTS` (icw8): **PASS, exact**.
- `SI.fit_weights` (8 v1 t's + SEAS_T, SIGNS_V9_SEAS) → 4 dp ==
  `PRODUCTION_WEIGHTS_V9_SEAS` (live icw9_seas): **PASS, exact**.

So the rule is unchanged; only its inputs move from v1 to v2 t's.

Cross-check: icw9_v2 with SI at the floor equals WO-23's "implied w A" column
exactly (asserted, 1e-12).

### 2.4 SI does nothing in period A (stated up front)

SI has zero coverage before 2020. The scorer renormalises by the |w|
available on each row, so on every A date SI drops out of numerator and
denominator, and a positive rescaling of the other weights leaves ranks
unchanged. **The icw9_v2 A books (in-sample and split-half) depend only on the
8 non-SI weights.** "SI stays at its B-fit value in both halves" is true and
has no effect on A. No A number is evidence for the SI fit.

### 2.5 Backtests (all)

cap150, v2 col c, `decile_volq`, 40 grid offsets, net 15 bp, excess vs SPY
annualised ×252/40 — the WO-23 harness (`screen_insider_v2grid.Book`,
`downcap_v2_readout.backtest`, `model_audit_wo23.run_book`), imported, not
edited. Books use the **4-dp** weight constants (as WO-20/WO-23); the
full-precision icw9_v2 is also reported. Stats: mean40, sd40 (population sd of
the 40 offset means), offsets positive (of 40), LOYO min (calendar year within
the period), post-2011-10 (A only).

Reconcile first: live icw9_seas 4 dp must reproduce WO-23's A and B
`icw9_seas` mean40 to 1e-9.

Variants:
1. **A in-sample**: live icw9_seas vs icw9_v2, 2007-2019. IN-SAMPLE for the 8
   factors of icw9_v2 (and for live icw9_seas, whose t's are v1 2007-2019).
2. **A split-half OOS (icw9_v2 only)**: odd/even split on `date.year % 2`
   (the v1 ICW convention). For each half, recompute the 8 non-SI t's with the
   same function that reproduced the full-A t's on that half's rows; SI stays
   at its B-fit t (no effect in A, 2.4). Score stitching: odd-year dates are
   scored with the even-fit weights and even-year dates with the odd-fit
   weights; one 40-offset A book is run on the stitched score (mean40, sd40,
   offsets positive, LOYO min, post-2011-10). Also reported: each half's
   restricted book (odd-fit weights on even-year dates only, and vice versa).
   Known artifacts, noted not embargoed (v1 convention): late-December 40d
   labels spill into the next year; turnover crosses year boundaries. Live
   icw9_seas has no split-half counterpart; its cell is N/A (in-sample only).
   Split-half weights use full precision (no 4-dp rounding).
3. **B 2020-01-02..2026-07-30**: live icw9_seas vs icw9_v2. IN-SAMPLE for the
   SI weight; out-of-sample for the other 8 weights.
4. **B with SI at the floor**: icw9_v2_si_floor (8 re-derived, SI t = NaN →
   floor). Isolates the SI-fit contribution (variant 3 minus variant 4, per
   offset, mean and sd).

### 2.6 Pick overlap

Latest panel date of the working cross-section, replicating
`current_signal_composite.main()`'s steps without calling it (it writes to the
main checkout): `working_panel.working_cross_section` → `seas_live.seas_asof`
→ `ICW.compute_composite_ic_weighted` with each 4-dp weight set →
`composite.pick_decile_volq`. Report shared names / share. The live-weight picks
are compared to the main checkout's `current_signal_composite.csv` only if its
meta `as_of` matches (that file is being redeployed; a mismatch there is not
this work's bug).

No p-value claims. No decision is made here; promotion is Gabe's call.

## 3. Proposed weights (derived from published t's; no new outcome read)

Code: `final/src/reweight/derive_weights.py` → `final/out/reweight/icw9_v2_weights.json`.

### 3.1 t's used

| factor | sign | t used | source |
|---|---|---|---|
| momentum_12_1 | +1 | +1.3898 | A |
| pct_from_high_252 | +1 | +2.0930 | A |
| volatility_60 | -1 | -2.9031 | A |
| gross_profitability | +1 | +6.0292 | A |
| accruals | -1 | -0.3946 | A |
| net_issuance_pct | -1 | -5.2453 | A |
| days_to_next_filing_seasonal | -1 | -4.2830 | A |
| short_interest_days_to_cover | -1 | -2.8937 | B (fit on hold-out) |
| seas | +1 | +2.8356 | A |

### 3.2 Weights

| factor | live icw9_seas | icw9_v2 | icw9_v2, SI at floor (B variant 4 only) |
|---|---|---|---|
| momentum_12_1 | +0.0402 | +0.0197 | +0.0217 |
| pct_from_high_252 | +0.0105 | +0.0553 | +0.0608 |
| volatility_60 | -0.0105 | -0.0962 | -0.1059 |
| gross_profitability | +0.4808 | +0.2544 | +0.2797 |
| accruals | -0.1314 | -0.0051 | -0.0056 |
| net_issuance_pct | -0.1129 | -0.2147 | -0.2361 |
| days_to_next_filing_seasonal | -0.0105 | -0.1660 | -0.1826 |
| short_interest_days_to_cover | -0.0105 | -0.0958 | -0.0056 |
| seas | +0.1928 | +0.0928 | +0.1021 |

### 3.3 Ready-to-paste constant block (NOT applied; Gabe's call)

```python
# WO-25 (Gabe 2026-09-29: "re derive on v2, fit on 2020-26"): same ICW rule
# w_k = sign_k*max(0.1,|t_k|-1)/sum, t's re-derived on v2 col c cap150 h=40:
# 8 factors on 2007-2019; short_interest_days_to_cover on 2020-01..2026-07-30
# (FIT ON THE HOLD-OUT, Gabe-approved; hold-out read #7). IN-SAMPLE for all 9.
# Doc: final/models/2026-09-29-icw-v2-reweight.md
MODEL_VERSION_V9_V2 = "ic_weighted_v2_2026-09-29"
PRODUCTION_WEIGHTS_V9_V2 = {
    "momentum_12_1": 0.0197,
    "pct_from_high_252": 0.0553,
    "volatility_60": -0.0962,
    "gross_profitability": 0.2544,
    "accruals": -0.0051,
    "net_issuance_pct": -0.2147,
    "days_to_next_filing_seasonal": -0.1660,
    "short_interest_days_to_cover": -0.0958,
    "seas": 0.0928,
}
```

## 4. Results

(Filled after the method commit.)
