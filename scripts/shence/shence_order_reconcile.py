#!/usr/bin/env python3
import argparse
import json
import os
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Asia/Shanghai")
WORKSPACE = "/home/eric/Documents/workspace"
# MFOOD_API_DIR, MFOOD_LOGIN_DIR, and MFOOD_SHENCE_DIR are removed as we use traeclaw packages directly
STATE_DIR = f"{WORKSPACE}/state/scjk"
DB_PATH = f"{STATE_DIR}/shence_monitor.db"
TAKEOUT_THRESHOLD = 200
MARKET_THRESHOLD = 60
MAX_RETRIES = 3
RETRY_DELAY_SECONDS = 2


def sh(cmd, cwd=None, env=None, timeout=240):
    res = subprocess.run(cmd, cwd=cwd, env=env, text=True, capture_output=True, timeout=timeout)
    if res.returncode != 0:
        raise RuntimeError(res.stderr.strip() or res.stdout.strip() or f"command failed: {' '.join(cmd)}")
    return res.stdout.strip()


def retry_call(fn, label, max_retries=MAX_RETRIES, delay=RETRY_DELAY_SECONDS):
    last_error = None
    for attempt in range(1, max_retries + 1):
        try:
            value = fn()
            return value, {"attempt": attempt, "max": max_retries, "ok": True, "label": label}
        except Exception as e:
            last_error = str(e)
            if attempt < max_retries:
                time.sleep(delay)
    raise RuntimeError(f"{label} failed after {max_retries} attempts: {last_error}")


def day_range(date_str=None):
    if date_str:
        target = datetime.strptime(date_str, "%Y-%m-%d").date()
    else:
        now = datetime.now(TZ)
        target = (now - timedelta(days=1)).date()
    start = datetime(target.year, target.month, target.day, 0, 0, 0, tzinfo=TZ)
    end = datetime(target.year, target.month, target.day, 23, 59, 59, tzinfo=TZ)
    return target.isoformat(), int(start.timestamp() * 1000), int(end.timestamp() * 1000)


def parse_args():
    parser = argparse.ArgumentParser(description="神策外賣/超市對賬巡檢")
    parser.add_argument("--date", help="查詢日期，格式 YYYY-MM-DD；不傳則默認查昨天")
    return parser.parse_args()


def get_token():
    from traeclaw.db import AppDatabase
    from pathlib import Path
    
    proj_root = Path(os.environ.get("TRAECLAW_PROJECT_ROOT") or Path(__file__).resolve().parents[3])
    db_file = Path(os.environ.get("TRAECLAW_DB_PATH") or (proj_root / "data" / "traeclaw.sqlite3"))
    
    db = AppDatabase(db_file)
    token = db.get_setting("mfood.login.token", "").strip()
    if not token:
        raise RuntimeError("mFood token not configured or empty in database")
    return {"token": token}


def shence_first_row(sql):
    from traeclaw.db import AppDatabase
    from traeclaw.mfood.shence import MFoodShence
    from pathlib import Path
    
    proj_root = Path(os.environ.get("TRAECLAW_PROJECT_ROOT") or Path(__file__).resolve().parents[3])
    db_file = Path(os.environ.get("TRAECLAW_DB_PATH") or (proj_root / "data" / "traeclaw.sqlite3"))
    
    db = AppDatabase(db_file)
    shence = MFoodShence(db)
    res = shence.query(sql, limit=10)
    rows = res.get("rows") or []
    if not rows:
        raise RuntimeError("empty shence query result")
    return rows[0]


def shence_count(sql):
    row = shence_first_row(sql)
    if isinstance(row, dict):
        for key in ("total", "count", "cnt", "event_count", "value"):
            if key in row:
                return int(row[key] or 0)
        return int(next(iter(row.values())) or 0)
    return int(row[0] or 0)


def decimal_to_str(value):
    if value is None:
        return "0"
    try:
        dec = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return str(value)
    normalized = dec.normalize()
    rendered = format(normalized, "f")
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    return rendered or "0"


def api_count(token, resource, date_str, status):
    import hashlib
    import hmac
    import base64
    import uuid
    import urllib.request
    import json
    
    target = datetime.strptime(date_str, "%Y-%m-%d")
    start_dt = datetime(target.year, target.month, target.day, 0, 0, 0, tzinfo=TZ)
    end_dt = datetime(target.year, target.month, target.day, 23, 59, 59, tzinfo=TZ)
    start_ms = int(start_dt.timestamp() * 1000)
    end_ms = int(end_dt.timestamp() * 1000)
    
    if resource == "takeouts":
        url = "https://management-api.mfoodapp.com/managers/takeouts/order/_list"
        payload = {
            "dateType": 2,
            "startDate": start_ms,
            "endDate": end_ms,
            "status": int(status),
            "pageNo": 1,
            "pageSize": 1,
        }
    elif resource == "market":
        url = "https://management-api.mfoodapp.com/managers/market/order/_list"
        payload = {
            "dateType": 2,
            "startDate": start_ms,
            "endDate": end_ms,
            "status": int(status),
            "pageNo": 1,
            "pageSize": 1,
        }
    else:
        raise ValueError(f"Unknown resource: {resource}")
        
    timestamp = str(int(datetime.now(TZ).timestamp() * 1000))
    nonce = hashlib.md5((uuid.uuid4().hex + timestamp).encode("utf-8")).hexdigest()
    scope = "manager"
    client = "web"
    client_version = "2.0.0"
    ca_secret = "5fde65edc94340458a4411d412bdc454"
    
    canonical = (
        "POST\n"
        f"x-ca-timestamp:{timestamp}\n"
        f"x-ca-nonce:{nonce}\n"
        f"x-scope:{scope}\n"
        f"x-client:{client}\n"
        f"x-client-version:{client_version}\n"
    )
    signature = base64.b64encode(
        hmac.new(ca_secret.encode("utf-8"), canonical.encode("utf-8"), hashlib.sha256).digest()
    ).decode("utf-8")
    
    headers = {
        "Content-Type": "application/json",
        "x-ca-timestamp": timestamp,
        "x-ca-nonce": nonce,
        "x-ca-signature": signature,
        "x-scope": scope,
        "x-client": client,
        "x-client-version": client_version,
        "x-token": token,
        "x-platform": "rider",
        "x-user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36",
    }
    
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=45) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body_err = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"mFood API query failed with HTTP {exc.code}: {body_err}") from exc
        
    for key in ("total", "count", "totalCount"):
        if key in data:
            return int(data[key] or 0)
    if isinstance(data.get("data"), dict):
        for key in ("total", "count", "totalCount"):
            if key in data["data"]:
                return int(data["data"][key] or 0)
    if isinstance(data.get("result"), dict):
        for key in ("total", "count", "totalCount"):
            if key in data["result"]:
                return int(data["result"][key] or 0)
    raise RuntimeError(f"Cannot parse api count from response: {data}")


def ensure_db():
    os.makedirs(STATE_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS reconcile_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            check_date TEXT NOT NULL,
            run_ts TEXT NOT NULL,
            status TEXT NOT NULL,
            takeout_api_count INTEGER,
            takeout_shence_count INTEGER,
            takeout_diff INTEGER,
            takeout_alert INTEGER,
            market_api_count INTEGER,
            market_shence_count INTEGER,
            market_diff INTEGER,
            market_alert INTEGER,
            message TEXT,
            payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_reconcile_runs_check_date ON reconcile_runs(check_date, run_ts)"
    )
    conn.commit()
    return conn


def persist_result(payload):
    conn = ensure_db()
    try:
        now = datetime.now(TZ).isoformat()
        takeouts = payload.get("takeouts") or {}
        market = payload.get("market") or {}
        conn.execute(
            """
            INSERT INTO reconcile_runs (
                check_date, run_ts, status,
                takeout_api_count, takeout_shence_count, takeout_diff, takeout_alert,
                market_api_count, market_shence_count, market_diff, market_alert,
                message, payload_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(payload.get("date") or ""),
                now,
                str(payload.get("status") or "error"),
                takeouts.get("api_count"),
                takeouts.get("shence_count"),
                takeouts.get("diff"),
                1 if takeouts.get("alert") else 0 if "alert" in takeouts else None,
                market.get("api_count"),
                market.get("shence_count"),
                market.get("diff"),
                1 if market.get("alert") else 0 if "alert" in market else None,
                str(payload.get("message") or ""),
                json.dumps(payload, ensure_ascii=False),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def main():
    args = parse_args()
    date_str, start_ms, end_ms = day_range(args.date)
    next_date_str = (datetime.fromisoformat(date_str) + timedelta(days=1)).date().isoformat()
    token_payload, token_retry = retry_call(get_token, "token")
    token = token_payload["token"]

    finished_sql = (
        f"SELECT count(1) AS value FROM events WHERE event = 'FinishedOrder' "
        f"AND time >= '{date_str} 00:00:00' AND time < '{next_date_str} 00:00:00';"
    )
    mall_sql = (
        f"SELECT count(1) AS value FROM events WHERE event = 'MallFinishOrder' "
        f"AND time >= '{date_str} 00:00:00' AND time < '{next_date_str} 00:00:00';"
    )
    takeout_star_sql = (
        "SELECT "
        "count(1) AS cccount, "
        "sum(ifnull(cast(order_actual_amount AS DOUBLE), 0)) AS star_order_actual_amount "
        "FROM events WHERE event = 'FinishedOrder' "
        "AND activity_name = '星選' "
        f"AND time >= '{date_str} 00:00:00' AND time < '{next_date_str} 00:00:00';"
    )

    shence_finished, finished_retry = retry_call(lambda: shence_count(finished_sql), "shence_finished")
    shence_mall, mall_retry = retry_call(lambda: shence_count(mall_sql), "shence_mall")
    try:
        star_row, star_retry = retry_call(lambda: shence_first_row(takeout_star_sql), "shence_takeout_star")
        star_order_count = int((star_row.get("cccount") if isinstance(star_row, dict) else star_row[0]) or 0)
        star_order_actual_amount = decimal_to_str(
            (star_row.get("star_order_actual_amount") if isinstance(star_row, dict) else star_row[1]) or 0
        )
        star_query_error = None
    except Exception as e:
        star_retry = {"attempt": MAX_RETRIES, "max": MAX_RETRIES, "ok": False, "label": "shence_takeout_star", "error": str(e)}
        star_order_count = None
        star_order_actual_amount = None
        star_query_error = str(e)
    api_takeouts, takeout_retry = retry_call(lambda: api_count(token, "takeouts", date_str, 4), "api_takeouts")
    api_market, market_retry = retry_call(lambda: api_count(token, "market", date_str, 6), "api_market")

    diff_takeouts = api_takeouts - shence_finished
    diff_market = api_market - shence_mall
    takeout_alert = diff_takeouts > TAKEOUT_THRESHOLD
    market_alert = diff_market > MARKET_THRESHOLD
    status = "alert" if (takeout_alert or market_alert) else "ok"

    result = {
        "status": status,
        "date": date_str,
        "thresholds": {"takeouts": TAKEOUT_THRESHOLD, "market": MARKET_THRESHOLD},
        "retries": {
            "token": token_retry,
            "shence_finished": finished_retry,
            "shence_mall": mall_retry,
            "shence_takeout_star": star_retry,
            "api_takeouts": takeout_retry,
            "api_market": market_retry,
        },
        "takeouts": {
            "api_count": api_takeouts,
            "shence_count": shence_finished,
            "diff": diff_takeouts,
            "alert": takeout_alert,
            "star_selected": {
                "activity_name": "星選",
                "order_count": star_order_count,
                "order_actual_amount_sum": star_order_actual_amount,
                "error": star_query_error,
            },
        },
        "market": {
            "api_count": api_market,
            "shence_count": shence_mall,
            "diff": diff_market,
            "alert": market_alert,
        },
        "message": (
            (
                f"异常: 外卖差值={diff_takeouts}，超市差值={diff_market}"
                if status == "alert"
                else f"正常: 外卖差值={diff_takeouts}，超市差值={diff_market}"
            )
            + "\n"
            + (
                f"星選訂單總數：{star_order_count}\n星選訂單實付總額：{star_order_actual_amount}"
                if star_query_error is None
                else f"星選訂單統計：查詢失敗（{star_query_error}）"
            )
        ),
    }
    persist_result(result)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        payload = {"status": "error", "message": str(e)}
        try:
            persist_result(payload)
        except Exception:
            pass
        print(json.dumps(payload, ensure_ascii=False))
        sys.exit(2)
