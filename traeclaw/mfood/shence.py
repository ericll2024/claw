from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import Any
from urllib import error, request

from ..db import AppDatabase
from .config import MFoodSettings


class MFoodShence:
    def __init__(self, db: AppDatabase):
        self.db = db

    def query(self, sql: str, limit: int = 100, timeout: int = 60) -> dict[str, Any]:
        settings = MFoodSettings.load_private(self.db)["shence"]
        if not settings["configured"]:
            raise RuntimeError("mFood 神策配置缺失：请填写 sensors_api_key 和 sensors_project")
        rows = run_query(
            sql=sql,
            api_url=settings["api_url"],
            sensors_api_key=settings["sensors_api_key"],
            sensors_project=settings["sensors_project"],
            limit=max(1, int(limit)),
            timeout=max(1, int(timeout)),
        )
        return {
            "sql": sql,
            "row_count": len(rows),
            "columns": list(rows[0].keys()) if rows else [],
            "rows": rows,
        }


def run_query(
    *,
    sql: str,
    api_url: str,
    sensors_api_key: str,
    sensors_project: str,
    limit: int,
    timeout: int,
) -> list[dict[str, Any]]:
    url = f"{api_url.rstrip('/')}/api/v3/analytics/v1/model/sql/query"
    payload = {
        "sql": sql.strip(),
        "limit": str(limit),
        "request_id": uuid.uuid4().hex,
    }
    headers = {
        "Content-Type": "application/json",
        "api-key": sensors_api_key,
        "sensorsdata-project": sensors_project,
    }
    req = request.Request(
        url=url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=timeout) as response:
            raw_text = response.read().decode("utf-8", errors="replace")
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Sensors query failed with HTTP {exc.code}: {body}") from exc
    except error.URLError as exc:
        raise RuntimeError(f"Sensors query request failed: {exc}") from exc
    return parse_response_text(raw_text)


def parse_response_text(raw_text: str) -> list[dict[str, Any]]:
    text = raw_text.strip()
    if not text:
        return []
    try:
        parsed: Any = json.loads(text)
    except json.JSONDecodeError:
        parsed = [json.loads(line) for line in text.splitlines() if line.strip()]
    items = parsed if isinstance(parsed, list) else [parsed]
    rows: list[dict[str, Any]] = []
    errors: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        code = item.get("code")
        if code and str(code).upper() != "SUCCESS":
            errors.append(str(item.get("message") or item.get("msg") or code))
            continue
        data_block = item.get("data")
        if not isinstance(data_block, dict):
            continue
        columns = data_block.get("columns")
        values = data_block.get("data")
        if not isinstance(columns, list):
            continue
        if isinstance(values, list) and values and all(isinstance(entry, list) for entry in values):
            for entry in values:
                if len(entry) == len(columns):
                    rows.append(dict(zip(columns, entry)))
        elif isinstance(values, list) and len(values) == len(columns):
            rows.append(dict(zip(columns, values)))
    if errors and not rows:
        raise RuntimeError("Sensors query failed: " + " | ".join(errors))
    return rows


