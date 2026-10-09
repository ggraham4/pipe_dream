Pre-registration hash-frozen (sha256 8dcc0296…49ca7, 2026-10-08T20:30:20Z), not committed, at the time these outcomes were computed.

# WO-53 results: IBES analyst EPS revisions (`rev3`, CJL 1996), v2 grid, nomination era

Date: 2026-10-08. Pre-registration: `final/models/2026-10-08-ibes-revisions.md`, full sha256
`8dcc029616866f70adde4f6aceac9df2f87bed596b050f4803792ee621149ca7`. The screen asserts it at
import, on every run mode. It was re-checked by hand before `--real` and again after
`--aggregate` (20:45:29Z), and was unchanged both times. Rules, gates, null and thresholds are exactly as frozen in that doc.
Family: analyst estimate revisions, trial 1, k = 1. Era 2007-01-02..2019-12-31 only. No 2020+
outcome was read and nothing was fitted on the hold-out.

## Verdict: **KILL**

Two registered gates fail:
- Gate 1: pooled IC t = +1.755, below the +2.0 bar.
- Gate 7: icw6 − icw5_seas = −0.300 pp/yr, with 1/40 offsets positive. That is below the null p80 and below 26/40.

Under the doc's own rule (any of 1–7 fails = KILL), the analyst-revisions family is certified
dead. It reopens only with forward data. No post-hoc variants: no REV6/REV1, FY2,
numup/numdown, median, dispersion, other scaling, or split-adjusted file.

## Reconciles (before any rev3 number)

- icw9_seas base (`dropcheck.base_chain`): 0.0348652006 vs ref 0.0348652. The fast picker
  equals `picks_w` on all 3,272 dates.
- icw5_seas: 0.036442521084825354 vs WO-48b D4 `arm_mean40` 0.036442521084825354. Exact, within the 1e-10 tolerance.
- Factor file sha256 `544cdda1…2865` asserted. Grid `composite_panel_v2.parquet` sha256
  `52f634ac…38ba` and WO-51 crosswalk `4db64e33…08c` were re-checked and unchanged.
- Universe: cap150 column c, 9,756,141 rows, 6,508 tickers, 3,272 dates
  (2007-01-03..2019-12-31). rev3 is finite on 86.17%.

## Gates

| # | Gate | Number | Bar | Pass |
|---|------|--------|-----|------|
| 1 | Pooled NW(39) Spearman IC t | **+1.755** (mean IC +0.01289, n 3,272) | t ≥ +2.0 | **FAIL** |
| 2 | Odd / even-year mean IC | odd +0.01857 (t 1.67), even +0.00628 (t 0.70) | both > 0 | pass |
| 3 | Both-sides sector-demeaned IC t | +1.961 (factor-only, not gated: +1.715) | ≥ +1.0 | pass |
| 4 | Grid-offset sign flips (40) | 0 flips; offset means +0.00887..+0.01736 | 0 | pass |
| 5 | LOYO: total IC sum > 0; max year share; min LOYO t | sum +42.19; max share **41.2% (2007)**; min LOYO t +1.10 (drop 2007) | > 0; ≤ 45%; > 0 | pass |
| 6 | Momentum-residual IC t (per-date OLS on momentum_12_1, intercept) | **+3.506** (median per-date Spearman with momentum_12_1 = +0.324) | ≥ +1.0 | pass |
| 7 | Book: paired icw6 − icw5_seas, decile_volq, net 15 bp, 40 offsets | **−0.300 pp/yr**, **1/40** offsets > 0 | > null p80 (−0.216 pp/yr) AND ≥ 26/40 | **FAIL** |
| A | Integrity: seed-53000 placebo fails gate 1; hand checks; 100-row brute force | placebo t −0.231; 5/5 hand checks match; 0/100 mismatches | all | pass |

Gate 7 detail:
- Weight rule: `w_rev = max(0.1, |1.755| − 1) · k`, with k = 0.109646, so w_rev = 0.08284. This is in-sample, as stated in the pre-reg. The five V5 weights are byte-exact, each asserted to 2e-4 against the t's in `ic_weighted_composite_report.json`.
- icw5_seas mean40 is +3.644%/yr and icw6 is +3.345%/yr. Base sd40 is 0.236 pp, reported but not the bar.
- Paired diff: sd40 0.127 pp, min −0.581 pp, max +0.008 pp. Jackknife t −1.01.
- Same-weight shuffle null, 100 draws, seeds 53000..53099:
  - p50 −0.245 pp/yr, p80 −0.216 pp/yr, p95 −0.193 pp/yr.
  - The real increment sits at the null's 9th percentile, so 91% of draws do better.
  - Null draw 0 rerun is bit-identical (−0.0019252410212129757 both times).

Notes:
- **Year shares** of the summed daily IC: 2007 41.2%, 2015 32.5%, 2014 23.6%, 2009 −42.9%,
  2016 −15.1%, 2018 −9.8%. LOYO t by dropped year ranges from 1.10 (drop 2007) to 3.19 (drop 2009).
- **Reading.** The IC is positive and stable across offsets. It survives sector demeaning and
  is not momentum in disguise: the residual t of 3.5 is larger than the raw t. But it misses
  the k = 1 bar. Added to icw5_seas at its rule weight, it lowers the book on 39 of 40 offsets
  and does worse than a same-weight random column. These notes are descriptive only and do not
  change the verdict.

## Code changes made for this run (not rule changes)

- `final/src/wrds_ibes/screen_rev3.py` never had a `git ls-files` guard. It only had a
  docstring "DO NOT RUN until that pre-registration is committed and pushed". That docstring
  was replaced with an import-time assert of the pre-reg sha256 against the frozen hash, plus a
  `WO53_HARNESS_SRC` env override for the harness path. The override defaults to
  `/tmp/wo53_src/final/src`.
- Harness source: a read-only `git archive origin/integration final/src final/out | tar -x -C
  /tmp/wo53_src`, integration @ `a2cbef56e97d84c92d7f001d737041cd375ef15f`. `final/out` was
  extracted as well, because the harness reads committed JSONs relative to its own tree:
  `stateint/state_interactions_report.json`, `pool/pool_hedge_read.json`,
  `seasonality/wo20_*.json` and `construction/*`. Data parquets are read by absolute path from the main
  checkout.
- `ICW_REPORT` is read from the main checkout's
  `final/out/reset2026/ic_weighted_composite_report.json`. The main checkout is on a different branch, but `scale_k` asserts every V5 weight against it to 2e-4, so this is guarded.
- On an integration base, run unchanged with
  `WO53_HARNESS_SRC=<repo>/final/src`.
- No fix-and-rerun cycles were needed (0 of 3 used).

## Runs (all under `caffeinate -i`, `/opt/anaconda3/envs/pipe_dream/bin/python`)

| Step | Wall time | Log |
|------|-----------|-----|
| `--real` | 117 s, peak RSS 6.9 GB | `final/out/wrds_ibes/logs/real.log` |
| `--null 100 --procs 3` | ~7.5 min | `logs/null.log` |
| `--recheck` | | `logs/recheck.log` |
| `--aggregate 100` | | `logs/aggregate.log` |

`--null` used 3 procs, not 4, because another WRDS job was running and memory was low.

Outputs:
- `final/out/wrds_ibes/rev3_report.json`
- `parts/real.json`, `parts/null/000..099.json`, `parts/null_recheck.json`

These are summary statistics only, with no raw IBES rows.
