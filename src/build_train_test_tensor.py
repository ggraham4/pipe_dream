"""
buildTrainTestTensor

Builds LSTM-ready tensors from S&P 500 price/feature history.

Design decisions baked into this function (see conversation for full reasoning):
- No explicit "time" feature: row position within each matrix already encodes
  time-step order, which is exactly what the LSTM uses. An explicit time
  column would be identical across every example and carry no information.
- No raw Volume feature: raw share-count volume varies enormously by company
  size and isn't comparable across tickers even after z-scoring (z-scoring
  only removes the global mean/scale, not cross-sectional differences).
  Volume_{window}, the ratio of current volume to its own rolling average,
  is used instead, it's dimensionless and comparable across tickers.
- Every feature is z-scored (mean 0, std 1) using statistics computed from
  the TRAINING tensor only, then applied to test/validation. Computing
  stats separately per split would leak information about the held-out
  data's distribution into preprocessing.
- forward_windows is currently unused. The forward-return horizon is
  implicitly equal to matrix_length: a test matrix's "ground truth" is
  defined as the very next matrix in that ticker's sequence. Decoupling
  horizon from matrix_length is a future improvement, not handled here.
"""

from itertools import chain
from collections import namedtuple
import numpy as np
import pandas as pd

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
)


def zscore_tensor(tensor: np.ndarray, mean: np.ndarray = None, std: np.ndarray = None):
    """
    Z-score a (num_examples, time_steps, num_features) tensor along the
    feature axis (last axis). If mean/std are not provided, they are
    computed from `tensor` itself, pooling across examples AND time steps
    for each feature. Pass in the TRAINING set's mean/std when scaling
    test/validation tensors, never recompute on held-out data.

    Returns (scaled_tensor, mean, std) so the same mean/std can be reused.
    """
    if tensor.size == 0:
        return tensor, mean, std

    flat = tensor.reshape(-1, tensor.shape[-1])

    if mean is None:
        mean = flat.mean(axis=0)
    if std is None:
        std = flat.std(axis=0)
        std = np.where(std == 0, 1.0, std)  # avoid divide-by-zero on constant features

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
        forward_windows=[20]
):
    lag = max(chain(momentum_windows, volatility_windows, volume_windows, price_level_windows))

    start_ts = pd.Timestamp(start_date)
    lag_date = start_ts - pd.Timedelta(days=lag)
    end_ts = pd.Timestamp(end_date)

    dataset = priceHistoryBatch(tickers=Tickers, start_date=lag_date, end_date=end_ts)
    dataset = dataset.loc[:, ['Open', 'High', 'Low', 'Close', 'Volume', 'Ticker']].dropna()

    # SPY must cover the SAME range as each ticker (including the lag
    # buffer), or calculateRelativeStrength's Date-based alignment produces
    # mismatched-length results, the same bug hit earlier in this project
    spy_returns_range = priceHistory(['SPY'], start_date=lag_date, end_date=end_ts)

    # feature columns, built ONCE, raw Volume intentionally excluded
    # (see module docstring)
    feature_columns = ['Cumulative_Return', 'Daily_Return']
    feature_columns += [f"Momentum_{m}" for m in momentum_windows]
    feature_columns += [f"Volume_{v}" for v in volume_windows]
    feature_columns += [f"Volatility_{v}" for v in volatility_windows]
    feature_columns += [f"Relative_Strength_{r}" for r in relative_strength_windows]
    for p in price_level_windows:
        feature_columns += [f'Price_Level_High_{p}', f'Price_Level_Low_{p}']

    train_matrices_list = []
    test_matrices_list = []
    validation_matrices_list = []
    train_ticker_key = []
    test_ticker_key = []
    validation_ticker_key = []

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

        data_ticker_nona = data_ticker.dropna().reset_index(drop=True)
        data_ticker_length = len(data_ticker_nona)
        n_matrices = data_ticker_length // matrix_length

        if n_matrices < 2:
            print(f"  Skipping {ticker_i}: not enough data for a train/test pair (n_matrices={n_matrices})")
            continue

        usable_rows = n_matrices * matrix_length
        overhang = data_ticker_length - usable_rows
        data_ticker_trimmed = data_ticker_nona.iloc[overhang:].reset_index(drop=True)

        # confirm oldest-first ordering (row 0 = earliest date, last row =
        # most recent) BEFORE reshaping, since reshape silently preserves
        # whatever row order it's given, if this were ever backwards, every
        # matrix would be backwards too with no obvious error downstream
        assert data_ticker_trimmed['Date'].is_monotonic_increasing, \
            f"{ticker_i}: rows are not in ascending date order before reshaping"

        ticker_arr = data_ticker_trimmed[feature_columns].to_numpy()
        ticker_matrices_3d = ticker_arr.reshape(-1, matrix_length, ticker_arr.shape[1])

        # per-matrix start/end dates, for bookkeeping only, never fed to the model
        date_arr = data_ticker_trimmed['Date'].to_numpy().reshape(-1, matrix_length)
        matrix_start_dates = date_arr[:, 0]
        matrix_end_dates = date_arr[:, -1]

        # test matrices sampled from indices 0..n_matrices-2, so idx+1
        # (the ground-truth matrix) always exists
        n_rand_matrices = n_matrices // test_interval
        if n_rand_matrices > 0:
            rand_matrices = np.sort(np.random.choice(n_matrices - 1, size=n_rand_matrices, replace=False))
            ground_truth_matrices = rand_matrices + 1

            test_matrices_list.append(ticker_matrices_3d[rand_matrices])
            validation_matrices_list.append(ticker_matrices_3d[ground_truth_matrices])

            for idx in rand_matrices:
                test_ticker_key.append((ticker_i, matrix_start_dates[idx], matrix_end_dates[idx]))
            for idx in ground_truth_matrices:
                validation_ticker_key.append((ticker_i, matrix_start_dates[idx], matrix_end_dates[idx]))

            held_out = np.concatenate([rand_matrices, ground_truth_matrices])
        else:
            held_out = np.array([], dtype=int)

        train_mask = np.ones(n_matrices, dtype=bool)
        train_mask[held_out] = False
        train_matrices_list.append(ticker_matrices_3d[train_mask])

        for idx in np.where(train_mask)[0]:
            train_ticker_key.append((ticker_i, matrix_start_dates[idx], matrix_end_dates[idx]))

    num_features = len(feature_columns)
    common_train_tensor = np.concatenate(train_matrices_list, axis=0) if train_matrices_list else np.empty((0, matrix_length, num_features))
    common_test_tensor = np.concatenate(test_matrices_list, axis=0) if test_matrices_list else np.empty((0, matrix_length, num_features))
    common_validation_tensor = np.concatenate(validation_matrices_list, axis=0) if validation_matrices_list else np.empty((0, matrix_length, num_features))

    # z-score every feature using TRAIN statistics only, then apply those
    # same stats to test/validation, never recompute on held-out data
    common_train_tensor, feature_mean, feature_std = zscore_tensor(common_train_tensor)
    common_test_tensor, _, _ = zscore_tensor(common_test_tensor, mean=feature_mean, std=feature_std)
    common_validation_tensor, _, _ = zscore_tensor(common_validation_tensor, mean=feature_mean, std=feature_std)

    OutputTuple = namedtuple('OutputTuple', [
        'train_tensor', 'test_tensor', 'validation_tensor',
        'train_ticker_key', 'test_ticker_key', 'validation_ticker_key',
        'feature_columns', 'feature_mean', 'feature_std'
    ])

    return OutputTuple(
        train_tensor=common_train_tensor,
        test_tensor=common_test_tensor,
        validation_tensor=common_validation_tensor,
        train_ticker_key=train_ticker_key,
        test_ticker_key=test_ticker_key,
        validation_ticker_key=validation_ticker_key,
        feature_columns=feature_columns,
        feature_mean=feature_mean,
        feature_std=feature_std,
    )
