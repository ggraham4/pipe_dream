"""
FINRA consolidated short interest features.

Round 20 (2026-09-18). Data-sourcing report item #7. Raw data from
`scripts/finra_short_interest_pull.py` -- see that script's docstring for
the coverage/era caveats (2020-04-15 hard floor, no true daily cap since
it's a direct free pull, not AV).

POINT-IN-TIME: the raw file only carries `settlementDate`. FINRA Rule 4560
publishes short interest a fixed ~8 business days after each settlement
date (the report's own "7-9 business days" estimate; 8 is the documented
midpoint used by FINRA's own reporting calendar) -- `filed_date` here is
settlementDate + 8 business days, and THAT is what the merge_asof below
uses as the availability timestamp, never settlementDate itself.

TWO CANDIDATES, deliberately simple for a first pass:
    short_interest_days_to_cover   level  -- API's own daysToCoverQuantity
    short_interest_chg_pct         change -- API's own changePercent (SUSIR-
                                    style: unexpected-ness of the raw pct
                                    change is the literature's actual claim,
                                    but this is the tradeable, unadorned
                                    version -- refine only if this nominates)
"""
import numpy as np
import pandas as pd

from features import PROJECT_ROOT

RAW = PROJECT_ROOT / "data" / "finra" / "short_interest_raw.csv"

SHORT_INTEREST_ALL = ["short_interest_days_to_cover", "short_interest_chg_pct"]


def load_short_interest(path=None):
    df = pd.read_csv(path or RAW)
    df["settlementDate"] = pd.to_datetime(df["settlementDate"])
    # FINRA Rule 4560: public ~8 BUSINESS days after settlement.
    df["filed_date"] = (df["settlementDate"]
                        + pd.offsets.BDay(8)).astype("datetime64[ns]")
    df["ticker"] = df["symbolCode"].astype(str)
    df["short_interest_days_to_cover"] = pd.to_numeric(
        df["daysToCoverQuantity"], errors="coerce")
    df["short_interest_chg_pct"] = pd.to_numeric(
        df["changePercent"], errors="coerce")
    df = (df.sort_values(["ticker", "filed_date"])
            .drop_duplicates(subset=["ticker", "filed_date"], keep="last"))
    return df[["ticker", "filed_date"] + SHORT_INTEREST_ALL]


def _asof(panel, si, date_col="date"):
    left = panel[["ticker", date_col]].copy()
    left["_row"] = np.arange(len(panel), dtype=np.int64)
    left = left.rename(columns={date_col: "date"}).sort_values(["date", "ticker"])
    fa = si.rename(columns={"filed_date": "date"}).sort_values(["date", "ticker"])
    m = (pd.merge_asof(left, fa, on="date", by="ticker", direction="backward")
           .sort_values("_row").reset_index(drop=True))
    assert len(m) == len(panel) and (m["_row"].to_numpy() == np.arange(len(panel))).all(), \
        "short interest merge lost or reordered rows"
    return m


def build_short_interest_features(panel):
    """Add SHORT_INTEREST_ALL to a feature panel (ticker, date). Returns a copy."""
    panel = panel.sort_values(["ticker", "date"]).reset_index(drop=True)
    si = load_short_interest()
    m = _asof(panel, si)
    for c in SHORT_INTEREST_ALL:
        panel[c] = m[c].to_numpy(np.float32)
    return panel
