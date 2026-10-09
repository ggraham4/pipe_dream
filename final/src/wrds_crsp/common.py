"""Shared loaders for WO-51 Phases 2/3 (CRSP daily, delistings, crosswalk attach, market calendar)."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from wrdsdb import CRSP_DIR, LINK_DIR, MAIN  # noqa: E402

FINAL = MAIN / "final"
R26 = FINAL / "out" / "reset2026"
SPY_CSV = FINAL / "scripts" / "td_data_local" / "SPY.csv"
OHLC_DIRS = [FINAL / "scripts" / "td_data_sharadar", FINAL / "scripts" / "td_data_sharadar_downcap_v2"]
REPO = Path(__file__).resolve().parents[3]
OUTDIR = REPO / "final" / "out" / "wrds_crsp"
DERIVED = CRSP_DIR / "derived"          # per-row tables carrying CRSP values: parquet, never committed
START, END = pd.Timestamp("2007-01-02"), pd.Timestamp("2019-12-31")
HOLDOUT = pd.Timestamp("2020-01-01")

# icw8 = PRODUCTION_WEIGHTS as of the WO-6 read-out (hard-coded so the 2026-10-07 icw5_seas switch cannot move it)
ICW8 = {
    "momentum_12_1": 0.0497,
    "pct_from_high_252": 0.0130,
    "volatility_60": -0.0130,
    "gross_profitability": 0.5956,
    "accruals": -0.1627,
    "net_issuance_pct": -0.1399,
    "days_to_next_filing_seasonal": -0.0130,
    "short_interest_days_to_cover": -0.0130,
}


def crosswalk() -> pd.DataFrame:
    return pd.read_parquet(LINK_DIR / "permno_sharadar.parquet")


def attach(df: pd.DataFrame, xw: pd.DataFrame) -> np.ndarray:
    """permno (float, NaN if unmapped) for each (ticker, date) row of df."""
    u = df[["ticker", "date"]].reset_index(drop=True).reset_index()
    u["ticker"] = u["ticker"].astype(str)
    u["date"] = pd.to_datetime(u["date"]).astype("datetime64[ns]")
    u = u.sort_values("date")
    x = xw[["ticker", "permno", "valid_from", "valid_to"]].copy()
    x["ticker"] = x["ticker"].astype(str)
    for c in ("valid_from", "valid_to"):
        x[c] = pd.to_datetime(x[c]).astype("datetime64[ns]")
    x = x.sort_values("valid_from")
    m = pd.merge_asof(u, x, left_on="date", right_on="valid_from", by="ticker", direction="backward")
    m.loc[m.date > m.valid_to, "permno"] = np.nan
    return m.sort_values("index").permno.to_numpy(np.float64)


EXIT_CUTOFF = pd.Timestamp("2020-03-31")   # 2020Q1 exit legs of late-2019 labels only (pre-reg "Data")
P2_CUTOFF = END                           # Phase 2 reads nothing after 2019-12-31


def load_dsf(years=range(2007, 2021), cols=("permno", "date", "ret", "retx", "prc", "openprc", "cfacpr"),
             permnos=None, cutoff=EXIT_CUTOFF) -> pd.DataFrame:
    filt = [("permno", "in", sorted(int(x) for x in permnos))] if permnos is not None else None
    d = pd.concat([pd.read_parquet(CRSP_DIR / f"dsf_{y}.parquet", columns=list(cols), filters=filt) for y in years],
                  ignore_index=True)
    d["date"] = pd.to_datetime(d["date"]).astype("datetime64[ns]")
    d = d[d.date <= cutoff]
    assert d.date.max() <= cutoff
    return d.sort_values(["permno", "date"]).reset_index(drop=True)


def load_delist() -> pd.DataFrame:
    d = pd.read_parquet(CRSP_DIR / "dsedelist.parquet",
                        columns=["permno", "dlstdt", "dlstcd", "dlret", "dlretx", "nwperm"])
    d["dlstdt"] = pd.to_datetime(d.dlstdt).astype("datetime64[ns]")
    assert not d.permno.duplicated().any()
    return d.set_index("permno")


def _read_csv_until(path, cutoff, usecols):
    """Read a date-sorted OHLC CSV line by line and stop at the first row dated after cutoff,
    so no row past the era is ever parsed."""
    lim = cutoff.strftime("%Y-%m-%d")
    with open(path) as f:
        hdr = f.readline().rstrip("\n").split(",")
        idx = [hdr.index(c) for c in usecols]
        rows = []
        for line in f:
            if line[:10] > lim:
                break
            v = line.rstrip("\n").split(",")
            rows.append([v[i] for i in idx])
    g = pd.DataFrame(rows, columns=usecols)
    g["date"] = pd.to_datetime(g["date"]).astype("datetime64[ns]")
    for c in usecols:
        if c != "date":
            g[c] = pd.to_numeric(g[c], errors="coerce")
    assert g.empty or g.date.max() <= cutoff
    return g


def market_calendar(cutoff=EXIT_CUTOFF) -> np.ndarray:
    s = _read_csv_until(SPY_CSV, cutoff, ["date"])
    return np.sort(s.date.unique()).astype("datetime64[ns]")


def ohlc_path(t):
    for d in OHLC_DIRS:
        f = d / f"{t}.csv"
        if f.exists():
            return f
    return None


def load_ohlc(tickers, cutoff=EXIT_CUTOFF, cols=("date", "open", "close")) -> dict[str, pd.DataFrame]:
    out = {}
    for t in tickers:
        f = ohlc_path(t)
        if f is not None:
            g = _read_csv_until(f, cutoff, list(cols))
            if not g.date.is_monotonic_increasing:
                g = g.sort_values("date").reset_index(drop=True)
            out[t] = g
    return out
