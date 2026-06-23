from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from .ai import AiSettings, test_deepseek_settings
from .ai_dispatcher import TelegramAiDispatcher
from .db import AppDatabase, mask_secret
from .mfood.config import MFoodSettings
from .runner import TaskRunner, _payload_has_alert, _text_has_alert
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
        if not db:
            if (self.project_root / "code" / "data").is_dir():
                db = AppDatabase(self.project_root / "code" / "data" / "traeclaw.sqlite3")
            else:
                db = AppDatabase(self.project_root / "data" / "traeclaw.sqlite3")
        self.db = db
        self.import_legacy_state = import_legacy_state
        self.runner = TaskRunner(self.db, self.project_root)
        self.telegram_listener = TelegramUpdateListener(self.db)
        self.ai_dispatcher = TelegramAiDispatcher(self)

    def initialize(self) -> None:
        self.db.initialize()
        if self.import_legacy_state:
            self.import_legacy_sources()
        self.import_and_cleanup_configs()
        self.db.cleanup_stuck_runs()
        
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
                    while parent != self.project_root / "state" and parent != self.project_root:
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
        if AiSettings.load_private(self.db)["enabled"]:
            self.ai_dispatcher.start()

    def stop_background_services(self) -> None:
        self.telegram_listener.stop()
        self.ai_dispatcher.stop()

    def import_legacy_sources(self) -> list[dict[str, Any]]:
        state_dir = self.project_root / "code" / "state" if (self.project_root / "code" / "state").is_dir() else self.project_root / "state"
        sources = [
            state_dir / "cp" / "doublecolor.db",
            state_dir / "mfdb" / "maskphone_monitor.db",
            state_dir / "scjk" / "shence_monitor.db",
        ]
        return [self.db.import_sqlite_tables(source) for source in sources if source.exists()]

    def get_task_config_preview(self, task_id: str) -> str | None:
        from .runner import TASK_FILE_MAP
        import json
        files = TASK_FILE_MAP.get(task_id, [])
        if not files:
            return None
        config_key = f"file:{files[0]}"
        content = self.db.get_setting(config_key, "")
        if not content:
            try:
                with open(self.project_root / files[0], "r", encoding="utf-8") as f:
                    content = f.read()
            except Exception:
                return None
        if not content:
            return None
        try:
            data = json.loads(content)
        except Exception:
            return None

        if not isinstance(data, dict):
            return None

        previews = []
        
        # 1. 商户 ID (已按要求隐藏，不显示在左下角预览中)
        # merchant_id = data.get("root_x_merchant")
        # if merchant_id:
        #     previews.append(f"商户ID: {merchant_id}")

        # 2. 门店 ID
        store_ids = data.get("store_ids")
        if store_ids and isinstance(store_ids, list):
            previews.append(f"门店ID: {', '.join(map(str, store_ids))}")
        else:
            payload = data.get("payload", {})
            if isinstance(payload, dict):
                store_id = payload.get("storeId")
                if store_id:
                    previews.append(f"门店ID: {store_id}")
                
                store_ids = payload.get("storeIds")
                if store_ids and isinstance(store_ids, list):
                    previews.append(f"门店ID: {', '.join(map(str, store_ids))}")

        # 3. Facebook 监控群组
        groups = data.get("groups")
        if groups and isinstance(groups, list):
            group_names_or_ids = []
            for g in groups:
                if isinstance(g, str):
                    g = g.strip("/")
                    parts = g.split("/")
                    if parts:
                        group_names_or_ids.append(parts[-1])
            if group_names_or_ids:
                previews.append(f"群组: {', '.join(group_names_or_ids)}")

        if previews:
            return " | ".join(previews)
        return None

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
            config_errors = self.get_task_config_errors(task.id)

            custom_name = schedule.get("name", "")
            task_display_name = custom_name if custom_name else task.name
            custom_note = schedule.get("note", "")

            cards.append(
                {
                    "id": task.id,
                    "name": task_display_name,
                    "reply_name": task.reply_name or task.name,
                    "group": task.group,
                    "description": task.description,
                    "note": custom_note,
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
                    "config_errors": config_errors,
                    "config_preview": self.get_task_config_preview(task.id),
                    "workflow_steps": _serialize_workflow_steps(task),
                    "work_path": get_agent_meta(task.group)["folder"],
                }
            )
        return cards

    def build_ai_task_context(self, task_or_id: TaskDefinition | str, chat_id: str = "") -> dict[str, Any]:
        task = get_task(task_or_id) if isinstance(task_or_id, str) else task_or_id
        cards = {card["id"]: card for card in self.list_task_cards()}
        current = cards.get(task.id)
        if current is None:
            current = {
                "id": task.id,
                "name": task.name,
                "reply_name": task.reply_name or task.name,
                "group": task.group,
                "description": task.description,
                "note": "",
                "schedule_label": task.schedule_label,
                "schedule": {"label": task.schedule_label},
                "next_run_at": None,
                "enabled": self.is_task_enabled(task),
                "command": task.command_label,
                "telegram_chat_id": str(chat_id or ""),
                "telegram_group_name": "",
                "config_preview": None,
                "workflow_steps": _serialize_workflow_steps(task),
                "work_path": get_agent_meta(task.group)["folder"],
                "last_run": self.db.get_latest_run(task.id),
                "recent_runs": self.db.get_runs(task.id, limit=5),
                "latest_results": self.db.get_task_results(task.id, limit=3),
            }
        group_cards = [cards[item.id] for item in list_tasks() if item.group == task.group and item.id in cards]
        latest_job = next((job for job in self.db.list_ai_jobs(limit=20) if job["task_id"] == task.id), None)
        current_task_detail = {
            "id": current["id"],
            "name": current["name"],
            "reply_name": current["reply_name"],
            "group": current["group"],
            "description": current["description"],
            "note": current["note"],
            "schedule_label": current["schedule_label"],
            "schedule": current["schedule"],
            "next_run_at": current["next_run_at"],
            "enabled": current["enabled"],
            "command": current["command"],
            "work_path": current["work_path"],
            "editable_paths": list(task.editable_paths),
            "context_files": list(task.context_files),
            "verify_commands": [list(command) for command in task.verify_commands],
            "telegram_chat_id": current["telegram_chat_id"],
            "telegram_group_name": current["telegram_group_name"],
            "config_preview": current["config_preview"],
            "workflow_steps": current["workflow_steps"],
            "latest_run": current["last_run"],
            "recent_runs": current["recent_runs"][:3],
            "latest_results": current["latest_results"][:3],
            "latest_ai_job": latest_job or {},
        }
        full_group_cards = group_cards or [current]
        if all(item["id"] != current["id"] for item in full_group_cards):
            full_group_cards = [current, *full_group_cards]
        other_tasks = [item for item in full_group_cards if item["id"] != task.id]
        group_task_summaries = [
            {
                "id": item["id"],
                "name": item["name"],
                "reply_name": item["reply_name"],
                "schedule_label": item["schedule_label"],
                "enabled": item["enabled"],
                "next_run_at": item["next_run_at"],
                "latest_run_status": (item.get("last_run") or {}).get("status", ""),
                "latest_run_summary": (item.get("last_run") or {}).get("summary", ""),
                "workflow_title": item["workflow_steps"][0]["title"] if item["workflow_steps"] else "",
                "work_path": item["work_path"],
            }
            for item in other_tasks
        ]
        enabled_count = sum(1 for item in full_group_cards if item["enabled"])
        latest_failure = next(
            (
                item["name"]
                for item in full_group_cards
                if (item.get("last_run") or {}).get("status") == "failed"
            ),
            "",
        )
        group_summary = (
            f"当前群对应分组 {task.group} 共 {len(full_group_cards)} 个任务，"
            f"启用 {enabled_count} 个，最近失败任务: {latest_failure or '无'}"
        )
        return {
            "chat_id": str(chat_id or current["telegram_chat_id"] or ""),
            "group_id": task.group,
            "group_name": get_agent_meta(task.group)["name"],
            "group_summary": group_summary,
            "current_task_detail": current_task_detail,
            "group_task_summaries": group_task_summaries,
        }
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
            custom_task_order_str = self.db.get_setting(f"task.order.{agent_id}", "").strip()
            if custom_task_order_str:
                custom_task_order = [x.strip() for x in custom_task_order_str.split(",") if x.strip()]
                new_tasks_order = []
                for task_id in custom_task_order:
                    found = next((t for t in agent_tasks if t["id"] == task_id), None)
                    if found:
                        new_tasks_order.append(found)
                for t in agent_tasks:
                    if t not in new_tasks_order:
                        new_tasks_order.append(t)
                agent_tasks = new_tasks_order

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
        schedule_data["name"] = self.db.get_setting(f"task.{task_def.id}.name", "").strip()
        schedule_data["note"] = self.db.get_setting(f"task.{task_def.id}.note", "").strip()
        return schedule_data

    def save_task_schedule(self, task_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        task = get_task(task_id)
        self.db.set_setting(f"task.{task.id}.schedule", dumps_schedule(payload, task))
        self.db.set_setting(f"task.{task.id}.telegram_chat_id", str(payload.get("telegram_chat_id") or "").strip())
        self.db.set_setting(f"task.{task.id}.notification_template", str(payload.get("notification_template") or ""))
        self.db.set_setting(f"task.{task.id}.name", str(payload.get("name") or "").strip())
        self.db.set_setting(f"task.{task.id}.note", str(payload.get("note") or "").strip())
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

    def get_task_config_errors(self, task_id: str) -> list[str]:
        import os
        errors = []
        
        def has_setting(key: str) -> bool:
            return bool(self.db.get_setting(key, "").strip())

        def has_setting_or_env(key: str, env_name: str) -> bool:
            return bool(self.db.get_setting(key, "").strip() or os.environ.get(env_name, "").strip())

        if task_id == "mfood.maskphone_monitor":
            if not has_setting_or_env("mfood.login.account", "MFOOD_ACCOUNT"):
                errors.append("mFood 账号未配置（需 MFOOD_ACCOUNT 环境变量或 mFood 登录设置中的账号）")
            if not has_setting("mfood.login.password_md5"):
                errors.append("mFood 密码未配置（需 mFood 登录设置中的密码 MD5）")



        elif task_id == "mfood.order_monitor":
            account = (
                os.environ.get("MFOOD_MANAGER_ACCOUNT") or 
                os.environ.get("MFOOD_ACCOUNT") or
                self.db.get_setting("mfood.login.account", "").strip() or
                self.db.get_setting("mfood.order_monitor.manager_account", "").strip()
            )
            password = (
                os.environ.get("MFOOD_MANAGER_PASSWORD_MD5") or 
                os.environ.get("MFOOD_PASSWORD_MD5") or
                self.db.get_setting("mfood.login.password_md5", "").strip() or
                self.db.get_setting("mfood.order_monitor.manager_password_md5", "").strip()
            )
            api_key = (
                os.environ.get("MFOOD_SENSORS_API_KEY") or
                self.db.get_setting("mfood.shence.sensors_api_key", "").strip() or
                self.db.get_setting("mfood.order_monitor.sensors_api_key", "").strip()
            )
            monitoring_dir_val = (
                os.environ.get("MFOOD_MONITORING_DIR") or
                self.db.get_setting("mfood.order_monitor.monitoring_dir", "").strip()
            )
            if not monitoring_dir_val:
                monitoring_dir_val = "/Users/eric/Documents/project/code/sensorsdata_monitor/monitoring"
                if not os.path.exists(monitoring_dir_val):
                    monitoring_dir_val = "/Users/eric/Documents/project/mfood/神策數據/monitoring"
            else:
                if not os.path.exists(monitoring_dir_val):
                    workspace_dir = "/Users/eric/Documents/project/code/sensorsdata_monitor/monitoring"
                    if os.path.exists(workspace_dir):
                        monitoring_dir_val = workspace_dir

            if not account:
                errors.append("管理账号未配置（需 mFood 登录账号）")
            if not password:
                errors.append("管理密码未配置（需 mFood 登录密码 MD5）")
            if not api_key:
                errors.append("神策 API Key 未配置")
            
            if monitoring_dir_val:
                from pathlib import Path
                path = Path(monitoring_dir_val).expanduser().resolve()
                if not path.exists():
                    errors.append(f"神策对账监控目录不存在：{path}")

        elif task_id in (
            "mfood.takeout_business_analysis",
            "mfood.market_business_analysis",
            "mfood.merchant_summary",
            "mfood.market_summary"
        ):
            if not has_setting_or_env("mfood.login.account", "MFOOD_ACCOUNT"):
                errors.append("mFood 账号未配置（需 MFOOD_ACCOUNT 环境变量或 mFood 登录设置中的账号）")
            if not has_setting("mfood.login.password_md5"):
                errors.append("mFood 密码未配置（需 mFood 登录设置中的密码 MD5）")
            
            from .runner import TASK_FILE_MAP
            files = TASK_FILE_MAP.get(task_id, [])
            for f in files:
                if not has_setting(f"file:{f}"):
                    errors.append(f"对应的技能配置文件未上传（key: file:{f}）")

        elif task_id == "shence.order_reconcile":
            if not has_setting_or_env("mfood.login.account", "MFOOD_ACCOUNT"):
                errors.append("mFood 账号未配置（需 MFOOD_ACCOUNT 环境变量或 mFood 登录设置中的账号）")
            if not has_setting("mfood.login.password_md5"):
                errors.append("mFood 密码未配置（需 mFood 登录设置中的密码 MD5）")
            if not has_setting("mfood.shence.sensors_api_key"):
                errors.append("神策 API Key 未配置")
            if not has_setting("mfood.shence.sensors_project"):
                errors.append("神策项目未配置")

        elif task_id == "facebook.yesterday_summary":
            if not has_setting("file:state/facebook/fb_groups.json"):
                errors.append("Facebook 群组配置文件未上传（key: file:state/facebook/fb_groups.json）")

        return errors

    def list_agent_runs(self, agent_id: str, limit: int | None = 10, offset: int | None = 0) -> dict[str, Any]:
        tasks = [task for task in list_tasks() if task.group == agent_id]
        if not tasks:
            raise KeyError(f"Unknown task group: {agent_id}")
        task_names = {}
        for task in tasks:
            schedule = self.get_task_schedule(task)
            custom_name = schedule.get("name", "")
            task_names[task.id] = custom_name if custom_name else task.name
        
        has_next = False
        if limit is not None:
            runs = self.db.get_runs_for_task_ids([task.id for task in tasks], limit=limit + 1, offset=offset)
            if len(runs) > limit:
                has_next = True
                runs = runs[:limit]
        else:
            runs = self.db.get_runs_for_task_ids([task.id for task in tasks], limit=limit, offset=offset)
            
        for run in runs:
            run["task_name"] = task_names.get(run["task_id"], run["task_id"])
        return {
            "task_group": agent_id,
            "limit": limit,
            "offset": offset,
            "has_next": has_next,
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

    def delete_run(self, run_id: int) -> None:
        self.db.delete_run(run_id)

    def task_due_key(self, task: TaskDefinition, now: datetime) -> str:
        return due_key(task, self.get_task_schedule(task), now)

    def run_task(self, task_id: str, trigger_type: str = "manual", send_to_telegram: bool = False) -> dict[str, Any]:
        task = get_task(task_id)
        return self.runner.run(task, trigger_type=trigger_type, send_to_telegram=send_to_telegram)

    def resolve_task_for_chat_id(self, chat_id: str) -> TaskDefinition:
        clean_chat_id = str(chat_id or "").strip()
        matches = []
        for task in list_tasks():
            if self.db.get_setting(f"task.{task.id}.telegram_chat_id", "").strip() == clean_chat_id:
                matches.append(task)
        if not matches:
            raise KeyError(f"Unknown task chat mapping: {clean_chat_id}")
        if len(matches) > 1:
            raise ValueError(f"Multiple tasks mapped to chat_id {clean_chat_id}")
        return matches[0]

    def get_ai_settings(self) -> dict[str, Any]:
        return AiSettings.load_public(self.db)

    def save_ai_settings(self, payload: dict[str, Any]) -> dict[str, Any]:
        AiSettings.save(self.db, payload)
        return self.get_ai_settings()

    def test_ai_settings(self, payload: dict[str, Any]) -> dict[str, Any]:
        return test_deepseek_settings(self.db, payload)

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
        if AiSettings.load_private(self.db)["enabled"]:
            self.ai_dispatcher.process_pending(limit=20)
        status = self.telegram_listener.status()
        status["poll"] = result
        return status

    def list_ai_jobs(self, limit: int = 50) -> list[dict[str, Any]]:
        return self.db.list_ai_jobs(limit=limit)

    def retry_ai_job(self, job_id: int) -> dict[str, Any]:
        return self.ai_dispatcher.retry_job(job_id)

    def get_mfood_settings(self) -> dict[str, Any]:
        settings = MFoodSettings.load_public(self.db)
        token = self.db.get_setting("mfood.login.token", "")
        settings["login"]["token_configured"] = bool(token)
        settings["login"]["token"] = mask_secret(token) if token else ""
        return settings

    def save_mfood_settings(self, payload: dict[str, Any]) -> dict[str, Any]:
        MFoodSettings.save(self.db, payload)
        return self.get_mfood_settings()

    def check_mfood_token(self) -> dict[str, Any]:
        from .mfood.login import MFoodLogin
        token = self.db.get_setting("mfood.login.token", "")
        if not token:
            return {"ok": False, "status": "未配置 Token"}
        login_handler = MFoodLogin(self.db, self.project_root)
        ok, message = login_handler.validate_token(token)
        return {"ok": ok, "status": message}

    def login_mfood(self) -> dict[str, Any]:
        from .mfood.login import MFoodLogin
        login_handler = MFoodLogin(self.db, self.project_root)
        try:
            res = login_handler.get_token(force_refresh=True)
            return {"ok": True, "token": mask_secret(res.get("token", ""))}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def save_agent_order(self, order: list[str]) -> None:
        from .tasks.registry import list_tasks
        valid_groups = {task.group for task in list_tasks()}
        clean_order = [g for g in order if g in valid_groups]
        self.db.set_setting("agent.order", ",".join(clean_order))

    def save_task_order(self, agent_id: str, order: list[str]) -> None:
        from .tasks.registry import list_tasks
        valid_tasks = {task.id for task in list_tasks() if task.group == agent_id}
        clean_order = [t for t in order if t in valid_tasks]
        self.db.set_setting(f"task.order.{agent_id}", ",".join(clean_order))



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


def _serialize_workflow_steps(task: TaskDefinition) -> list[dict[str, str]]:
    return [{"title": step.title, "detail": step.detail} for step in task.workflow_steps]
