from __future__ import annotations

import json
import threading
import time
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable
from urllib.parse import urlencode

from .db import AppDatabase, mask_secret, utc_now


def post_json(url: str, payload: dict[str, Any], timeout: int = 20) -> dict[str, Any]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def get_json(url: str, params: dict[str, Any] | None = None, timeout: int = 20) -> dict[str, Any]:
    if params:
        url = f"{url}?{urlencode(params)}"
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


class TelegramConfig:
    @staticmethod
    def save(db: AppDatabase, enabled: bool, bot_token: str = "", chat_id: str = "") -> None:
        db.set_setting("telegram.enabled", "1" if enabled else "0")
        if bot_token:
            db.set_setting("telegram.bot_token", bot_token.strip(), is_secret=True)
        db.set_setting("telegram.chat_id", chat_id.strip())

    @staticmethod
    def load_private(db: AppDatabase) -> dict[str, Any]:
        enabled = db.get_setting("telegram.enabled", "0") == "1"
        bot_token = db.get_setting("telegram.bot_token", "")
        chat_id = db.get_setting("telegram.chat_id", "")
        return {
            "enabled": enabled,
            "bot_token": bot_token,
            "chat_id": chat_id,
            "token_configured": bool(bot_token),
            "configured": bool(bot_token and chat_id),
        }

    @staticmethod
    def load_public(db: AppDatabase) -> dict[str, Any]:
        private = TelegramConfig.load_private(db)
        return {
            "enabled": private["enabled"],
            "bot_token": mask_secret(private["bot_token"]),
            "chat_id": private["chat_id"],
            "token_configured": private["token_configured"],
            "configured": private["configured"],
        }


@dataclass
class TelegramNotifier:
    bot_token: str
    chat_id: str
    post_json: Callable[[str, dict[str, Any], int], dict[str, Any]] = post_json

    def send_message(self, text: str) -> dict[str, Any]:
        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        return self.post_json(
            url,
            {
                "chat_id": self.chat_id,
                "text": text,
                "disable_web_page_preview": True,
            },
            20,
        )


class TelegramUpdateListener:
    def __init__(
        self,
        db: AppDatabase,
        get_json_func: Callable[[str, dict[str, Any] | None, int], dict[str, Any]] = get_json,
        poll_interval: float = 3.0,
    ):
        self.db = db
        self.get_json = get_json_func
        self.poll_interval = poll_interval
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    def start(self) -> None:
        if self.is_running():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, name="telegram-update-listener", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=2)

    def is_running(self) -> bool:
        thread = self._thread
        return bool(thread and thread.is_alive())

    def status(self, limit: int = 50) -> dict[str, Any]:
        token = TelegramConfig.load_private(self.db)["bot_token"]
        return {
            "enabled": self.db.get_setting("telegram.listener_enabled", "0") == "1",
            "running": self.is_running(),
            "configured": bool(token),
            "bot_username": self.db.get_setting("telegram.bot_username", ""),
            "last_poll_at": self.db.get_setting("telegram.listener_last_poll_at", ""),
            "last_error": self.db.get_setting("telegram.listener_last_error", ""),
            "updates": self.db.list_telegram_updates(limit=limit),
        }

    def set_enabled(self, enabled: bool) -> dict[str, Any]:
        token = TelegramConfig.load_private(self.db)["bot_token"]
        if enabled and not token:
            raise ValueError("请先保存 Telegram Bot Token")
        self.db.set_setting("telegram.listener_enabled", "1" if enabled else "0")
        if enabled:
            self.start()
        else:
            self.stop()
        return self.status()

    def poll_once(self, timeout: int = 2) -> dict[str, Any]:
        with self._lock:
            token = TelegramConfig.load_private(self.db)["bot_token"]
            if not token:
                raise ValueError("请先保存 Telegram Bot Token")
            bot_username = self._ensure_bot_username(token)
            offset = self.db.get_setting("telegram.update_offset", "")
            params: dict[str, Any] = {
                "timeout": timeout,
                "allowed_updates": json.dumps(["message", "edited_message"], ensure_ascii=False),
            }
            if offset:
                params["offset"] = offset
            payload = self.get_json(f"https://api.telegram.org/bot{token}/getUpdates", params, timeout + 5)
            if not payload.get("ok"):
                raise RuntimeError(str(payload.get("description") or "Telegram getUpdates failed"))
            updates = payload.get("result") or []
            max_update_id = None
            saved = 0
            for update in updates:
                update_id = int(update.get("update_id", 0))
                max_update_id = update_id if max_update_id is None else max(max_update_id, update_id)
                item = _telegram_update_to_row(update, bot_username)
                if item:
                    self.db.save_telegram_update(item)
                    saved += 1
            if max_update_id is not None:
                self.db.set_setting("telegram.update_offset", str(max_update_id + 1))
            self.db.set_setting("telegram.listener_last_poll_at", utc_now())
            self.db.set_setting("telegram.listener_last_error", "")
            return {"received": len(updates), "saved": saved, "bot_username": bot_username}

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            if self.db.get_setting("telegram.listener_enabled", "0") != "1":
                break
            try:
                self.poll_once(timeout=8)
            except Exception as exc:
                self.db.set_setting("telegram.listener_last_error", str(exc)[:500])
            self._stop_event.wait(self.poll_interval)

    def _ensure_bot_username(self, token: str) -> str:
        username = self.db.get_setting("telegram.bot_username", "")
        if username:
            return username
        payload = self.get_json(f"https://api.telegram.org/bot{token}/getMe", None, 10)
        if not payload.get("ok"):
            raise RuntimeError(str(payload.get("description") or "Telegram getMe failed"))
        username = str((payload.get("result") or {}).get("username") or "")
        if username:
            self.db.set_setting("telegram.bot_username", username)
        return username


def _telegram_update_to_row(update: dict[str, Any], bot_username: str = "") -> dict[str, Any] | None:
    message = update.get("message") or update.get("edited_message")
    if not isinstance(message, dict):
        return None
    chat = message.get("chat") or {}
    sender = message.get("from") or {}
    text = str(message.get("text") or message.get("caption") or "")
    first_name = str(sender.get("first_name") or "")
    last_name = str(sender.get("last_name") or "")
    username = str(sender.get("username") or "")
    from_name = " ".join(part for part in [first_name, last_name] if part).strip()
    if username:
        from_name = f"{from_name} (@{username})".strip()
    message_date = ""
    if message.get("date"):
        message_date = datetime.fromtimestamp(int(message["date"]), timezone.utc).isoformat()
    chat_title = str(chat.get("title") or chat.get("username") or chat.get("first_name") or "")
    mention = _message_mentions_bot(text, bot_username)
    return {
        "update_id": int(update["update_id"]),
        "message_id": message.get("message_id"),
        "chat_id": str(chat.get("id") or ""),
        "chat_type": str(chat.get("type") or ""),
        "chat_title": chat_title,
        "message_thread_id": message.get("message_thread_id"),
        "from_id": str(sender.get("id") or ""),
        "from_name": from_name,
        "text": text,
        "is_mention": mention,
        "message_date": message_date,
        "received_at": utc_now(),
        "raw": update,
    }


def _message_mentions_bot(text: str, bot_username: str) -> bool:
    if not text:
        return False
    if text.startswith("/"):
        return True
    if not bot_username:
        return False
    return f"@{bot_username.lower()}" in text.lower()


def initialize_chat_titles_bg(db: AppDatabase) -> None:
    def run():
        try:
            bot_token = db.get_setting("telegram.bot_token", "").strip()
            if not bot_token:
                return
            chat_ids = []
            global_id = db.get_setting("telegram.chat_id", "").strip()
            if global_id:
                chat_ids.append(global_id)
            with db.connect() as conn:
                rows = conn.execute(
                    "SELECT value FROM settings WHERE key LIKE 'task.%.telegram_chat_id'"
                ).fetchall()
                for row in rows:
                    val = str(row["value"]).strip()
                    if val and val not in chat_ids:
                        chat_ids.append(val)
            
            existing_titles = db.get_latest_chat_titles()
            for chat_id in chat_ids:
                if chat_id not in existing_titles or not existing_titles[chat_id]:
                    # Call getChat API
                    url = f"https://api.telegram.org/bot{bot_token}/getChat?chat_id={chat_id}"
                    try:
                        req = urllib.request.Request(url)
                        with urllib.request.urlopen(req, timeout=10) as response:
                            payload = json.loads(response.read().decode("utf-8"))
                            if payload.get("ok"):
                                result = payload["result"]
                                title = result.get("title") or result.get("username") or result.get("first_name") or ""
                                if title:
                                    db.save_telegram_update({
                                        "update_id": int(time.time() * 1000),
                                        "message_id": 0,
                                        "chat_id": chat_id,
                                        "chat_type": result.get("type", "group"),
                                        "chat_title": title,
                                        "from_id": "system",
                                        "from_name": "System",
                                        "text": "System initialized chat title",
                                        "is_mention": False,
                                        "received_at": utc_now(),
                                        "raw": result,
                                    })
                    except Exception:
                        pass
        except Exception:
            pass

    threading.Thread(target=run, daemon=True).start()
