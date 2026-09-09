"""
Walk-forward, no-lookahead buy/no-buy probability scores for every distinct
options entry_date in the expanded-universe calls training table. Same
XGBoostClassifier hyperparams / 75th-percentile label / 40-trading-day
embargo as the production final/src/backtest.py, just evaluated at ~89
option-entry dates instead of the usual 8 annual timepoints.

Resumable by design (each call to this script processes as many remaining
dates as fit in a ~140s budget, then exits) -- the device bridge shell this
runs under does not keep background processes alive between tool calls, and
a single fit on the full ~6M-row panel takes ~15-20s, so the full ~89-date
sweep needs several separate invocations of this same script.
"""
import time
import gc
from pathlib import Path
import pandas as pd
import numpy as np
from xgboost import XGBClassifier

OUT_DIR = Path(__file__).resolve().parent
TIME_BUDGET_SEC = 120
FEATURE_COLS = ['daily_return','momentum_5','momentum_20','momentum_60','momentum_120',
                'volatility_20','volatility_60','volume_ratio_20','relative_strength_20',
                'pct_from_high_252','pct_from_low_252']
EMBARGO = 40
CUTOFF_PCTL = 75
TRAIN_CAP = 3500000  # memory cap for the 3.8GB device-bridge shell

t_start = time.time()

target_dates = pd.read_parquet(OUT_DIR / "options_calls_training_expanded_v2.parquet",
                                columns=["entry_date"])["entry_date"].drop_duplicates().sort_values()
target_dates = pd.to_datetime(target_dates).tolist()
print(f"{len(target_dates)} distinct entry dates need scoring", flush=True)

SCORES_DIR = OUT_DIR / "scores_by_date"
SCORES_DIR.mkdir(exist_ok=True)
done_dates = set(pd.to_datetime(pd.Timestamp(f.stem.replace("d_", "").replace("_", "-"))) for f in SCORES_DIR.glob("d_*.parquet"))
print(f"{len(done_dates)} dates already scored, resuming", flush=True)

remaining = [d for d in target_dates if pd.Timestamp(d) not in done_dates]
print(f"{len(remaining)} dates remaining", flush=True)
if not remaining:
    print("ALL DONE", flush=True)
    raise SystemExit(0)

cols = ['act_symbol', 'date'] + FEATURE_COLS + ['forward_return_40']
sf = pd.read_parquet(OUT_DIR / "expanded_stock_features.parquet", columns=cols)
sf["date"] = pd.to_datetime(sf["date"])
all_dates = sf["date"].drop_duplicates().sort_values().reset_index(drop=True)
sf_date_vals = sf["date"].to_numpy()
print(f"loaded sf panel {sf.shape} in {time.time()-t_start:.0f}s", flush=True)

results = []
n_done_this_run = 0
for entry_date in remaining:
    if time.time() - t_start > TIME_BUDGET_SEC:
        print(f"time budget reached, stopping after {n_done_this_run} dates this run", flush=True)
        break
    entry_date = pd.Timestamp(entry_date)
    # nearest trading day <= entry_date
    leq = all_dates[all_dates <= entry_date]
    if len(leq) < EMBARGO + 100:
        print(f"skip {entry_date.date()}: not enough history", flush=True)
        continue
    score_date = leq.iloc[-1]
    idx = all_dates[all_dates == score_date].index[0]
    cutoff_date = all_dates.iloc[idx - EMBARGO]

    idx = np.where(sf_date_vals <= np.datetime64(cutoff_date))[0]
    if len(idx) > TRAIN_CAP:
        rng = np.random.default_rng(42)
        idx = rng.choice(idx, size=TRAIN_CAP, replace=False)
        idx.sort()
    train = sf.iloc[idx].dropna(subset=FEATURE_COLS + ["forward_return_40"])
    if len(train) < 5000:
        print(f"skip {entry_date.date()}: only {len(train)} train rows", flush=True)
        continue
    X_train = train[FEATURE_COLS].to_numpy(dtype="float32")
    cutoff_val = np.percentile(train["forward_return_40"].to_numpy(), CUTOFF_PCTL)
    y_train = (train["forward_return_40"].to_numpy() > cutoff_val).astype("int8")
    del train
    gc.collect()

    model = XGBClassifier(n_estimators=100, max_depth=3, learning_rate=0.1,
                           eval_metric="logloss", verbosity=0, n_jobs=1, tree_method="hist")
    tfit = time.time()
    model.fit(X_train, y_train)
    del X_train, y_train
    gc.collect()

    test_rows = sf[sf["date"] == score_date].dropna(subset=FEATURE_COLS).copy()
    test_rows["buy_no_buy_proba"] = model.predict_proba(test_rows[FEATURE_COLS].to_numpy(dtype="float32"))[:, 1]
    test_rows["entry_date"] = entry_date
    test_rows["score_date"] = score_date
    out_one = test_rows[["act_symbol", "entry_date", "score_date", "buy_no_buy_proba"]]
    fname = f"d_{entry_date.strftime('%Y_%m_%d')}.parquet"
    out_one.to_parquet(SCORES_DIR / fname)
    n_done_this_run += 1
    print(f"  [{n_done_this_run}] {entry_date.date()} (scored @ {score_date.date()}) "
          f"fit {time.time()-tfit:.1f}s, total {time.time()-t_start:.0f}s, saved {fname}", flush=True)
    del model, test_rows, out_one
    gc.collect()

n_left = len(remaining) - n_done_this_run
print(f"{n_left} dates still remaining after this run "
      f"({len(list(SCORES_DIR.glob('d_*.parquet')))} files saved total)", flush=True)
