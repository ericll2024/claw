#!/usr/bin/env bash
set -euo pipefail

WORKSPACE="/home/eric/Documents/workspace"
LOG_DIR="$WORKSPACE/tmp/qinglong_maskphone"
mkdir -p "$LOG_DIR"

TS="$(TZ=Asia/Shanghai date '+%Y-%m-%d %H:%M:%S %Z')"
OUT_FILE="$LOG_DIR/last.json"
ERR_FILE="$LOG_DIR/last.err"

python3 "$WORKSPACE/scripts/mFood/qinglong_maskphone_monitor.py" >"$OUT_FILE" 2>"$ERR_FILE" || STATUS=$?
STATUS=${STATUS:-0}

if [[ -s "$ERR_FILE" ]]; then
  echo "[$TS] stderr:" >&2
  cat "$ERR_FILE" >&2
fi

cat "$OUT_FILE"
exit "$STATUS"
