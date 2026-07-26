#### Make PCA and UMAP of S&P 500 ###
### 2026_07_25 ####

#dependencies
import numpy as np
import sklearn
import umap
import seaborn as sns
import matplotlib.pyplot as plt

# this doesnt work and I added an __init__.py
from src.data_loading import sp500Tickers, priceHistoryBatch

### Get list of 500 companies
sp = sp500Tickers()

# make a dataframe for the time from 2000 - 2025
history = priceHistoryBatch(tickers = sp.tolist(), 
                       start_date = '2025-01-01',
                       end_date = '2025-12-31'
                      )

# select closing price
history_close = history.loc[:,['Close', 'Ticker']].dropna()

#make wide dataframe where columns are tickers, cells are closing prices, 
# and rows are dates
#pivot so now columns are dates
history_close_wide = history_close.pivot(columns = 'Ticker', values = 'Close').dropna().T

#initialize scaler
scaler = sklearn.preprocessing.StandardScaler()

#scale data
history_close_wide_scaled = scaler.fit_transform(history_close_wide)

#intialize pca
pc_= sklearn.decomposition.PCA()

#fit pc to scaled data
pc_X = pc_.fit_transform(history_close_wide_scaled)

#plot principal components
tickers = history_close_wide.index

plt.scatter(pc_X[:, 0], pc_X[:, 1], c =history_close_wide.mean(axis=1), cmap = 'viridis')

for i, ticker in enumerate(tickers):
    plt.text(pc_X[i, 0], pc_X[i, 1], ticker)

plt.xlabel('PC1')
plt.ylabel('PC2')
plt.show()

#plot with UMAP
um = umap.UMAP()
um_x = um.fit_transform(pc_X)

plt.scatter(um_x[:, 0], um_x[:, 1], s = 1, c =np.log(history_close_wide.mean(axis=1)), cmap = 'viridis')
for i, ticker in enumerate(tickers):
    plt.text(um_x[i, 0], um_x[i, 1], ticker, size = 3)

plt.xlabel('um_1')
plt.ylabel('um_2')
plt.show()

um_x_df = pd.DataFrame(um_x)
um_x_df['Ticker'] = tickers

#which tickers have um_1 > 15
outliiers =um_x_df['Ticker'][um_x_df[0]>15]

# are these all losers?
history_close_wide_df = history_close_wide.T

plt.scatter(history_close_wide_df["T"],
            history_close_wide_df['WY'])

cor_mat_outliers = history_close_wide_df[outliiers].corr()
cor_mat_outliers.mean() # not particularly strong, though mostly positive
sns.clustermap(cor_mat_outliers.abs())

# doesnt seem to be by mean price

plt.hist(history_close_wide.mean(axis=1))

history_close_wide.mean(axis=1).min()
history_close_wide.mean(axis=1).max()
#huge disparity

## a big problem here is that we are clustering and whatnot based on price not
# day change, so lets fix that
history_close_wide_indexed = history_close_wide.div(history_close_wide.iloc[:, 0], axis=0)
# in this case, I will not do scaling since its already scaled by start price

pc_2= sklearn.decomposition.PCA()
pc_2X = pc_2.fit_transform(history_close_wide_indexed)

plt.scatter(pc_2X[:, 0], pc_2X[:, 1], c =history_close_wide_indexed.mean(axis=1), cmap = 'viridis')
for i, ticker in enumerate(tickers):
    plt.text(pc_2X[i, 0], pc_2X[i, 1], ticker)
plt.colorbar()
plt.xlabel('PC1')
plt.ylabel('PC2')
plt.show()
# interesting, so PC1 seems to strongly covary with growth

plt.scatter(history_close_wide_indexed.mean(axis=1),
            pc_2X[:, 0])
# a nearly perfect correlation
np.corrcoef(history_close_wide_indexed.mean(axis=1),
            pc_2X[:, 0])
#.9967

#plot with UMAP
um2 = umap.UMAP()
um_2x = um.fit_transform(pc_2X)

plt.scatter(um_2x[:, 0], um_2x[:, 1], c =(history_close_wide_indexed.mean(axis=1)), cmap = 'viridis')
for i, ticker in enumerate(tickers):
    plt.text(um_2x[i, 0], um_2x[i, 1], ticker, size = 6)

plt.colorbar()
plt.xlabel('um_1')
plt.ylabel('um_2')
plt.show()
# looks like a swordfish, neat
# likewise, um_1 seems to be negatively correlated with growth

np.corrcoef(history_close_wide_indexed.mean(axis=1),
            um_2x[:, 0])
#-0.89


#### Next question, what are the odds that a selected stock based on lets say
# pca would ACTUALLY be a winner

## to do this, I will split the PCA into "winners" vs "losers", and see
## if the winners have done better in 2026 than the losers, I suspect
# the answer will be weakly yes
history_close_wide_indexed_classified = history_close_wide_indexed
history_close_wide_indexed['PC1'] = pc_2X[:,0]

history_close_wide_indexed['Class'] = np.where(history_close_wide_indexed['PC1']>2,
                                               "Winner",
                                               "Loser")

winners = history_close_wide_indexed.index[history_close_wide_indexed['Class']=='Winner'].astype(str).tolist()

# ALB, LITE, and WDC
# I think since I havent heard of them this is probably a bad sign

pc_predictions = priceHistoryBatch(tickers = winners, 
                       start_date = '2026-01-01',
                       end_date = '2026-12-31'
                      )

pc_predictions_close = pc_predictions.loc[:,['Close', 'Ticker']].dropna()
pc_predictions_pivot=pc_predictions_close.pivot(columns = 'Ticker', values = 'Close').dropna().T

pc_predictions_pivot_index = pc_predictions_pivot.div(pc_predictions_pivot.iloc[:, 0], axis=0)

pc_predictions_pivot_index.iloc[:,139]
# WDC and LITE continued to grow, while ALB did not 

"""
ALB     0.801976
LITE    1.976095
WDC     2.771360
"""
