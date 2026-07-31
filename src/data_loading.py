import yfinance as yf
import pandas as pd
import lxml
import requests
import io
import numpy as np
from datetime import datetime
from itertools import chain
from collections import namedtuple
import random

def priceHistory(
    tickers: list[str], 
    start_date:str, 
    end_date:str):
        """
        Pull  price history between start date and end date for a given ticker
        
        Parameters
        tickers: list of str
        start_date and end date: str in 
        YYYY-MM-DD format
        
        Returns pd df with price indexed by date for
        open,
        high, 
        low,
        close, 
        volume
        """    
        data = pd.DataFrame()
        for i in tickers:
            
            data_temp= yf.download(i, 
                              start = start_date, 
                              end = end_date,
                              progress=False)
            data_temp.columns = data_temp.columns.get_level_values(0)
            data_temp['Ticker'] = i
            
            data= pd.concat([data_temp, data], ignore_index = False)
        return data
    
    
def priceHistoryBatch(tickers: list[str], start_date: str, end_date: str):
     
    """
    Pull historical daily price/volume data for multiple tickers in a single
    batched yfinance call, reshaped into the same long format as priceHistory:
    one row per ticker per date, columns Open/High/Low/Close/Volume, plus Symbol.
    
    Parameters
    ----------
    tickers : list[str]
    start_date, end_date : str, "YYYY-MM-DD"
    
    Returns
    -------
    pd.DataFrame
    """
    raw = yf.download(tickers, start=start_date, end=end_date, progress=False, group_by='ticker')
    
    frames = []
    for ticker in tickers:
        df_ticker = raw[ticker].copy()
        df_ticker['Ticker'] = ticker
        frames.append(df_ticker)
    
    data = pd.concat(frames, ignore_index=False)
    return data
   
def sp500Tickers():
    url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
    headers = {"User-Agent": "Mozilla/5.0"}
    
    response = requests.get(url, headers=headers)
    tables = pd.read_html(io.BytesIO(response.content))
    relevant = tables[0]
    companies = relevant['Symbol']
    companies_yfinance = companies.str.replace('.', '-', regex = False)
    
    return companies_yfinance


# the next family of functions are all designed to take inputs from a data frame
# output from priceHistoryBatch
sp = sp500Tickers()

history = priceHistoryBatch(tickers = sp.tolist(), 
                      start_date = '2017-01-01',
                       end_date = '2019-12-31'
                      )
history_nona = history.loc[:,['Open','High','Low','Close','Volume', 'Ticker']].dropna()
# in the future the sp list should be appended to get the 500 stocks from those
#dates oh well 

#Ticker = 'MMM'

def calculateReturnSinceInception(Ticker, data=history_nona):
    """
    Cumulative return relative to the ticker's first available Open price.

    Parameters
    ----------
    Ticker : str
        Stock ticker.
    data : pd.DataFrame, optional
        Dataframe output from priceHistory or priceHistoryBatch including the
        ticker as well as open, close, and date columns. The default is
        history_nona.

    Returns
    -------
    pd.Series
        Close / first Open, indexed by row position (0..n-1, sorted by Date).
    """
    history_subset = data[data['Ticker'] == Ticker].sort_values('Date').reset_index(drop=True)
    
    open_first = history_subset['Open'].iloc[0]
    
    returns = history_subset['Close'] / open_first
    
    return returns

def calculateDailyReturn(Ticker,
                          data=history_nona):
    """
    Daily percent return for a single ticker.

    Parameters
    ----------
    Ticker : str
        Stock ticker.
    data : pd.DataFrame, optional
        Dataframe output from priceHistory or priceHistoryBatch including the
        ticker as well as open, close, and date columns. The default is
        history_nona.

    Returns
    -------
    pd.Series
        Daily return (Close_t - Close_t-1) / Close_t-1, indexed by date.
    """
    history_subset = data[data['Ticker'] == Ticker].reset_index()
    history_subset = history_subset.sort_values('Date').reset_index(drop=True)
    daily_return = history_subset['Close'].pct_change()
    return daily_return


def calculateVolatility(Ticker, window_size=20, data=history_nona):
    history_subset = data[data['Ticker'] == Ticker].reset_index()
    history_subset = history_subset.sort_values('Date').reset_index(drop=True)
    
    history_subset['Daily Return'] = calculateDailyReturn(Ticker, data=data)
    
    volatility = history_subset['Daily Return'].rolling(window=window_size).std()
    volatility.index = history_subset['Date']
    
    return volatility



def calculateMomentum(Ticker, 
                      window_size=20, 
                      data = history):
    
    history_subset = data[data['Ticker'] == Ticker].reset_index()
    history_subset = history_subset.sort_values('Date').reset_index(drop=True)

    momentum = history_subset['Close'].pct_change(periods=window_size)
    momentum.index = history_subset['Date']
    return momentum
    

#def calculateAverageTrueRange
    
    
def calculateVolumeRatio(Ticker,window_size = 20,data =history_nona):
    history_subset = data[data['Ticker'] == Ticker].reset_index()
    history_subset = history_subset.sort_values('Date').reset_index(drop=True)

    volume_avg = history_subset['Volume'].rolling(window=window_size).mean()
    volume_avg.index = history_subset['Date']
    return volume_avg
    
    
spy_returns = priceHistory(['SPY'],
                           start_date = '2017-01-01',
                           end_date = '2019-12-31'
                           )

def calculateRelativeStrength(Ticker,
                     window_size=20, 
                     data=history_nona,
                     spy_returns=spy_returns):
    ticker_momentum = calculateMomentum(Ticker, 
                                        window_size=window_size,
                                        data=data)
    spy_momentum = calculateMomentum('SPY', 
                                        window_size=window_size,
                                        data=spy_returns)
    
    rel_strength = ticker_momentum - spy_momentum
    return rel_strength    
    
def priceLevelContext(Ticker, window_size=252, data=history_nona):
    history_subset = data[data['Ticker'] == Ticker].reset_index()
    history_subset = history_subset.sort_values('Date').reset_index(drop=True)
    
    rolling_high = history_subset['Close'].rolling(window=window_size).max()
    rolling_low = history_subset['Close'].rolling(window=window_size).min()
    
    pct_from_high = (history_subset['Close'] - rolling_high) / rolling_high
    pct_from_low = (history_subset['Close'] - rolling_low) / rolling_low
    
    result = pd.DataFrame({
        'pct_from_high': pct_from_high,
        'pct_from_low': pct_from_low
    })
    result.index = history_subset['Date']
    
    return result

def calculateForwardReturn(Ticker, window_size =20, data = history_nona):
    history_subset = data[data['Ticker'] == Ticker].reset_index()
    history_subset = history_subset.sort_values('Date').reset_index(drop=True)

    forward_return= history_subset['Close'].pct_change(periods=-window_size)
    forward_return.index = history_subset['Date']
    return forward_return
    
    
def buildTrainingTable(Tickers: list[str],
                   start_date: str,
                   end_date: str,
                   momentum_windows=[5, 20, 60, 120],
                   vol_windows=[20, 60],
                   volume_windows=[20],
                   relative_strength_window=[20],
                   price_level_window=[252],
                   forward_window=20):
    
    lag = max(chain(momentum_windows,
                   vol_windows,
                   volume_windows, 
                   price_level_window))

    start_ts = pd.Timestamp(start_date)
    lag_date = start_ts - pd.Timedelta(days=lag)
    
    training_data = priceHistoryBatch(tickers=Tickers,
                                     start_date=lag_date,
                                     end_date=end_date)
        

    training_data = training_data.loc[:, ['Open', 'High', 'Low', 'Close', 'Volume', 'Ticker']].dropna()    
    end_ts = pd.Timestamp(end_date)
    test_date = end_ts + pd.Timedelta(days=forward_window)
    test_lag_date = pd.Timestamp(test_date) - pd.Timedelta(days=lag)  # same `lag` you already computed above
    test_date_year = end_ts + pd.Timedelta(days=forward_window) + pd.Timedelta(days=365)
    
    test_data_raw = priceHistoryBatch(tickers=Tickers,
                                     start_date=test_lag_date,
                                     end_date=test_date_year)
    
    test_data_raw = test_data_raw.loc[:, ['Open', 'High', 'Low', 'Close', 'Volume', 'Ticker']].dropna()

    spy_returns_local_train = priceHistory(['SPY'],
                           start_date=lag_date,
                           end_date=end_date
                           )
    
    spy_returns_local_test = priceHistory(['SPY'],
                            start_date=test_lag_date,
                            end_date=test_date_year
                           )
    
    ### create training and test dataset ###
    full_data = pd.DataFrame()
    test_data = pd.DataFrame()

    for stock in Tickers:
        training_data_ticker = training_data[training_data['Ticker'] == stock].reset_index().sort_values('Date').reset_index(drop=True).copy()        
        test_data_ticker = test_data_raw[test_data_raw['Ticker'] == stock].reset_index().sort_values('Date').reset_index(drop=True).copy()
        
        # skip this ticker cleanly if there's no usable data, e.g. it didn't
        # exist yet during this date range (IPO'd later, delisted, etc.)
        if training_data_ticker.empty or test_data_ticker.empty:
            print(f"  Skipping {stock}: no data in this date range (train rows={len(training_data_ticker)}, test rows={len(test_data_ticker)})")
            continue
        
        try:
            training_data_ticker['Cumulative Return'] = calculateReturnSinceInception(stock, training_data_ticker)
            test_data_ticker['Cumulative Return'] = calculateReturnSinceInception(stock, test_data_ticker)
    
            training_data_ticker['Daily Return'] = calculateDailyReturn(stock, training_data_ticker)
            test_data_ticker['Daily Return'] = calculateDailyReturn(stock, test_data_ticker)
            
            training_data_ticker[f"Forward Return_,{forward_window}"] = calculateForwardReturn(stock, forward_window, training_data_ticker).values
            test_data_ticker[f"Forward Return_,{forward_window}"] = calculateForwardReturn(stock, forward_window, test_data_ticker).values
    
            for moment in momentum_windows:
                training_data_ticker[f"Momentum_,{moment}"] = calculateMomentum(stock, moment, training_data_ticker).values
                test_data_ticker[f"Momentum_,{moment}"] = calculateMomentum(stock, moment, test_data_ticker).values
    
            for vol in volume_windows:
                training_data_ticker[f"Volume,{vol}"] = calculateVolatility(stock, vol, training_data_ticker).values
                test_data_ticker[f"Volume,{vol}"] = calculateVolatility(stock, vol, test_data_ticker).values
    
            for p_l_w in price_level_window:
                plc_train = priceLevelContext(stock, p_l_w, training_data_ticker)
                training_data_ticker[f'Price_Level_High_{p_l_w}'] = plc_train['pct_from_high'].values
                training_data_ticker[f'Price_Level_Low_{p_l_w}'] = plc_train['pct_from_low'].values
                
                plc_test = priceLevelContext(stock, p_l_w, test_data_ticker)
                test_data_ticker[f'Price_Level_High_{p_l_w}'] = plc_test['pct_from_high'].values
                test_data_ticker[f'Price_Level_Low_{p_l_w}'] = plc_test['pct_from_low'].values
            
            for r_s_w in relative_strength_window:
                training_data_ticker[f'Relative Strength,{r_s_w}'] = calculateRelativeStrength(stock, r_s_w, training_data_ticker, spy_returns_local_train).values
                test_data_ticker[f'Relative Strength,{r_s_w}'] = calculateRelativeStrength(stock, r_s_w, test_data_ticker, spy_returns_local_test).values
    
        except Exception as e:
            print(f"  Skipping {stock}: error while computing features ({e})")
            continue
        
        test_data = pd.concat([pd.DataFrame(test_data_ticker), test_data])
        full_data = pd.concat([training_data_ticker, full_data], ignore_index=False)
    
    TrainingResult = namedtuple('TrainingResult', ['train', 'test'])
    return TrainingResult(train=full_data, test=test_data)
    
#train, test = buildTrainingTable(['AAPL','MMM'],
 #                  '2017-01-01',
  #                 '2021-01-01')


def buildFeatureBase(Tickers: list[str],
                   start_date: str,
                   end_date: str,
                   momentum_windows=[5, 20, 60, 120],
                   vol_windows=[20, 60],
                   volume_windows=[20],
                   relative_strength_window=[20],
                   price_level_window=[252],
                   max_forward_window=200):
    """
    Same as buildTrainingTable, but WITHOUT computing any forward-return
    label, and pulls test data far enough out to cover the largest horizon
    you plan to sweep. Everything here (momentum, volatility, price level,
    relative strength) doesn't depend on forward_window, so this only needs
    to run once per (Tickers, start_date, end_date) combination, no matter
    how many horizons you test afterward.
    """
    lag = max(chain(momentum_windows, vol_windows, volume_windows, price_level_window))

    start_ts = pd.Timestamp(start_date)
    lag_date = start_ts - pd.Timedelta(days=lag)

    training_data = priceHistoryBatch(tickers=Tickers, start_date=lag_date, end_date=end_date)
    training_data = training_data.loc[:, ['Open', 'High', 'Low', 'Close', 'Volume', 'Ticker']].dropna()

    end_ts = pd.Timestamp(end_date)
    # size the test pull to cover the WIDEST horizon you'll test, plus a year
    # of runway past that, so every forward_window in the sweep has enough
    # future data available without re-pulling
    test_date = end_ts + pd.Timedelta(days=1)
    test_lag_date = pd.Timestamp(test_date) - pd.Timedelta(days=lag)
    test_date_year = end_ts + pd.Timedelta(days=max_forward_window) + pd.Timedelta(days=365)

    test_data_raw = priceHistoryBatch(tickers=Tickers, start_date=test_lag_date, end_date=test_date_year)
    test_data_raw = test_data_raw.loc[:, ['Open', 'High', 'Low', 'Close', 'Volume', 'Ticker']].dropna()

    spy_returns_local_train = priceHistory(['SPY'], start_date=lag_date, end_date=end_date)
    spy_returns_local_test = priceHistory(['SPY'], start_date=test_lag_date, end_date=test_date_year)

    full_data = pd.DataFrame()
    test_data = pd.DataFrame()

    for stock in Tickers:
        training_data_ticker = training_data[training_data['Ticker'] == stock].reset_index().sort_values('Date').reset_index(drop=True).copy()
        test_data_ticker = test_data_raw[test_data_raw['Ticker'] == stock].reset_index().sort_values('Date').reset_index(drop=True).copy()

        if training_data_ticker.empty or test_data_ticker.empty:
            print(f"  Skipping {stock}: no data in this date range (train rows={len(training_data_ticker)}, test rows={len(test_data_ticker)})")
            continue

        try:
            training_data_ticker['Cumulative Return'] = calculateReturnSinceInception(stock, training_data_ticker)
            test_data_ticker['Cumulative Return'] = calculateReturnSinceInception(stock, test_data_ticker)

            training_data_ticker['Daily Return'] = calculateDailyReturn(stock, training_data_ticker)
            test_data_ticker['Daily Return'] = calculateDailyReturn(stock, test_data_ticker)

            for moment in momentum_windows:
                training_data_ticker[f"Momentum_,{moment}"] = calculateMomentum(stock, moment, training_data_ticker).values
                test_data_ticker[f"Momentum_,{moment}"] = calculateMomentum(stock, moment, test_data_ticker).values

            for vol in volume_windows:
                training_data_ticker[f"Volume,{vol}"] = calculateVolatility(stock, vol, training_data_ticker).values
                test_data_ticker[f"Volume,{vol}"] = calculateVolatility(stock, vol, test_data_ticker).values

            for p_l_w in price_level_window:
                plc_train = priceLevelContext(stock, p_l_w, training_data_ticker)
                training_data_ticker[f'Price_Level_High_{p_l_w}'] = plc_train['pct_from_high'].values
                training_data_ticker[f'Price_Level_Low_{p_l_w}'] = plc_train['pct_from_low'].values

                plc_test = priceLevelContext(stock, p_l_w, test_data_ticker)
                test_data_ticker[f'Price_Level_High_{p_l_w}'] = plc_test['pct_from_high'].values
                test_data_ticker[f'Price_Level_Low_{p_l_w}'] = plc_test['pct_from_low'].values

            for r_s_w in relative_strength_window:
                training_data_ticker[f'Relative Strength,{r_s_w}'] = calculateRelativeStrength(stock, r_s_w, training_data_ticker, spy_returns_local_train).values
                test_data_ticker[f'Relative Strength,{r_s_w}'] = calculateRelativeStrength(stock, r_s_w, test_data_ticker, spy_returns_local_test).values

        except Exception as e:
            print(f"  Skipping {stock}: error while computing features ({e})")
            continue

        test_data = pd.concat([test_data_ticker, test_data], ignore_index=True)
        full_data = pd.concat([training_data_ticker, full_data], ignore_index=True)

    FeatureBase = namedtuple('FeatureBase', ['train', 'test'])
    return FeatureBase(train=full_data, test=test_data)


def addForwardReturnLabel(data: pd.DataFrame, forward_window: int):
    """
    Takes a dataframe already built by buildFeatureBase (has Date, Close,
    Ticker, and all the horizon-independent features) and adds a forward
    return label column for a SPECIFIC forward_window, per ticker.
    No network calls, this is pure pandas, fast to call repeatedly.
    """
    data = data.copy()
    label_col = f"Forward Return_,{forward_window}"
    pieces = []
    for stock in data['Ticker'].unique():
        subset = data[data['Ticker'] == stock].sort_values('Date').reset_index(drop=True)
        subset[label_col] = calculateForwardReturn(stock, forward_window, subset).values
        pieces.append(subset)
    return pd.concat(pieces, ignore_index=True)   




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
 
    
    
    

