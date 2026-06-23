#!/usr/bin/env python3
import base64
import hashlib
import hmac
import json
import os
import sqlite3
import subprocess
import sys
import urllib.request
import urllib.error
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Asia/Shanghai")
WORKSPACE = "/home/eric/Documents/workspace"
STATE_DIR = f"{WORKSPACE}/state/mfdb"
DB_PATH = f"{STATE_DIR}/maskphone_monitor.db"
CONFIG_PATH = f"{STATE_DIR}/merchant_summary_check_config.json"
URL = "https://management-api.mfoodapp.com/merchants/summarys/summary/_list"
REVIEW_URL = "https://management-api.mfoodapp.com/merchants/takeouts/order/_list"
# TOKEN_CMD and TOKEN_WORKDIR are removed as we use traeclaw.mfood.login directly
REPORT_TITLE = "外卖对账"


def with_report_title(status: str, message: str) -> str:
    summary = "正常" if status == "ok" else "异常"
    title = f"{REPORT_TITLE} {summary}"
    return title if not message else f"{title}\n{message}"


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
        content = db.get_setting("file:state/mfdb/merchant_summary_check_config.json", "")
        if not content:
            content = db.get_setting("file:code/state/mfdb/merchant_summary_check_config.json", "")
        if content:
            return json.loads(content)
    except Exception as e:
        print(f"警告：從數據庫加載配置失敗：{e}", file=sys.stderr)

    return {}


def yesterday_str() -> str:
    return (datetime.now(TZ).date() - timedelta(days=1)).isoformat()


def get_login_token(profile: str = "") -> str:
    from traeclaw.db import AppDatabase
    from traeclaw.mfood.login import MFoodLogin
    from pathlib import Path
    
    proj_root = Path(os.environ.get("TRAECLAW_PROJECT_ROOT") or Path(__file__).resolve().parents[3])
    db_file = Path(os.environ.get("TRAECLAW_DB_PATH") or (proj_root / "data" / "traeclaw.sqlite3"))
    
    db = AppDatabase(db_file)
    login_handler = MFoodLogin(db, proj_root)
    return login_handler.get_valid_token()


def post_json(headers: dict, payload: dict, url: str = URL) -> dict:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))


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
    "status": "",
    "yearMonth": "",
    "fromMerchant": True,
    "storeIds": [],
    "pageNo": 1,
    "pageSize": 20
}


def build_headers(cfg: dict, x_merchant: str, x_token: str, store_id: str = None) -> dict:
    base = dict(DEFAULT_HEADERS)
    if cfg.get("headers"):
        base.update(cfg["headers"])
    timestamp = str(int(datetime.now(TZ).timestamp() * 1000))
    nonce = hashlib.md5((uuid.uuid4().hex + timestamp).encode("utf-8")).hexdigest()
    scope = to_text(base.get("x-scope") or "manager")
    client = to_text(base.get("x-client") or "web")
    client_version = to_text(base.get("x-client-version") or "2.0.0")
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
    base["x-ca-timestamp"] = timestamp
    base["x-ca-nonce"] = nonce
    base["x-ca-signature"] = signature
    base["x-merchant"] = x_merchant
    base["x-token"] = x_token
    base["x-platform"] = "rider"
    if store_id:
        base["x-store"] = store_id
        base["x-storeid"] = store_id
    return base


def payload_from_cfg(cfg: dict) -> dict:
    payload = dict(DEFAULT_PAYLOAD)
    if cfg.get("payload"):
        payload.update(cfg["payload"])
    payload["storeIds"] = []
    return payload



def to_text(v: Any) -> str:
    if v is None:
        return ""
    return str(v).strip()


def extract_context_fields(obj: dict, ctx: dict) -> dict:
    next_ctx = dict(ctx)
    merchant_keys = ["merchantId", "merchant_id", "merchantNo", "merchantCode"]
    store_id_keys = ["storeId", "store_id", "shopId", "shop_id"]
    store_name_keys = ["storeName", "store_name", "shopName", "shop_name", "name"]

    for key in merchant_keys:
        value = to_text(obj.get(key))
        if value:
            next_ctx["merchant_id"] = value
            break
    for key in store_id_keys:
        value = to_text(obj.get(key))
        if value:
            next_ctx["store_id"] = value
            break
    for key in store_name_keys:
        value = to_text(obj.get(key))
        if value and not (key == "name" and not next_ctx.get("store_id")):
            next_ctx["store_name"] = value
            break
    return next_ctx


def walk_for_stores(node: Any, ctx: Optional[dict] = None, out: Optional[List[dict]] = None) -> List[dict]:
    if out is None:
        out = []
    if ctx is None:
        ctx = {}

    if isinstance(node, dict):
        next_ctx = extract_context_fields(node, ctx)
        if next_ctx.get("merchant_id") and next_ctx.get("store_id") and next_ctx.get("store_name"):
            out.append({
                "merchant_id": next_ctx["merchant_id"],
                "store_id": next_ctx["store_id"],
                "store_name": next_ctx["store_name"],
            })
        for value in node.values():
            walk_for_stores(value, next_ctx, out)
    elif isinstance(node, list):
        for item in node:
            walk_for_stores(item, ctx, out)
    return out


def walk_for_details(node: Any, ctx: Optional[dict] = None, out: Optional[List[dict]] = None) -> List[dict]:
    if out is None:
        out = []
    if ctx is None:
        ctx = {}

    if isinstance(node, dict):
        next_ctx = extract_context_fields(node, ctx)
        details = node.get("details")
        if isinstance(details, list):
            for detail in details:
                if not isinstance(detail, dict):
                    continue
                out.append({
                    "merchant_id": to_text(next_ctx.get("merchant_id")),
                    "store_id": to_text(next_ctx.get("store_id")),
                    "store_name": to_text(next_ctx.get("store_name")),
                    "dateStr": to_text(detail.get("dateStr")),
                    "storeReceiveAmtn": detail.get("storeReceiveAmtn"),
                    "subsidyStoreReceiveAmtn": detail.get("subsidyStoreReceiveAmtn"),
                    "subsidyStoreReceiveAmtnNew": detail.get("subsidyStoreReceiveAmtnNew"),
                    "detail": detail,
                })
        for value in node.values():
            walk_for_details(value, next_ctx, out)
    elif isinstance(node, list):
        for item in node:
            walk_for_details(item, ctx, out)
    return out


def dedupe_store_rows(rows: List[dict]) -> List[dict]:
    seen = set()
    cleaned = []
    for row in rows:
        key = (row.get("merchant_id"), row.get("store_id"), row.get("store_name"))
        if not key[0] or not key[1] or not key[2] or key in seen:
            continue
        seen.add(key)
        cleaned.append(row)
    return cleaned


def ensure_db() -> sqlite3.Connection:
    os.makedirs(STATE_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS merchant_summary_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_ts TEXT NOT NULL,
            target_date TEXT NOT NULL,
            root_merchant_id TEXT,
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
        CREATE TABLE IF NOT EXISTS merchant_summary_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id INTEGER NOT NULL,
            merchant_id TEXT,
            store_id TEXT,
            store_name TEXT,
            date_str TEXT,
            date_key TEXT,
            store_receive_amtn TEXT,
            subsidy_store_receive_amtn TEXT,
            subsidy_store_receive_amtn_new TEXT,
            has_issue INTEGER NOT NULL DEFAULT 0,
            payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_merchant_summary_runs_ts ON merchant_summary_runs(run_ts)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_merchant_summary_records_run_id ON merchant_summary_records(run_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_merchant_summary_records_store_date ON merchant_summary_records(store_id, date_key)")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS take_out_stores (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            merchant_id TEXT NOT NULL,
            store_id TEXT NOT NULL,
            store_name TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            UNIQUE(merchant_id, store_id)
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_take_out_stores_merchant_id ON take_out_stores(merchant_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_take_out_stores_store_id ON take_out_stores(store_id)")
    conn.commit()
    return conn


def upsert_stores(conn: sqlite3.Connection, stores: List[dict]):
    for row in stores:
        conn.execute(
            """
            INSERT INTO take_out_stores (merchant_id, store_id, store_name)
            VALUES (?, ?, ?)
            ON CONFLICT(merchant_id, store_id) DO UPDATE SET
                store_name=excluded.store_name
            """,
            (row["merchant_id"], row["store_id"], row["store_name"]),
        )
    conn.commit()


def persist_run(conn: sqlite3.Connection, target_date: str, root_merchant_id: str, status: str, checked_store_count: int, issue_count: int, message: str, payload: dict, records: List[dict]):
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO merchant_summary_runs (
            run_ts, target_date, root_merchant_id, status,
            checked_store_count, issue_count, message, payload_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            datetime.now(TZ).isoformat(),
            target_date,
            root_merchant_id,
            status,
            checked_store_count,
            issue_count,
            message,
            json.dumps(payload, ensure_ascii=False),
        ),
    )
    run_id = cur.lastrowid
    for record in records:
        db_payload = record.get("detail") or {}
        if record.get("review_raw"):
            db_payload = {
                "detail_data": record.get("detail") or {},
                "review_orders": record.get("review_raw"),
            }
        cur.execute(
            """
            INSERT INTO merchant_summary_records (
                run_id, merchant_id, store_id, store_name, date_str, date_key,
                store_receive_amtn, subsidy_store_receive_amtn, subsidy_store_receive_amtn_new,
                has_issue, payload_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                record.get("merchant_id") or "",
                record.get("store_id") or "",
                record.get("store_name") or "",
                record.get("dateStr") or "",
                (record.get("dateStr") or "")[:10],
                to_text(record.get("storeReceiveAmtn")),
                to_text(record.get("subsidyStoreReceiveAmtn")),
                to_text(record.get("subsidyStoreReceiveAmtnNew")),
                1 if record.get("has_issue") else 0,
                json.dumps(db_payload, ensure_ascii=False),
            ),
        )
    conn.commit()


def is_zero(value: Any) -> bool:
    txt = to_text(value)
    if txt == "":
        return False
    try:
        return float(txt) == 0.0
    except Exception:
        return False


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
        "商户对账分析门店问题",
        f"门店id：{record.get('store_id') or ''}",
        f"门店名：{record.get('store_name') or ''}",
        f"日期：{record.get('dateStr') or ''}",
        f"storeReceiveAmtn: {to_text(record.get('storeReceiveAmtn'))}",
        f"subsidyStoreReceiveAmtn: {to_text(record.get('subsidyStoreReceiveAmtn'))}",
        f"subsidyStoreReceiveAmtnNew: {to_text(record.get('subsidyStoreReceiveAmtnNew'))}",
        f"提示：昨日营业额为 0，但复查发现有 {len(orders)} 笔有效订单：",
        *order_summaries
    ]
    return "\n".join(lines)


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


def main() -> int:
    cfg = load_config()
    target_date = yesterday_str()
    token_profile = to_text(cfg.get("token_profile") or "default")

    configured_ids = cfg.get("store_ids") or cfg.get("payload", {}).get("storeIds") or cfg.get("merchant_ids") or cfg.get("payload", {}).get("merchantIds")
    if isinstance(configured_ids, list):
        configured_ids = [to_text(s) for s in configured_ids if to_text(s)]
    else:
        configured_ids = []

    # Get root_merchant_id from configured merchant_ids, or fallback to default
    cfg_merchant_ids = cfg.get("merchant_ids") or cfg.get("payload", {}).get("merchantIds")
    if isinstance(cfg_merchant_ids, list):
        cfg_merchant_ids = [to_text(s) for s in cfg_merchant_ids if to_text(s)]
    else:
        cfg_merchant_ids = []

    if cfg_merchant_ids:
        root_merchant_id = cfg_merchant_ids[0]
    elif to_text(cfg.get("x-merchant") or cfg.get("merchant_id") or cfg.get("root_x_merchant")):
        root_merchant_id = to_text(cfg.get("x-merchant") or cfg.get("merchant_id") or cfg.get("root_x_merchant"))
    else:
        root_merchant_id = "202307141644140647101"

    configured_ids = [cid for cid in configured_ids if cid != root_merchant_id]

    conn = ensure_db()
    all_payload = {"target_date": target_date, "root_merchant_id": root_merchant_id, "token_profile": token_profile}
    try:
        login_token = get_login_token(token_profile)
    except Exception as exc:
        msg = f"需人工复核：获取 mFood 登录 token 失败，{exc}"
        persist_run(conn, target_date, root_merchant_id, "error", 0, 0, msg, {**all_payload, "error": str(exc)}, [])
        print(msg)
        conn.close()
        return 2
    try:
        try:
            root_resp = post_json(build_headers(cfg, root_merchant_id, login_token), payload_from_cfg(cfg))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            parsed = parse_http_error_detail(detail)
            msg = f"需人工复核：接口请求失败 HTTP {exc.code}" + (f"，{parsed}" if parsed else "")
            persist_run(conn, target_date, root_merchant_id, "error", 0, 0, msg, {**all_payload, "error": detail}, [])
            print(msg)
            return 2
        except Exception as exc:
            msg = f"需人工复核：接口请求失败 {exc}"
            persist_run(conn, target_date, root_merchant_id, "error", 0, 0, msg, {**all_payload, "error": str(exc)}, [])
            print(msg)
            return 2

        stores = dedupe_store_rows(walk_for_stores(root_resp))
        upsert_stores(conn, stores)

        if configured_ids:
            merchant_ids = sorted({
                row["merchant_id"]
                for row in stores
                if row.get("merchant_id") and (
                    to_text(row.get("store_id")) in configured_ids or
                    to_text(row.get("merchant_id")) in configured_ids
                )
            })
        else:
            merchant_ids = sorted({row["merchant_id"] for row in stores if row.get("merchant_id")})

        if not merchant_ids:
            merchant_ids = [root_merchant_id]

        detail_records: List[dict] = []
        merchant_errors: List[str] = []
        raw_responses = []
        for merchant_id in merchant_ids:
            try:
                resp = post_json(build_headers(cfg, merchant_id, login_token), payload_from_cfg(cfg))
                raw_responses.append({"merchant_id": merchant_id, "response": resp})
                detail_records.extend(walk_for_details(resp))
            except urllib.error.HTTPError as exc:
                merchant_errors.append(f"merchant {merchant_id}: http {exc.code}")
            except Exception as exc:
                merchant_errors.append(f"merchant {merchant_id}: {exc}")

        yesterday_records = []
        for record in detail_records:
            date_str = to_text(record.get("dateStr"))
            if date_str[:10] == target_date:
                store_id = to_text(record.get("store_id"))
                merchant_id = to_text(record.get("merchant_id"))
                if configured_ids and store_id not in configured_ids and merchant_id not in configured_ids:
                    continue
                record["has_issue"] = False
                if is_zero(record.get("subsidyStoreReceiveAmtn")):
                    try:
                        has_orders, review_resp = review_has_orders(cfg, record.get("merchant_id") or root_merchant_id, record.get("store_id") or "", login_token)
                        record["review_raw"] = review_resp
                        record["has_issue"] = has_orders
                    except urllib.error.HTTPError as exc:
                        detail = exc.read().decode("utf-8", errors="replace")
                        parsed = parse_http_error_detail(detail)
                        merchant_errors.append(f"review store {record.get('store_id')}: HTTP {exc.code}" + (f"，{parsed}" if parsed else ""))
                    except Exception as exc:
                        merchant_errors.append(f"review store {record.get('store_id')}: {exc}")
                yesterday_records.append(record)

        issues = [record for record in yesterday_records if record.get("has_issue")]

        if merchant_errors:
            status = "partial_error" if yesterday_records else "error"
            message = "需人工复核：" + "; ".join(merchant_errors[:5])
        elif not yesterday_records:
            status = "error"
            message = f"需人工复核：未找到昨日 {target_date} 数据"
        elif issues:
            status = "alert"
            message = "\n\n".join(render_issue(item) for item in issues)
        else:
            status = "ok"
            message = "数据正常"

        persist_run(
            conn,
            target_date,
            root_merchant_id,
            status,
            len(yesterday_records),
            len(issues),
            message,
            {**all_payload, "root_response": root_resp, "merchant_errors": merchant_errors, "merchant_count": len(merchant_ids), "store_count": len(stores), "responses": raw_responses[:20]},
            yesterday_records,
        )
        print(with_report_title(status, message))
        if status == "ok":
            print("数据正常")
        elif status == "alert":
            print(f"发现 {len(issues)} 家门店有对账数据异常，请人工核对")
        elif status == "partial_error":
            print("部分商户数据查询失败")
        else:
            print("查询失败，请检查错误日志")
        return 1 if status in {"alert", "partial_error", "error"} else 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
