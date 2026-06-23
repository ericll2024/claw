import importlib
import json
from pathlib import Path

import pytest

from traeclaw.app import TraeclawApp
from traeclaw.db import AppDatabase
from traeclaw.tasks.registry import get_task


def _load_module(name: str):
    try:
        return importlib.import_module(name)
    except ImportError as exc:
        pytest.fail(str(exc))


def test_task_definitions_expose_ai_metadata():
    cp_task = get_task("cp.predict")

    assert cp_task.editable_paths
    assert cp_task.context_files
    assert cp_task.verify_commands
    assert cp_task.reply_name
    assert cp_task.workflow_steps
    assert "scripts/cp" in cp_task.editable_paths


def test_resolve_task_for_chat_id_requires_single_match(tmp_path):
    db = AppDatabase(tmp_path / "app.sqlite3")
    app = TraeclawApp(project_root=tmp_path, db=db, import_legacy_state=False)
    app.initialize()

    db.set_setting("task.cp.predict.telegram_chat_id", "-1001")
    db.set_setting("task.cp.check_result.telegram_chat_id", "-1002")

    resolved = app.resolve_task_for_chat_id("-1001")
    assert resolved.id == "cp.predict"

    db.set_setting("task.cp.check_result.telegram_chat_id", "-1001")
    try:
        app.resolve_task_for_chat_id("-1001")
    except ValueError as exc:
        assert "multiple" in str(exc).lower()
    else:
        raise AssertionError("Expected duplicate chat mapping to raise ValueError")


def test_context_manager_compacts_old_messages_into_summary(tmp_path):
    context_module = _load_module("traeclaw.ai_context")
    db = AppDatabase(tmp_path / "app.sqlite3")
    db.initialize()
    manager = context_module.AiContextManager(db)

    session = manager.get_or_create_session("cp.predict", "-1001", None)
    for index in range(8):
        manager.add_message(
            session["id"],
            "user" if index % 2 == 0 else "assistant",
            f"message {index}",
            update_id=index + 1 if index % 2 == 0 else None,
        )

    context = manager.build_context(session["id"], current_text="请继续修改")

    assert len(context["recent_messages"]) == 6
    assert "message 0" not in [item["message_text"] for item in context["recent_messages"]]
    assert "用户目标" in context["session_summary"]


def test_context_manager_builds_task_context_packet_with_group_summaries(tmp_path):
    context_module = _load_module("traeclaw.ai_context")
    db = AppDatabase(tmp_path / "app.sqlite3")
    app = TraeclawApp(project_root=tmp_path, db=db, import_legacy_state=False)
    app.initialize()

    db.set_setting("task.cp.predict.telegram_chat_id", "-1001")
    run_id = db.start_run("cp.predict", "manual")
    db.finish_run(run_id, "success", 0, "stdout", "", "cp latest run")

    manager = context_module.AiContextManager(db)
    session = manager.get_or_create_session("cp.predict", "-1001", None)
    context = manager.build_context(session["id"], current_text="列出这个群的任务", app=app)

    packet = context["task_context"]
    assert packet["current_task_detail"]["id"] == "cp.predict"
    assert packet["current_task_detail"]["work_path"] == "scripts/cp"
    assert packet["current_task_detail"]["workflow_steps"]
    assert packet["current_task_detail"]["latest_run"]["summary"] == "cp latest run"
    assert packet["group_task_summaries"]
    assert {item["id"] for item in packet["group_task_summaries"]} == {"cp.check_result"}
    assert packet["group_summary"]


def test_patch_executor_rejects_out_of_scope_edits(tmp_path):
    executor_module = _load_module("traeclaw.ai_executor")
    from traeclaw.tasks.registry import TaskDefinition

    task = TaskDefinition(
        id="test.ai.scope",
        name="AI Scope",
        group="test",
        description="",
        schedule_label="手动",
        command=["python3", "-c", "print('ok')"],
        editable_paths=("allowed",),
        context_files=("allowed/file.py",),
        verify_commands=(("python3", "-c", "print('verify ok')"),),
        reply_name="AI Scope",
    )

    executor = executor_module.AiPatchExecutor(tmp_path)
    result = executor.apply(task, {"summary": "", "reason": "", "reply": "", "edits": [{"path": "blocked/file.py", "content": "print(1)\n"}]})

    assert result["status"] == "failed"
    assert "allowed" in result["error"].lower()


def test_patch_executor_rolls_back_failed_verification(tmp_path):
    executor_module = _load_module("traeclaw.ai_executor")
    from traeclaw.tasks.registry import TaskDefinition

    target = tmp_path / "allowed" / "file.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("print('before')\n", encoding="utf-8")

    task = TaskDefinition(
        id="test.ai.rollback",
        name="AI Rollback",
        group="test",
        description="",
        schedule_label="手动",
        command=["python3", "-c", "print('ok')"],
        editable_paths=("allowed",),
        context_files=("allowed/file.py",),
        verify_commands=(("python3", "-c", "import sys; sys.exit(3)"),),
        reply_name="AI Rollback",
    )

    executor = executor_module.AiPatchExecutor(tmp_path)
    result = executor.apply(task, {"summary": "", "reason": "", "reply": "", "edits": [{"path": "allowed/file.py", "content": "print('after')\n"}]})

    assert result["status"] == "rolled_back"
    assert target.read_text(encoding="utf-8") == "print('before')\n"
    assert result["verification_status"] == "failed"


def test_extract_json_payload_from_markdown_block():
    provider_module = _load_module("traeclaw.ai_provider")

    payload = provider_module.extract_json_payload(
        "```json\n{\"summary\":\"ok\",\"reason\":\"fine\",\"reply\":\"done\",\"edits\":[]}\n```"
    )

    assert payload["summary"] == "ok"
    assert payload["reply"] == "done"


def test_gemini_cli_provider_appends_prompt_flag(monkeypatch):
    provider_module = _load_module("traeclaw.ai_provider")
    calls = []

    class Result:
        returncode = 0
        stdout = "{\"summary\":\"ok\",\"reason\":\"fine\",\"reply\":\"done\",\"edits\":[]}"
        stderr = ""

    def fake_run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        return Result()

    monkeypatch.setattr(provider_module.subprocess, "run", fake_run)

    provider = provider_module.GeminiCliProvider(command="gemini")
    payload = provider.generate("change the file")

    assert payload["summary"] == "ok"
    assert calls[0][0][-2:] == ["-p", "change the file"]


def test_dispatcher_processes_mention_into_ai_job_and_replies(tmp_path, monkeypatch):
    dispatcher_module = _load_module("traeclaw.ai_dispatcher")
    from traeclaw.tasks.registry import TaskDefinition

    db = AppDatabase(tmp_path / "app.sqlite3")
    app = TraeclawApp(project_root=tmp_path, db=db, import_legacy_state=False)
    app.initialize()

    target = tmp_path / "allowed" / "task.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("print('before')\n", encoding="utf-8")
    db.set_setting("telegram.bot_token", "test-token", is_secret=True)
    db.set_setting("task.test.ai.telegram_chat_id", "-1001")

    task = TaskDefinition(
        id="test.ai",
        name="Test AI",
        group="test",
        description="",
        schedule_label="手动",
        command=["python3", "-c", "print('ok')"],
        editable_paths=("allowed",),
        context_files=("allowed/task.py",),
        verify_commands=(("python3", "-c", "print('verify ok')"),),
        reply_name="Test AI",
    )

    replies = []

    class FakeProvider:
        def generate(self, prompt: str):
            return {
                "summary": "updated",
                "reason": "requested change",
                "reply": "已完成修改",
                "edits": [{"path": "allowed/task.py", "content": "print('after')\n"}],
            }

    monkeypatch.setattr(app, "resolve_task_for_chat_id", lambda chat_id: task)
    monkeypatch.setattr(app, "run_task", lambda task_id, trigger_type="manual", send_to_telegram=False: {"task_id": task_id, "status": "success", "summary": "task rerun ok"})

    dispatcher = dispatcher_module.TelegramAiDispatcher(
        app=app,
        provider_factory=lambda provider_name: FakeProvider(),
        notifier=lambda chat_id, text, message_thread_id=None: replies.append((chat_id, text, message_thread_id)),
    )

    db.save_telegram_update(
        {
            "update_id": 101,
            "message_id": 55,
            "chat_id": "-1001",
            "chat_title": "AI Group",
            "message_thread_id": 9,
            "from_id": "u1",
            "from_name": "tester",
            "text": "@bot 请把输出改成 after",
            "is_mention": True,
            "received_at": "2026-06-22T00:00:00Z",
            "raw": {},
        }
    )

    processed = dispatcher.process_pending(limit=10)

    assert processed == 1
    assert target.read_text(encoding="utf-8") == "print('after')\n"
    assert len(replies) == 2
    assert "正在处理" in replies[0][1]
    assert "已完成修改" in replies[1][1]


def test_dispatcher_prompt_includes_task_context_packet(tmp_path):
    dispatcher_module = _load_module("traeclaw.ai_dispatcher")

    db = AppDatabase(tmp_path / "app.sqlite3")
    app = TraeclawApp(project_root=tmp_path, db=db, import_legacy_state=False)
    app.initialize()
    db.set_setting("task.cp.predict.telegram_chat_id", "-1001")

    session = db.get_or_create_ai_session("cp.predict", "-1001", None)
    dispatcher = dispatcher_module.TelegramAiDispatcher(app=app)
    prompt = dispatcher._build_prompt(get_task("cp.predict"), session["id"], "查看任务状态")
    payload = json.loads(prompt)

    assert payload["task_context"]["current_task_detail"]["id"] == "cp.predict"
    assert payload["task_context"]["current_task_detail"]["workflow_steps"]
    assert payload["task_context"]["current_task_detail"]["work_path"] == "scripts/cp"
    assert {item["id"] for item in payload["task_context"]["group_task_summaries"]} == {"cp.check_result"}


def test_dispatcher_reset_command_clears_context(tmp_path):
    dispatcher_module = _load_module("traeclaw.ai_dispatcher")

    db = AppDatabase(tmp_path / "app.sqlite3")
    app = TraeclawApp(project_root=tmp_path, db=db, import_legacy_state=False)
    app.initialize()
    db.set_setting("telegram.bot_token", "test-token", is_secret=True)
    db.set_setting("task.cp.predict.telegram_chat_id", "-1001")

    context_module = _load_module("traeclaw.ai_context")
    manager = context_module.AiContextManager(db)
    session = manager.get_or_create_session("cp.predict", "-1001", None)
    manager.add_message(session["id"], "user", "old message", update_id=1)
    manager.add_message(session["id"], "assistant", "old reply")

    replies = []
    dispatcher = dispatcher_module.TelegramAiDispatcher(
        app=app,
        provider_factory=lambda provider_name: None,
        notifier=lambda chat_id, text, message_thread_id=None: replies.append(text),
    )
    db.save_telegram_update(
        {
            "update_id": 102,
            "message_id": 56,
            "chat_id": "-1001",
            "chat_title": "AI Group",
            "from_id": "u1",
            "from_name": "tester",
            "text": "@bot reset",
            "is_mention": True,
            "received_at": "2026-06-22T00:05:00Z",
            "raw": {},
        }
    )

    processed = dispatcher.process_pending(limit=10)
    context = manager.build_context(session["id"], current_text="")

    assert processed == 1
    assert context["recent_messages"] == []
    assert replies and "重置" in replies[0]


def test_dispatcher_status_and_tasks_commands_are_read_only(tmp_path):
    dispatcher_module = _load_module("traeclaw.ai_dispatcher")

    db = AppDatabase(tmp_path / "app.sqlite3")
    app = TraeclawApp(project_root=tmp_path, db=db, import_legacy_state=False)
    app.initialize()
    db.set_setting("task.cp.predict.telegram_chat_id", "-1001")

    run_id = db.start_run("cp.predict", "manual")
    db.finish_run(run_id, "success", 0, "", "", "cp latest run")
    session = db.get_or_create_ai_session("cp.predict", "-1001", None)
    db.create_ai_job(session["id"], 501, "cp.predict", "deepseek", "rerun_success", "old request")

    replies = []
    dispatcher = dispatcher_module.TelegramAiDispatcher(
        app=app,
        provider_factory=lambda provider_name: None,
        notifier=lambda chat_id, text, message_thread_id=None: replies.append(text),
    )

    db.save_telegram_update(
        {
            "update_id": 103,
            "message_id": 57,
            "chat_id": "-1001",
            "chat_title": "AI Group",
            "from_id": "u1",
            "from_name": "tester",
            "text": "@bot status",
            "is_mention": True,
            "received_at": "2026-06-22T00:06:00Z",
            "raw": {},
        }
    )
    db.save_telegram_update(
        {
            "update_id": 104,
            "message_id": 58,
            "chat_id": "-1001",
            "chat_title": "AI Group",
            "from_id": "u1",
            "from_name": "tester",
            "text": "@bot tasks",
            "is_mention": True,
            "received_at": "2026-06-22T00:07:00Z",
            "raw": {},
        }
    )

    processed = dispatcher.process_pending(limit=10)

    assert processed == 2
    assert len(db.list_ai_jobs(limit=10, session_id=session["id"])) == 1
    assert "当前任务" in replies[0]
    assert "最近作业" in replies[0]
    assert "任务列表" in replies[1]
    assert "CP 双色球推荐号码" in replies[1]
    assert "CP 拉取开奖并复盘" in replies[1]
