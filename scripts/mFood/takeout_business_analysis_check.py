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
CONFIG_PATH = f"{STATE_DIR}/takeout_business_analysis_check_config.json"
URL = "https://management-api.mfoodapp.com/merchants/takeouts/analysis/store/order/_business_data"
REVIEW_URL = "https://management-api.mfoodapp.com/merchants/takeouts/order/_list"
# TOKEN_CMD and TOKEN_WORKDIR are removed as we use traeclaw.mfood.login directly
REPORT_TITLE = "外卖经营数据"


def with_report_title(status: str, message: str) -> str:
    summary = "正常" if status == "ok" else "异常"
    title = f"{REPORT_TITLE} {summary}"
    return title if not message else f"{title}\n{message}"


def to_text(v: Any) -> str:
    if v is None:
        return ""
    return str(v).strip()


def load_config() -> dict:
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"警告：讀取本地配置失敗：{e}", file=sys.stderr)

    # Fallback to database setting
    try:
        from traeclaw.db import AppDatabase
        from pathlib import Path
        proj_root = Path(os.environ.get("TRAECLAW_PROJECT_ROOT") or Path(__file__).resolve().parents[3])
        db_file = Path(os.environ.get("TRAECLAW_DB_PATH") or (proj_root / "code" / "data" / "traeclaw.sqlite3"))
        db = AppDatabase(db_file)
        content = db.get_setting("file:state/mfdb/takeout_business_analysis_check_config.json", "")
        if not content:
            content = db.get_setting("file:code/state/mfdb/takeout_business_analysis_check_config.json", "")
        if content:
            return json.loads(content)
    except Exception as e:
        print(f"警告：從數據庫加載配置失敗：{e}", file=sys.stderr)

    return {}


def get_login_token(profile: str = "") -> str:
    from traeclaw.db import AppDatabase
    from traeclaw.mfood.login import MFoodLogin
    from pathlib import Path
    
    proj_root = Path(os.environ.get("TRAECLAW_PROJECT_ROOT") or Path(__file__).resolve().parents[3])
    db_file = Path(os.environ.get("TRAECLAW_DB_PATH") or (proj_root / "data" / "traeclaw.sqlite3"))
    
    db = AppDatabase(db_file)
    login_handler = MFoodLogin(db, proj_root)
    return login_handler.get_valid_token()


DEFAULT_HEADERS = {
    "accept": "application/json",
    "accept-language": "zh-CN,zh;q=0.9",
    "content-type": "application/json;charset=UTF-8",
    "origin": "https://merchant.mfoodapp.com",
    "priority": "u=1, i",
    "referer": "https://merchant.mfoodapp.com/",
    "sec-ch-ua": '"Google Chrome";v="149", "Chromium";v="149", "Not)A;Brand";v="24"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"macOS"',
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-site",
    "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36",
    "x-ca-key": "83579288",
    "x-device-id": "7892dbca-2fa9-4d04-bf6f-13d7deb04d29",
    "x-scope": "manager",
    "x-client": "web",
    "x-client-version": "2.0.0",
}

DEFAULT_PAYLOAD = {
    "startTime": "",
    "endTime": "",
    "cycle": 1,
    "storeId": None,
    "fromMerchant": True,
}


def build_headers(cfg: dict, x_merchant: str, x_token: str, store_id: str = None) -> dict:
    headers = dict(DEFAULT_HEADERS)
    if cfg.get("headers"):
        headers.update(cfg["headers"])
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
    headers["x-platform"] = "rider"
    if store_id:
        headers["x-store"] = store_id
        headers["x-storeid"] = store_id
    return headers


def build_payload(cfg: dict, store_id: str) -> dict:
    payload = dict(DEFAULT_PAYLOAD)
    if cfg.get("payload"):
        payload.update(cfg["payload"])
    payload["storeId"] = store_id
    return payload



def _post_json_raw(headers: dict, payload: dict, url: str = URL) -> dict:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))


def post_json(headers: dict, payload: dict, url: str = URL) -> dict:
    import time
    retries = 2
    delay = 2.0
    for attempt in range(retries + 1):
        try:
            return _post_json_raw(headers, payload, url)
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError) as exc:
            is_http_error = isinstance(exc, urllib.error.HTTPError)
            if is_http_error and exc.code < 500:
                raise
            if attempt == retries:
                raise
            time.sleep(delay * (attempt + 1))


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
        CREATE TABLE IF NOT EXISTS takeout_business_analysis_runs (
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
        CREATE TABLE IF NOT EXISTS takeout_business_analysis_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id INTEGER NOT NULL,
            merchant_id TEXT,
            store_id TEXT,
            store_name TEXT,
            total_business_amtn TEXT,
            total_receive_amtn TEXT,
            has_issue INTEGER NOT NULL DEFAULT 0,
            payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_takeout_business_analysis_runs_ts ON takeout_business_analysis_runs(run_ts)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_takeout_business_analysis_records_run_id ON takeout_business_analysis_records(run_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_takeout_business_analysis_records_store_id ON takeout_business_analysis_records(store_id)")
    conn.commit()
    return conn


def load_takeout_stores(cfg: dict, conn: sqlite3.Connection) -> List[dict]:
    if "stores" in cfg and isinstance(cfg["stores"], list) and cfg["stores"]:
        return cfg["stores"]
    cfg_merchant_ids = cfg.get("merchant_ids") or cfg.get("merchantIds")
    if isinstance(cfg_merchant_ids, list):
        cfg_merchant_ids = [to_text(m) for m in cfg_merchant_ids if to_text(m)]
    else:
        cfg_merchant_ids = []
    cur = conn.cursor()
    if cfg_merchant_ids:
        placeholders = ",".join("?" for _ in cfg_merchant_ids)
        cur.execute(f"SELECT merchant_id, store_id, store_name FROM take_out_stores WHERE merchant_id IN ({placeholders}) ORDER BY merchant_id, store_id", cfg_merchant_ids)
    else:
        cur.execute("SELECT merchant_id, store_id, store_name FROM take_out_stores ORDER BY merchant_id, store_id")
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


def pick_metrics(resp: dict) -> tuple[Any, Any, dict]:
    result = resp.get("result") if isinstance(resp, dict) else None
    if isinstance(result, dict):
        business = result.get("totalBusinessAmtn")
        receive = result.get("totalReceiveAmtn")
        return business, receive, result
    return resp.get("totalBusinessAmtn"), resp.get("totalReceiveAmtn"), resp if isinstance(resp, dict) else {}


def yesterday_window_ms() -> tuple[int, int]:
    day = datetime.now(TZ).date() - timedelta(days=1)
    start_dt = datetime(day.year, day.month, day.day, tzinfo=TZ)
    end_dt = start_dt + timedelta(days=1) - timedelta(seconds=1)
    return int(start_dt.timestamp() * 1000), int(end_dt.timestamp() * 1000)


def build_review_headers(cfg: dict, x_merchant: str, x_token: str, store_id: str) -> dict:
    headers = build_headers(cfg, x_merchant, x_token, store_id)
    return headers


def build_review_payload(store_id: str) -> dict:
    start_ms, end_ms = yesterday_window_ms()
    return {
        "endTime": end_ms,
        "status": 4,
        "startTime": start_ms,
        "refundType": None,
        "isReserve": None,
        "dateType": 1,
        "deliveryType": None,
        "orderNumber": None,
        "tradeNo": None,
        "fromMerchant": False,
        "id": store_id,
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
        INSERT INTO takeout_business_analysis_runs (
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
        db_payload = record.get("raw") or {}
        if record.get("review_raw"):
            db_payload = {
                "business_data": record.get("raw") or {},
                "review_orders": record.get("review_raw"),
            }
        cur.execute(
            """
            INSERT INTO takeout_business_analysis_records (
                run_id, merchant_id, store_id, store_name, total_business_amtn, total_receive_amtn, has_issue, payload_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                record.get("merchant_id") or "",
                record.get("store_id") or "",
                record.get("store_name") or "",
                to_text(record.get("totalBusinessAmtn")),
                to_text(record.get("totalReceiveAmtn")),
                1 if record.get("has_issue") else 0,
                json.dumps(db_payload, ensure_ascii=False),
            ),
        )
    conn.commit()


def render_issue(record: dict) -> str:
    review_raw = record.get("review_raw") or {}
    orders = []
    if isinstance(review_raw, dict):
        orders = review_raw.get("result") or review_raw.get("list") or review_raw.get("records") or []
        if not isinstance(orders, list):
            orders = []
    elif isinstance(review_raw, list):
        orders = review_raw
    
    order_summaries = []
    for order in orders[:5]:
        order_id = order.get("id") or order.get("tradeNo") or "未知"
        amount = order.get("realPayAmt") or order.get("orderAmountAmt") or 0
        pay_time = ""
        if order.get("payTime"):
            try:
                pay_time = " " + datetime.fromtimestamp(order.get("payTime") / 1000, TZ).strftime("%H:%M:%S")
            except Exception:
                pass
        order_summaries.append(f"  - 订单号: {order_id}, 实付金额: {amount}{pay_time}")
    
    if len(orders) > 5:
        order_summaries.append(f"  - ... 还有 {len(orders) - 5} 笔订单")
        
    lines = [
        "外卖经营分析门店问题",
        f"门店id：{record.get('store_id') or ''}",
        f"门店名：{record.get('store_name') or ''}",
        f"营业额：{to_text(record.get('totalBusinessAmtn'))}",
        f"实收金额：{to_text(record.get('totalReceiveAmtn'))}",
        f"提示：昨日营业额为 0，但复查发现有 {len(orders)} 笔有效订单：",
        *order_summaries
    ]
    return "\n".join(lines)


def main() -> int:
    cfg = load_config()
    token_profile = to_text(cfg.get("token_profile") or "default")
    conn = ensure_db()
    stores = load_takeout_stores(cfg, conn)
    if not stores:
        msg = "需人工复核：take_out_stores 暂无门店数据"
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

    cfg_merchant_ids = cfg.get("merchant_ids") or cfg.get("merchantIds") or []
    if not isinstance(cfg_merchant_ids, list):
        cfg_merchant_ids = [cfg_merchant_ids]
    cfg_merchant_ids = [to_text(m) for m in cfg_merchant_ids if to_text(m)]
    fallback_merchant_id = cfg_merchant_ids[0] if cfg_merchant_ids else ""
    checked = []
    issues = []
    errors = []
    raw_payload = []

    def process_store(store):
        merchant_id = store.get("merchant_id") or store.get("merchantNo") or fallback_merchant_id
        store_id = store["store_id"]
        store_checked = []
        store_issues = []
        store_error = None
        store_raw_payload = None
        try:
            resp = post_json(build_headers(cfg, merchant_id, login_token, store_id), build_payload(cfg, store_id))
            store_raw_payload = {"merchant_id": merchant_id, "store_id": store_id, "response": resp}
            total_business_amtn, total_receive_amtn, raw = pick_metrics(resp)
            rec = {
                **store,
                "totalBusinessAmtn": total_business_amtn,
                "totalReceiveAmtn": total_receive_amtn,
                "has_issue": False,
                "raw": raw,
            }
            if is_zero(total_business_amtn):
                has_orders, review_resp = review_has_orders(cfg, merchant_id, store_id, login_token)
                rec["review_raw"] = review_resp
                rec["has_issue"] = has_orders
            store_checked.append(rec)
            if rec["has_issue"]:
                store_issues.append(rec)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            parsed = parse_http_error_detail(detail)
            store_error = f"store {store_id}: HTTP {exc.code}" + (f"，{parsed}" if parsed else "")
        except Exception as exc:
            store_error = f"store {store_id}: {exc}"
            
        return store_checked, store_issues, store_error, store_raw_payload

    from concurrent.futures import ThreadPoolExecutor
    try:
        with ThreadPoolExecutor(max_workers=10) as executor:
            results = list(executor.map(process_store, stores))
            
        for store_checked, store_issues, store_error, store_raw_payload in results:
            checked.extend(store_checked)
            issues.extend(store_issues)
            if store_error:
                errors.append(store_error)
            if store_raw_payload:
                raw_payload.append(store_raw_payload)

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
        if status == "ok":
            print("数据正常")
        elif status == "alert":
            print(f"发现 {len(issues)} 家门店有营业数据异常，请人工核对")
        elif status == "partial_error":
            print("部分门店数据查询失败")
        else:
            print("查询失败，请检查错误日志")
        return 1 if status in {"alert", "partial_error", "error"} else 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
