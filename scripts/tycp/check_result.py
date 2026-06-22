#!/usr/bin/env python3
from __future__ import annotations
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

# This default path is rewritten by legacy.py to traeclaw.sqlite3 when run via traeclaw
DB_PATH = Path('/home/eric/Documents/workspace/state/tycp/data/dlt_history.sqlite3')

def main():
    db_file = DB_PATH
    if not db_file.exists():
        fallback_path = Path(__file__).resolve().parents[2] / "data" / "traeclaw.sqlite3"
        if fallback_path.exists():
            db_file = fallback_path

    # 1. Fetch latest draw from API to database
    fetch_script = Path(__file__).parent / "fetch_dlt.py"
    cmd_fetch = [
        sys.executable,
        str(Path(__file__).resolve().parents[2] / "traeclaw" / "tasks" / "legacy.py"),
        str(fetch_script),
        "--mode", "latest"
    ]
    subprocess.run(cmd_fetch, capture_output=True)

    # 2. Query the latest draw number from dlt_results
    conn = sqlite3.connect(db_file)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    last_draw_row = cur.execute('SELECT draw_num FROM dlt_results ORDER BY draw_num DESC LIMIT 1').fetchone()
    if not last_draw_row:
        print(json.dumps({"error": "No draw results in database"}, ensure_ascii=False))
        sys.exit(1)
    
    draw_num = last_draw_row['draw_num']
    conn.close()

    # 3. Check results against prediction plan for that draw number
    review_script = Path(__file__).parent / "dlt_review_draw.py"
    cmd_review = [
        sys.executable,
        str(Path(__file__).resolve().parents[2] / "traeclaw" / "tasks" / "legacy.py"),
        str(review_script),
        "--draw-num", draw_num
    ]
    review_res = subprocess.run(cmd_review, capture_output=True, text=True)
    if review_res.returncode != 0:
        if "未找到方案" in review_res.stderr or "未找到方案" in review_res.stdout:
            print(json.dumps({
                "mode": "waiting",
                "issue_code": draw_num,
                "summary_text": f"第 {draw_num} 期开奖已更新，但未找到对应的推荐购买方案，无法复盘。"
            }, ensure_ascii=False, indent=2))
            sys.exit(0)
            
        print(json.dumps({
            "error": "Failed to run review",
            "stdout": review_res.stdout,
            "stderr": review_res.stderr
        }, ensure_ascii=False))
        sys.exit(1)

    try:
        obj = json.loads(review_res.stdout)
        obj["summary_text"] = obj["report_text"]
        print(json.dumps(obj, ensure_ascii=False, indent=2))
    except Exception as e:
        print(json.dumps({
            "error": f"Failed to parse review output: {str(e)}",
            "stdout": review_res.stdout
        }, ensure_ascii=False))
        sys.exit(1)

if __name__ == '__main__':
    main()
