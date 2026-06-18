#!/usr/bin/env bash
set -euo pipefail
ROOT="/home/eric/Documents/workspace"
cd "$ROOT"
FETCH=$(python3 scripts/cp/fetch_ssq.py --mode latest --latest-pages 1 2>/tmp/cp_ssq_result.err || true)
if [ -n "$FETCH" ]; then
  echo "$FETCH"
fi
OUT=$(python3 scripts/cp/settle_prediction.py --latest)
echo "$OUT"
MODE=$(python3 - <<'PY' "$OUT"
import json, sys
obj=json.loads(sys.argv[1])
print(obj.get('mode',''))
PY
)
if [ "$MODE" = "settled" ] || [ "$MODE" = "already_settled" ]; then
  SUMMARY=$(python3 - <<'PY' "$OUT"
import json, sys
obj=json.loads(sys.argv[1])
draw=obj['draw']
lines=[f"第 {obj['issue_code']} 期复盘", f"开奖号码：红球 {','.join(f'{x:02d}' for x in draw['reds'])}｜蓝球 {draw['blue']:02d}"]
label_map={'main':'主推8+1','reference':'参考9+1','budget_500':'500元档','budget_1000':'1000元档'}
for plan in obj.get('plans', []):
    result=plan.get('result') or {}
    summary=plan.get('summary') or {}
    label=label_map.get(plan['plan_type'], plan['plan_type'])
    sample=(summary.get('sample_reds') or [''])[0]
    lines.append(f"\n【本期购买方案｜{label}】")
    lines.append(f"号码：红球 {sample}｜蓝球 {summary.get('blues','')}｜投入 {result.get('total_cost', summary.get('cost',0))} 元")
    if result.get('logic'):
        lines.append(f"推演逻辑：{result['logic']}")
    ticket_lines=[]
    for ticket in result.get('ticket_results', []):
        blue='命中' if ticket.get('hit_blue') else '未中'
        ticket_lines.append(f"第{ticket['ticket_no']}票：{ticket['reds']} + {ticket['blues']} → {ticket['hit_red']}红，蓝球{blue}，{ticket['prize_level']}，中奖 {ticket['return_amount']} 元")
    lines.append("开奖结果对比：")
    if ticket_lines:
        lines.extend(ticket_lines[:3])
        if len(ticket_lines) > 3:
            lines.append(f"其余汇总：共 {result.get('ticket_count',0)} 票，中出 {result.get('winning_tickets',0)} 票，最高命中 {result.get('best_hit_summary','')}，合计中奖 {result.get('total_bonus',0)} 元，回报率 {result.get('roi',0)*100:.1f}%")
    lines.append(f"未中原因分析：{result.get('miss_reason','')}")
    lines.append(f"下期修正方向：{result.get('next_fix','')}")
print('\n'.join(lines))
PY
)
  printf "\n%s\n" "$SUMMARY"
fi
