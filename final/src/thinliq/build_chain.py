"""
WO-37: build the unified chain + option features for the window dates into
final/out/thinliq/ (never options_wo25/, never final/data/). Imports
build_option_chain_unified / build_av_options_features unchanged, so every
feature (opt_cw_spread included) is defined exactly as in WO-25.

    /opt/anaconda3/envs/pipe_dream/bin/python final/src/thinliq/build_chain.py [--dates a,b] [--all-dates]

Incremental: a partition is rebuilt only when the store file is newer. All
names in the store are converted (cap2000 and thin); the tier is assigned
downstream from downcap_universe_v2. No forward return is read.
"""
from __future__ import annotations

import argparse
import os

import pandas as pd

import tl_common as T
import build_option_chain_unified as U
import build_av_options_features as F


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dates", default="")
    ap.add_argument("--all-dates", action="store_true", help="include dates outside the 2008-2018 window (not used by either arm)")
    a = ap.parse_args()
    dates = T.monthly_dates(window=not a.all_dates)
    if a.dates:
        want = {pd.Timestamp(x) for x in a.dates.split(",")}
        dates = [d for d in dates if d in want]
    T.CHAIN.mkdir(parents=True, exist_ok=True); T.FCACHE.mkdir(parents=True, exist_ok=True)
    L = T.read_log()
    rates = U.load_rates(T.DATA)
    for d in dates:
        src = T.AV_MONTHLY / f"date={d.date()}.parquet"
        dst = T.CHAIN / f"date={d.date()}.parquet"
        if U.newer(src, dst):
            keep = U.av_keep(L[L.date == str(d.date())])
            df = U.convert_av(src, d, U.rate_on(rates, d), keep)
            U.write_atomic(df, dst)
            T.log(f"chain {d.date()}: {len(df):,} rows, {df.sharadar_ticker.nunique()} names")
        fdst = T.FCACHE / dst.name
        if not fdst.exists() or fdst.stat().st_mtime < dst.stat().st_mtime:
            f = F.partition_features(dst)
            f["source"] = "av_monthly"
            tmp = fdst.with_suffix(".tmp"); f.to_parquet(tmp, index=False); os.replace(tmp, fdst)
    parts = sorted(T.FCACHE.glob("date=*.parquet"))
    X = pd.concat([pd.read_parquet(p) for p in parts], ignore_index=True)
    sv = F.share_volume_20d(T.SEP, X.date.unique())
    X = X.merge(sv, on=["date", "ticker"], how="left")
    X["opt_os_ratio"] = 100 * X._opt_volume / X.shares_vol_20d
    X = X.drop(columns=["shares_vol_20d"]).rename(columns={"_opt_volume": "opt_volume"})
    X.to_parquet(T.FEATS, index=False)
    T.log(f"features: {len(X):,} name-dates on {X.date.nunique()} dates -> {T.FEATS}")


if __name__ == "__main__":
    main()
