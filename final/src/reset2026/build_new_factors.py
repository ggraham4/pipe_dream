"""
Three new candidate factors, per PREREGISTRATION.md's "Trial-count ledger
and next round (2026-09-22)" section, written before this ran. Same PIT
join pattern as quality_factors.py (filed_date-keyed, merge_asof with
row-position assertion) -- no new data pull, all from sf1_fundamentals.parquet
already on disk.

    fcf_yield            = (ncfo(latest FY) + capex(latest FY)) / market_cap
                            (capex already negative in this data --
                            confirmed 88.8% of ARY rows -- so + not -)
    leverage             = debtnc(latest filing) / assets(latest filing)
                            (both stock/level concepts, backward asof,
                            same treatment as `assets` itself)
    profitability_trend  = opinc/revenue(latest FY) - opinc/revenue(FY, 365d prior)

Usage: python3 build_new_factors.py
Output: out/reset2026/new_factors.parquet
"""
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

MAIN_ROOT = Path("/Users/ggraham/pipe_dream/final")
SF1 = MAIN_ROOT / "data" / "sharadar" / "sf1_fundamentals.parquet"
PANEL_PATH = MAIN_ROOT / "out" / "reset2026" / "composite_panel.parquet"
OUT = MAIN_ROOT / "out" / "reset2026" / "new_factors.parquet"


def log(msg):
    print(msg, flush=True)


def load_sf1_facts():
    df = pd.read_parquet(SF1, columns=["ticker", "dimension", "date", "assets", "debtnc",
                                        "ncfo", "capex", "opinc", "revenue"])
    df = df[df["dimension"].isin(["ARQ", "ARY"])].copy()
    df["filed_date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df[df["filed_date"].notna()]
    df["ticker"] = df["ticker"].astype(str)
    is_ary = df["dimension"].eq("ARY")

    def _series(col, annual_only):
        sub = df.loc[df[col].notna() & (is_ary if annual_only else True),
                     ["ticker", "filed_date", col]].copy()
        sub = (sub.sort_values(["ticker", "filed_date"])
                  .drop_duplicates(subset=["ticker", "filed_date"], keep="last"))
        return sub.rename(columns={col: "value"}).reset_index(drop=True)

    return {
        "assets": _series("assets", annual_only=False),
        "debtnc": _series("debtnc", annual_only=False),
        "ncfo": _series("ncfo", annual_only=True),
        "capex": _series("capex", annual_only=True),
        "opinc": _series("opinc", annual_only=True),
        "revenue": _series("revenue", annual_only=True),
    }


def _asof_value(panel, fact, date_col):
    left = panel[["ticker", date_col]].copy()
    left["_row"] = np.arange(len(panel), dtype=np.int64)
    left = left.rename(columns={date_col: "date"}).sort_values(["date", "ticker"])
    fa = fact.rename(columns={"filed_date": "date"}).sort_values(["date", "ticker"])
    m = (pd.merge_asof(left, fa, on="date", by="ticker", direction="backward")
           .sort_values("_row").reset_index(drop=True))
    assert len(m) == len(panel) and (m["_row"].to_numpy() == np.arange(len(panel))).all(), \
        "new-factor merge lost or reordered rows"
    return m["value"].to_numpy(np.float64)


def main():
    t0 = time.time()
    log("loading composite_panel (ticker, date, market_cap) ...")
    panel = pd.read_parquet(PANEL_PATH, columns=["ticker", "date", "market_cap"])
    panel["ticker"] = panel["ticker"].astype(str)
    panel["date"] = pd.to_datetime(panel["date"])
    panel = panel.sort_values(["ticker", "date"]).reset_index(drop=True)
    log(f"  {len(panel):,} rows ({time.time()-t0:.0f}s)")

    log("loading SF1 facts ...")
    facts = load_sf1_facts()

    log("as-of joins (current) ...")
    assets_cur = _asof_value(panel, facts["assets"], "date")
    debtnc_cur = _asof_value(panel, facts["debtnc"], "date")
    ncfo_cur = _asof_value(panel, facts["ncfo"], "date")
    capex_cur = _asof_value(panel, facts["capex"], "date")
    opinc_cur = _asof_value(panel, facts["opinc"], "date")
    revenue_cur = _asof_value(panel, facts["revenue"], "date")

    log("as-of join (opinc/revenue, 365 days back, for profitability_trend) ...")
    lookback = pd.DataFrame({"ticker": panel["ticker"], "date": panel["date"] - pd.Timedelta(days=365)})
    opinc_prior = _asof_value(lookback, facts["opinc"], "date")
    revenue_prior = _asof_value(lookback, facts["revenue"], "date")

    mc = panel["market_cap"].to_numpy(np.float64)
    with np.errstate(divide="ignore", invalid="ignore"):
        fcf_yield = np.where((mc > 0) & np.isfinite(ncfo_cur) & np.isfinite(capex_cur),
                              (ncfo_cur + capex_cur) / mc, np.nan)
        leverage = np.where((assets_cur > 0) & np.isfinite(debtnc_cur),
                             debtnc_cur / assets_cur, np.nan)
        margin_cur = np.where((revenue_cur > 0) & np.isfinite(opinc_cur), opinc_cur / revenue_cur, np.nan)
        margin_prior = np.where((revenue_prior > 0) & np.isfinite(opinc_prior),
                                 opinc_prior / revenue_prior, np.nan)
        profitability_trend = margin_cur - margin_prior

    out = panel[["ticker", "date"]].copy()
    out["fcf_yield"] = fcf_yield.astype(np.float32)
    out["leverage"] = leverage.astype(np.float32)
    out["profitability_trend"] = profitability_trend.astype(np.float32)

    for col in ("fcf_yield", "leverage", "profitability_trend"):
        n_inf = int(np.isinf(out[col].to_numpy(np.float64)).sum())
        if n_inf:
            log(f"  WARNING: {n_inf} inf in {col}, coercing to NaN")
            out.loc[~np.isfinite(out[col]), col] = np.nan
        log(f"  {col}: coverage {out[col].notna().mean():.1%}, median {out[col].median():.4g}")

    out["date"] = out["date"].dt.strftime("%Y-%m-%d")
    pq.write_table(pa.Table.from_pandas(out, preserve_index=False), OUT)
    log(f"\n-> {OUT} ({len(out):,} rows, {time.time()-t0:.0f}s total)")


if __name__ == "__main__":
    main()
