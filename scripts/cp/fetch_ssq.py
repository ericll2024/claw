#!/usr/bin/env python3
import argparse
import json
import os
import random
import sqlite3
import sys
import time
from datetime import datetime, timezone
from urllib.parse import urlencode

import requests

API_URL = 'https://www.cwl.gov.cn/cwl_admin/front/cwlkj/search/kjxx/findDrawNotice'
DEFAULT_DB = os.path.join(os.path.dirname(os.path.dirname(__file__)), '..', 'state', 'cp', 'doublecolor.db')

CREATE_SQL = '''
CREATE TABLE IF NOT EXISTS ssq_draws (
  issue_code TEXT PRIMARY KEY,
  draw_date TEXT NOT NULL,
  draw_week TEXT,
  year INTEGER,
  sub_code TEXT,
  red1 INTEGER NOT NULL,
  red2 INTEGER NOT NULL,
  red3 INTEGER NOT NULL,
  red4 INTEGER NOT NULL,
  red5 INTEGER NOT NULL,
  red6 INTEGER NOT NULL,
  blue INTEGER NOT NULL,
  red_sum INTEGER NOT NULL,
  total_sum INTEGER NOT NULL,
  source_url TEXT,
  raw_json TEXT,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ssq_draws_draw_date ON ssq_draws(draw_date DESC);
CREATE INDEX IF NOT EXISTS idx_ssq_draws_year ON ssq_draws(year DESC);
'''


def fetch_page(session, page_no: int, page_size: int, extra_params=None):
    params = {
        'name': 'ssq',
        'pageNo': page_no,
        'pageSize': page_size,
        'systemType': 'PC',
    }
    if extra_params:
        params.update({k: v for k, v in extra_params.items() if v not in (None, '')})
    url = f"{API_URL}?{urlencode(params)}"
    headers = {
        'Accept': 'application/json, text/javascript, */*; q=0.01',
        'Accept-Language': 'zh',
        'Connection': 'keep-alive',
        'Referer': 'https://www.cwl.gov.cn/ygkj/wqkjgg/ssq/',
        'Sec-Fetch-Dest': 'empty',
        'Sec-Fetch-Mode': 'cors',
        'Sec-Fetch-Site': 'same-origin',
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36',
        'X-Requested-With': 'XMLHttpRequest',
        'sec-ch-ua': '"Google Chrome";v="147", "Not.A/Brand";v="8", "Chromium";v="147"',
        'sec-ch-ua-mobile': '?0',
        'sec-ch-ua-platform': '"macOS"',
    }
    session.cookies.set('HMF_CI', 'c936832cc656596be5d5ead359df602fa7cd71c62cb1af085461f9e1f38b11643b30d9c98a7914f61b8dde1efd77669ae46ec2b3c13737d87b3ce7abd0ae8fcc92', domain='www.cwl.gov.cn', path='/')
    session.cookies.set('21_vq', '3', domain='www.cwl.gov.cn', path='/')
    last_err = None
    for attempt in range(5):
        try:
            resp = session.get(API_URL, params=params, timeout=30, headers=headers)
            resp.raise_for_status()
            return url, resp.json()
        except Exception as e:
            last_err = e
            if attempt < 4:
                time.sleep(0.8 + random.random() * 1.6)
    raise last_err


def parse_date(raw: str):
    if not raw:
        return None, None
    date_part = raw.split('(')[0]
    week = raw.split('(')[1].rstrip(')') if '(' in raw else None
    return date_part, week


def ensure_db(conn):
    conn.executescript(CREATE_SQL)
    conn.commit()


def upsert_rows(conn, rows, source_url):
    inserted = 0
    updated = 0
    now = datetime.now(timezone.utc).isoformat()
    for row in rows:
        code = row.get('code')
        red = row.get('red', '')
        blue = row.get('blue')
        if not code or not red or blue in (None, ''):
            continue
        reds = [int(x) for x in red.split(',') if x.strip()]
        if len(reds) != 6:
            continue
        blue_int = int(blue)
        draw_date, draw_week = parse_date(row.get('date', ''))
        year = int(code[:4]) if len(code) >= 4 and code[:4].isdigit() else None
        sub_code = code[-3:] if len(code) >= 3 else None
        red_sum = sum(reds)
        total_sum = red_sum + blue_int
        payload = (
            code, draw_date, draw_week, year, sub_code,
            *reds, blue_int, red_sum, total_sum,
            source_url, json.dumps(row, ensure_ascii=False, sort_keys=True), now,
        )
        cur = conn.execute('SELECT 1 FROM ssq_draws WHERE issue_code = ?', (code,))
        exists = cur.fetchone() is not None
        conn.execute('''
            INSERT INTO ssq_draws (
              issue_code, draw_date, draw_week, year, sub_code,
              red1, red2, red3, red4, red5, red6,
              blue, red_sum, total_sum, source_url, raw_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(issue_code) DO UPDATE SET
              draw_date=excluded.draw_date,
              draw_week=excluded.draw_week,
              year=excluded.year,
              sub_code=excluded.sub_code,
              red1=excluded.red1,
              red2=excluded.red2,
              red3=excluded.red3,
              red4=excluded.red4,
              red5=excluded.red5,
              red6=excluded.red6,
              blue=excluded.blue,
              red_sum=excluded.red_sum,
              total_sum=excluded.total_sum,
              source_url=excluded.source_url,
              raw_json=excluded.raw_json
        ''', payload)
        if exists:
            updated += 1
        else:
            inserted += 1
    conn.commit()
    return inserted, updated


def summarize_latest(conn, limit=5):
    cur = conn.execute('''
      SELECT issue_code, draw_date, red1, red2, red3, red4, red5, red6, blue, red_sum, total_sum
      FROM ssq_draws ORDER BY issue_code DESC LIMIT ?
    ''', (limit,))
    rows = cur.fetchall()
    lines = []
    for r in rows:
        reds = ','.join(f'{n:02d}' for n in r[2:8])
        lines.append(f"{r[0]} {r[1]} | 红球 {reds} | 蓝球 {r[8]:02d} | 红和 {r[9]} | 总和 {r[10]}")
    return lines


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--db', default=DEFAULT_DB)
    p.add_argument('--mode', choices=['full', 'latest'], default='latest')
    p.add_argument('--page-size', type=int, default=30)
    p.add_argument('--latest-pages', type=int, default=1)
    p.add_argument('--max-pages', type=int, default=0)
    p.add_argument('--issue-start', default='')
    p.add_argument('--issue-end', default='')
    p.add_argument('--issue-count', default='')
    p.add_argument('--day-start', default='')
    p.add_argument('--day-end', default='')
    p.add_argument('--week', default='')
    args = p.parse_args()

    os.makedirs(os.path.dirname(os.path.abspath(args.db)), exist_ok=True)
    conn = sqlite3.connect(args.db)
    ensure_db(conn)

    total_inserted = 0
    total_updated = 0
    total_rows = 0
    page_no = 1
    pages_done = 0
    stop_after = args.latest_pages if args.mode == 'latest' else None
    session = requests.Session()
    extra_params = {
        'issueStart': args.issue_start,
        'issueEnd': args.issue_end,
        'issueCount': args.issue_count,
        'dayStart': args.day_start,
        'dayEnd': args.day_end,
        'week': args.week,
    }

    while True:
        source_url, data = fetch_page(session, page_no, args.page_size, extra_params=extra_params)
        rows = data.get('result') or []
        if not rows:
            break
        inserted, updated = upsert_rows(conn, rows, source_url)
        total_inserted += inserted
        total_updated += updated
        total_rows += len(rows)
        pages_done += 1
        if args.mode == 'latest' and page_no >= stop_after:
            break
        if args.mode == 'full':
            page_num = data.get('pageNum')
            if args.max_pages and page_no >= args.max_pages:
                break
            if page_num and page_no >= int(page_num):
                break
        page_no += 1
        if args.mode == 'full':
            time.sleep(1.2 + random.random() * 1.8)

    cur = conn.execute('SELECT COUNT(*) FROM ssq_draws')
    db_total = cur.fetchone()[0]
    latest = summarize_latest(conn)
    print(json.dumps({
        'mode': args.mode,
        'pages_processed': pages_done,
        'rows_seen': total_rows,
        'inserted': total_inserted,
        'updated': total_updated,
        'db_total': db_total,
        'latest': latest,
        'db_path': os.path.abspath(args.db),
        'filters': {k: v for k, v in extra_params.items() if v not in (None, '')},
    }, ensure_ascii=False, indent=2))

if __name__ == '__main__':
    main()
