#!/usr/bin/env python3
import json
import os
import sqlite3
import subprocess
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Asia/Shanghai")
WORKSPACE = "/home/eric/Documents/workspace"
STATE_DIR = f"{WORKSPACE}/state/mfdb"
DB_PATH = f"{STATE_DIR}/maskphone_monitor.db"
CONFIG_PATH = f"{STATE_DIR}/maskphone_monitor_config.json"
URL = "https://management-api.mfoodapp.com/managers/orgs/maskPhone/_topCount"
DEFAULT_HEADERS = {
    "accept": "application/json",
    "accept-language": "zh",
    "content-type": "application/json;charset=UTF-8",
    "origin": "https://manager.mfoodapp.com",
    "referer": "https://manager.mfoodapp.com/",
    "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36",
    "x-app-code-name": "Mozilla",
    "x-app-name": "Netscape",
    "x-app-version": "5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36",
    "x-browser-language": "zh",
    "x-ca-key": "83579288",
    "x-client": "web",
    "x-client-version": "2.0.0",
    "x-platform": "rider",
    "x-scope": "manager",
    "x-user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36",
}
PAYLOAD = {
    "orderId": None,
    "appSource": None,
    "pageNo": 1,
    "pageSize": 20,
}
# TOKEN_CMD and TOKEN_WORKDIR are removed as we use traeclaw.mfood.login directly


def env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def get_token() -> str:
    from traeclaw.db import AppDatabase
    from pathlib import Path
    
    proj_root = Path(os.environ.get("TRAECLAW_PROJECT_ROOT") or Path(__file__).resolve().parents[3])
    db_file = Path(os.environ.get("TRAECLAW_DB_PATH") or (proj_root / "data" / "traeclaw.sqlite3"))
    
    db = AppDatabase(db_file)
    # 直接从数据库的 settings 表中读取键值为 "mfood.login.token" 的全局设定
    token = db.get_setting("mfood.login.token", "").strip()
    if not token:
        raise RuntimeError("token fetch failed: empty token in database")
    return token


def build_headers() -> dict:
    headers = dict(DEFAULT_HEADERS)
    optional_headers = {
        "x-token": get_token(),
        "x-ca-nonce": env("MFOOD_MASKPHONE_CA_NONCE"),
        "x-ca-signature": env("MFOOD_MASKPHONE_CA_SIGNATURE"),
        "x-ca-timestamp": env("MFOOD_MASKPHONE_CA_TIMESTAMP") or str(int(time.time() * 1000)),
        "x-city-id": env("MFOOD_MASKPHONE_CITY_ID"),
        "x-city-name": env("MFOOD_MASKPHONE_CITY_NAME"),
        "x-ip": env("MFOOD_MASKPHONE_IP"),
        "priority": env("MFOOD_MASKPHONE_PRIORITY", "u=1, i"),
        "sec-ch-ua": env("MFOOD_MASKPHONE_SEC_CH_UA", '"Google Chrome";v="147", "Not.A/Brand";v="8", "Chromium";v="147"'),
        "sec-ch-ua-mobile": env("MFOOD_MASKPHONE_SEC_CH_UA_MOBILE", "?0"),
        "sec-ch-ua-platform": env("MFOOD_MASKPHONE_SEC_CH_UA_PLATFORM", '"macOS"'),
        "sec-fetch-dest": env("MFOOD_MASKPHONE_SEC_FETCH_DEST", "empty"),
        "sec-fetch-mode": env("MFOOD_MASKPHONE_SEC_FETCH_MODE", "cors"),
        "sec-fetch-site": env("MFOOD_MASKPHONE_SEC_FETCH_SITE", "same-site"),
    }
    for key, value in optional_headers.items():
        if value:
            headers[key] = value
    return headers


def fetch() -> dict:
    body = json.dumps(PAYLOAD).encode("utf-8")
    request = urllib.request.Request(URL, data=body, headers=build_headers(), method="POST")
    with urllib.request.urlopen(request, timeout=30) as response:
        raw = response.read().decode("utf-8")
        return json.loads(raw)


def fetch_with_retry(max_attempts: int = 3, delay_seconds: int = 2) -> dict:
    last_error = None
    for attempt in range(1, max_attempts + 1):
        try:
            data = fetch()
            data["retryAttempt"] = attempt
            data["maxAttempts"] = max_attempts
            return data
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            last_error = {"status": "error", "type": "http", "code": exc.code, "detail": detail, "retryAttempt": attempt, "maxAttempts": max_attempts}
        except Exception as exc:
            last_error = {"status": "error", "type": "runtime", "detail": str(exc), "retryAttempt": attempt, "maxAttempts": max_attempts}

        if attempt < max_attempts:
            time.sleep(delay_seconds)

    return last_error


def ensure_db():
    os.makedirs(STATE_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS maskphone_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_ts TEXT NOT NULL,
            status TEXT NOT NULL,
            monitor TEXT,
            agent TEXT,
            all_count INTEGER,
            using_count INTEGER,
            will_release_count INTEGER,
            other_using_count INTEGER,
            focus_used_count INTEGER,
            occupied_count INTEGER,
            threshold REAL,
            retry_attempt INTEGER,
            max_attempts INTEGER,
            message TEXT,
            payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_maskphone_runs_run_ts ON maskphone_runs(run_ts)")
    conn.commit()
    return conn


def persist_result(payload: dict):
    conn = ensure_db()
    try:
        conn.execute(
            """
            INSERT INTO maskphone_runs (
                run_ts, status, monitor, agent,
                all_count, using_count, will_release_count, other_using_count,
                focus_used_count, occupied_count, threshold,
                retry_attempt, max_attempts, message, payload_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                datetime.now(TZ).isoformat(),
                str(payload.get("status") or "error"),
                str(payload.get("monitor") or ""),
                str(payload.get("agent") or ""),
                payload.get("allCount"),
                payload.get("usingCount"),
                payload.get("willReleaseCount"),
                payload.get("otherUsingCount"),
                payload.get("focusUsedCount"),
                payload.get("occupiedCount"),
                payload.get("threshold"),
                payload.get("retryAttempt") or (payload.get("raw") or {}).get("retryAttempt"),
                payload.get("maxAttempts") or (payload.get("raw") or {}).get("maxAttempts"),
                str(payload.get("message") or payload.get("detail") or ""),
                json.dumps(payload, ensure_ascii=False),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def main() -> int:
    data = fetch_with_retry()
    if data.get("status") == "error":
        persist_result(data)
        print(json.dumps(data, ensure_ascii=False))
        return 2

    all_count = int(data.get("allCount", 0) or 0)
    using_count = int(data.get("usingCount", 0) or 0)
    will_release_count = int(data.get("willReleaseCount", 0) or 0)
    other_using_count = int(data.get("otherUsingCount", 0) or 0)
    focus_used_count = using_count + other_using_count
    occupied = using_count + will_release_count + other_using_count

    threshold_percent = 80
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                cfg = json.load(f)
                if isinstance(cfg, dict) and "threshold_percent" in cfg:
                    threshold_percent = int(cfg["threshold_percent"])
        except Exception:
            pass

    threshold_factor = threshold_percent / 100.0
    threshold = all_count * threshold_factor
    alert = focus_used_count > threshold if all_count > 0 else False

    result = {
        "status": "alert" if alert else "ok",
        "agent": "庆龙测试",
        "monitor": "maskPhone_topCount",
        "allCount": all_count,
        "usingCount": using_count,
        "willReleaseCount": will_release_count,
        "otherUsingCount": other_using_count,
        "focusUsedCount": focus_used_count,
        "occupiedCount": occupied,
        "threshold": threshold,
        "message": (
            f"报警: usingCount + otherUsingCount = {focus_used_count}，已超过 allCount 的 {threshold_factor * 100:.0f}% 阈值 {threshold:.1f}" if alert
            else f"正常: usingCount + otherUsingCount = {focus_used_count}，未超过 allCount 的 {threshold_factor * 100:.0f}% 阈值 {threshold:.1f}"
        ),
        "raw": data,
    }
    persist_result(result)
    print(json.dumps(result, ensure_ascii=False))
    return 1 if alert else 0


if __name__ == "__main__":
    sys.exit(main())
