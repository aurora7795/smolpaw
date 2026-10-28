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
SUMMARY_WAIT_SECONDS = 120.0
MAX_STARTED = 1000


class Scheduler:
    def __init__(self, session, approvals, poll: float = POLL_SECONDS,
                 clock: Callable[[], datetime] = datetime.now,
                 schedule_timeout: float | None = None,
                 summary_wait: float = SUMMARY_WAIT_SECONDS):
        self.session, self.approvals = session, approvals
        self.poll, self.clock = poll, clock
        self.summary_wait = float(summary_wait)
        self._stop = threading.Event()
        self._last_error = ""
        self._summary_since: datetime | None = None
        self._started: dict[str, str] = {}
        self._max_started: int = MAX_STARTED
        if schedule_timeout is not None:
            self.session.schedule_timeout = float(schedule_timeout)

    @property
    def started(self) -> dict[str, str]:
        return self._started

    def _prune_started(self) -> None:
        try:
            current = {s["id"]: s.get("next_run") for s in schedules.load() if isinstance(s, dict) and "id" in s}
            for sid, next_run in list(self._started.items()):
                if sid not in current or current[sid] != next_run:
                    del self._started[sid]
        except Exception:
            pass
        while len(self._started) > self._max_started:
            self._started.pop(next(iter(self._started)))

    def tick(self) -> str | None:
        """Start the oldest due schedule if nothing else is running; return its id, else None."""
        summarizing = getattr(self.session, "summarizing", False)
        if not summarizing:  # before the early return, or a stale start would cut the next summary's wait short
            self._summary_since = None
        if self.session.status == "running" or self.approvals.pending:
            return None
        now = self.clock()
        if summarizing:
            if self._summary_since is None:
                self._summary_since = now
            if (now - self._summary_since).total_seconds() < self.summary_wait:
                return None

        self._prune_started()

        try:
            due = sorted(schedules.due(now), key=lambda s: datetime.fromisoformat(s["next_run"]))
            due = [s for s in due if self._started.get(s["id"]) != s["next_run"]]
            if not due:
                self._last_error = ""
                return None
            chosen = due[0]
            if not self.session.start(chosen["prompt"], schedule=chosen["id"]):
                return None  # an interactive run got in first; the schedule stays due
            self._started[chosen["id"]] = chosen["next_run"]
            self._prune_started()
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
