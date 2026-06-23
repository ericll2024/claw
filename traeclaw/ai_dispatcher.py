from __future__ import annotations

import hashlib
import json
import threading
from pathlib import Path
from typing import Any, Callable

from .ai import AiSettings
from .ai_context import AiContextManager
from .ai_executor import AiPatchExecutor
from .ai_provider import DeepSeekProvider, GeminiCliProvider
from .telegram import TelegramConfig, TelegramNotifier


class TelegramAiDispatcher:
    def __init__(
        self,
        app,
        provider_factory: Callable[[str], Any] | None = None,
        notifier: Callable[[str, str, int | None], None] | None = None,
        poll_interval: float = 3.0,
    ):
        self.app = app
        self.db = app.db
        self.provider_factory = provider_factory or self._make_provider
        self.notifier = notifier or self._send_telegram_message
        self.context_manager = AiContextManager(self.db)
        self.executor = AiPatchExecutor(app.project_root)
        self.poll_interval = poll_interval
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self.is_running():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, name="telegram-ai-dispatcher", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=2)

    def is_running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def process_pending(self, limit: int = 20) -> int:
        processed = 0
        for update in self.db.list_pending_telegram_mentions(limit=limit):
            self._process_update(update)
            processed += 1
        return processed

    def retry_job(self, job_id: int) -> dict[str, Any]:
        job = self.db.get_ai_job(job_id)
        if not job:
            raise KeyError(f"Unknown AI job: {job_id}")
        task = self.app.resolve_task_for_chat_id(self.db.get_ai_session(job["session_id"])["chat_id"])
        session = self.db.get_ai_session(job["session_id"])
        new_job_id = self.db.create_ai_job(
            job["session_id"],
            None,
            task.id,
            job["provider"],
            "queued",
            job["request_text"],
        )
        self._run_ai_job(
            job_id=new_job_id,
            task=task,
            session=session,
            request_text=job["request_text"],
            chat_id=session["chat_id"],
            message_thread_id=session.get("message_thread_id"),
        )
        return self.db.get_ai_job(new_job_id) or {}

    def _run_loop(self) -> None:
        while not self._stop_event.wait(self.poll_interval):
            try:
                self.process_pending(limit=20)
            except Exception:
                continue

    def _process_update(self, update: dict[str, Any]) -> None:
        chat_id = str(update["chat_id"])
        message_thread_id = update.get("message_thread_id")
        clean_text = self._normalize_text(update.get("text") or "")
        try:
            task = self.app.resolve_task_for_chat_id(chat_id)
        except Exception as exc:
            self.db.create_ai_job(None, update["update_id"], "__unresolved__", "", "failed", clean_text)
            self.notifier(chat_id, f"无法定位任务: {exc}", message_thread_id)
            return

        session = self.context_manager.get_or_create_session(task.id, chat_id, message_thread_id)
        command = clean_text.strip().lower()
        if command == "reset":
            self.context_manager.reset_session(session["id"])
            self.notifier(chat_id, f"{task.reply_name} 会话已重置", message_thread_id)
            return
        if command == "status":
            self.notifier(chat_id, self._build_status_reply(task, session["id"], chat_id), message_thread_id)
            return
        if command == "tasks":
            self.notifier(chat_id, self._build_tasks_reply(task, chat_id), message_thread_id)
            return

        self.context_manager.add_message(session["id"], "user", clean_text, update_id=update["update_id"])
        if self.db.find_running_ai_job(task.id):
            self.notifier(chat_id, "正在处理中，请稍后", message_thread_id)
            return

        provider_name = self._choose_provider_name()
        job_id = self.db.create_ai_job(session["id"], update["update_id"], task.id, provider_name, "queued", clean_text)
        self.notifier(chat_id, f"已收到，正在处理 {task.reply_name}", message_thread_id)
        self._run_ai_job(job_id, task, session, clean_text, chat_id, message_thread_id)

    def _run_ai_job(
        self,
        job_id: int,
        task,
        session: dict[str, Any],
        request_text: str,
        chat_id: str,
        message_thread_id: int | None,
    ) -> None:
        self.db.update_ai_job(job_id, status="running")
        try:
            provider_name = self.db.get_ai_job(job_id)["provider"]
            provider = self.provider_factory(provider_name)
            prompt = self._build_prompt(task, session["id"], request_text, provider_name=provider_name)
            payload = provider.generate(prompt)
            patch_result = self.executor.apply(task, payload)
            reply_text = self._build_reply(payload, patch_result, None)
            final_status = "failed"
            files_touched = patch_result["files_touched"]

            if patch_result["status"] == "success":
                run_result = self.app.run_task(task.id, trigger_type="ai")
                if run_result.get("status") == "success":
                    final_status = "rerun_success"
                else:
                    self.executor.rollback(patch_result["backups"])
                    patch_result["status"] = "rolled_back"
                    final_status = "rolled_back"
                reply_text = self._build_reply(payload, patch_result, run_result)
            elif patch_result["status"] == "rolled_back":
                final_status = "rolled_back"
            else:
                final_status = "failed"

            self.db.update_ai_job(
                job_id,
                status=final_status,
                files_touched=files_touched,
                verification_status=patch_result["verification_status"],
                verification_output=patch_result["verification_output"],
                reply_text=reply_text,
            )
        except Exception as exc:
            reply_text = f"AI 处理失败: {exc}"
            self.db.update_ai_job(
                job_id,
                status="failed",
                files_touched=[],
                verification_status="failed",
                verification_output=str(exc),
                reply_text=reply_text,
            )
        self.context_manager.add_message(session["id"], "assistant", reply_text)
        self.notifier(chat_id, reply_text, message_thread_id)

    def _build_prompt(self, task, session_id: int, request_text: str, provider_name: str = "") -> str:
        context = self.context_manager.build_context(session_id, request_text, app=self.app, task=task)
        file_sections = []
        for rel_path in task.context_files:
            target = Path(self.app.project_root) / rel_path
            content = ""
            if target.exists():
                content = target.read_text(encoding="utf-8")
            else:
                content = self.db.get_setting(f"file:{rel_path}", "")
            if content:
                file_sections.append(f"[{rel_path}]\n{content[:4000]}")
        latest_run = self.db.get_latest_run(task.id) or {}
        task_context = context.get("task_context") or {}
        context_hash = self._context_snapshot_hash(task_context)
        self.db.update_ai_session_state(
            session_id,
            provider_model=self._provider_model(provider_name),
            context_snapshot_hash=context_hash,
        )
        prompt = {
            "task": task.reply_name or task.name,
            "request_text": request_text,
            "allowed_paths": list(task.editable_paths),
            "session_summary": context["session_summary"],
            "recent_messages": [
                {"role": item["role"], "text": item["message_text"]}
                for item in context["recent_messages"]
            ],
            "task_context": task_context,
            "recent_job_summaries": [
                {
                    "status": item["status"],
                    "files_touched": item["files_touched"],
                    "reply_text": item["reply_text"][:300],
                    "verification_status": item["verification_status"],
                }
                for item in context["recent_jobs"]
            ],
            "latest_run_summary": latest_run.get("summary", ""),
            "context_files": file_sections,
            "format": {
                "summary": "string",
                "reason": "string",
                "reply": "string",
                "edits": [{"path": "relative path", "content": "new full content"}],
            },
        }
        return json.dumps(prompt, ensure_ascii=False)

    def _build_reply(self, payload: dict[str, Any], patch_result: dict[str, Any], run_result: dict[str, Any] | None) -> str:
        parts = [str(payload.get("reply") or "处理完成").strip()]
        if patch_result["files_touched"]:
            parts.append(f"修改文件: {', '.join(patch_result['files_touched'])}")
        if patch_result["verification_status"]:
            label = "通过" if patch_result["verification_status"] == "passed" else "失败"
            parts.append(f"验证: {label}")
        if run_result is not None:
            parts.append(f"任务重跑: {'成功' if run_result.get('status') == 'success' else '失败'}")
            if run_result.get("summary"):
                parts.append(f"结果摘要: {run_result['summary']}")
        elif patch_result["status"] != "success" and patch_result["verification_output"]:
            parts.append(f"失败原因: {patch_result['verification_output'][:300]}")
        return "\n".join(part for part in parts if part)

    def _choose_provider_name(self) -> str:
        settings = AiSettings.load_private(self.db)
        provider = settings["default_provider"]
        if provider == "gemini" and settings["gemini_cli_enabled"]:
            return "gemini"
        return "deepseek"

    def _make_provider(self, provider_name: str):
        settings = AiSettings.load_private(self.db)
        if provider_name == "gemini":
            return GeminiCliProvider(settings["gemini_cli_command"])
        return DeepSeekProvider(
            settings["deepseek_api_base"] or "https://api.deepseek.com",
            settings["deepseek_api_key"],
            settings["deepseek_model"] or "deepseek-chat",
        )

    def _send_telegram_message(self, chat_id: str, text: str, message_thread_id: int | None = None) -> None:
        config = TelegramConfig.load_private(self.db)
        token = config.get("bot_token")
        if not token:
            return
        TelegramNotifier(token, chat_id).send_message(text, message_thread_id=message_thread_id)

    def _normalize_text(self, text: str) -> str:
        clean = (text or "").strip()
        if clean.startswith("@bot"):
            clean = clean[4:].strip()
        return clean

    def _build_status_reply(self, task, session_id: int, chat_id: str) -> str:
        context = self.context_manager.build_context(session_id, "", app=self.app)
        latest_job = (self.db.list_ai_jobs(limit=1, session_id=session_id) or [{}])[0]
        task_context = context.get("task_context") or {}
        current = task_context.get("current_task_detail") or {}
        return "\n".join(
            [
                f"当前任务: {current.get('name') or task.name}",
                f"工作路径: {current.get('work_path') or '-'}",
                f"计划: {current.get('schedule_label') or task.schedule_label}",
                f"最近运行: {(current.get('latest_run') or {}).get('summary') or '暂无'}",
                f"最近作业: {latest_job.get('status', '无')}",
                f"会话摘要: {context.get('session_summary') or '暂无摘要'}",
                f"分组摘要: {task_context.get('group_summary') or '暂无'}",
            ]
        )

    def _build_tasks_reply(self, task, chat_id: str) -> str:
        task_context = self.app.build_ai_task_context(task.id, chat_id)
        lines = [f"任务列表: {task_context.get('group_name') or task.group}"]
        current = task_context.get("current_task_detail") or {}
        current_status = (current.get("latest_run") or {}).get("status") or "未运行"
        lines.append(
            f"- {current.get('name') or task.name} | {current.get('schedule_label') or task.schedule_label} | {current_status}"
        )
        for item in task_context.get("group_task_summaries") or []:
            status = item.get("latest_run_status") or "未运行"
            lines.append(f"- {item['name']} | {item['schedule_label']} | {status}")
        return "\n".join(lines)

    def _provider_model(self, provider_name: str) -> str:
        settings = AiSettings.load_private(self.db)
        if provider_name == "gemini":
            return settings["gemini_cli_command"] or "gemini"
        return settings["deepseek_model"] or "deepseek-chat"

    def _context_snapshot_hash(self, task_context: dict[str, Any]) -> str:
        raw = json.dumps(task_context or {}, ensure_ascii=False, sort_keys=True)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()
