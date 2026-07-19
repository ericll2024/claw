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
    "tycp": {"name": "tycp", "folder": "scripts/tycp", "description": "大乐透历史数据、推荐和复盘"},
}


@dataclass(frozen=True)
class WorkflowStep:
    title: str
    detail: str


def _steps(*items: tuple[str, str]) -> tuple[WorkflowStep, ...]:
    return tuple(WorkflowStep(title=title, detail=detail) for title, detail in items)


TASK_WORKFLOWS: dict[str, tuple[WorkflowStep, ...]] = {
    "cp.predict": _steps(
        ("加载历史数据", "连接 traerclaw.sqlite3 数据库，读取双色球最新期号，并载入最近 100 期中奖号码。"),
        ("运行预测算法", "基于历史开奖数据运行概率算法和过滤规则，生成候选号码组合并评分。"),
        ("生成推荐方案", "整理评分最高的前几组双色球推荐号码方案。"),
        ("保存预测结果", "将预测结果持久化到 SQLite，供后续开奖复盘使用。"),
    ),
    "cp.check_result": _steps(
        ("拉取最新开奖", "请求开奖接口，带重试获取双色球最新开奖号码。"),
        ("写入开奖历史", "将最新中奖号码写入本地数据库历史表。"),
        ("读取预测方案", "查询之前为该期生成的预测号码方案。"),
        ("结算与复盘", "比对预测与开奖结果，生成复盘结算信息并通知 Telegram。"),
    ),
    "tycp.dlt_recommend": _steps(
        ("生成预算组合", "按预算档位生成大乐透复式票组合方案。"),
        ("保存推荐方案", "把方案和投注明细持久化到 SQLite。"),
    ),
    "tycp.dlt_fetch": _steps(
        ("拉取最新开奖", "调用体彩接口增量更新大乐透开奖结果。"),
        ("比对结算复盘", "对照历史推荐方案计算中奖情况并生成报告。"),
    ),
    "mfood.maskphone_monitor": _steps(
        ("读取登录 Token", "从设置中读取 mFood 登录 Token，缺失则报错中断。"),
        ("访问隐私号 API", "调用管理后台接口抓取当天隐私号使用详情。"),
        ("监测使用限额", "计算当前使用量与阈值，判断是否超限。"),
        ("推送报警消息", "超阈值时生成报警消息并通过 Telegram 推送。"),
    ),
    "mfood.takeout_business_analysis": _steps(
        ("解析店铺配置", "读取外卖店铺配置和全局 Token。"),
        ("请求营业数据", "调用营业分析接口抓取指定日期的营业指标。"),
        ("拉取订单复查", "营业额异常时再查订单列表进行二次核对。"),
        ("异常诊断与推送", "发现营业数据和订单数据不一致时推送报警。"),
    ),
    "mfood.market_business_analysis": _steps(
        ("解析超市配置", "读取超市配置和全局 Token。"),
        ("获取超市营业数据", "调用超市营业数据接口抓取核心指标。"),
        ("提取超市订单明细", "营业额异常时再查订单明细接口复核。"),
        ("指标计算与播报", "确认异常后生成超市营业异常通知。"),
    ),
    "mfood.market_summary": _steps(
        ("加载对账配置", "读取超市汇总对账配置和登录 Token。"),
        ("调取超市汇总报表", "调用汇总接口抓取全商户超市结算数据。"),
        ("核对资金流向", "对异常记录进行二次订单复核。"),
        ("异常核算并播报", "发现资金流异常时通过 Telegram 发送报警。"),
    ),
    "mfood.merchant_summary": _steps(
        ("加载外卖汇总配置", "读取外卖商户汇总配置和登录 Token。"),
        ("请求商户对账单", "调用商户汇总接口抓取销售和结算数据。"),
        ("处理账目不匹配项", "对异常记录调用订单接口做二次核验。"),
        ("差异结算报告与报警", "确认对账异常后生成报告并推送。"),
    ),
    "shence.order_reconcile": _steps(
        ("配置时间区间", "计算默认的昨日时间区间参数。"),
        ("运行神策 SQL", "调用神策 API 查询埋点订单数据。"),
        ("获取 mFood 账单", "登录并拉取 mFood 管理后台订单记录。"),
        ("双端比对及报警", "比对两端差异，异常时写库并推送通知。"),
    ),
    "facebook.yesterday_summary": _steps(
        ("读取监测群组", "加载 Facebook 群组配置和已有登录态。"),
        ("启动 Playwright", "启动浏览器并复用 cookies 登录状态。"),
        ("遍历抓取贴文", "抓取昨日群组贴文、互动数据和内容。"),
        ("内容摘要与通知", "汇总生成摘要并按需推送 Telegram。"),
    ),
    "mfood.token_check": _steps(
        ("读取登录 Token", "从数据库中读取已保存的 mFood Token。"),
        ("验证 Token 状态", "访问 mFood 管理后台接口校验 Token 是否有效。"),
        ("自动重新登录", "若 Token 已失效，自动调用登录接口重新获取 Token。"),
        ("更新检查时间", "记录当前检查时间到数据库。"),
    ),

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
    workflow_steps: tuple[WorkflowStep, ...] = field(default_factory=tuple)

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
            workflow_steps=TASK_WORKFLOWS["cp.predict"],
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
            workflow_steps=TASK_WORKFLOWS["cp.check_result"],
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
            workflow_steps=TASK_WORKFLOWS["tycp.dlt_recommend"],
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
            workflow_steps=TASK_WORKFLOWS["tycp.dlt_fetch"],
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
            workflow_steps=TASK_WORKFLOWS["mfood.maskphone_monitor"],
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
            workflow_steps=TASK_WORKFLOWS["mfood.takeout_business_analysis"],
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
            workflow_steps=TASK_WORKFLOWS["mfood.market_business_analysis"],
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
            workflow_steps=TASK_WORKFLOWS["mfood.market_summary"],
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
            workflow_steps=TASK_WORKFLOWS["mfood.merchant_summary"],
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
            workflow_steps=TASK_WORKFLOWS["shence.order_reconcile"],
        ),
        TaskDefinition(
            id="facebook.yesterday_summary",
            name="Facebook 群组昨日摘要",
            group="fb",
            description="使用 BrowserSkill 自动抓取 Facebook 群组昨日内容并生成摘要。",
            schedule_kind="daily",
            time_of_day="09:00",
            schedule_label="每天 09:00",
            command=["node", "scripts/fb/fb_group_checker_bsk.js"],
            editable_paths=("scripts/fb", "state/facebook/fb_groups.json"),
            context_files=("scripts/fb/fb_group_checker_bsk.js", "state/facebook/fb_groups.json"),
            verify_commands=verify,
            reply_name="Facebook 群组昨日摘要",
            workflow_steps=TASK_WORKFLOWS["facebook.yesterday_summary"],
        ),

        TaskDefinition(
            id="mfood.token_check",
            name="mFood Token 检查与重登",
            group="mFood",
            description="早上5点到10点，每5分钟检查一次，其他时间1小时检查一次。异常（连续3次登录失败）发送通知。",
            schedule_kind="custom_daily",
            interval_minutes=5,
            schedule_label="每天 05:00-10:00 每5分钟，其他时间每小时",
            enabled_by_default=True,
            command=[python, "-m", "traeclaw.mfood.token_check"],
            editable_paths=("traeclaw/mfood/token_check.py",),
            context_files=("traeclaw/mfood/token_check.py",),
            verify_commands=verify,
            reply_name="mFood Token 检查",
            workflow_steps=TASK_WORKFLOWS["mfood.token_check"],
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
