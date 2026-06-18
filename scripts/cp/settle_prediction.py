#!/usr/bin/env python3
import argparse
import json
import sqlite3

from cp_prediction_core import DB_PATH, get_issue_report, settle_next_pending


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--issue', default='', help='指定期号复盘')
    parser.add_argument('--latest', action='store_true', help='优先输出最新已记录期号的复盘')
    args = parser.parse_args()
    conn = sqlite3.connect(DB_PATH)
    if args.issue:
        obj = get_issue_report(conn, args.issue)
    elif args.latest:
        obj = get_issue_report(conn)
    else:
        obj = settle_next_pending(conn)
    print(json.dumps(obj, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
