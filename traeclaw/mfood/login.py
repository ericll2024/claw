from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from ..db import AppDatabase
from .config import MFoodSettings


class MFoodLogin:
    def __init__(self, db: AppDatabase, project_root: str | Path):
        self.db = db
        self.project_root = Path(project_root)
        self.state_dir = self.project_root / "code" / "data" / "mfood_login"
        self.script_path = Path(__file__).resolve().parent / "vendor" / "get_mfood_token.js"

    def get_token(self, force_refresh: bool = False) -> dict[str, Any]:
        settings = MFoodSettings.load_private(self.db)["login"]
        if not settings["configured"]:
            raise RuntimeError("mFood 信息配置缺失：请填写 password_md5")
        account = settings.get("account") or os.environ.get("MFOOD_ACCOUNT")
        if not account:
            raise RuntimeError("mFood 账号缺失：请设置 MFOOD_ACCOUNT 环境变量")
        self._write_defaults(settings, account)
        args = [
            "node",
            str(self.script_path),
            "--profile",
            settings.get("profile") or "default",
            "--cache-path",
            str(self.state_dir / "cache.json"),
            "--defaults-path",
            str(self.state_dir / "defaults.json"),
            "--format",
            "json",
        ]
        if force_refresh:
            args.append("--force-refresh")
        env = os.environ.copy()
        env["CODEX_HOME"] = str(self.project_root / "code")
        completed = subprocess.run(
            args,
            cwd=self.project_root,
            env=env,
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
        )
        if completed.returncode != 0:
            raise RuntimeError(completed.stderr.strip() or completed.stdout.strip() or "mFood token 获取失败")
        res_data = json.loads(completed.stdout)
        token = res_data.get("token")
        if token:
            self.db.set_setting("mfood.login.token", token, is_secret=True)
        return res_data

    def _write_defaults(self, settings: dict[str, Any], account: str) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        profile = settings.get("profile") or "default"
        payload = {
            "version": 2,
            "defaultProfile": profile,
            "profiles": {
                profile: {
                    "account": account,
                    "passwordMd5": settings["password_md5"],
                }
            },
        }
        path = self.state_dir / "defaults.json"
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        try:
            path.chmod(0o600)
        except OSError:
            pass


def main(argv: list[str] | None = None) -> int:
    root = Path(os.environ.get("TRAECLAW_PROJECT_ROOT", Path(__file__).resolve().parents[3])).resolve()
    db_path = Path(os.environ.get("TRAECLAW_DB_PATH", root / "code" / "data" / "traeclaw.sqlite3"))
    force = "--force-refresh" in (argv if argv is not None else sys.argv[1:])
    db = AppDatabase(db_path)
    db.initialize()
    print(json.dumps(MFoodLogin(db, root).get_token(force_refresh=force), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
