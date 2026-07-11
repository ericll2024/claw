from __future__ import annotations

import subprocess
from pathlib import Path

from traeclaw.tasks import cp


def test_default_project_root_is_standalone_repo(monkeypatch):
    monkeypatch.delenv("TRAECLAW_PROJECT_ROOT", raising=False)

    expected = Path(__file__).resolve().parents[1]
    assert cp.project_root() == expected
    assert cp.scripts_dir() == expected / "scripts" / "cp"
    assert (cp.scripts_dir() / "fetch_ssq.py").is_file()


def test_outer_project_root_keeps_nested_code_layout_compatibility(monkeypatch, tmp_path):
    nested = tmp_path / "code"
    (nested / "scripts" / "cp").mkdir(parents=True)
    (nested / "data").mkdir()
    monkeypatch.setenv("TRAECLAW_PROJECT_ROOT", str(tmp_path))

    assert cp.project_root() == tmp_path
    assert cp.layout_root() == nested
    assert cp.scripts_dir() == nested / "scripts" / "cp"
    assert cp.db_path() == nested / "data" / "traeclaw.sqlite3"


def test_fetch_timeout_returns_structured_failure(monkeypatch, tmp_path):
    (tmp_path / "scripts" / "cp").mkdir(parents=True)
    monkeypatch.setenv("TRAECLAW_PROJECT_ROOT", str(tmp_path))

    def raise_timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], 180, output="partial", stderr="slow")

    monkeypatch.setattr(cp.subprocess, "run", raise_timeout)

    result = cp.fetch_latest()

    assert result["mode"] == "fetch_failed"
    assert result["error_type"] == "timeout"
    assert result["stdout"] == "partial"
    assert result["stderr"] == "slow"
    assert "超时" in result["summary_text"]


def test_fetch_start_failure_returns_structured_failure(monkeypatch, tmp_path):
    (tmp_path / "scripts" / "cp").mkdir(parents=True)
    monkeypatch.setenv("TRAECLAW_PROJECT_ROOT", str(tmp_path))

    def raise_os_error(*args, **kwargs):
        raise OSError("python unavailable")

    monkeypatch.setattr(cp.subprocess, "run", raise_os_error)

    result = cp.fetch_latest()

    assert result["mode"] == "fetch_failed"
    assert result["error_type"] == "os_error"
    assert result["stderr"] == "python unavailable"
    assert "启动失败" in result["summary_text"]
