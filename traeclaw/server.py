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

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/api/tasks":
            self.write_json({"tasks": self.app.list_task_cards(), "agents": self.app.list_agent_cards()})
            return
        if path.startswith("/api/task-groups/") and path.endswith("/runs"):
            agent_id = unquote(path[len("/api/task-groups/") : -len("/runs")])
            limit = _parse_limit(parse_qs(parsed.query).get("limit", ["10"])[0])
            try:
                self.write_json(self.app.list_agent_runs(agent_id, limit=limit))
            except KeyError as exc:
                self.write_json({"error": str(exc)}, status=404)
            except ValueError as exc:
                self.write_json({"error": str(exc)}, status=400)
            return
        if path == "/api/settings/telegram":
            self.write_json({"settings": self.app.get_telegram_settings()})
            return
        if path == "/api/telegram/listener":
            self.write_json({"listener": self.app.get_telegram_listener()})
            return
        if path == "/api/settings/mfood":
            self.write_json({"settings": self.app.get_mfood_settings()})
            return
        self.serve_static(path)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/agents/reorder":
            payload = self.read_json()
            order = payload.get("order") or []
            self.app.save_agent_order(order)
            self.write_json({"ok": True})
            return
        if path == "/api/settings/telegram":
            payload = self.read_json()
            settings = self.app.save_telegram_settings(payload)
            self.write_json({"settings": settings})
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
        if path == "/api/settings/mfood":
            payload = self.read_json()
            settings = self.app.save_mfood_settings(payload)
            self.write_json({"settings": settings})
            return
        if path == "/api/mfood/login":
            try:
                result = self.app.mfood_login(force_refresh=True)
                self.write_json({"ok": True, "token": result.get("token", "")})
            except Exception as exc:
                self.write_json({"error": str(exc)}, status=400)
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
