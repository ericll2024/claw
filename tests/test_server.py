import json
import threading
import urllib.request

from traeclaw.app import TraeclawApp
from traeclaw.db import AppDatabase
from traeclaw.server import make_server


def request_json(base_url, path, method="GET", payload=None, headers=None):
    data = None
    req_headers = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        req_headers["Content-Type"] = "application/json"
    if headers:
        req_headers.update(headers)
    req = urllib.request.Request(base_url + path, data=data, headers=req_headers, method=method)
    with urllib.request.urlopen(req, timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


def request_text(base_url, path):
    with urllib.request.urlopen(base_url + path, timeout=5) as response:
        return response.read().decode("utf-8")


def run_test_server(tmp_path):
    db = AppDatabase(tmp_path / "app.sqlite3")
    app = TraeclawApp(project_root=tmp_path, db=db, import_legacy_state=False)
    app.initialize()
    httpd = make_server(("127.0.0.1", 0), app)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    return httpd, f"http://127.0.0.1:{httpd.server_address[1]}"


def test_tasks_api_returns_registered_tasks_and_latest_run(tmp_path):
    httpd, base_url = run_test_server(tmp_path)
    try:
        payload = request_json(base_url, "/api/tasks")
    finally:
        httpd.shutdown()

    task_ids = {task["id"] for task in payload["tasks"]}
    assert "cp.predict" in task_ids
    cp_task = next(task for task in payload["tasks"] if task["id"] == "cp.predict")
    assert cp_task["schedule_label"] == "每天 18:00"
    assert "next_run_at" in cp_task
    assert cp_task["workflow_steps"]
    assert cp_task["work_path"] == "scripts/cp"


def test_index_page_shows_telegram_listener_status_slot(tmp_path):
    httpd, base_url = run_test_server(tmp_path)
    try:
        html = request_text(base_url, "/")
    finally:
        httpd.shutdown()

    assert 'id="telegramListenerStatus"' in html
    assert "Telegram" in html


def test_tasks_api_groups_tasks_by_folder_agent(tmp_path):
    httpd, base_url = run_test_server(tmp_path)
    try:
        payload = request_json(base_url, "/api/tasks")
    finally:
        httpd.shutdown()

    agents = {agent["id"]: agent for agent in payload["agents"]}
    assert "cp" in agents
    assert agents["cp"]["folder"] == "scripts/cp"
    assert agents["cp"]["task_count"] == 2
    assert [task["id"] for task in agents["cp"]["tasks"]] == ["cp.predict", "cp.check_result"]
    assert agents["cp"]["schedule_summary"] == "每天 18:00 / 每天 22:00"
    assert agents["mFood"]["folder"] == "scripts/mFood"
    assert agents["fb"]["folder"] == "scripts/fb"


def test_task_group_alias_api_changes_display_name(tmp_path):
    httpd, base_url = run_test_server(tmp_path)
    try:
        saved = request_json(
            base_url,
            "/api/task-groups/cp/alias",
            method="POST",
            payload={"alias": "彩票任务"},
        )
        payload = request_json(base_url, "/api/tasks")
        reset = request_json(
            base_url,
            "/api/task-groups/cp/alias",
            method="POST",
            payload={"alias": ""},
        )
    finally:
        httpd.shutdown()

    agents = {agent["id"]: agent for agent in payload["agents"]}
    assert saved["task"]["name"] == "彩票任务"
    assert agents["cp"]["name"] == "彩票任务"
    assert agents["cp"]["default_name"] == "cp"
    assert agents["cp"]["alias"] == "彩票任务"
    assert reset["task"]["name"] == "cp"


def test_task_schedule_api_overrides_default_schedule(tmp_path):
    httpd, base_url = run_test_server(tmp_path)
    try:
        saved = request_json(
            base_url,
            "/api/tasks/cp.predict/schedule",
            method="POST",
            payload={
                "mode": "long_term",
                "weekdays": [0, 2, 4],
                "times": ["08:30", "18:30"],
                "name": "Custom Task Name",
                "note": "Custom Task Note",
                "only_alert_on_abnormal": True,
            },
        )
        payload = request_json(base_url, "/api/tasks")
    finally:
        httpd.shutdown()

    task = next(item for item in payload["tasks"] if item["id"] == "cp.predict")
    assert saved["schedule"]["custom"] is True
    assert saved["schedule"]["times"] == ["08:30", "18:30"]
    assert saved["schedule"]["name"] == "Custom Task Name"
    assert saved["schedule"]["note"] == "Custom Task Note"
    assert saved["schedule"]["only_alert_on_abnormal"] is True
    assert task["schedule"]["custom"] is True
    assert task["name"] == "Custom Task Name"
    assert task["note"] == "Custom Task Note"
    assert task["schedule"]["only_alert_on_abnormal"] is True
    assert task["schedule_label"] == "长期 · 周一、周三、周五 · 08:30、18:30"


def test_task_group_runs_api_returns_recent_runs_with_limit(tmp_path):
    db = AppDatabase(tmp_path / "app.sqlite3")
    app = TraeclawApp(project_root=tmp_path, db=db, import_legacy_state=False)
    app.initialize()
    for task_id, summary in [
        ("cp.predict", "predict ok"),
        ("cp.check_result", "check ok"),
        ("mfood.order_monitor", "login ok"),
    ]:
        run_id = db.start_run(task_id, "manual")
        db.finish_run(run_id, "success", 0, "", "", summary)
    httpd = make_server(("127.0.0.1", 0), app)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{httpd.server_address[1]}"
    try:
        limited = request_json(base_url, "/api/task-groups/cp/runs?limit=1")
        all_runs = request_json(base_url, "/api/task-groups/cp/runs?limit=all")
    finally:
        httpd.shutdown()

    assert limited["task_group"] == "cp"
    assert limited["limit"] == 1
    assert len(limited["runs"]) == 1
    assert limited["runs"][0]["task_id"].startswith("cp.")
    assert "task_name" in limited["runs"][0]
    assert all_runs["limit"] is None
    assert len(all_runs["runs"]) == 2


def test_mfood_and_shence_tasks_surface_alert_label(tmp_path):
    db = AppDatabase(tmp_path / "app.sqlite3")
    app = TraeclawApp(project_root=tmp_path, db=db, import_legacy_state=False)
    app.initialize()
    mfood_run_id = db.start_run("mfood.maskphone_monitor", "manual")
    db.finish_run(
        mfood_run_id,
        "failed",
        1,
        '{"status":"alert","message":"报警: 超过阈值"}',
        "",
        "报警: 超过阈值",
        result_payload={"status": "alert", "message": "报警: 超过阈值"},
    )
    shence_run_id = db.start_run("shence.order_reconcile", "manual")
    db.finish_run(
        shence_run_id,
        "success",
        0,
        '{"status":"alert","takeouts":{"alert":true}}',
        "",
        "异常: 外卖差值=999",
        result_payload={"status": "alert", "takeouts": {"alert": True}},
    )

    cards = {task["id"]: task for task in app.list_task_cards()}

    assert cards["mfood.maskphone_monitor"]["alert"] is True
    assert cards["mfood.maskphone_monitor"]["alert_label"] == "警报"
    assert cards["shence.order_reconcile"]["alert"] is True
    assert cards["cp.predict"]["alert"] is False


def test_settings_page_is_served_by_clean_route(tmp_path):
    httpd, base_url = run_test_server(tmp_path)
    try:
        html = request_text(base_url, "/settings")
    finally:
        httpd.shutdown()

    assert "<h1>设置</h1>" in html
    assert 'src="/settings.js"' in html


def test_login_page_is_served_by_clean_route(tmp_path):
    # Copy login.html to the temp web directory so it can be served
    import shutil
    from pathlib import Path
    web_dir = tmp_path / "web"
    web_dir.mkdir(parents=True, exist_ok=True)
    src_login = Path(__file__).resolve().parents[1] / "web" / "login.html"
    shutil.copy(src_login, web_dir / "login.html")

    httpd, base_url = run_test_server(tmp_path)
    try:
        html = request_text(base_url, "/login")
    finally:
        httpd.shutdown()

    assert "<h1>claw</h1>" in html or "<h1>Traeclaw Lite</h1>" in html


def test_telegram_settings_api_round_trip(tmp_path):
    httpd, base_url = run_test_server(tmp_path)
    try:
        saved = request_json(
            base_url,
            "/api/settings/telegram",
            method="POST",
            payload={"enabled": True, "bot_token": "123456:secret-token", "chat_id": "-1001"},
        )
        loaded = request_json(base_url, "/api/settings/telegram")
        
        # 測試：當 bot_token 為空時保留原有 token，而當 chat_id 變更/清空時則進行更新
        saved_clear_chat = request_json(
            base_url,
            "/api/settings/telegram",
            method="POST",
            payload={"enabled": True, "bot_token": "", "chat_id": ""},
        )
        loaded_clear_chat = request_json(base_url, "/api/settings/telegram")
    finally:
        httpd.shutdown()

    assert saved["settings"]["configured"] is True
    assert loaded["settings"]["bot_token"] == "************oken"
    assert loaded["settings"]["chat_id"] == "-1001"
    
    assert saved_clear_chat["settings"]["bot_token"] == "************oken"  # 原 token 仍保留
    assert loaded_clear_chat["settings"]["chat_id"] == ""  # chat_id 被成功清空了


def test_ai_settings_api_round_trip(tmp_path):
    httpd, base_url = run_test_server(tmp_path)
    try:
        saved = request_json(
            base_url,
            "/api/settings/ai",
            method="POST",
            payload={
                "enabled": True,
                "default_provider": "deepseek",
                "deepseek_api_base": "https://api.deepseek.com",
                "deepseek_api_key": "deepseek-secret-key",
                "deepseek_model": "deepseek-chat",
                "gemini_cli_enabled": True,
                "gemini_cli_command": "gemini",
            },
        )
        loaded = request_json(base_url, "/api/settings/ai")
    finally:
        httpd.shutdown()

    assert saved["settings"]["enabled"] is True
    assert loaded["settings"]["default_provider"] == "deepseek"
    assert loaded["settings"]["deepseek_api_base"] == "https://api.deepseek.com"
    assert loaded["settings"]["deepseek_api_key"] == "************-key"
    assert loaded["settings"]["deepseek_api_key_configured"] is True
    assert loaded["settings"]["deepseek_model"] == "deepseek-chat"
    assert loaded["settings"]["gemini_cli_enabled"] is True
    assert loaded["settings"]["gemini_cli_command"] == "gemini"


def test_ai_jobs_api_lists_and_retries(tmp_path):
    db = AppDatabase(tmp_path / "app.sqlite3")
    app = TraeclawApp(project_root=tmp_path, db=db, import_legacy_state=False)
    app.initialize()
    session = db.get_or_create_ai_session("cp.predict", "-1001", None)
    job_id = db.create_ai_job(
        session["id"],
        301,
        "cp.predict",
        "deepseek",
        "failed",
        "请修一下",
    )
    db.update_ai_job(
        job_id,
        files_touched=["code/scripts/cp/cp_prediction_core.py"],
        verification_status="failed",
        verification_output="traceback",
        reply_text="失败了",
    )

    retried_jobs = []

    def fake_retry(target_job_id: int):
        retried_jobs.append(target_job_id)
        return {
            "id": 999,
            "task_id": "cp.predict",
            "status": "rerun_success",
            "provider": "deepseek",
        }

    app.retry_ai_job = fake_retry

    httpd = make_server(("127.0.0.1", 0), app)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{httpd.server_address[1]}"
    try:
        listed = request_json(base_url, "/api/telegram/ai-jobs")
        retried = request_json(
            base_url,
            f"/api/telegram/ai-jobs/{job_id}/retry",
            method="POST",
            payload={},
        )
    finally:
        httpd.shutdown()

    assert listed["jobs"][0]["task_id"] == "cp.predict"
    assert listed["jobs"][0]["files_touched"] == ["code/scripts/cp/cp_prediction_core.py"]
    assert retried_jobs == [job_id]
    assert retried["job"]["id"] == 999


def test_ai_settings_test_endpoint(tmp_path):
    db = AppDatabase(tmp_path / "app.sqlite3")
    app = TraeclawApp(project_root=tmp_path, db=db, import_legacy_state=False)
    app.initialize()

    called_payloads = []

    def fake_test(payload: dict):
        called_payloads.append(payload)
        return {
            "ok": True,
            "provider": "deepseek",
            "model": payload["deepseek_model"],
            "reply": "hi there",
        }

    app.test_ai_settings = fake_test

    httpd = make_server(("127.0.0.1", 0), app)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{httpd.server_address[1]}"
    try:
        tested = request_json(
            base_url,
            "/api/settings/ai/test",
            method="POST",
            payload={
                "deepseek_api_base": "https://api.deepseek.com",
                "deepseek_api_key": "secret",
                "deepseek_model": "deepseek-v4-flash",
            },
        )
    finally:
        httpd.shutdown()

    assert called_payloads[0]["deepseek_model"] == "deepseek-v4-flash"
    assert tested["result"]["ok"] is True
    assert tested["result"]["reply"] == "hi there"


def test_telegram_listener_api(tmp_path):
    httpd, base_url = run_test_server(tmp_path)
    try:
        # 首先配置 Token 以便能夠啟用監聽器
        request_json(
            base_url,
            "/api/settings/telegram",
            method="POST",
            payload={"enabled": True, "bot_token": "123456:fake-token-for-test", "chat_id": "-1001"},
        )
        # 獲取初始監聽狀態
        status = request_json(base_url, "/api/telegram/listener")
        assert status["listener"]["enabled"] is False

        # 啟用監聽
        saved = request_json(
            base_url,
            "/api/telegram/listener",
            method="POST",
            payload={"enabled": True},
        )
        assert saved["listener"]["enabled"] is True

        # 禁用監聽
        saved_disabled = request_json(
            base_url,
            "/api/telegram/listener",
            method="POST",
            payload={"enabled": False},
        )
        assert saved_disabled["listener"]["enabled"] is False
    finally:
        httpd.shutdown()


def test_mfood_settings_api_round_trip(tmp_path):
    httpd, base_url = run_test_server(tmp_path)
    try:
        saved = request_json(
            base_url,
            "/api/settings/mfood",
            method="POST",
            payload={
                "login": {
                    "profile": "default",
                    "account": "manager-a",
                    "password_md5": "0123456789abcdef0123456789abcdef",
                },
                "shence": {
                    "api_url": "https://shence-db-admin.mfoodapp.com",
                    "sensors_api_key": "sensors-secret-key",
                    "sensors_project": "production",
                },
                "order_monitor": {
                    "monitoring_dir": "/tmp/monitoring",
                    "manager_account": "manager-a",
                    "manager_password_md5": "abcdefabcdefabcdefabcdefabcdefab",
                    "sensors_api_key": "monitor-secret-key",
                    "sensors_project": "production",
                    "takeout_threshold": "300",
                    "market_threshold": "300",
                    "timezone": "Asia/Shanghai",
                },
            },
        )
        loaded = request_json(base_url, "/api/settings/mfood")
    finally:
        httpd.shutdown()

    assert saved["settings"]["login"]["configured"] is True
    assert loaded["settings"]["login"]["password_md5"] == "************cdef"
    assert loaded["settings"]["shence"]["sensors_project"] == "production"


def test_authentication(tmp_path):
    import urllib.error
    httpd, base_url = run_test_server(tmp_path)
    try:
        # 1. Access without auth header -> should succeed (because of test environment bypass)
        request_json(base_url, "/api/tasks")

        # 2. Access with force auth header -> should fail with 401
        try:
            request_json(base_url, "/api/tasks", headers={"X-Test-Force-Auth": "1"})
            assert False, "Should raise urllib.error.HTTPError for 401"
        except urllib.error.HTTPError as exc:
            assert exc.code == 401

        # 3. Log in with wrong password -> should fail with 401
        try:
            request_json(base_url, "/api/login", method="POST", payload={"password": "wrong_password"})
            assert False, "Should raise urllib.error.HTTPError for 401"
        except urllib.error.HTTPError as exc:
            assert exc.code == 401

        # 4. Log in with correct password (default hash value) -> should succeed
        res = request_json(base_url, "/api/login", method="POST", payload={"password": "23feb120658a1cb2c5b0be2be826bbc9"})
        assert res["ok"] is True
        token = res["token"]
        assert token

        # 5. Access with force auth and valid token -> should succeed
        res_tasks = request_json(
            base_url,
            "/api/tasks",
            headers={"X-Test-Force-Auth": "1", "Authorization": f"Bearer {token}"}
        )
        assert "tasks" in res_tasks

        # 6. Log out
        res_logout = request_json(
            base_url,
            "/api/logout",
            method="POST",
            headers={"X-Test-Force-Auth": "1", "Authorization": f"Bearer {token}"}
        )
        assert res_logout["ok"] is True

        # 7. Access with force auth and old token -> should fail with 401
        try:
            request_json(
                base_url,
                "/api/tasks",
                headers={"X-Test-Force-Auth": "1", "Authorization": f"Bearer {token}"}
            )
            assert False, "Should raise urllib.error.HTTPError for 401"
        except urllib.error.HTTPError as exc:
            assert exc.code == 401
    finally:
        httpd.shutdown()


def test_delete_run_api(tmp_path):
    db = AppDatabase(tmp_path / "app.sqlite3")
    app = TraeclawApp(project_root=tmp_path, db=db, import_legacy_state=False)
    app.initialize()
    run_id = db.start_run("cp.predict", "manual")
    db.finish_run(run_id, "success", 0, "", "", "ok")
    
    httpd = make_server(("127.0.0.1", 0), app)
    import threading
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{httpd.server_address[1]}"
    try:
        runs = db.get_runs("cp.predict")
        assert len(runs) == 1
        
        res = request_json(base_url, f"/api/runs/{run_id}/delete", method="POST")
        assert res["ok"] is True
        
        runs = db.get_runs("cp.predict")
        assert len(runs) == 0
    finally:
        httpd.shutdown()


def test_mfood_settings_api_check_and_login(tmp_path, monkeypatch):
    from unittest.mock import MagicMock
    httpd, base_url = run_test_server(tmp_path)
    
    # Mock MFoodLogin
    mock_validate = MagicMock(return_value=(True, "test_user"))
    mock_get_token = MagicMock(return_value={"token": "test-new-token-12345678"})
    
    import traeclaw.mfood.login
    monkeypatch.setattr(traeclaw.mfood.login.MFoodLogin, "validate_token", mock_validate)
    monkeypatch.setattr(traeclaw.mfood.login.MFoodLogin, "get_token", mock_get_token)
    
    try:
        # First save settings so MFoodLogin configured is True
        request_json(
            base_url,
            "/api/settings/mfood",
            method="POST",
            payload={
                "login": {
                    "profile": "default",
                    "account": "manager-a",
                    "password_md5": "0123456789abcdef0123456789abcdef",
                }
            }
        )
        
        # Test check endpoint without token in database
        check_res = request_json(base_url, "/api/settings/mfood/check", method="POST")
        assert check_res["ok"] is False
        assert "未配置 Token" in check_res["status"]
        
        # Now set the token in the DB manually (or via another way)
        db = AppDatabase(tmp_path / "app.sqlite3")
        db.set_setting("mfood.login.token", "test-saved-token")
        
        # Test check endpoint with token
        check_res2 = request_json(base_url, "/api/settings/mfood/check", method="POST")
        assert check_res2["ok"] is True
        assert check_res2["status"] == "test_user"
        mock_validate.assert_called_once_with("test-saved-token")
        
        # Test login endpoint
        login_res = request_json(base_url, "/api/settings/mfood/login", method="POST")
        assert login_res["ok"] is True
        assert login_res["token"] == "************5678"
        mock_get_token.assert_called_once_with(force_refresh=True)
        
        # Update DB to match mocked token
        db.set_setting("mfood.login.token", "test-new-token-12345678")
        
        # Test settings exposure
        loaded = request_json(base_url, "/api/settings/mfood")
        assert loaded["settings"]["login"]["token_configured"] is True
        assert loaded["settings"]["login"]["token"] == "************5678"
    finally:
        httpd.shutdown()
