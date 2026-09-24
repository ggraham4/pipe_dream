# pipe_dream model dashboard

> **STATUS AS OF 2026-09-16 (Rounds 18–19) — READ FIRST.**
>
> The Stock tab now shows **two signals side by side**, plus SPY and USMV as
> reference lines.
>
> ```
> PRIMARY    q75    price_fund_h40_q75_trd_xgb_d3e01r100_expanding_cap500k_pit_s40
>                   binary top-quartile label, XGBClassifier -- the deployed model
> CANDIDATE  xrank  price_fund_h40_xrank_trd_xgb_reg_d3e01r100_expanding_cap500k_pit_s40
>                   within-date percentile-rank label, XGBRegressor -- TRACKED, NOT TRADED
>
> both:     24 features (price momentum + point-in-time SEC fundamentals)
>           depth 3, eta 0.1, 100 rounds, most recent 500,000 labelled rows
>           top 1 name from each of 5 trailing-volatility quintiles (5 total)
>           inverse-volatility weighted, entered at the next open
>           held to the 40-day horizon, NO stop-loss
> ```
>
> The two differ **only** in the training target. The candidate is on the page
> because Round 17b found the rank label flipped every feature family's
> model-level IC positive — and Round 18 then put it on the 2020-2026 hold-out,
> where it lost:
>
> ```
>              2007-2019 (in-sample)     2020-2026 (hold-out)
> q75          +8.71%/yr   2.796x SPY    +7.33%/yr   1.526x SPY
> xrank        +6.35%/yr   2.132x SPY    -4.28%/yr   0.771x SPY
> ```
>
> **Neither is a validated edge and neither is claimed to be one.** Read every
> number above against the noise band the app prints beside it: ten cells that
> differ from the deployed one only by a turned knob span **-8.01 to +9.15 %/yr
> excess, sd 5.03**. The deployed cell's +8.71 is 1.06 sd above its own family
> mean of +3.40.
>
> What the model demonstrably owns is a **low-volatility tilt** (score-vs-
> volatility correlation -0.134) plus a tech/healthcare sector bet — both
> purchasable as ETFs, which is why **USMV** is drawn on the backtest chart.
> Sources: `backtest/2026-09-12-xrank-fails-the-holdout-do-not-switch.md`,
> `models/2026-09-12-sector-bet-decomposition.md`,
> `backtest/2026-09-12-turnover-and-what-the-ranking-actually-buys.md`,
> `models/2026-09-11-deployed-best-case-config.md`.
>
> **REMOVED in Round 18:** the *Secondary Models (XGBoost / LSTM)* tab and every
> cross-check expander that pointed at it. Those models were trained on the
> pre-Round-11 universe, which was missing a third of the eligible 2008 names
> (89% of them since dead), so every number they produced is measured on data
> now known to be defective. Showing them beside point-in-time picks invited a
> comparison that was not valid in either direction. `src/current_signal.py` and
> `src/lstm_current_signal.py` still exist on disk; nothing in the app calls
> them.

An interactive local app for both models in this repo: the stock buy/no-buy
model (XGBoost on a point-in-time panel, `final/src/`) and the options premium
model (Tweedie GLM, calls only, `final/models/` + `app/lib/options_common.py`).

## Running it

```bash
conda activate pipe_dream        # or whatever env has xgboost/torch/sklearn already
pip install -r requirements.txt  # adds streamlit + yfinance on top of what's already there
cd final/app
streamlit run app.py
```

It opens in your browser at `http://localhost:8501`. Leave the terminal
running while you use it.

## What's in each tab

**Overview** — headline numbers for both models: point-in-time universe size,
as-of date, the deployed model's picks, the candidate's picks and today's
overlap, and the options backtest win rate.

**Stock Buy/No-Buy** (six tabs)
- *Today's Picks* — the deployed signal and the tracked candidate, side by
  side, each with its hold-out result under it. Both are produced by a single
  run of `src/current_signal_pit.py`, which loads the panel once and trains
  both models from the same training rows. Selection and weighting are
  **imported from `sweep.portfolio`** rather than reimplemented, so a live pick
  and a backtested pick cannot drift apart (DATA-PIPELINE-HANDOFF.md §6.4). The
  page also shows today's overlap between the two, with the caveat that matters:
  they share features, hyperparameters and construction, so their errors are
  correlated by design and agreement is not independent confirmation. Reads
  `out/current_signal_pit.csv`, `out/current_signal_pit_xrank.csv` and
  `out/current_signal_compare.json`. A "Retrain both signals" button reruns the
  whole point-in-time sequence in the background and streams the log.
- *Query a Ticker* — **(2026-09-24)** answers each ticker for **both** the
  blend (Today's Picks, cap2000) and the theoretical model (composite alone,
  cap150), one row per ticker, with a "Both models pick it" column. Blend
  statuses come from `out/current_signal_blend_full.csv` (PICK /
  ELIGIBLE_NOT_PICKED / ELIGIBLE_NOT_SCORED / INELIGIBLE_TODAY / NOT SCANNED).
  The theoretical model only writes a picks file, so a non-pick there is
  "NOT A PICK" with no reason; `lib/composite_model.py` picks up
  `out/current_signal_composite_full.csv` automatically if a model owner ever
  writes one (same schema as the blend's). The blend's `composite_score` is
  never reused for the theoretical model (different universe). Both files'
  `as_of_date` are shown, with a warning if they differ or are more than 5
  business days old. Below the lookup, an agreement panel (`lib/model_agreement.py`)
  counts both books, the overlap, Jaccard and weight overlap, splits
  theoretical-only picks into structural (outside the blend's universe) vs
  genuine disagreement, and lists the shared tickers. Descriptive only.
- *Sector Bets* — **new in Round 19.** What the model is actually betting on,
  at every level of the industry tree, because Round 13's finding that
  essentially *all* of this model's performance is a sector bet was not visible
  anywhere in the app until now.

  - **Active weight, not portfolio weight.** The book's weight in a group minus
    the *eligible universe's* weight in that group on the same date. A portfolio
    30% in technology when the universe is 28% technology is not a technology
    bet, it is the market. The universe is equal-weighted, because that is the
    benchmark the model's own construction-matched null uses.
  - **Six levels**, coarse to fine: `sector` (11) → `famaindustry` (48) →
    `sic2` (65) → `industry` (136) → `sic3` (210) → `sicindustry` (315). SIC
    rollups render as `"283 · Pharmaceutical Preparations"`, each named by the
    modal 4-digit industry among its members, derived from the data rather than
    hardcoded. The *statistics* stop at four levels — residualising 1,665 names
    on 314 dummies burns 19% of the degrees of freedom — but that objection is
    about **regression**, not **counting**. "Three of five picks are in
    Biotechnology" is a fact about the portfolio, not an estimate with a
    standard error, so the description goes deeper than the statistics do.
  - **"Is any of this more than chance?"** A hypergeometric enrichment test, the
    same one used for GO terms, matched to how the model actually draws: one
    name per volatility quintile, so a group's pick count is a sum of five
    *one-draw* hypergeometrics rather than one five-draw hypergeometric. Same
    expectation, different dispersion — and for a group concentrated in one
    quintile the flat version understates a real concentration by ~10–50×.
    Exact Poisson-binomial tails, no normal approximation, BH-corrected across
    every group at that level. Pooled over 124 windows / 620 draws: Healthcare
    and Energy clear q < 0.10 in **both** eras; Biotechnology does at
    `industry`. Industrials, Financials, Real Estate, Materials and Utilities
    are significantly *avoided*. The single-date test on today's five picks is
    also offered and is near-powerless by construction — a group needs 2 of the
    5 before BH can call anything — and the tab says so.
  - **"Where does a ticker sit?"** Any classified ticker's group at all six
    levels, beside how many eligible peers share it today and what the model did
    with that group across the 620 pooled draws. The gap between adjacent levels
    is the useful part: XOM is in Energy (74 picks vs 48.0 expected, q 6.6e-4)
    but in *Oil & Gas Integrated*, where the model has bought **0** against 1.63
    expected. The energy bet is E&P, not integrateds.
  - Sources: `models/2026-09-16-sector-enrichment-hypergeometric.md`,
    `models/2026-09-16-sector-hierarchy-and-the-bet-descriptor.md`.
  - Built by `src/build_sector_tilt.py` → `out/sector_tilt_history.json` and
    `src/build_sector_enrichment.py` → `out/sector_enrichment.json`. The tilt
    history predates the finer levels and carries four; the level selector on
    the standing-tilts panel is driven by what the file actually has, not by the
    display list. Rerun it to add the rest.

- *Query a Ticker* also gained the industry-classification expander described
  above, per looked-up ticker.

- *Model Weights* — one sub-tab per model: `feature_importances_` as a chart
  plus table, fundamentals features marked 🧾. Read as *what the trees split on*,
  not *what predicts returns*: Round 17 took a raw feature with t = +3.40 and
  watched it come out of this pipeline at t = -0.65.
- *Backtest & History* — window-by-window equity curves for both models against
  **SPY and USMV**, on both the 2007-2019 selection era and the 2020-2026
  hold-out, with the noise band printed above them. Built by
  `src/build_app_benchmarks.py` into `out/app_model_comparison.json`. Both sides
  are price returns: neither the model nor the benchmarks are credited with
  dividends, so SPY and USMV are each understated by roughly their ~1.8-1.9%/yr
  distribution yield.
- *Universe* — the point-in-time universe count at the top (what the models
  actually pick from, including delisted/acquired/bankrupt names that were
  genuinely investable at the time), then the plain current-universe price panel
  (`features.parquet`) that the sidebar and the ticker-history charts read.

**Options Premium** — same four-tab structure, calls only. Puts are shown in
*Model Weights* for transparency (their round-2 numbers never beat the
benchmark) but there's no puts "Today's Picks" — surfacing one would imply a
working model that doesn't exist yet. Live scoring fits the Tweedie GLM
fresh from `final/data/training/options_calls_training.parquet` each time
(sub-second, per the design doc) rather than trusting a pickled model
object, so it's never out of sync with the training data on disk.

**Data & Updates** — freshness timestamps for every key dataset, plus three
refresh actions (see below).

## The three refresh buttons

1. **Refresh stock price data + retrain both signals.** Runs
   `scripts/local_data_pull.py` (yfinance, your own network — this is why it
   has to run locally, not in any sandboxed shell), then the full point-in-time
   sequence: `sharadar_pull_pit_panel.py` → `build_pit_universe.py` →
   `build_features_sharadar.py` → `build_features_fundamentals_sharadar.py` →
   `export_sharadar_ohlc.py` → `current_signal_pit.py` → `build_app_benchmarks.py`.
   The Sector Bets tab additionally reads two artifacts that are **not** part of
   this sequence and are rebuilt by hand when the deployed cell changes:
   `src/build_sector_tilt.py` and `src/build_sector_enrichment.py`. Both read
   the score cache, not the live signal, so they go stale only when the cell id
   they hard-code is replaced.
   Can take several minutes. The same sequence without the price pull is the
   "Retrain" button on the Today's Picks tab; "Retrain ALL models" (button 0)
   is this plus a `features.py` rebuild for the sidebar and Universe tab.
   **`SHARADAR_API_KEY` must be exported in the shell that launches Streamlit**
   (jobs inherit Streamlit's environment). Since 2026-09-24 both this button and
   "Retrain ALL models" refuse to start, with an error, when it isn't set; the
   app never reads the key from a file.
   The last step needs network access **the first time it runs**, to pull USMV
   into `data/benchmarks/USMV.csv`. If it cannot reach the network the run still
   succeeds — the backtest chart is simply drawn without the USMV line and says
   why.

2. **Refresh today's live options chain.** Runs the new
   `scripts/pull_live_options_chain.py`, which pulls a same-day option chain
   via yfinance for the nearest ~30-day monthly expiration, for every ticker
   with local price history. Needed before "Today's Picks" on the Options
   tab reflects the current market rather than a stale snapshot.

3. **Update options historical data (DoltHub).** Best-effort. Runs the new
   `scripts/update_options_history.py`, which does `dolt pull` in the local
   clone at `pipe_dream/options_raw/` and pulls only NEW rows via `dolt sql`
   (much simpler than the original one-time export's byte-slicing workaround
   — that was only needed to get around the device-bridge shell's 45-second
   cap, which doesn't apply when you run this directly). Requires the `dolt`
   CLI and network access to dolthub.com from this machine. **Does not**
   rebuild `options_calls_training.parquet`/`options_puts_training.parquet`
   or `garch_volatility.parquet` — those are engineered tables (30-day-out
   entry selection, GARCH walk-forward refits, the below-intrinsic-value
   data-quality filter) that need their own rebuild pass. That pipeline is
   documented in `models/options-premium-model-design.md` but isn't yet
   consolidated into one script the way the stock side's `features.py` is —
   a reasonable next step if you want this fully automated end to end.

Each button runs its job as a real background process and polls a log file
— refreshing the page or navigating away doesn't stop it.

## Staying compatible with future changes

This app was built specifically so it keeps working as you add more data,
features, or tune hyperparameters, without needing its own code touched:

- **Stock model**: everything is read from `features.py`'s own constants
  (`FEATURE_COLS`, `FORWARD_WINDOW`, `TRADABLE_LABEL_COL`) and whatever
  `current_signal_pit.py` and `build_app_benchmarks.py` most recently wrote to
  `out/`. Add a feature column, change the horizon, retrain — the dashboard
  picks it up on next refresh (Streamlit's cache is keyed on each file's mtime;
  use the sidebar's "Clear cache & reload" if something looks stale).
- **Adding or promoting a signal**: the list of signals lives in ONE place per
  side — `VARIANTS` in `src/current_signal_pit.py` (training + output paths)
  mirrored by `VARIANTS` in `app/lib/pit_model.py` (display). Promoting the
  candidate to primary is a `role` change in both, not an app rewrite. The
  cell ids in `src/build_app_benchmarks.py` are deliberately hard-coded and
  should be edited only when a signal is genuinely replaced — see the header
  of that file for why it must not become a way to search the hold-out.
- **Options model**: hyperparameters (`TWEEDIE_POWER`, `TWEEDIE_ALPHA`) and
  the feature list (`FEATURES`) live as constants at the top of
  `app/lib/options_common.py`, sourced from `final/models/round2_results.json`.
  If you rerun a hyperparameter sweep, update those two constants there —
  the model is refit fresh from the training parquet on every dashboard
  load, so there's no stale pickled object to worry about.
- If you add a **third model** to this project entirely, it'll want its own
  `lib/<name>_model.py` following the same pattern (read source-of-truth
  constants + `out/`-style artifacts, don't duplicate modeling logic) and a
  new top-level tab in `app.py`.

## Known limitations / honesty notes

- **`cumulative_return` and `volume_20`, two of the 18 options-model
  features, are reconstructed.** `final/src/features.py` doesn't produce
  them (it has `volume_ratio_20`, a ratio, not `volume_20`, a raw rolling
  average; and no cumulative-return column at all) — they were verified
  present in `options_calls_training.parquet` from an earlier cloud-sandbox
  run. `app/lib/options_common.py::compute_extra_stock_features()`
  recomputes them directly from price history with a documented, verified
  (against AMP/AAPL rows) definition, but if you still have the original
  script that built the training table, prefer it over this reconstruction.
- **Puts are not offered as a scoreable model** — see Options → Model
  Weights for why (never beat the benchmark in round 2, and the
  below-intrinsic-value data-quality fix that landed after round 2 hasn't
  been rerun for puts).
- **Options data update (button 3) only refreshes the raw history**, not
  the engineered training tables or GARCH panel — see above.
- **The Sector Bets tab describes the bet; it does not validate it.** The
  enrichment test says *which* groups the model over-picks and with what
  confidence. It says nothing about whether those bets made money — Round 13
  established that sector-neutralising removes essentially all of the edge
  (2.7957× → 0.7719 against a null median of 0.7721, the exact centre). An
  enrichment test on the picks is a description of the portfolio, not an
  attribution of its returns.
- **The benchmark on that tab fails loudly, not quietly.** If
  `data/sharadar/pit_universe.parquet` is missing or has no row for the as-of
  date, every group would read 100% active weight against a universe weight of
  zero — a plausible-looking tab built on nothing. The tab now refuses to be
  read in that state and says which file is missing. That failure mode was live
  in the first version of the code.
- **IC is no longer a feature-admission gate anywhere in this project, and the
  Model Weights tab's caveat is now stronger than it reads.** Across all 64
  cells scored to 2026-09-16, the rank correlation between a cell's IC and what
  it earned is **+0.019** — the deployed model has IC +0.0020 while the highest
  IC in the set earns 1.49×. Split importance was already not a claim about
  returns; IC turns out not to be either. See `sweep/RUNBOOK.md` §9.
- **The stock model has no demonstrated edge, and the app says so on every
  relevant tab.** Round 12's pre-registered sweep of 1,152 configurations
  failed its acceptance criteria (Deflated Sharpe 0.746, Reality Check
  p = 0.61); Round 13 showed the fundamental signal is a sector bet; Rounds 15
  and 15b closed off breadth and horizon as levers. For calibration: in a
  synthetic grid containing no signal at all, 27% of configurations beat the
  market and the best reached 2.58x. A single config beating SPY is not
  evidence of anything.
- **The hold-out is spent.** 2020-2026 was used once in Round 13 to confirm
  the top-5 breadth choice and once in Round 18 to test the xrank label. The
  Backtest & History tab replots those results because they are already paid
  for — it cannot adjudicate anything new. `src/build_app_benchmarks.py`
  hard-codes its two cells for exactly this reason: there is nothing in it to
  select over. Anything nominated from here is confirmable only on data that
  does not exist yet.
- **Backtest returns are price-only on both sides.** The panel's prices are
  split-adjusted but not dividend-adjusted and `SPY.csv` is a raw price series,
  so neither the model's picks nor the benchmarks are credited with dividends.
  Excess figures are therefore roughly comparable but are **not** total returns.
- **The candidate is displayed, not followed.** Nothing in the app blends the
  two models' scores, and nothing should: `xrank` has already lost once
  out-of-sample. Overlap between them is close to a foregone conclusion given
  how much they share, and is not confirmation.
- **The 15% stop-loss price shown per name is guidance, not the model.** The
  deployed configuration holds to the 40-day horizon with no stop. Round 8's
  stop-loss sweep described a model this app no longer runs, and its tables
  were removed from the Backtest tab in Round 18 for that reason.
- Every backtest number here carries the caveats documented in this project's
  own docs; the dashboard surfaces them inline rather than hiding them.
