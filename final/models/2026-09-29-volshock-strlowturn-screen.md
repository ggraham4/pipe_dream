# WO-28: `vol_shock` (28a) and `str_lowturn` (28b) nomination screens vs icw9_seas

Date: 2026-09-29/30. COO work order WO-28 (COO authority; approved in "COO
rulings on the literature review", COO.md 2026-09-29). Background: literature
review `final/models/2026-09-29-literature-feature-candidates.md`, rows 1 and 4.
Branch `worktree-agent-a79a9999a5df053aa`, based on `integration` 144b16c.
Code: `final/src/volshock/`. Outputs: `final/out/volshock/`.

Status: **PRE-REGISTERED.** This part is committed before any
candidate-vs-return number (IC, book, null) was computed for either trial.
Results are appended below the line at the end.

**In-era only.** Rebalance dates 2007-01-02..2019-12-31. Every loaded frame
(panel, outcome cache, sector, seas, io_gap, the WO-28 inputs) is filtered at
read time and asserted `date < 2020-01-01`; SEP month files are opened only if
the file stem is ≤ 2019-12 (asserted before the open). The 40-day labels of
late-2019 rows that run into early 2020 stay unmasked (Gabe 2026-09-25, as in
WO-13/18). No 2020+ read of any kind is part of this order.

## Hypotheses and trial counts

Two independent trials. Each is scored on its own gates; there is no
pick-the-better and no combined read.

**28a `vol_shock`, sign +1.** High-volume return premium: a stock whose
trading volume spikes relative to its own recent history gains visibility,
attracts new investors, and earns higher subsequent returns (Gervais, Kaniel &
Mingelgrin 2001, JF 56:877-919; Kaniel, Ozoguz & Starks 2012, JFE 103:255-279;
Wang 2021, JFE 140:325-345). **Family "volume-based signals", trial 2** (the
Amihud illiquidity screen was trial 1, null). Bar: pooled NW(39) rank-IC
**t ≥ +2.24**. COO spec fix: split-adjusted **share** volume (GKM's turnover
construct), not dollar volume, which would mix the stock's own price change
into the ranking.

**28b `str_lowturn`, sign −1 on r_1m.** Short-term reversal restricted to
low-turnover names: liquidity providers earn the reversal where turnover is
low, while high-turnover names show short-term momentum, so the unconditional
reversal nets to about zero (Medhat & Schmeling 2022, RFS; Jegadeesh 1990, JF;
Lehmann 1990, QJE). **Family "short-term reversal", trial 2** (trial 1 was
`momentum_1_1`, t −0.39, PREREGISTRATION trial ledger / physics doc §9.3;
Medhat-Schmeling predict exactly that unconditional null). Bar: pooled NW(39)
rank-IC **t ≤ −2.24**.

## Definitions (frozen)

Data: Sharadar SEP `data/sharadar/panel/stocks/2006-06..2019-12` (single pull
2026-09-09; SEP `close` and `volume` are split-adjusted on one common basis,
certified by Gate A1 below). Market calendar = SEP dates with ≥ 1,000 tickers
(3,420 days; 0 SEP rows fall off it). A window is **complete** only if the
ticker has a SEP row with finite volume on every market day in it; zero
volume counts as data (3.97% of SEP rows have zero volume).

**28a.** `V5(t)` = sum of SEP volume over the 5 market days ending t.
`vol_shock(t)` = average-ties rank (1..10) of `V5(t)` among the 10
non-overlapping windows `{V5(t − 5k), k = 0..9}` (the current one plus 9
prior). NaN unless all 50 market days t−49..t are complete. Composite input:
the usual cross-sectional `rank_z` of `vol_shock` per date. Sign +1. No daily,
window or lookback variants.

**28b.**
- `r_1m(t) = close[t] / close[t−21] − 1`, SEP split-adjusted close; t−21 is
  21 market days back and the ticker must have a row there.
- `turnover_21(t) = mean(volume[t−20..t]) / shares_adj(t)`, all 21 market
  days complete.
- **Shares source (named):** `shares_adj(t) = market_cap(t) / close(t)`, with
  `market_cap` from `composite_panel_v2` (Sharadar DAILY marketcap, USD, the
  same field that drives cap150 eligibility) and `close` = SEP close. The
  panel close equals the SEP close on all 13,253,466 panel rows (max relative
  difference 0.0, asserted). This puts shares on the same split-adjusted basis
  as SEP volume. Checked on AAPL 7:1 2014-06-09 and NFLX 7:1 2015-07-15:
  shares_adj ratio across the split 1.000 for both (Gate A2).
- **Valid** = finite `turnover_21` and finite `r_1m`. **Eligible** =
  `turnover_21` strictly below the date's median over valid cap150 rows. The
  median split is fixed and not tunable.
- **Value:** eligible rows get the `rank_z` of `r_1m` among the date's
  eligible rows (range −0.5..+0.5). Valid non-eligible rows get **exactly 0.0,
  the neutral mid-rank (signed rank 0), not NaN**, because
  `ic_weighted_composite` renormalises over present factors and a NaN would
  silently reweight the other factors by turnover. Invalid rows are NaN
  (ordinary missing data). This column is fed to the composite directly as the
  factor's signed-rank input; it is **not** re-ranked. Sign −1.
- No tercile, decile, window or threshold variants.

PIT: every input to (ticker, t) is dated ≤ t; the latest SEP row used is the
row at t itself (asserted on every finite row, Gate A6). close[t] and
volume[t] are known before the label's entry at open[t+1].

## Screen (frozen): v2 col c, cap150, h = 40

Universe: `downcap_v2_readout.load_column("c")`, `eligible_cap150`,
2007-01-02..2019-12-31, 9,756,141 rows, 6,508 tickers (2,987,605 added-ticker
rows), identical to WO-13/18/io_gap. Label `forward_return_tradable_40` =
close[t+40]/open[t+1] − 1.

**Harness:** `insider/screen_insider_v2grid.py` imported as a module (Book,
reconcile, fit_t, oos_score, shuffle_within_date). Its `ic_gates` and `gate6`
are replaced by WO-28's retargeted versions in `screen_volshock.py`.

**Gates, all 7 must pass, per trial** (sign s = +1 for 28a, −1 for 28b):
1. Pooled NW(39) Spearman rank-IC: s·t ≥ 2.24. The IC is computed on the full
   cap150 cross-section the composite sees; for 28b that includes the tied
   zeros of non-eligible rows.
2. **Both calendar halves, 2007-2013 and 2014-2019**: s·mean IC > 0 in each.
   (This differs from WO-13/18, which used odd/even years; odd/even is
   reported descriptively.)
3. Both-sides sector-demeaned IC (factor AND label demeaned within
   date × sector): s·t ≥ 1.0.
4. **0/40 grid-offset sign flips of the book increment**: for each of the 40
   grid offsets, (candidate + icw9_seas) excess minus icw9_seas excess, both
   the gate-6 books, must be > 0 in all 40. (This differs from WO-13/18,
   which counted flips of the daily-IC offset means; that count is reported
   descriptively.)
5. Year concentration: s·(summed daily IC) > 0 and the max single-year share
   of the summed daily IC ≤ 0.45 (LOYO t reported).
6. Book: **candidate + icw9_seas vs icw9_seas** (the LIVE Theoretical model:
   the 8 production factors + seas, not icw8), `decile_volq`, net 15bp, mean of
   40 grid offsets, excess vs SPY. Weights are split-half OOS on both sides
   (WO-18 method: the frozen rule `w_k = s_k·max(0.1, |t_k|−1)/Σ` fit on odd
   years scores even years and vice versa; the base refits its 9 weights the
   same way). PASS iff the real book is above the 80th percentile of a 20-draw
   within-date shuffle null (seeds 0..19; each draw permutes all finite
   candidate values within date, which for 28b moves both the eligibility
   pattern and the ranks, then refits the candidate weight per half) on the
   same base.
7. Gate A clean (below: A1-A6 all PASS).

**Descriptive only (never gated, cannot rescue a fail, not trials):**
- weight-matched null: the same 20 shuffles scored with the real per-half
  fitted candidate weights (no refit), per the io_gap floor-weight caveat;
- the increment over an icw10_io base (icw9_seas + io_gap, split-half OOS),
  no null;
- median cross-sectional Spearman of the candidate with r_5d, r_21d,
  momentum_12_1, io_gap, volatility_60, pct_from_high_252 and seas;
- daily-IC offset flips, odd/even halves, LOYO t;
- 28b: IC of r_1m on eligible rows only.

**Kill criteria.** Any gate fails → **DEAD**.
- 28a DEAD closes the volume-shock family: no daily-formation, window-length
  or dollar-volume variants.
- 28b DEAD closes the short-term reversal family at 2 trials: no tercile,
  decile, window or turnover-threshold variants.

**Success** = all 7 gates → **PASS-nomination** only. The next step would be
a separate unfitted 2020+ read work order that needs a fresh COO go-ahead.
Nothing enters live weights on this evidence.

**Iteration cap 3**, bug fixes only; no definition changes after this commit.

## Implementation

- `build_volshock.py`: SEP → `volshock_inputs_v2.parquet` (gitignored; vol_shock,
  V5, r_1m, vol21, turnover_21, r_5d, r_21d) + `build_volshock_meta.json`.
- `gate_a_volshock.py`: Gate A → `gate_a_volshock.json`.
- `screen_volshock.py --validate` → `validate_volshock.json` (no
  candidate-vs-return number); `--trial vol_shock|str_lowturn` →
  `<trial>_screen_report.json`.
- Borrowed read-only inputs (gitignored in their worktrees):
  - seas: `.claude/worktrees/agent-a790eb27c4530aa0a/final/out/seasonality/seas_factor_v2.parquet`,
    sha256 `8054af21…0e45` (identical to the WO-18 copy in agent-ad57ef9f; asserted at start);
  - io_gap: `.claude/worktrees/overnight-intraday/final/out/overnight/io_gap_factor_v2.parquet`.
- Python: `/opt/anaconda3/envs/pipe_dream/bin/python`.

**Input hashes** (re-checked at screen start):
- `composite_panel_v2.parquet` sha256 `30f636fd4802b4f13278322bc0c6e766a4623853edf15e92b60c2b672e97e0ff`
  (same as the io_gap screen). If the weekly refresh moves the full-file hash
  before the trial runs, the identity check is the hash of the sorted
  2007-2019 cap150 slice (ticker, date, label, 8 factors):
  `bc60e5d5654a404c37b9105e6d20b328289b8e1bd4ef4ead28218ab71b1e147d`.
- SEP 2006-06..2019-12 digest `3c323040c3da6beb1dca019de7c8f0d3b4f4ceb0e728a30784ff8706f6844df5`.
- `volshock_inputs_v2.parquet` sha256 `7c595da6bd697913d75d602852a69040e57a9b2c286ee014a0eb7784c224e2d8`.

## Validation (run before this commit; no candidate-vs-return number)

**Harness reconciliation: PASS (hard asserts).**

| check | harness | reference |
|---|---|---|
| icw8 decile_volq net 15bp, mean of 40 offsets | +0.028541633 | readout.json +0.028541633 |
| split-half OOS IC, fit odd → test even | 0.0404111057 | 0.0404111057 |
| split-half OOS IC, fit even → test odd | 0.0553979834 | 0.0553979834 |
| per-offset backtest copy, mean | = DR.backtest to 1e-12 | |
| icw9_seas frozen 4dp book | +0.0348652006 | WO-23 model_audit_wo23_A +0.0348652006 |
| frozen rule → PRODUCTION_WEIGHTS and PRODUCTION_WEIGHTS_V9_SEAS | 4dp exact | |
| retargeted gate fn on seas (sign +1, odd/even) vs V.ic_gates | identical | |
| seas pooled NW t | 2.83557806966033 | ICW.SEAS_T |
| io_gap pooled NW t | 3.99530887824343 | io_gap_screen_report.json |

Base book for gate 6 (no candidate): icw9_seas split-half OOS **+2.550%/yr**.

**Coverage** (cap150 col c, 2007-2019):

| factor | all | old grid | added | min year |
|---|---|---|---|---|
| vol_shock | 99.30% | 99.43% | 99.02% | 98.9% |
| str_lowturn (valid) | 99.67% | 99.72% | 99.57% | 99.5% |

- 28b: eligible share of valid rows 0.4999; every valid non-eligible row is
  exactly 0.0 (asserted); eligible value range [−0.5, +0.5]. Added tickers are
  38.8% of eligible rows vs 30.6% of valid rows (low turnover skews to added
  names).
- vol_shock value distribution: 12.1% at rank 1, 10.9% at rank 10, 9.2-10.2%
  at ranks 2-9, 0.2% half-ranks (ties). The U shape is expected from volume
  clustering.
- turnover_21 quantiles (daily): 1% 0.09%, 25% 0.43%, median 0.72%, 75% 1.19%,
  99% 5.1%.

**Gate A (gate 7): PASS** (`gate_a_volshock.json`).
- **A1 basis scan** over SEP 2006-06..2019-12: 3,543 day-over-day changes of
  k = close/closeunadj; 3,262 are split-like (closeunadj jumps, close
  continuous). A pull-basis break between month files would show as close
  jumping with closeunadj continuous on a month file's first day for many
  tickers at once. Found: 1 such event, CDSS 2008-12-01, a single non-panel
  ticker. PASS rule (fixed before any outcome read): no month-boundary
  mismatch on a panel ticker and no boundary day with more than one. 39
  mid-month "mismatch" events on single names, 5 of them panel tickers, are
  vendor or corporate events, not basis breaks: EXPE 2011-12-21 (1:2 reverse
  split plus TripAdvisor spin-off on the same day) and NRF 2014-06-30 (1:4
  reverse split plus NSAM spin-off). Both adjust volume correctly. ASTI,
  CHUC and NEOM are penny prints with no cap150 rows in the following 75 days.
- **A2 named splits:**

  | | split factor | shares_adj ratio | turnover_21 ratio on split day | V5 adjusted ratio (t+4 vs t−1) | V5 raw-volume ratio |
  |---|---|---|---|---|---|
  | AAPL 2014-06-09 | 7.0 | 1.000 | 1.012 | 0.71 | 4.97 |
  | NFLX 2015-07-15 | 7.0 | 1.000 | 1.026 | 1.50 | 10.49 |

  With raw unadjusted volume the 7× jump would put vol_shock at 10. With the
  adjusted volume AAPL's vol_shock runs 7, 8, 7, 6, 2, 1, ... from the split
  day. NFLX's 8-10 over its split week is real: NFLX reported Q2 earnings on
  2015-07-15, the split day, and its adjusted V5 rises 1.5×, not 7×.
- **A3 dead name:** LEHMQ has 184 cap150 rows in 2008 (last 2008-09-30),
  all with finite vol_shock, r_1m and turnover_21.
- **A4 label trace** (close[t+40]/open[t+1] − 1 from raw SEP rows, t+40 < 2020):
  AAPL 2014-06-02, LEHMQ 2008-06-16 and NFLX 2015-07-01 all match the panel
  label exactly (diff 0.0).
- **A5 hand check** (independent loop over raw month files): AAPL
  2014-06-13, LEHMQ 2008-06-16, NFLX 2015-07-24, MU 2012-03-15 and AAPL
  2019-12-31 match on vol_shock (exact), vol21 and r_1m (1e-9).
- **A6 PIT:** the last input date equals t on every finite row (0 violations).

---

## Results

(appended after the pre-registration commit)
