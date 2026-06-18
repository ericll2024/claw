#!/usr/bin/env bash
set -euo pipefail

WORKSPACE="/home/eric/Documents/workspace"
TMP_DIR="$(mktemp -d)"
OUT_FILE="$TMP_DIR/last.json"
ERR_FILE="$TMP_DIR/last.err"
trap 'rm -rf "$TMP_DIR"' EXIT

python3 "$WORKSPACE/scripts/shence/shence_order_reconcile.py" >"$OUT_FILE" 2>"$ERR_FILE" || STATUS=$?
STATUS=${STATUS:-0}

cat "$OUT_FILE"
exit "$STATUS"
