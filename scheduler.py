"""Runs due schedules (see schedules.py) one at a time, between interactive runs.

The thread only starts a schedule when the Session is idle and no approval prompt is pending, so it never
interrupts a chat. Scheduled runs are read-only: web.Session declines every confirmation (see Session._run).
Console output never includes a schedule's prompt, which may be private.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from datetime import datetime

import schedules

POLL_SECONDS = 30.0


class Scheduler:
    def __init__(self, session, approvals, poll: float = POLL_SECONDS,
                 clock: Callable[[], datetime] = datetime.now,
                 schedule_timeout: float | None = None):
        self.session, self.approvals = session, approvals
        self.poll, self.clock = poll, clock
        self._stop = threading.Event()
        self._last_error = ""
        if schedule_timeout is not None:
            self.session.schedule_timeout = float(schedule_timeout)

    def tick(self) -> str | None:
        """Start the oldest due schedule if nothing else is running; return its id, else None."""
        if self.session.status == "running" or self.approvals.pending:
            return None
        now = self.clock()
        try:
            due = sorted(schedules.due(now), key=lambda s: datetime.fromisoformat(s["next_run"]))
            if not due:
                self._last_error = ""
                return None
            chosen = due[0]
            if not self.session.start(chosen["prompt"], schedule=chosen["id"]):
                return None  # an interactive run got in first; the schedule stays due
            schedules.mark_ran(chosen["id"], now)  # even if the run later errors, so it does not retry every tick
            self._last_error = ""
            return chosen["id"]
        except Exception as exc:  # noqa: BLE001 - a bad schedules.json must not kill the thread
            self._report(f"{type(exc).__name__}: {exc}")
            return None

    def _report(self, message: str) -> None:
        if message != self._last_error:  # one line per distinct error, not one per tick
            self._last_error = message
            print(f"[scheduler] {message}")

    def run(self) -> None:
        while not self._stop.is_set():
            self.tick()
            self._stop.wait(self.poll)

    def start(self) -> threading.Thread:
        thread = threading.Thread(target=self.run, name="scheduler", daemon=True)
        thread.start()
        return thread

    def stop(self) -> None:
        self._stop.set()
