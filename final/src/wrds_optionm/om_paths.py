"""WO-52 shared paths. The WO-37 harness (final/src/thinliq, options_wo25, build_*) is imported from
the checkout's own final/src when present (after the branch is based on integration), else from
THINLIQ_SRC (a read-only extract of origin/integration, used before the branch switch)."""
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_SRC = HERE.parent
SRC = REPO_SRC if (REPO_SRC / "thinliq" / "tl_common.py").exists() else Path(os.environ.get("THINLIQ_SRC", "/tmp/wo52/int/final/src"))
for p in (SRC, SRC / "options_wo25", SRC / "thinliq"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

MAIN = Path("/Users/ggraham/pipe_dream/final")
ROOT = MAIN / "data" / "wrds" / "optionm"
RAW = ROOT / "opprcd"
STORE = ROOT / "av_shaped"
MONTHLY = STORE / "options" / "monthly"
CALLS = STORE / "calls.parquet"
XWALK = MAIN / "data" / "wrds" / "link" / "permno_sharadar.parquet"
OPCRSP = MAIN / "data" / "wrds" / "link" / "opcrsphist.parquet"
UNIVERSE = MAIN / "data" / "sharadar" / "downcap_universe_v2.parquet"
AV_FULL = MAIN / "data" / "alphavantage_full"
OUT = HERE.parents[1] / "out" / "thinliq_om"
AMEND_DOC = "final/models/2026-10-08-thinliq-optionmetrics-amendment.md"
