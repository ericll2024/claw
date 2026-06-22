from __future__ import annotations

import json
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def mask_secret(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 4:
        return "*" * len(value)
    return ("*" * 12) + value[-4:]


class AppDatabase:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA foreign_keys = ON")
            yield conn
            conn.commit()
        finally:
            conn.close()

    def initialize(self) -> None:
        with self.connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL DEFAULT '',
                    is_secret INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS task_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT NOT NULL,
                    trigger_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    finished_at TEXT,
                    duration_ms INTEGER,
                    exit_code INTEGER,
                    stdout TEXT NOT NULL DEFAULT '',
                    stderr TEXT NOT NULL DEFAULT '',
                    summary TEXT NOT NULL DEFAULT '',
                    notify_status TEXT NOT NULL DEFAULT '',
                    notify_error TEXT NOT NULL DEFAULT ''
                );
                CREATE INDEX IF NOT EXISTS idx_task_runs_task_started
                    ON task_runs(task_id, started_at DESC);

                CREATE TABLE IF NOT EXISTS task_results (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT NOT NULL,
                    run_id INTEGER,
                    result_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(run_id) REFERENCES task_runs(id)
                );
                CREATE INDEX IF NOT EXISTS idx_task_results_task_created
                    ON task_results(task_id, created_at DESC);

                CREATE TABLE IF NOT EXISTS legacy_imports (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_path TEXT NOT NULL,
                    table_name TEXT NOT NULL,
                    row_count INTEGER NOT NULL,
                    imported_at TEXT NOT NULL,
                    UNIQUE(source_path, table_name)
                );

                CREATE TABLE IF NOT EXISTS telegram_updates (
                    update_id INTEGER PRIMARY KEY,
                    message_id INTEGER,
                    chat_id TEXT NOT NULL,
                    chat_type TEXT NOT NULL DEFAULT '',
                    chat_title TEXT NOT NULL DEFAULT '',
                    message_thread_id INTEGER,
                    from_id TEXT NOT NULL DEFAULT '',
                    from_name TEXT NOT NULL DEFAULT '',
                    text TEXT NOT NULL DEFAULT '',
                    is_mention INTEGER NOT NULL DEFAULT 0,
                    message_date TEXT NOT NULL DEFAULT '',
                    received_at TEXT NOT NULL,
                    raw_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_telegram_updates_received
                    ON telegram_updates(received_at DESC);
                CREATE INDEX IF NOT EXISTS idx_telegram_updates_chat
                    ON telegram_updates(chat_id, received_at DESC);
                """
            )
            # Check if login.password_md5 exists, if not set it
            row = conn.execute("SELECT 1 FROM settings WHERE key = 'login.password_md5'").fetchone()
            if not row:
                conn.execute(
                    """
                    INSERT INTO settings (key, value, is_secret, updated_at)
                    VALUES ('login.password_md5', '23feb120658a1cb2c5b0be2be826bbc9', 1, ?)
                    """,
                    (utc_now(),),
                )

    def set_setting(self, key: str, value: str, is_secret: bool = False) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO settings (key, value, is_secret, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    is_secret = excluded.is_secret,
                    updated_at = excluded.updated_at
                """,
                (key, value, 1 if is_secret else 0, utc_now()),
            )

    def get_setting(self, key: str, default: str = "") -> str:
        with self.connect() as conn:
            row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return str(row["value"]) if row else default

    def get_settings_public(self) -> dict[str, dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT key, value, is_secret, updated_at FROM settings ORDER BY key"
            ).fetchall()
        result: dict[str, dict[str, Any]] = {}
        for row in rows:
            value = str(row["value"])
            is_secret = bool(row["is_secret"])
            result[row["key"]] = {
                "value": mask_secret(value) if is_secret else value,
                "configured": bool(value),
                "is_secret": is_secret,
                "updated_at": row["updated_at"],
            }
        return result

    def start_run(self, task_id: str, trigger_type: str) -> int:
        with self.connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO task_runs (task_id, trigger_type, status, started_at)
                VALUES (?, ?, 'running', ?)
                """,
                (task_id, trigger_type, utc_now()),
            )
            return int(cur.lastrowid)

    def finish_run(
        self,
        run_id: int,
        status: str,
        exit_code: int | None,
        stdout: str,
        stderr: str,
        summary: str,
        result_payload: dict[str, Any] | list[Any] | None = None,
        notify_status: str = "",
        notify_error: str = "",
    ) -> None:
        finished_at = utc_now()
        with self.connect() as conn:
            row = conn.execute("SELECT started_at, task_id FROM task_runs WHERE id = ?", (run_id,)).fetchone()
            duration_ms = None
            task_id = ""
            if row:
                task_id = row["task_id"]
                started_at = datetime.fromisoformat(row["started_at"])
                duration_ms = int((datetime.fromisoformat(finished_at) - started_at).total_seconds() * 1000)
            conn.execute(
                """
                UPDATE task_runs
                SET status = ?, finished_at = ?, duration_ms = ?, exit_code = ?,
                    stdout = ?, stderr = ?, summary = ?, notify_status = ?, notify_error = ?
                WHERE id = ?
                """,
                (
                    status,
                    finished_at,
                    duration_ms,
                    exit_code,
                    stdout,
                    stderr,
                    summary,
                    notify_status,
                    notify_error,
                    run_id,
                ),
            )
            if result_payload is not None and task_id:
                conn.execute(
                    """
                    INSERT INTO task_results (task_id, run_id, result_type, payload_json, created_at)
                    VALUES (?, ?, 'run', ?, ?)
                    """,
                    (task_id, run_id, json.dumps(result_payload, ensure_ascii=False), finished_at),
                )

    def cleanup_stuck_runs(self) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE task_runs
                SET status = 'failed',
                    finished_at = ?,
                    summary = '服务器重启，任务被动中断',
                    stderr = 'Task interrupted due to server restart.'
                WHERE status = 'running'
                """,
                (utc_now(),),
            )

    def get_latest_run(self, task_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM task_runs WHERE task_id = ? ORDER BY started_at DESC, id DESC LIMIT 1",
                (task_id,),
            ).fetchone()
        return dict(row) if row else None

    def get_runs(self, task_id: str, limit: int = 10) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM task_runs
                WHERE task_id = ?
                ORDER BY started_at DESC, id DESC
                LIMIT ?
                """,
                (task_id, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_runs_for_task_ids(self, task_ids: list[str], limit: int | None = 10, offset: int | None = None) -> list[dict[str, Any]]:
        if not task_ids:
            return []
        placeholders = ", ".join("?" for _ in task_ids)
        params: list[Any] = list(task_ids)
        limit_clause = ""
        if limit is not None:
            limit_clause = "LIMIT ?"
            params.append(limit)
            if offset is not None:
                limit_clause += " OFFSET ?"
                params.append(offset)
        with self.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM task_runs
                WHERE task_id IN ({placeholders})
                ORDER BY started_at DESC, id DESC
                {limit_clause}
                """,
                params,
            ).fetchall()
        return [dict(row) for row in rows]

    def delete_run(self, run_id: int) -> None:
        with self.connect() as conn:
            conn.execute("DELETE FROM task_results WHERE run_id = ?", (run_id,))
            conn.execute("DELETE FROM task_runs WHERE id = ?", (run_id,))

    def get_task_results(self, task_id: str, limit: int = 10) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM task_results
                WHERE task_id = ?
                ORDER BY created_at DESC, id DESC
                LIMIT ?
                """,
                (task_id, limit),
            ).fetchall()
        results = []
        for row in rows:
            item = dict(row)
            item["payload"] = json.loads(item.pop("payload_json"))
            results.append(item)
        return results

    def save_telegram_update(self, item: dict[str, Any]) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO telegram_updates (
                    update_id, message_id, chat_id, chat_type, chat_title,
                    message_thread_id, from_id, from_name, text, is_mention,
                    message_date, received_at, raw_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item["update_id"],
                    item.get("message_id"),
                    item["chat_id"],
                    item.get("chat_type", ""),
                    item.get("chat_title", ""),
                    item.get("message_thread_id"),
                    item.get("from_id", ""),
                    item.get("from_name", ""),
                    item.get("text", ""),
                    1 if item.get("is_mention") else 0,
                    item.get("message_date", ""),
                    item.get("received_at") or utc_now(),
                    json.dumps(item.get("raw", {}), ensure_ascii=False),
                ),
            )

    def list_telegram_updates(self, limit: int = 50) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM telegram_updates
                ORDER BY received_at DESC, update_id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        updates = []
        for row in rows:
            item = dict(row)
            item["is_mention"] = bool(item["is_mention"])
            item["raw"] = json.loads(item.pop("raw_json"))
            updates.append(item)
        return updates

    def get_latest_chat_titles(self) -> dict[str, str]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT chat_id, chat_title
                FROM telegram_updates
                WHERE chat_title != ''
                ORDER BY received_at ASC, update_id ASC
                """
            ).fetchall()
        return {row["chat_id"]: row["chat_title"] for row in rows}

    def import_sqlite_tables(self, source_path: str | Path) -> dict[str, Any]:
        source = Path(source_path)
        if not source.exists():
            return {"source_path": str(source), "tables": [], "missing": True}
        imported: list[str] = []
        with self.connect() as conn:
            conn.execute("ATTACH DATABASE ? AS legacy", (str(source),))
            conn.execute("PRAGMA foreign_keys = OFF")
            try:
                tables = conn.execute(
                    """
                    SELECT name, sql FROM legacy.sqlite_master
                    WHERE type = 'table'
                      AND name NOT LIKE 'sqlite_%'
                    ORDER BY name
                    """
                ).fetchall()
                for table in tables:
                    name = str(table["name"])
                    sql = table["sql"]
                    if not sql:
                        continue
                    conn.execute(_with_if_not_exists(sql))
                    imported.append(name)
                conn.commit()

                for name in imported:
                    _copy_table_rows(conn, name)
                    row_count = conn.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]
                    conn.execute(
                        """
                        INSERT INTO legacy_imports (source_path, table_name, row_count, imported_at)
                        VALUES (?, ?, ?, ?)
                        ON CONFLICT(source_path, table_name) DO UPDATE SET
                            row_count = excluded.row_count,
                            imported_at = excluded.imported_at
                        """,
                        (str(source), name, int(row_count), utc_now()),
                    )
                conn.commit()

                indexes = conn.execute(
                    """
                    SELECT name, sql FROM legacy.sqlite_master
                    WHERE type = 'index'
                      AND sql IS NOT NULL
                      AND name NOT LIKE 'sqlite_%'
                    ORDER BY name
                    """
                ).fetchall()
                for index in indexes:
                    conn.execute(_index_with_if_not_exists(str(index["sql"])))
                conn.commit()
            finally:
                conn.rollback()
                conn.execute("DETACH DATABASE legacy")
                conn.execute("PRAGMA foreign_keys = ON")
        return {"source_path": str(source), "tables": imported, "missing": False}


def _with_if_not_exists(sql: str) -> str:
    return re.sub(
        r"^CREATE\s+TABLE\s+(?!IF\s+NOT\s+EXISTS)",
        "CREATE TABLE IF NOT EXISTS ",
        sql,
        count=1,
        flags=re.IGNORECASE,
    )


def _index_with_if_not_exists(sql: str) -> str:
    return re.sub(
        r"^CREATE\s+(UNIQUE\s+)?INDEX\s+(?!IF\s+NOT\s+EXISTS)",
        lambda match: f"CREATE {match.group(1) or ''}INDEX IF NOT EXISTS ",
        sql,
        count=1,
        flags=re.IGNORECASE,
    )


def _copy_table_rows(conn: sqlite3.Connection, table_name: str) -> None:
    columns = [
        row["name"]
        for row in conn.execute(f'PRAGMA legacy.table_info("{table_name}")').fetchall()
    ]
    if not columns:
        return
    quoted = ", ".join(f'"{name}"' for name in columns)
    conn.execute(
        f'INSERT OR IGNORE INTO "{table_name}" ({quoted}) '
        f'SELECT {quoted} FROM legacy."{table_name}"'
    )
