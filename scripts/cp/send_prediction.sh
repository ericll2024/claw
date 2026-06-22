#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$ROOT"
OUT=$(python3 scripts/cp/predict_and_record.py "$@")
echo "$OUT"
SUMMARY=$(python3 - <<'PY' "$OUT"
import json, sys
obj=json.loads(sys.argv[1])
plans=obj.get('plans', [])
lines=[]
prefix='已存在' if obj.get('mode') == 'existing' else '已生成'
lines.append(f"第 {obj['issue_code']} 期预测{prefix}。")
for plan in plans:
    summary=plan.get('summary') or {}
    label=summary.get('label', plan.get('plan_type'))
    sample=(summary.get('sample_reds') or [''])[0]
    lines.append(f"- {label}：红球 {sample}，蓝球 {summary.get('blues','')}，成本 {summary.get('cost',0)} 元。")
print('\n'.join(lines))
PY
)
printf "\n%s\n" "$SUMMARY"
