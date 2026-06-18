import json
import sqlite3

from traeclaw.db import AppDatabase


def test_initialize_creates_single_shared_schema(tmp_path):
    db_path = tmp_path / "traeclaw.sqlite3"
    db = AppDatabase(db_path)
    db.initialize()

    with sqlite3.connect(db_path) as conn:
        tables = {
            row[0]
            for row in conn.execute(
                "select name from sqlite_master where type='table' order by name"
            )
        }

    assert "settings" in tables
    assert "task_runs" in tables
    assert "task_results" in tables
    assert "legacy_imports" in tables


def test_settings_round_trip_and_mask_secret(tmp_path):
    db = AppDatabase(tmp_path / "app.sqlite3")
    db.initialize()

    db.set_setting("telegram.bot_token", "123456:secret-token", is_secret=True)
    db.set_setting("telegram.chat_id", "987654", is_secret=False)

    assert db.get_setting("telegram.bot_token") == "123456:secret-token"
    public = db.get_settings_public()

    assert public["telegram.chat_id"]["value"] == "987654"
    assert public["telegram.bot_token"]["value"] == "************oken"
    assert public["telegram.bot_token"]["configured"] is True


def test_record_run_and_latest_result(tmp_path):
    db = AppDatabase(tmp_path / "app.sqlite3")
    db.initialize()

    run_id = db.start_run("cp.predict", trigger_type="manual")
    db.finish_run(
        run_id,
        status="success",
        exit_code=0,
        stdout="cp 第 2026062 期预测已生成",
        stderr="",
        summary="cp 第 2026062 期预测已生成",
        result_payload={"issue_code": "2026062", "plans": [{"plan_type": "main"}]},
    )

    latest = db.get_latest_run("cp.predict")
    assert latest["status"] == "success"
    assert latest["summary"] == "cp 第 2026062 期预测已生成"

    results = db.get_task_results("cp.predict", limit=5)
    assert results[0]["payload"]["issue_code"] == "2026062"


def test_import_sqlite_tables_copies_legacy_state_into_shared_db(tmp_path):
    source = tmp_path / "legacy.db"
    with sqlite3.connect(source) as conn:
        conn.execute("create table sample_runs (id integer primary key, message text unique)")
        conn.execute("insert into sample_runs (message) values (?)", ("old result",))

    db = AppDatabase(tmp_path / "shared.sqlite3")
    db.initialize()
    imported = db.import_sqlite_tables(source)

    assert imported["tables"] == ["sample_runs"]
    with sqlite3.connect(db.path) as conn:
        row = conn.execute("select message from sample_runs").fetchone()
        marker = conn.execute(
            "select source_path from legacy_imports where source_path = ?", (str(source),)
        ).fetchone()

    assert row[0] == "old result"
    assert marker[0] == str(source)


def test_telegram_chat_titles(tmp_path):
    db = AppDatabase(tmp_path / "app.sqlite3")
    db.initialize()

    db.save_telegram_update({
        "update_id": 1,
        "chat_id": "-1001",
        "chat_title": "Old Group Title",
        "received_at": "2026-06-18T00:00:00Z"
    })
    db.save_telegram_update({
        "update_id": 2,
        "chat_id": "-1001",
        "chat_title": "New Group Title",
        "received_at": "2026-06-18T01:00:00Z"
    })
    db.save_telegram_update({
        "update_id": 3,
        "chat_id": "-1002",
        "chat_title": "Another Group",
        "received_at": "2026-06-18T02:00:00Z"
    })

    titles = db.get_latest_chat_titles()
    assert titles == {
        "-1001": "New Group Title",
        "-1002": "Another Group"
    }
