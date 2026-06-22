#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$ROOT"
OUT=$(python3 scripts/cp/fetch_ssq.py --mode latest --latest-pages 1 2>/tmp/cp_ssq_update.err || true)
if [ -z "$OUT" ]; then
  ERR_MSG=$(tail -n 5 /tmp/cp_ssq_update.err 2>/dev/null | tr '\n' ' ')
  echo "双色球更新失败，官方接口当前返回拦截。已保留本地数据库，待稍后自动重试。错误摘要: ${ERR_MSG}"
  exit 0
fi
echo "$OUT"
SUMMARY=$(python3 - <<'PY' "$OUT"
import json, sys
obj=json.loads(sys.argv[1])
latest=obj.get('latest',[])
line=latest[0] if latest else '暂无最新数据'
print(f"双色球已更新，新增 {obj['inserted']} 条，库内共 {obj['db_total']} 条。最新一期: {line}")
PY
)
echo "\n$SUMMARY"
