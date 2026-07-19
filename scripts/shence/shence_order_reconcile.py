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
def load_thresholds() -> tuple[int, int]:
    import json
    from pathlib import Path
    
    takeout_default = 300
    market_default = 300
    
    try:
        proj_root = Path(os.environ.get("TRAECLAW_PROJECT_ROOT") or Path(__file__).resolve().parents[3])
        db_file = Path(os.environ.get("TRAECLAW_DB_PATH") or (proj_root / "code" / "data" / "traeclaw.sqlite3"))
        
        if db_file.exists():
            from traeclaw.db import AppDatabase
            db = AppDatabase(db_file)
            db_config_content = db.get_setting("file:code/state/mfdb/order_monitor_config.json", "")
            if not db_config_content:
                db_config_content = db.get_setting("file:state/mfdb/order_monitor_config.json", "")
                
            if db_config_content:
                ext_config = json.loads(db_config_content)
                takeout = ext_config.get("takeout_threshold", takeout_default)
                market = ext_config.get("market_threshold", market_default)
                return int(takeout), int(market)
    except Exception:
        pass

    try:
        proj_root = Path(os.environ.get("TRAECLAW_PROJECT_ROOT") or Path(__file__).resolve().parents[3])
        config_paths = [
            proj_root / "code" / "state" / "mfdb" / "order_monitor_config.json",
            Path("state/mfdb/order_monitor_config.json"),
            Path("code/state/mfdb/order_monitor_config.json")
        ]
        for path in config_paths:
            if path.exists():
                with open(path, "r", encoding="utf-8") as f:
                    ext_config = json.load(f)
                    takeout = ext_config.get("takeout_threshold", takeout_default)
                    market = ext_config.get("market_threshold", market_default)
                    return int(takeout), int(market)
    except Exception:
        pass

    return takeout_default, market_default

TAKEOUT_THRESHOLD, MARKET_THRESHOLD = load_thresholds()
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
    from traeclaw.mfood.login import MFoodLogin
    from pathlib import Path
    
    proj_root = Path(os.environ.get("TRAECLAW_PROJECT_ROOT") or Path(__file__).resolve().parents[3])
    db_file = Path(os.environ.get("TRAECLAW_DB_PATH") or (proj_root / "data" / "traeclaw.sqlite3"))
    
    db = AppDatabase(db_file)
    login_handler = MFoodLogin(db, proj_root)
    return {"token": login_handler.get_valid_token()}


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


def format_count(value):
    if value is None:
        return "0"
    try:
        return f"{int(value):,}"
    except Exception:
        return str(value)


def format_money(value):
    if value is None:
        return "0"
    try:
        dec = Decimal(str(value))
        s = f"{dec:,.2f}"
        if s.endswith(".00"):
            s = s[:-3]
        elif s[-1] == "0" and "." in s:
            s = s[:-1]
        return s
    except Exception:
        return str(value)



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
        "SELECT "
        "count(1) AS cnt, "
        "sum(ifnull(cast(order_actual_amount AS DOUBLE), 0)) AS total_amount "
        "FROM events WHERE event = 'FinishedOrder' "
        f"AND time >= '{date_str} 00:00:00' AND time < '{next_date_str} 00:00:00';"
    )
    mall_sql = (
        "SELECT "
        "count(1) AS cnt, "
        "sum(ifnull(cast(order_actual_amount AS DOUBLE), 0)) AS total_amount "
        "FROM events WHERE event = 'MallFinishOrder' "
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

    finished_row, finished_retry = retry_call(lambda: shence_first_row(finished_sql), "shence_finished")
    shence_finished = int((finished_row.get("cnt") if isinstance(finished_row, dict) else finished_row[0]) or 0)
    shence_finished_amount = decimal_to_str(
        (finished_row.get("total_amount") if isinstance(finished_row, dict) else finished_row[1]) or 0
    )

    mall_row, mall_retry = retry_call(lambda: shence_first_row(mall_sql), "shence_mall")
    shence_mall = int((mall_row.get("cnt") if isinstance(mall_row, dict) else mall_row[0]) or 0)
    shence_mall_amount = decimal_to_str(
        (mall_row.get("total_amount") if isinstance(mall_row, dict) else mall_row[1]) or 0
    )
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
            "shence_amount": shence_finished_amount,
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
            "shence_amount": shence_mall_amount,
            "diff": diff_market,
            "alert": market_alert,
        },
        "message": (
            f"外賣-----\n"
            f"後臺訂單數：{format_count(api_takeouts)}\n"
            f"神策訂單數：{format_count(shence_finished)}\n"
            f"神策訂單總額：{format_money(shence_finished_amount)}\n"
            f"差值：{format_count(diff_takeouts)}\n\n"
            f"超市-----\n"
            f"後臺訂單數：{format_count(api_market)}\n"
            f"神策訂單數：{format_count(shence_mall)}\n"
            f"神策訂單總額：{format_money(shence_mall_amount)}\n"
            f"超市差值：{format_count(diff_market)}\n\n"
            f"星選-----\n"
            + (
                f"訂單總數：{format_count(star_order_count)}\n"
                f"訂單實付總額：{format_money(star_order_actual_amount)}"
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
