"""
buildTrainTestTensor

Builds LSTM-ready tensors + forward-return labels from S&P 500 price/feature
history.

Design decisions baked into this function (see conversation for full reasoning):
- No explicit "time" feature: row position within each matrix already encodes
  time-step order, which is exactly what the LSTM uses.
- No raw Volume feature: raw share-count volume varies enormously by company
  size and isn't comparable across tickers even after z-scoring.
  Volume_{window} (ratio to its own rolling average) is used instead.
- Every FEATURE is z-scored using statistics computed from the TRAINING
  tensor only, then applied to test. Close price is tracked separately,
  purely to compute labels, and is never z-scored or included as a feature.
- Labels: for matrix i, the label is the forward return from THIS matrix's
  last Close to the NEXT matrix's first Close, i.e. horizon == matrix_length.
  This ties input window length and prediction horizon together; that
  coupling is a known simplification, not a bug (see conversation).
- The last matrix in each ticker's sequence has no "next" matrix, so it has
  no label and is excluded from both train and test.
- Labels returned here are CONTINUOUS forward returns, not yet binarized.
  Binarize downstream using a cutoff computed from train_labels only.
- Uses priceHistoryBatchChunked (not priceHistoryBatch) for the main price
  pull, since a pull this large (hundreds-thousands of tickers, decades of
  history) reliably trips Yahoo's rate limiter in one shot. Chunking with
  pauses between requests spreads the load and keeps one rate-limited
  chunk from taking down the entire pull.
"""

from itertools import chain
from collections import namedtuple
import numpy as np
import pandas as pd

from src.data_loading import (
    priceHistoryBatchChunked,
    priceHistory,
    calculateReturnSinceInception,
    calculateDailyReturn,
    calculateMomentum,
    calculateVolumeRatio,
    calculateVolatility,
    calculateRelativeStrength,
    priceLevelContext,
)


def zscore_tensor(tensor: np.ndarray, mean: np.ndarray = None, std: np.ndarray = None):
    """
    Z-score a (num_examples, time_steps, num_features) tensor along the
    feature axis (last axis). Pass in the TRAINING set's mean/std when
    scaling the test tensor, never recompute on held-out data.
    """
    if tensor.size == 0:
        return tensor, mean, std

    flat = tensor.reshape(-1, tensor.shape[-1])

    if mean is None:
        mean = flat.mean(axis=0)
    if std is None:
        std = flat.std(axis=0)
        std = np.where(std == 0, 1.0, std)

    scaled = (tensor - mean) / std
    return scaled, mean, std


def buildTrainTestTensor(
        Tickers: list[str],
        start_date: str,
        end_date: str,
        test_interval=5,
        matrix_length=20,
        momentum_windows=[5, 20, 60, 120],
        volatility_windows=[20, 60],
        volume_windows=[20],
        relative_strength_windows=[20],
        price_level_windows=[252],
        chunk_size=100,
        pause_seconds=5,
):
    lag = max(chain(momentum_windows, volatility_windows, volume_windows, price_level_windows))

    start_ts = pd.Timestamp(start_date)
    lag_date = start_ts - pd.Timedelta(days=lag)
    end_ts = pd.Timestamp(end_date)

    dataset = priceHistoryBatchChunked(
        tickers=Tickers, start_date=lag_date, end_date=end_ts,
        chunk_size=chunk_size, pause_seconds=pause_seconds,
    )
    dataset = dataset.loc[:, ['Open', 'High', 'Low', 'Close', 'Volume', 'Ticker']].dropna()

    spy_returns_range = priceHistory(['SPY'], start_date=lag_date, end_date=end_ts)

    feature_columns = ['Cumulative_Return', 'Daily_Return']
    feature_columns += [f"Momentum_{m}" for m in momentum_windows]
    feature_columns += [f"Volume_{v}" for v in volume_windows]
    feature_columns += [f"Volatility_{v}" for v in volatility_windows]
    feature_columns += [f"Relative_Strength_{r}" for r in relative_strength_windows]
    for p in price_level_windows:
        feature_columns += [f'Price_Level_High_{p}', f'Price_Level_Low_{p}']

    train_matrices_list = []
    test_matrices_list = []
    train_labels_list = []
    test_labels_list = []
    train_ticker_key = []
    test_ticker_key = []

    for ticker_i in Tickers:
        data_ticker = dataset[dataset['Ticker'] == ticker_i].reset_index().sort_values('Date').reset_index(drop=True).copy()

        if data_ticker.empty:
            print(f"  Skipping {ticker_i}: no data in this date range")
            continue

        try:
            data_ticker['Cumulative_Return'] = calculateReturnSinceInception(Ticker=ticker_i, data=data_ticker).values
            data_ticker['Daily_Return'] = calculateDailyReturn(Ticker=ticker_i, data=data_ticker).values

            for momentum_i in momentum_windows:
                data_ticker[f"Momentum_{momentum_i}"] = calculateMomentum(Ticker=ticker_i, window_size=momentum_i, data=data_ticker).values

            for volume_i in volume_windows:
                data_ticker[f"Volume_{volume_i}"] = calculateVolumeRatio(Ticker=ticker_i, window_size=volume_i, data=data_ticker).values

            for volatility_i in volatility_windows:
                data_ticker[f"Volatility_{volatility_i}"] = calculateVolatility(Ticker=ticker_i, window_size=volatility_i, data=data_ticker).values

            for relative_strength_i in relative_strength_windows:
                data_ticker[f"Relative_Strength_{relative_strength_i}"] = calculateRelativeStrength(
                    Ticker=ticker_i, window_size=relative_strength_i, data=data_ticker, spy_returns=spy_returns_range).values

            for plw_i in price_level_windows:
                plw_i_data = priceLevelContext(Ticker=ticker_i, window_size=plw_i, data=data_ticker)
                data_ticker[f'Price_Level_High_{plw_i}'] = plw_i_data['pct_from_high'].values
                data_ticker[f'Price_Level_Low_{plw_i}'] = plw_i_data['pct_from_low'].values

        except Exception as e:
            print(f"  Skipping {ticker_i}: error while computing features ({e})")
            continue

        # 'Close' must survive dropna/trimming alongside the features so we
        # can compute labels, but it is never added to feature_columns
        data_ticker_nona = data_ticker.dropna().reset_index(drop=True)
        data_ticker_length = len(data_ticker_nona)
        n_matrices = data_ticker_length // matrix_length

        if n_matrices < 2:
            print(f"  Skipping {ticker_i}: not enough data for a train/test pair (n_matrices={n_matrices})")
            continue

        usable_rows = n_matrices * matrix_length
        overhang = data_ticker_length - usable_rows
        data_ticker_trimmed = data_ticker_nona.iloc[overhang:].reset_index(drop=True)

        assert data_ticker_trimmed['Date'].is_monotonic_increasing, \
            f"{ticker_i}: rows are not in ascending date order before reshaping"

        ticker_arr = data_ticker_trimmed[feature_columns].to_numpy()
        ticker_matrices_3d = ticker_arr.reshape(-1, matrix_length, ticker_arr.shape[1])

        date_arr = data_ticker_trimmed['Date'].to_numpy().reshape(-1, matrix_length)
        matrix_start_dates = date_arr[:, 0]
        matrix_end_dates = date_arr[:, -1]

        # --- labels: forward return from this matrix's last Close to the
        # next matrix's first Close. forward_return_per_matrix[i] is the
        # label for matrix i, valid for i in 0..n_matrices-2 (the last
        # matrix has no "next" matrix, so no label)
        close_arr = data_ticker_trimmed['Close'].to_numpy().reshape(-1, matrix_length)
        matrix_first_close = close_arr[:, 0]
        matrix_last_close = close_arr[:, -1]
        forward_return_per_matrix = (matrix_first_close[1:] - matrix_last_close[:-1]) / matrix_last_close[:-1]

        n_labeled = n_matrices - 1  # matrices 0..n_matrices-2

        n_rand_matrices = n_labeled // test_interval
        if n_rand_matrices > 0:
            rand_matrices = np.sort(np.random.choice(n_labeled, size=n_rand_matrices, replace=False))

            test_matrices_list.append(ticker_matrices_3d[rand_matrices])
            test_labels_list.append(forward_return_per_matrix[rand_matrices])
            for idx in rand_matrices:
                test_ticker_key.append((ticker_i, matrix_start_dates[idx], matrix_end_dates[idx]))

            # exclude both the test matrix AND its "next" matrix from
            # training, so no calendar period does double duty as both a
            # test label's source and a training input
            held_out = np.unique(np.concatenate([rand_matrices, rand_matrices + 1]))
            held_out = held_out[held_out < n_labeled]
        else:
            held_out = np.array([], dtype=int)

        train_mask = np.ones(n_labeled, dtype=bool)
        train_mask[held_out] = False
        train_idx = np.where(train_mask)[0]

        train_matrices_list.append(ticker_matrices_3d[train_idx])
        train_labels_list.append(forward_return_per_matrix[train_idx])
        for idx in train_idx:
            train_ticker_key.append((ticker_i, matrix_start_dates[idx], matrix_end_dates[idx]))

    num_features = len(feature_columns)
    common_train_tensor = np.concatenate(train_matrices_list, axis=0) if train_matrices_list else np.empty((0, matrix_length, num_features))
    common_test_tensor = np.concatenate(test_matrices_list, axis=0) if test_matrices_list else np.empty((0, matrix_length, num_features))
    common_train_labels = np.concatenate(train_labels_list, axis=0) if train_labels_list else np.empty((0,))
    common_test_labels = np.concatenate(test_labels_list, axis=0) if test_labels_list else np.empty((0,))

    # z-score FEATURES using TRAIN statistics only, labels are never scaled
    common_train_tensor, feature_mean, feature_std = zscore_tensor(common_train_tensor)
    common_test_tensor, _, _ = zscore_tensor(common_test_tensor, mean=feature_mean, std=feature_std)

    OutputTuple = namedtuple('OutputTuple', [
        'train_tensor', 'train_labels', 'test_tensor', 'test_labels',
        'train_ticker_key', 'test_ticker_key',
        'feature_columns', 'feature_mean', 'feature_std'
    ])

    return OutputTuple(
        train_tensor=common_train_tensor,
        train_labels=common_train_labels,
        test_tensor=common_test_tensor,
        test_labels=common_test_labels,
        train_ticker_key=train_ticker_key,
        test_ticker_key=test_ticker_key,
        feature_columns=feature_columns,
        feature_mean=feature_mean,
        feature_std=feature_std,
    )