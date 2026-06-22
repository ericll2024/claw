#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$ROOT"
if [ -f "$ROOT/data/traeclaw.sqlite3" ]; then
  DB="$ROOT/data/traeclaw.sqlite3"
else
  DB="$ROOT/state/cp/doublecolor.db"
fi
for year in $(seq 2026 -1 2003); do
  start=$(printf "%d001" "$year")
  end=$(printf "%d999" "$year")
  echo "== backfill year $year =="
  python3 scripts/cp/fetch_ssq.py --mode full --page-size 100 --issue-start "$start" --issue-end "$end" --db "$DB" || true
  sleep 2
done
