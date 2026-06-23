from __future__ import annotations

from typing import Any

from .db import AppDatabase


class AiContextManager:
    def __init__(self, db: AppDatabase):
        self.db = db

    def get_or_create_session(self, task_id: str, chat_id: str, message_thread_id: int | None) -> dict[str, Any]:
        return self.db.get_or_create_ai_session(task_id, chat_id, message_thread_id)

    def add_message(
        self,
        session_id: int,
        role: str,
        message_text: str,
        update_id: int | None = None,
        include_in_context: bool = True,
    ) -> int:
        message_id = self.db.add_ai_message(
            session_id,
            role,
            message_text,
            update_id=update_id,
            include_in_context=include_in_context,
        )
        self._compact_session(session_id)
        return message_id

    def reset_session(self, session_id: int) -> None:
        self.db.reset_ai_session_context(session_id)

    def build_context(
        self,
        session_id: int,
        current_text: str,
        app: Any | None = None,
        task: Any | None = None,
    ) -> dict[str, Any]:
        session = self.db.get_ai_session(session_id) or {}
        recent_messages = self.db.list_ai_messages(session_id, include_archived=False, limit=6)
        recent_jobs = self.db.list_ai_jobs(limit=3, session_id=session_id)
        task_context = {}
        if app and session:
            task_context = app.build_ai_task_context(task or session["task_id"], session["chat_id"])
        return {
            "session": session,
            "session_summary": session.get("session_summary", ""),
            "recent_messages": recent_messages,
            "recent_jobs": recent_jobs,
            "current_text": current_text,
            "task_context": task_context,
        }

    def _compact_session(self, session_id: int) -> None:
        messages = self.db.list_ai_messages(session_id, include_archived=False, limit=None)
        if len(messages) <= 6:
            return
        to_archive = messages[:-6]
        self.db.archive_ai_messages([item["id"] for item in to_archive])
        self.db.update_ai_session_summary(session_id, self._build_summary(session_id))

    def _build_summary(self, session_id: int) -> str:
        all_messages = self.db.list_ai_messages(session_id, include_archived=True, limit=None)
        recent_jobs = self.db.list_ai_jobs(limit=3, session_id=session_id)
        user_messages = [item["message_text"] for item in all_messages if item["role"] == "user" and item["message_text"].strip()]
        changed_files = []
        last_failure = ""
        for job in recent_jobs:
            changed_files.extend(job["files_touched"])
            if not last_failure and job["status"] in {"failed", "rolled_back"}:
                last_failure = job["reply_text"] or job["verification_output"]
        unique_files = []
        for path in changed_files:
            if path not in unique_files:
                unique_files.append(path)
        return "\n".join(
            [
                f"用户目标: {user_messages[0] if user_messages else ''}".strip(),
                f"已改文件: {', '.join(unique_files) if unique_files else '无'}",
                "当前约束: 仅允许编辑任务授权路径内的文件",
                f"最近失败原因: {last_failure[:200] if last_failure else '无'}",
                f"下一步待做: {user_messages[-1] if user_messages else ''}".strip(),
            ]
        ).strip()
