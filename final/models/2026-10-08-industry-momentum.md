# WO-50: industry momentum (Moskowitz & Grinblatt 1999; Hou 2007)

Status: PRE-REGISTRATION DRAFT, written 2026-10-07 before any outcome
statistic (no factor IC, no icw6 book number has been computed). It becomes
frozen when the integrator commits and pushes it on branch `wo50-ind-mom`.
Section 2 (results) is appended only after that push.

Owner: Gabe. Commissioned by pipe-dream-coo as WO-50. New family, trial k=1.

## 1. Pre-registration

### 1.1 Hypothesis and mechanism
Industry-level returns over the past 6-12 months persist, because
industry-wide news diffuses slowly (Moskowitz-Grinblatt 1999: industry
momentum explains much of stock momentum; Hou 2007: intra-industry
lead-lag). The composite already holds stock-level `momentum_12_1`. The
question is whether the industry component adds anything beyond it.

### 1.2 Era, grid, label
- Era 2007-01-02..2019-12-31 ONLY. Code hard-asserts that no panel row, SEP
  bar, label or SPY return dated >= 2020-01-01 is loaded. No hold-out read.
- Grid: v2 survivorship-safe down-cap grid "column c"
  (`composite_panel_v2.parquet` + `outcome_cache_v2.parquet`, loaded through
  `model_audit_wo23.load_theo("A", "cap150")`, as in WO-46/WO-48/WO-48b).
- Test universe: cap150-eligible rows. Horizon h=40. Label
  `forward_return_tradable_40` (close[t+40]/open[t+1]); book uses
  `gross_return_40` from `outcome_cache_v2` as in the harness.

### 1.3 Data and the point-in-time caveat
- Prices: `momentum_12_1` from the panel (t-252..t-21 return, prices <= t).
- Industry labels: `composite_panel_v2` carries `sector` but no `industry`.
  `industry` (and `sector` for the fallback) comes from
  `final/data/sharadar/tickers_master.csv` (one row per ticker, `table ==
  stocks`, 20,965+ tickers), joined on `ticker`. Every cap2000 ticker on the
  2007-2019 grid (2,789) is found in it; panel `sector` agrees with
  tickers_master `sector` on 99.99% of rows; `industry` is missing on 0.01%
  of rows (those rows use `sector`; if `sector` is also missing they get no
  factor value).
- **Known look-ahead risk (stated, not fixed):** these labels are the
  vendor's CURRENT labels (frozen 2026-09-08 snapshot lineage, WO-17), not
  historical ones. A firm that changed industry is classified by its 2026
  label throughout 2007-2019. Reused tickers (WO-47) get the current owner's
  label on a predecessor's rows, since the join is on the symbol.
- Label-change share: no dated history of tickers_master exists before
  2026-09-08, so the share of names whose label changed over 2007-2019 is
  NOT AVAILABLE. Reported instead (descriptive only): between the two
  snapshots on disk (`tickers_master_through_2026-09-08.csv` vs
  `tickers_master.csv`, ~2.5 weeks apart), 0.73% of 20,965 common tickers
  changed `industry`.
- Mitigation (frozen): industry groups with < 5 members on a date fall back
  to `sector` (about 10.5% of cap2000 rows sit in industry groups < 5).

### 1.4 Factor (frozen)
`ind_mom_12_1` for stock i on date t:
1. Group population: ALL rows with `eligible_cap2000 == True` on the v2 grid
   on date t (not just cap150), with finite `momentum_12_1`, after the same
   SPAC filter `load_theo` applies.
2. Group key: Sharadar `industry`. If the industry group on t has fewer than
   5 members with finite `momentum_12_1`, the key becomes `sector` (the
   sector group is the full cap2000 sector population on t, finite
   momentum). If the sector group also has < 5 members, the factor is NaN.
3. Value: equal-weighted mean of the group members' `momentum_12_1`,
   INCLUDING stock i itself (the M-G industry portfolio).
4. Assigned to each cap150 row by (ticker, date). Sign +1. Single column,
   no window variants.

Registered secondary (report only, cannot PASS alone): `ind_mom_resid` =
per-date cross-sectional OLS residual of `ind_mom_12_1` on the stock's own
`momentum_12_1` (with intercept), fit on the cap150 rows of that date where
both are finite.

### 1.5 Base model and reconcile
Base = icw5_seas (`PRODUCTION_WEIGHTS_V5_SEAS`, live model as of
2026-10-07). Before anything else the base book is reconciled against the
WO-48b harness (`final/src/signcheck/dropcheck.py`, arm D4 == icw5_seas):
era-A 40-offset mean, decile_volq, net 15bp, vs SPY = 0.0364425
(+3.64%/yr; `dropcheck_report.json` eras.A.arms.D4.arm_mean40). Tolerance
±0.0002 (±0.02pp). If it does not reconcile: STOP and report.

### 1.6 icw6 weight (frozen formula, fixed before the t is seen)
Same frozen IC-shrinkage rule as icw9_seas: raw_k = sign_k * max(0.1,
|t_k| - 1). The five icw5_seas factors keep their icw9_seas raw magnitudes
(raw_k = W9_k * 0.1 / 0.0105, i.e. weights re-expressed in raw units where
the 0.1 floor maps to 0.0105). The new factor gets raw_new = +1 *
max(0.1, |t_ind| - 1), where t_ind is the gate-1 pooled NW(39) Spearman IC t
of `ind_mom_12_1` on 2007-2019 (sign +1 regardless of the observed sign,
per the frozen sign). icw6 weights = raw / sum(|raw|) * sum(|W5|) (same total
|w| as icw5_seas; ranks are scale-free). Composite = coverage-aware
weighted mean of rank-z (screen_insider.composite_score), as in the harness.

### 1.7 Gate stack (all must hold for PASS; verbatim from WO-50)
1. Pooled NW(39) Spearman IC t >= +2.0 (k=1), sign +.
2. Odd-year and even-year halves both right-signed (mean IC > 0).
3. SUBSTITUTED for this factor only (a both-sides sector-demeaned test would
   remove most of an industry factor by construction): the secondary column
   `ind_mom_resid` must have pooled NW(39) Spearman IC right-signed with
   t >= +1.0.
4. 0/40 grid-offset IC sign flips (IC mean on each of the 40 offset
   sub-grids, every 40th rebalance date, all > 0).
5. LOYO: no single year > 45% of the effect (sum of daily IC), and the
   leave-one-year-out minimum t right-signed (> 0).
6. Book: icw6 vs icw5_seas on decile_volq, net 15bp, PAIRED per offset.
   Mean paired increment (icw6 - icw5_seas, %/yr) > p80 of a 100-draw null
   where the `ind_mom_12_1` column is shuffled within date and given the
   SAME icw6 weight (not the floor weight), AND >= 26/40 offsets positive.
   Base sd40 is reported beside it but is not the bar (Gabe 2026-10-07,
   small-weight rule).
7. Gate A: (a) PIT assert (the factor on date t is recomputed from data <= t
   on a sample of rows; a fake x7 rescale of all prices after a cut date
   leaves every factor value on or before it unchanged; hold-out assert);
   (b) placebo: the factor shuffled within date (seed 50000) FAILS gate 1;
   (c) named hand-check: recompute the factor by hand for one named stock on
   each of three dates (an energy name mid-2014, a bank in 2009, a
   semiconductor in 2017) from the raw member list and their
   `momentum_12_1`, matching the pipeline to 1e-12.

Kill: any of gates 1-6 fails -> KILL. Industry-momentum family closed;
reopen only with point-in-time historical industry labels. No post-hoc
variants. Iteration cap: 3 bug-fix cycles, no spec changes. Null seeds:
50000 + draw.

### 1.8 Outputs
Code `final/src/indmom/`; small JSON outputs `final/out/indmom/`
(`indmom_report.json`, parts/). Every long command under `caffeinate -i`.

## 2. Results
(Not computed. Appended only after the pre-registration above is committed
and pushed.)
