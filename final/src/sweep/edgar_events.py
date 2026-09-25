"""
SEC EDGAR 8-K event flags: going-concern language, Item 4.02 restatements,
Item 5.02 executive departures.

Round 20 (2026-09-18). Data-sourcing report item #8. Raw data from
`scripts/edgar_8k_events_pull.py` -- CIK-keyed, full 2007-2026 history, no
lag needed (filing date is the public date, unlike FINRA short interest).

FRAMING, per the report: these are downside-protection / avoid-blowup
features for a no-stop-loss, 40-day-hold model, not alpha features. A
window flag says "something happened recently that a cautious holder would
want to know about," not "this will outperform."

CIK COVERAGE IS INCOMPLETE, STATED HONESTLY
------------------------------------------------------------------
Ticker->CIK mapping reuses this project's existing two maps
(`scripts/fundamentals_raw/_ticker_cik_map.csv`, ~1,645 current tickers;
`scripts/fundamentals_raw_delisted/_ticker_cik_map.csv`, ~212 delisted
tickers, many unmatched). Combined this covers roughly half the ~4,011-name
PIT universe -- the ~264 Sharadar gap tickers without either project's own
CIK lookup are NOT covered here. This is the same class of known,
documented gap as "not every gap ticker has Sharadar coverage" elsewhere in
this project (see AGENTS.md "Known gaps"), not a new defect. A ticker with
no CIK match gets NaN on all three columns, same as any other missing-data
ticker -- XGBoost handles that natively, and it is not distinguishable from
"nothing happened" at the model-input level, which is an honest limitation
worth fixing later (build the delisted CIK map out further) rather than
now.

TRAILING WINDOWS, deliberately different per event's persistence:
    filed_going_concern_120d   120 calendar days -- solvency doubt is a
                                slow-moving concern, matches roughly one
                                quarter of relevance
    filed_item402_240d         240 calendar days -- a restatement casts a
                                longer shadow (re-audits, litigation risk)
    filed_item502_60d          60 calendar days -- exec departures are
                                frequent and mostly routine; a short window
                                avoids flagging most of the panel most of
                                the time
"""
import re

import numpy as np
import pandas as pd

from features import PROJECT_ROOT

RAW = PROJECT_ROOT / "data" / "edgar" / "8k_events_raw.csv"
CIK_MAPS = [
    PROJECT_ROOT / "scripts" / "fundamentals_raw" / "_ticker_cik_map.csv",
    PROJECT_ROOT / "scripts" / "fundamentals_raw_delisted" / "_ticker_cik_map.csv",
]

WINDOWS = {
    "going_concern": ("filed_going_concern_120d", 120),
    "item_402_restatement": ("filed_item402_240d", 240),
    "item_502_departure": ("filed_item502_60d", 60),
}
EDGAR_EVENTS_ALL = [v[0] for v in WINDOWS.values()]


def _load_cik_map():
    frames = []
    for p in CIK_MAPS:
        if p.exists():
            d = pd.read_csv(p, dtype=str)
            d = d[d["cik"].notna() & (d["status"].str.lower() == "matched")]
            frames.append(d[["ticker", "cik"]])
    m = pd.concat(frames, ignore_index=True).drop_duplicates("ticker")
    # SEC CIKs are zero-padded to 10 digits in some sources, bare ints in
    # others -- normalize to bare int string so both sides of the join match.
    m["cik"] = m["cik"].astype(str).str.lstrip("0").replace("", "0")
    return dict(zip(m["ticker"], m["cik"]))


def _load_events():
    df = pd.read_csv(RAW, dtype={"cik": str})
    df["cik"] = df["cik"].str.lstrip("0").replace("", "0")
    df["file_date"] = pd.to_datetime(df["file_date"])
    return df


def _asof_flag(panel, events_dates, window_days):
    """1.0 if an event date falls within `window_days` before the panel
    date, else 0.0 (never NaN for a ticker that HAS a CIK -- absence of an
    event is a real, known zero, not missing data)."""
    if len(events_dates) == 0:
        return np.zeros(len(panel), dtype=np.float32)
    ev = np.sort(np.asarray(events_dates, dtype="datetime64[ns]"))
    dates = panel["date"].to_numpy("datetime64[ns]")
    # most recent event on or before each panel date
    idx = np.searchsorted(ev, dates, side="right") - 1
    out = np.zeros(len(panel), dtype=np.float32)
    ok = idx >= 0
    gap_days = (dates[ok] - ev[idx[ok]]) / np.timedelta64(1, "D")
    out[ok] = (gap_days <= window_days).astype(np.float32)
    return out


def build_edgar_event_features(panel):
    """Add EDGAR_EVENTS_ALL to a feature panel (ticker, date). Returns a copy."""
    panel = panel.sort_values(["ticker", "date"]).reset_index(drop=True)
    cik_map = _load_cik_map()
    events = _load_events()

    # Pre-group event dates by (cik, flag) ONCE -- looping the full 344k-row
    # events frame per ticker (x4,011 tickers x3 flags) would refilter the
    # same table 12,000+ times for no reason.
    ev_by_cik_flag = {
        key: g["file_date"].to_numpy("datetime64[ns]")
        for key, g in events.groupby(["cik", "flag"])
    }

    for col in EDGAR_EVENTS_ALL:
        panel[col] = np.nan

    for tk, g in panel.groupby("ticker", sort=False):
        cik = cik_map.get(tk)
        if cik is None:
            continue
        idx = g.index
        for flag, (col, window) in WINDOWS.items():
            ev_dates = ev_by_cik_flag.get((cik, flag), np.array([], dtype="datetime64[ns]"))
            panel.loc[idx, col] = _asof_flag(g, ev_dates, window)
    return panel
