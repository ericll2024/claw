from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from .tasks.registry import TaskDefinition


class AiPatchExecutor:
    def __init__(self, project_root: str | Path):
        self.project_root = Path(project_root).resolve()

    def apply(self, task: TaskDefinition, payload: dict[str, Any]) -> dict[str, Any]:
        edits = payload.get("edits") or []
        if not isinstance(edits, list) or not edits:
            return {
                "status": "failed",
                "error": "No edits provided",
                "files_touched": [],
                "verification_status": "",
                "verification_output": "",
                "backups": {},
            }

        backups: dict[str, str | None] = {}
        files_touched: list[str] = []
        try:
            for edit in edits:
                action = str(edit.get("action") or "write").strip().lower()
                if action != "write":
                    return self._fail("Only write edits are allowed")
                rel_path = str(edit.get("path") or "").strip()
                content = str(edit.get("content") or "")
                target = self._resolve_target(task, rel_path)
                if rel_path not in files_touched:
                    files_touched.append(rel_path)
                backups[rel_path] = target.read_text(encoding="utf-8") if target.exists() else None
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content, encoding="utf-8")
            verification_status, verification_output = self._run_verifications(task)
            if verification_status != "passed":
                self.rollback(backups)
                return {
                    "status": "rolled_back",
                    "error": "",
                    "files_touched": files_touched,
                    "verification_status": verification_status,
                    "verification_output": verification_output,
                    "backups": backups,
                }
            return {
                "status": "success",
                "error": "",
                "files_touched": files_touched,
                "verification_status": verification_status,
                "verification_output": verification_output,
                "backups": backups,
            }
        except ValueError as exc:
            self.rollback(backups)
            return self._fail(str(exc))

    def rollback(self, backups: dict[str, str | None]) -> None:
        for rel_path, previous in backups.items():
            target = (self.project_root / rel_path).resolve()
            if previous is None:
                if target.exists():
                    target.unlink()
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(previous, encoding="utf-8")

    def _resolve_target(self, task: TaskDefinition, rel_path: str) -> Path:
        candidate = (self.project_root / rel_path).resolve()
        if not str(candidate).startswith(str(self.project_root)):
            raise ValueError("Path escapes project root")
        allowed_roots = [(self.project_root / allowed).resolve() for allowed in task.editable_paths]
        if not any(self._is_allowed(candidate, allowed) for allowed in allowed_roots):
            raise ValueError(f"Path {rel_path} is outside allowed paths")
        return candidate

    def _is_allowed(self, candidate: Path, allowed: Path) -> bool:
        if candidate == allowed:
            return True
        try:
            candidate.relative_to(allowed)
            return True
        except ValueError:
            return False

    def _run_verifications(self, task: TaskDefinition) -> tuple[str, str]:
        outputs = []
        for command in task.verify_commands:
            completed = subprocess.run(
                list(command),
                cwd=self.project_root,
                capture_output=True,
                text=True,
                timeout=120,
                check=False,
            )
            chunk = (completed.stdout or "") + (completed.stderr or "")
            outputs.append(chunk.strip())
            if completed.returncode != 0:
                return "failed", "\n".join(part for part in outputs if part).strip()
        return "passed", "\n".join(part for part in outputs if part).strip()

    def _fail(self, error: str) -> dict[str, Any]:
        return {
            "status": "failed",
            "error": error,
            "files_touched": [],
            "verification_status": "",
            "verification_output": "",
            "backups": {},
        }
