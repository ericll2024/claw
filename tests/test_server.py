import json
import threading
import urllib.request

from traeclaw.app import TraeclawApp
from traeclaw.db import AppDatabase
from traeclaw.server import make_server


def request_json(base_url, path, method="GET", payload=None):
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(base_url + path, data=data, headers=headers, method=method)
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


def test_tasks_api_groups_tasks_by_folder_agent(tmp_path):
    httpd, base_url = run_test_server(tmp_path)
    try:
        payload = request_json(base_url, "/api/tasks")
    finally:
        httpd.shutdown()

    agents = {agent["id"]: agent for agent in payload["agents"]}
    assert "cp" in agents
    assert agents["cp"]["folder"] == "code/scripts/cp"
    assert agents["cp"]["task_count"] == 2
    assert [task["id"] for task in agents["cp"]["tasks"]] == ["cp.predict", "cp.check_result"]
    assert agents["cp"]["schedule_summary"] == "每天 18:00 / 每天 22:00"
    assert agents["mFood"]["folder"] == "code/scripts/mFood"
    assert agents["fb"]["folder"] == "code/scripts/fb"


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
            },
        )
        payload = request_json(base_url, "/api/tasks")
        reset = request_json(
            base_url,
            "/api/tasks/cp.predict/schedule",
            method="POST",
            payload={"reset": True},
        )
    finally:
        httpd.shutdown()

    task = next(item for item in payload["tasks"] if item["id"] == "cp.predict")
    assert saved["schedule"]["custom"] is True
    assert saved["schedule"]["times"] == ["08:30", "18:30"]
    assert task["schedule"]["custom"] is True
    assert task["schedule_label"] == "长期 · 周一、周三、周五 · 08:30、18:30"
    assert reset["schedule"]["custom"] is False
    assert reset["schedule"]["label"] == "每天 18:00"


def test_task_group_runs_api_returns_recent_runs_with_limit(tmp_path):
    db = AppDatabase(tmp_path / "app.sqlite3")
    app = TraeclawApp(project_root=tmp_path, db=db, import_legacy_state=False)
    app.initialize()
    for task_id, summary in [
        ("cp.predict", "predict ok"),
        ("cp.check_result", "check ok"),
        ("mfood.login_token", "login ok"),
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
