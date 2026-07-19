import json
from unittest.mock import MagicMock
from traeclaw.db import AppDatabase
from traeclaw.mfood.token_check import MFoodTokenCheck
from traeclaw.mfood.config import MFoodSettings

def test_mfood_token_check_valid(tmp_path, monkeypatch):
    db = AppDatabase(tmp_path / "app.sqlite3")
    db.initialize()

    # 1. Setup settings
    MFoodSettings.save(
        db,
        {
            "login": {
                "profile": "default",
                "account": "manager-a",
                "password_md5": "0123456789abcdef0123456789abcdef",
            }
        }
    )
    db.set_setting("mfood.login.token", "existing-valid-token")

    # 2. Mock MFoodLogin
    mock_login_instance = MagicMock()
    # When validate_token is called, return (True, "manager-a")
    mock_login_instance.validate_token.return_value = (True, "manager-a")
    
    # We patch MFoodLogin in token_check
    import traeclaw.mfood.token_check
    monkeypatch.setattr(traeclaw.mfood.token_check, "MFoodLogin", lambda db, root: mock_login_instance)

    checker = MFoodTokenCheck(db, tmp_path)
    res = checker.run()

    assert res["ok"] is True
    assert res["status"] == "valid"
    assert "Token 有效" in res["message"]
    
    # Verify last check time is saved
    last_check_time = db.get_setting("mfood.login.last_check_time")
    assert last_check_time != ""
    assert res["checked_at"] == last_check_time


def test_mfood_token_check_invalid_relogin_success(tmp_path, monkeypatch):
    db = AppDatabase(tmp_path / "app.sqlite3")
    db.initialize()

    # Setup settings
    MFoodSettings.save(
        db,
        {
            "login": {
                "profile": "default",
                "account": "manager-a",
                "password_md5": "0123456789abcdef0123456789abcdef",
            }
        }
    )
    db.set_setting("mfood.login.token", "expired-token")

    # Mock MFoodLogin
    mock_login_instance = MagicMock()
    # First token validation fails
    mock_login_instance.validate_token.return_value = (False, "Token expired")
    # Relogin succeeds
    mock_login_instance.get_token.return_value = {"token": "new-valid-token"}

    import traeclaw.mfood.token_check
    monkeypatch.setattr(traeclaw.mfood.token_check, "MFoodLogin", lambda db, root: mock_login_instance)

    checker = MFoodTokenCheck(db, tmp_path)
    res = checker.run()

    assert res["ok"] is True
    assert res["status"] == "relogged"
    assert "自动重新登录成功" in res["message"]
    mock_login_instance.get_token.assert_called_once_with(force_refresh=True)


def test_task_due_key_skips_recent_runs(tmp_path):
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from traeclaw.app import TraeclawApp
    from traeclaw.tasks.registry import get_task
    
    TZ = ZoneInfo("Asia/Shanghai")
    db = AppDatabase(tmp_path / "app.sqlite3")
    db.initialize()
    
    app = TraeclawApp(project_root=tmp_path, db=db, import_legacy_state=False)
    task = get_task("mfood.token_check")
    
    # 1. When there is no last run time, it should be due (returns a bucket string)
    now = datetime(2026, 7, 17, 14, 0, 0, tzinfo=TZ)
    due = app.task_due_key(task, now)
    assert due != ""
    
    # 2. When last run was 2 minutes ago, it should not be due (returns "")
    db.set_setting("mfood.login.last_check_time", "2026-07-17 13:58:00")
    assert app.task_due_key(task, now) == ""
    
    # 3. When last run was 5 minutes ago, it should be due
    db.set_setting("mfood.login.last_check_time", "2026-07-17 13:55:00")
    assert app.task_due_key(task, now) != ""


def test_custom_daily_schedule_default_times(tmp_path):
    from traeclaw.tasks.registry import get_task
    from traeclaw.schedule import default_schedule
    
    task = get_task("mfood.token_check")
    sched = default_schedule(task)
    
    # Verify times are generated correctly
    times = sched["times"]
    
    # 5:00 to 10:00 every 5 minutes:
    # 5:00, 5:05, ..., 9:55, 10:00
    assert "05:00" in times
    assert "05:05" in times
    assert "09:55" in times
    assert "10:00" in times
    # Other hours every 1 hour (e.g. 0:00, 4:00, 11:00, 23:00)
    assert "00:00" in times
    assert "04:00" in times
    assert "11:00" in times
    assert "23:00" in times
    
    # Should not have non-hourly times outside 5-10
    assert "11:05" not in times
    assert "04:05" not in times


def test_token_check_increments_consecutive_failures(tmp_path, monkeypatch):
    db = AppDatabase(tmp_path / "app.sqlite3")
    db.initialize()
    
    # Setup invalid token
    db.set_setting("mfood.login.token", "bad-token")
    
    # Mock MFoodLogin validation to fail, and get_token to raise Exception
    mock_login_instance = MagicMock()
    mock_login_instance.validate_token.return_value = (False, "Invalid")
    mock_login_instance.get_token.side_effect = Exception("Login server down")
    
    import traeclaw.mfood.token_check
    monkeypatch.setattr(traeclaw.mfood.token_check, "MFoodLogin", lambda db, root: mock_login_instance)
    
    checker = MFoodTokenCheck(db, tmp_path)
    
    # First failure
    res = checker.run()
    assert res["ok"] is False
    assert db.get_setting("mfood.login.consecutive_failures") == "1"
    
    # Second failure
    res = checker.run()
    assert db.get_setting("mfood.login.consecutive_failures") == "2"
    
    # Mock validation to succeed
    mock_login_instance.validate_token.return_value = (True, "manager-a")
    res = checker.run()
    assert res["ok"] is True
    # Should reset to 0
    assert db.get_setting("mfood.login.consecutive_failures") == "0"
