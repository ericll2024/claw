from __future__ import annotations

import sys
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
from typing import Sequence
from zoneinfo import ZoneInfo


TZ = ZoneInfo("Asia/Shanghai")


AGENTS = {
    "cp": {"name": "cp", "folder": "code/scripts/cp", "description": "双色球推荐、开奖拉取和复盘"},
    "mFood": {"name": "mFood", "folder": "code/scripts/mFood", "description": "mFood 登录、门店巡检和经营数据监控"},
    "shence": {"name": "shence", "folder": "code/scripts/shence", "description": "神策数据查询和订单对账"},
    "fb": {"name": "fb", "folder": "code/scripts/fb", "description": "Facebook 群组抓取和摘要"},
    "crowd": {"name": "crowd", "folder": "code/scripts/crowd", "description": "众包代码更新播报"},
    "tycp": {"name": "tycp", "folder": "code/scripts/tycp", "description": "大乐透历史数据、推荐和复盘"},
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
        ),
        TaskDefinition(
            id="tycp.dlt_recommend",
            name="大乐透推荐",
            group="tycp",
            description="旧 scripts/tycp 大乐透推荐脚本，默认只展示，待确认路径后可启用。",
            schedule_kind="daily",
            time_of_day="18:30",
            schedule_label="每天 18:30",
            command=[*legacy, "code/scripts/tycp/dlt_recommend.py"],
        ),
        TaskDefinition(
            id="tycp.dlt_fetch",
            name="大乐透拉取开奖",
            group="tycp",
            description="拉取最新大乐透开奖号码，更新历史数据库。",
            schedule_kind="daily",
            time_of_day="21:30",
            schedule_label="每天 21:30",
            enabled_by_default=True,
            command=[*legacy, "code/scripts/tycp/fetch_dlt.py", "--mode", "latest"],
        ),
        TaskDefinition(
            id="mfood.maskphone_monitor",
            name="mFood 隐私号监控",
            group="mFood",
            description="检查 mFood 隐私号使用量，旧脚本依赖 mfood_login_skill。",
            schedule_kind="interval",
            interval_minutes=10,
            schedule_label="每 10 分钟",
            command=[*legacy, "code/scripts/mFood/qinglong_maskphone_monitor.py"],
        ),
        TaskDefinition(
            id="mfood.login_token",
            name="mFood 登录 Token",
            group="mFood",
            description="项目内迁移的 mfood_login_skill：按网页配置获取或刷新 manager token。",
            schedule_label="手动触发",
            command=[python, "-m", "traeclaw.mfood.login"],
        ),
        TaskDefinition(
            id="mfood.shence_health",
            name="mFood 神策查询",
            group="mFood",
            description="项目内迁移的 mfood_shence：使用网页配置执行 Sensors SQL 健康检查。",
            schedule_label="手动触发",
            command=[python, "-m", "traeclaw.mfood.shence"],
        ),
        TaskDefinition(
            id="mfood.order_monitor",
            name="mFood 订单对账 Monitor",
            group="mFood",
            description="项目内迁移的 mfood-order-monitor：对比神策事件和管理后台完成订单数。",
            schedule_kind="daily",
            time_of_day="09:50",
            schedule_label="每天 09:50",
            command=[python, "-m", "traeclaw.mfood.order_monitor"],
        ),
        TaskDefinition(
            id="mfood.takeout_business_analysis",
            name="mFood 外卖营业分析",
            group="mFood",
            description="外卖门店营业状态分析，读取 state/mfdb 配置。",
            schedule_kind="daily",
            time_of_day="09:00",
            schedule_label="每天 09:00",
            command=[*legacy, "code/scripts/mFood/takeout_business_analysis_check.py"],
        ),
        TaskDefinition(
            id="mfood.market_business_analysis",
            name="mFood 超市营业分析",
            group="mFood",
            description="超市门店营业状态分析，读取 state/mfdb 配置。",
            schedule_kind="daily",
            time_of_day="09:10",
            schedule_label="每天 09:10",
            command=[*legacy, "code/scripts/mFood/market_business_analysis_check.py"],
        ),
        TaskDefinition(
            id="mfood.market_summary",
            name="mFood 超市汇总检查",
            group="mFood",
            description="超市汇总巡检，读取 state/mfdb 配置。",
            schedule_kind="daily",
            time_of_day="09:20",
            schedule_label="每天 09:20",
            command=[*legacy, "code/scripts/mFood/market_summary_check.py"],
        ),
        TaskDefinition(
            id="mfood.merchant_summary",
            name="mFood 商户汇总检查",
            group="mFood",
            description="商户汇总巡检，读取 state/mfdb 配置。",
            schedule_kind="daily",
            time_of_day="09:30",
            schedule_label="每天 09:30",
            command=[*legacy, "code/scripts/mFood/merchant_summary_check.py"],
        ),
        TaskDefinition(
            id="shence.order_reconcile",
            name="神策订单对账",
            group="shence",
            description="比对神策事件与管理后台订单数量。",
            schedule_kind="daily",
            time_of_day="09:40",
            schedule_label="每天 09:40",
            command=[*legacy, "code/scripts/shence/shence_order_reconcile.py"],
        ),
        TaskDefinition(
            id="facebook.yesterday_summary",
            name="Facebook 群组昨日摘要",
            group="fb",
            description="抓取 Facebook 群组昨日内容并生成摘要。",
            schedule_kind="daily",
            time_of_day="09:00",
            schedule_label="每天 09:00",
            command=["bash", "code/scripts/fb/fb_yesterday_summary.sh"],
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
            command=["bash", "code/scripts/crowd/crowd_pull_report.sh"],
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
