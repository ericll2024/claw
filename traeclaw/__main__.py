from __future__ import annotations

import argparse
import json
from pathlib import Path

from .app import TraeclawApp
from .scheduler import Scheduler
from .server import make_server


def default_project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def build_app(args) -> TraeclawApp:
    root = Path(args.project_root).resolve() if args.project_root else default_project_root()
    db_path = Path(args.db).resolve() if args.db else root / "data" / "traeclaw.sqlite3"
    from .db import AppDatabase

    return TraeclawApp(root, db=AppDatabase(db_path), import_legacy_state=not args.no_import_state)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="claw task dashboard")
    parser.add_argument("--project-root", default="")
    parser.add_argument("--db", default="")
    parser.add_argument("--no-import-state", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    serve = sub.add_parser("serve")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8765)
    serve.add_argument("--no-scheduler", action="store_true")

    sub.add_parser("init-db")
    sub.add_parser("import-state")
    run_task = sub.add_parser("run-task")
    run_task.add_argument("task_id")

    args = parser.parse_args(argv)
    app = build_app(args)

    if args.command == "init-db":
        app.db.initialize()
        print(json.dumps({"ok": True, "db": str(app.db.path)}, ensure_ascii=False))
        return 0

    if args.command == "import-state":
        app.db.initialize()
        print(json.dumps({"imports": app.import_legacy_sources()}, ensure_ascii=False))
        return 0

    app.initialize()
    if args.command == "run-task":
        print(json.dumps(app.run_task(args.task_id), ensure_ascii=False))
        return 0

    scheduler = None
    if not args.no_scheduler:
        scheduler = Scheduler(app)
        scheduler.start()
    app.start_background_services()

    httpd = make_server((args.host, args.port), app)
    url = f"http://{args.host}:{httpd.server_address[1]}"
    print(f"claw running at {url}")
    print(f"Database: {app.db.path}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        app.stop_background_services()
        if scheduler:
            scheduler.stop()
        httpd.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
