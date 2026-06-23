#!/usr/bin/env python3
import argparse
import json
import sqlite3
import sys
from pathlib import Path
_dir = str(Path(__file__).resolve().parent)
if _dir not in sys.path:
    sys.path.insert(0, _dir)

from cp_prediction_core import DB_PATH, create_predictions


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--force', action='store_true', help='强制重生成下一期预测')
    args = parser.parse_args()
    conn = sqlite3.connect(DB_PATH)
    obj = create_predictions(conn, force=args.force)
    print(json.dumps(obj, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
