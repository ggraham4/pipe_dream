"""
Walk-forward LSTM buy/no-buy backtest, built to be directly comparable to
backtest.py (XGBoost): same 8 timepoints, same strict embargo (train only on
rows whose OWN forward-return label resolves at or before the train cutoff),
same 75th-percentile label cutoff computed from the training set only, same
top-N-of-5 $10k simulation vs SPY.

This explicitly fixes the leakage flaw flagged in the project's own prior
LSTM script (build_train_test_tensor.py's test_interval=5 interleaved split,
which put training and test examples right next to each other in time --
not a genuine holdout of the future). Here, every training sequence's label
resolves strictly before the embargoed cutoff, exactly like the XGBoost
backtest.

Architecture reuses the BuySignalLSTM design from the repo's own
src/lstm_model.py (single-direction LSTM -> last hidden state -> linear ->
BCEWithLogitsLoss), extended with feature standardization (fit on training
data only) and early stopping on a held-out validation slice of the training
window.

Given CPU-only compute in this environment, each walk-forward retrain
subsamples its training set (RNG-seeded, capped) rather than using the full
multi-million-row history every time -- called out explicitly in the output
so this is a visible, documented tradeoff, not a silent shortcut.
"""
import json
import time

import numpy as np
import pandas as pd
import torch
import torch.nn as nn
from sklearn.metrics import roc_auc_score, matthews_corrcoef

from features import FEATURE_COLS, FORWARD_WINDOW, LABEL_COL, DATA_DIR, OUT_DIR

SEQ_LEN = 20  # trading days of TRAILING feature-history input per example --
               # independent of FORWARD_WINDOW (the forward-looking prediction
               # target); unchanged when FORWARD_WINDOW changes.
CUTOFF_PERCENTILE = 75
TOP_N = 5
TRAIN_CAP = 150000         # max training sequences per walk-forward retrain --
                           # raised from 40,000 on 2026-08-27 per Gabe's request
                           # to test whether the LSTM's stagnant-looking results
                           # were a symptom of the sample cap never growing with
                           # the training pool (which reached ~5.8M sequences by
                           # the last timepoint while training still only ever
                           # saw 40k of it, well under 1%). Matches the cap the
                           # one-off production LSTM scripts (lstm_current_
                           # signal.py, score_watchlist.py, query_day.py) have
                           # used all along -- this just brings the 8x-repeated
                           # walk-forward backtest in line with them.
VAL_FRACTION = 0.1
HIDDEN_SIZE = 32
NUM_LAYERS = 1
DROPOUT = 0.0
LEARNING_RATE = 1e-3
BATCH_SIZE = 256
MAX_EPOCHS = 12
PATIENCE = 3
SEED = 42

TIMEPOINTS = [
    "2013-01-02", "2015-01-02", "2017-01-03", "2019-01-02",
    "2021-01-04", "2023-01-03", "2025-01-02", "2026-06-01",
]


class BuySignalLSTM(nn.Module):
    def __init__(self, num_features, hidden_size=32, num_layers=1, dropout=0.0):
        super().__init__()
        self.lstm = nn.LSTM(
            input_size=num_features,
            hidden_size=hidden_size,
            num_layers=num_layers,
            batch_first=True,
            dropout=dropout if num_layers > 1 else 0.0,
        )
        self.output_layer = nn.Linear(hidden_size, 1)

    def forward(self, x):
        lstm_out, (hidden, cell) = self.lstm(x)
        last_hidden = hidden[-1]
        return self.output_layer(last_hidden).squeeze(-1)


def nearest_trading_date(target, available_dates):
    target = pd.Timestamp(target)
    candidates = available_dates[available_dates <= target]
    return candidates.max() if len(candidates) else None


class SequenceIndex:
    """
    Memory-safe replacement for materializing every ticker's full sliding-
    window sequence array up front. At S&P-500 scale (~500 tickers) building
    one big (n_sequences, SEQ_LEN, n_features) array via np.concatenate was
    fine (~1-2GB). At the expanded ~1,620-ticker universe that array is
    ~5GB+ on its own, and np.concatenate's peak (source + destination both
    resident) pushed the walk-forward backtest past this box's ~8GB and got
    OOM-killed (exit 137) with no traceback -- just a silent stop after the
    "Building sliding-window sequences..." log line.

    Fix: keep only a lightweight per-row index (ticker id, row offset, date,
    label -- ~24 bytes/row, ~150MB total) plus each ticker's own (N, 11)
    feature array (no windowing yet). Actual (SEQ_LEN, 11) windows are
    sliced out on demand, only for the handful of rows a given step
    actually needs (a day's cross-section to score, or a TRAIN_CAP-sized
    random training sample) -- never all ~6M sequences at once.
    """

    def __init__(self, feat: pd.DataFrame):
        self.tickers = []
        self._vals_by_ticker = []

        tid_chunks, row_chunks, date_chunks, label_chunks = [], [], [], []

        for ticker, g in feat.groupby("ticker", sort=False):
            g = g.sort_values("date").dropna(subset=FEATURE_COLS)
            if len(g) < SEQ_LEN:
                continue
            tid = len(self.tickers)
            self.tickers.append(ticker)
            self._vals_by_ticker.append(g[FEATURE_COLS].to_numpy(dtype=np.float32))

            end_idx = np.arange(SEQ_LEN - 1, len(g), dtype=np.int32)
            tid_chunks.append(np.full(len(end_idx), tid, dtype=np.int32))
            row_chunks.append(end_idx)
            date_chunks.append(g["date"].to_numpy()[end_idx])
            label_chunks.append(g[LABEL_COL].to_numpy(dtype=np.float64)[end_idx])

        self.ticker_id = np.concatenate(tid_chunks)
        self.row_idx = np.concatenate(row_chunks)
        self.dates = np.concatenate(date_chunks)
        self.labels = np.concatenate(label_chunks)

    def __len__(self):
        return len(self.dates)

    def sequences_for(self, pool_idx):
        """Slice out (SEQ_LEN, n_features) windows for the given positions
        into the flat index (self.ticker_id/row_idx/dates/labels arrays)."""
        n_features = self._vals_by_ticker[0].shape[1]
        out = np.empty((len(pool_idx), SEQ_LEN, n_features), dtype=np.float32)
        tids = self.ticker_id[pool_idx]
        ridx = self.row_idx[pool_idx]
        for i in range(len(pool_idx)):
            vals = self._vals_by_ticker[tids[i]]
            r = ridx[i]
            out[i] = vals[r - SEQ_LEN + 1: r + 1]
        return out

    def tickers_for(self, pool_idx):
        tids = self.ticker_id[pool_idx]
        return np.array([self.tickers[t] for t in tids], dtype=object)


def train_lstm(X_train, y_train, rng, num_features):
    n = len(X_train)
    idx = rng.permutation(n)
    n_val = max(1, int(n * VAL_FRACTION))
    val_idx, tr_idx = idx[:n_val], idx[n_val:]

    Xtr = torch.tensor(X_train[tr_idx], dtype=torch.float32)
    ytr = torch.tensor(y_train[tr_idx], dtype=torch.float32)
    Xval = torch.tensor(X_train[val_idx], dtype=torch.float32)
    yval = torch.tensor(y_train[val_idx], dtype=torch.float32)

    model = BuySignalLSTM(num_features, HIDDEN_SIZE, NUM_LAYERS, DROPOUT)
    optimizer = torch.optim.Adam(model.parameters(), lr=LEARNING_RATE)
    loss_fn = nn.BCEWithLogitsLoss()

    best_val, best_state, best_epoch, stall = float("inf"), None, 0, 0
    n_train = len(Xtr)
    for epoch in range(MAX_EPOCHS):
        model.train()
        perm = torch.randperm(n_train)
        for start in range(0, n_train, BATCH_SIZE):
            batch_idx = perm[start:start + BATCH_SIZE]
            optimizer.zero_grad()
            logits = model(Xtr[batch_idx])
            loss = loss_fn(logits, ytr[batch_idx])
            loss.backward()
            optimizer.step()

        model.eval()
        with torch.no_grad():
            val_loss = loss_fn(model(Xval), yval).item()
        if val_loss < best_val:
            best_val, best_epoch, stall = val_loss, epoch + 1, 0
            best_state = {k: v.clone() for k, v in model.state_dict().items()}
        else:
            stall += 1
            if stall >= PATIENCE:
                break

    model.load_state_dict(best_state)
    model.eval()
    return model, best_epoch, best_val


def run_lstm_backtest():
    feat = pd.read_parquet(OUT_DIR / "features.parquet")
    feat = feat.sort_values(["ticker", "date"]).reset_index(drop=True)

    spy = pd.read_csv(DATA_DIR / "SPY.csv", parse_dates=["date"]).sort_values("date").reset_index(drop=True)
    spy["spy_fwd_return"] = spy["close"].shift(-FORWARD_WINDOW) / spy["close"] - 1

    all_dates = feat["date"].drop_duplicates().sort_values().reset_index(drop=True)
    embargo_days = FORWARD_WINDOW

    print("Indexing sliding-window sequences for all tickers (memory-safe, on-demand slicing)...")
    t0 = time.time()
    idx_store = SequenceIndex(feat)
    print(f"  {len(idx_store)} sequences indexed across {len(idx_store.tickers)} tickers, "
          f"in {time.time()-t0:.1f}s")

    rng = np.random.default_rng(SEED)
    results, picks_log, metrics_log = [], [], []

    for tp_str in TIMEPOINTS:
        tp = nearest_trading_date(tp_str, all_dates)
        if tp is None:
            print(f"skip {tp_str}: no trading date found")
            continue
        idx = all_dates[all_dates == tp].index[0]
        if idx < embargo_days:
            print(f"skip {tp_str}: not enough history for embargo")
            continue
        train_cutoff_date = all_dates.iloc[idx - embargo_days]

        train_mask = (idx_store.dates <= np.datetime64(train_cutoff_date)) & ~np.isnan(idx_store.labels)
        n_avail = train_mask.sum()
        if n_avail < 500:
            print(f"skip {tp_str}: only {n_avail} training sequences")
            continue

        train_idx_pool = np.where(train_mask)[0]
        if len(train_idx_pool) > TRAIN_CAP:
            train_idx_pool = rng.choice(train_idx_pool, size=TRAIN_CAP, replace=False)

        X_train_raw = idx_store.sequences_for(train_idx_pool)
        y_train_raw = idx_store.labels[train_idx_pool]

        cutoff_val = np.percentile(y_train_raw, CUTOFF_PERCENTILE)
        y_train = (y_train_raw > cutoff_val).astype(np.float32)

        # standardize using TRAIN stats only (per-feature, across time steps)
        mean = X_train_raw.reshape(-1, X_train_raw.shape[-1]).mean(axis=0)
        std = X_train_raw.reshape(-1, X_train_raw.shape[-1]).std(axis=0)
        std[std == 0] = 1.0
        X_train = (X_train_raw - mean) / std

        t0 = time.time()
        model, best_epoch, best_val = train_lstm(X_train, y_train, rng, X_train.shape[-1])
        train_secs = time.time() - t0

        test_mask = idx_store.dates == np.datetime64(tp)
        test_idx = np.where(test_mask)[0]
        if len(test_idx) == 0:
            print(f"skip {tp_str}: no scoreable sequences at {tp.date()}")
            continue
        X_test = (idx_store.sequences_for(test_idx) - mean) / std
        y_test_label = idx_store.labels[test_idx]
        test_tickers = idx_store.tickers_for(test_idx)

        with torch.no_grad():
            test_probs = torch.sigmoid(model(torch.tensor(X_test, dtype=torch.float32))).numpy()

        eval_mask = ~np.isnan(y_test_label)
        if eval_mask.sum() > 10 and len(np.unique(y_test_label[eval_mask] > cutoff_val)) > 1:
            y_eval = (y_test_label[eval_mask] > cutoff_val).astype(int)
            auc = roc_auc_score(y_eval, test_probs[eval_mask])
            preds = (test_probs[eval_mask] > 0.5).astype(int)
            mcc = matthews_corrcoef(y_eval, preds) if len(np.unique(preds)) > 1 else float("nan")
        else:
            auc, mcc = float("nan"), float("nan")

        metrics_log.append({
            "timepoint": str(tp.date()),
            "train_sequences": int(len(train_idx_pool)),
            "train_pool_available": int(n_avail),
            "train_cutoff_date": str(train_cutoff_date.date()),
            "label_cutoff_return": round(float(cutoff_val), 4),
            "best_epoch": best_epoch,
            "best_val_loss": round(float(best_val), 4),
            "train_seconds": round(train_secs, 1),
            "n_scored": int(len(test_idx)),
            "auc": round(float(auc), 4) if auc == auc else None,
            "mcc": round(float(mcc), 4) if mcc == mcc else None,
        })
        print(f"{tp_str}: trained on {len(train_idx_pool)} seqs in {train_secs:.1f}s "
              f"(best_epoch={best_epoch}), AUC={metrics_log[-1]['auc']}")

        order = np.argsort(-test_probs)
        realized_mask = ~np.isnan(y_test_label)
        top_idx = [i for i in order if realized_mask[i]][:TOP_N]
        if not top_idx:
            print(f"skip {tp_str}: no picks with realized forward return yet")
            continue

        n_realized = len(top_idx)
        per_stock = 10000 / n_realized
        picked_returns = y_test_label[top_idx]
        ending_value = float((per_stock * (1 + picked_returns)).sum())
        portfolio_return = ending_value / 10000 - 1

        spy_row = spy[spy["date"] == tp]
        if spy_row.empty or spy_row["spy_fwd_return"].isna().all():
            spy_return, spy_ending = None, None
        else:
            spy_return = float(spy_row["spy_fwd_return"].iloc[0])
            spy_ending = 10000 * (1 + spy_return)

        universe_return = float(np.nanmean(y_test_label))

        results.append({
            "timepoint": str(tp.date()),
            "exit_date_approx_trading_days": FORWARD_WINDOW,
            "picks": [str(test_tickers[i]) for i in top_idx],
            "pick_probs": [round(float(test_probs[i]), 3) for i in top_idx],
            "starting_value": 10000,
            "ending_value_model": round(ending_value, 2),
            "model_return_pct": round(portfolio_return * 100, 2),
            "ending_value_spy": round(float(spy_ending), 2) if spy_ending else None,
            "spy_return_pct": round(float(spy_return) * 100, 2) if spy_return is not None else None,
            "universe_avg_return_pct": round(universe_return * 100, 2),
            "beat_spy": bool(spy_return is not None and portfolio_return > spy_return),
        })
        for i in top_idx:
            picks_log.append({
                "timepoint": str(tp.date()), "ticker": str(test_tickers[i]),
                "buy_proba": round(float(test_probs[i]), 3),
                "realized_fwd_return_pct": round(float(y_test_label[i]) * 100, 2),
            })

    return results, metrics_log, picks_log


if __name__ == "__main__":
    torch.manual_seed(SEED)
    results, metrics_log, picks_log = run_lstm_backtest()

    with open(OUT_DIR / "lstm_backtest_results.json", "w") as f:
        json.dump(results, f, indent=2)
    with open(OUT_DIR / "lstm_backtest_metrics.json", "w") as f:
        json.dump(metrics_log, f, indent=2)
    pd.DataFrame(picks_log).to_csv(OUT_DIR / "lstm_backtest_picks.csv", index=False)

    print(f"\n{'timepoint':<12}{'model %':>10}{'SPY %':>10}{'univ avg %':>12}{'beat SPY':>10}")
    for r in results:
        print(f"{r['timepoint']:<12}{r['model_return_pct']:>10.2f}{r['spy_return_pct']:>10.2f}"
              f"{r['universe_avg_return_pct']:>12.2f}{str(r['beat_spy']):>10}")

    n = len(results)
    wins = sum(r["beat_spy"] for r in results)
    avg_model = np.mean([r["model_return_pct"] for r in results])
    avg_spy = np.mean([r["spy_return_pct"] for r in results])
    print(f"\nWin rate vs SPY: {wins}/{n}")
    print(f"Avg model return per trial: {avg_model:.2f}%")
    print(f"Avg SPY return per trial:   {avg_spy:.2f}%")
