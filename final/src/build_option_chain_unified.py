"""
Unified option chain: Alpha Vantage HISTORICAL_OPTIONS (2008+, volume/OI,
dead issuers) + the DoltHub expanded chain (2019+, daily, no volume/OI).

    python3 build_option_chain_unified.py [--data-dir .../final/data] [--only-av]

Incremental and re-runnable while final/scripts/av_options_pull.py is still
landing data: an output partition is rebuilt only when its source is newer.

OUTPUT  <data-dir>/options_unified/source=<av_monthly|av_weekly|dolthub>/date=YYYY-MM-DD.parquet
        (hive-partitioned; read with pyarrow.dataset or duckdb
         read_parquet('.../**/*.parquet', hive_partitioning=1))

SCHEMA (one row per contract per date)
  date, act_symbol (as-traded), sharadar_ticker, expiration, strike,
  call_put ('Call'/'Put'), bid, ask, vol, delta, gamma, theta, vega, rho,
  volume, open_interest, bid_size, ask_size, last, mark, spot, iv_source
  - vol/delta for AV rows are RECOMPUTED here (Black-Scholes on the bid/ask
    mid, spot = Sharadar closeunadj on the same date, r = 3m Treasury, no
    dividend) -- AV's own IV/greeks are unreliable (DELL 2012: every call
    delta 1.0) and are NOT carried. iv_source = 'bs_mid'. Rows where no IV
    solves (zero bid, mid below intrinsic, <1 day to expiry) get NaN.
    gamma/theta/vega/rho are left NaN for AV rows; nothing downstream reads
    them.
  - DoltHub rows keep the vendor vol/greeks: iv_source = 'dolthub'.
    volume/open_interest are NaN (DoltHub never had them).
  - Where both sources have the same (date, act_symbol), the DoltHub rows are
    DROPPED: the two agree on bid/ask exactly (98-100% on 4 ticker-days,
    2026-09-22) and AV adds volume/OI and ~14x the strikes.
  - spot / sharadar_ticker for DoltHub rows: exact ticker match against the
    point-in-time downcap universe on that date, else NaN.

CADENCE differs by source and era (AV: monthly all names + weekly down-cap,
DoltHub: daily large-cap 2019+). Anything comparing across eras must subsample
to a common grid -- the `source` partition is there to make that easy.

Strikes are UNADJUSTED (as quoted). Moneyness should be computed against
`spot` (unadjusted close on the same date), which needs no split rescale.
"""
from __future__ import annotations

import argparse
import os
import time
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from scipy.stats import norm

FINAL = Path(__file__).resolve().parents[1]
COLS = ["date", "act_symbol", "sharadar_ticker", "expiration", "strike", "call_put",
        "bid", "ask", "vol", "delta", "gamma", "theta", "vega", "rho", "volume",
        "open_interest", "bid_size", "ask_size", "last", "mark", "spot", "iv_source"]


# ------------------------------------------------------------ Black-Scholes
def bs_price(S, K, T, r, sig, is_call):
    sq = sig * np.sqrt(T)
    d1 = (np.log(S / K) + (r + 0.5 * sig * sig) * T) / sq
    d2 = d1 - sq
    call = S * norm.cdf(d1) - K * np.exp(-r * T) * norm.cdf(d2)
    put = K * np.exp(-r * T) * norm.cdf(-d2) - S * norm.cdf(-d1)
    return np.where(is_call, call, put)


def bs_iv(price, S, K, T, r, is_call, lo=0.005, hi=6.0, iters=60):
    """Vectorised bisection. NaN where price is outside the no-arb band."""
    price, S, K, T, r = map(np.asarray, (price, S, K, T, r))
    ok = (price > 0) & (S > 0) & (K > 0) & (T > 0)
    intrinsic = np.where(is_call, np.maximum(S - K * np.exp(-r * T), 0),
                         np.maximum(K * np.exp(-r * T) - S, 0))
    upper = np.where(is_call, S, K * np.exp(-r * T))
    ok &= (price > intrinsic + 1e-9) & (price < upper)
    a = np.full(price.shape, lo)
    b = np.full(price.shape, hi)
    Ss, Ks, Ts, rs = [np.where(ok, x, 1.0) for x in (S, K, T, r)]
    for _ in range(iters):
        m = 0.5 * (a + b)
        p = bs_price(Ss, Ks, Ts, rs, m, is_call)
        hi_mask = p > price
        b = np.where(hi_mask, m, b)
        a = np.where(hi_mask, a, m)
    iv = 0.5 * (a + b)
    iv[~ok | (iv >= hi * 0.999) | (iv <= lo * 1.001)] = np.nan
    return iv


def bs_delta(S, K, T, r, sig, is_call):
    d1 = (np.log(S / K) + (r + 0.5 * sig * sig) * T) / (sig * np.sqrt(T))
    return np.where(is_call, norm.cdf(d1), norm.cdf(d1) - 1.0)


# ------------------------------------------------------------ inputs
def load_rates(data: Path) -> pd.Series:
    r = pd.read_csv(data / "rates" / "treasury_yields.csv", parse_dates=["date"])
    s = r.set_index("date")["y3m"].sort_index() / 100.0
    return s


def rate_on(rates: pd.Series, d: pd.Timestamp) -> float:
    i = rates.index.searchsorted(d, side="right") - 1
    return float(rates.iloc[max(i, 0)])


def newer(src: Path, dst: Path) -> bool:
    return (not dst.exists()) or src.stat().st_mtime > dst.stat().st_mtime


def write_atomic(df: pd.DataFrame, out: Path):
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".tmp")
    df.to_parquet(tmp, index=False)
    os.replace(tmp, out)


# ------------------------------------------------------------ AV
def convert_av(src: Path, d: pd.Timestamp, r: float) -> pd.DataFrame:
    a = pd.read_parquet(src)
    out = pd.DataFrame({
        "date": d.date(), "act_symbol": a.av_symbol, "sharadar_ticker": a.sharadar_ticker,
        "expiration": pd.to_datetime(a.expiration).dt.date, "strike": a.strike,
        "call_put": np.where(a["type"] == "call", "Call", "Put"),
        "bid": a.bid, "ask": a.ask, "volume": a.volume, "open_interest": a.open_interest,
        "bid_size": a.bid_size, "ask_size": a.ask_size, "last": a["last"], "mark": a["mark"],
        "spot": a.closeunadj,
    })
    T = (pd.to_datetime(out.expiration) - d).dt.days.to_numpy() / 365.0
    is_call = out.call_put.to_numpy() == "Call"
    mid = ((out.bid + out.ask) / 2).to_numpy()
    mid = np.where(out.bid.to_numpy() > 0, mid, np.nan)
    S, K = out.spot.to_numpy(float), out.strike.to_numpy(float)
    T = np.where(T >= 1 / 365.0, T, np.nan)
    iv = bs_iv(np.nan_to_num(mid, nan=-1.0), S, K, np.nan_to_num(T, nan=-1.0), r, is_call)
    out["vol"] = iv
    with np.errstate(all="ignore"):
        out["delta"] = np.where(np.isfinite(iv), bs_delta(S, K, np.nan_to_num(T, nan=1.0), r,
                                                          np.nan_to_num(iv, nan=1.0), is_call), np.nan)
    for c in ["gamma", "theta", "vega", "rho"]:
        out[c] = np.nan
    out["iv_source"] = "bs_mid"
    return out[COLS]


# ------------------------------------------------------------ DoltHub
def dolthub_dates(dh_path: Path) -> list:
    f = pq.ParquetFile(dh_path)
    ds = set()
    for i in range(f.num_row_groups):
        ds.update(f.read_row_group(i, columns=["date"]).column(0).to_pylist())
    return sorted(ds)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", type=Path, default=FINAL / "data")
    ap.add_argument("--only-av", action="store_true")
    ap.add_argument("--limit", type=int, default=0, help="max partitions per source (testing)")
    a = ap.parse_args()
    data = a.data_dir
    out_root = data / "options_unified"
    rates = load_rates(data)
    t0 = time.time()

    # ---- AV partitions
    av_dates: dict = {}
    n = 0
    for pas in ["monthly", "weekly"]:
        for src in sorted((data / "alphavantage" / "options" / pas).glob("date=*.parquet")):
            d = pd.Timestamp(src.stem.split("=")[1])
            dst = out_root / f"source=av_{pas}" / f"date={d.date()}.parquet"
            av_dates.setdefault(d.date(), []).append(src)
            if newer(src, dst):
                df = convert_av(src, d, rate_on(rates, d))
                write_atomic(df.drop(columns=["date"]), dst)
                solved = df.vol.notna().mean()
                print(f"av_{pas} {d.date()}: {len(df):,} rows, {df.act_symbol.nunique()} syms, "
                      f"IV solved {solved:.0%}", flush=True)
                n += 1
                if a.limit and n >= a.limit:
                    break
    if a.only_av:
        print(f"done (AV only) {time.time()-t0:.0f}s")
        return

    # ---- DoltHub partitions (dedup against AV on the same date)
    dh_path = data / "options_raw" / "expanded" / "option_chain_expanded_merged.parquet"
    u = pd.read_parquet(data / "sharadar" / "downcap_universe.parquet",
                        columns=["date", "ticker", "closeunadj"])
    u["date"] = pd.to_datetime(u["date"]).dt.date
    u = u[u.date >= pd.Timestamp("2019-01-01").date()]
    ubd = {d: g.set_index("ticker")["closeunadj"] for d, g in u.groupby("date")}
    import pyarrow.dataset as ds_
    dh = ds_.dataset(dh_path)
    n = 0
    for d in dolthub_dates(dh_path):
        dst = out_root / "source=dolthub" / f"date={d}.parquet"
        srcs = av_dates.get(d, [])
        stale = (not dst.exists()) or any(s.stat().st_mtime > dst.stat().st_mtime for s in srcs)
        if not stale:
            continue
        t = dh.to_table(filter=ds_.field("date") == d).to_pandas()
        if srcs:
            have = set(pd.concat([pd.read_parquet(s, columns=["av_symbol"]) for s in srcs]).av_symbol)
            t = t[~t.act_symbol.isin(have)]
        spot = ubd.get(d)
        t["sharadar_ticker"] = np.where(t.act_symbol.isin(spot.index), t.act_symbol, None) if spot is not None else None
        t["spot"] = t.act_symbol.map(spot) if spot is not None else np.nan
        for c in ["volume", "open_interest", "bid_size", "ask_size", "last", "mark"]:
            t[c] = np.nan
        t["iv_source"] = "dolthub"
        write_atomic(t[COLS].drop(columns=["date"]), dst)
        n += 1
        if n % 100 == 0:
            print(f"dolthub {d}: {n} partitions written ({time.time()-t0:.0f}s)", flush=True)
        if a.limit and n >= a.limit:
            break
    print(f"done {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
