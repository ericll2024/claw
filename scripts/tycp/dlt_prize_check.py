import argparse
import json
import sqlite3
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


def normalize(nums):
    return sorted([f'{int(x):02d}' for x in nums])


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


def fixed_prize(prize, pool_balance_afterdraw=None):
    if not prize:
        return 0, '未中奖'
    if prize in ('一等奖', '二等奖'):
        return None, '浮动奖'
    high = False
    if pool_balance_afterdraw is not None:
        try:
            val = float(str(pool_balance_afterdraw).replace(',', ''))
            high = val >= 800000000
        except Exception:
            high = False
    base = BASE_PRIZES_HIGH if high else BASE_PRIZES_LOW
    amount = base[prize]
    return amount, '固定奖'


def fetch_draw(draw_num):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    has_history = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='dlt_history'").fetchone()
    if has_history:
        columns = [r[1] for r in conn.execute("PRAGMA table_info(dlt_history)").fetchall()]
        if 'poolBalanceAfterdraw' in columns:
            row = conn.execute('''
                SELECT r.*, h.poolBalanceAfterdraw as pool_balance_afterdraw
                FROM dlt_results r
                LEFT JOIN dlt_history h ON h.lottery_draw_num = r.draw_num
                WHERE r.draw_num = ?
            ''', (draw_num,)).fetchone()
        else:
            row = conn.execute('SELECT *, NULL as pool_balance_afterdraw FROM dlt_results WHERE draw_num = ?', (draw_num,)).fetchone()
    else:
        row = conn.execute('SELECT *, NULL as pool_balance_afterdraw FROM dlt_results WHERE draw_num = ?', (draw_num,)).fetchone()
    conn.close()
    return row


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--draw-num', required=True)
    parser.add_argument('--front', nargs=5, required=True)
    parser.add_argument('--back', nargs=2, required=True)
    parser.add_argument('--additional', action='store_true')
    args = parser.parse_args()

    row = fetch_draw(args.draw_num)
    if not row:
        raise SystemExit(f'未找到期开奖: {args.draw_num}')

    front = normalize(args.front)
    back = normalize(args.back)
    win_front = normalize([row['front_1'], row['front_2'], row['front_3'], row['front_4'], row['front_5']])
    win_back = normalize([row['back_1'], row['back_2']])

    hf, hb, prize = judge(front, back, win_front, win_back)
    amount, prize_type = fixed_prize(prize, row['pool_balance_afterdraw'])

    result = {
        'draw_num': args.draw_num,
        'ticket_front': front,
        'ticket_back': back,
        'winning_front': win_front,
        'winning_back': win_back,
        'hit_front_count': hf,
        'hit_back_count': hb,
        'prize_level': prize or '未中奖',
        'prize_type': prize_type,
        'prize_amount': amount,
        'is_additional': args.additional,
    }

    if args.additional and prize in ('一等奖', '二等奖'):
        result['additional_note'] = '追加投注仅对浮动奖生效，追加奖金约为基本投注对应单注奖金的80%'

    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
