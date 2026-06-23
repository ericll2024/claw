from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from traeclaw.schedule import due_key, dumps_schedule, load_schedule, next_run_after
from traeclaw.tasks.registry import get_task, list_tasks


TZ = ZoneInfo("Asia/Shanghai")


def test_registry_exposes_cp_tasks_with_readable_schedule():
    tasks = {task.id: task for task in list_tasks()}

    assert "cp.predict" in tasks
    assert "cp.check_result" in tasks
    assert tasks["cp.predict"].schedule_label == "每天 18:00"
    assert tasks["cp.check_result"].schedule_label == "每天 22:00"
    assert tasks["cp.predict"].enabled_by_default is True


def test_registry_includes_legacy_script_tasks_as_visible_items():
    task_ids = {task.id for task in list_tasks()}

    assert "mfood.maskphone_monitor" in task_ids
    assert "shence.order_reconcile" in task_ids
    assert "facebook.yesterday_summary" in task_ids


def test_registry_includes_migrated_mfood_skill_tasks():
    task_ids = {task.id for task in list_tasks()}

    assert "mfood.order_monitor" in task_ids


def test_next_run_for_daily_task_rolls_to_today_or_tomorrow():
    task = get_task("cp.predict")

    morning = datetime(2026, 6, 9, 8, 30, tzinfo=TZ)
    evening = datetime(2026, 6, 9, 18, 30, tzinfo=TZ)

    assert task.next_run_after(morning).isoformat() == "2026-06-09T18:00:00+08:00"
    assert task.next_run_after(evening).isoformat() == "2026-06-10T18:00:00+08:00"


def test_manual_task_has_no_next_run():
    from traeclaw.tasks.registry import TaskDefinition
    task = TaskDefinition(
        id="test.manual",
        name="Test Manual",
        group="test",
        description="test manual task",
        schedule_label="手动触发",
        command=["echo"],
        schedule_kind="manual"
    )

    assert task.schedule_label == "手动触发"
    assert task.next_run_after(datetime(2026, 6, 9, 8, 30, tzinfo=TZ)) is None


def test_custom_schedule_supports_date_range_weekdays_and_times():
    task = get_task("cp.predict")
    raw = dumps_schedule(
        {
            "mode": "date_range",
            "start_date": "2026-06-13",
            "end_date": "2026-06-20",
            "weekdays": [5],
            "times": ["18:00", "09:00"],
        }
    )
    schedule = load_schedule(task, raw)

    assert schedule["custom"] is True
    assert schedule["times"] == ["09:00", "18:00"]
    assert "2026-06-13 至 2026-06-20" in schedule["label"]
    assert next_run_after(task, schedule, datetime(2026, 6, 13, 8, 0, tzinfo=TZ)).isoformat() == "2026-06-13T09:00:00+08:00"
    assert due_key(task, schedule, datetime(2026, 6, 13, 18, 0, tzinfo=TZ)) == "2026-06-13:18:00"

