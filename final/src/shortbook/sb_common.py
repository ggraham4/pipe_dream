"""WO-60 short book: shared paths, constants and the outcome-free panel loader.

HARD RULES (WO-60): no code here can place, modify or cancel an order. No outcome
(forward return) after 2019 is read: signal dates are cut at SIG_HI = 2019-10-24
BEFORE any return column is joined (40d labels from later dates mature in 2020).
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
SRC = HERE.parent
WT_FINAL = HERE.parents[1]
MAIN = Path("/Users/ggraham/pipe_dream/final")
R26 = MAIN / "out" / "reset2026"
PANEL = R26 / "composite_panel_v2.parquet"
OLD_PANEL = R26 / "composite_panel.parquet"
OUTCOME = R26 / "outcome_cache_v2.parquet"
BETA = R26 / "beta_feature_v2.parquet"
SEAS_EXT = Path("/Users/ggraham/pipe_dream/.claude/worktrees/wo24-construction-drag/final/out/audit/seas_factor_ext.parquet")
SPY_BENCH = Path("/Users/ggraham/pipe_dream/.claude/worktrees/agent-a224b0b3e3e4eaba0/final/out/pool/bench/SPY.parquet")
SEP_DIR = MAIN / "data" / "sharadar" / "panel" / "stocks"
TM = MAIN / "data" / "sharadar" / "tickers_master.csv"
WRDS = MAIN / "data" / "wrds"
OUT_BIG = MAIN / "out" / "shortbook"            # gitignored large intermediates (main checkout)
OUT = WT_FINAL / "out" / "shortbook"            # small committed json outputs (worktree)

ERA_LO = pd.Timestamp("2007-01-01")
SIG_HI = pd.Timestamp("2019-10-24")             # last signal date whose 40d label matures in 2019
PRICE_HI = pd.Timestamp("2019-12-31")           # no price/outcome data after this is ever read
H = 40
ANN = 252.0 / H
COST = 0.0015                                    # 15bp per side on traded notional
SEED0 = 60000

sys.path.insert(0, str(SRC / "reset2026"))
import ic_weighted_composite as ICW  # noqa: E402

W5 = dict(ICW.PRODUCTION_WEIGHTS_V5_SEAS)
FT = list(W5)
PANEL_FACTORS = [f for f in FT if f != "seas"]


def log(m):
    print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)


def filt(path, lo, hi):
    import pyarrow.parquet as pq
    t = str(pq.read_schema(path).field("date").type)
    if "string" in t:
        return [("date", ">=", lo.date().isoformat()), ("date", "<=", hi.date().isoformat())]
    return [("date", ">=", lo), ("date", "<=", hi)]


def _dt(df):
    df["date"] = pd.to_datetime(df["date"]).astype("datetime64[ns]")
    df["ticker"] = df["ticker"].astype(str)
    return df


def load_features(tier: str) -> pd.DataFrame:
    """Outcome-free tier universe 2007-01-01..SIG_HI: v2 eligible_<tier>, v2 universe rule
    (old 4,011-ticker grid OR not a SPAC), the five icw5_seas inputs (seas = WO-18/WO-23 ext),
    plus close/open/volatility_60/sector/market_cap. No forward-return column is loaded."""
    cols = ["ticker", "date", "close", "open", "market_cap", "volatility_60", "sector", f"eligible_{tier}"] + PANEL_FACTORS
    p = pd.read_parquet(PANEL, columns=cols, filters=filt(PANEL, ERA_LO, SIG_HI))
    p = _dt(p)
    assert "forward_return_tradable_40" not in p.columns and "forward_return_40" not in p.columns
    p = p[(p["date"] >= ERA_LO) & (p["date"] <= SIG_HI)]
    old_t = set(pd.read_parquet(OLD_PANEL, columns=["ticker"])["ticker"].astype(str).unique())
    tm = pd.read_csv(TM, dtype=str, usecols=["ticker", "sicindustry"]).drop_duplicates("ticker")
    spac = set(tm.loc[tm["sicindustry"].fillna("").str.contains("Blank Check"), "ticker"])
    p = p[p["ticker"].isin(old_t) | ~p["ticker"].isin(spac)]
    all_dates = sorted(p["date"].unique())
    p = p[p[f"eligible_{tier}"].astype(bool)].drop(columns=[f"eligible_{tier}"])
    s = pd.read_parquet(SEAS_EXT, columns=["ticker", "date", "seas"], filters=filt(SEAS_EXT, ERA_LO, SIG_HI))
    s = _dt(s)
    n = len(p)
    p = p.merge(s, on=["ticker", "date"], how="left")
    assert len(p) == n
    p = p.sort_values(["date", "ticker"]).reset_index(drop=True)
    assert p["date"].max() <= SIG_HI, "HOLD-OUT BREACH"
    return p, [pd.Timestamp(d) for d in all_dates]


def rank_z(df, col):
    r = df.groupby("date")[col].rank(method="average")
    n = df[col].notna().groupby(df["date"]).transform("sum")
    return ((r - 1.0) / (n - 1.0) - 0.5).where(n >= 2)


def score_icw5(U: pd.DataFrame) -> np.ndarray:
    """== ICW.compute_composite_ic_weighted(per date, PRODUCTION_WEIGHTS_V5_SEAS)."""
    num = np.zeros(len(U)); den = np.zeros(len(U)); cov = np.zeros(len(U), dtype=int)
    for c, w in W5.items():
        rz = rank_z(U, c).to_numpy(np.float64)
        ok = ~np.isnan(rz)
        num += np.where(ok, rz * w, 0.0); den += np.where(ok, abs(w), 0.0); cov += ok
    with np.errstate(invalid="ignore", divide="ignore"):
        out = num / np.where(den == 0, np.nan, den)
    out[cov == 0] = np.nan
    return out
