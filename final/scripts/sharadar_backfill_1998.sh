#!/bin/zsh
# Push the Sharadar equity history back from 2005-01 to 1998-12 (the start of
# Sharadar's DAILY market-cap table), WITHOUT touching the live panel that
# build_pit_universe.py / downcap_universe.py glob (standing constraint #1:
# the next "Retrain ALL models" click must not silently change app inputs).
#
#   export SHARADAR_API_KEY=...        # keep it in ~/.zshrc, never in the repo
#   zsh final/scripts/sharadar_backfill_1998.sh
#
# Writes everything under final/data/sharadar_backfill/:
#   panel/daily/1998-12..2004-12.parquet, panel/stocks/...   (same format as live)
#   sf1_fundamentals.parquet, sf1_shares.csv                  (1997 onward: one
#       year of lead-in so TTM/growth fundamentals exist by 1998-12)
# Then run the validation (units / marketcap corruption) against the new months
# before anything consumes them -- units were only confirmed for 2005-2026.
set -e
: ${SHARADAR_API_KEY:?set SHARADAR_API_KEY (export it in ~/.zshrc, not in the repo)}
HERE=${0:A:h}
SRC=$HERE/../src
BF=/Users/ggraham/pipe_dream/final/data/sharadar_backfill
PY=/opt/anaconda3/envs/pipe_dream/bin/python
mkdir -p $BF/panel
SHARADAR_PANEL_DIR=$BF/panel $PY $SRC/sharadar_pull_pit_panel.py --start 1998-12 --end 2004-12
SHARADAR_OUT_DIR=$BF SHARADAR_START=1997-01-01 $PY $SRC/sharadar_pull_fundamentals.py
SHARADAR_OUT_DIR=$BF SHARADAR_START=1997-01-01 $PY $SRC/sharadar_pull_shares.py
echo "backfill landed in $BF"
