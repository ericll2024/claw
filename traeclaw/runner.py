from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

from .db import AppDatabase
from .tasks.registry import TaskDefinition
from .telegram import TelegramConfig, TelegramNotifier


TASK_FILE_MAP = {
    "mfood.takeout_business_analysis": [
        "state/mfdb/takeout_business_analysis_check_config.json",
    ],
    "mfood.market_business_analysis": [
        "state/mfdb/market_business_analysis_check_config.json",
    ],
    "mfood.merchant_summary": [
        "state/mfdb/merchant_summary_check_config.json",
    ],
    "mfood.market_summary": [
        "state/mfdb/market_summary_check_config.json",
    ],
    "facebook.yesterday_summary": [
        "state/facebook/fb_groups.json",
        "state/facebook/fb_storage_state.json",
    ],
    "mfood.order_monitor": [
        "state/mfdb/order_monitor_config.json",
    ],
    "mfood.maskphone_monitor": [
        "state/mfdb/maskphone_monitor_config.json",
    ],
}


def _output_text(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


class TaskRunner:
    def __init__(self, db: AppDatabase, project_root: str | Path):
        self.db = db
        self.project_root = Path(project_root)

    def run(
        self,
        task: TaskDefinition,
        trigger_type: str = "manual",
        send_to_telegram: bool = False,
        retry_count: int = 2,
    ) -> dict[str, Any]:
        run_id = self.db.start_run(task.id, trigger_type)
        stdout = ""
        stderr = ""
        exit_code: int | None = None
        status = "failed"
        retry_count = max(int(retry_count), 0)
        max_attempts = retry_count + 1
        attempt_count = 0

        # Write files from DB to filesystem
        files_to_sync = TASK_FILE_MAP.get(task.id, [])
        for rel_path in files_to_sync:
            content = self.db.get_setting(f"file:{rel_path}", "")
            if content:
                file_path = self.project_root / rel_path
                file_path.parent.mkdir(parents=True, exist_ok=True)
                file_path.write_text(content, encoding="utf-8")

        try:
            cmd = adjust_command(list(task.command), self.project_root)
            failure_diagnostics: list[str] = []
            for attempt_count in range(1, max_attempts + 1):
                stdout, stderr, exit_code, status = self._run_command(cmd, task)
                if status == "success":
                    break
                failure_diagnostics.append(
                    f"Attempt {attempt_count}/{max_attempts} failed\n"
                    f"stdout:\n{stdout}\n"
                    f"stderr:\n{stderr}"
                )
            if failure_diagnostics:
                if status == "success" and stderr:
                    failure_diagnostics.append(f"Final attempt stderr:\n{stderr}")
                stderr = "\n\n".join(failure_diagnostics)
        finally:
            # Sync files back to DB and delete from disk
            for rel_path in files_to_sync:
                file_path = self.project_root / rel_path
                if file_path.exists():
                    try:
                        content = file_path.read_text(encoding="utf-8")
                        self.db.set_setting(f"file:{rel_path}", content)
                        file_path.unlink()
                        # Clean up empty parent directories up to state
                        parent = file_path.parent
                        while parent != self.project_root / "state" and parent != self.project_root:
                            try:
                                parent.rmdir()
                                parent = parent.parent
                            except Exception:
                                break
                    except Exception:
                        pass

        summary = summarize_output(stdout, stderr, status)
        result_payload = parse_result_payload(stdout, stderr, status)
        notify_status = ""
        notify_error = ""
        if trigger_type == "schedule" or (trigger_type == "manual" and send_to_telegram):
            from .schedule import load_schedule
            raw_schedule = self.db.get_setting(f"task.{task.id}.schedule", "")
            schedule = load_schedule(task, raw_schedule)
            only_alert = schedule.get("only_alert_on_abnormal", False)

            should_notify = True
            if task.id == "mfood.maskphone_monitor":
                # Special rule: only notify on threshold exceeded (status == "alert" in result_payload)
                should_notify = (
                    status == "success"
                    and isinstance(result_payload, dict)
                    and result_payload.get("status") == "alert"
                )
            elif trigger_type == "schedule" and only_alert:
                should_notify = check_run_has_alert(status, summary, result_payload)

            if should_notify:
                notify_status, notify_error = self._notify_if_configured(task, status, summary)
            else:
                notify_status = "skipped"
        self.db.finish_run(
            run_id,
            status=status,
            exit_code=exit_code,
            stdout=stdout,
            stderr=stderr,
            summary=summary,
            result_payload=result_payload,
            notify_status=notify_status,
            notify_error=notify_error,
        )
        return {
            "run_id": run_id,
            "task_id": task.id,
            "status": status,
            "exit_code": exit_code,
            "summary": summary,
            "attempt_count": attempt_count,
            "notify_status": notify_status,
            "notify_error": notify_error,
        }

    def _run_command(self, cmd: list[str], task: TaskDefinition) -> tuple[str, str, int | None, str]:
        try:
            completed = subprocess.run(
                cmd,
                cwd=self.project_root,
                env=self._env(),
                capture_output=True,
                encoding="utf-8",
                errors="replace",
                timeout=task.timeout_seconds,
                check=False,
            )
            stdout = completed.stdout or ""
            stderr = completed.stderr or ""
            status = "success" if completed.returncode == 0 else "failed"
            return stdout, stderr, completed.returncode, status
        except subprocess.TimeoutExpired as exc:
            return (
                _output_text(exc.stdout),
                _output_text(exc.stderr) + f"\nTask timed out after {task.timeout_seconds}s",
                None,
                "failed",
            )
        except Exception as exc:
            return "", str(exc), None, "failed"

    def _env(self) -> dict[str, str]:
        env = os.environ.copy()
        code_dir = Path(__file__).resolve().parents[1]
        existing = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = str(code_dir) if not existing else f"{code_dir}{os.pathsep}{existing}"
        env["TRAECLAW_DB_PATH"] = str(self.db.path)
        env["TRAECLAW_PROJECT_ROOT"] = str(self.project_root)
        env["PYTHONUTF8"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"
        return env

    def _notify_if_configured(self, task: TaskDefinition, status: str, summary: str) -> tuple[str, str]:
        config = TelegramConfig.load_private(self.db)
        if not config["enabled"] or not config.get("bot_token"):
            return "", ""

        # Fetch task-specific Telegram chat ID and template
        task_chat_id = self.db.get_setting(f"task.{task.id}.telegram_chat_id", "").strip()
        chat_id = task_chat_id or config.get("chat_id")
        if not chat_id:
            return "", ""

        text = summary.strip() or f"{task.name} 运行{'成功' if status == 'success' else '失败'}"

        try:
            TelegramNotifier(config["bot_token"], chat_id).send_message(text)
            return "sent", ""
        except Exception as exc:
            return "failed", str(exc)


def summarize_output(stdout: str, stderr: str, status: str) -> str:
    parsed = _parse_json(stdout)
    if isinstance(parsed, dict):
        if parsed.get("summary_text"):
            return str(parsed["summary_text"])[:4000]
        if parsed.get("message"):
            return str(parsed["message"])[:4000]
        
        # Lottery fetch task (dlt_fetch)
        if "inserted" in parsed and "db_total" in parsed:
            inserted = parsed.get("inserted", 0)
            updated = parsed.get("updated", 0)
            db_total = parsed.get("db_total", 0)
            latest = parsed.get("latest") or []
            latest_line = f"。最新一期: {latest[0]}" if latest else ""
            return f"拉取完成，新增 {inserted} 条，更新 {updated} 条，共 {db_total} 条{latest_line}"[:4000]
            
        # Lottery recommendation task (dlt_recommend)
        if "recommendations" in parsed:
            recs = parsed.get("recommendations") or []
            if recs:
                rec_lines = [f"{r.get('front', '')} + {r.get('back', '')}" for r in recs[:3]]
                return "推荐方案已生成（前区+后区）：\n" + "\n".join(rec_lines)
            return "推荐方案已生成，但未选出合适组合"
            
        # Lottery prize checking task (dlt_prize_check)
        if "prize_level" in parsed and "draw_num" in parsed:
            draw_num = parsed.get("draw_num")
            level = parsed.get("prize_level")
            amount = parsed.get("prize_amount", 0)
            return f"第 {draw_num} 期中奖检查：{level}，奖金 {amount} 元"
            
        # Lottery review task (dlt_review_draw)
        if "top_prize_level" in parsed and "draw_num" in parsed:
            draw_num = parsed.get("draw_num")
            level = parsed.get("top_prize_level")
            amount = parsed.get("fixed_prize_amount", 0)
            report = parsed.get("report_text", "")
            if report:
                return report[:4000]
            return f"第 {draw_num} 期复盘完成。最高奖项: {level}，固定奖金: {amount} 元"
            
        # Lottery store plan task (dlt_store_plan)
        if "tickets_written" in parsed and "plan_id" in parsed:
            plan_id = parsed.get("plan_id")
            count = parsed.get("tickets_written", 0)
            cost = parsed.get("total_cost", 0)
            return f"计划 {plan_id} 已入库。共写入 {count} 张彩票，总成本 {cost} 元"

        # General dict fallback: compact JSON
        try:
            return json.dumps(parsed, ensure_ascii=False)[:4000]
        except Exception:
            pass

    for text in (stdout, stderr):
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if lines:
            return lines[-1][:4000]
    return "运行成功" if status == "success" else "运行失败"


def parse_result_payload(stdout: str, stderr: str, status: str) -> dict[str, Any]:
    parsed = _parse_json(stdout)
    if isinstance(parsed, dict):
        return parsed
    if parsed is not None:
        return {"value": parsed}
    return {"status": status, "stdout": stdout[-4000:], "stderr": stderr[-4000:]}


def _parse_json(stdout: str) -> Any:
    stripped = stdout.strip()
    if not stripped:
        return None
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        # Extract the JSON substring between the first '{' and the last '}'
        start = stripped.find('{')
        end = stripped.rfind('}')
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(stripped[start:end+1])
            except json.JSONDecodeError:
                pass
        return None


def check_run_has_alert(status: str, summary: str, result_payload: Any) -> bool:
    if status != "success":
        return True
    if _payload_has_alert(result_payload):
        return True
    if _text_has_alert(summary):
        return True
    return False


def _payload_has_alert(value: Any) -> bool:
    if isinstance(value, dict):
        status = str(value.get("status") or "").strip().lower()
        if status == "alert":
            return True
        for key, item in value.items():
            key_text = str(key).lower()
            if key_text.endswith("alert") and item is True:
                return True
            if _payload_has_alert(item):
                return True
        return False
    if isinstance(value, list):
        return any(_payload_has_alert(item) for item in value)
    if isinstance(value, str):
        return _text_has_alert(value)
    return False


def _text_has_alert(value: str) -> bool:
    alert_words = ("报警", "告警", "异常")
    return any(word in value for word in alert_words)


def adjust_command(cmd: list[str], project_root: str | Path) -> list[str]:
    if not cmd:
        return cmd
    cmd = list(cmd)
    import sys
    if cmd[0] == "python3" and sys.platform == "win32":
        cmd[0] = sys.executable or "python"

    if cmd[0] == "bash" and sys.platform == "win32":
        if len(cmd) >= 2 and "fb_yesterday_summary.sh" in cmd[1]:
            js_path = str(Path(cmd[1]).with_suffix(".js"))
            state_file = str(Path("state/facebook/fb_storage_state.json"))
            output_dir = str(Path("tmp/fb_yesterday_summary"))
            config_file = str(Path("state/facebook/fb_groups.json"))
            new_cmd = ["node", js_path, "--state-file", state_file, "--output-dir", output_dir, "--config", config_file]
            new_cmd.extend(cmd[2:])
            return new_cmd

    first = cmd[0].lower()
    is_python = (
        first in ("python", "python3", "pythonw") or
        first.endswith(("/python", "\\python", "/python.exe", "\\python.exe", "/pythonw.exe", "\\pythonw.exe"))
    )
    if is_python and len(cmd) >= 3 and cmd[1] == "-m":
        module_name = cmd[2]
        if module_name.startswith("traeclaw.") or module_name == "traeclaw":
            bootstrap = (
                f"import sys; "
                f"sys.path.insert(0, {str(project_root)!r}); "
                f"from {module_name} import main; "
                f"sys.exit(main(sys.argv[1:]))"
            )
            return [cmd[0], "-c", bootstrap] + cmd[3:]
        elif module_name == "pytest":
            bootstrap = (
                f"import sys; "
                f"sys.path.insert(0, {str(project_root)!r}); "
                f"import pytest; "
                f"sys.exit(pytest.main(sys.argv[1:]))"
            )
            return [cmd[0], "-c", bootstrap] + cmd[3:]
    return cmd
