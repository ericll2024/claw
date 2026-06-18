import json

from traeclaw.db import AppDatabase
from traeclaw.runner import TaskRunner
from traeclaw.tasks.registry import TaskDefinition
from traeclaw.telegram import TelegramConfig, TelegramNotifier


def test_runner_records_successful_command(tmp_path):
    db = AppDatabase(tmp_path / "app.sqlite3")
    db.initialize()
    task = TaskDefinition(
        id="test.echo",
        name="Echo",
        group="test",
        description="",
        schedule_label="手动触发",
        command=["python3", "-c", "print('hello task')"],
    )

    result = TaskRunner(db, project_root=tmp_path).run(task, trigger_type="manual")

    assert result["status"] == "success"
    latest = db.get_latest_run("test.echo")
    assert latest["stdout"].strip() == "hello task"
    assert latest["summary"] == "hello task"


def test_runner_records_failed_command(tmp_path):
    db = AppDatabase(tmp_path / "app.sqlite3")
    db.initialize()
    task = TaskDefinition(
        id="test.fail",
        name="Fail",
        group="test",
        description="",
        schedule_label="手动触发",
        command=["python3", "-c", "import sys; print('bad', file=sys.stderr); sys.exit(7)"],
    )

    result = TaskRunner(db, project_root=tmp_path).run(task, trigger_type="manual")

    assert result["status"] == "failed"
    latest = db.get_latest_run("test.fail")
    assert latest["exit_code"] == 7
    assert "bad" in latest["stderr"]


def test_telegram_config_saved_from_web_form(tmp_path):
    db = AppDatabase(tmp_path / "app.sqlite3")
    db.initialize()

    TelegramConfig.save(db, enabled=True, bot_token="123456:secret-token", chat_id="-1001")
    public = TelegramConfig.load_public(db)

    assert public["enabled"] is True
    assert public["chat_id"] == "-1001"
    assert public["bot_token"] == "************oken"
    assert public["configured"] is True


def test_telegram_notifier_builds_send_message_request():
    calls = []

    def fake_post(url, payload, timeout):
        calls.append((url, payload, timeout))
        return {"ok": True, "result": {"message_id": 1}}

    notifier = TelegramNotifier(
        bot_token="123456:secret-token",
        chat_id="-1001",
        post_json=fake_post,
    )

    response = notifier.send_message("任务完成")

    assert response["ok"] is True
    assert calls[0][0] == "https://api.telegram.org/bot123456:secret-token/sendMessage"
    assert calls[0][1]["chat_id"] == "-1001"
    assert calls[0][1]["text"] == "任务完成"


def test_runner_sends_telegram_with_summary(tmp_path, monkeypatch):
    from unittest.mock import MagicMock
    from traeclaw.telegram import TelegramConfig, TelegramNotifier

    db = AppDatabase(tmp_path / "app.sqlite3")
    db.initialize()

    # 1. Setup global Telegram config
    TelegramConfig.save(db, enabled=True, bot_token="global-bot-token", chat_id="global-chat-id")

    # 2. Setup task-specific Chat ID
    task_id = "test.custom_notify"
    db.set_setting(f"task.{task_id}.telegram_chat_id", "custom-chat-id-123")

    task = TaskDefinition(
        id=task_id,
        name="Custom Notify Task",
        group="test",
        description="",
        schedule_label="手动触发",
        command=["python3", "-c", "print('output text')"],
    )

    notifier_calls = []

    def mock_init(self, bot_token, chat_id, post_json=None):
        self.bot_token = bot_token
        self.chat_id = chat_id
        notifier_calls.append((bot_token, chat_id))

    monkeypatch.setattr(TelegramNotifier, "__init__", mock_init)
    
    mock_send = MagicMock()
    monkeypatch.setattr(TelegramNotifier, "send_message", mock_send)

    # 3. Run task
    result = TaskRunner(db, project_root=tmp_path).run(task, trigger_type="manual", send_to_telegram=True)

    assert result["status"] == "success"

    # 4. Verify message content and targeted chat_id
    mock_send.assert_called_once()
    args, _ = mock_send.call_args
    sent_text = args[0]
    
    assert sent_text == "output text"

    assert len(notifier_calls) == 1
    assert notifier_calls[0][0] == "global-bot-token"
    assert notifier_calls[0][1] == "custom-chat-id-123"


def test_task_runner_config_sync(tmp_path):
    db = AppDatabase(tmp_path / "app.sqlite3")
    db.initialize()

    # Put a mock config into the database
    config_rel_path = "code/state/facebook/fb_groups.json"
    mock_config_content = '{"groups": [123, 456]}'
    db.set_setting(f"file:{config_rel_path}", mock_config_content)

    cmd = [
        "python3",
        "-c",
        f"import pathlib; p = pathlib.Path({config_rel_path!r}); print('exists:', p.exists()); print('content:', p.read_text() if p.exists() else ''); p.write_text('{{\"groups\": [123, 456, 789]}}')",
    ]

    task = TaskDefinition(
        id="facebook.yesterday_summary",
        name="Mock FB Summary",
        group="facebook",
        description="",
        schedule_label="手动触发",
        command=cmd,
    )

    runner = TaskRunner(db, project_root=tmp_path)
    result = runner.run(task, trigger_type="manual")

    # Verify execution output
    latest_run = db.get_latest_run(task.id)
    assert "exists: True" in latest_run["stdout"]
    assert mock_config_content in latest_run["stdout"]

    # Verify that the file was deleted from disk
    assert not (tmp_path / config_rel_path).exists()
    # Verify parent directory was cleaned up recursively
    assert not (tmp_path / "code" / "state" / "facebook").exists()

    # Verify that the updated config was saved back to the database
    updated_content = db.get_setting(f"file:{config_rel_path}")
    assert updated_content == '{"groups": [123, 456, 789]}'


