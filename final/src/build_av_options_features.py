"""
Per-(date, ticker) option features from the unified chain
(build_option_chain_unified.py), keyed on Sharadar ticker so they join the
point-in-time panel directly.

    python3 build_av_options_features.py [--data-dir .../final/data] [--out-dir .../final/out]

Incremental: one cached feature file per unified partition under
<data-dir>/options_features/<source>/date=....parquet, rebuilt only when its
partition is newer; the concatenation is written to
<out-dir>/av_options_features.parquet.

Every feature is a published, mechanism-backed option signal (per the
2026-09-18 foundation reset: hunt named anomalies, not transforms):

  shape (same definitions as build_options_features.py, ~56 DTE expiry)
    opt_atm_iv, opt_rr25 (put25 - call25), opt_bfly25, opt_term_slope
  Cremers & Weinbaum (2010) -- call-minus-put IV at matched strikes,
    OI-weighted; high spread predicts higher returns
    opt_cw_spread
  Pan & Poteshman (2006) -- put/call volume ratio; high predicts lower returns
    opt_pc_vol_ratio  = put vol / (put + call vol)
    opt_pc_oi_ratio   = put OI  / (put + call OI)
  Johnson & So (2012) -- option/stock volume ratio; high predicts lower returns
    opt_os_ratio      = 100 * option volume / 20d-median share volume
  liquidity (thin-liquidity hypothesis; also the cost side of any trade)
    opt_log_oi, opt_log_vol, opt_spread_atm (median rel. spread, |delta| .3-.7)

Only AV rows carry volume/OI; DoltHub-only rows get NaN for those columns.
Acceptance checks printed at the end (Gate A7c: expected values named first):
  rr25 > 0 on most name-dates (puts richer than calls);
  pc_vol_ratio median ~0.3-0.45 (equity options are call-heavy by volume);
  cw_spread median slightly negative. Measured 2008: -2.2 vol pts, wider than
  the literature ~-1 because BS here ignores dividends (forward overstated ->
  put IV up / call IV down). Near-uniform offset; irrelevant after rank_z.
"""
from __future__ import annotations

import argparse
import os
import time
from pathlib import Path

import numpy as np
import pandas as pd

FINAL = Path(__file__).resolve().parents[1]
TARGET_DTE, DTE_LO, DTE_HI = 56, 20, 100

FEATURES = ["opt_atm_iv", "opt_rr25", "opt_bfly25", "opt_term_slope", "opt_cw_spread",
            "opt_pc_vol_ratio", "opt_pc_oi_ratio", "opt_os_ratio", "opt_log_oi",
            "opt_log_vol", "opt_spread_atm"]


def iv_at_delta(g: pd.DataFrame, target: float) -> float:
    d = g["delta"].to_numpy(float); v = g["vol"].to_numpy(float)
    ok = np.isfinite(d) & np.isfinite(v) & (v > 1e-4) & (v < 5.0)
    if ok.sum() < 2:
        return np.nan
    d, v = d[ok], v[ok]
    o = np.argsort(d); d, v = d[o], v[o]
    if target < d[0] or target > d[-1]:
        return np.nan
    return float(np.interp(target, d, v))


def name_features(g: pd.DataFrame, d: pd.Timestamp) -> dict:
    out = dict.fromkeys(FEATURES, np.nan)
    dte = (pd.to_datetime(g.expiration) - d).dt.days
    band = g[(dte >= DTE_LO) & (dte <= DTE_HI)]
    if len(band):
        bdte = (pd.to_datetime(band.expiration) - d).dt.days
        exps = band.expiration.unique()
        edte = np.array([(pd.Timestamp(e) - d).days for e in exps])
        near = exps[np.argmin(np.abs(edte - TARGET_DTE))]
        gg = band[band.expiration == near]
        calls, puts = gg[gg.call_put == "Call"], gg[gg.call_put == "Put"]
        atm, c25, p25 = iv_at_delta(calls, 0.50), iv_at_delta(calls, 0.25), iv_at_delta(puts, -0.25)
        out["opt_atm_iv"] = atm
        if np.isfinite(p25) and np.isfinite(c25):
            out["opt_rr25"] = p25 - c25
            if np.isfinite(atm):
                out["opt_bfly25"] = (p25 + c25) / 2 - atm
        if len(exps) > 1:
            lo_e, hi_e = exps[np.argmin(edte)], exps[np.argmax(edte)]
            a = iv_at_delta(band[(band.expiration == hi_e) & (band.call_put == "Call")], 0.50)
            b = iv_at_delta(band[(band.expiration == lo_e) & (band.call_put == "Call")], 0.50)
            if np.isfinite(a) and np.isfinite(b):
                out["opt_term_slope"] = a - b
    # Cremers-Weinbaum: all expiries, matched strikes, OI-weighted
    m = g.pivot_table(index=["expiration", "strike"], columns="call_put",
                      values=["vol", "open_interest"], aggfunc="first")
    if (("vol", "Call") in m and ("vol", "Put") in m
            and ("open_interest", "Call") in m and ("open_interest", "Put") in m):
        sp = (m[("vol", "Call")] - m[("vol", "Put")])
        w = m[("open_interest", "Call")].fillna(0) + m[("open_interest", "Put")].fillna(0)
        ok = sp.notna() & (w > 0)
        if ok.any():
            out["opt_cw_spread"] = float(np.average(sp[ok], weights=w[ok]))
    vol_c = g.loc[g.call_put == "Call", "volume"].sum(min_count=1)
    vol_p = g.loc[g.call_put == "Put", "volume"].sum(min_count=1)
    oi_c = g.loc[g.call_put == "Call", "open_interest"].sum(min_count=1)
    oi_p = g.loc[g.call_put == "Put", "open_interest"].sum(min_count=1)
    if np.isfinite(vol_c) and np.isfinite(vol_p):
        tv = vol_c + vol_p
        out["opt_log_vol"] = np.log1p(tv)
        if tv > 0:
            out["opt_pc_vol_ratio"] = vol_p / tv
    if np.isfinite(oi_c) and np.isfinite(oi_p):
        toi = oi_c + oi_p
        out["opt_log_oi"] = np.log1p(toi)
        if toi > 0:
            out["opt_pc_oi_ratio"] = oi_p / toi
    nm = g[(g.delta.abs() >= 0.3) & (g.delta.abs() <= 0.7) & (g.bid > 0)]
    if len(nm):
        out["opt_spread_atm"] = float(((nm.ask - nm.bid) / ((nm.ask + nm.bid) / 2)).median())
    out["_opt_volume"] = (vol_c + vol_p) if np.isfinite(vol_c) and np.isfinite(vol_p) else np.nan
    return out


def share_volume_20d(stocks_dir: Path, dates) -> pd.DataFrame:
    dates = sorted(pd.to_datetime(pd.Series(dates)).unique())
    out = []
    for ym in sorted({d.strftime("%Y-%m") for d in dates}):
        prev = (pd.Timestamp(ym + "-01") - pd.Timedelta(days=1)).strftime("%Y-%m")
        fs = [stocks_dir / f"{m}.parquet" for m in (prev, ym) if (stocks_dir / f"{m}.parquet").exists()]
        s = pd.concat([pd.read_parquet(f, columns=["ticker", "date", "volume", "close", "closeunadj"]) for f in fs])
        s["date"] = pd.to_datetime(s.date)
        s = s.sort_values(["ticker", "date"])
        s["sh"] = s.volume * s.close / s.closeunadj
        s["shares_vol_20d"] = s.groupby("ticker").sh.transform(lambda x: x.rolling(20, min_periods=10).median())
        want = [d for d in dates if d.strftime("%Y-%m") == ym]
        out.append(s[s.date.isin(want)][["date", "ticker", "shares_vol_20d"]])
    return pd.concat(out, ignore_index=True)


def partition_features(src: Path) -> pd.DataFrame:
    d = pd.Timestamp(src.stem.split("=")[1])
    t = pd.read_parquet(src)
    t = t[t.sharadar_ticker.notna()]
    rows = []
    for tk, g in t.groupby("sharadar_ticker", sort=False):
        f = name_features(g, d)
        f["date"], f["ticker"], f["source"] = d, tk, src.parent.name.split("=")[1]
        rows.append(f)
    return pd.DataFrame(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", type=Path, default=FINAL / "data")
    ap.add_argument("--out-dir", type=Path, default=FINAL / "out")
    ap.add_argument("--include-dolthub", action="store_true",
                    help="also featurise the 2019+ DoltHub daily chain (slow; the "
                         "pre-registered model uses av_monthly only)")
    a = ap.parse_args()
    uni = a.data_dir / "options_unified"
    cache = a.data_dir / "options_features"
    t0 = time.time()
    n = 0
    srcs = sorted(uni.glob("source=*/date=*.parquet"))
    if not a.include_dolthub:
        srcs = [x for x in srcs if x.parent.name != "source=dolthub"]
    for src in srcs:
        dst = cache / src.parent.name / src.name
        if dst.exists() and dst.stat().st_mtime >= src.stat().st_mtime:
            continue
        f = partition_features(src)
        dst.parent.mkdir(parents=True, exist_ok=True)
        tmp = dst.with_suffix(".tmp"); f.to_parquet(tmp, index=False); os.replace(tmp, dst)
        n += 1
        if n % 20 == 0:
            print(f"  {n} partitions ({time.time()-t0:.0f}s)", flush=True)
    parts = sorted(cache.glob("source=*/date=*.parquet"))
    if not a.include_dolthub:
        parts = [x for x in parts if x.parent.name != "source=dolthub"]
    if not parts:
        print("no partitions yet"); return
    F = pd.concat([pd.read_parquet(p) for p in parts], ignore_index=True)
    # AV wins over DoltHub on the same (date, ticker); monthly over weekly.
    pri = {"av_monthly": 0, "av_weekly": 1, "dolthub": 2}
    F = F.sort_values(by=["date", "ticker", "source"], key=lambda s: s.map(pri) if s.name == "source" else s)
    F = F.drop_duplicates(["date", "ticker"], keep="first")
    # Option/stock volume ratio. Contracts are on 100 AS-TRADED shares, so the
    # denominator is as-traded share volume: Sharadar SEP volume is
    # split-adjusted, so shares_traded = volume * close / closeunadj.
    # 20-trading-day trailing median ending ON the date (same-day EOD data,
    # as is the option volume itself).
    sv = share_volume_20d(a.data_dir / "sharadar" / "panel" / "stocks", F.date.unique())
    F = F.merge(sv, on=["date", "ticker"], how="left")
    F["opt_os_ratio"] = 100 * F._opt_volume / F.shares_vol_20d
    F = F.drop(columns=["_opt_volume", "shares_vol_20d"])
    a.out_dir.mkdir(parents=True, exist_ok=True)
    F.to_parquet(a.out_dir / "av_options_features.parquet", index=False)
    print(f"wrote {len(F):,} rows, {F.date.nunique()} dates, {F.ticker.nunique()} tickers "
          f"({n} partitions rebuilt, {time.time()-t0:.0f}s)")
    q = F[FEATURES].describe(percentiles=[.5]).T[["count", "mean", "50%"]]
    print(q.to_string())
    print(f"CHECK rr25>0 share: {(F.opt_rr25 > 0).mean():.2f} of non-null "
          f"{(F.opt_rr25.dropna() > 0).mean():.2f}   (expect majority)")
    print(f"CHECK pc_vol median: {F.opt_pc_vol_ratio.median():.2f}   (expect ~0.3-0.45)")
    print(f"CHECK cw_spread median: {F.opt_cw_spread.median():.4f}   (expect slightly <0)")


if __name__ == "__main__":
    main()
