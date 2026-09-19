"""
Four new factors for the composite, point-in-time correct: gross
profitability, accruals, asset growth (all Sharadar SF1) and 12-1 momentum
(price panel only). See PREREGISTRATION.md §2 for signs and citations.

None of these existed anywhere in the project before this reset -- verified
by grep (see the pre-registration commit message / advisor consult): the
panel carries `momentum_5/20/60/120` (all full-window sums, no skip-month
form) and `roe/roa/gross_margin/operating_margin/fcf_margin/rnd_intensity`
(ratios already computed by `fundamentals_features_beta.process_ticker`) but
never `gp/assets`, `(netinc-ncfo)/assets`, or an assets growth rate.

POINT-IN-TIME DISCIPLINE -- identical to `build_features_fundamentals_sharadar.py`
and `sweep/issuance.py`, reused rather than reimplemented-and-drifted:

  - `filed_date` is SF1's `date` column, never `calendardate` (the period
    end, which precedes the filing by 4-6 weeks -- using it would leak
    lookahead into every one of these features, exactly the bug that
    motivated the two-decision docstring in build_features_fundamentals_sharadar.py).
  - Only ARQ/ARY (as-reported, never restated MR* dimensions).
  - `assets` is a STOCK/level concept (like `sharesbas` in issuance.py):
    both ARQ and ARY rows feed it, most recent filing <= date.
  - `gp`, `netinc`, `ncfo` are FLOW concepts: ARY only (annual, 10-K/FY),
    matching `FLOW_CONCEPTS` in fundamentals_features_beta.py, to avoid the
    quarterly cumulative-vs-discrete ambiguity that annual-only avoids there.
  - Every merge_asof carries an explicit `_row` position and restores it
    afterward -- `.sort_index()` after `merge_asof` is a no-op (Round 16),
    and this project has shipped that exact bug once already.

DEFINITIONS
    gross_profitability(t) = gp(latest FY filed <= t) / assets(latest filing <= t)
    accruals(t)             = (netinc(latest FY) - ncfo(latest FY)) / assets(latest filing <= t)
    asset_growth(t)         = assets(latest filing <= t) / assets(latest filing <= t-365d) - 1
    momentum_12_1(t)        = close(t-21) / close(t-252) - 1     [skips the most recent month]

OUTPUT
    <MAIN_ROOT>/out/reset2026/quality_factors.parquet
        ticker, date, gross_profitability, accruals, asset_growth, momentum_12_1
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
PRICE_PANEL = MAIN_ROOT / "out" / "features_sharadar_pit.parquet"
OUT_DIR = MAIN_ROOT / "out" / "reset2026"
OUT = OUT_DIR / "quality_factors.parquet"

MOM_SKIP = 21     # trading days -- the "1" in 12-1
MOM_SPAN = 252    # trading days -- the "12"


def log(msg):
    print(msg, flush=True)


def load_sf1_facts():
    df = pd.read_parquet(SF1, columns=["ticker", "dimension", "date", "assets", "gp", "netinc", "ncfo"])
    df = df[df["dimension"].isin(["ARQ", "ARY"])].copy()
    df["filed_date"] = pd.to_datetime(df["date"], errors="coerce").astype("datetime64[ns]")
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
        "gp": _series("gp", annual_only=True),
        "netinc": _series("netinc", annual_only=True),
        "ncfo": _series("ncfo", annual_only=True),
    }


def _asof_value(panel, fact, date_col):
    """merge_asof `fact` (ticker, filed_date, value) onto panel[date_col],
    backward, row order preserved. Returns a float64 array."""
    left = panel[["ticker", date_col]].copy()
    left["_row"] = np.arange(len(panel), dtype=np.int64)
    left = left.rename(columns={date_col: "date"}).sort_values(["date", "ticker"])
    fa = fact.rename(columns={"filed_date": "date"}).sort_values(["date", "ticker"])
    m = (pd.merge_asof(left, fa, on="date", by="ticker", direction="backward")
           .sort_values("_row").reset_index(drop=True))
    assert len(m) == len(panel) and (m["_row"].to_numpy() == np.arange(len(panel))).all(), \
        "quality-factor merge lost or reordered rows"
    return m["value"].to_numpy(np.float64)


def main():
    t0 = time.time()
    log("loading price panel (ticker, date, close) ...")
    panel = pd.read_parquet(PRICE_PANEL, columns=["ticker", "date", "close"])
    panel["ticker"] = panel["ticker"].astype(str)
    panel["date"] = pd.to_datetime(panel["date"])
    panel = panel.sort_values(["ticker", "date"]).reset_index(drop=True)
    log(f"  {len(panel):,} rows, {panel['ticker'].nunique():,} tickers ({time.time()-t0:.0f}s)")

    log("momentum_12_1 (skip-month, per-ticker) ...")
    panel["momentum_12_1"] = (
        panel.groupby("ticker")["close"]
             .transform(lambda s: s.shift(MOM_SKIP) / s.shift(MOM_SPAN) - 1.0)
    )
    log(f"  coverage {panel['momentum_12_1'].notna().mean():.1%} ({time.time()-t0:.0f}s)")

    log("loading SF1 facts (assets/gp/netinc/ncfo, ARQ+ARY, filed-date keyed) ...")
    facts = load_sf1_facts()
    for k, v in facts.items():
        log(f"  {k}: {len(v):,} filed observations, {v['ticker'].nunique():,} tickers")

    log("as-of joins (current) ...")
    assets_cur = _asof_value(panel, facts["assets"], "date")
    gp_cur = _asof_value(panel, facts["gp"], "date")
    netinc_cur = _asof_value(panel, facts["netinc"], "date")
    ncfo_cur = _asof_value(panel, facts["ncfo"], "date")
    log(f"  done ({time.time()-t0:.0f}s)")

    log("as-of join (assets, 365 days back, for asset_growth) ...")
    lookback = pd.DataFrame({
        "ticker": panel["ticker"],
        "date": panel["date"] - pd.Timedelta(days=365),
    })
    assets_prior = _asof_value(lookback, facts["assets"], "date")
    log(f"  done ({time.time()-t0:.0f}s)")

    with np.errstate(divide="ignore", invalid="ignore"):
        gross_profitability = np.where((assets_cur > 0) & np.isfinite(assets_cur) & np.isfinite(gp_cur),
                                        gp_cur / assets_cur, np.nan)
        accruals = np.where((assets_cur > 0) & np.isfinite(assets_cur)
                             & np.isfinite(netinc_cur) & np.isfinite(ncfo_cur),
                             (netinc_cur - ncfo_cur) / assets_cur, np.nan)
        asset_growth = np.where((assets_prior > 0) & np.isfinite(assets_prior) & np.isfinite(assets_cur),
                                 assets_cur / assets_prior - 1.0, np.nan)

    panel["gross_profitability"] = gross_profitability.astype(np.float32)
    panel["accruals"] = accruals.astype(np.float32)
    panel["asset_growth"] = asset_growth.astype(np.float32)
    panel["momentum_12_1"] = panel["momentum_12_1"].astype(np.float32)

    for col in ("gross_profitability", "accruals", "asset_growth", "momentum_12_1"):
        n_inf = int(np.isinf(panel[col].to_numpy(np.float64)).sum())
        if n_inf:
            log(f"  WARNING: {n_inf} inf values in {col}, coercing to NaN")
            panel.loc[~np.isfinite(panel[col]), col] = np.nan
        log(f"  {col}: coverage {panel[col].notna().mean():.1%}, "
            f"median {panel[col].median():.4g}")

    out = panel[["ticker", "date", "gross_profitability", "accruals",
                 "asset_growth", "momentum_12_1"]].copy()
    out["date"] = out["date"].dt.strftime("%Y-%m-%d")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pandas(out, preserve_index=False), OUT)
    log(f"\n-> {OUT}  ({len(out):,} rows, {time.time()-t0:.0f}s total)")


if __name__ == "__main__":
    sys.exit(main())
