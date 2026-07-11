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
    for candidate in Path(__file__).resolve().parents:
        if (candidate / "traeclaw").is_dir() and (candidate / "scripts" / "cp").is_dir():
            return candidate
    return Path(__file__).resolve().parents[2]


def layout_root() -> Path:
    root = project_root()
    if (root / "scripts" / "cp").is_dir():
        return root
    nested = root / "code"
    if (nested / "scripts" / "cp").is_dir():
        return nested
    return root


def scripts_dir() -> Path:
    return layout_root() / "scripts" / "cp"


def db_path() -> Path:
    if os.environ.get("TRAECLAW_DB_PATH"):
        return Path(os.environ["TRAECLAW_DB_PATH"]).resolve()
    return layout_root() / "data" / "traeclaw.sqlite3"


def _load_cp_core():
    cp_scripts = scripts_dir()
    if str(cp_scripts) not in sys.path:
        sys.path.insert(0, str(cp_scripts))
    import backtest_ssq  # type: ignore

    backtest_ssq.DB_PATH = str(db_path())
    module_path = cp_scripts / "cp_prediction_core.py"
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
    script = scripts_dir() / "fetch_ssq.py"
    command = [
        sys.executable,
        str(script),
        "--db",
        str(db_path()),
        "--mode",
        "latest",
        "--latest-pages",
        "1",
    ]
    try:
        completed = subprocess.run(
            command,
            cwd=layout_root(),
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        stdout = _output_text(exc.stdout)
        stderr = _output_text(exc.stderr)
        return {
            "mode": "fetch_failed",
            "returncode": None,
            "error_type": "timeout",
            "stdout": stdout,
            "stderr": stderr,
            "summary_text": "CP 开奖数据拉取超时（180 秒），本地数据库保持不变",
        }
    except OSError as exc:
        return {
            "mode": "fetch_failed",
            "returncode": None,
            "error_type": "os_error",
            "stdout": "",
            "stderr": str(exc),
            "summary_text": "CP 开奖数据拉取进程启动失败，本地数据库保持不变",
        }
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


def _output_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def check_result() -> dict[str, Any]:
    fetch_result = fetch_latest()
    core = _load_cp_core()
    with sqlite3.connect(db_path()) as conn:
        settle_result = core.get_issue_report(conn)
    settle_result["fetch"] = fetch_result
    settle_result["summary_text"] = _settle_summary(settle_result)
    return settle_result


def _prediction_summary(result: dict[str, Any]) -> str:
    lines = [f"第 {result.get('issue_code', '')} 期预测"]
    label_map = {
        "main": " 8+1:  ",
        "reference": " 9+1:  ",
        "budget_500": "10+1: ",
        "budget_1000": "11+1: "
    }
    for plan in result.get("plans", [])[:4]:
        pt = plan.get("plan_type")
        label = label_map.get(pt, f"{pt}: ")
        summary = plan.get("summary") or {}
        sample = (summary.get("sample_reds") or [""])[0]
        lines.append(
            f"{label}红球 {sample}，蓝球 {summary.get('blues', '')}，成本 {summary.get('cost', 0)} 元"
        )
    return "\n".join(lines)


def _fetch_summary(result: dict[str, Any]) -> str:
    latest = result.get("latest") or []
    line = latest[0] if latest else "暂无最新数据"
    return f"双色球已更新，新增 {result.get('inserted', 0)} 条，库内共 {result.get('db_total', 0)} 条。最新一期: {line}"


def _settle_summary(result: dict[str, Any]) -> str:
    mode = result.get("mode")
    if mode not in {"settled", "already_settled"}:
        if mode == "waiting":
            return f"第 {result.get('issue_code', '')} 期开奖数据尚未入库"
        return f"复盘状态：{mode or 'unknown'}"

    draw = result.get("draw") or {}
    issue = result.get("issue_code", "")
    if not draw:
        return f"第 {issue} 期复盘完成"

    reds = ",".join(f"{x:02d}" for x in draw.get("reds", []))
    blue_val = draw.get("blue")
    blue = f"{int(blue_val):02d}" if blue_val is not None else ""

    lines = [
        f"第 {issue} 期复盘",
        f"开奖号码：红球 {reds}｜蓝球 {blue}"
    ]

    label_map = {
        'main': '主推 8+1',
        'reference': '参考 9+1',
        'budget_500': '500元方案',
        'budget_1000': '1000元方案'
    }

    for plan in result.get('plans', []):
        res = plan.get('result') or {}
        summary = plan.get('summary') or {}
        label = label_map.get(plan.get('plan_type'), plan.get('plan_type'))

        sample_reds = summary.get('sample_reds') or ['']
        sample = sample_reds[0] if sample_reds else ''
        blues = summary.get('blues', '')
        cost = res.get('total_cost', summary.get('cost', 0))
        bonus = res.get('total_bonus', 0)

        lines.append(f"\n{label}: 红球 {sample}，蓝球 {blues}，成本 {cost} 元")
        lines.append(f"中獎金額：{bonus}元")

    return "\n".join(lines)


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
