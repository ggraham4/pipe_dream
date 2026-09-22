"""
Mechanical market-beta estimation -- theoretical model addition #1
(2026-09-22, per Gabe's direction): the composite currently has no term
for the single largest, most basic driver of any stock's realized return
-- its exposure to the market itself. Every prediction so far is
implicitly contaminated by market direction the model has no view on
(the physics audit's own point about IC being a within-date, market-
neutral quantity only handles the AVERAGE market effect, not the
DISPERSION that comes from stocks having different betas).

beta_i,t = Cov(r_i, r_mkt) / Var(r_mkt), trailing 252 trading days,
causal (uses only data up to and including date t). This is a mechanical
estimate, not a fitted parameter -- the identical definition used in
every textbook and every commercial risk model since Sharpe (1964) /
Fama-Fisher-Jensen-Roll (1969)'s original event-study market-model
methodology. No lookahead, no tuning: 252 days and SPY as the market
proxy are the standard, off-the-shelf choices, not backtested for fit.

Computed via the rolling-moments identity (fast, no per-group .cov()
call): Cov(x,y) = E[xy] - E[x]E[y], Var(y) = E[y^2] - E[y]^2, all as
rolling means -- algebraically identical to a rolling OLS/covariance,
much cheaper at 4,011 tickers x ~12M rows.

Output: out/reset2026/beta_feature.parquet (ticker, date, beta_252,
market_return -- the same-day SPY return, kept for the excess-return
calculation this feeds into).

Usage: python3 build_beta_feature.py
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
OUT = MAIN_ROOT / "out" / "reset2026" / "beta_feature.parquet"

BETA_WINDOW = 252
MIN_PERIODS = 126  # half-window burn-in, standard convention


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def main():
    t0 = time.time()
    log("loading composite_panel (ticker, date, close) ...")
    panel = pd.read_parquet(PANEL_PATH, columns=["ticker", "date", "close"])
    panel["date"] = pd.to_datetime(panel["date"])
    panel["ticker"] = panel["ticker"].astype(str)
    panel = panel.sort_values(["ticker", "date"]).reset_index(drop=True)
    log(f"  {len(panel):,} rows, {panel['ticker'].nunique():,} tickers ({time.time()-t0:.0f}s)")

    log("loading SPY daily returns (market proxy) ...")
    spy = pd.read_csv(SPY_CSV, usecols=["date", "close"], parse_dates=["date"]).sort_values("date")
    spy["market_return"] = spy["close"].pct_change()
    spy = spy[["date", "market_return"]].dropna()

    log("computing per-ticker daily returns ...")
    panel["stock_return"] = panel.groupby("ticker")["close"].pct_change()

    log("merging market return onto panel ...")
    panel = panel.merge(spy, on="date", how="left")
    n_no_mkt = panel["market_return"].isna().sum()
    log(f"  {n_no_mkt:,} rows with no SPY return that date (outside SPY's own history)")

    log(f"computing rolling {BETA_WINDOW}-day beta via the moments identity ...")
    panel["xy"] = panel["stock_return"] * panel["market_return"]
    panel["y2"] = panel["market_return"] ** 2

    g = panel.groupby("ticker")
    roll = lambda s: s.rolling(BETA_WINDOW, min_periods=MIN_PERIODS)
    e_xy = g["xy"].transform(lambda s: roll(s).mean())
    e_x = g["stock_return"].transform(lambda s: roll(s).mean())
    e_y = g["market_return"].transform(lambda s: roll(s).mean())
    e_y2 = g["y2"].transform(lambda s: roll(s).mean())

    cov_xy = e_xy - e_x * e_y
    var_y = e_y2 - e_y ** 2
    beta = np.where(var_y > 1e-12, cov_xy / var_y, np.nan)
    panel["beta_252"] = beta.astype(np.float32)

    coverage = panel["beta_252"].notna().mean()
    log(f"  coverage: {coverage:.1%} ({time.time()-t0:.0f}s)")
    log(f"  beta distribution: median={np.nanmedian(panel['beta_252']):.2f}, "
        f"p10={np.nanpercentile(panel['beta_252'], 10):.2f}, "
        f"p90={np.nanpercentile(panel['beta_252'], 90):.2f}")

    out = panel[["ticker", "date", "beta_252", "market_return"]].copy()
    out["date"] = out["date"].dt.strftime("%Y-%m-%d")
    pq.write_table(pa.Table.from_pandas(out, preserve_index=False), OUT)
    log(f"\n-> {OUT} ({len(out):,} rows, {time.time()-t0:.0f}s total)")


if __name__ == "__main__":
    main()
