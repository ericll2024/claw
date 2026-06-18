#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKSPACE="/home/eric/Documents/workspace"
STATE_FILE="${FB_STATE_FILE:-$WORKSPACE/state/facebook/fb_storage_state.json}"
OUTPUT_DIR="${FB_OUTPUT_DIR:-$WORKSPACE/tmp/fb_yesterday_summary}"
CHROME_PATH="${FB_CHROME_PATH:-/usr/bin/google-chrome-stable}"
NODE_PATH_EXTRA="$WORKSPACE/.tmp/fbprobe/node_modules"

export NODE_PATH="${NODE_PATH_EXTRA}${NODE_PATH:+:$NODE_PATH}"

exec node "$SCRIPT_DIR/fb_yesterday_summary.js" \
  --state-file "$STATE_FILE" \
  --output-dir "$OUTPUT_DIR" \
  --chrome-path "$CHROME_PATH" \
  --config "$WORKSPACE/state/facebook/fb_groups.json" \
  "$@"
