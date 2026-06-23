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
        self.state_dir = self.project_root / "data" / "mfood_login"
        self.script_path = Path(__file__).resolve().parent / "vendor" / "get_mfood_token.js"

    def validate_token(self, token: str) -> tuple[bool, str]:
        import time
        import uuid
        import hashlib
        import hmac
        import base64
        import urllib.request
        import urllib.error

        if not token:
            return False, "Token is empty"

        url = "https://management-api.mfoodapp.com/managers/orgs/users/_getName"
        timestamp = str(int(time.time() * 1000))
        nonce = hashlib.md5((uuid.uuid4().hex + timestamp).encode("utf-8")).hexdigest()

        scope = "manager"
        client = "web"
        client_version = "9.0.0"
        ca_secret = "5fde65edc94340458a4411d412bdc454"

        canonical = (
            "POST\n"
            f"x-ca-timestamp:{timestamp}\n"
            f"x-ca-nonce:{nonce}\n"
            f"x-scope:{scope}\n"
            f"x-client:{client}\n"
            f"x-client-version:{client_version}\n"
        )
        signature = base64.b64encode(
            hmac.new(ca_secret.encode("utf-8"), canonical.encode("utf-8"), hashlib.sha256).digest()
        ).decode("utf-8")

        headers = {
            "accept": "application/json",
            "content-type": "application/json;charset=UTF-8",
            "origin": "https://manager.mfoodapp.com",
            "referer": "https://manager.mfoodapp.com/",
            "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36",
            "x-app-code-name": "Mozilla",
            "x-app-name": "Netscape",
            "x-app-version": "5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36",
            "x-browser-language": "zh",
            "x-ca-key": "83579288",
            "x-ca-nonce": nonce,
            "x-ca-signature": signature,
            "x-ca-timestamp": timestamp,
            "x-city-id": "",
            "x-city-name": "",
            "x-client": client,
            "x-client-version": client_version,
            "x-ip": "",
            "x-platform": "MacIntel",
            "x-scope": scope,
            "x-token": token,
            "x-user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36",
        }

        req = urllib.request.Request(url, data=b"", headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                res_body = resp.read().decode("utf-8")
                data = json.loads(res_body)

                code = data.get("code")
                if isinstance(code, int) and code < 0:
                    return False, data.get("note") or data.get("message") or f"API error code {code}"
                if isinstance(code, str) and code.startswith("-"):
                    return False, data.get("note") or data.get("message") or f"API error code {code}"

                payloads = [data, data.get("data"), data.get("result")]
                for p in payloads:
                    if isinstance(p, dict):
                        user_name = p.get("userName") or p.get("name") or p.get("userId")
                        if user_name:
                            return True, str(user_name)
                return True, "Success"
        except urllib.error.HTTPError as exc:
            try:
                err_body = exc.read().decode("utf-8")
                err_data = json.loads(err_body)
                msg = err_data.get("note") or err_data.get("message") or f"HTTP Error {exc.code}"
                return False, msg
            except Exception:
                return False, f"HTTP Error {exc.code}"
        except Exception as exc:
            return False, str(exc)

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

    def get_valid_token(self) -> str:
        token = self.db.get_setting("mfood.login.token", "").strip()
        if not token:
            raise RuntimeError("mFood Token 未配置，請至系統設定頁面點擊「登錄 mFood」重新獲取")
        ok, msg = self.validate_token(token)
        if ok:
            return token
        raise RuntimeError(f"mFood Token 已失效（原因：{msg}），請至系統設定頁面重新登錄")


def main(argv: list[str] | None = None) -> int:
    root = Path(os.environ.get("TRAECLAW_PROJECT_ROOT", Path(__file__).resolve().parents[3])).resolve()
    db_path = Path(os.environ.get("TRAECLAW_DB_PATH", root / "data" / "traeclaw.sqlite3"))
    force = "--force-refresh" in (argv if argv is not None else sys.argv[1:])
    db = AppDatabase(db_path)
    db.initialize()
    print(json.dumps(MFoodLogin(db, root).get_token(force_refresh=force), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
