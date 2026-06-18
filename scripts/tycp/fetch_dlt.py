#!/usr/bin/env python3
import argparse
import json
import os
import random
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
import requests

# This default path is rewritten by legacy.py to traeclaw.sqlite3 when run via traeclaw
DB_PATH = Path('/home/eric/Documents/workspace/state/tycp/data/dlt_history.sqlite3')

API_URL = 'https://webapi.sporttery.cn/gateway/lottery/getHistoryPageListV1.qry'

def fetch_page(session, page_no: int, page_size: int):
    params = {
        'gameNo': '85',       # 85 is Super Lotto (大乐透)
        'provinceId': '0',
        'pageSize': str(page_size),
        'pageNo': str(page_no),
        'isVerify': '1'
    }
    headers = {
        'Accept': '*/*',
        'Accept-Language': 'zh-CN,zh;q=0.9',
        'Connection': 'keep-alive',
        'Referer': 'https://www.lottery.gov.cn/',
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }
    last_err = None
    for attempt in range(5):
        try:
            resp = session.get(API_URL, params=params, timeout=30, headers=headers)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            last_err = e
            if attempt < 4:
                time.sleep(1.0 + random.random() * 2.0)
    raise last_err

def ensure_db(conn):
    # Ensure dlt_results table exists
    conn.executescript('''
    CREATE TABLE IF NOT EXISTS dlt_results (
        draw_num TEXT PRIMARY KEY,
        draw_time TEXT NOT NULL,
        front_1 TEXT NOT NULL,
        front_2 TEXT NOT NULL,
        front_3 TEXT NOT NULL,
        front_4 TEXT NOT NULL,
        front_5 TEXT NOT NULL,
        back_1 TEXT NOT NULL,
        back_2 TEXT NOT NULL,
        raw_result TEXT NOT NULL,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX IF NOT EXISTS idx_dlt_results_draw_time ON dlt_results(draw_time DESC);
    ''')
    
    # Check if dlt_history table exists, and make sure it has poolBalanceAfterdraw if possible
    has_history = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='dlt_history'").fetchone()
    if has_history:
        columns = [r[1] for r in conn.execute("PRAGMA table_info(dlt_history)").fetchall()]
        if 'poolBalanceAfterdraw' not in columns:
            try:
                conn.execute("ALTER TABLE dlt_history ADD COLUMN poolBalanceAfterdraw TEXT")
                conn.commit()
            except Exception as e:
                print(f"Warning: failed to add poolBalanceAfterdraw column: {e}", file=sys.stderr)
    conn.commit()

def upsert_rows(conn, rows):
    inserted = 0
    updated = 0
    
    # Get columns of dlt_history dynamically
    has_history = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='dlt_history'").fetchone()
    history_columns = []
    if has_history:
        history_columns = [r[1] for r in conn.execute("PRAGMA table_info(dlt_history)").fetchall()]
        
    for row in rows:
        draw_num = row.get('lotteryDrawNum')
        draw_time = row.get('lotteryDrawTime')
        result_str = row.get('lotteryDrawResult')
        pool_balance = row.get('poolBalanceAfterdraw')
        
        if not draw_num or not draw_time or not result_str:
            continue
            
        parts = result_str.split(' ')
        if len(parts) != 7:
            continue
            
        front_1, front_2, front_3, front_4, front_5 = parts[0], parts[1], parts[2], parts[3], parts[4]
        back_1, back_2 = parts[5], parts[6]
        
        # dlt_results raw_result expects space separated string of all numbers
        raw_result = result_str
        
        # Check if already exists in dlt_results
        exists = conn.execute("SELECT 1 FROM dlt_results WHERE draw_num = ?", (draw_num,)).fetchone() is not None
        
        # Insert or update dlt_results
        conn.execute('''
            INSERT INTO dlt_results (
                draw_num, draw_time, front_1, front_2, front_3, front_4, front_5, back_1, back_2, raw_result
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(draw_num) DO UPDATE SET
                draw_time=excluded.draw_time,
                front_1=excluded.front_1,
                front_2=excluded.front_2,
                front_3=excluded.front_3,
                front_4=excluded.front_4,
                front_5=excluded.front_5,
                back_1=excluded.back_1,
                back_2=excluded.back_2,
                raw_result=excluded.raw_result
        ''', (draw_num, draw_time, front_1, front_2, front_3, front_4, front_5, back_1, back_2, raw_result))
        
        # Insert or update dlt_history if table exists
        if has_history:
            if 'poolBalanceAfterdraw' in history_columns:
                conn.execute('''
                    INSERT INTO dlt_history (
                        lottery_draw_num, lottery_draw_time, lottery_draw_result,
                        front_1, front_2, front_3, front_4, front_5, back_1, back_2, poolBalanceAfterdraw
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(lottery_draw_num) DO UPDATE SET
                        lottery_draw_time=excluded.lottery_draw_time,
                        lottery_draw_result=excluded.lottery_draw_result,
                        front_1=excluded.front_1,
                        front_2=excluded.front_2,
                        front_3=excluded.front_3,
                        front_4=excluded.front_4,
                        front_5=excluded.front_5,
                        back_1=excluded.back_1,
                        back_2=excluded.back_2,
                        poolBalanceAfterdraw=excluded.poolBalanceAfterdraw
                ''', (draw_num, draw_time, raw_result, front_1, front_2, front_3, front_4, front_5, back_1, back_2, pool_balance))
            else:
                conn.execute('''
                    INSERT INTO dlt_history (
                        lottery_draw_num, lottery_draw_time, lottery_draw_result,
                        front_1, front_2, front_3, front_4, front_5, back_1, back_2
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(lottery_draw_num) DO UPDATE SET
                        lottery_draw_time=excluded.lottery_draw_time,
                        lottery_draw_result=excluded.lottery_draw_result,
                        front_1=excluded.front_1,
                        front_2=excluded.front_2,
                        front_3=excluded.front_3,
                        front_4=excluded.front_4,
                        front_5=excluded.front_5,
                        back_1=excluded.back_1,
                        back_2=excluded.back_2
                ''', (draw_num, draw_time, raw_result, front_1, front_2, front_3, front_4, front_5, back_1, back_2))
                
        if exists:
            updated += 1
        else:
            inserted += 1
            
    conn.commit()
    return inserted, updated

def summarize_latest(conn, limit=5):
    cur = conn.execute('''
        SELECT draw_num, draw_time, front_1, front_2, front_3, front_4, front_5, back_1, back_2
        FROM dlt_results ORDER BY draw_num DESC LIMIT ?
    ''', (limit,))
    rows = cur.fetchall()
    lines = []
    for r in rows:
        fronts = f"{r[2]},{r[3]},{r[4]},{r[5]},{r[6]}"
        backs = f"{r[7]},{r[8]}"
        lines.append(f"{r[0]} {r[1]} | 前区 {fronts} | 后区 {backs}")
    return lines

def main():
    p = argparse.ArgumentParser(description="Fetch DLT (Super Lotto) draw results")
    p.add_argument('--db', default=None)
    p.add_argument('--mode', choices=['full', 'latest'], default='latest')
    p.add_argument('--page-size', type=int, default=30)
    p.add_argument('--latest-pages', type=int, default=1)
    p.add_argument('--max-pages', type=int, default=0)
    args = p.parse_args()
    
    # Determine the database path
    target_db = args.db if args.db else str(DB_PATH)
    os.makedirs(os.path.dirname(os.path.abspath(target_db)), exist_ok=True)
    
    conn = sqlite3.connect(target_db)
    ensure_db(conn)
    
    total_inserted = 0
    total_updated = 0
    total_rows = 0
    page_no = 1
    pages_done = 0
    stop_after = args.latest_pages if args.mode == 'latest' else None
    session = requests.Session()
    
    while True:
        try:
            data = fetch_page(session, page_no, args.page_size)
        except Exception as e:
            print(f"Error fetching page {page_no}: {e}", file=sys.stderr)
            break
            
        value_data = data.get('value') or {}
        rows = value_data.get('list') or []
        if not rows:
            break
            
        inserted, updated = upsert_rows(conn, rows)
        total_inserted += inserted
        total_updated += updated
        total_rows += len(rows)
        pages_done += 1
        
        if args.mode == 'latest' and page_no >= stop_after:
            break
            
        if args.mode == 'full':
            pages_total = value_data.get('pages') or 0
            if args.max_pages and page_no >= args.max_pages:
                break
            if pages_total and page_no >= int(pages_total):
                break
                
        page_no += 1
        time.sleep(1.2 + random.random() * 1.8)
        
    cur = conn.execute('SELECT COUNT(*) FROM dlt_results')
    db_total = cur.fetchone()[0]
    latest = summarize_latest(conn)
    conn.close()
    
    print(json.dumps({
        'mode': args.mode,
        'pages_processed': pages_done,
        'rows_seen': total_rows,
        'inserted': total_inserted,
        'updated': total_updated,
        'db_total': db_total,
        'latest': latest,
        'db_path': os.path.abspath(target_db),
    }, ensure_ascii=False, indent=2))

if __name__ == '__main__':
    main()
