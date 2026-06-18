from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from .db import AppDatabase, mask_secret
from .mfood.config import MFoodSettings
from .runner import TaskRunner
from .schedule import dumps_schedule, due_key, load_schedule, next_run_after
from .tasks.registry import TaskDefinition, get_agent_meta, get_task, list_tasks
from .telegram import TelegramConfig, TelegramUpdateListener


TZ = ZoneInfo("Asia/Shanghai")


class TraeclawApp:
    def __init__(
        self,
        project_root: str | Path,
        db: AppDatabase | None = None,
        import_legacy_state: bool = True,
    ):
        self.project_root = Path(project_root).resolve()
        self.db = db or AppDatabase(self.project_root / "code" / "data" / "traeclaw.sqlite3")
        self.import_legacy_state = import_legacy_state
        self.runner = TaskRunner(self.db, self.project_root)
        self.telegram_listener = TelegramUpdateListener(self.db)

    def initialize(self) -> None:
        self.db.initialize()
        if self.import_legacy_state:
            self.import_legacy_sources()
        self.import_and_cleanup_configs()
        
        # Start background Telegram chat title initialization
        from .telegram import initialize_chat_titles_bg
        initialize_chat_titles_bg(self.db)

    def import_and_cleanup_configs(self) -> None:
        from .runner import TASK_FILE_MAP
        all_files = set()
        for files in TASK_FILE_MAP.values():
            all_files.update(files)

        for rel_path in all_files:
            file_path = self.project_root / rel_path
            if file_path.exists():
                try:
                    content = file_path.read_text(encoding="utf-8")
                    self.db.set_setting(f"file:{rel_path}", content)
                    file_path.unlink()
                    parent = file_path.parent
                    while parent != self.project_root / "code" / "state" and parent != self.project_root:
                        try:
                            parent.rmdir()
                            parent = parent.parent
                        except Exception:
                            break
                except Exception:
                    pass

    def start_background_services(self) -> None:
        if self.db.get_setting("telegram.listener_enabled", "0") == "1":
            self.telegram_listener.start()

    def stop_background_services(self) -> None:
        self.telegram_listener.stop()

    def import_legacy_sources(self) -> list[dict[str, Any]]:
        sources = [
            self.project_root / "code" / "state" / "cp" / "doublecolor.db",
            self.project_root / "code" / "state" / "mfdb" / "maskphone_monitor.db",
            self.project_root / "code" / "state" / "scjk" / "shence_monitor.db",
        ]
        return [self.db.import_sqlite_tables(source) for source in sources if source.exists()]

    def list_task_cards(self, now: datetime | None = None) -> list[dict[str, Any]]:
        if not getattr(self, "_chat_titles_initialized", False):
            self._chat_titles_initialized = True
            from .telegram import initialize_chat_titles_bg
            initialize_chat_titles_bg(self.db)

        now = now or datetime.now(TZ)
        cards = []
        chat_titles = self.db.get_latest_chat_titles()
        global_chat_id = self.db.get_setting("telegram.chat_id", "").strip()

        for task in list_tasks():
            schedule = self.get_task_schedule(task)
            next_run = next_run_after(task, schedule, now)
            enabled = self.is_task_enabled(task)
            latest_run = self.db.get_latest_run(task.id)
            latest_results = self.db.get_task_results(task.id, limit=3)
            alert = _task_has_alert(task, latest_run, latest_results)

            task_chat_id = self.db.get_setting(f"task.{task.id}.telegram_chat_id", "").strip()
            resolved_chat_id = task_chat_id or global_chat_id
            telegram_group_name = chat_titles.get(resolved_chat_id, "") if resolved_chat_id else ""

            cards.append(
                {
                    "id": task.id,
                    "name": task.name,
                    "group": task.group,
                    "description": task.description,
                    "schedule_label": schedule["label"],
                    "default_schedule_label": task.schedule_label,
                    "schedule": schedule,
                    "next_run_at": next_run.isoformat() if next_run else None,
                    "enabled": enabled,
                    "enabled_by_default": task.enabled_by_default,
                    "command": task.command_label,
                    "alert": alert,
                    "alert_label": "警报" if alert else "",
                    "last_run": latest_run,
                    "recent_runs": self.db.get_runs(task.id, limit=5),
                    "latest_results": latest_results,
                    "telegram_chat_id": resolved_chat_id,
                    "telegram_group_name": telegram_group_name,
                }
            )
        return cards
    def list_agent_cards(self, now: datetime | None = None) -> list[dict[str, Any]]:
        tasks = self.list_task_cards(now=now)
        grouped: dict[str, list[dict[str, Any]]] = {}
        order: list[str] = []
        for task in tasks:
            agent_id = task["group"]
            if agent_id not in grouped:
                grouped[agent_id] = []
                order.append(agent_id)
            grouped[agent_id].append(task)

        # Apply custom agent sorting order if configured
        custom_order_str = self.db.get_setting("agent.order", "").strip()
        if custom_order_str:
            custom_order = [x.strip() for x in custom_order_str.split(",") if x.strip()]
            new_order = []
            for agent_id in custom_order:
                if agent_id in order:
                    new_order.append(agent_id)
            for agent_id in order:
                if agent_id not in new_order:
                    new_order.append(agent_id)
            order = new_order

        agents = []
        for agent_id in order:
            agent_tasks = grouped[agent_id]
            meta = get_agent_meta(agent_id)
            default_name = meta["name"]
            alias = self.get_agent_alias(agent_id)
            statuses = [task["last_run"]["status"] for task in agent_tasks if task.get("last_run")]
            status = _agent_status(statuses, agent_tasks)
            schedule_summary = " / ".join(dict.fromkeys(task["schedule_label"] for task in agent_tasks))
            next_times = [task["next_run_at"] for task in agent_tasks if task.get("next_run_at")]
            agents.append(
                {
                    "id": agent_id,
                    "name": alias or default_name,
                    "default_name": default_name,
                    "alias": alias,
                    "folder": meta["folder"],
                    "description": meta["description"],
                    "task_count": len(agent_tasks),
                    "enabled_count": sum(1 for task in agent_tasks if task["enabled"]),
                    "status": status,
                    "schedule_summary": schedule_summary,
                    "next_run_at": min(next_times) if next_times else None,
                    "tasks": agent_tasks,
                }
            )
        return agents

    def get_task_schedule(self, task: TaskDefinition | str) -> dict[str, Any]:
        task_def = get_task(task) if isinstance(task, str) else task
        raw = self.db.get_setting(f"task.{task_def.id}.schedule", "")
        schedule_data = load_schedule(task_def, raw)
        schedule_data["telegram_chat_id"] = self.db.get_setting(f"task.{task_def.id}.telegram_chat_id", "").strip()
        schedule_data["notification_template"] = self.db.get_setting(f"task.{task_def.id}.notification_template", "")
        return schedule_data

    def save_task_schedule(self, task_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        task = get_task(task_id)
        if payload.get("reset"):
            self.db.set_setting(f"task.{task.id}.schedule", "")
            self.db.set_setting(f"task.{task.id}.telegram_chat_id", "")
            self.db.set_setting(f"task.{task.id}.notification_template", "")
            return self.get_task_schedule(task)
        self.db.set_setting(f"task.{task.id}.schedule", dumps_schedule(payload))
        self.db.set_setting(f"task.{task.id}.telegram_chat_id", str(payload.get("telegram_chat_id") or "").strip())
        self.db.set_setting(f"task.{task.id}.notification_template", str(payload.get("notification_template") or ""))
        return self.get_task_schedule(task)

    def get_agent_alias(self, agent_id: str) -> str:
        return self.db.get_setting(f"agent.{agent_id}.alias", "").strip()

    def save_agent_alias(self, agent_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        if agent_id not in {task.group for task in list_tasks()}:
            raise KeyError(f"Unknown task group: {agent_id}")
        alias = str(payload.get("alias") or "").strip()
        if len(alias) > 80:
            raise ValueError("Alias must be 80 characters or less")
        self.db.set_setting(f"agent.{agent_id}.alias", alias)
        meta = get_agent_meta(agent_id)
        return {
            "id": agent_id,
            "name": alias or meta["name"],
            "default_name": meta["name"],
            "alias": alias,
            "folder": meta["folder"],
        }

    def list_agent_runs(self, agent_id: str, limit: int | None = 10) -> dict[str, Any]:
        tasks = [task for task in list_tasks() if task.group == agent_id]
        if not tasks:
            raise KeyError(f"Unknown task group: {agent_id}")
        task_names = {task.id: task.name for task in tasks}
        runs = self.db.get_runs_for_task_ids([task.id for task in tasks], limit=limit)
        for run in runs:
            run["task_name"] = task_names.get(run["task_id"], run["task_id"])
        return {
            "task_group": agent_id,
            "limit": limit,
            "runs": runs,
        }

    def is_task_enabled(self, task: TaskDefinition) -> bool:
        raw = self.db.get_setting(f"task.{task.id}.enabled", "")
        if raw == "":
            return task.enabled_by_default
        return raw == "1"

    def set_task_enabled(self, task_id: str, enabled: bool) -> None:
        get_task(task_id)
        self.db.set_setting(f"task.{task_id}.enabled", "1" if enabled else "0")

    def task_due_key(self, task: TaskDefinition, now: datetime) -> str:
        return due_key(task, self.get_task_schedule(task), now)

    def run_task(self, task_id: str, trigger_type: str = "manual", send_to_telegram: bool = False) -> dict[str, Any]:
        task = get_task(task_id)
        return self.runner.run(task, trigger_type=trigger_type, send_to_telegram=send_to_telegram)

    def get_telegram_settings(self) -> dict[str, Any]:
        return TelegramConfig.load_public(self.db)

    def save_telegram_settings(self, payload: dict[str, Any]) -> dict[str, Any]:
        TelegramConfig.save(
            self.db,
            enabled=bool(payload.get("enabled")),
            bot_token=str(payload.get("bot_token") or "").strip(),
            chat_id=str(payload.get("chat_id") or "").strip(),
        )
        return self.get_telegram_settings()

    def get_telegram_listener(self) -> dict[str, Any]:
        return self.telegram_listener.status()

    def save_telegram_listener(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.telegram_listener.set_enabled(bool(payload.get("enabled")))

    def poll_telegram_listener(self) -> dict[str, Any]:
        result = self.telegram_listener.poll_once()
        status = self.telegram_listener.status()
        status["poll"] = result
        return status

    def get_mfood_settings(self) -> dict[str, Any]:
        settings = MFoodSettings.load_public(self.db)
        token = self.db.get_setting("mfood.login.token", "")
        settings["login"]["token_configured"] = bool(token)
        settings["login"]["token_masked"] = mask_secret(token) if token else ""
        return settings

    def save_mfood_settings(self, payload: dict[str, Any]) -> dict[str, Any]:
        MFoodSettings.save(self.db, payload)
        return self.get_mfood_settings()

    def mfood_login(self, force_refresh: bool = False) -> dict[str, Any]:
        from .mfood.login import MFoodLogin
        login = MFoodLogin(self.db, self.project_root)
        return login.get_token(force_refresh=force_refresh)

    def save_agent_order(self, order: list[str]) -> None:
        from .tasks.registry import list_tasks
        valid_groups = {task.group for task in list_tasks()}
        clean_order = [g for g in order if g in valid_groups]
        self.db.set_setting("agent.order", ",".join(clean_order))



def _agent_status(statuses: list[str], tasks: list[dict[str, Any]]) -> str:
    if any(status == "failed" for status in statuses):
        return "failed"
    if any(status == "running" for status in statuses):
        return "running"
    if any(status == "success" for status in statuses):
        return "success"
    if any(task["enabled"] for task in tasks):
        return "pending"
    return "disabled"


def _task_has_alert(
    task: TaskDefinition,
    latest_run: dict[str, Any] | None,
    latest_results: list[dict[str, Any]],
) -> bool:
    if task.group not in {"mFood", "shence"}:
        return False
    for result in latest_results:
        if _payload_has_alert(result.get("payload")):
            return True
    if latest_run:
        text = "\n".join(
            str(latest_run.get(key) or "")
            for key in ("summary", "stdout", "stderr")
        )
        return _text_has_alert(text)
    return False


def _payload_has_alert(value: Any) -> bool:
    if isinstance(value, dict):
        status = str(value.get("status") or "").strip().lower()
        if status == "alert":
            return True
        for key, item in value.items():
            key_text = str(key).lower()
            if key_text.endswith("alert") and item is True:
                return True
            if _payload_has_alert(item):
                return True
        return False
    if isinstance(value, list):
        return any(_payload_has_alert(item) for item in value)
    if isinstance(value, str):
        return _text_has_alert(value)
    return False


def _text_has_alert(value: str) -> bool:
    alert_words = ("报警", "告警", "异常")
    return any(word in value for word in alert_words)
