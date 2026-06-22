from __future__ import annotations

import json
import mimetypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from .app import TraeclawApp


class TraeclawRequestHandler(BaseHTTPRequestHandler):
    app: TraeclawApp

    def log_message(self, format: str, *args: Any) -> None:
        return

    def is_authenticated(self) -> bool:
        import os
        if os.environ.get("TRAECLAW_TESTING") == "1" and self.headers.get("X-Test-Force-Auth") != "1":
            return True

        cookie_header = self.headers.get("Cookie")
        token = None
        if cookie_header:
            from http.cookies import SimpleCookie
            try:
                cookie = SimpleCookie(cookie_header)
                if "token" in cookie:
                    token = cookie["token"].value
            except Exception:
                pass

        if not token:
            auth_header = self.headers.get("Authorization")
            if auth_header and auth_header.startswith("Bearer "):
                token = auth_header[len("Bearer ") :]

        if not token:
            return False

        from datetime import datetime, timezone
        try:
            sessions_str = self.app.db.get_setting("login.session_tokens", "[]")
            sessions = json.loads(sessions_str)
            now = datetime.now(timezone.utc).isoformat()

            valid_sessions = []
            is_valid = False
            for s in sessions:
                if s.get("expires_at", "") > now:
                    valid_sessions.append(s)
                    if s.get("token") == token:
                        is_valid = True

            if len(valid_sessions) != len(sessions):
                self.app.db.set_setting("login.session_tokens", json.dumps(valid_sessions))

            return is_valid
        except Exception:
            return False

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path

        # Check authentication for non-public paths
        is_html_request = path in {"", "/", "/settings", "/index.html", "/settings.html"}
        is_api_request = path.startswith("/api/")

        if (is_html_request or is_api_request) and path != "/api/login":
            if not self.is_authenticated():
                if is_api_request:
                    self.write_json({"error": "Unauthorized"}, status=401)
                else:
                    self.send_response(302)
                    self.send_header("Location", "/login")
                    self.end_headers()
                return

        if path == "/login" and self.is_authenticated():
            self.send_response(302)
            self.send_header("Location", "/")
            self.end_headers()
            return

        if path == "/api/tasks":
            self.write_json({"tasks": self.app.list_task_cards(), "agents": self.app.list_agent_cards()})
            return
        if path.startswith("/api/tasks/") and path.endswith("/config"):
            task_id = unquote(path[len("/api/tasks/") : -len("/config")])
            from .runner import TASK_FILE_MAP
            files = TASK_FILE_MAP.get(task_id, [])
            if files:
                config_key = f"file:{files[0]}"
                content = self.app.db.get_setting(config_key, "")
                if not content:
                    try:
                        with open(self.app.project_root / files[0], "r", encoding="utf-8") as f:
                            content = f.read()
                    except Exception:
                        if task_id == "mfood.order_monitor":
                            content = '{\n  "takeout_threshold": 300,\n  "market_threshold": 300\n}'
                        else:
                            content = "{}"
                self.write_json({
                    "task_id": task_id,
                    "config_key": config_key,
                    "config_content": content,
                    "has_config": True
                })
            else:
                self.write_json({
                    "task_id": task_id,
                    "config_key": None,
                    "config_content": None,
                    "has_config": False
                })
            return
        if path.startswith("/api/task-groups/") and path.endswith("/runs"):
            agent_id = unquote(path[len("/api/task-groups/") : -len("/runs")])
            query_params = parse_qs(parsed.query)
            limit = _parse_limit(query_params.get("limit", ["10"])[0])
            offset_val = query_params.get("offset", ["0"])[0]
            try:
                offset = int(offset_val)
            except ValueError:
                offset = 0
            try:
                self.write_json(self.app.list_agent_runs(agent_id, limit=limit, offset=offset))
            except KeyError as exc:
                self.write_json({"error": str(exc)}, status=404)
            except ValueError as exc:
                self.write_json({"error": str(exc)}, status=400)
            return
        if path == "/api/settings/telegram":
            self.write_json({"settings": self.app.get_telegram_settings()})
            return
        if path == "/api/settings/ai":
            self.write_json({"settings": self.app.get_ai_settings()})
            return
        if path == "/api/telegram/listener":
            self.write_json({"listener": self.app.get_telegram_listener()})
            return
        if path == "/api/telegram/ai-jobs":
            self.write_json({"jobs": self.app.list_ai_jobs(limit=50)})
            return
        if path == "/api/settings/mfood":
            self.write_json({"settings": self.app.get_mfood_settings()})
            return
        self.serve_static(path)

    def do_POST(self) -> None:
        path = urlparse(self.path).path

        if path == "/api/login":
            payload = self.read_json()
            password = payload.get("password", "")

            # Fetch MD5 hash from settings database
            db_hash = self.app.db.get_setting("login.password_md5", "23feb120658a1cb2c5b0be2be826bbc9")

            # MD5 check
            import hashlib
            input_hash = hashlib.md5(password.encode('utf-8')).hexdigest()

            if input_hash == db_hash or password == db_hash:
                import secrets
                from datetime import datetime, timedelta, timezone
                token = secrets.token_hex(24)
                expires_at = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()

                # Save token to db
                sessions_str = self.app.db.get_setting("login.session_tokens", "[]")
                try:
                    sessions = json.loads(sessions_str)
                except Exception:
                    sessions = []
                sessions.append({"token": token, "expires_at": expires_at})
                self.app.db.set_setting("login.session_tokens", json.dumps(sessions))

                # Return success and set cookie
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Set-Cookie", f"token={token}; Path=/; Max-Age=604800; SameSite=Strict")
                self.end_headers()
                self.wfile.write(json.dumps({"ok": True, "token": token}).encode("utf-8"))
            else:
                self.write_json({"error": "密码不正确"}, status=401)
            return

        # Check authentication for other POST paths
        if not self.is_authenticated():
            self.write_json({"error": "Unauthorized"}, status=401)
            return

        if path == "/api/logout":
            cookie_header = self.headers.get("Cookie")
            token = None
            if cookie_header:
                from http.cookies import SimpleCookie
                try:
                    cookie = SimpleCookie(cookie_header)
                    if "token" in cookie:
                        token = cookie["token"].value
                except Exception:
                    pass

            if not token:
                auth_header = self.headers.get("Authorization")
                if auth_header and auth_header.startswith("Bearer "):
                    token = auth_header[len("Bearer ") :]

            if token:
                sessions_str = self.app.db.get_setting("login.session_tokens", "[]")
                try:
                    sessions = json.loads(sessions_str)
                    sessions = [s for s in sessions if s.get("token") != token]
                    self.app.db.set_setting("login.session_tokens", json.dumps(sessions))
                except Exception:
                    pass

            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Set-Cookie", "token=; Path=/; Max-Age=0; SameSite=Strict")
            self.end_headers()
            self.wfile.write(json.dumps({"ok": True}).encode("utf-8"))
            return

        if path == "/api/agents/reorder":
            payload = self.read_json()
            order = payload.get("order") or []
            self.app.save_agent_order(order)
            self.write_json({"ok": True})
            return
        if path == "/api/tasks/reorder":
            payload = self.read_json()
            agent_id = payload.get("agent_id")
            order = payload.get("order") or []
            if agent_id:
                self.app.save_task_order(agent_id, order)
            self.write_json({"ok": True})
            return
        if path == "/api/settings/telegram":
            payload = self.read_json()
            settings = self.app.save_telegram_settings(payload)
            self.write_json({"settings": settings})
            return
        if path == "/api/settings/ai":
            payload = self.read_json()
            settings = self.app.save_ai_settings(payload)
            self.write_json({"settings": settings})
            return
        if path == "/api/settings/ai/test":
            payload = self.read_json()
            try:
                result = self.app.test_ai_settings(payload)
            except ValueError as exc:
                self.write_json({"error": str(exc)}, status=400)
                return
            except Exception as exc:
                self.write_json({"error": str(exc)}, status=502)
                return
            self.write_json({"result": result})
            return
        if path == "/api/telegram/listener":
            payload = self.read_json()
            try:
                listener = self.app.save_telegram_listener(payload)
            except ValueError as exc:
                self.write_json({"error": str(exc)}, status=400)
                return
            self.write_json({"listener": listener})
            return
        if path == "/api/telegram/listener/poll":
            try:
                listener = self.app.poll_telegram_listener()
            except ValueError as exc:
                self.write_json({"error": str(exc)}, status=400)
                return
            except Exception as exc:
                self.write_json({"error": str(exc)}, status=502)
                return
            self.write_json({"listener": listener})
            return
        if path.startswith("/api/telegram/ai-jobs/") and path.endswith("/retry"):
            job_id_text = path[len("/api/telegram/ai-jobs/") : -len("/retry")]
            try:
                job_id = int(job_id_text)
                job = self.app.retry_ai_job(job_id)
            except ValueError:
                self.write_json({"error": "Invalid AI job ID"}, status=400)
                return
            except KeyError as exc:
                self.write_json({"error": str(exc)}, status=404)
                return
            except Exception as exc:
                self.write_json({"error": str(exc)}, status=500)
                return
            self.write_json({"job": job})
            return
        if path == "/api/settings/mfood":
            payload = self.read_json()
            settings = self.app.save_mfood_settings(payload)
            self.write_json({"settings": settings})
            return
        if path == "/api/settings/mfood/check":
            res = self.app.check_mfood_token()
            self.write_json(res)
            return
        if path == "/api/settings/mfood/login":
            res = self.app.login_mfood()
            if not res.get("ok"):
                self.write_json({"error": res.get("error", "Login failed")}, status=500)
            else:
                self.write_json(res)
            return

        if path.startswith("/api/task-groups/") and path.endswith("/alias"):
            agent_id = unquote(path[len("/api/task-groups/") : -len("/alias")])
            payload = self.read_json()
            try:
                task_group = self.app.save_agent_alias(agent_id, payload)
            except KeyError as exc:
                self.write_json({"error": str(exc)}, status=404)
                return
            except ValueError as exc:
                self.write_json({"error": str(exc)}, status=400)
                return
            self.write_json({"task": task_group})
            return
        if path.startswith("/api/tasks/") and path.endswith("/schedule"):
            task_id = unquote(path[len("/api/tasks/") : -len("/schedule")])
            payload = self.read_json()
            try:
                schedule = self.app.save_task_schedule(task_id, payload)
            except KeyError as exc:
                self.write_json({"error": str(exc)}, status=404)
                return
            except ValueError as exc:
                self.write_json({"error": str(exc)}, status=400)
                return
            self.write_json({"schedule": schedule})
            return
        if path.startswith("/api/tasks/") and path.endswith("/run"):
            task_id = path[len("/api/tasks/") : -len("/run")]
            payload = self.read_json()
            send_to_telegram = bool(payload.get("send_to_telegram", False))
            try:
                result = self.app.run_task(task_id, trigger_type="manual", send_to_telegram=send_to_telegram)
            except KeyError as exc:
                self.write_json({"error": str(exc)}, status=404)
                return
            self.write_json({"run": result})
            return
        if path.startswith("/api/tasks/") and path.endswith("/enabled"):
            task_id = path[len("/api/tasks/") : -len("/enabled")]
            payload = self.read_json()
            try:
                self.app.set_task_enabled(task_id, bool(payload.get("enabled")))
            except KeyError as exc:
                self.write_json({"error": str(exc)}, status=404)
                return
            self.write_json({"ok": True})
            return
        if path.startswith("/api/runs/") and path.endswith("/delete"):
            try:
                run_id = int(path[len("/api/runs/") : -len("/delete")])
                self.app.delete_run(run_id)
            except ValueError as exc:
                self.write_json({"error": "Invalid run ID"}, status=400)
                return
            self.write_json({"ok": True})
            return
        if path.startswith("/api/tasks/") and path.endswith("/config"):
            task_id = unquote(path[len("/api/tasks/") : -len("/config")])
            payload = self.read_json()
            new_content = payload.get("config_content", "")
            try:
                json.loads(new_content)
            except Exception as exc:
                self.write_json({"error": f"JSON 格式不合法: {str(exc)}"}, status=400)
                return
            from .runner import TASK_FILE_MAP
            files = TASK_FILE_MAP.get(task_id, [])
            if not files:
                self.write_json({"error": "该子任务无需外部配置文件"}, status=400)
                return
            config_key = f"file:{files[0]}"
            self.app.db.set_setting(config_key, new_content)
            self.write_json({"success": True})
            return
        self.write_json({"error": "Not found"}, status=404)

    def read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        raw = self.rfile.read(length).decode("utf-8")
        return json.loads(raw)

    def write_json(self, payload: dict[str, Any], status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def serve_static(self, path: str) -> None:
        web_root = Path(__file__).resolve().parents[1] / "web"
        static_routes = {
            "": "index.html",
            "/": "index.html",
            "/settings": "settings.html",
            "/login": "login.html",
        }
        rel = static_routes.get(path, path.lstrip("/"))
        target = (web_root / rel).resolve()
        if not str(target).startswith(str(web_root.resolve())) or not target.exists():
            self.write_json({"error": "Not found"}, status=404)
            return
        body = target.read_bytes()
        content_type = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        if target.suffix in {".html", ".css", ".js"}:
            content_type += "; charset=utf-8"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def make_server(address: tuple[str, int], app: TraeclawApp) -> ThreadingHTTPServer:
    class Handler(TraeclawRequestHandler):
        pass

    Handler.app = app
    return ThreadingHTTPServer(address, Handler)


def _parse_limit(value: str) -> int | None:
    if value == "all":
        return None
    limit = int(value)
    if limit < 1:
        raise ValueError("Limit must be greater than 0")
    return limit
