import yfinance as yf
import pandas as pd
import lxml
import requests
import io
import numpy as np


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

Ticker = 'MMM'

def calculateReturnSinceInception(Ticker,
                                  data = history_nona):
    """
    SUMMARY.

    Parameters
    ----------
    Ticker : TYPE
        Stock Ticker.
    data : TYPE, optional
        Dataframe output from priceHistory or priceHistoryBatch including the ticker
        as well as open, close, and date columns
        . The default is history_nona.

    Returns
    -------
    64 bit float
        proportion of return since inception indexed to date.
    """
    history_subset = history_nona[history_nona['Ticker']==Ticker].reset_index()
    
    open_first =  history_subset['Open'][history_subset['Date'] == np.min(history_subset['Date'])][0] 
    
    returns= history_subset['Close']/open_first
    
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
                     data = history_nona,
                     spy_returns = spy_returns):
    ticker_momentum = calculateMomentum(Ticker, 
                                        window_size=window_size,
                                        data= history_nona)
    spy_momentum = calculateMomentum('SPY', 
                                        window_size=window_size,
                                        data =spy_returns)
    
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
    



