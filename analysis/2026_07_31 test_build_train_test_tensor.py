"""
Test script for buildTrainTestTensor (labels version).

Run this after your normal src/data_loading.py setup is loaded.
This does NOT check whether the model can predict anything, it only checks
that the function is producing structurally correct output: right shapes,
right ordering, no leakage between train/test stats, labels aligned with
their matrices, etc.

Start with a small, cheap ticker list before scaling up to the full S&P 500,
this will be slow and hit yfinance a lot on a big universe.
"""

import numpy as np
from src.data_loading import buildTrainTestTensor

# ---- small, cheap test run ----
TEST_TICKERS = ['AAPL', 'MSFT', 'MMM', 'JNJ', 'KO']

result = buildTrainTestTensor(
    Tickers=TEST_TICKERS,
    start_date='2018-01-01',
    end_date='2023-01-01',
    test_interval=5,
    matrix_length=20,
)

print("=" * 60)
print("SHAPE CHECKS")
print("=" * 60)
print(f"train_tensor shape:   {result.train_tensor.shape}")
print(f"train_labels shape:   {result.train_labels.shape}")
print(f"test_tensor shape:    {result.test_tensor.shape}")
print(f"test_labels shape:    {result.test_labels.shape}")
print(f"num features expected: {len(result.feature_columns)}")
print(f"feature_columns:      {result.feature_columns}")

assert result.train_tensor.shape[1:] == result.test_tensor.shape[1:], \
    "train/test tensors disagree on (time_steps, num_features)"
assert result.train_tensor.shape[1] == 20, "matrix_length mismatch"
assert result.train_tensor.shape[2] == len(result.feature_columns), \
    "feature axis doesn't match feature_columns length"

# labels must be one scalar per matrix, not per time step
assert result.train_labels.ndim == 1, "train_labels should be 1-D (one label per matrix)"
assert result.test_labels.ndim == 1, "test_labels should be 1-D (one label per matrix)"
print("PASS: tensor shapes are consistent, labels are 1-D\n")

print("=" * 60)
print("TENSOR / LABEL / KEY ALIGNMENT CHECKS")
print("=" * 60)
print(f"train_tensor examples: {result.train_tensor.shape[0]}, train_labels: {len(result.train_labels)}, train_ticker_key: {len(result.train_ticker_key)}")
print(f"test_tensor examples:  {result.test_tensor.shape[0]}, test_labels:  {len(result.test_labels)}, test_ticker_key:  {len(result.test_ticker_key)}")

assert result.train_tensor.shape[0] == len(result.train_labels) == len(result.train_ticker_key), \
    "train tensor, train_labels, and train_ticker_key are out of sync"
assert result.test_tensor.shape[0] == len(result.test_labels) == len(result.test_ticker_key), \
    "test tensor, test_labels, and test_ticker_key are out of sync"
print("PASS: every matrix has exactly one label and one key entry\n")

print("=" * 60)
print("NO TRAIN/TEST TICKER-PERIOD OVERLAP CHECK")
print("=" * 60)
# a (ticker, start_date) pair should never appear in both train and test,
# this would indicate the same matrix leaked into both sets
train_periods = set((t, s) for t, s, e in result.train_ticker_key)
test_periods = set((t, s) for t, s, e in result.test_ticker_key)
overlap = train_periods & test_periods
if overlap:
    print(f"FAIL: {len(overlap)} (ticker, start_date) pairs appear in BOTH train and test: {list(overlap)[:5]}")
else:
    print("PASS: no (ticker, start_date) pair appears in both train and test\n")

print("=" * 60)
print("DATE ORDERING SPOT-CHECK (first train example)")
print("=" * 60)
print(f"First train example, ticker/start/end: {result.train_ticker_key[0]}")
print("(start date should be EARLIER than end date, confirming oldest-first ordering)")
first_ticker, first_start, first_end = result.train_ticker_key[0]
assert first_start < first_end, "start date is not before end date, ordering may be reversed"
print("PASS: start date precedes end date\n")

print("=" * 60)
print("LABEL SANITY CHECK")
print("=" * 60)
print(f"train_labels: min={result.train_labels.min():.4f}  max={result.train_labels.max():.4f}  "
      f"mean={result.train_labels.mean():.4f}  std={result.train_labels.std():.4f}")
print(f"test_labels:  min={result.test_labels.min():.4f}  max={result.test_labels.max():.4f}  "
      f"mean={result.test_labels.mean():.4f}  std={result.test_labels.std():.4f}")
print("(these are raw forward returns, e.g. 0.05 = +5% over the matrix_length window,")
print(" sanity check: values should be small decimals, not huge numbers or all zeros)\n")

print("=" * 60)
print("Z-SCORING SANITY CHECK (features only, labels are never scaled)")
print("=" * 60)
train_flat = result.train_tensor.reshape(-1, result.train_tensor.shape[-1])
print("Per-feature mean (train, should be ~0):")
print(np.round(train_flat.mean(axis=0), 4))
print("Per-feature std (train, should be ~1):")
print(np.round(train_flat.std(axis=0), 4))

print(f"\nStored feature_mean (pre-scaling, from original data):")
print(np.round(result.feature_mean, 4))
print(f"Stored feature_std (pre-scaling, from original data):")
print(np.round(result.feature_std, 4))

print("\nNote: the test tensor is scaled using TRAIN mean/std, so its own")
print("post-scaling mean/std will NOT be exactly 0/1, that's expected and")
print("correct, it's the sign there's no leakage from test into the scaling")
print("statistics.")
test_flat = result.test_tensor.reshape(-1, result.test_tensor.shape[-1])
print("\nPer-feature mean (test, scaled with TRAIN stats, may deviate from 0):")
print(np.round(test_flat.mean(axis=0), 4))

print("\n" + "=" * 60)
print("ALL CHECKS COMPLETE")
print("=" * 60)