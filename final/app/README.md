# pipe_dream model dashboard

> **STATUS AS OF 2026-09-16 (Round 18) — READ FIRST.**
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

**Stock Buy/No-Buy** (five tabs)
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
- *Query a Ticker* — scores any ticker(s) against **both** saved checkpoints
  (`out/models/xgb_pit_augmented_model.json` and
  `out/models/xgb_pit_xrank_model.json`), no retraining. Shows score, rank and a
  BUY / NO BUY / INELIGIBLE verdict per model, and calls out where the two
  disagree. **INELIGIBLE** means the name is not in today's point-in-time
  universe, so it is not pickable regardless of what the model thinks. **BUY**
  means top quartile among eligible names — a lower bar than being one of the
  five allocated positions. If a saved model is older than the panel on disk,
  a banner suggests a retrain.
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
   Can take several minutes. The same sequence without the price pull is the
   "Retrain" button on the Today's Picks tab; "Retrain ALL models" (button 0)
   is this plus a `features.py` rebuild for the sidebar and Universe tab.
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
