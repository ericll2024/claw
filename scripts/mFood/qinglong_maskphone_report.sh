#!/usr/bin/env bash
set -euo pipefail

WORKSPACE="/home/eric/Documents/workspace"
OUT="$(/usr/bin/env bash "$WORKSPACE/scripts/mFood/qinglong_maskphone_monitor.sh")"
STATUS="$(python3 - <<'PY' "$OUT"
import json, sys
try:
    data = json.loads(sys.argv[1])
    print(data.get('status', 'error'))
except Exception:
    print('error')
PY
)"

python3 - <<'PY' "$OUT" "$STATUS"
import json, sys
raw = sys.argv[1]
status = sys.argv[2]
try:
    data = json.loads(raw)
except Exception:
    print("- 检查总结：需人工复核\n- 当前设置阈值：无法解析\n- 关键数据：返回结果无法解析")
    raise SystemExit(0)

all_count = data.get('allCount', 0)
using_count = data.get('usingCount', 0)
other_using_count = data.get('otherUsingCount', 0)
focus_used_count = data.get('focusUsedCount', 0)
threshold = data.get('threshold', 0)
message = data.get('message', '')
raw_meta = data.get('raw') or {}
retry_attempt = data.get('retryAttempt', '') or raw_meta.get('retryAttempt', '')
max_attempts = data.get('maxAttempts', '') or raw_meta.get('maxAttempts', '')
retry_text = f"{retry_attempt}/{max_attempts}" if retry_attempt and max_attempts else '1/1'
summary = '异常' if status == 'alert' else '正常' if status == 'ok' else '需人工复核'

prefix = '🔴 异常告警' if status == 'alert' else '🟡 需人工复核' if status == 'error' else '🟢 例行检查'
print(
    f"{prefix}\n"
    f"- 检查总结：{summary}\n"
    f"- 当前设置阈值：{threshold}\n"
    f"- 关键数据：allCount={all_count}，usingCount={using_count}，otherUsingCount={other_using_count}，关注值={focus_used_count}\n"
    f"- 重试情况：{retry_text}\n"
    f"- 报警说明：{message}"
)
PY

if [[ "$STATUS" == "alert" ]]; then
  exit 0
fi

exit 0
