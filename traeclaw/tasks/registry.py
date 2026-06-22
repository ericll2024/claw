from __future__ import annotations

import sys
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
from typing import Sequence
from zoneinfo import ZoneInfo


TZ = ZoneInfo("Asia/Shanghai")


AGENTS = {
    "cp": {"name": "cp", "folder": "scripts/cp", "description": "双色球推荐、开奖拉取和复盘"},
    "mFood": {"name": "mFood", "folder": "scripts/mFood", "description": "mFood 登录、门店巡检和经营数据监控"},
    "shence": {"name": "shence", "folder": "scripts/shence", "description": "神策数据查询和订单对账"},
    "fb": {"name": "fb", "folder": "scripts/fb", "description": "Facebook 群组抓取和摘要"},
    "crowd": {"name": "crowd", "folder": "scripts/crowd", "description": "众包代码更新播报"},
    "tycp": {"name": "tycp", "folder": "scripts/tycp", "description": "大乐透历史数据、推荐和复盘"},
}


@dataclass(frozen=True)
class TaskDefinition:
    id: str
    name: str
    group: str
    description: str
    schedule_label: str
    command: Sequence[str]
    enabled_by_default: bool = False
    schedule_kind: str = "manual"
    time_of_day: str = ""
    weekdays: tuple[int, ...] = field(default_factory=tuple)
    interval_minutes: int = 0
    timeout_seconds: int = 900
    editable_paths: tuple[str, ...] = field(default_factory=tuple)
    context_files: tuple[str, ...] = field(default_factory=tuple)
    verify_commands: tuple[tuple[str, ...], ...] = field(default_factory=tuple)
    reply_name: str = ""

    def next_run_after(self, now: datetime) -> datetime | None:
        if now.tzinfo is None:
            now = now.replace(tzinfo=TZ)
        else:
            now = now.astimezone(TZ)

        if self.schedule_kind == "daily" and self.time_of_day:
            hour, minute = _parse_time(self.time_of_day)
            candidate = datetime.combine(now.date(), time(hour, minute), tzinfo=TZ)
            if candidate <= now:
                candidate += timedelta(days=1)
            return candidate

        if self.schedule_kind == "weekly" and self.time_of_day and self.weekdays:
            hour, minute = _parse_time(self.time_of_day)
            for offset in range(8):
                day = now.date() + timedelta(days=offset)
                candidate = datetime.combine(day, time(hour, minute), tzinfo=TZ)
                if candidate.weekday() in self.weekdays and candidate > now:
                    return candidate
            return None

        if self.schedule_kind == "interval" and self.interval_minutes > 0:
            return now + timedelta(minutes=self.interval_minutes)

        return None

    @property
    def command_label(self) -> str:
        return " ".join(self.command)


def list_tasks() -> list[TaskDefinition]:
    python = sys.executable or "python3"
    legacy = [python, "-m", "traeclaw.tasks.legacy"]
    verify = ((python, "-m", "pytest", "tests", "-q"),)
    return [
        TaskDefinition(
            id="cp.predict",
            name="CP 双色球推荐号码",
            group="cp",
            description="基于已有开奖数据生成下一期推荐方案，写入统一 SQLite。",
            schedule_kind="daily",
            time_of_day="18:00",
            schedule_label="每天 18:00",
            enabled_by_default=True,
            command=[python, "-m", "traeclaw.tasks.cp", "predict"],
            editable_paths=("scripts/cp", "traeclaw/tasks/cp.py"),
            context_files=("traeclaw/tasks/cp.py", "scripts/cp/cp_prediction_core.py"),
            verify_commands=verify,
            reply_name="CP 双色球推荐",
        ),
        TaskDefinition(
            id="cp.check_result",
            name="CP 拉取开奖并复盘",
            group="cp",
            description="晚上拉取最新开奖号码，然后比对已生成方案并记录复盘结果。",
            schedule_kind="daily",
            time_of_day="22:00",
            schedule_label="每天 22:00",
            enabled_by_default=True,
            command=[python, "-m", "traeclaw.tasks.cp", "check-result"],
            editable_paths=("scripts/cp", "traeclaw/tasks/cp.py"),
            context_files=("traeclaw/tasks/cp.py", "scripts/cp/check_result_and_notify.sh"),
            verify_commands=verify,
            reply_name="CP 开奖复盘",
        ),
        TaskDefinition(
            id="tycp.dlt_recommend",
            name="大乐透推荐",
            group="tycp",
            description="大乐透预算推荐，生成 100, 500, 1000 元的组合号码并入库。",
            schedule_kind="daily",
            time_of_day="18:30",
            schedule_label="每天 18:30",
            enabled_by_default=True,
            command=[*legacy, "scripts/tycp/dlt_recommend_budget.py"],
            editable_paths=("scripts/tycp",),
            context_files=("scripts/tycp/dlt_recommend_budget.py",),
            verify_commands=verify,
            reply_name="大乐透推荐",
        ),
        TaskDefinition(
            id="tycp.dlt_fetch",
            name="大乐透拉取开奖",
            group="tycp",
            description="拉取最新大乐透开奖号码并对照已生成方案进行复盘结算。",
            schedule_kind="daily",
            time_of_day="21:30",
            schedule_label="每天 21:30",
            enabled_by_default=True,
            command=[*legacy, "scripts/tycp/check_result.py"],
            editable_paths=("scripts/tycp",),
            context_files=("scripts/tycp/check_result.py",),
            verify_commands=verify,
            reply_name="大乐透开奖复盘",
        ),
        TaskDefinition(
            id="mfood.maskphone_monitor",
            name="mFood 隐私号监控",
            group="mFood",
            description="检查 mFood 隐私号使用量，旧脚本依赖 mfood_login_skill。",
            schedule_kind="interval",
            interval_minutes=10,
            schedule_label="每 10 分钟",
            command=[*legacy, "scripts/mFood/qinglong_maskphone_monitor.py"],
            editable_paths=("scripts/mFood", "state/mfdb/maskphone_monitor_config.json"),
            context_files=("scripts/mFood/qinglong_maskphone_monitor.py", "state/mfdb/maskphone_monitor_config.json"),
            verify_commands=verify,
            reply_name="mFood 隐私号监控",
        ),
        TaskDefinition(
            id="mfood.order_monitor",
            name="mFood 订单数据检查",
            group="mFood",
            description="项目内迁移的 mfood-order-monitor：对比神策事件和管理后台完成订单数。",
            schedule_kind="daily",
            time_of_day="09:50",
            schedule_label="每天 09:50",
            command=[python, "-m", "traeclaw.mfood.order_monitor"],
            editable_paths=("traeclaw/mfood/order_monitor.py", "state/mfdb/order_monitor_config.json"),
            context_files=("traeclaw/mfood/order_monitor.py", "state/mfdb/order_monitor_config.json"),
            verify_commands=verify,
            reply_name="mFood 订单数据检查",
        ),
        TaskDefinition(
            id="mfood.takeout_business_analysis",
            name="mFood 外卖营业分析",
            group="mFood",
            description="外卖门店营业状态分析，读取 state/mfdb 配置。",
            schedule_kind="daily",
            time_of_day="09:00",
            schedule_label="每天 09:00",
            command=[*legacy, "scripts/mFood/takeout_business_analysis_check.py"],
            editable_paths=("scripts/mFood", "state/mfdb/takeout_business_analysis_check_config.json"),
            context_files=("scripts/mFood/takeout_business_analysis_check.py", "state/mfdb/takeout_business_analysis_check_config.json"),
            verify_commands=verify,
            reply_name="mFood 外卖营业分析",
        ),
        TaskDefinition(
            id="mfood.market_business_analysis",
            name="mFood 超市营业分析",
            group="mFood",
            description="超市门店营业状态分析，读取 state/mfdb 配置。",
            schedule_kind="daily",
            time_of_day="09:10",
            schedule_label="每天 09:10",
            command=[*legacy, "scripts/mFood/market_business_analysis_check.py"],
            editable_paths=("scripts/mFood", "state/mfdb/market_business_analysis_check_config.json"),
            context_files=("scripts/mFood/market_business_analysis_check.py", "state/mfdb/market_business_analysis_check_config.json"),
            verify_commands=verify,
            reply_name="mFood 超市营业分析",
        ),
        TaskDefinition(
            id="mfood.market_summary",
            name="mFood 超市汇总检查",
            group="mFood",
            description="超市汇总巡检，读取 state/mfdb 配置。",
            schedule_kind="daily",
            time_of_day="09:20",
            schedule_label="每天 09:20",
            command=[*legacy, "scripts/mFood/market_summary_check.py"],
            editable_paths=("scripts/mFood", "state/mfdb/market_summary_check_config.json"),
            context_files=("scripts/mFood/market_summary_check.py", "state/mfdb/market_summary_check_config.json"),
            verify_commands=verify,
            reply_name="mFood 超市汇总检查",
        ),
        TaskDefinition(
            id="mfood.merchant_summary",
            name="mFood 商户汇总检查",
            group="mFood",
            description="商户汇总巡检，读取 state/mfdb 配置。",
            schedule_kind="daily",
            time_of_day="09:30",
            schedule_label="每天 09:30",
            command=[*legacy, "scripts/mFood/merchant_summary_check.py"],
            editable_paths=("scripts/mFood", "state/mfdb/merchant_summary_check_config.json"),
            context_files=("scripts/mFood/merchant_summary_check.py", "state/mfdb/merchant_summary_check_config.json"),
            verify_commands=verify,
            reply_name="mFood 商户汇总检查",
        ),
        TaskDefinition(
            id="shence.order_reconcile",
            name="神策订单对账",
            group="shence",
            description="比对神策事件与管理后台订单数量。",
            schedule_kind="daily",
            time_of_day="09:40",
            schedule_label="每天 09:40",
            command=[*legacy, "scripts/shence/shence_order_reconcile.py"],
            editable_paths=("scripts/shence",),
            context_files=("scripts/shence/shence_order_reconcile.py",),
            verify_commands=verify,
            reply_name="神策订单对账",
        ),
        TaskDefinition(
            id="facebook.yesterday_summary",
            name="Facebook 群组昨日摘要",
            group="fb",
            description="抓取 Facebook 群组昨日内容并生成摘要。",
            schedule_kind="daily",
            time_of_day="09:00",
            schedule_label="每天 09:00",
            command=["bash", "scripts/fb/fb_yesterday_summary.sh"],
            editable_paths=("scripts/fb", "state/facebook/fb_groups.json", "state/facebook/fb_storage_state.json"),
            context_files=("scripts/fb/fb_yesterday_summary.sh", "state/facebook/fb_groups.json"),
            verify_commands=verify,
            reply_name="Facebook 群组昨日摘要",
        ),
        TaskDefinition(
            id="crowd.pull_report",
            name="众包代码更新播报",
            group="crowd",
            description="拉取众包相关仓库并输出更新播报。",
            schedule_kind="weekly",
            weekdays=(0, 1, 2, 3, 4),
            time_of_day="10:00",
            schedule_label="工作日 10:00",
            command=["bash", "scripts/crowd/crowd_pull_report.sh"],
            editable_paths=("scripts/crowd",),
            context_files=("scripts/crowd/crowd_pull_report.sh",),
            verify_commands=verify,
            reply_name="众包代码更新播报",
        ),
    ]


def get_task(task_id: str) -> TaskDefinition:
    for task in list_tasks():
        if task.id == task_id:
            return task
    raise KeyError(f"Unknown task: {task_id}")


def get_agent_meta(agent_id: str) -> dict[str, str]:
    fallback = {"name": agent_id, "folder": agent_id, "description": ""}
    return {**fallback, **AGENTS.get(agent_id, {})}


def _parse_time(value: str) -> tuple[int, int]:
    hour, minute = value.split(":", 1)
    return int(hour), int(minute)
