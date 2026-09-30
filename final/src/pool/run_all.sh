#!/bin/zsh
# WO-31: run every pool x period job (one process each), then aggregate.
# Usage: zsh final/src/pool/run_all.sh   (after pull_bench.py and gate_a.py)
set -e
HERE=${0:A:h}
PY=/opt/anaconda3/envs/pipe_dream/bin/python
LOGS=$HERE/../../out/pool/logs
mkdir -p $LOGS
for job in "A cap150" "B cap150" "A cap500" "A cap2000" "B cap500" "B cap2000"; do
  p=${job% *}; t=${job#* }
  $PY $HERE/pool_read.py --period $p --pool $t > $LOGS/${p}_${t}.log 2>&1
  echo "done $p $t"
done
$PY $HERE/pool_read.py --aggregate > $LOGS/aggregate.log 2>&1
echo "aggregate done"
