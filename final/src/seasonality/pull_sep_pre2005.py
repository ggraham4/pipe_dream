"""
WO-18: pull Sharadar SEP (table `stocks`: open/high/low/close/volume/closeadj/
closeunadj) for 1998-01..2004-12 (+ 2005-01 overlap) into a SEPARATE directory, so the
return-seasonality factor can use a 10-year lookback from 2007 onward.

It runs the shared puller (final/src/sharadar_pull_pit_panel.py, unedited)
with SHARADAR_PANEL_DIR redirected to final/data/sharadar/sep_pre2005/ in the
MAIN checkout. It never writes to data/sharadar/panel/ (which the live
refresh globs), so no live feature or refresh input changes.

The API key is read from ~/.config/pipe_dream/secrets.env (never printed).
Usage: python pull_sep_pre2005.py
"""
import os
import re
import runpy
import sys
from pathlib import Path

MAIN = Path("/Users/ggraham/pipe_dream/final")
OUT_DIR = MAIN / "data" / "sharadar" / "sep_pre2005"

if __name__ == "__main__":
    txt = Path("~/.config/pipe_dream/secrets.env").expanduser().read_text()
    os.environ["SHARADAR_API_KEY"] = re.search(r"SHARADAR_API_KEY=[\"']?([^\"'\s]+)", txt).group(1)
    os.environ["SHARADAR_PANEL_DIR"] = str(OUT_DIR)
    # 2005-01 is pulled too, as an OVERLAP month only: closeadj is re-based to
    # the pull date (dividends/splits after 2026-09-09 rescale all history), so
    # build_seas.py rescales 1998-2004 onto the 2026-09-09 basis of
    # data/sharadar/panel/stocks via the per-ticker 2005-01 month-end ratio.
    sys.argv = ["sharadar_pull_pit_panel.py", "--table", "stocks", "--start", "1998-01", "--end", "2005-01"]
    runpy.run_path(str(MAIN / "src" / "sharadar_pull_pit_panel.py"), run_name="__main__")
