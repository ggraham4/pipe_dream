# WO-59 results: 13F breadth change (`dbreadth`, Chen-Hong-Stein 2002): **KILL**

Date: 2026-10-10 (screen run); written up 2026-10-12. This doc gives the results for the pre-registration in
`final/models/2026-10-10-13f-breadth.md`.

**Freeze of the pre-reg**
- sha256 `02dbc86c0e01e976e798aa1489b250de3b90b2ed9a3fb4cac26b1504bcaede26`, committed and pushed as
  `0846537` on `origin/wo59-13f-breadth` before any outcome was computed.
- A copy is in `~/.claude/pipe_dream-coordination/wrds-frozen-2026-10-10/` (SHA256SUMS.txt, stamped
  2026-10-10T22:00:21Z).
- The screen asserts the pre-reg sha and the factor sha (`fb1d4dde…f11a`) at import and at load.

**Scope**
- Era 2007-01-02..2019-12-31 only. No 2020+ outcome was read.
- Iteration count: 0 bug-fix reruns of the screen. The integrity script needed one code fix (named-date
  lookup) before the freeze; it was factor-only and computed no outcome.
- Family "institutional ownership / 13F": trial 1 (k = 1).

## Verdict: KILL (gate 1 and gate 7 fail)

13F breadth change is **certified dead for the composite**. Per the pre-reg, it can reopen only with a new
pre-registered construction (for example ownership level, or the CHS long-short in small caps), counted as
trial 2.

| gate | number | bar | result |
|---|---|---|---|
| Reconcile | icw5_seas 0.036442521 = REF_V5 (1e-10); icw9_seas base OK | exact | OK |
| 1. Pooled NW(39) IC t | **+1.072** (mean IC +0.00743, 2,895 dates) | ≥ +2.0 | **FAIL** |
| 2. Odd / even halves | +0.00650 / +0.00849 | both > 0 | pass |
| 3. Sector-demeaned (both sides) t | +1.650 (factor-only +1.594, not gated) | ≥ +1.0 | pass |
| 4. Offset sign flips | 0 / 40 (offset mean IC +0.0036..+0.0107) | 0 | pass |
| 5. LOYO | total summed IC +21.50 > 0; max year share 37.7% (2007); min LOYO t +0.69 | > 0, ≤ 45%, > 0 | pass |
| 6. Momentum-residual IC t | +1.550 (median Spearman with mom_12_1 +0.343) | ≥ +1.0 | pass |
| 7. Book icw6 − icw5_seas | **−0.0165 pp/yr**, **19 / 40** offsets positive; null p80 −0.0206 pp | > null p80 **and** ≥ 26/40 | **FAIL** (beats p80, fails 26/40) |
| A. Integrity | placebo (seed 59000) t +0.307, fails g1; hand checks 4/4; brute force 0/100 mismatches; PIT and trap rules asserted | all | pass |

**Book details (gate 7)**
- w_dbreadth = 0.01096, from k = 0.10965 and the in-sample t = 1.072. Because t is close to 1, this is
  close to the floor weight.
- icw5_seas mean40 3.6443%/yr, icw6 3.6277%/yr. Base sd40 0.236 pp (reported, not the bar).
- Null: 100 draws, p50 −0.0330 pp, p95 −0.0109 pp. The real increment beats 88% of draws.
- The draw-0 rerun is bit-identical (−0.000330226…).
- Jackknife t of the paired diff: −0.17.

## Per-year IC next to per-year factor coverage (descriptive, not gated; COO request)

Summed daily IC per year (year share × total). cap150 coverage is the finite dbreadth share of cap150
name-dates under the SPAC rule. LOYO t is the pooled t with that year left out.

| year | summed IC | year share | cap150 coverage % | LOYO t |
|---|---|---|---|---|
| 2007 | +8.11 | +0.377 | 96.7 | 0.69 |
| 2008 | +4.04 | +0.188 | 98.0 | 0.89 |
| 2009 | **−20.97** | −0.975 | 98.8 | 2.96 |
| 2010 | +7.69 | +0.358 | 96.9 | 0.70 |
| 2011 | +1.74 | +0.081 | **48.4** | 0.99 |
| 2012 | +4.88 | +0.227 | 97.0 | 0.85 |
| 2013 | +5.34 | +0.248 | 95.9 | 0.81 |
| 2014 | +1.37 | +0.064 | 94.6 | 1.01 |
| 2015 | +7.09 | +0.330 | **63.4** | 0.75 |
| 2016 | −8.08 | −0.376 | 82.2 | 1.57 |
| 2017 | +4.75 | +0.221 | 96.1 | 0.84 |
| 2018 | +1.52 | +0.071 | **44.9** | 1.00 |
| 2019 | +4.01 | +0.187 | 90.8 | 0.91 |

**Reading the table**
- The IC is positive in 11 of 13 years. One year, 2009 (the momentum-crash rebound), wipes out most of the
  total. dbreadth's median Spearman with momentum_12_1 is +0.34, so it shares momentum's 2009 loss.
- Leaving 2009 out lifts the t to 2.96. **This is reported, not used.** Year exclusion is a post-hoc
  variant, and the pre-reg rules it out.
- The coverage dips in 2011, 2015 and 2018 come from the registered NaN quarters around the TR
  security-coverage gaps. Those years' IC contributions are small but positive.

**2017Q4 Thomson-Reuters regime break**
- From 2017Q4, TR's stale carry-forward rows (vintage fdate > rdate) disappear completely. Through 2017Q3
  they ran at about 115–360 managers per vintage.
- In the same quarter, raw first-vintage filers jump +14.6% (4,192 → 4,805).
- Distinct mapped cusips fall from 6,569 to 6,086, and 914 still-listed stocks with ≥ 10 holders at 2017Q3
  have 0 holders at 2017Q4.
- 2017Q4 is therefore flagged under the security-coverage trap rule, and the changes ending 2017Q4 and
  2018Q1 are NaN. That is why 2018 coverage is 44.9%.
- The manager-count rule (a drop of more than 10%) flagged no quarter. The largest drop was −1.9%.

## Overlap with the composite (descriptive)

Median per-date Spearman of dbreadth, cap150:

| factor | median Spearman |
|---|---|
| momentum_12_1 | +0.343 |
| net_issuance_pct | +0.102 |
| gross_profitability | −0.017 |
| accruals | −0.003 |
| seas | +0.007 |
| short_interest_days_to_cover | not computable: the column is 0% finite on cap150 2007–2019 (`corr_si.json`) |

The only material overlap is with momentum.

## Data and integrity summary

Details are in the pre-reg.
- **Mapping:** 99.82% of cap150 name-dates map to a permno. dbreadth is finite on 95.7% before the trap
  rules and on **84.7%** (cap2000-eligible 84.9%) after them. That is below the 85% target only because of
  the registered NaN quarters; it was reported, not tuned.
- **Manager counts:** 2,423 (2005Q4) → 5,495 (2019Q4), rising smoothly.
- **Named checks:**
  - AAPL 2015 holders: 2,313–2,412.
  - Lehman holders 608 → 429 → 0 across 2007–2008; dbreadth negative through 2008.
  - WaMu and Anadarko present until delisting.

## Files

- **Code** (`final/src/wrds_13f/`): `pull_13f.py`, `probe_*.py`, `build_dbreadth.py`,
  `integrity_dbreadth.py`, `screen_dbreadth.py`, `corr_si.py`.
- **Outputs** (`final/out/wrds_13f/`): `dbreadth_report.json`, `parts/real.json`, `parts/null/000..099.json`,
  `parts/null_recheck.json`, `dbreadth_build.json`, `dbreadth_integrity.json`, `manager_counts.csv`,
  `probe_cf.json`, `probe_vanish.json`, `corr_si.json`, and the logs.
- **Data** (parquet, gitignored, never committed): `/Users/ggraham/pipe_dream/final/data/wrds/tr_13f/`.
