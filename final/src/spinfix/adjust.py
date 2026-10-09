"""WO-57: the WO-54 spin-off correction as a builder library.

Pre-registration: final/models/2026-10-09-spinfix-builder-prereg.md.

Sharadar's split-adjusted `close` books a spin-off ex-date as a large one-day drop. Per event (ticker, exdt):
    m = (1 + r_S) / (1 + r_C)        r_S = Sharadar exdt return, r_C = CRSP `ret` on exdt
and every price of that ticker dated BEFORE exdt is multiplied by m (events compound). The adjusted exdt return
equals CRSP's. Uniform scaling leaves every ratio feature whose window lies entirely before exdt unchanged, so the
adjustment is point-in-time safe for return / price-ratio quantities. Level quantities (market_cap = close x
shares, dollar volume, price floors, eligibility) must keep RAW prices: callers adjust a copy, never the stored
price columns.

Event table: a DataFrame with columns ticker, exdt (datetime64[ns]), m. `load_events()` builds it from WO-54's
CRSP table (history 2007-2019). A forward source (Sharadar ACTIONS) gives dates but not m; see the WO-57 results.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

MAIN = Path("/Users/ggraham/pipe_dream/final")
EVENTS_PQ = MAIN / "data" / "wrds" / "crsp" / "derived" / "spinfix_events.parquet"
THRESH = 0.02
OHLC = ("open", "high", "low", "close")


def load_events(path=EVENTS_PQ, cutoff="2019-12-31", series="close", m_col=None):
    """WO-54 applied events for the split-adjusted `close` series: ticker, exdt, m.
    `m_col` lets a caller pass an events frame that already carries another series' factor."""
    ev = pd.read_parquet(path) if not isinstance(path, pd.DataFrame) else path.copy()
    ev["exdt"] = pd.to_datetime(ev["exdt"]).astype("datetime64[ns]")
    ev = ev[ev["exdt"] <= pd.Timestamp(cutoff)]
    if m_col is None:
        assert series == "close", "only the close-series factor is stored in the WO-54 table"
        ev = ev[ev["applied"].fillna(False).astype(bool)]
        m_col = "m"
    else:
        ev = ev[np.isfinite(ev[m_col].astype(float)) & (np.abs(np.log(ev[m_col].astype(float))) >= THRESH)]
    out = ev[["ticker", "exdt", m_col]].rename(columns={m_col: "m"}).astype({"ticker": str, "m": np.float64})
    return out.sort_values(["ticker", "exdt"]).reset_index(drop=True)


def multiplier(dates, ev_t):
    """Per-row factor M(date) = product of m over events with exdt > date. `dates` sorted datetime64[ns]."""
    d = np.asarray(dates, dtype="datetime64[ns]")
    M = np.ones(len(d), dtype=np.float64)
    for exdt, m in zip(ev_t["exdt"].to_numpy("datetime64[ns]"), ev_t["m"].to_numpy(np.float64)):
        M[: np.searchsorted(d, exdt, side="left")] *= m
    return M


def _segment_events(ticker, dates, by_base):
    """Events of the symbol (WO-47 base name) whose exdt falls inside this segment's date span."""
    base = ticker.split("__post")[0]
    ev = by_base.get(base)
    if ev is None or not len(dates):
        return None
    lo, hi = np.datetime64(dates[0], "ns"), np.datetime64(dates[-1], "ns")
    x = ev["exdt"].to_numpy("datetime64[ns]")
    keep = (x > lo) & (x <= hi)          # an exdt on the first row scales nothing
    return ev[keep] if keep.any() else None


def apply_spin_factors(px, events, cols=OHLC):
    """Copy of `px` (ticker, date, price columns; any row order) with `cols` scaled by M(date) per ticker.
    Rows of tickers without events are returned unchanged. Call AFTER segment_reused_symbols."""
    if events is None or not len(events):
        return px
    by_base = {t: g for t, g in events.groupby("ticker")}
    tick = px["ticker"].astype(str).to_numpy()
    hit = np.isin(np.char.partition(tick.astype(str), "__post")[:, 0], list(by_base))
    if not hit.any():
        return px
    out = px.copy()
    cols = [c for c in cols if c in out.columns]
    sub = out.loc[hit, ["ticker", "date"]]
    for t, g in sub.groupby("ticker", sort=False):
        g = g.sort_values("date")
        d = pd.to_datetime(g["date"]).to_numpy("datetime64[ns]")
        ev = _segment_events(str(t), d, by_base)
        if ev is None:
            continue
        M = multiplier(d, ev)
        for c in cols:
            out.loc[g.index, c] = out.loc[g.index, c].to_numpy(np.float64) * M
    return out


def adjust_month_ends(me, events_adj, price_col="closeadj"):
    """build_seas month-end table (ticker, date, ym, closeadj): scale month-end prices dated before exdt by m_adj.
    Apply AFTER splice_month_ends."""
    if events_adj is None or not len(events_adj):
        return me
    return apply_spin_factors(me, events_adj, cols=(price_col,))
