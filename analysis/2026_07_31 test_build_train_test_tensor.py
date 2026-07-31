"""
Test script for buildTrainTestTensor.

Run this after your normal src/data_loading.py setup is loaded (or with
build_train_test_tensor.py importing from src.data_loading as it already
does). This does NOT check whether the model can predict anything, it only
checks that the function is producing structurally correct output: right
shapes, right ordering, no leakage between train/test stats, etc.

Start with a small, cheap ticker list before scaling up to the full S&P 500,
this will be slow and hit yfinance a lot on a big universe.
"""

import numpy as np
from src.data_loading import (
    priceHistoryBatch,
    priceHistory,
    calculateReturnSinceInception,
    calculateDailyReturn,
    calculateMomentum,
    calculateVolumeRatio,
    calculateVolatility,
    calculateRelativeStrength,
    priceLevelContext,
    zscore_tensor
)

from src.data_loading import buildTrainTestTensor, zscore_tensor

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
print(f"train_tensor shape:      {result.train_tensor.shape}")
print(f"test_tensor shape:       {result.test_tensor.shape}")
print(f"validation_tensor shape: {result.validation_tensor.shape}")
print(f"num features expected:   {len(result.feature_columns)}")
print(f"feature_columns:         {result.feature_columns}")

# All three tensors should agree on (time_steps, num_features), only the
# number of examples (axis 0) should differ
assert result.train_tensor.shape[1:] == result.test_tensor.shape[1:], \
    "train/test tensors disagree on (time_steps, num_features)"
assert result.train_tensor.shape[1:] == result.validation_tensor.shape[1:], \
    "train/validation tensors disagree on (time_steps, num_features)"
assert result.train_tensor.shape[1] == 20, "matrix_length mismatch"
assert result.train_tensor.shape[2] == len(result.feature_columns), \
    "feature axis doesn't match feature_columns length"
print("PASS: shapes are consistent across train/test/validation\n")

print("=" * 60)
print("KEY LENGTH CHECKS")
print("=" * 60)
print(f"train_tensor examples:   {result.train_tensor.shape[0]}, train_ticker_key entries: {len(result.train_ticker_key)}")
print(f"test_tensor examples:    {result.test_tensor.shape[0]}, test_ticker_key entries:  {len(result.test_ticker_key)}")
print(f"validation_tensor examples: {result.validation_tensor.shape[0]}, validation_ticker_key entries: {len(result.validation_ticker_key)}")

assert result.train_tensor.shape[0] == len(result.train_ticker_key), \
    "train tensor and train_ticker_key are out of sync"
assert result.test_tensor.shape[0] == len(result.test_ticker_key), \
    "test tensor and test_ticker_key are out of sync"
assert result.validation_tensor.shape[0] == len(result.validation_ticker_key), \
    "validation tensor and validation_ticker_key are out of sync"
print("PASS: every matrix has a matching key entry\n")

print("=" * 60)
print("TEST/GROUND-TRUTH PAIRING CHECK")
print("=" * 60)
# every test matrix's ground truth should be the ticker's next matrix,
# i.e. the ticker in test_ticker_key[i] should match validation_ticker_key[i],
# and the validation matrix's start date should be right after the test
# matrix's end date
mismatches = 0
for i, (test_entry, val_entry) in enumerate(zip(result.test_ticker_key, result.validation_ticker_key)):
    test_ticker, test_start, test_end = test_entry
    val_ticker, val_start, val_end = val_entry
    if test_ticker != val_ticker:
        print(f"  MISMATCH at index {i}: test ticker {test_ticker} != validation ticker {val_ticker}")
        mismatches += 1
    if val_start <= test_end:
        print(f"  WARNING at index {i}: validation matrix ({val_start}) doesn't start after test matrix ends ({test_end})")

if mismatches == 0:
    print("PASS: every test matrix's ground truth is from the same ticker\n")
else:
    print(f"FAIL: {mismatches} ticker mismatches between test and validation keys\n")

print("=" * 60)
print("DATE ORDERING SPOT-CHECK (first train example)")
print("=" * 60)
print(f"First train example, ticker/start/end: {result.train_ticker_key[0]}")
print("(start date should be EARLIER than end date, confirming oldest-first ordering)")
first_ticker, first_start, first_end = result.train_ticker_key[0]
assert first_start < first_end, "start date is not before end date, ordering may be reversed"
print("PASS: start date precedes end date\n")

print("=" * 60)
print("Z-SCORING SANITY CHECK")
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

print("\nNote: test/validation tensors are scaled using TRAIN mean/std, so")
print("their own post-scaling mean/std will NOT be exactly 0/1, that's")
print("expected and correct, it's the sign there's no leakage from")
print("test/validation into the scaling statistics.")
test_flat = result.test_tensor.reshape(-1, result.test_tensor.shape[-1])
print("\nPer-feature mean (test, scaled with TRAIN stats, may deviate from 0):")
print(np.round(test_flat.mean(axis=0), 4))

print("\n" + "=" * 60)
print("ALL CHECKS COMPLETE")
print("=" * 60)
