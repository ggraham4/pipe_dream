"""
Net share issuance / buyback yield (Sharadar SF1 `sharesbas`).

Round 20 (2026-09-17). Data-sourcing report item #2. `sf1_shares.csv` is
already pulled (`sharadar_pull_shares.py`, for marketcap validation) and
already point-in-time by construction: its `date` column is the FILING date,
not the period end (`sharadar_pull_shares.py` line 47), which is what makes
the merge_asof below point-in-time at all -- same discipline as
`build_features_fundamentals_sharadar.py`'s `filed_date`. `shares_outstanding`
is already loaded into `fundamentals_features_beta.process_ticker` but only
to compute `market_cap`; it has never been exposed as its own trailing-change
feature, which is the actual gap this closes.

DEFINITION
----------
    net_issuance_pct(t) = shares(latest filing <= t)
                           / shares(latest filing <= t - 365 days) - 1

Positive = net issuance (dilution), negative = net buyback. Both ARQ and ARY
rows are used -- unlike the flow concepts (revenue, income), `sharesbas` is a
STOCK/level concept with no cumulative-vs-discrete ambiguity across dimensions,
so there is no reason to drop the quarterly (ARQ) observations the way
`build_features_fundamentals_sharadar.py` does for flows.

SAFETY: the exact bug this project has shipped before. `merge_asof` resets
the index -- sorting the left frame and calling `.sort_index()` on the result
is a no-op (Round 16). Carry an explicit `_row` position and sort back onto
it, with an assertion that no row was lost or reordered, exactly as
`events.build_event_features` does.
"""
from pathlib import Path

import numpy as np
import pandas as pd

from features import PROJECT_ROOT

SF1_SHARES = PROJECT_ROOT / "data" / "sharadar" / "sf1_shares.csv"

NET_ISSUANCE_COL = "net_issuance_pct"


def load_shares(path=None):
    df = pd.read_csv(path or SF1_SHARES)
    df = df[df["dimension"].isin(["ARQ", "ARY"])].copy()
    df["filed_date"] = (pd.to_datetime(df["date"], errors="coerce")
                        .astype("datetime64[ns]"))
    df = df.dropna(subset=["filed_date", "sharesbas"])
    df["ticker"] = df["ticker"].astype(str)
    # A ticker can file both an ARQ and ARY fact on the same date; the level
    # is the same either way, so keep one row per (ticker, filed_date).
    df = (df.sort_values(["ticker", "filed_date"])
            .drop_duplicates(subset=["ticker", "filed_date"], keep="last"))
    return df[["ticker", "filed_date", "sharesbas"]]


def _asof_shares(panel, shares, date_col):
    """One merge_asof of `shares` onto `panel[date_col]`, row-order preserved."""
    left = panel[["ticker", date_col]].copy()
    left["_row"] = np.arange(len(panel), dtype=np.int64)
    left = left.rename(columns={date_col: "date"}).sort_values(["date", "ticker"])
    fa = shares.rename(columns={"filed_date": "date"}).sort_values(["date", "ticker"])
    m = (pd.merge_asof(left, fa, on="date", by="ticker", direction="backward")
           .sort_values("_row").reset_index(drop=True))
    assert len(m) == len(panel) and (m["_row"].to_numpy() == np.arange(len(panel))).all(), \
        "shares merge lost or reordered rows"
    return m["sharesbas"].to_numpy(np.float64)


def build_issuance_features(panel):
    """Add `net_issuance_pct` to a feature panel (ticker, date). Returns a copy."""
    panel = panel.sort_values(["ticker", "date"]).reset_index(drop=True)
    shares = load_shares()

    cur = _asof_shares(panel, shares, "date")
    lookback = (pd.to_datetime(panel["date"]) - pd.Timedelta(days=365)).to_frame("date")
    lookback["ticker"] = panel["ticker"]
    old = _asof_shares(lookback, shares, "date")

    with np.errstate(divide="ignore", invalid="ignore"):
        pct = np.where((old > 0) & np.isfinite(old) & np.isfinite(cur),
                       cur / old - 1.0, np.nan)
    panel[NET_ISSUANCE_COL] = pct.astype(np.float32)
    return panel
