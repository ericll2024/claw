import argparse
import json
import sqlite3
from collections import Counter
from datetime import datetime
from pathlib import Path

DB_PATH = Path('/home/eric/Documents/workspace/state/tycp/data/dlt_history.sqlite3')

BASE_PRIZES_LOW = {
    '三等奖': 5000,
    '四等奖': 300,
    '五等奖': 150,
    '六等奖': 15,
    '七等奖': 5,
}
BASE_PRIZES_HIGH = {
    '三等奖': 6666,
    '四等奖': 380,
    '五等奖': 200,
    '六等奖': 18,
    '七等奖': 7,
}


def prize_amount(prize, pool_balance_afterdraw=None):
    if not prize:
        return 0
    if prize in ('一等奖', '二等奖'):
        return None
    high = False
    if pool_balance_afterdraw is not None:
        try:
            val = float(str(pool_balance_afterdraw).replace(',', ''))
            high = val >= 800000000
        except Exception:
            high = False
    return (BASE_PRIZES_HIGH if high else BASE_PRIZES_LOW)[prize]


def judge(front, back, win_front, win_back):
    hf = len(set(front) & set(win_front))
    hb = len(set(back) & set(win_back))
    prize = None
    if hf == 5 and hb == 2:
        prize = '一等奖'
    elif hf == 5 and hb == 1:
        prize = '二等奖'
    elif hf == 5 and hb == 0:
        prize = '三等奖'
    elif hf == 4 and hb == 2:
        prize = '三等奖'
    elif hf == 4 and hb == 1:
        prize = '四等奖'
    elif hf == 4 and hb == 0:
        prize = '五等奖'
    elif hf == 3 and hb == 2:
        prize = '五等奖'
    elif hf == 3 and hb == 1:
        prize = '六等奖'
    elif hf == 2 and hb == 2:
        prize = '六等奖'
    elif hf == 3 and hb == 0:
        prize = '七等奖'
    elif hf == 2 and hb == 1:
        prize = '七等奖'
    elif hf == 1 and hb == 2:
        prize = '七等奖'
    elif hf == 0 and hb == 2:
        prize = '七等奖'
    return hf, hb, prize


def prize_rank(level):
    order = {
        '一等奖': 1, '二等奖': 2, '三等奖': 3, '四等奖': 4,
        '五等奖': 5, '六等奖': 6, '七等奖': 7, '未中奖': 99, None: 99
    }
    return order.get(level, 99)


def fetch_draw(conn, draw_num):
    has_history = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='dlt_history'").fetchone()
    if has_history:
        columns = [r[1] for r in conn.execute('PRAGMA table_info(dlt_history)').fetchall()]
        if 'poolBalanceAfterdraw' in columns:
            return conn.execute('''
                SELECT r.*, h.poolBalanceAfterdraw as pool_balance_afterdraw
                FROM dlt_results r
                LEFT JOIN dlt_history h ON h.lottery_draw_num = r.draw_num
                WHERE r.draw_num = ?
            ''', (draw_num,)).fetchone()
    return conn.execute('SELECT r.*, NULL as pool_balance_afterdraw FROM dlt_results r WHERE r.draw_num = ?', (draw_num,)).fetchone()


def build_report(draw_num, win_front, win_back, top_level, fixed_total, floating_hits, level_counter, group_summaries, comparison_text, ticket_count):
    lines = [
        f'第{draw_num}期开奖：{" ".join(win_front)} + {" ".join(win_back)}',
        f'本期最佳命中：{top_level or "未中奖"}',
        f'固定奖金合计：{fixed_total}元',
    ]
    if floating_hits:
        floating_text = '；'.join(f'{item["label"]} {item["level"]}' for item in floating_hits[:5])
        if len(floating_hits) > 5:
            floating_text += f' 等{len(floating_hits)}注'
        lines.append(f'浮动奖命中：{floating_text}（金额以官方派奖为准）')
    if level_counter:
        summary = '、'.join(f'{level}{count}注' for level, count in sorted(level_counter.items(), key=lambda x: prize_rank(x[0])))
        lines.append(f'奖级分布：{summary}')
    for s in group_summaries:
        lines.append(s)
    if comparison_text:
        if ticket_count <= 20:
            lines.append(f'明细：{comparison_text}')
        else:
            excerpt = '；'.join(comparison_text.split('；')[:8])
            lines.append(f'明细摘录：{excerpt}；共{ticket_count}注')
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--draw-num', required=True)
    parser.add_argument('--review-time', default=datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
    parser.add_argument('--miss-reason', default='待补充')
    parser.add_argument('--fix-direction', default='后区防守：维持；前区区间：维持；和值：维持；奇偶大小：再平衡；出票结构：维持')
    parser.add_argument('--review-text', default='待补充')
    args = parser.parse_args()

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    draw = fetch_draw(conn, args.draw_num)
    if not draw:
        raise SystemExit(f'未找到期开奖: {args.draw_num}')

    plan = cur.execute('SELECT * FROM dlt_plans WHERE draw_num = ? ORDER BY id DESC LIMIT 1', (args.draw_num,)).fetchone()
    if not plan:
        raise SystemExit(f'未找到方案: {args.draw_num}')

    tickets = cur.execute('SELECT * FROM dlt_tickets WHERE plan_id = ? ORDER BY id', (plan['id'],)).fetchall()
    win_front = [draw['front_1'], draw['front_2'], draw['front_3'], draw['front_4'], draw['front_5']]
    win_back = [draw['back_1'], draw['back_2']]

    top_level = '未中奖'
    fixed_total = 0
    floating_hits = []
    level_counter = Counter()
    main_summary = None
    ref_summary = None
    comparisons = []
    label_map = {
        'key': '主推(100元档)',
        'reference': '参考(500元档)',
        'budget_1000': '1000元档',
    }
    group_stats = {}

    for t in tickets:
        front = [t['front_1'], t['front_2'], t['front_3'], t['front_4'], t['front_5']]
        back = [t['back_1'], t['back_2']]
        hf, hb, level = judge(front, back, win_front, win_back)
        level_text = level or '未中奖'
        amount = prize_amount(level, draw['pool_balance_afterdraw'])
        if amount is not None:
            fixed_total += amount
        if level:
            level_counter[level_text] += 1
        cur.execute('''
            UPDATE dlt_tickets
            SET hit_front_count = ?, hit_back_count = ?, prize_level = ?, prize_amount = ?
            WHERE id = ?
        ''', (hf, hb, level_text, amount if amount is not None else None, t['id']))
        label = t['ticket_label'] or t['ticket_type']
        summary = f'{label}：前区中{hf}，后区中{hb}，{level_text}'
        comparisons.append(summary)
        ticket_type = t['ticket_type']
        if ticket_type not in group_stats:
            group_stats[ticket_type] = {
                'label': label_map.get(ticket_type, ticket_type),
                'count': 0,
                'fixed_total': 0,
                'best_level': '未中奖',
                'floating_hits': []
            }
        group_stats[ticket_type]['count'] += 1
        if amount is not None:
            group_stats[ticket_type]['fixed_total'] += amount
        if prize_rank(level) < prize_rank(group_stats[ticket_type]['best_level']):
            group_stats[ticket_type]['best_level'] = level
        if level in ('一等奖', '二等奖'):
            group_stats[ticket_type]['floating_hits'].append({'label': label, 'level': level})
        if level in ('一等奖', '二等奖'):
            floating_hits.append({'label': label, 'level': level})
        if prize_rank(level) < prize_rank(top_level):
            top_level = level

    top_level = top_level or '未中奖'
    group_summaries = []
    order_weight = {'key': 0, 'reference': 1, 'budget_1000': 2}
    sorted_types = sorted(group_stats.keys(), key=lambda k: order_weight.get(k, 99))

    for ticket_type in sorted_types:
        stats = group_stats[ticket_type]
        if stats['count'] == 0:
            continue
        floating_desc = f"，浮动奖{len(stats['floating_hits'])}注" if stats['floating_hits'] else ''
        summary = f"{stats['label']}：{stats['count']}注，最佳{stats['best_level']}，固定奖金{stats['fixed_total']}元{floating_desc}"
        group_summaries.append(summary)
        if ticket_type == 'key':
            main_summary = summary
        elif ticket_type == 'reference':
            ref_summary = summary

    comparison_text = '；'.join(comparisons)
    report_text = build_report(
        args.draw_num, win_front, win_back, top_level, fixed_total,
        floating_hits, level_counter, group_summaries, comparison_text, len(tickets)
    )
    final_review_text = args.review_text if args.review_text != '待补充' else report_text

    existing_review = cur.execute(
        'SELECT id FROM dlt_reviews WHERE draw_num = ? AND plan_id = ? ORDER BY id DESC LIMIT 1',
        (args.draw_num, plan['id'])
    ).fetchone()

    if existing_review:
        review_id = existing_review['id']
        cur.execute('''
            UPDATE dlt_reviews
            SET review_time = ?, top_prize_level = ?, prize_amount = ?,
                main_hit_summary = ?, ref_hit_summary = ?, comparison_text = ?,
                miss_reason = ?, fix_direction = ?, review_text = ?
            WHERE id = ?
        ''', (
            args.review_time, top_level, fixed_total, main_summary, ref_summary,
            comparison_text, args.miss_reason, args.fix_direction, final_review_text,
            review_id
        ))
    else:
        cur.execute('''
            INSERT INTO dlt_reviews (
                draw_num, review_time, plan_id, top_prize_level, prize_amount,
                main_hit_summary, ref_hit_summary, comparison_text,
                miss_reason, fix_direction, review_text
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            args.draw_num, args.review_time, plan['id'], top_level, fixed_total,
            main_summary, ref_summary, comparison_text, args.miss_reason,
            args.fix_direction, final_review_text
        ))
        review_id = cur.lastrowid

    conn.commit()
    conn.close()

    print(json.dumps({
        'draw_num': args.draw_num,
        'plan_id': plan['id'],
        'review_id': review_id,
        'top_prize_level': top_level,
        'fixed_prize_amount': fixed_total,
        'floating_prize_hits': floating_hits,
        'level_counter': dict(level_counter),
        'main_hit_summary': main_summary,
        'ref_hit_summary': ref_summary,
        'report_text': report_text
    }, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
