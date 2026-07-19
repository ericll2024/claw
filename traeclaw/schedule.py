from __future__ import annotations

import json
import re
from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from .tasks.registry import TaskDefinition


TZ = ZoneInfo("Asia/Shanghai")
WEEKDAY_LABELS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
TIME_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


def default_schedule(task: TaskDefinition) -> dict[str, Any]:
    weekdays = list(range(7))
    times: list[str] = []
    if task.schedule_kind == "custom_daily":
        for h in range(5, 10):
            for m in range(0, 60, 5):
                times.append(f"{h:02d}:{m:02d}")
        times.append("10:00")
        for h in list(range(0, 5)) + list(range(11, 24)):
            times.append(f"{h:02d}:00")
        times.sort()
    elif task.schedule_kind == "daily" and task.time_of_day:
        times = [task.time_of_day]
    elif task.schedule_kind == "weekly" and task.time_of_day:
        weekdays = list(task.weekdays or tuple(range(7)))
        times = [task.time_of_day]
    return {
        "custom": False,
        "mode": "long_term",
        "start_date": "",
        "end_date": "",
        "weekdays": weekdays,
        "times": times,
        "label": task.schedule_label,
        "default_label": task.schedule_label,
        "default_kind": task.schedule_kind,
        "only_alert_on_abnormal": False,
    }


def load_schedule(task: TaskDefinition, raw: str = "") -> dict[str, Any]:
    base = default_schedule(task)
    if not raw:
        return base
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return base
    custom = normalize_schedule_payload(payload, task)
    return {
        **custom,
        "custom": True,
        "label": schedule_label(custom),
        "default_label": task.schedule_label,
        "default_kind": task.schedule_kind,
    }


def normalize_schedule_payload(payload: dict[str, Any], task: TaskDefinition | None = None) -> dict[str, Any]:
    mode = str(payload.get("mode") or "long_term").strip()
    if mode not in {"long_term", "date_range"}:
        raise ValueError("计划范围必须是长期或日期范围")
    start_date = _normalize_date(str(payload.get("start_date") or "").strip(), "开始日期")
    end_date = _normalize_date(str(payload.get("end_date") or "").strip(), "结束日期")
    if mode == "date_range":
        if not start_date or not end_date:
            raise ValueError("日期范围需要填写开始日期和结束日期")
        if date.fromisoformat(start_date) > date.fromisoformat(end_date):
            raise ValueError("开始日期不能晚于结束日期")
    else:
        start_date = ""
        end_date = ""
    weekdays = _normalize_weekdays(payload.get("weekdays", []))
    times = _normalize_times(payload.get("times", []))
    if not weekdays:
        raise ValueError("至少选择一个星期")
    if (task is None or task.schedule_kind != "interval") and not times:
        raise ValueError("至少填写一个时间点")
    only_alert_on_abnormal = payload.get("only_alert_on_abnormal", False)
    if not isinstance(only_alert_on_abnormal, bool):
        only_alert_on_abnormal = bool(only_alert_on_abnormal)

    return {
        "mode": mode,
        "start_date": start_date,
        "end_date": end_date,
        "weekdays": weekdays,
        "times": times,
        "only_alert_on_abnormal": only_alert_on_abnormal,
    }


def schedule_label(schedule: dict[str, Any]) -> str:
    prefix = "长期"
    if schedule["mode"] == "date_range":
        prefix = f"{schedule['start_date']} 至 {schedule['end_date']}"
    weekdays = _weekdays_label(schedule["weekdays"])
    times = "、".join(schedule["times"])
    return f"{prefix} · {weekdays} · {times}"


def next_run_after(task: TaskDefinition, schedule: dict[str, Any], now: datetime) -> datetime | None:
    if not schedule.get("custom"):
        return task.next_run_after(now)
    now = _to_tz(now)
    start = date.fromisoformat(schedule["start_date"]) if schedule.get("start_date") else now.date()
    end = date.fromisoformat(schedule["end_date"]) if schedule.get("end_date") else None
    current = max(now.date(), start)
    max_days = (end - current).days if end else 370
    if max_days < 0:
        return None
    times = [_parse_time(value) for value in schedule["times"]]
    weekdays = set(schedule["weekdays"])
    for offset in range(max_days + 1):
        day = current + timedelta(days=offset)
        if end and day > end:
            return None
        if day.weekday() not in weekdays:
            continue
        for item in times:
            candidate = datetime.combine(day, item, tzinfo=TZ)
            if candidate > now:
                return candidate
    return None


def due_key(task: TaskDefinition, schedule: dict[str, Any], now: datetime) -> str:
    now = _to_tz(now)
    if schedule.get("custom"):
        day = now.date()
        if schedule.get("start_date") and day < date.fromisoformat(schedule["start_date"]):
            return ""
        if schedule.get("end_date") and day > date.fromisoformat(schedule["end_date"]):
            return ""
        if day.weekday() not in set(schedule["weekdays"]):
            return ""
        hhmm = now.strftime("%H:%M")
        return f"{now.strftime('%Y-%m-%d')}:{hhmm}" if hhmm in set(schedule["times"]) else ""
    if task.schedule_kind == "custom_daily":
        hhmm = now.strftime("%H:%M")
        return f"{now.strftime('%Y-%m-%d')}:{hhmm}" if hhmm in set(schedule.get("times", [])) else ""
    if task.schedule_kind == "daily" and task.time_of_day:
        hhmm = now.strftime("%H:%M")
        return now.strftime("%Y-%m-%d") if hhmm == task.time_of_day else ""
    if task.schedule_kind == "weekly" and task.time_of_day:
        hhmm = now.strftime("%H:%M")
        if hhmm == task.time_of_day and now.weekday() in task.weekdays:
            return now.strftime("%Y-%m-%d")
    if task.schedule_kind == "interval" and task.interval_minutes > 0:
        minute_bucket = int(now.timestamp() // (task.interval_minutes * 60))
        return str(minute_bucket)
    return ""


def dumps_schedule(schedule: dict[str, Any], task: TaskDefinition | None = None) -> str:
    normalized = normalize_schedule_payload(schedule, task)
    return json.dumps(normalized, ensure_ascii=False, sort_keys=True)


def _normalize_date(value: str, label: str) -> str:
    if not value:
        return ""
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError as exc:
        raise ValueError(f"{label}格式应为 YYYY-MM-DD") from exc


def _normalize_weekdays(values: Any) -> list[int]:
    result: list[int] = []
    for value in values or []:
        try:
            weekday = int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError("星期值必须是 0-6") from exc
        if weekday < 0 or weekday > 6:
            raise ValueError("星期值必须是 0-6")
        if weekday not in result:
            result.append(weekday)
    return sorted(result)


def _normalize_times(values: Any) -> list[str]:
    result: list[str] = []
    for value in values or []:
        item = str(value or "").strip()
        if not item:
            continue
        if not TIME_RE.match(item):
            raise ValueError("时间格式应为 HH:MM")
        if item not in result:
            result.append(item)
    return sorted(result)


def _parse_time(value: str) -> time:
    hour, minute = value.split(":", 1)
    return time(int(hour), int(minute))


def _to_tz(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=TZ)
    return value.astimezone(TZ)


def _weekdays_label(values: list[int]) -> str:
    if values == list(range(7)):
        return "周一至周日"
    if values == [0, 1, 2, 3, 4]:
        return "工作日"
    if values == [5, 6]:
        return "周末"
    return "、".join(WEEKDAY_LABELS[index] for index in values)
