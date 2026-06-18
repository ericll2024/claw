#!/usr/bin/env python3
import json
import itertools
import math
import sqlite3
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Tuple

from backtest_ssq import DB_PATH, PRIZE_MAP, build_strategy, ensure_tables, load_draws

ROOT = Path('/home/eric/Documents/workspace')
PRED_LOG = ROOT / 'state' / 'cp' / 'predictions.jsonl'
STRATEGY_VERSION = 'cp-v5.3'

CREATE_SQL = '''
CREATE TABLE IF NOT EXISTS cp_prediction_plans (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  issue_code TEXT NOT NULL,
  strategy_version TEXT NOT NULL,
  plan_type TEXT NOT NULL,
  bet_type TEXT NOT NULL,
  budget INTEGER NOT NULL DEFAULT 0,
  ticket_count INTEGER NOT NULL DEFAULT 0,
  bet_count INTEGER NOT NULL DEFAULT 0,
  cost INTEGER NOT NULL DEFAULT 0,
  blues TEXT NOT NULL,
  summary_json TEXT,
  reason_json TEXT,
  status TEXT NOT NULL DEFAULT 'predicted',
  draw_date TEXT,
  result_json TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(issue_code, plan_type)
);
CREATE INDEX IF NOT EXISTS idx_cp_prediction_plans_status_issue
  ON cp_prediction_plans(status, issue_code DESC, plan_type);

CREATE TABLE IF NOT EXISTS cp_prediction_tickets (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  plan_id INTEGER NOT NULL,
  ticket_no INTEGER NOT NULL,
  label TEXT,
  reds TEXT NOT NULL,
  blues TEXT NOT NULL,
  bet_count INTEGER NOT NULL,
  cost INTEGER NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE(plan_id, ticket_no),
  FOREIGN KEY(plan_id) REFERENCES cp_prediction_plans(id)
);
CREATE INDEX IF NOT EXISTS idx_cp_prediction_tickets_plan_id
  ON cp_prediction_tickets(plan_id, ticket_no);

CREATE TABLE IF NOT EXISTS cp_prediction_ticket_results (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  issue_code TEXT NOT NULL,
  plan_id INTEGER NOT NULL,
  ticket_id INTEGER NOT NULL,
  draw_date TEXT NOT NULL,
  draw_reds TEXT NOT NULL,
  draw_blue TEXT NOT NULL,
  hit_red INTEGER NOT NULL,
  hit_blue INTEGER NOT NULL,
  prize_level TEXT NOT NULL,
  return_amount INTEGER NOT NULL,
  prize_breakdown_json TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(issue_code, ticket_id),
  FOREIGN KEY(plan_id) REFERENCES cp_prediction_plans(id),
  FOREIGN KEY(ticket_id) REFERENCES cp_prediction_tickets(id)
);
CREATE INDEX IF NOT EXISTS idx_cp_prediction_ticket_results_issue
  ON cp_prediction_ticket_results(issue_code DESC, plan_id);
'''

PLAN_TYPE_LABELS = {
    'main': '主推 8+1',
    'reference': '参考 9+1',
    'budget_500': '500元方案',
    'budget_1000': '1000元方案',
}
PLAN_TYPE_ORDER = {
    'main': 1,
    'reference': 2,
    'budget_500': 3,
    'budget_1000': 4,
}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def fmt_nums(nums: List[int]) -> str:
    return ','.join(f'{x:02d}' for x in nums)


def parse_nums(text: str) -> List[int]:
    return [int(x) for x in text.split(',') if x]


def infer_next_issue(last_issue: str) -> str:
    year = int(last_issue[:4])
    seq = int(last_issue[-3:]) + 1
    if seq > 200:
        year += 1
        seq = 1
    return f'{year}{seq:03d}'


def ensure_prediction_tables(conn: sqlite3.Connection):
    ensure_tables(conn)
    conn.executescript(CREATE_SQL)


def load_draw(conn: sqlite3.Connection, issue_code: str):
    row = conn.execute(
        '''SELECT issue_code, draw_date, red1, red2, red3, red4, red5, red6, blue, red_sum, total_sum
           FROM ssq_draws WHERE issue_code=?''',
        (issue_code,),
    ).fetchone()
    if not row:
        return None
    return {
        'issue_code': row[0],
        'draw_date': row[1],
        'reds': list(row[2:8]),
        'blue': row[8],
        'red_sum': row[9],
        'total_sum': row[10],
    }


def single_ticket_return(reds: List[int], blues: List[int], draw: Dict) -> Tuple[int, bool, str, int, Dict[str, int]]:
    hit_red = len(set(reds) & set(draw['reds']))
    hit_blue = draw['blue'] in blues
    prize_counter = Counter()
    total_return = 0
    for red6 in itertools.combinations(sorted(reds), 6):
        hit_r = len(set(red6) & set(draw['reds']))
        for blue in blues:
            hit_b = blue == draw['blue']
            prize_level, amount = PRIZE_MAP.get((hit_r, hit_b), ('未中奖', 0))
            if amount > 0:
                prize_counter[prize_level] += 1
                total_return += amount
    if prize_counter:
        prize_level = ' + '.join(f'{name}x{count}' for name, count in prize_counter.items())
    else:
        prize_level = '未中奖'
    return hit_red, hit_blue, prize_level, total_return, dict(prize_counter)


def build_logic_text(reason: Dict) -> str:
    return (
        f"和值主看 {reason.get('target_sum')}，"
        f"奇偶倾向 {reason.get('odd_target')} 奇，"
        f"AC 值主看 {reason.get('ac_target')}，"
        f"继续保留连号同三区均衡。"
    )


def expand_reds(base_reds: List[int], candidate_pool: List[int], target_count: int) -> List[int]:
    pool = list(dict.fromkeys(sorted(candidate_pool)))
    extras = [n for n in pool if n not in base_reds]
    reds = sorted(base_reds)
    need = max(0, target_count - len(reds))
    if need:
        reds.extend(extras[:need])
    if len(reds) < target_count:
        fallback = [n for n in range(1, 34) if n not in reds]
        reds.extend(fallback[:target_count - len(reds)])
    return sorted(reds[:target_count])


def build_single_ticket_plan(plan_type: str, label: str, red_count: int, blue: List[int], base_reds: List[int], candidate_pool: List[int], logic: str, blue_rank: List[int]) -> Dict:
    reds = expand_reds(base_reds, candidate_pool, red_count)
    bet_count = math.comb(len(reds), 6) * len(blue)
    return {
        'plan_type': plan_type,
        'bet_type': f'{red_count}红+1蓝复式',
        'budget': bet_count * 2,
        'ticket_blue': blue,
        'tickets': [{
            'ticket_no': 1,
            'label': label,
            'reds': reds,
            'blues': blue,
            'bet_count': bet_count,
            'cost': bet_count * 2,
        }],
        'reason': {'logic': logic, 'candidate_pool': candidate_pool, 'blue_rank': blue_rank},
    }


def generate_main_and_reference(base_strategy: Dict) -> List[Dict]:
    reason = base_strategy['reason']
    candidate_pool = reason.get('candidate_pool', [])
    blue_rank = reason.get('blue_rank', [])
    base_reds = sorted(base_strategy['reds'])
    blue = [blue_rank[0] if blue_rank else base_strategy['blues'][0]]
    logic = build_logic_text(reason)
    return [
        build_single_ticket_plan('main', '主推核心票', 8, blue, base_reds, candidate_pool, logic, blue_rank),
        build_single_ticket_plan('reference', '参考扩展票', 9, blue, base_reds, candidate_pool, logic, blue_rank),
        build_single_ticket_plan('budget_500', '500元扩容票', 10, blue, base_reds, candidate_pool, logic, blue_rank),
        build_single_ticket_plan('budget_1000', '1000元扩容票', 11, blue, base_reds, candidate_pool, logic, blue_rank),
    ]


def combo_shape_ok(combo: Tuple[int, ...], a_layer: List[int], b_layer: List[int], c_layer: List[int]) -> bool:
    count_a = sum(1 for x in combo if x in a_layer)
    count_b = sum(1 for x in combo if x in b_layer)
    count_c = sum(1 for x in combo if x in c_layer)
    return 2 <= count_a <= 4 and 2 <= count_b <= 3 and 1 <= count_c <= 3


def combo_feature_score(combo: Tuple[int, ...], rank_map: Dict[int, int], base_set: set) -> float:
    consecutive = sum(1 for a, b in zip(combo, combo[1:]) if b - a == 1)
    overlap = len(base_set & set(combo))
    tail_penalty = len({x % 10 for x in combo}) == 7
    sum_value = sum(combo)
    rank_score = sum(rank_map.get(n, 0) for n in combo)
    zone_counts = (
        sum(1 for x in combo if 1 <= x <= 11),
        sum(1 for x in combo if 12 <= x <= 22),
        sum(1 for x in combo if 23 <= x <= 33),
    )
    zone_penalty = abs(zone_counts[0] - 2) + abs(zone_counts[1] - 2) + abs(zone_counts[2] - 2)
    sum_penalty = abs(sum_value - 105) / 10.0
    return rank_score + consecutive * 1.6 + overlap * 0.8 - zone_penalty - sum_penalty - (1.0 if tail_penalty else 0.0)


def similarity(a: Tuple[int, ...], b: Tuple[int, ...]) -> int:
    return len(set(a) & set(b))


def summarize_plan(plan_type: str, tickets: List[Dict]) -> Dict:
    reds = [fmt_nums(ticket['reds']) for ticket in tickets[:3]]
    blues = sorted({b for ticket in tickets for b in ticket['blues']})
    return {
        'label': PLAN_TYPE_LABELS.get(plan_type, plan_type),
        'ticket_count': len(tickets),
        'sample_reds': reds,
        'blues': fmt_nums(blues),
        'bet_count': sum(ticket['bet_count'] for ticket in tickets),
        'cost': sum(ticket['cost'] for ticket in tickets),
    }


def build_prediction_payloads(draws: List[Dict]) -> List[Dict]:
    base_strategy = build_strategy(draws, STRATEGY_VERSION)
    return generate_main_and_reference(base_strategy)


def load_plan_bundle(conn: sqlite3.Connection, issue_code: str) -> List[Dict]:
    rows = conn.execute(
        '''SELECT p.id, p.issue_code, p.strategy_version, p.plan_type, p.bet_type, p.budget,
                  p.ticket_count, p.bet_count, p.cost, p.blues, p.summary_json, p.reason_json,
                  p.status, p.draw_date, p.result_json, p.created_at,
                  t.id, t.ticket_no, t.label, t.reds, t.blues, t.bet_count, t.cost
           FROM cp_prediction_plans p
           LEFT JOIN cp_prediction_tickets t ON t.plan_id = p.id
           WHERE p.issue_code=?
           ORDER BY p.plan_type, t.ticket_no''',
        (issue_code,),
    ).fetchall()
    plans = {}
    for row in rows:
        plan_id = row[0]
        plan = plans.setdefault(plan_id, {
            'id': plan_id,
            'issue_code': row[1],
            'strategy_version': row[2],
            'plan_type': row[3],
            'bet_type': row[4],
            'budget': row[5],
            'ticket_count': row[6],
            'bet_count': row[7],
            'cost': row[8],
            'blues': row[9],
            'summary': json.loads(row[10]) if row[10] else None,
            'reason': json.loads(row[11]) if row[11] else None,
            'status': row[12],
            'draw_date': row[13],
            'result': json.loads(row[14]) if row[14] else None,
            'created_at': row[15],
            'tickets': [],
        })
        if row[16] is not None:
            plan['tickets'].append({
                'id': row[16],
                'ticket_no': row[17],
                'label': row[18],
                'reds': row[19],
                'blues': row[20],
                'bet_count': row[21],
                'cost': row[22],
            })
    return sorted(plans.values(), key=lambda x: PLAN_TYPE_ORDER.get(x['plan_type'], 99))


def delete_prediction_issue(conn: sqlite3.Connection, issue_code: str):
    plan_rows = conn.execute("SELECT id FROM cp_prediction_plans WHERE issue_code=?", (issue_code,)).fetchall()
    plan_ids = [row[0] for row in plan_rows]
    if plan_ids:
        placeholders = ','.join('?' for _ in plan_ids)
        conn.execute(f"DELETE FROM cp_prediction_ticket_results WHERE plan_id IN ({placeholders})", plan_ids)
        conn.execute(f"DELETE FROM cp_prediction_tickets WHERE plan_id IN ({placeholders})", plan_ids)
    conn.execute("DELETE FROM cp_prediction_plans WHERE issue_code=?", (issue_code,))
    conn.commit()


def create_predictions(conn: sqlite3.Connection, force: bool = False) -> Dict:
    ensure_prediction_tables(conn)
    draws = load_draws(conn)
    if len(draws) < 30:
        raise SystemExit('数据不足，无法生成预测')
    latest = draws[-1]
    issue_code = infer_next_issue(latest['issue_code'])
    existing = load_plan_bundle(conn, issue_code)
    if existing and not force:
        return {'mode': 'existing', 'issue_code': issue_code, 'plans': existing}
    if existing and force:
        delete_prediction_issue(conn, issue_code)
    payloads = build_prediction_payloads(draws)
    now = now_iso()
    inserted = []
    for payload in payloads:
        tickets = payload['tickets']
        summary = summarize_plan(payload['plan_type'], tickets)
        cur = conn.execute(
            '''INSERT INTO cp_prediction_plans (
                 issue_code, strategy_version, plan_type, bet_type, budget, ticket_count,
                 bet_count, cost, blues, summary_json, reason_json, status, created_at, updated_at
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'predicted', ?, ?)''',
            (
                issue_code,
                STRATEGY_VERSION,
                payload['plan_type'],
                payload['bet_type'],
                payload['budget'],
                len(tickets),
                summary['bet_count'],
                summary['cost'],
                summary['blues'],
                json.dumps(summary, ensure_ascii=False),
                json.dumps(payload['reason'], ensure_ascii=False),
                now,
                now,
            ),
        )
        plan_id = cur.lastrowid
        for ticket in tickets:
            conn.execute(
                '''INSERT INTO cp_prediction_tickets (
                     plan_id, ticket_no, label, reds, blues, bet_count, cost, created_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
                (
                    plan_id,
                    ticket['ticket_no'],
                    ticket['label'],
                    fmt_nums(ticket['reds']),
                    fmt_nums(ticket['blues']),
                    ticket['bet_count'],
                    ticket['cost'],
                    now,
                ),
            )
        inserted.append({
            'plan_type': payload['plan_type'],
            'bet_type': payload['bet_type'],
            'summary': summary,
            'reason': payload['reason'],
        })
    conn.commit()
    PRED_LOG.parent.mkdir(parents=True, exist_ok=True)
    with PRED_LOG.open('a', encoding='utf-8') as f:
        f.write(json.dumps({'issue_code': issue_code, 'plans': inserted, 'created_at': now}, ensure_ascii=False) + '\n')
    return {'mode': 'created', 'issue_code': issue_code, 'plans': load_plan_bundle(conn, issue_code)}


def settle_issue(conn: sqlite3.Connection, issue_code: str) -> Dict:
    ensure_prediction_tables(conn)
    plans = load_plan_bundle(conn, issue_code)
    if not plans:
        return {'mode': 'noop', 'reason': 'no_pending_prediction'}
    draw = load_draw(conn, issue_code)
    if not draw:
        return {'mode': 'waiting', 'issue_code': issue_code}
    now = now_iso()
    settled_plans = []
    for plan in plans:
        ticket_results = []
        total_bonus = 0
        winning_tickets = 0
        best_hit = ''
        best_score = (-1, -1)
        for ticket in plan['tickets']:
            reds = parse_nums(ticket['reds'])
            blues = parse_nums(ticket['blues'])
            hit_red, hit_blue, prize_level, return_amount, breakdown = single_ticket_return(reds, blues, draw)
            conn.execute(
                '''INSERT INTO cp_prediction_ticket_results (
                     issue_code, plan_id, ticket_id, draw_date, draw_reds, draw_blue,
                     hit_red, hit_blue, prize_level, return_amount, prize_breakdown_json,
                     created_at, updated_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(issue_code, ticket_id) DO UPDATE SET
                     hit_red=excluded.hit_red,
                     hit_blue=excluded.hit_blue,
                     prize_level=excluded.prize_level,
                     return_amount=excluded.return_amount,
                     prize_breakdown_json=excluded.prize_breakdown_json,
                     updated_at=excluded.updated_at''',
                (
                    issue_code,
                    plan['id'],
                    ticket['id'],
                    draw['draw_date'],
                    fmt_nums(draw['reds']),
                    f"{draw['blue']:02d}",
                    hit_red,
                    1 if hit_blue else 0,
                    prize_level,
                    return_amount,
                    json.dumps(breakdown, ensure_ascii=False),
                    now,
                    now,
                ),
            )
            total_bonus += return_amount
            if return_amount > 0:
                winning_tickets += 1
            if (hit_red, int(hit_blue)) > best_score:
                best_score = (hit_red, int(hit_blue))
                best_hit = f'红{hit_red}蓝{1 if hit_blue else 0}'
            ticket_results.append({
                'ticket_no': ticket['ticket_no'],
                'label': ticket['label'],
                'reds': ticket['reds'],
                'blues': ticket['blues'],
                'hit_red': hit_red,
                'hit_blue': bool(hit_blue),
                'prize_level': prize_level,
                'return_amount': return_amount,
                'breakdown': breakdown,
            })
        roi = round(total_bonus / plan['cost'], 4) if plan['cost'] else 0.0
        hit_red_values = [item['hit_red'] for item in ticket_results]
        hit_blue_count = sum(1 for item in ticket_results if item['hit_blue'])
        max_hit_red = max(hit_red_values) if hit_red_values else 0
        logic_text = (plan.get('reason') or {}).get('logic', '')
        if winning_tickets:
            miss_reason = '本期已有回报，但最高命中层级未顶到冲二等区，说明覆盖有用、核心骨架仍未咬中最关键那一层。'
        elif max_hit_red >= 4 or hit_blue_count > 0:
            miss_reason = '号码方向未完全走偏，但红球关键第5、第6位未补齐，蓝球防守亦未转成有效奖金。'
        else:
            miss_reason = '红球主骨架整体偏离开奖号，中段与高段衔接不足，蓝球亦未同步命中。'
        next_fix = '下期继续控和值90-120，保留1组二连号，优先修正中段密度与20段补位，蓝球继续在03/08/11内收窄。'
        result = {
            'issue_code': issue_code,
            'draw_date': draw['draw_date'],
            'draw_reds': fmt_nums(draw['reds']),
            'draw_blue': f"{draw['blue']:02d}",
            'plan_type': plan['plan_type'],
            'ticket_count': len(plan['tickets']),
            'total_cost': plan['cost'],
            'winning_tickets': winning_tickets,
            'total_bonus': total_bonus,
            'roi': roi,
            'best_hit_summary': best_hit,
            'logic': logic_text,
            'hit_blue_ticket_count': hit_blue_count,
            'max_hit_red': max_hit_red,
            'miss_reason': miss_reason,
            'next_fix': next_fix,
            'ticket_results': ticket_results,
        }
        conn.execute(
            '''UPDATE cp_prediction_plans
               SET status='settled', draw_date=?, result_json=?, updated_at=?
               WHERE id=?''',
            (draw['draw_date'], json.dumps(result, ensure_ascii=False), now, plan['id']),
        )
        settled_plans.append({
            'plan_type': plan['plan_type'],
            'bet_type': plan['bet_type'],
            'cost': plan['cost'],
            'result': result,
            'summary': plan['summary'],
        })
    conn.commit()
    return {'mode': 'settled', 'issue_code': issue_code, 'draw': draw, 'plans': settled_plans}


def get_issue_report(conn: sqlite3.Connection, issue_code: str | None = None) -> Dict:
    ensure_prediction_tables(conn)
    if issue_code is None:
        # Check if there are any unsettled predictions that can now be settled
        pending_rows = conn.execute(
            "SELECT DISTINCT issue_code FROM cp_prediction_plans WHERE status != 'settled' ORDER BY issue_code ASC"
        ).fetchall()
        settled_any = False
        last_settled_result = None
        for (pending_issue,) in pending_rows:
            draw = load_draw(conn, pending_issue)
            if draw:
                last_settled_result = settle_issue(conn, pending_issue)
                settled_any = True
        if settled_any:
            return last_settled_result

        row = conn.execute(
            "SELECT issue_code FROM cp_prediction_plans ORDER BY issue_code DESC LIMIT 1"
        ).fetchone()
        if not row:
            return {'mode': 'noop', 'reason': 'no_prediction_found'}
        issue_code = row[0]
    plans = load_plan_bundle(conn, issue_code)
    if not plans:
        return {'mode': 'noop', 'reason': 'no_prediction_for_issue', 'issue_code': issue_code}
    if any(plan['status'] != 'settled' for plan in plans):
        return settle_issue(conn, issue_code)
    draw = load_draw(conn, issue_code)
    return {'mode': 'already_settled', 'issue_code': issue_code, 'draw': draw, 'plans': plans}


def settle_next_pending(conn: sqlite3.Connection) -> Dict:
    ensure_prediction_tables(conn)
    row = conn.execute(
        "SELECT issue_code FROM cp_prediction_plans WHERE status='predicted' ORDER BY issue_code ASC LIMIT 1"
    ).fetchone()
    if not row:
        return {'mode': 'noop', 'reason': 'no_pending_prediction'}
    return settle_issue(conn, row[0])
