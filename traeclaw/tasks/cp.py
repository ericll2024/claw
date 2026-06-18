from __future__ import annotations

import argparse
import json
import os
import sqlite3
import subprocess
import sys
import types
from pathlib import Path
from typing import Any


def project_root() -> Path:
    if os.environ.get("TRAECLAW_PROJECT_ROOT"):
        return Path(os.environ["TRAECLAW_PROJECT_ROOT"]).resolve()
    return Path(__file__).resolve().parents[3]


def db_path() -> Path:
    if os.environ.get("TRAECLAW_DB_PATH"):
        return Path(os.environ["TRAECLAW_DB_PATH"]).resolve()
    return project_root() / "code" / "data" / "traeclaw.sqlite3"


def _load_cp_core():
    scripts_dir = project_root() / "code" / "scripts" / "cp"
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))
    import backtest_ssq  # type: ignore

    backtest_ssq.DB_PATH = str(db_path())
    module_path = scripts_dir / "cp_prediction_core.py"
    module = types.ModuleType("cp_prediction_core")
    module.__file__ = str(module_path)
    sys.modules["cp_prediction_core"] = module
    source = module_path.read_text(encoding="utf-8")
    code = compile("from __future__ import annotations\n" + source, str(module_path), "exec")
    exec(code, module.__dict__)
    module.DB_PATH = str(db_path())
    module.PRED_LOG = Path("/dev/null")
    return module


def predict(force: bool = False) -> dict[str, Any]:
    core = _load_cp_core()
    with sqlite3.connect(db_path()) as conn:
        result = core.create_predictions(conn, force=force)
    result["summary_text"] = _prediction_summary(result)
    return result


def fetch_latest() -> dict[str, Any]:
    script = project_root() / "code" / "scripts" / "cp" / "fetch_ssq.py"
    completed = subprocess.run(
        [
            sys.executable,
            str(script),
            "--db",
            str(db_path()),
            "--mode",
            "latest",
            "--latest-pages",
            "1",
        ],
        cwd=project_root(),
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    if completed.returncode != 0:
        return {
            "mode": "fetch_failed",
            "returncode": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
            "summary_text": completed.stderr.strip() or "CP 开奖数据拉取失败",
        }
    try:
        result = json.loads(completed.stdout)
    except json.JSONDecodeError:
        result = {"mode": "fetch_output", "stdout": completed.stdout}
    result["summary_text"] = _fetch_summary(result)
    return result


def check_result() -> dict[str, Any]:
    fetch_result = fetch_latest()
    core = _load_cp_core()
    with sqlite3.connect(db_path()) as conn:
        settle_result = core.get_issue_report(conn)
    settle_result["fetch"] = fetch_result
    settle_result["summary_text"] = _settle_summary(settle_result)
    return settle_result


def _prediction_summary(result: dict[str, Any]) -> str:
    prefix = "已存在" if result.get("mode") == "existing" else "已生成"
    lines = [f"第 {result.get('issue_code', '')} 期预测{prefix}。"]
    for plan in result.get("plans", [])[:4]:
        summary = plan.get("summary") or {}
        sample = (summary.get("sample_reds") or [""])[0]
        lines.append(
            f"{summary.get('label', plan.get('plan_type'))}: 红球 {sample}，"
            f"蓝球 {summary.get('blues', '')}，成本 {summary.get('cost', 0)} 元"
        )
    return "\n".join(lines)


def _fetch_summary(result: dict[str, Any]) -> str:
    latest = result.get("latest") or []
    line = latest[0] if latest else "暂无最新数据"
    return f"双色球已更新，新增 {result.get('inserted', 0)} 条，库内共 {result.get('db_total', 0)} 条。最新一期: {line}"


def _settle_summary(result: dict[str, Any]) -> str:
    mode = result.get("mode")
    if mode in {"settled", "already_settled"}:
        draw = result.get("draw") or {}
        issue = result.get("issue_code", "")
        if draw:
            reds = ",".join(f"{x:02d}" for x in draw.get("reds", []))
            blue = draw.get("blue", "")
            return f"第 {issue} 期复盘完成，开奖号码：红球 {reds}，蓝球 {int(blue):02d}"
        return f"第 {issue} 期复盘完成"
    if mode == "waiting":
        return f"第 {result.get('issue_code', '')} 期开奖数据尚未入库"
    return f"复盘状态：{mode or 'unknown'}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="CP task wrapper using shared Traeclaw DB")
    sub = parser.add_subparsers(dest="command", required=True)
    predict_parser = sub.add_parser("predict")
    predict_parser.add_argument("--force", action="store_true")
    sub.add_parser("fetch-latest")
    sub.add_parser("check-result")
    args = parser.parse_args(argv)

    if args.command == "predict":
        result = predict(force=args.force)
    elif args.command == "fetch-latest":
        result = fetch_latest()
    else:
        result = check_result()
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
