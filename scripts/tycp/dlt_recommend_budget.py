#!/usr/bin/env python3
from __future__ import annotations
import argparse
import json
import os
import sqlite3
import subprocess
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

# This default path is rewritten by legacy.py to traeclaw.sqlite3 when run via traeclaw
DB_PATH = Path('/home/eric/Documents/workspace/state/tycp/data/dlt_history.sqlite3')

# Add current folder to sys.path to import dlt_recommend
sys.path.insert(0, str(Path(__file__).parent))
import dlt_recommend


def infer_next_draw(last_draw: str) -> str:
    year = int(last_draw[:2])
    seq = int(last_draw[2:])
    if seq >= 155:
        return f"{year+1:02d}001"
    else:
        return f"{year:02d}{seq+1:03d}"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--front-pool', default='')
    parser.add_argument('--back-pool', default='')
    parser.add_argument('--draw-num', default='')
    args = parser.parse_args()

    # Determine database path (in case it is not rewritten by legacy.py)
    db_file = DB_PATH
    if not db_file.exists():
        # Fallback to local traeclaw database if we are running outside legacy.py
        fallback_path = Path(__file__).resolve().parents[2] / "data" / "traeclaw.sqlite3"
        if fallback_path.exists():
            db_file = fallback_path

    # 1. Fetch latest draw to infer draw_num
    conn = sqlite3.connect(db_file)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    
    last_draw_row = cur.execute('SELECT draw_num FROM dlt_results ORDER BY draw_num DESC LIMIT 1').fetchone()
    if last_draw_row:
        last_draw = last_draw_row['draw_num']
    else:
        last_draw = '26068'  # fallback
    
    draw_num = args.draw_num if args.draw_num else infer_next_draw(last_draw)
    
    # 2. Get recommendations
    front_pool = dlt_recommend.parse_pool(args.front_pool, dlt_recommend.DEFAULT_FRONT_POOL)
    back_pool = dlt_recommend.parse_pool(args.back_pool, dlt_recommend.DEFAULT_BACK_POOL)
    
    # Generate a large limit of recommendations to extract frequencies
    recommendations = dlt_recommend.recommend(front_pool, back_pool, limit=1000)
    
    if not recommendations:
        print(json.dumps({"error": "No recommendations generated under the current rules"}, ensure_ascii=False))
        sys.exit(1)
        
    # 3. Pick the core front and back numbers from the top recommendation
    base_front = recommendations[0]['front']
    base_back = recommendations[0]['back']
    
    # 4. Count frequencies of front numbers in high-scoring recommendations
    front_counts = Counter()
    for r in recommendations:
        for num in r['front']:
            front_counts[num] += 1
            
    # Sort remaining front pool numbers by frequency descending
    remaining = [f"{num:02d}" for num in sorted(set(front_pool))]
    remaining = [num for num in remaining if num not in base_front]
    remaining.sort(key=lambda num: (-front_counts.get(num, 0), num))
    
    # Form the budget combinations
    front_8 = sorted(base_front + remaining[:3])
    front_10 = sorted(base_front + remaining[:5])
    front_11 = sorted(base_front + remaining[:6])
    
    # Write the 1000 RMB single tickets (expanded budget_1000) to a temporary file
    # for dlt_store_plan.py to consume
    singles_dir = Path(__file__).resolve().parents[2] / "tmp"
    singles_dir.mkdir(parents=True, exist_ok=True)
    singles_file_path = singles_dir / "dlt_singles.json"
    
    singles_data = [
        {
            "ticket_type": "budget_1000",
            "label": "1000元档",
            "front": " ".join(front_11),
            "back": " ".join(base_back)
        }
    ]
    singles_file_path.write_text(json.dumps(singles_data, ensure_ascii=False), encoding="utf-8")
    
    # 5. Call dlt_store_plan.py via subprocess to write everything to traeclaw.sqlite3
    plan_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    store_plan_script = Path(__file__).parent / "dlt_store_plan.py"
    
    # budget = 112 (for 8+2) + 252 (for 9+2) + 924 (for 11+2)? 
    # Wait, the user wants 100, 500, 1000.
    # 100元档: 8+2 (112元)
    # 500元档: 10+2 (504元)
    # 1000元档: 11+2 (924元)
    # Total budget = 112 + 504 + 924 = 1540
    budget = 1540.0
    
    # We call dlt_store_plan.py using the legacy.py runner to ensure path rewrites work
    # We pass the main combination as front_8, reference combination as front_10, 
    # and singles file containing the front_11 combination.
    cmd = [
        sys.executable,
        str(Path(__file__).resolve().parents[2] / "traeclaw" / "tasks" / "legacy.py"),
        str(store_plan_script),
        "--draw-num", draw_num,
        "--plan-time", plan_time,
        "--budget", str(budget),
        "--strategy-model", "dlt-recommend-budget",
        "--front-core", ",".join(base_front),
        "--front-secondary", ",".join(front_11),
        "--back-core", ",".join(base_back),
        "--main-ticket-type", "8+2",
        "--main-front", " ".join(front_8),
        "--main-back", " ".join(base_back),
        "--main-label", "100元档",
        "--ref-front", " ".join(front_10),
        "--ref-back", " ".join(base_back),
        "--ref-label", "500元档",
        "--singles-file", str(singles_file_path),
        "--logic-text", f"前区以核心{','.join(base_front)}为基础，后区主防{','.join(base_back)}。通过推荐频率扩展：100元档选8码复式，500元档选10码复式，1000元档选11码复式。"
    ]
    
    store_res = subprocess.run(cmd, capture_output=True, text=True)
    if store_res.returncode != 0:
        print(json.dumps({
            "error": "Failed to store plan",
            "stdout": store_res.stdout,
            "stderr": store_res.stderr
        }, ensure_ascii=False))
        sys.exit(1)
        
    # Clean up singles file
    if singles_file_path.exists():
        singles_file_path.unlink()
        
    # 6. Build summary response
    summary_text = (
        f"大乐透第 {draw_num} 期组合推荐已生成并保存：\n"
        f"- **100元档 (8+2)**: 前区 {' '.join(front_8)} | 后区 {' '.join(base_back)}，成本 112 元\n"
        f"- **500元档 (10+2)**: 前区 {' '.join(front_10)} | 后区 {' '.join(base_back)}，成本 504 元\n"
        f"- **1000元档 (11+2)**: 前区 {' '.join(front_11)} | 后区 {' '.join(base_back)}，成本 924 元"
    )
    
    result = {
        "draw_num": draw_num,
        "plan_time": plan_time,
        "budget": budget,
        "strategy_model": "dlt-recommend-budget",
        "combinations": {
            "100": {
                "label": "100元档组合",
                "front": front_8,
                "back": base_back,
                "cost": 112.0
            },
            "500": {
                "label": "500元档组合",
                "front": front_10,
                "back": base_back,
                "cost": 504.0
            },
            "1000": {
                "label": "1000元档组合",
                "front": front_11,
                "back": base_back,
                "cost": 924.0
            }
        },
        "summary_text": summary_text
    }
    
    print(json.dumps(result, ensure_ascii=False, indent=2))
    conn.close()


if __name__ == '__main__':
    main()
