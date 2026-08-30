# pipe_dream model dashboard

An interactive local app for both models in this repo: the stock buy/no-buy
classifier (XGBoost + LSTM, `final/src/`) and the options premium model
(Tweedie GLM, calls only, `final/models/` + `app/lib/options_common.py`).

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

**Overview** — headline numbers for both models: universe size, as-of date,
top picks preview, backtest win rate.

**Stock Buy/No-Buy**
- *Today's Picks* — reads `out/current_top10.csv` / `out/lstm_current_top10.csv`
  (whatever `current_signal.py` / `lstm_current_signal.py` last wrote). A
  "Retrain both models on latest data" button reruns those two scripts (plus
  `features.py` first) in the background and streams their log.
- *Query a Ticker* — look up any ticker(s), instantly, using the **currently
  saved** model checkpoints (`out/models/xgb_current_model.json`,
  `lstm_current_model.pt`) — no retraining. Shows probability, rank,
  percentile, and a BUY/NO BUY/MIXED verdict per model, same top-quartile
  rule `recommend.py` uses. If the saved model is older than your latest
  pulled data, you'll see a banner suggesting a retrain.
- *Model Weights* — XGBoost's `feature_importances_` as a chart + table, and
  the LSTM's architecture/training config (it doesn't have a simple
  per-feature weight table the way a tree model does).
- *Backtest & History* — the 8-timepoint walk-forward backtest tables, AUC/MCC
  by timepoint, the horizon sweep (10/20/40/60 days), and the equity chart.
- *Universe* — ticker count, date range, forward-return horizon, feature
  list — all read live from `features.parquet`, not hardcoded.

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

1. **Refresh stock price data + retrain both models.** Runs
   `scripts/local_data_pull.py` (yfinance, your own network — this is why it
   has to run locally, not in any sandboxed shell), then `features.py`,
   `current_signal.py`, `lstm_current_signal.py` in sequence. Can take
   several minutes across the full ~1,620-ticker universe.

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
  (`FEATURE_COLS`, `FORWARD_WINDOW`, `LABEL_COL`) and whatever
  `current_signal.py`/`lstm_current_signal.py`/`backtest.py`/
  `horizon_sweep.py` most recently wrote to `out/`. Add a feature column,
  change the horizon, retrain — the dashboard picks it up on next refresh
  (Streamlit's cache is keyed on each file's mtime; use the sidebar's
  "Clear cache & reload" if something looks stale).
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
- **The LSTM has no per-feature weight table** — it's a sequence model. A
  permutation-importance or integrated-gradients pass would give an
  analogous breakdown; not built here.
- Every backtest number here carries the same caveats already documented in
  this project's own docs: small samples (6-8 timepoints), no transaction
  costs, survivorship bias from applying the current universe retroactively.
  The dashboard surfaces these captions inline rather than hiding them.
