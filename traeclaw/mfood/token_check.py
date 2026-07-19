from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from ..db import AppDatabase
from .login import MFoodLogin

TZ = ZoneInfo("Asia/Shanghai")

class MFoodTokenCheck:
    def __init__(self, db: AppDatabase, project_root: str | Path):
        self.db = db
        self.project_root = Path(project_root)

    def run(self) -> dict[str, Any]:
        login_handler = MFoodLogin(self.db, self.project_root)
        token = self.db.get_setting("mfood.login.token", "").strip()
        
        now_str = datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S")
        self.db.set_setting("mfood.login.last_check_time", now_str)

        if not token:
            failures = int(self.db.get_setting("mfood.login.consecutive_failures", "0")) + 1
            self.db.set_setting("mfood.login.consecutive_failures", str(failures))
            return {
                "ok": False,
                "status": "token_missing",
                "message": f"mFood Token 未配置 (连续失败 {failures} 次)",
                "checked_at": now_str,
            }

        ok, msg = login_handler.validate_token(token)
        if ok:
            self.db.set_setting("mfood.login.consecutive_failures", "0")
            return {
                "ok": True,
                "status": "valid",
                "message": f"Token 有效 (用户: {msg})",
                "checked_at": now_str,
            }

        # Token is invalid, try to re-login
        try:
            res = login_handler.get_token(force_refresh=True)
            new_token = res.get("token", "")
            if new_token:
                self.db.set_setting("mfood.login.consecutive_failures", "0")
                return {
                    "ok": True,
                    "status": "relogged",
                    "message": "Token 已失效，自动重新登录成功",
                    "checked_at": now_str,
                }
            else:
                failures = int(self.db.get_setting("mfood.login.consecutive_failures", "0")) + 1
                self.db.set_setting("mfood.login.consecutive_failures", str(failures))
                return {
                    "ok": False,
                    "status": "relogin_no_token",
                    "message": f"Token 已失效，重新登录未返回 Token (连续失败 {failures} 次)",
                    "checked_at": now_str,
                }
        except Exception as exc:
            failures = int(self.db.get_setting("mfood.login.consecutive_failures", "0")) + 1
            self.db.set_setting("mfood.login.consecutive_failures", str(failures))
            return {
                "ok": False,
                "status": "relogin_failed",
                "message": f"Token 已失效且重新登录失败: {str(exc)} (连续失败 {failures} 次)",
                "checked_at": now_str,
            }

def main(argv: list[str] | None = None) -> int:
    root = Path(os.environ.get("TRAECLAW_PROJECT_ROOT", Path(__file__).resolve().parents[3])).resolve()
    db_path = Path(os.environ.get("TRAECLAW_DB_PATH", root / "data" / "traeclaw.sqlite3"))
    db = AppDatabase(db_path)
    db.initialize()
    
    checker = MFoodTokenCheck(db, root)
    result = checker.run()
    
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["ok"] else 1

if __name__ == "__main__":
    raise SystemExit(main())
