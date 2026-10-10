Pre-registration committed and pushed before any outcome statistic: `final/models/2026-10-09-iv-smirk.md`,
commit 3d35f75 on `wo56-iv-smirk`, sha256 `71517f642946b03027d8dd976fb567e7ede64dd1aabdd72d4eef892b0e95d0af`
(frozen 2026-10-09T16:36:09Z; copy in `~/.claude/pipe_dream-coordination/wrds-frozen-2026-10-09/`).
The screen asserts it at import on every mode; re-checked by hand after `--aggregate` (2026-10-10T18:18:55Z), unchanged.

# WO-56 results: OptionMetrics IV smirk (Xing-Zhang-Zhao 2010), v2 grid, nomination era

Dates: run 2026-10-09 (`--ic2000`, `--real`, `--null 100`), finished 2026-10-10 (`--recheck`,
`--aggregate` after a rate-limit stop; completed parts reused, nothing recomputed). Options family
trial 23 (29 incl. WO-36). Era 2007-01-02..2019-12-31 only; no 2020+ outcome read; nothing fitted on
the hold-out. Iteration cycles used: 0 of 3 (no fixes). Report: `final/out/wrds_optionm_smirk/smirk_report.json`.

## Verdict: **KILL**

Two registered gates fail (any failure = KILL):
- **Gate 1:** cap2000 pooled IC (sign −1) t = **−1.658**, i.e. SIGN·t = 1.66 < **3.0**.
- **Gate 5:** max single-year share **55.5% (2008)** > 45% (2007 adds 51.7%; 2007+2008 carry more than the whole
  13-year sum).

IV smirk is certified dead under the pre-reg; it reopens only with forward data. No variants
(other deltas, maturities, smirk changes, opprcd smirk, sign flip, cap150-gated IC).

## Reconciles (before any smirk number)

- icw9_seas base (`dropcheck.base_chain`): 0.0348652 vs ref 0.0348652; fast picker == picks_w on 3,272 dates.
- icw5_seas: 0.036442521084825354, exact vs WO-48b D4 ref.
- Factor sha256 `820c3f3a…a2b8` asserted. cap2000: 3,802,861 rows, 2,789 tickers, smirk finite 98.17%.
  cap150: 9,756,141 rows, finite 85.75%.

## Coverage (share of name-dates with a smirk)

| year | 2007 | 2008 | 2009 | 2010 | 2011 | 2012 | 2013 | 2014 | 2015 | 2016 | 2017 | 2018 | 2019 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| cap150 % | 69.4 | 76.2 | 83.7 | 82.1 | 85.4 | 88.6 | 89.9 | 88.6 | 89.2 | 93.0 | 90.8 | 89.4 | 89.1 |
| cap2000 % | 94.4 | 96.1 | 98.5 | 98.0 | 98.2 | 98.6 | 98.5 | 98.7 | 98.9 | 99.3 | 98.7 | 98.4 | 98.7 |

No cap150 year 2008-2019 is below 60%.

## Gates (cap2000 IC, label forward_return_tradable_40; bars for sign −1)

| gate | value | bar | pass |
|---|---|---|---|
| 1 pooled IC NW(39) t | mean −0.00882, t −1.658 | SIGN·t ≥ 3.0 | **FAIL** |
| D-NWT (reported) | null t sd 1.127 (100 within-date shuffles, mean −0.08); one-sided emp p 0.10 | — | — |
| 2 halves | odd −0.0111, even −0.0061 | both SIGN·mean > 0 | pass |
| 3 sector both-sides t | −1.290 (factor-only −0.468, not gated) | SIGN·t ≥ 1.0 | pass |
| 4 offset flips | 0/40 (offset means −0.0156..−0.0023) | 0 | pass |
| 5 LOYO | total ΣIC −28.87; max share 55.5% (2008); every LOYO t < 0 (−0.85..−2.83) | share ≤ 45% | **FAIL** |
| 6 momentum residual t | −2.172 (median Spearman with mom_12_1 +0.010) | SIGN·t ≥ 1.0 | pass |
| 7 book (cap150) | +0.170 pp/yr, 29/40 offsets > 0 | > null p80 (−0.212 pp) and ≥ 24/40 | pass |
| A integrity | placebo (seed 56000) t −0.79 fails g1; hand checks 6/6, brute force 0/100 + 0/100 | — | pass |

Year shares of the cap2000 IC sum: 2007 51.7%, 2008 55.5%, 2009 −40.1%, 2010 −12.1%, 2011 0.3%, 2012
−8.4%, 2013 4.0%, 2014 19.9%, 2015 10.5%, 2016 −21.7%, 2017 17.4%, 2018 −1.0%, 2019 24.0%. The signal
in large caps is a 2007-2008 (crisis) effect; 2009-2013 net zero or wrong-signed.

## Book (gate 7, cap150, decile_volq, net 15 bp, h = 40)

- w_smirk = −0.21826 (cap150 NW t −2.991, k 0.10965). icw5_seas +3.644 %/yr → icw6 +3.815 %/yr:
  **Δ +0.170 pp/yr, 29/40 offsets positive** (offset Δ −0.315..+0.673 pp; diff sd40 0.268 pp; base
  sd40 0.236 pp). Jackknife-by-year t 0.72; LOYO Δ +0.063..+0.275 pp (min when 2012 dropped);
  max year share 65.6% (2012). Post-2011-10 sub-period +0.337 pp, 31/40.
- Null (100 same-weight shuffles, seeds 56000..56099): p50 −0.252, p80 −0.212, p95 −0.176 pp; the
  real Δ beats all 100. Null draw 0 rerun bit-identical.
- Reading: the book gate passes, but its margin over the null is mostly that a shuffled factor at
  this weight costs ~0.25 pp (dilution); vs icw5 itself the gain is +0.17 pp, under one base sd40,
  jackknife t 0.72. It does not override the failed IC gates.

## Descriptive only (not gated): cap150 IC

cap150 pooled IC −0.00913, t −2.991 (below 3.0 in any case); sector both-sides t −3.23; 0/40 flips;
max year share 34.7% (2007); momentum residual t −3.16. The smirk effect is stronger in smaller
names than in cap2000, but the pre-registered IC universe was cap2000 and the cap150 t would also
miss the 3.0 bar. Not a rescue route.

## Files

Code `final/src/wrds_optionm_smirk/` (pull_vsurf, build_smirk, hand_check_smirk, screen_smirk,
probe_schema). Outputs `final/out/wrds_optionm_smirk/` (smirk_report.json, smirk_build.json,
smirk_integrity.json, parts/, logs/). Data (parquet, not committed):
`/Users/ggraham/pipe_dream/final/data/wrds/optionm/vsurf/vsurfd_2006..2019.parquet` + pull_meta_wo56.json.
