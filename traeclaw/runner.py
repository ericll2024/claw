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
        "code/state/mfdb/takeout_business_analysis_check_config.json",
    ],
    "mfood.market_business_analysis": [
        "code/state/mfdb/market_business_analysis_check_config.json",
    ],
    "mfood.merchant_summary": [
        "code/state/mfdb/merchant_summary_check_config.json",
    ],
    "mfood.market_summary": [
        "code/state/mfdb/market_summary_check_config.json",
    ],
    "facebook.yesterday_summary": [
        "code/state/facebook/fb_groups.json",
        "code/state/facebook/fb_storage_state.json",
    ],
}


class TaskRunner:
    def __init__(self, db: AppDatabase, project_root: str | Path):
        self.db = db
        self.project_root = Path(project_root)

    def run(self, task: TaskDefinition, trigger_type: str = "manual", send_to_telegram: bool = False) -> dict[str, Any]:
        run_id = self.db.start_run(task.id, trigger_type)
        stdout = ""
        stderr = ""
        exit_code: int | None = None
        status = "failed"

        # Write files from DB to filesystem
        files_to_sync = TASK_FILE_MAP.get(task.id, [])
        for rel_path in files_to_sync:
            content = self.db.get_setting(f"file:{rel_path}", "")
            if content:
                file_path = self.project_root / rel_path
                file_path.parent.mkdir(parents=True, exist_ok=True)
                file_path.write_text(content, encoding="utf-8")

        try:
            completed = subprocess.run(
                list(task.command),
                cwd=self.project_root,
                env=self._env(),
                capture_output=True,
                text=True,
                timeout=task.timeout_seconds,
                check=False,
            )
            stdout = completed.stdout or ""
            stderr = completed.stderr or ""
            exit_code = completed.returncode
            status = "success" if completed.returncode == 0 else "failed"
        except subprocess.TimeoutExpired as exc:
            stdout = exc.stdout or ""
            stderr = (exc.stderr or "") + f"\nTask timed out after {task.timeout_seconds}s"
            exit_code = None
            status = "failed"
        except Exception as exc:
            stderr = str(exc)
            status = "failed"
        finally:
            # Sync files back to DB and delete from disk
            for rel_path in files_to_sync:
                file_path = self.project_root / rel_path
                if file_path.exists():
                    try:
                        content = file_path.read_text(encoding="utf-8")
                        self.db.set_setting(f"file:{rel_path}", content)
                        file_path.unlink()
                        # Clean up empty parent directories up to code/state
                        parent = file_path.parent
                        while parent != self.project_root / "code" / "state" and parent != self.project_root:
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
            notify_status, notify_error = self._notify_if_configured(task, status, summary)
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
            "notify_status": notify_status,
            "notify_error": notify_error,
        }

    def _env(self) -> dict[str, str]:
        env = os.environ.copy()
        code_dir = Path(__file__).resolve().parents[1]
        existing = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = str(code_dir) if not existing else f"{code_dir}{os.pathsep}{existing}"
        env["TRAECLAW_DB_PATH"] = str(self.db.path)
        env["TRAECLAW_PROJECT_ROOT"] = str(self.project_root)
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
            return str(parsed["summary_text"])[:500]
        if parsed.get("message"):
            return str(parsed["message"])[:500]
        
        # Lottery fetch task (dlt_fetch)
        if "inserted" in parsed and "db_total" in parsed:
            inserted = parsed.get("inserted", 0)
            updated = parsed.get("updated", 0)
            db_total = parsed.get("db_total", 0)
            latest = parsed.get("latest") or []
            latest_line = f"。最新一期: {latest[0]}" if latest else ""
            return f"拉取完成，新增 {inserted} 条，更新 {updated} 条，共 {db_total} 条{latest_line}"[:500]
            
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
                return report[:500]
            return f"第 {draw_num} 期复盘完成。最高奖项: {level}，固定奖金: {amount} 元"
            
        # Lottery store plan task (dlt_store_plan)
        if "tickets_written" in parsed and "plan_id" in parsed:
            plan_id = parsed.get("plan_id")
            count = parsed.get("tickets_written", 0)
            cost = parsed.get("total_cost", 0)
            return f"计划 {plan_id} 已入库。共写入 {count} 张彩票，总成本 {cost} 元"

        # General dict fallback: compact JSON
        try:
            return json.dumps(parsed, ensure_ascii=False)[:500]
        except Exception:
            pass

    for text in (stdout, stderr):
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if lines:
            return lines[-1][:500]
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
