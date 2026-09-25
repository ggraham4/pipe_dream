"""
EWMA beta -- remedy for caveat 5 (static 252-day rolling beta lags real
shifts in a stock's risk profile). RiskMetrics-convention 0.94 daily
decay -- a standard, off-the-shelf industry convention (same status as
the 252-day window itself: a convention, not a parameter fit to this
backtest).

beta_i,t = EWMA_Cov(r_i, r_mkt) / EWMA_Var(r_mkt), lambda=0.94 (daily),
seeded with an expanding calculation for the first 60 observations to
avoid an unstable early estimate, causal throughout.

Usage: python3 build_ewma_beta_feature.py
Output: out/reset2026/ewma_beta_feature.parquet
"""
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

MAIN_ROOT = Path("/Users/ggraham/pipe_dream/final")
PANEL_PATH = MAIN_ROOT / "out" / "reset2026" / "composite_panel.parquet"
SPY_CSV = MAIN_ROOT / "scripts" / "td_data_local" / "SPY.csv"
OUT = MAIN_ROOT / "out" / "reset2026" / "ewma_beta_feature.parquet"

LAMBDA = 0.94  # RiskMetrics daily decay convention
MIN_OBS = 60


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def ewma_beta_for_group(stock_ret, mkt_ret, lam=LAMBDA, min_obs=MIN_OBS):
    """EWMA covariance/variance -> beta, via pandas' own `.ewm()` (a
    numerically stable, O(n) recursive filter -- NOT the cumulative
    lam^-t power trick tried first, which overflows/underflows for long
    series: verified AAPL's beta collapsing to ~0 and flipping sign near
    the end of its ~5,000-day history under that version. `.ewm()` avoids
    this because it recurses forward (each step only involves lam and the
    previous state), never raising lam to a large negative or positive
    power directly."""
    xy = pd.Series(stock_ret * mkt_ret)
    y2 = pd.Series(mkt_ret * mkt_ret)
    valid = xy.notna() & y2.notna()
    xy = xy.where(valid)
    y2 = y2.where(valid)
    alpha = 1.0 - lam
    ewm_xy = xy.ewm(alpha=alpha, adjust=False, min_periods=min_obs, ignore_na=True).mean()
    ewm_y2 = y2.ewm(alpha=alpha, adjust=False, min_periods=min_obs, ignore_na=True).mean()
    beta = (ewm_xy / ewm_y2).to_numpy(np.float64).copy()
    n_eff = valid.astype(np.float64).cumsum().to_numpy()
    beta[n_eff < min_obs] = np.nan
    return beta


def main():
    t0 = time.time()
    log("loading composite_panel (ticker, date, close) ...")
    panel = pd.read_parquet(PANEL_PATH, columns=["ticker", "date", "close"])
    panel["date"] = pd.to_datetime(panel["date"])
    panel["ticker"] = panel["ticker"].astype(str)
    panel = panel.sort_values(["ticker", "date"]).reset_index(drop=True)

    spy = pd.read_csv(SPY_CSV, usecols=["date", "close"], parse_dates=["date"]).sort_values("date")
    spy["market_return"] = spy["close"].pct_change()
    spy = spy[["date", "market_return"]].dropna()

    panel["stock_return"] = panel.groupby("ticker")["close"].pct_change()
    panel = panel.merge(spy, on="date", how="left")
    log(f"  {len(panel):,} rows ({time.time()-t0:.0f}s)")

    log("computing EWMA beta per ticker (RiskMetrics lambda=0.94) ...")
    betas = np.empty(len(panel), dtype=np.float64)
    betas[:] = np.nan
    for ticker, idx in panel.groupby("ticker").groups.items():
        idx = idx.to_numpy()
        sr = panel["stock_return"].to_numpy()[idx]
        mr = panel["market_return"].to_numpy()[idx]
        betas[idx] = ewma_beta_for_group(sr, mr)
    panel["beta_ewma"] = betas.astype(np.float32)

    coverage = panel["beta_ewma"].notna().mean()
    log(f"  coverage: {coverage:.1%} ({time.time()-t0:.0f}s)")
    log(f"  distribution: median={np.nanmedian(panel['beta_ewma']):.2f}, "
        f"p10={np.nanpercentile(panel['beta_ewma'], 10):.2f}, "
        f"p90={np.nanpercentile(panel['beta_ewma'], 90):.2f}")

    out = panel[["ticker", "date", "beta_ewma"]].copy()
    out["date"] = out["date"].dt.strftime("%Y-%m-%d")
    pq.write_table(pa.Table.from_pandas(out, preserve_index=False), OUT)
    log(f"\n-> {OUT} ({len(out):,} rows, {time.time()-t0:.0f}s total)")


if __name__ == "__main__":
    main()
