#!/usr/bin/env bash
set -euo pipefail
ROOT="/home/eric/Documents/workspace"
cd "$ROOT"
DB="$ROOT/state/cp/doublecolor.db"
for year in $(seq 2026 -1 2003); do
  start=$(printf "%d001" "$year")
  end=$(printf "%d999" "$year")
  echo "== backfill year $year =="
  python3 scripts/cp/fetch_ssq.py --mode full --page-size 100 --issue-start "$start" --issue-end "$end" --db "$DB" || true
  sleep 2
done
