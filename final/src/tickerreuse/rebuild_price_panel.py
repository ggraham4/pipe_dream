"""WO-47 A4: scratch rebuilds of features_sharadar_pit.parquet from the frozen inputs.

    caffeinate -i python final/src/tickerreuse/rebuild_price_panel.py unfixed   # A4c control
    caffeinate -i python final/src/tickerreuse/rebuild_price_panel.py fixed     # A4a/A4b

Writes ~/.cache/wo47/features_sharadar_pit_{unfixed,fixed}.parquet only. Never writes final/out.
"""
import sys

from common import SCRATCH, FROZEN, SEP_DIR, MASTERS
import build_features_sharadar as BF

mode = sys.argv[1]
assert mode in ("fixed", "unfixed")
BF.PANEL = SEP_DIR
BF.UNIVERSE = FROZEN / "pit_universe.parquet"
BF.SPY_CSV = FROZEN / "SPY.csv"
BF.OUT = SCRATCH / f"features_sharadar_pit_{mode}.parquet"
assert "pipe_dream/final/out" not in str(BF.OUT)

_orig = BF.segment_reused_symbols
if mode == "unfixed":
    BF.segment_reused_symbols = lambda px, entities=None, return_report=False: (px, []) if return_report else px
else:
    ents = BF.load_reuse_entities(MASTERS)        # fresh TICKERS + both local masters
    BF.segment_reused_symbols = (lambda px, entities=None, return_report=False:
                                 _orig(px, entities=ents, return_report=return_report))
BF.build()
