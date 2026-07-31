import yfinance as yf
import pandas as pd
import lxml
import requests
import io
import numpy as np
from datetime import datetime
from itertools import chain
from collections import namedtuple

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



""" outline for tensor builder
"""

def buildTrainTestTensor(
        Tickers: list[str],
        start_date: str,
        end_date: str,
        test_interval = 5, # how many n matrices should be trained per test matrix
        matrix_length = 20, # how long each matrix will be 
        momentum_windows=[5, 20, 60, 120],
        volatility_windows=[20, 60],
        volume_windows=[20],
        relative_strength_window=[20],
        price_level_window=[252],
        forward_window=20
        ):   
    """
    The goal of this funciton is the following:
        Build a tensor such that each matrix is, for a given ticker:
            Rows are days where earilest day is first and latest day is last
            of format t-20 ... -> t-1; a countdown
            Columns are features
        Matrices will follow oldest -> earliest within ticker and then
        move on to the next ticker
            
    
    A few considerations
    1) With any of these lagging metrics, we want to make sure the matrices
    are properly populated so we will need to make sure we add proper buffer
    before / after the window of interest OR we exclude any NA matrices and 
    assume that the matrix count will be enough without buffering
    
    2) We need to make sure each matrix is full, so after this buffering or 
    whatever, I need to make sure matrix length is a multiple of matrix_length,
    and filter out any overhangs
    
    3) For label tracking, I think it needs to be two arrays or perhaps 
    tuples where one set is ticker and another is date range
    
    4) For test data, I will pull out the last 2 matrices for each ticker and 
    hold them out, the first will be the test and the second will be the ground
    truth
    """
    

    
    #here, I will first calculate the number of trading days 
    # between lag start and lag end dates, and floor it to the closest
    # mutliple of matrix_length
    
    #start_use = 
    #end_use = 
    
    #here, I will price history batch based on those dates



    # here, I will then apply all of the calculations I would do in 
    # buildTrainingTable
    
    # next, instead of rejoining into a common dataframe, I will then divide
    # into matrices of lenght matrix length and join into a common tensor
    # stripping out date and ticker
    #here, I will also recode day to my t- format and preserve only features
    # I want
    #before joining into a common tensor, I will first ticker specific tensors
    # and strip out the last two, one for testing and one for validation
    
    #Here, I will then put the rest into a common final tensor and output that 
    # along with my tracking vectors 
    
    return "Filler"
    
    
    
    

