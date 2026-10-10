# WO-50 results: industry momentum `ind_mom_12_1` — KILL

Written 2026-10-10. Pre-reg `final/models/2026-10-08-industry-momentum.md` (sha256 c686ad7e...cc16,
asserted by every script, untouched). Pre-outcome amendment
`final/models/2026-10-10-industry-momentum-amendment.md` (committed + pushed af37fa4 BEFORE any
outcome): the cap2000 population is a SUBSET of cap150 (tiers are mcap floors), so the literal
(ticker, date) join leaves 62% of cap150 rows without a value. Coverage 37.9% of cap150 rows
(median 1,148 of 3,008 names per date). In practice this tested industry momentum on the >= $2B
part of the cap150 book. Era 2007-01-02..2019-12-31 only; no hold-out read. Trial k=1, one run,
zero bug-fix iterations used on outcomes.

Code: `final/src/indmom/` (build_indmom.py, integrity_indmom.py, screen_indmom.py).
Outputs: `final/out/indmom/indmom_report.json`, `indmom_integrity.json`, `parts/`.

## Reconcile
icw5_seas base (WO-48b harness, D4): +0.036442521 vs ref 0.0364425 (|diff| 2.1e-8, tol 2e-4). OK.
icw9_seas harness reconcile +0.0348652 OK.

## Gates (cap150, h=40, NW(39) Spearman)

| # | gate | number | bar | result |
|---|---|---|---|---|
| 1 | pooled IC t | +0.183 (mean IC +0.0025, 3,272 dates) | >= +2.0 | FAIL |
| 2 | odd / even halves mean IC | +0.0129 / -0.0096 | both > 0 | FAIL |
| 3 | `ind_mom_resid` (on own momentum) IC t | -0.148 | >= +1.0 | FAIL |
| 4 | 40 offset IC means all > 0 | 12/40 non-positive (range -0.0042..+0.0104) | 0 non-positive | FAIL |
| 5 | max year share / LOYO min t | 2013 share 228% of total sum IC; LOYO min t -0.241 | <= 45%, > 0 | FAIL |
| 6 | icw6 - icw5_seas paired, net 15bp | -0.0060 pp/yr; 18/40 offsets > 0; null p80 -0.0065 pp/yr (real > 83% of null) | > p80 AND >= 26/40 | FAIL (offsets) |
| 7 | Gate A: PIT + rescale + holdout + placebo + hand-check | placebo t -0.596 (fails g1); integrity all pass | all | PASS |

icw6 weight: w_ind = +0.01084 (raw = max(0.1, |0.183|-1) = 0.1, the floor), W6 renormalised to sum|W5|.
Base sd40 (not the bar) 0.236 pp/yr. Null: 100 draws, seeds 50000-50099, draw 0 rerun identical.
Descriptive: sector both-sides demeaned IC t +0.52; median per-date Spearman(ind_mom, own momentum) 0.49.

## Verdict: KILL
Gates 1-6 all fail. Per the pre-reg: industry-momentum family closed; reopen only with point-in-time
historical industry labels. No post-hoc variants. Caveat for the COO: coverage was large caps
only (the literal spec); a coverage-widened version (population = cap150) would be a NEW trial
needing its own pre-registration, not a rerun of this one.
