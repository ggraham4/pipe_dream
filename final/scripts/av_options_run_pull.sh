#!/bin/zsh
# Launch/resume the AV options pull detached (survives terminal/session exit;
# caffeinate keeps the Mac awake). Idempotent: exits if already running.
#   ALPHAVANTAGE_API_KEY=... zsh final/scripts/av_options_run_pull.sh
# Progress:  /opt/anaconda3/envs/pipe_dream/bin/python final/scripts/av_options_pull.py \
#                --data-root /Users/ggraham/pipe_dream/final/data/alphavantage --status
# Stop:      pkill -f "av_options_pull.py --data-root"   (resumes where it left off)
set -e
ROOT=/Users/ggraham/pipe_dream/final/data/alphavantage
PY=/opt/anaconda3/envs/pipe_dream/bin/python
if pgrep -f "av_options_pull.py --data-root" >/dev/null; then echo "already running"; exit 0; fi
: ${ALPHAVANTAGE_API_KEY:?set ALPHAVANTAGE_API_KEY}
mkdir -p "$ROOT/bin"
cp "${0:A:h}/av_options_pull.py" "$ROOT/bin/av_options_pull.py"
cd "$ROOT"
nohup caffeinate -i "$PY" "$ROOT/bin/av_options_pull.py" --data-root "$ROOT" \
    --sharadar-dir /Users/ggraham/pipe_dream/final/data/sharadar ${=AV_PULL_ARGS} >> "$ROOT/pull.out" 2>&1 &
echo "launched pid $!"
