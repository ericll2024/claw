#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="${TRAECLAW_PROJECT_ROOT:-$(cd "$SCRIPT_DIR/../../.." && pwd)}"

# Default files relative to project root
STATE_FILE="${FB_STATE_FILE:-$PROJECT_ROOT/code/state/facebook/fb_storage_state.json}"
OUTPUT_DIR="${FB_OUTPUT_DIR:-$PROJECT_ROOT/code/tmp/fb_yesterday_summary}"

# Check OS for default Chrome path
if [[ "$OSTYPE" == "darwin"* ]]; then
  DEFAULT_CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
else
  DEFAULT_CHROME="/usr/bin/google-chrome-stable"
fi
CHROME_PATH="${FB_CHROME_PATH:-$DEFAULT_CHROME}"

# Add cache and workspace fallback paths to NODE_PATH
NODE_PATH_EXTRA="$HOME/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules:$PROJECT_ROOT/.tmp/fbprobe/node_modules"
export NODE_PATH="${NODE_PATH_EXTRA}${NODE_PATH:+:$NODE_PATH}"

exec node "$SCRIPT_DIR/fb_yesterday_summary.js" \
  --state-file "$STATE_FILE" \
  --output-dir "$OUTPUT_DIR" \
  --chrome-path "$CHROME_PATH" \
  --config "$PROJECT_ROOT/code/state/facebook/fb_groups.json" \
  "$@"
