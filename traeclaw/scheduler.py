from __future__ import annotations

import threading
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from .app import TraeclawApp
from .tasks.registry import list_tasks


TZ = ZoneInfo("Asia/Shanghai")


class Scheduler:
    def __init__(self, app: TraeclawApp, poll_seconds: int = 30):
        self.app = app
        self.poll_seconds = poll_seconds
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_run_key: dict[str, str] = {}

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._loop, name="traeclaw-scheduler", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)

    def tick(self, now: datetime | None = None) -> list[str]:
        now = now or datetime.now(TZ)
        ran: list[str] = []
        for task in list_tasks():
            if not self.app.is_task_enabled(task):
                continue
            due_key = self._due_key(task, now)
            if not due_key or self._last_run_key.get(task.id) == due_key:
                continue
            self._last_run_key[task.id] = due_key
            threading.Thread(
                target=self.app.run_task,
                args=(task.id, "schedule"),
                daemon=True,
                name=f"traeclaw-task-{task.id}",
            ).start()
            ran.append(task.id)
        return ran

    def _loop(self) -> None:
        while not self._stop.is_set():
            self.tick()
            self._stop.wait(self.poll_seconds)

    def _due_key(self, task, now: datetime) -> str:
        return self.app.task_due_key(task, now)
