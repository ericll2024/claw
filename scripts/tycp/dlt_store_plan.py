import argparse
import json
import sqlite3
from collections import Counter
from itertools import combinations
from pathlib import Path

DB_PATH = Path('/home/eric/Documents/workspace/state/tycp/data/dlt_history.sqlite3')


def parse_nums(text):
    return [f'{int(x):02d}' for x in str(text).replace(',', ' ').split() if x.strip()]


def expand_ticket_group(front_text, back_text):
    front = sorted(parse_nums(front_text))
    back = sorted(parse_nums(back_text))
    if len(front) < 5 or len(back) < 2:
        raise ValueError('号码至少需要前区5个、后区2个')
    front_groups = list(combinations(front, 5))
    back_groups = list(combinations(back, 2))
    return front, back, front_groups, back_groups


def load_ticket_defs(singles_file):
    if not singles_file:
        return []
    singles_path = Path(singles_file)
    if not singles_path.exists():
        return []
    return json.loads(singles_path.read_text(encoding='utf-8'))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--draw-num', required=True)
    parser.add_argument('--plan-time', required=True)
    parser.add_argument('--budget', type=float, required=True)
    parser.add_argument('--strategy-model', required=True)
    parser.add_argument('--front-core', default='')
    parser.add_argument('--front-secondary', default='')
    parser.add_argument('--back-core', default='')
    parser.add_argument('--main-ticket-type', default='')
    parser.add_argument('--main-front', default='')
    parser.add_argument('--main-back', default='')
    parser.add_argument('--singles-file', default='')
    parser.add_argument('--logic-text', default='')
    parser.add_argument('--version', default='v1')
    parser.add_argument('--main-label', default='主推')
    parser.add_argument('--ref-front', default='')
    parser.add_argument('--ref-back', default='')
    parser.add_argument('--ref-label', default='参考')
    args = parser.parse_args()

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    single_tickets = load_ticket_defs(args.singles_file)
    singles_detail = json.dumps(single_tickets, ensure_ascii=False) if single_tickets else ''

    existing = cur.execute(
        'SELECT id FROM dlt_plans WHERE draw_num = ? AND plan_time = ?',
        (args.draw_num, args.plan_time)
    ).fetchone()

    if existing:
        plan_id = existing['id']
        cur.execute('DELETE FROM dlt_tickets WHERE plan_id = ?', (plan_id,))
        cur.execute('''
            UPDATE dlt_plans
            SET budget = ?, strategy_model = ?, front_core = ?, front_secondary = ?,
                back_core = ?, main_ticket_type = ?, main_front = ?, main_back = ?,
                singles_count = ?, singles_detail = ?, logic_text = ?, version = ?
            WHERE id = ?
        ''', (
            args.budget, args.strategy_model, args.front_core, args.front_secondary,
            args.back_core, args.main_ticket_type, args.main_front, args.main_back,
            len(single_tickets), singles_detail, args.logic_text, args.version, plan_id
        ))
    else:
        cur.execute('''
            INSERT INTO dlt_plans (
                draw_num, plan_time, budget, strategy_model, front_core, front_secondary,
                back_core, main_ticket_type, main_front, main_back, singles_count,
                singles_detail, logic_text, version
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            args.draw_num, args.plan_time, args.budget, args.strategy_model,
            args.front_core, args.front_secondary, args.back_core,
            args.main_ticket_type, args.main_front, args.main_back,
            len(single_tickets), singles_detail, args.logic_text, args.version
        ))
        plan_id = cur.lastrowid

    ticket_counter = Counter()
    group_counter = Counter()

    def add_ticket(ticket_type, label, front_nums, back_nums, cost=2):
        cur.execute('''
            INSERT INTO dlt_tickets (
                plan_id, draw_num, ticket_type, ticket_label,
                front_1, front_2, front_3, front_4, front_5,
                back_1, back_2, is_additional, cost
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)
        ''', (
            plan_id, args.draw_num, ticket_type, label,
            front_nums[0], front_nums[1], front_nums[2], front_nums[3], front_nums[4],
            back_nums[0], back_nums[1], cost
        ))
        ticket_counter[ticket_type] += 1

    def add_group(ticket_type, label, front_text, back_text):
        if not front_text or not back_text:
            return
        front_all, back_all, front_groups, back_groups = expand_ticket_group(front_text, back_text)
        combo_index = 0
        for front_nums in front_groups:
            for back_nums in back_groups:
                combo_index += 1
                combo_label = label if len(front_groups) == 1 and len(back_groups) == 1 else f'{label}{combo_index}'
                add_ticket(ticket_type, combo_label, list(front_nums), list(back_nums))
        group_counter[label] = len(front_groups) * len(back_groups)
        return {
            'label': label,
            'front_count': len(front_all),
            'back_count': len(back_all),
            'ticket_count': len(front_groups) * len(back_groups),
            'cost': len(front_groups) * len(back_groups) * 2,
        }

    group_summaries = []
    main_summary = add_group('key', args.main_label, args.main_front, args.main_back)
    if main_summary:
        group_summaries.append(main_summary)

    ref_summary = add_group('reference', args.ref_label, args.ref_front, args.ref_back)
    if ref_summary:
        group_summaries.append(ref_summary)

    for i, ticket in enumerate(single_tickets, start=1):
        label = ticket.get('label') or f'单式{i}'
        summary = add_group(ticket.get('ticket_type', 'single'), label, ticket['front'], ticket['back'])
        if summary:
            group_summaries.append(summary)

    conn.commit()
    ticket_count = cur.execute('SELECT COUNT(*) FROM dlt_tickets WHERE plan_id = ?', (plan_id,)).fetchone()[0]
    total_cost = cur.execute('SELECT COALESCE(SUM(cost), 0) FROM dlt_tickets WHERE plan_id = ?', (plan_id,)).fetchone()[0]
    conn.close()

    print(json.dumps({
        'plan_id': plan_id,
        'draw_num': args.draw_num,
        'tickets_written': ticket_count,
        'ticket_breakdown': dict(ticket_counter),
        'group_summaries': group_summaries,
        'total_cost': total_cost
    }, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
