"""WO-55 shared paths and window. Spec: final/models/2026-10-09-cwspread-outofera-prereg.md.

The WO-52 OptionMetrics store (final/data/wrds/optionm/{opprcd,secprd.parquet,av_shaped}) is the frozen
2008-2018 input of WO-52 and is never written here. The 2019-2025 gap lives under its own root, oos2019/.
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE.parent
for p in (SRC, SRC / "options_wo25", SRC / "thinliq", SRC / "wrds_optionm"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

MAIN = Path("/Users/ggraham/pipe_dream/final")
OM = MAIN / "data" / "wrds" / "optionm"
SECURD = OM / "securd.parquet"                      # WO-52 pull of optionm.securd (read only)
ROOT = OM / "oos2019"                               # WO-55 gap root (parquet only, gitignored)
RAW = ROOT / "opprcd"
SECPRD = ROOT / "secprd.parquet"
SECNMD = ROOT / "secnmd.parquet"
STORE = ROOT / "av_shaped"
MONTHLY = STORE / "options" / "monthly"
CALLS = STORE / "calls.parquet"
XWALK = MAIN / "data" / "wrds" / "link" / "permno_sharadar.parquet"
OPCRSP = MAIN / "data" / "wrds" / "link" / "opcrsphist.parquet"
UNIVERSE = MAIN / "data" / "sharadar" / "downcap_universe_v2.parquet"
AV_MONTHLY_GRID = MAIN / "data" / "alphavantage_full" / "options" / "monthly"   # the WO-37 date grid (names only)
OUT = HERE.parents[1] / "out" / "cwspread_oos"
PREREG_DOC = "final/models/2026-10-09-cwspread-outofera-prereg.md"

LO, HI = "2019-01-01", "2025-08-29"     # OptionMetrics ends 2025-08-29; nothing before 2019 (WO-52 has it), nothing before 2007 ever
N_DATES = 80                           # AV grid dates in [LO, HI], counted 2026-10-09 (file names only)
CRSP_LEGACY_END = "2024-12-31"         # crsp.stocknames (legacy SIZ) nameenddt censoring date


def entry_dates():
    ds = sorted(p.stem.split("=")[1] for p in AV_MONTHLY_GRID.glob("date=*.parquet"))
    ds = [d for d in ds if LO <= d <= HI]
    assert len(ds) == N_DATES, len(ds)
    return ds
