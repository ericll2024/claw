import json
import subprocess

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


def test_runner_retries_until_a_command_succeeds(tmp_path):
    db = AppDatabase(tmp_path / "app.sqlite3")
    db.initialize()
    task = TaskDefinition(
        id="test.retry_success",
        name="Retry",
        group="test",
        description="",
        schedule_label="手动触发",
        command=[
            "python3",
            "-c",
            "from pathlib import Path; import sys; p=Path('attempt'); n=int(p.read_text())+1 if p.exists() else 1; p.write_text(str(n)); sys.exit(0 if n == 3 else 1)",
        ],
    )

    result = TaskRunner(db, tmp_path).run(task, retry_count=2)

    assert result["status"] == "success"
    assert (tmp_path / "attempt").read_text() == "3"
    assert "Attempt 1/3" in db.get_latest_run(task.id)["stderr"]


def test_runner_stops_after_the_configured_retry_count(tmp_path):
    db = AppDatabase(tmp_path / "app.sqlite3")
    db.initialize()
    task = TaskDefinition(
        id="test.retry_exhausted",
        name="Retry",
        group="test",
        description="",
        schedule_label="手动触发",
        command=[
            "python3",
            "-c",
            "from pathlib import Path; import sys; p=Path('attempt'); n=int(p.read_text())+1 if p.exists() else 1; p.write_text(str(n)); sys.exit(9)",
        ],
    )

    result = TaskRunner(db, tmp_path).run(task, retry_count=2)

    assert result["status"] == "failed"
    assert (tmp_path / "attempt").read_text() == "3"


def test_runner_records_timeout_when_captured_output_is_bytes(tmp_path, monkeypatch):
    db = AppDatabase(tmp_path / "app.sqlite3")
    db.initialize()
    task = TaskDefinition(
        id="test.timeout",
        name="Timeout",
        group="test",
        description="",
        schedule_label="手动触发",
        command=["python3", "-c", "print('never reached')"],
        timeout_seconds=1,
    )

    def raise_timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(
            args[0],
            1,
            output="部分输出".encode("utf-8"),
            stderr="超时前错误".encode("utf-8"),
        )

    monkeypatch.setattr("traeclaw.runner.subprocess.run", raise_timeout)

    result = TaskRunner(db, project_root=tmp_path).run(task, trigger_type="manual")

    assert result["status"] == "failed"
    latest = db.get_latest_run(task.id)
    assert latest["status"] == "failed"
    assert latest["stdout"] == "部分输出"
    assert "超时前错误" in latest["stderr"]
    assert "Task timed out after 1s" in latest["stderr"]


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
    config_rel_path = "state/facebook/fb_groups.json"
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
    assert not (tmp_path / "state" / "facebook").exists()

    # Verify that the updated config was saved back to the database
    updated_content = db.get_setting(f"file:{config_rel_path}")
    assert updated_content == '{"groups": [123, 456, 789]}'


def test_only_alert_on_abnormal(tmp_path, monkeypatch):
    from unittest.mock import MagicMock
    from traeclaw.telegram import TelegramConfig, TelegramNotifier

    db = AppDatabase(tmp_path / "app.sqlite3")
    db.initialize()

    # 1. Setup global Telegram config
    TelegramConfig.save(db, enabled=True, bot_token="global-bot-token", chat_id="global-chat-id")

    task = TaskDefinition(
        id="test.alert_check",
        name="Alert Check Task",
        group="test",
        description="",
        schedule_label="手动触发",
        command=["python3", "-c", "print('output text')"],
    )

    mock_send = MagicMock()
    monkeypatch.setattr(TelegramNotifier, "send_message", mock_send)

    # Test Case 1: only_alert_on_abnormal is True (default), and task has no alert (success with normal text).
    # Expected: No Telegram message sent.
    db.set_setting(f"task.{task.id}.schedule", json.dumps({"only_alert_on_abnormal": True, "weekdays": [0,1,2,3,4,5,6], "times": ["12:00"], "mode": "long_term"}))
    result = TaskRunner(db, project_root=tmp_path).run(task, trigger_type="schedule")
    assert result["status"] == "success"
    assert result["notify_status"] == "skipped"
    mock_send.assert_not_called()

    # Test Case 2: only_alert_on_abnormal is True (default), but task has an alert (e.g. text contains "异常").
    # Expected: Telegram message sent.
    mock_send.reset_mock()
    task_alert = TaskDefinition(
        id="test.alert_check",
        name="Alert Check Task",
        group="test",
        description="",
        schedule_label="手动触发",
        command=["python3", "-c", "print('发生异常了')"],
    )
    result = TaskRunner(db, project_root=tmp_path).run(task_alert, trigger_type="schedule")
    assert result["status"] == "success"
    assert result["notify_status"] == "sent"
    mock_send.assert_called_once()

    # Test Case 3: only_alert_on_abnormal is False, and task has no alert.
    # Expected: Telegram message sent.
    mock_send.reset_mock()
    db.set_setting(f"task.{task.id}.schedule", json.dumps({"only_alert_on_abnormal": False, "weekdays": [0,1,2,3,4,5,6], "times": ["12:00"], "mode": "long_term"}))
    result = TaskRunner(db, project_root=tmp_path).run(task, trigger_type="schedule")
    assert result["status"] == "success"
    assert result["notify_status"] == "sent"
    mock_send.assert_called_once()


def test_mfood_maskphone_monitor_only_alert_on_threshold(tmp_path, monkeypatch):
    from unittest.mock import MagicMock
    from traeclaw.telegram import TelegramConfig, TelegramNotifier

    db = AppDatabase(tmp_path / "app.sqlite3")
    db.initialize()

    # Setup Telegram config
    TelegramConfig.save(db, enabled=True, bot_token="global-bot-token", chat_id="global-chat-id")

    task = TaskDefinition(
        id="mfood.maskphone_monitor",
        name="mFood 隐私号监控",
        group="mFood",
        description="",
        schedule_label="手动触发",
        command=["python3", "-c", "import json; print(json.dumps({'status': 'alert', 'message': '报警'}))"],
    )

    mock_send = MagicMock()
    monkeypatch.setattr(TelegramNotifier, "send_message", mock_send)

    # 1. Exceeds threshold (status='alert') -> notify
    runner = TaskRunner(db, project_root=tmp_path)
    result = runner.run(task, trigger_type="schedule")
    assert result["status"] == "success"
    assert result["notify_status"] == "sent"
    mock_send.assert_called_once()

    # 2. Does not exceed threshold (status='ok') -> skip
    mock_send.reset_mock()
    task_ok = TaskDefinition(
        id="mfood.maskphone_monitor",
        name="mFood 隐私号监控",
        group="mFood",
        description="",
        schedule_label="手动触发",
        command=["python3", "-c", "import json; print(json.dumps({'status': 'ok', 'message': '正常'}))"],
    )
    result = runner.run(task_ok, trigger_type="schedule")
    assert result["status"] == "success"
    assert result["notify_status"] == "skipped"
    mock_send.assert_not_called()

    # 3. Failed command -> skip (since it's not a threshold exceed event)
    mock_send.reset_mock()
    task_fail = TaskDefinition(
        id="mfood.maskphone_monitor",
        name="mFood 隐私号监控",
        group="mFood",
        description="",
        schedule_label="手动触发",
        command=["python3", "-c", "import sys; sys.exit(1)"],
    )
    result = runner.run(task_fail, trigger_type="schedule")
    assert result["status"] == "failed"
    assert result["notify_status"] == "skipped"
    mock_send.assert_not_called()

