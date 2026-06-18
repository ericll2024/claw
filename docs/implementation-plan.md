# Traeclaw Lite Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use $superpower-subagents (recommended) or $superpower-executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking via update_plan.

**Goal:** Build a small local web app under `code/` that monitors legacy script tasks, stores app data in one shared SQLite database, and lets the user configure Telegram notifications from the web UI.

**Architecture:** Use Python standard library only: a SQLite data layer, a small HTTP server, a background scheduler, task wrappers, and static HTML/CSS/JS. Legacy state databases are imported into `code/data/traeclaw.sqlite3` so new application data is centralized while keeping source `state/` files untouched.

**Tech Stack:** Python 3.9+, sqlite3, http.server, urllib, pytest, vanilla HTML/CSS/JS.

---

### Task 1: Core Data Layer

**Files:**
- Create: `code/traeclaw/db.py`
- Test: `code/tests/test_db.py`

- [ ] Write failing tests for schema creation, setting storage, task run persistence, and legacy SQLite table import.
- [ ] Implement `AppDatabase` with `settings`, `task_runs`, `task_results`, and `legacy_imports` tables.
- [ ] Implement generic `import_sqlite_tables()` that copies old user tables into the shared DB with optional prefixes.
- [ ] Run `python3 -m pytest code/tests/test_db.py -q`.

### Task 2: Task Registry and Scheduler

**Files:**
- Create: `code/traeclaw/tasks/registry.py`
- Create: `code/traeclaw/scheduler.py`
- Test: `code/tests/test_tasks.py`
- Test: `code/tests/test_scheduler.py`

- [ ] Write failing tests for known task definitions, readable schedule labels, next-run computation, and disabled/manual tasks.
- [ ] Register CP prediction and result-check tasks with daily schedule labels, plus mFood, shence, Dida, Facebook, and crowd scripts as visible tasks.
- [ ] Implement a simple scheduler that checks due tasks and delegates execution to a runner.
- [ ] Run focused pytest files.

### Task 3: Task Runner and Telegram

**Files:**
- Create: `code/traeclaw/runner.py`
- Create: `code/traeclaw/telegram.py`
- Create: `code/traeclaw/tasks/cp.py`
- Test: `code/tests/test_runner_telegram.py`

- [ ] Write failing tests for command execution recording, failure recording, Telegram config masking, and notification send URL construction.
- [ ] Implement CP wrappers that use the shared database and avoid writing legacy JSONL logs.
- [ ] Implement Telegram config storage and optional notifications after task runs.
- [ ] Run focused pytest files.

### Task 4: HTTP API and Web UI

**Files:**
- Create: `code/traeclaw/server.py`
- Create: `code/web/index.html`
- Create: `code/web/app.js`
- Create: `code/web/styles.css`
- Test: `code/tests/test_server.py`

- [ ] Write failing tests for `/api/tasks`, `/api/settings/telegram`, and task run API behavior.
- [ ] Implement JSON endpoints and static file serving.
- [ ] Build a dense local dashboard showing task status, schedule, latest result, run history, and Telegram settings.
- [ ] Run focused pytest files.

### Task 5: Entry Points and Verification

**Files:**
- Create: `code/traeclaw/__main__.py`
- Create: `code/README.md`
- Create: `code/run.py`

- [ ] Add CLI commands for `serve`, `init-db`, `import-state`, and `run-task`.
- [ ] Run full `python3 -m pytest code/tests -q`.
- [ ] Start the local server and verify the dashboard in a browser.
