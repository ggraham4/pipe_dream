"""WO-47 shared paths and entity loading. Reads the main checkout's data read-only and the frozen
copies in ~/.cache/wo47/frozen (pinned in final/models/2026-10-07-ticker-reuse-panel-drift.md)."""
from pathlib import Path
import sys

import pandas as pd

HERE = Path(__file__).resolve().parent
WT_FINAL = HERE.parent.parent                       # worktree final/
MAIN = Path("/Users/ggraham/pipe_dream/final")       # live checkout: data read-only
SHARADAR = MAIN / "data" / "sharadar"
SEP_DIR = SHARADAR / "panel" / "stocks"
DAILY_DIR = SHARADAR / "panel" / "daily"
SCRATCH = Path.home() / ".cache" / "wo47"
FROZEN = SCRATCH / "frozen"
OUT = WT_FINAL / "out" / "tickerreuse"
OUT.mkdir(parents=True, exist_ok=True)

FRESH_TICKERS = SCRATCH / "tickers_fresh_2026-10-07.csv"
MASTERS = [FRESH_TICKERS, FROZEN / "tickers_master.csv", SHARADAR / "tickers_master_through_2026-09-08.csv"]

sys.path.insert(0, str(WT_FINAL / "src"))


def load_entity_rows():
    """Every (permaticker, ticker) seen in any TICKERS snapshot (table=stocks), with the span from the
    freshest snapshot that has that permaticker."""
    frames = []
    for rank, p in enumerate(MASTERS):
        m = pd.read_csv(p, dtype=str, usecols=["table", "permaticker", "ticker", "name", "isdelisted",
                                               "firstpricedate", "lastpricedate"])
        m = m[m["table"] == "stocks"].copy()
        m["rank"] = rank
        frames.append(m)
    m = pd.concat(frames, ignore_index=True)
    m["firstpricedate"] = pd.to_datetime(m["firstpricedate"], errors="coerce")
    m["lastpricedate"] = pd.to_datetime(m["lastpricedate"], errors="coerce")
    span = (m.sort_values("rank").drop_duplicates("permaticker")
             .set_index("permaticker")[["name", "isdelisted", "firstpricedate", "lastpricedate"]])
    names = m[["permaticker", "ticker"]].drop_duplicates()
    return names, span
