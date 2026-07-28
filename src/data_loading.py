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
        

    
    training_data = training_data.dropna()
    
    end_ts = pd.Timestamp(end_date)
    test_date = end_ts + pd.Timedelta(days=forward_window)
    test_lag_date = pd.Timestamp(test_date) - pd.Timedelta(days=lag)  # same `lag` you already computed above
    test_date_year = end_ts + pd.Timedelta(days=forward_window) + pd.Timedelta(days=365)
    
    test_data_raw = priceHistoryBatch(tickers=Tickers,
                                     start_date=test_lag_date,
                                     end_date=test_date_year).dropna()    
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
    
train, test = buildTrainingTable(['AAPL','MMM'],
                   '2017-01-01',
                   '2021-01-01')



