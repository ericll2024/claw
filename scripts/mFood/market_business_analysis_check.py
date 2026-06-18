#!/usr/bin/env python3
import base64
import hashlib
import hmac
import json
import os
import sqlite3
import subprocess
import sys
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timedelta
from typing import Any, List
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Asia/Shanghai")
WORKSPACE = "/home/eric/Documents/workspace"
STATE_DIR = f"{WORKSPACE}/state/mfdb"
DB_PATH = f"{STATE_DIR}/maskphone_monitor.db"
CONFIG_PATH = f"{STATE_DIR}/market_business_analysis_check_config.json"
URL = "https://management-api.mfoodapp.com/merchants/market/report/business/_merchant-data"
REVIEW_URL = "https://management-api.mfoodapp.com/merchants/market/merchantOrder/report/_list"
# TOKEN_CMD and TOKEN_WORKDIR are removed as we use traeclaw.mfood.login directly
REPORT_TITLE = "超市经营数据"


def with_report_title(status: str, message: str) -> str:
    summary = "正常" if status == "ok" else "异常"
    title = f"{REPORT_TITLE} {summary}"
    return title if not message else f"{title}\n{message}"


def to_text(v: Any) -> str:
    if v is None:
        return ""
    return str(v).strip()


def load_config() -> dict:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def get_login_token(profile: str = "") -> str:
    from traeclaw.db import AppDatabase
    from traeclaw.mfood.login import MFoodLogin
    from pathlib import Path
    
    proj_root = Path(os.environ.get("TRAECLAW_PROJECT_ROOT") or Path(__file__).resolve().parents[3])
    db_file = Path(os.environ.get("TRAECLAW_DB_PATH") or (proj_root / "code" / "data" / "traeclaw.sqlite3"))
    
    db = AppDatabase(db_file)
    login = MFoodLogin(db, proj_root)
    res = login.get_token()
    token = to_text(res.get("token"))
    if not token:
        raise RuntimeError("mFood login returned empty token")
    return token


def build_headers(cfg: dict, x_merchant: str, x_token: str) -> dict:
    headers = dict(cfg.get("headers") or {})
    timestamp = str(int(datetime.now(TZ).timestamp() * 1000))
    nonce = hashlib.md5((uuid.uuid4().hex + timestamp).encode("utf-8")).hexdigest()
    scope = to_text(headers.get("x-scope") or "manager")
    client = to_text(headers.get("x-client") or "web")
    client_version = to_text(headers.get("x-client-version") or "2.0.0")
    ca_secret = to_text(cfg.get("ca_secret") or "5fde65edc94340458a4411d412bdc454")
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
    headers["x-ca-timestamp"] = timestamp
    headers["x-ca-nonce"] = nonce
    headers["x-ca-signature"] = signature
    headers["x-merchant"] = x_merchant
    headers["x-token"] = x_token
    return headers


def build_payload(cfg: dict, store_id: str) -> dict:
    payload = dict(cfg.get("payload") or {})
    payload["storeId"] = store_id
    return payload


def post_json(headers: dict, payload: dict, url: str = URL) -> dict:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=45) as resp:
        return json.loads(resp.read().decode("utf-8"))


def parse_http_error_detail(detail: str) -> str:
    try:
        data = json.loads(detail)
    except Exception:
        return ""
    note = to_text(data.get("note") or data.get("enNote"))
    code = to_text(data.get("code"))
    if note and code:
        return f"{note}（{code}）"
    return note or code


def ensure_db() -> sqlite3.Connection:
    os.makedirs(STATE_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS market_business_analysis_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_ts TEXT NOT NULL,
            status TEXT NOT NULL,
            checked_store_count INTEGER NOT NULL DEFAULT 0,
            issue_count INTEGER NOT NULL DEFAULT 0,
            message TEXT,
            payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS market_business_analysis_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id INTEGER NOT NULL,
            merchant_id TEXT,
            store_id TEXT,
            store_name TEXT,
            business_amtn TEXT,
            has_issue INTEGER NOT NULL DEFAULT 0,
            payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_market_business_analysis_runs_ts ON market_business_analysis_runs(run_ts)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_market_business_analysis_records_run_id ON market_business_analysis_records(run_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_market_business_analysis_records_store_id ON market_business_analysis_records(store_id)")
    conn.commit()
    return conn


def load_market_stores(conn: sqlite3.Connection) -> List[dict]:
    cur = conn.cursor()
    cur.execute("SELECT merchant_id, store_id, store_name FROM market_stores ORDER BY merchant_id, store_id")
    return [
        {"merchant_id": row[0], "store_id": row[1], "store_name": row[2]}
        for row in cur.fetchall()
    ]


def is_zero(value: Any) -> bool:
    txt = to_text(value)
    if txt == "":
        return False
    try:
        return float(txt) == 0.0
    except Exception:
        return False


def pick_business_amtn_items(resp: dict) -> List[Any]:
    result = resp.get("result") if isinstance(resp, dict) else None
    if isinstance(result, dict):
        items = result.get("businessDataList")
        if isinstance(items, list):
            return items
    items = resp.get("businessDataList") if isinstance(resp, dict) else None
    return items if isinstance(items, list) else []


def yesterday_range_ms() -> tuple[int, int]:
    start = datetime.now(TZ).date() - timedelta(days=1)
    start_dt = datetime(start.year, start.month, start.day, tzinfo=TZ)
    start_ms = int(start_dt.timestamp() * 1000)
    return start_ms, start_ms


def build_review_headers(cfg: dict, x_merchant: str, x_token: str, store_id: str) -> dict:
    headers = build_headers(cfg, x_merchant, x_token)
    headers["x-store"] = store_id
    headers["x-storeid"] = store_id
    return headers


def build_review_payload(store_id: str) -> dict:
    start_ms, end_ms = yesterday_range_ms()
    return {
        "tradeNo": "",
        "orderStatus": None,
        "isReserve": None,
        "deliveryType": None,
        "date": [start_ms, end_ms],
        "phone": None,
        "storeId": "",
        "timeType": 1,
        "orderNumber": None,
        "startTime": start_ms,
        "endTime": end_ms,
        "pageNo": 1,
        "pageSize": 20,
    }


def review_has_orders(cfg: dict, merchant_id: str, store_id: str, login_token: str) -> tuple[bool, dict]:
    resp = post_json(build_review_headers(cfg, merchant_id, login_token, store_id), build_review_payload(store_id), REVIEW_URL)
    result = resp.get("result") if isinstance(resp, dict) else None
    if isinstance(result, list):
        return len(result) > 0, resp
    if isinstance(result, dict):
        items = result.get("result") or result.get("list") or result.get("records")
        if isinstance(items, list):
            return len(items) > 0, resp
        total = result.get("total")
        try:
            return int(total or 0) > 0, resp
        except Exception:
            return False, resp
    total = resp.get("total") if isinstance(resp, dict) else None
    try:
        return int(total or 0) > 0, resp
    except Exception:
        return False, resp


def persist_run(conn: sqlite3.Connection, status: str, checked_store_count: int, issue_count: int, message: str, payload: dict, records: List[dict]):
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO market_business_analysis_runs (
            run_ts, status, checked_store_count, issue_count, message, payload_json
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            datetime.now(TZ).isoformat(),
            status,
            checked_store_count,
            issue_count,
            message,
            json.dumps(payload, ensure_ascii=False),
        ),
    )
    run_id = cur.lastrowid
    for record in records:
        cur.execute(
            """
            INSERT INTO market_business_analysis_records (
                run_id, merchant_id, store_id, store_name, business_amtn, has_issue, payload_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                record.get("merchant_id") or "",
                record.get("store_id") or "",
                record.get("store_name") or "",
                to_text(record.get("businessAmtn")),
                1 if record.get("has_issue") else 0,
                json.dumps(record.get("raw") or {}, ensure_ascii=False),
            ),
        )
    conn.commit()


def render_issue(record: dict) -> str:
    lines = [
        "超市经营分析门店问题",
        f"门店id：{record.get('store_id') or ''}",
        f"门店名：{record.get('store_name') or ''}",
        f"经营分析json：{json.dumps(record.get('raw') or {}, ensure_ascii=False)}",
    ]
    review_raw = record.get('review_raw')
    if review_raw:
        lines.append(f"複查订单json：{json.dumps(review_raw, ensure_ascii=False)}")
    return "\n".join(lines)


def main() -> int:
    cfg = load_config()
    token_profile = to_text(cfg.get("token_profile") or "default")
    conn = ensure_db()
    stores = load_market_stores(conn)
    if not stores:
        msg = "需人工复核：market_stores 暂无门店数据"
        persist_run(conn, "error", 0, 0, msg, {"token_profile": token_profile}, [])
        print(msg)
        conn.close()
        return 2

    try:
        login_token = get_login_token(token_profile)
    except Exception as exc:
        msg = f"需人工复核：获取 mFood 登录 token 失败，{exc}"
        persist_run(conn, "error", 0, 0, msg, {"token_profile": token_profile, "error": str(exc)}, [])
        print(msg)
        conn.close()
        return 2

    checked = []
    issues = []
    errors = []
    raw_payload = []
    try:
        for store in stores:
            merchant_id = store["merchant_id"]
            store_id = store["store_id"]
            store_name = store["store_name"]
            try:
                resp = post_json(build_headers(cfg, merchant_id, login_token), build_payload(cfg, store_id))
                raw_payload.append({"merchant_id": merchant_id, "store_id": store_id, "response": resp})
                items = pick_business_amtn_items(resp)
                if not items:
                    checked.append({**store, "businessAmtn": "", "has_issue": False, "raw": resp})
                    continue
                for item in items:
                    value = item.get("businessAmtn") if isinstance(item, dict) else None
                    rec = {**store, "businessAmtn": value, "has_issue": False, "raw": item if isinstance(item, dict) else {"value": item}}
                    if is_zero(value):
                        has_orders, review_resp = review_has_orders(cfg, merchant_id, store_id, login_token)
                        rec["review_raw"] = review_resp
                        rec["has_issue"] = has_orders
                    checked.append(rec)
                    if rec["has_issue"]:
                        issues.append(rec)
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", errors="replace")
                parsed = parse_http_error_detail(detail)
                errors.append(f"store {store_id}: HTTP {exc.code}" + (f"，{parsed}" if parsed else ""))
            except Exception as exc:
                errors.append(f"store {store_id}: {exc}")

        if errors:
            status = "partial_error" if checked else "error"
            message = "需人工复核：" + "; ".join(errors[:5])
        elif issues:
            status = "alert"
            message = "\n\n".join(render_issue(item) for item in issues)
        else:
            status = "ok"
            message = "数据正常"

        persist_run(conn, status, len(checked), len(issues), message, {"token_profile": token_profile, "store_count": len(stores), "errors": errors, "responses": raw_payload[:20]}, checked)
        print(with_report_title(status, message))
        return 1 if status in {"alert", "partial_error", "error"} else 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
