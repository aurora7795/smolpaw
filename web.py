"""
SmolPaw web harness: run the agent and answer its [y/N] prompts and questions from a browser.

  .venv/bin/python web.py --backend ollama --host 0.0.0.0

Open the printed URL; it carries the access token, and every request must present it. The
confirmation rules are unchanged: this only replaces where the prompts are answered.
"""

import argparse
import hmac
import itertools
import json
import math
import os
import re
import secrets
import threading
import time
import urllib.request
from collections.abc import Callable
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import generic_tools as g
import schedules
from agent import BACKENDS, MAX_STEPS, build_agent, load_env, run_request
from scheduler import Scheduler
from smolagents.models import ChatMessage, MessageRole

PORT = 8770
MAX_BODY = 64_000
MAX_PROMPT = 4_000
FEED_LINES = 40
NO_ANSWER = "(no answer from the user in time. Do not ask again; make your best attempt.)"


class Approvals:
    """Prompts waiting for an answer from the browser. The agent blocks until answered, as with input()."""

    def __init__(self, timeout: float = 0):
        self.timeout = timeout  # seconds; 0 waits forever. Unanswered confirms count as "no".
        self._serial = threading.Lock()  # tools can run in parallel threads: one prompt at a time
        self._lock = threading.Lock()
        self._done = threading.Event()
        self._ids = itertools.count(int(time.time() * 1000))  # unique across restarts, so the page never reuses an id
        self._answer: object = None
        self.pending: dict | None = None

    def _wait(self, kind: str, text: str, default: object) -> object:
        with self._serial:
            with self._lock:
                self.pending = {"id": next(self._ids), "kind": kind, "text": g._redact(text)}
                self._answer = None
                self._done.clear()
            answered = self._done.wait(self.timeout or None)
            with self._lock:
                self.pending = None
                return self._answer if answered else default

    def confirm(self, desc: str) -> bool:
        return self._wait("confirm", desc, False) is True

    def ask(self, question: str) -> str:
        answer = self._wait("ask", question, NO_ANSWER)
        return answer if isinstance(answer, str) and answer.strip() else NO_ANSWER

    def answer(self, prompt_id: int, value: object) -> bool:
        """Answer the pending prompt if `prompt_id` is still current; stale answers are refused."""
        with self._lock:
            if not self.pending or self.pending["id"] != prompt_id:
                return False
            kind = self.pending["kind"]
            if kind == "confirm" and not isinstance(value, bool):
                return False
            if kind == "ask" and not isinstance(value, str):
                return False
            self._answer = value[:MAX_PROMPT] if isinstance(value, str) else value
            self._done.set()
            return True

    def cancel(self) -> None:
        """Decline whatever is pending (used by Stop)."""
        with self._lock:
            if self.pending:
                self._answer = False if self.pending["kind"] == "confirm" else NO_ANSWER
                self._done.set()

    def install(self) -> None:
        g.CONFIRM = self.confirm
        g.ASK = self.ask


def summarize_run(prompt: str, answer: str, call_model: Callable[[str], str]) -> str | None:
    """Ask the loaded model for a one-sentence summary (<= 100 chars) of a run."""
    try:
        p = (prompt or "")[:1500]
        a = (answer or "")[:1500]
        query = (
            "Write a one-sentence summary of at most 100 characters for this run.\n\n"
            f"Prompt: {p}\n\n"
            f"Final answer: {a}"
        )
        reply = call_model(query)
        if not reply or not isinstance(reply, str):
            return None
        reply = reply.strip()
        if not reply:
            return None
        first_line = reply.splitlines()[0].strip()
        if not first_line:
            return None
        redacted = g.redact_pasted_secrets(g._redact(first_line)).strip()
        if not redacted:
            return None
        return redacted[:100]
    except Exception:
        return None


def call_summary_model(model, text: str) -> str:
    """One short reply from the loaded model with thinking off and output capped (a thinking model otherwise
    spends minutes on a one-line summary and blocks the next request, see RESULTS.md); retries without the
    reasoning setting if the server rejects it."""
    messages = [ChatMessage(role=MessageRole.USER, content=text)]
    try:
        msg = model(messages, reasoning_effort="none", max_tokens=80)
    except Exception:  # noqa: BLE001 - a server that does not know reasoning_effort
        msg = model(messages, max_tokens=80)
    return getattr(msg, "content", "") or ""


CONTEXT_TURNS = 3
CONTEXT_ANSWER_CHARS = 600


def build_context(history: list[tuple[str, str]]) -> str:
    """The last few turns of a chat as plain text to put before a follow-up; '' for a first message."""
    if not history:
        return ""
    lines = ["Earlier in this chat (for context only):"]
    for prompt, answer in history[-CONTEXT_TURNS:]:
        lines.append(f"User: {prompt}")
        lines.append(f"You: {answer if len(answer) <= CONTEXT_ANSWER_CHARS else answer[:CONTEXT_ANSWER_CHARS] + '...'}")
    return "\n".join(lines) + "\n\nNew message from the user: "


def _log_start(path: Path) -> dict:
    """The first (start) entry of a run log, or {}."""
    try:
        with path.open() as fh:
            e = json.loads(fh.readline())
        return e if isinstance(e, dict) and e.get("kind") == "start" else {}
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return {}


def _thread_turns(thread: str) -> list[tuple[str, str]]:
    """Finished (prompt, answer) turns of a chat, oldest first, from the run logs."""
    turns = []
    if not g.LOG_DIR.is_dir():
        return turns
    for f in sorted(g.LOG_DIR.glob("*.jsonl"), key=lambda f: f.name):
        if _log_start(f).get("thread") != thread:
            continue
        d = _run_detail(f)
        if d and d["finished"] and d["answer"]:
            turns.append((d["prompt"], d["answer"]))
    return turns


def _load_deferred_approvals() -> list[dict]:
    """Deferred actions from past scheduled runs in g.LOG_DIR, oldest first, one per schedule.

    Scans newest files first and stops after 50 runs. Runs marked handled (via a .handled.txt
    sidecar) or missing a start/deferred entry are skipped.
    """
    if not g.LOG_DIR.exists() or not g.LOG_DIR.is_dir():
        return []
    try:
        files = sorted(g.LOG_DIR.glob("*.jsonl"), key=lambda f: f.name, reverse=True)
    except OSError:
        return []

    candidates: list[dict] = []
    seen_schedules: set[str] = set()
    scanned_runs = 0

    for f in files:
        if not f.is_file():
            continue
        try:
            entries = [json.loads(raw) for raw in f.read_text().splitlines() if raw.strip()]
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            continue
        if not entries:
            continue
        start = entries[0] if isinstance(entries[0], dict) and entries[0].get("kind") == "start" else None
        if not start:
            continue

        scanned_runs += 1
        schedule = start.get("schedule")
        if schedule and schedule not in seen_schedules:
            deferred = next((e for e in entries if isinstance(e, dict) and e.get("kind") == "deferred"), None)
            actions = deferred.get("actions") if deferred else None
            handled = f.with_name(f"{f.stem}.handled.txt").exists()
            # Only a deferring or dismissed run supersedes older runs of its schedule, as in a live
            # session; a clean or stopped run leaves an older pending deferral alone.
            if handled or (actions and isinstance(actions, list)):
                seen_schedules.add(schedule)
            if not handled and actions and isinstance(actions, list):
                candidates.append({
                    "id": f.stem,
                    "schedule_id": str(schedule),
                    "prompt": g._redact(str(start.get("prompt", ""))),
                    "actions": [g._redact(str(a)) for a in actions],
                    "t": str(start.get("t") or deferred.get("t") or ""),
                })
        if scanned_runs >= 50:
            break

    candidates.reverse()
    return candidates


class Session:
    """Runs one agent request at a time in a background thread."""

    def __init__(self, agent, model: str, approvals: Approvals, backend: str = "lmstudio",
                 max_steps: int = MAX_STEPS, run_summaries: bool | None = None,
                 call_model: Callable[[str], str] | None = None,
                 schedule_timeout: float | None = None):
        self.agent, self.model, self.approvals = agent, model, approvals
        self.backend, self.max_steps = backend, max_steps
        if run_summaries is None:
            run_summaries = os.environ.get("SMOLPAW_RUN_SUMMARIES", "1").lower() not in ("0", "false", "no", "off")
        self.run_summaries = run_summaries
        if schedule_timeout is None:
            raw = os.environ.get("SCHEDULE_TIMEOUT", "900")
            try:
                schedule_timeout = float(raw) if raw != "" else 900.0
            except ValueError:
                schedule_timeout = 900.0
            if not 0 <= schedule_timeout < 86_400 * 365:  # negative, nan or inf: a bad value must not drop the limit
                schedule_timeout = 900.0
        self.schedule_timeout = float(schedule_timeout)
        self.call_model = call_model
        self._lock = threading.Lock()
        self.status, self.prompt, self.answer, self.outcome, self.error = "idle", "", "", "", ""
        self.started_at = 0.0
        self._run_id = 0
        self._timer: threading.Timer | None = None
        self._timed_out_run_id: int | None = None
        self._summarizing = threading.Event()
        self._summarizing_run_id: int | None = None
        self.thread: str | None = None  # id of the current chat; follow-ups share it
        self.history: list[tuple[str, str]] = []  # finished turns before the current prompt/answer
        self._scheduled_chat = False  # the current thread belongs to a scheduled run; interactive runs must not join it
        self.needs_approval: list[dict] = _load_deferred_approvals()

    def new_thread(self) -> bool:
        """Begin an empty chat; refused while a request runs."""
        with self._lock:
            if self.status == "running":
                return False
            self._run_id += 1
            self.thread, self.history = None, []
            self.prompt = self.answer = self.outcome = self.error = ""
            return True

    def start(self, prompt: str, thread: str | None = None, schedule: str | None = None) -> bool:
        """Begin a run; False if one is already running. `schedule` (a schedule id) makes it an unattended,
        read-only run in its own thread."""
        with self._lock:
            if self.status == "running":
                return False
            if schedule or self._scheduled_chat:  # a scheduled run never joins a chat, nor does a chat join it
                self.thread, self.history = None, []
                self.prompt = self.answer = self.outcome = self.error = ""
                self._scheduled_chat = bool(schedule)
            if thread and thread != self.thread:  # continue a chat picked from Recents
                self.thread, self.history = thread, _thread_turns(thread)
                self.prompt = self.answer = self.outcome = self.error = ""
            elif self.prompt and self.answer and not self.error:
                self.history.append((self.prompt, self.answer))
            if not self.thread:
                self.thread = f"{datetime.now():%Y%m%d-%H%M%S-%f}"
            context = build_context(self.history)
            self._run_id += 1
            run_id = self._run_id
            self.status, self.prompt, self.answer, self.outcome, self.error = "running", prompt, "", "", ""
            self.started_at = time.time()
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None
            if schedule and self.schedule_timeout > 0:
                self._timer = threading.Timer(self.schedule_timeout, self._on_timeout, args=(run_id, schedule))
                self._timer.daemon = True
                self._timer.start()
        threading.Thread(target=self._run, args=(prompt, run_id, context, self.thread, schedule), daemon=True).start()
        return True

    @property
    def summarizing(self) -> bool:
        return self._summarizing.is_set()

    def _default_call_model(self, text: str) -> str:
        return call_summary_model(self.agent.model, text)

    def _summarize(self, run_id: int, prompt: str, answer: str, log_file: Path) -> None:
        try:
            with self._lock:
                if self._run_id != run_id or self.status == "running":
                    return
            caller = self.call_model or self._default_call_model
            summary = summarize_run(prompt, answer, caller)
            with self._lock:
                if self._run_id != run_id or self.status == "running":
                    return
            if summary:
                try:
                    sidecar = log_file.with_name(f"{log_file.stem}.summary.txt")
                    sidecar.write_text(summary)
                except OSError:
                    pass
        finally:
            with self._lock:
                if self._summarizing_run_id == run_id:
                    self._summarizing_run_id = None
                    self._summarizing.clear()

    def _run(self, prompt: str, run_id: int, context: str = "", thread: str | None = None,
             schedule: str | None = None) -> None:
        deferred: list[str] = []
        saved_hooks = g.CONFIRM, g.ASK
        if schedule:  # nobody is there to answer: decline through the normal path and remember what was refused
            def confirm_later(desc: str) -> bool:
                deferred.append(g._redact(desc))
                return False
            g.CONFIRM, g.ASK = confirm_later, lambda question: NO_ANSWER
        exc_type = ""
        try:
            self.answer, self.outcome = run_request(self.agent, self.model, "generic", prompt, thread, context,
                                                    schedule)
            if not g.ACTIONS:  # nothing to report; the Activity feed already shows the run (the terminal keeps its line)
                self.outcome = ""
        except Exception as exc:  # noqa: BLE001 - shown on the page, as the CLI prints it
            exc_type = type(exc).__name__
            self.error = f"{type(exc).__name__}: {exc}"
        finally:
            with self._lock:
                if self._timer is not None:
                    self._timer.cancel()
                    self._timer = None
            if schedule:
                g.CONFIRM, g.ASK = saved_hooks
            log_file = g._log_file
            answer = self.answer
            has_error = bool(self.error)
            with self._lock:
                timed_out = bool(schedule and self._timed_out_run_id == run_id)
                if deferred and self._run_id == run_id:  # not for a stopped run
                    if log_file:
                        g._log("deferred", actions=deferred)
                    run_t = ""
                    if log_file:
                        start_entry = _log_start(log_file)
                        run_t = str(start_entry.get("t") or "")
                    if not run_t:
                        run_t = datetime.now().isoformat(timespec="seconds")
                    self.needs_approval = [e for e in self.needs_approval if e.get("schedule_id") != schedule]
                    self.needs_approval.append({
                        "id": log_file.stem if log_file else str(run_id),
                        "schedule_id": str(schedule),
                        "prompt": g._redact(prompt),
                        "actions": list(deferred),
                        "t": run_t,
                    })
                if schedule:
                    if timed_out:
                        status = "timeout"
                    elif self._run_id != run_id:
                        status = "stopped"
                    elif self.error:
                        status = "error"
                    elif deferred:
                        status = "needs_approval"
                    else:
                        status = "ok"
                    # Only the exception class name: messages, prompt, answer or tool output can contain private data or secrets
                    error = exc_type if status == "error" else ""
                    try:
                        schedules.mark_outcome(schedule, status, error)
                    except (OSError, ValueError, KeyError):
                        pass
                    if timed_out and log_file:
                        g._log("timeout", schedule=schedule, limit=self.schedule_timeout)
                will_summarize = bool(self.run_summaries and log_file and answer and not has_error)
                if will_summarize:
                    self._summarizing_run_id = run_id
                    self._summarizing.set()
                self.status = "idle"
            if will_summarize:
                threading.Thread(target=self._summarize, args=(run_id, prompt, answer, log_file), daemon=True).start()

    def dismiss_approval(self, id: str) -> bool:
        """Remove a deferred approval entry and persist dismissal as a <stem>.handled.txt sidecar."""
        with self._lock:
            entry = next((e for e in self.needs_approval if e.get("id") == id), None)
            if not entry:
                return False
            self.needs_approval = [e for e in self.needs_approval if e.get("id") != id]
            try:
                g.LOG_DIR.mkdir(exist_ok=True)
                sidecar = g.LOG_DIR / f"{id}.handled.txt"
                sidecar.write_text("handled\n")
            except OSError:
                pass
            return True

    def _on_timeout(self, run_id: int, schedule: str) -> None:
        """Called when a scheduled run hits the wall-clock time limit."""
        self._stop(timeout=True, expected_run_id=run_id)

    def stop(self) -> None:
        """Stop the currently running request.

        Note on cooperative interruption: agent.interrupt() is cooperative and only
        takes effect between steps. A model call or tool that never returns will not be
        killed. The session status remains 'running' until the worker thread actually
        ends, preserving generic_tools module-global state from overlapping runs.
        """
        self._stop(timeout=False)

    def _stop(self, timeout: bool = False, expected_run_id: int | None = None) -> None:
        with self._lock:
            if expected_run_id is not None and (self._run_id != expected_run_id or self.status != "running"):
                return
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None
            if timeout:
                self._timed_out_run_id = self._run_id
            self._run_id += 1
        self.agent.interrupt()
        self.approvals.cancel()

    def configure(self, backend: str, model: str, max_steps: int, timeout: float,
                  run_summaries: bool | None = None,
                  schedule_timeout: float | None = None) -> bool:
        """Switch backend, model, step limit, prompt timeout, run summaries, and schedule timeout between requests; refused while one runs."""
        with self._lock:
            if self.status == "running":
                return False
            self._run_id += 1
            if (backend, model, max_steps) != (self.backend, self.model, self.max_steps):
                self.agent = build_agent(model, "tool", max_steps, "generic", backend)
                self.backend, self.model, self.max_steps = backend, model, max_steps
            self.approvals.timeout = timeout
            if run_summaries is not None:
                self.run_summaries = run_summaries
            if schedule_timeout is not None:
                self.schedule_timeout = float(schedule_timeout)
            return True


def list_models(backend: str) -> list[str]:
    """Model ids the backend's server lists (both expose the OpenAI-style /models); empty if unreachable."""
    try:
        req = urllib.request.Request(BACKENDS[backend]["url"] + "/models",
                                     headers={"Authorization": f"Bearer {BACKENDS[backend]['key']}"})
        with urllib.request.urlopen(req, timeout=3) as r:
            data = json.loads(r.read(1_000_000))
        return sorted(str(m["id"]) for m in data.get("data", []) if isinstance(m, dict) and "id" in m)
    except (OSError, ValueError, KeyError, AttributeError):
        return []


TOOL_KINDS = {
    "shell", "http", "fetch_page", "openapi_search",
    "read_file", "list_dir", "write_file", "list_skills", "read_skill", "write_skill",
    "remember", "recall", "ask", "web_search",
}


def feed(log_path: Path | None = None) -> list[str]:
    """Short lines from a run log (default: current run, already redacted by generic_tools)."""
    target = log_path if log_path is not None else g._log_file
    if not target or not target.exists():
        return []
    try:
        raw_lines = target.read_text().splitlines()
    except OSError:
        return []
    lines = []
    for raw in raw_lines[-FEED_LINES:]:
        try:
            e = json.loads(raw)
        except json.JSONDecodeError:
            continue
        t = e.get("t", "")[11:]
        kind = e.get("kind")
        if kind == "shell":
            lines.append(f"{t} $ {e.get('command')} (exit {e.get('exit')})")
        elif kind == "http":
            lines.append(f"{t} {e.get('method')} {e.get('url')} -> {e.get('status')}")
        elif kind == "preflight":
            lines.append(f"{t} refused before sending: {e.get('method')} {e.get('url')} ({e.get('reason')})")
        elif kind == "confirm":
            first = (str(e.get("desc", "")).splitlines() or [""])[0]
            lines.append(f"{t} asked: {first} -> {'yes' if e.get('approved') else 'no'}")
        elif kind == "ask":
            lines.append(f"{t} question: {e.get('question')}")
        elif kind == "read_file":
            lines.append(f"{t} read_file {e.get('path')} -> {e.get('result')}")
        elif kind == "list_dir":
            lines.append(f"{t} list_dir {e.get('path')} -> {e.get('result')}")
        elif kind == "write_file":
            lines.append(f"{t} write_file {e.get('path')} ({e.get('chars')} chars) -> {e.get('result')}")
        elif kind == "list_skills":
            lines.append(f"{t} list_skills -> {e.get('result')}")
        elif kind == "read_skill":
            lines.append(f"{t} read_skill {e.get('name')} -> {e.get('result')}")
        elif kind == "write_skill":
            lines.append(f"{t} write_skill {e.get('name')} ({e.get('chars')} chars) -> {e.get('result')}")
        elif kind == "openapi_search":
            lines.append(f"{t} openapi_search {e.get('spec_url')} {e.get('keyword') or '(no keyword)'} -> {e.get('result')}")
        elif kind == "fetch_page":
            lines.append(f"{t} fetch_page {e.get('url')} {e.get('query') or '(no query)'} -> {e.get('result')}")
        elif kind == "web_search":
            lines.append(f"{t} web_search {e.get('query')} ({e.get('provider')}) -> {e.get('result')}")
        elif kind == "remember":
            lines.append(f"{t} remember {e.get('fact')}")
        elif kind == "recall":
            lines.append(f"{t} recall {e.get('query') or '(all)'} -> {e.get('result')}")
        elif kind in ("start", "final"):
            lines.append(f"{t} {kind}")
        elif kind == "timeout":
            lines.append(f"{t} timeout (schedule {e.get('schedule')}, limit {e.get('limit')}s)")
    return [g._redact(line) for line in lines]


def _run_summary(path: Path | None) -> str | None:
    """One-line summary for a run log derived from existing log fields."""
    if not path or not path.exists():
        return None
    try:
        raw_lines = path.read_text().splitlines()
    except OSError:
        return None
    entries = []
    for raw in raw_lines:
        try:
            entries.append(json.loads(raw))
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
    if not entries:
        return None
    start = next((e for e in entries if e.get("kind") == "start"), None)
    if not start:
        return None
    start_t = start.get("t", "")
    model = start.get("model", "")
    has_final = any(e.get("kind") == "final" for e in entries)
    if has_final:
        last_t = entries[-1].get("t", "")
        try:
            d = max(0.0, (datetime.fromisoformat(last_t) - datetime.fromisoformat(start_t)).total_seconds())
            dur = f"{int(round(d))}s"
        except (ValueError, TypeError):
            dur = "unfinished"
    else:
        dur = "unfinished"
    tool_calls = sum(1 for e in entries if e.get("kind") in TOOL_KINDS)
    tool_str = f"{tool_calls} tool call" if tool_calls == 1 else f"{tool_calls} tool calls"
    final = next((e for e in entries if e.get("kind") == "final"), {})
    tokens = ""
    if isinstance(final.get("input_tokens"), int):
        tokens = f" · {final['input_tokens']:,} in / {final.get('output_tokens', 0):,} out tokens"
    return g._redact(f"{start_t} · {model} · {dur} · {tool_str}{tokens}")


def _run_title(path: Path) -> str:
    """First sentence of the run's prompt, clipped to 80 characters, or '' if unavailable."""
    try:
        with path.open() as fh:
            for raw in fh:
                try:
                    e = json.loads(raw)
                except (json.JSONDecodeError, UnicodeDecodeError):
                    continue
                if e.get("kind") != "start":
                    continue
                text = " ".join(str(e.get("prompt", "")).split())
                text = re.split(r"(?<=[.!?])\s", text, maxsplit=1)[0]
                text = g._redact(text)
                return text if len(text) <= 80 else text[:79].rstrip() + "\u2026"
    except OSError:
        pass
    return ""


def _run_title_for(f: Path) -> str:
    """A run's title: its model-written summary if there is one, else the first sentence of its prompt."""
    sidecar = f.with_name(f"{f.stem}.summary.txt")
    if sidecar.exists():
        try:
            txt = g.redact_pasted_secrets(g._redact(sidecar.read_text().strip()))[:100]
            if txt:
                return txt
        except OSError:
            pass
    return _run_title(f)


def _list_runs() -> list[dict]:
    """Recent chats from g.LOG_DIR, newest first, capped at 20. Runs sharing a thread id form one chat.

    Each entry: id (the chat's first run log), ids (all its run logs, oldest first), thread (or ''),
    title (from the first run), summary (of the latest run) and turns.
    """
    if not g.LOG_DIR.exists() or not g.LOG_DIR.is_dir():
        return []
    try:
        files = sorted(g.LOG_DIR.glob("*.jsonl"), key=lambda f: f.name, reverse=True)
    except OSError:
        return []
    groups: dict[str, list[Path]] = {}  # newest-first order of first appearance
    for f in files:
        if not f.is_file():
            continue
        start = _log_start(f)
        if not start:
            continue
        groups.setdefault(str(start.get("thread") or f.name), []).append(f)
    runs = []
    for key, members in groups.items():
        latest, first = members[0], members[-1]
        summary = _run_summary(latest)
        if summary is None:
            continue
        threaded = key != first.name
        runs.append({"id": first.name, "ids": [m.name for m in reversed(members)], "thread": key if threaded else "",
                     "summary": summary, "title": _run_title_for(first), "turns": len(members)})
        if len(runs) >= 20:
            break
    return runs


def _run_detail(path: Path) -> dict | None:
    """What a past run asked and answered, for the page's chat view; logs are already redacted."""
    try:
        entries = [json.loads(raw) for raw in path.read_text().splitlines() if raw.strip()]
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    start = next((e for e in entries if e.get("kind") == "start"), None)
    if not start:
        return None
    final = next((e for e in entries if e.get("kind") == "final"), None)
    actions = "\n  ".join(str(a) for a in (final or {}).get("actions", []))
    return {"prompt": g._redact(str(start.get("prompt", ""))),
            "answer": g._redact(str(final.get("answer", ""))) if final else "",
            "outcome": f"[Harness says]\n  {g._redact(actions)}" if final and actions else "",
            "finished": final is not None}


def _files_payload() -> dict:
    """Read-only view of notes.md, skills/*.md and memory.md, secret-redacted and clipped."""
    def read_safe(p: Path) -> str:
        try:
            if p.exists() and p.is_file():
                return g._clip(g._redact(p.read_text()))
        except OSError:
            pass
        return ""

    skills = []
    try:
        if g.SKILLS.exists() and g.SKILLS.is_dir():
            for f in sorted(g.SKILLS.glob("*.md")):
                if f.is_file():
                    try:
                        skills.append({"name": f.stem, "text": g._clip(g._redact(f.read_text()))})
                    except OSError:
                        continue
    except OSError:
        pass
    return {
        "notes": read_safe(g.NOTES),
        "skills": skills,
        "memory": read_safe(g.MEMORY),
    }


def make_handler(token: str, approvals: Approvals, session: Session | None, info: dict):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args) -> None:
            pass  # keep the terminal for the agent's own output

        def _authed(self) -> bool:
            given = self.headers.get("X-Token") or parse_qs(urlparse(self.path).query).get("t", [""])[0]
            return hmac.compare_digest(given.encode(), token.encode())

        def _send(self, code: int, body, ctype: str = "application/json") -> None:
            data = body if isinstance(body, bytes) else json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Referrer-Policy", "no-referrer")  # the token is in the page URL
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'none'; script-src 'unsafe-inline'; "
                             "style-src 'unsafe-inline'; connect-src 'self'")
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self) -> None:
            if not self._authed():
                return self._send(403, {"error": "missing or wrong token"})
            path = urlparse(self.path).path
            if path == "/":
                return self._send(200, PAGE.encode(), "text/html; charset=utf-8")
            if path == "/api/state":
                s = session
                curr_summary = _run_summary(g._log_file) if g._log_file else ""
                return self._send(200, {
                    **info, "can_run": s is not None,
                    **({"backends": sorted(BACKENDS), "backend": s.backend, "model": s.model,
                        "max_steps": s.max_steps, "timeout": approvals.timeout,
                        "run_summaries": s.run_summaries,
                        "schedule_timeout": s.schedule_timeout} if s else {}),
                    "status": s.status if s else info.get("status", "running"),
                    "started_at": s.started_at if s and s.status == "running" else None,
                    "prompt": s.prompt if s else "", "answer": s.answer if s else "",
                    "thread": s.thread if s else None,
                    "turns": [{"prompt": g._redact(p), "answer": g._redact(a)} for p, a in s.history] if s else [],
                    "outcome": s.outcome if s else "", "error": s.error if s else "",
                    "pending": approvals.pending, "feed": feed(),
                    "tool_output": ({"label": g.SHOWN_OUTPUT[0], "text": g.SHOWN_OUTPUT[1]} if g.SHOWN_OUTPUT else None),
                    "summary": curr_summary or "", "run_id": g._log_file.name if g._log_file else ""})
            if path == "/api/models":
                backend = parse_qs(urlparse(self.path).query).get("backend", [""])[0]
                if backend not in BACKENDS:
                    return self._send(404, {"error": "unknown backend"})
                return self._send(200, list_models(backend))
            if path == "/api/files":
                return self._send(200, _files_payload())
            if path == "/api/runs":
                return self._send(200, _list_runs())
            if path in ("/api/run_feed", "/api/run_detail"):
                run_id = parse_qs(urlparse(self.path).query).get("id", [""])[0]
                if not run_id or "/" in run_id or "\\" in run_id:
                    return self._send(404, {"error": "not found"})
                if not g.LOG_DIR.exists() or not g.LOG_DIR.is_dir():
                    return self._send(404, {"error": "not found"})
                try:
                    files = list(g.LOG_DIR.glob("*.jsonl"))
                except OSError:
                    return self._send(404, {"error": "not found"})
                matched = next((f for f in files if f.name == run_id), None)
                if not matched:
                    return self._send(404, {"error": "not found"})
                if path == "/api/run_detail":
                    detail = _run_detail(matched)
                    return self._send(200, {**detail, "feed": feed(matched)} if detail else {"error": "not found"})
                return self._send(200, feed(matched))
            return self._send(404, {"error": "not found"})

        def do_POST(self) -> None:
            if not self._authed():
                return self._send(403, {"error": "missing or wrong token"})
            length = int(self.headers.get("Content-Length") or 0)
            if length > MAX_BODY:
                return self._send(413, {"error": "too large"})
            try:
                body = json.loads(self.rfile.read(length) or b"{}")
            except json.JSONDecodeError:
                return self._send(400, {"error": "bad JSON"})
            if not isinstance(body, dict):
                return self._send(400, {"error": "expected a JSON object"})
            path = urlparse(self.path).path
            if path == "/api/answer":
                ok = approvals.answer(body.get("id"), body.get("value"))
                return self._send(200 if ok else 409, {"ok": ok})
            if path == "/api/run" and session:
                prompt = str(body.get("prompt", "")).strip()
                if not prompt or len(prompt) > MAX_PROMPT:
                    return self._send(400, {"error": "empty or too long"})
                thread = body.get("thread")
                if thread is not None and not (isinstance(thread, str) and re.fullmatch(r"[\w.-]{1,64}", thread)):
                    return self._send(400, {"error": "bad thread"})
                ok = session.start(prompt, thread)
                return self._send(200 if ok else 409, {"ok": ok})
            if path == "/api/new_thread" and session:
                ok = session.new_thread()
                return self._send(200 if ok else 409, {"ok": ok})
            if path == "/api/settings" and session:
                backend, model = body.get("backend"), body.get("model")
                steps, timeout = body.get("max_steps"), body.get("timeout")
                summaries = body.get("run_summaries", session.run_summaries)
                sched_timeout = body.get("schedule_timeout", session.schedule_timeout)
                if (backend not in BACKENDS or not isinstance(model, str) or not model.strip()
                        or len(model) > 200 or isinstance(steps, bool) or not isinstance(steps, int)
                        or not 1 <= steps <= 50 or isinstance(timeout, bool)
                        or not isinstance(timeout, (int, float)) or not 0 <= timeout <= 3600
                        or not isinstance(summaries, bool)
                        or isinstance(sched_timeout, bool)
                        or not isinstance(sched_timeout, (int, float))
                        or not math.isfinite(sched_timeout)
                        or not 0 <= sched_timeout <= 86400):
                    return self._send(400, {"error": "invalid settings"})
                ok = session.configure(backend, model.strip(), steps, float(timeout), summaries,
                                       schedule_timeout=float(sched_timeout))
                return self._send(200 if ok else 409, {"ok": ok})
            if path == "/api/stop" and session:
                session.stop()
                return self._send(200, {"ok": True})
            return self._send(404, {"error": "not found"})

    return Handler


def serve(host: str, port: int, token: str, approvals: Approvals, session: Session | None = None,
          info: dict | None = None) -> ThreadingHTTPServer:
    """Start the web server in a background thread. `info` is shown on the page (eval uses it for progress)."""
    server = ThreadingHTTPServer((host, port), make_handler(token, approvals, session, info or {}))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def url(host: str, port: int, token: str) -> str:
    shown = "<this-machine>" if host in ("0.0.0.0", "::") else host
    return f"http://{shown}:{port}/?t={token}"


def main() -> None:
    ap = argparse.ArgumentParser(description="Run SmolPaw and answer its prompts from a browser.")
    ap.add_argument("--backend", choices=sorted(BACKENDS), default="lmstudio")
    ap.add_argument("--model", default=None, help="default depends on --backend")
    ap.add_argument("--max-steps", type=int, default=None, help="default: MAX_STEPS env var, else 12")
    ap.add_argument("--host", default="127.0.0.1",
                    help="address to listen on (0.0.0.0 for all interfaces, e.g. to reach it over Tailscale)")
    ap.add_argument("--port", type=int, default=PORT)
    ap.add_argument("--timeout", type=float, default=0, help="seconds before an unanswered prompt counts as no "
                                                              "(default: wait forever)")
    args = ap.parse_args()

    load_env()
    model = args.model or BACKENDS[args.backend]["model"]
    max_steps = args.max_steps or int(os.environ.get("MAX_STEPS", MAX_STEPS))
    token = os.environ.get("SMOLPAW_WEB_TOKEN") or secrets.token_urlsafe(18)
    approvals = Approvals(args.timeout)
    approvals.install()
    session = Session(build_agent(model, "tool", max_steps, "generic", args.backend), model, approvals,
                      args.backend, max_steps)
    server = serve(args.host, args.port, token, approvals, session,
                   {"mode": "agent", "backend": args.backend, "model": model})
    Scheduler(session, approvals).start()
    print(f"SmolPaw web [{args.backend}: {model}] at {url(args.host, args.port, token)}  (Ctrl-C to stop)")
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        print("\nBye.")
        server.shutdown()


PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>SmolPaw</title>
<style>
:root { --bg:#f6f5f2; --card:#fff; --ink:#1d1d1f; --muted:#6b6b70; --line:#dcdad5; --accent:#2f6fde;
        --yes:#1f8a4c; --no:#c23b3b; --warn:#fff4d6; }
@media (prefers-color-scheme: dark) { :root { --bg:#151517; --card:#1f1f22; --ink:#ececee; --muted:#9a9aa1;
        --line:#333338; --accent:#6b9cff; --yes:#3fbf73; --no:#ff6b6b; --warn:#3a3220; } }
* { box-sizing:border-box; }
body { margin:0; background:var(--bg); color:var(--ink); font:16px/1.45 -apple-system, system-ui, sans-serif; }
main { max-width:720px; margin:0 auto; padding:16px; overflow-wrap:anywhere; }
h1 { font-size:20px; margin:0 0 4px; }
.meta { color:var(--muted); font-size:14px; margin-bottom:16px; }
.card { background:var(--card); border:1px solid var(--line); border-radius:12px; padding:14px; margin-bottom:14px; }
.card h2 { font-size:13px; text-transform:uppercase; letter-spacing:.04em; color:var(--muted); margin:0 0 8px; }
.pending { border:2px solid var(--accent); background:var(--warn); }
pre { white-space:pre-wrap; overflow-wrap:anywhere; margin:0; font:14px/1.4 ui-monospace, Menlo, monospace; }
textarea { width:100%; min-height:84px; font:inherit; padding:10px; border-radius:8px; border:1px solid var(--line);
           background:var(--bg); color:var(--ink); }
.row { display:flex; gap:10px; margin-top:10px; }
button { flex:1; font:inherit; font-weight:600; padding:12px; border-radius:10px; border:0; color:#fff;
         background:var(--accent); }
button.yes { background:var(--yes); } button.no { background:var(--no); }
button.ghost { background:transparent; color:var(--muted); border:1px solid var(--line); }
button:disabled { opacity:.45; }
.cardhead { display:flex; justify-content:space-between; align-items:center; margin-bottom:8px; }
.cardhead h2 { margin:0; }
.copybtn { font:12px inherit; font-weight:600; padding:4px 10px; border-radius:6px; border:1px solid var(--line);
           background:transparent; color:var(--muted); }
.feed pre { font-size:12px; color:var(--muted); }
.runtitle { font-weight:600; }
.runmeta { color:var(--muted); font-size:12px; }
summary { font-size:13px; text-transform:uppercase; letter-spacing:.04em; color:var(--muted); font-weight:600; cursor:pointer; }
summary:focus { outline:none; }
details.sub { margin-top:8px; }
details.sub > summary { text-transform:none; letter-spacing:0; font-size:14px; }
details.sub > pre, details.sub > div { margin-top:8px; }
.filesec { margin-top:12px; }
.filesec h3 { font-size:12px; font-weight:600; color:var(--muted); margin:8px 0 2px; }
.runitem { padding:6px 8px; border-radius:6px; cursor:pointer; font-size:12px; font-family:ui-monospace, Menlo, monospace; color:var(--muted); margin-bottom:4px; }
.runitem:hover { background:var(--bg); color:var(--ink); }
select, input:not([type="checkbox"]) { width:100%; font:inherit; padding:8px; border-radius:8px; border:1px solid var(--line);
                background:var(--bg); color:var(--ink); }
input[type="checkbox"] { width:auto; cursor:pointer; }
[hidden] { display:none !important; }
.nav { display:none; }
aside { padding:16px 16px 0; }
main { display:flex; flex-direction:column; min-height:100vh; padding:0 16px; max-width:none; width:100%; }
#content, #dock { width:100%; max-width:760px; margin:0 auto; }
#content { flex:1; padding-top:16px; }
#dock { position:sticky; bottom:0; background:var(--bg); padding:8px 0 16px; }
#dock .card { margin-bottom:10px; }
#thread, #history { display:flex; flex-direction:column; gap:14px; }
#thread { padding-bottom:14px; }
#history:empty { display:none; }
.bubble { align-self:flex-end; max-width:85%; background:var(--card); border:1px solid var(--line);
          border-radius:18px 18px 4px 18px; padding:10px 14px; }
.bubble pre, .reply pre { font:inherit; }
.reply { padding:2px 4px; }
.reply .copybtn { margin-top:8px; }
#thread .card { margin-bottom:0; }
.composer { background:var(--card); border:1px solid var(--line); border-radius:22px; padding:10px 12px; }
.composer textarea { border:0; background:transparent; min-height:44px; max-height:200px; resize:none; padding:6px; outline:none; }
.composer .row { margin-top:4px; align-items:center; justify-content:flex-end; }
.composer .row .meta { margin:0 auto 0 6px; font-size:13px; }
.composer button { flex:none; padding:8px 20px; border-radius:18px; }
#newchat { margin:0 0 4px; flex:none; }
.recents { margin-top:10px; }
.recents h2 { font-size:12px; text-transform:uppercase; letter-spacing:.04em; color:var(--muted); margin:0 0 6px 8px; }
#runslist { max-height:35vh; overflow-y:auto; }
.runitem { font-family:inherit; font-size:14px; color:var(--ink); padding:7px 10px; margin-bottom:2px; }
.runitem.on { background:var(--bg); color:var(--accent); }
.runtitle { display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical; overflow:hidden; font-weight:500; }
@media (min-width:900px) {
  body { display:grid; grid-template-columns:280px minmax(0,1fr); min-height:100vh; }
  aside { position:sticky; top:0; height:100vh; padding:20px 14px; border-right:1px solid var(--line);
          background:var(--card); display:flex; flex-direction:column; gap:6px; overflow-y:auto; }
  aside h1 { font-size:22px; margin:0 0 12px 8px; }
  aside .meta { margin:auto 8px 0; font-size:12px; }
  .recents { flex:1; min-height:0; display:flex; flex-direction:column; }
  #runslist { max-height:none; flex:1; }
  .nav { display:block; text-align:left; background:transparent; color:var(--muted); font-weight:600;
         padding:10px 12px; border-radius:8px; flex:none; }
  .nav:hover { background:var(--bg); color:var(--ink); }
  .nav.on { background:var(--bg); color:var(--accent); }
  main { padding:0 32px; }
  #content { padding-top:24px; }
  [data-views] { display:none; }
  body[data-view=chat] [data-views~=chat], body[data-view=settings] [data-views~=settings] { display:block; }
  body:not([data-view=chat]) #thread { display:none; }
  body[data-view=settings] #dock { background:transparent; }
  #setcard > summary { display:none; }
  .feed pre { font-size:13px; }
}
</style></head><body data-view="chat">
<aside><h1>SmolPaw</h1>
  <button id="newchat">+ New chat</button>
  <button class="nav on" data-view="chat">Chat</button>
  <button class="nav" data-view="settings">Settings</button>
  <div class="recents"><h2>Recents</h2><div id="runslist"><pre>(no runs yet)</pre></div></div>
  <div class="meta" id="meta">connecting...</div></aside>
<main><div id="content">
<div id="thread" data-views="chat">
  <div id="history"></div>
  <div class="bubble" id="userbubble" hidden><pre id="pastprompt"></pre></div>
  <div class="reply" id="result" hidden><pre id="answer"></pre><pre id="outcome" style="margin-top:10px"></pre>
    <button class="copybtn" id="copy">Copy</button></div>
  <details class="card" id="outcard" hidden open><summary id="outlabel">Output</summary><pre id="outtext"></pre></details>
  <details class="card feed" id="feedcard"><summary>Activity</summary>
    <div class="cardhead"><div class="meta" id="actsummary" style="margin:0"></div><button class="copybtn" id="livebtn" hidden>Current run</button></div>
    <pre id="feed">(nothing yet)</pre></details>
</div>
<details class="card" id="setcard" data-views="settings"><summary>Settings</summary>
  <div class="filesec" id="setform" hidden>
    <h3>Backend</h3><select id="sbackend"></select>
    <h3>Model</h3><input id="smodel" list="smodels" autocomplete="off"><datalist id="smodels"></datalist>
    <h3>Step limit</h3><input id="ssteps" type="number" min="1" max="50">
    <h3>Prompt timeout (seconds, 0 waits forever)</h3><input id="stimeout" type="number" min="0" max="3600">
    <h3>Scheduled-run time limit (seconds, 0 disables)</h3><input id="sschedtimeout" type="number" min="0" max="86400">
    <h3>Run summaries</h3><label style="display:flex;align-items:center;gap:8px;font-size:14px;cursor:pointer"><input id="ssummaries" type="checkbox"> Model-written one-sentence summaries for recent runs</label>
    <div class="row"><button id="sapply">Apply</button></div>
    <div class="meta" id="smsg"></div>
  </div>
  <div class="filesec">
    <h2>Files (read-only)</h2>
    <details class="sub"><summary>Notes (notes.md)</summary><pre id="fnotes">(empty)</pre></details>
    <details class="sub"><summary>Skills (skills/)</summary><div id="fskills"><pre>(none)</pre></div></details>
    <details class="sub"><summary>Memory (memory.md)</summary><pre id="fmemory">(empty)</pre></details>
  </div></details>
</div>
<div id="dock">
<div class="card pending" id="pending" data-views="chat settings" hidden><h2 id="pkind">Approval needed</h2><pre id="ptext"></pre>
  <div class="row" id="yesno"><button class="yes" id="yes">Yes</button><button class="no" id="no">No</button></div>
  <div id="askbox" hidden><textarea id="reply" placeholder="Your answer"></textarea>
    <div class="row"><button id="send">Send answer</button></div></div></div>
<div class="composer" id="runcard" data-views="chat" hidden><textarea id="prompt" rows="1" placeholder="What should the agent do?"></textarea>
  <div class="row"><div class="meta" id="working" hidden></div><button class="ghost" id="stop">Stop</button><button id="run">Run</button></div></div>
</div></main><script>
const token = new URLSearchParams(location.search).get("t") || "";
const $ = id => document.getElementById(id);
let pendingId = null;
let startedAt = null;
const VERBS = ["Pawing", "Sniffing", "Fetching", "Digging", "Trotting", "Scouting",
               "Rummaging", "Burrowing", "Tinkering", "Nosing around"];
function tick() {
  if (!startedAt) return;
  const secs = Math.max(0, Math.round((Date.now() - startedAt) / 1000));
  const verb = VERBS[Math.floor(secs / 3) % VERBS.length];
  $("working").textContent = verb + "... (" + secs + "s)";
}
setInterval(tick, 1000);
async function api(path, body) {
  const r = await fetch(path, {method: body ? "POST" : "GET", cache: "no-store",
    headers: {"X-Token": token, "Content-Type": "application/json"}, body: body ? JSON.stringify(body) : undefined});
  return r.json();
}
async function answer(value) { if (pendingId !== null) { await api("/api/answer", {id: pendingId, value}); refresh(); } }
$("yes").onclick = () => answer(true);
$("no").onclick = () => answer(false);
$("send").onclick = () => { answer($("reply").value); $("reply").value = ""; };
function fitPrompt() { const t = $("prompt"); t.style.height = "auto"; t.style.height = Math.min(t.scrollHeight, 200) + "px"; }
$("prompt").addEventListener("input", fitPrompt);
$("run").onclick = async () => {
  const p = $("prompt").value.trim();
  if (!p) return;
  const r = await api("/api/run", selectedThread ? {prompt: p, thread: selectedThread} : {prompt: p});
  if (!r || !r.ok) { refresh(); return; }
  $("prompt").value = ""; fitPrompt(); selectedRunId = null; selectedThread = ""; historyKey = null;
  $("livebtn").hidden = true; renderRuns(); refresh();
};
$("stop").onclick = () => api("/api/stop", {});
// Enter sends, Shift+Enter adds a newline; click() keeps the buttons' disabled state in charge
for (const [box, btn] of [["prompt", "run"], ["reply", "send"]])
  $(box).addEventListener("keydown", e => {
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); $(btn).click(); }
  });
$("copy").onclick = async () => {
  const text = $("answer").textContent;
  const flash = msg => { $("copy").textContent = msg; setTimeout(() => { $("copy").textContent = "Copy"; }, 1500); };
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text);
    } else {
      const ta = document.createElement("textarea");
      ta.value = text; ta.style.position = "fixed"; ta.style.opacity = "0";
      document.body.appendChild(ta); ta.focus(); ta.select();
      document.execCommand("copy"); document.body.removeChild(ta);
    }
    flash("Copied!");
  } catch (e) { flash("Copy failed"); }
};
async function loadFiles() {
  try {
    const data = await api("/api/files");
    $("fnotes").textContent = data.notes || "(empty)";
    $("fmemory").textContent = data.memory || "(empty)";
    const skillsDiv = $("fskills");
    while (skillsDiv.firstChild) skillsDiv.removeChild(skillsDiv.firstChild);
    if (!data.skills || !data.skills.length) {
      const p = document.createElement("pre");
      p.textContent = "(none)";
      skillsDiv.appendChild(p);
    } else {
      for (const s of data.skills) {
        const title = document.createElement("h3");
        title.textContent = s.name;
        const pre = document.createElement("pre");
        pre.textContent = s.text || "(empty)";
        skillsDiv.appendChild(title);
        skillsDiv.appendChild(pre);
      }
    }
  } catch (e) {}
}
let setLoaded = false;
async function loadModels() {
  try {
    const models = await api("/api/models?backend=" + encodeURIComponent($("sbackend").value));
    const dl = $("smodels");
    while (dl.firstChild) dl.removeChild(dl.firstChild);
    for (const m of models) { const o = document.createElement("option"); o.value = m; dl.appendChild(o); }
    $("smsg").textContent = models.length ? "" : "Could not list models from this server; type an id.";
  } catch (e) {}
}
function fillSettings(s) {
  if (setLoaded) return;
  setLoaded = true;
  const sel = $("sbackend");
  for (const b of s.backends || [s.backend]) {
    const o = document.createElement("option"); o.value = o.textContent = b; sel.appendChild(o);
  }
  sel.value = s.backend; $("smodel").value = s.model;
  $("ssteps").value = s.max_steps; $("stimeout").value = s.timeout;
  $("sschedtimeout").value = s.schedule_timeout;
  $("ssummaries").checked = !!s.run_summaries;
}
$("sbackend").onchange = () => { $("smodel").value = ""; loadModels(); };
$("setcard").ontoggle = () => { if ($("setcard").open) { loadModels(); loadFiles(); } };
$("sapply").onclick = async () => {
  const r = await fetch("/api/settings", {method: "POST", cache: "no-store",
    headers: {"X-Token": token, "Content-Type": "application/json"},
    body: JSON.stringify({backend: $("sbackend").value, model: $("smodel").value,
      max_steps: parseInt($("ssteps").value, 10), timeout: Number($("stimeout").value),
      schedule_timeout: Number($("sschedtimeout").value),
      run_summaries: $("ssummaries").checked})});
  $("smsg").textContent = r.ok ? "Applied." : r.status === 409 ? "A request is running; try again when it finishes." : "Invalid settings.";
  refresh();
};
let lastSig = null, selectedThread = "", historyKey = null, selectedRunId = null, lastRunId = null, runsKey = null, runsData = [];
function renderRuns() {
  const container = $("runslist");
  while (container.firstChild) container.removeChild(container.firstChild);
  if (!runsData.length) {
    const p = document.createElement("pre");
    p.textContent = "(no runs yet)";
    container.appendChild(p);
    return;
  }
  for (const r of runsData) {
    const row = document.createElement("div");
    row.className = "runitem" + (r.id === selectedRunId ? " on" : "");
    row.title = r.summary;
    const t = document.createElement("div");
    t.className = "runtitle";
    t.textContent = r.title || r.summary;
    row.appendChild(t);
    const m = document.createElement("div");
    m.className = "runmeta";
    m.textContent = r.summary.split(" · ")[0].replace("T", " ").slice(0, 16);
    if (r.turns > 1) m.textContent += " · " + r.turns + " messages";
    row.appendChild(m);
    row.onclick = () => selectRun(r);
    container.appendChild(row);
  }
}
async function loadRuns() {
  try { runsData = (await api("/api/runs")) || []; renderRuns(); } catch (e) {}
}
function renderHistory(turns) {
  const box = $("history");
  while (box.firstChild) box.removeChild(box.firstChild);
  for (const t of turns) {
    const b = document.createElement("div"); b.className = "bubble";
    const bp = document.createElement("pre"); bp.textContent = t.prompt; b.appendChild(bp);
    const a = document.createElement("div"); a.className = "reply";
    const ap = document.createElement("pre"); ap.textContent = t.answer; a.appendChild(ap);
    if (t.outcome) { const op = document.createElement("pre"); op.style.marginTop = "10px"; op.textContent = t.outcome; a.appendChild(op); }
    box.appendChild(b); box.appendChild(a);
  }
}
async function selectRun(r) {
  selectedRunId = r.id; selectedThread = r.thread || "";
  setView("chat");
  renderRuns();
  try {
    const ds = await Promise.all((r.ids || [r.id]).map(id => api("/api/run_detail?id=" + encodeURIComponent(id))));
    if (selectedRunId !== r.id) return;
    const ok = ds.filter(d => d && d.prompt !== undefined);
    renderHistory(ok.map(d => ({prompt: d.prompt, answer: d.finished ? d.answer : "(this run did not finish)", outcome: d.outcome})));
    historyKey = null;
    const last = ok[ok.length - 1] || {};
    $("feed").textContent = (last.feed || []).join("\\n") || "(empty run log)";
    $("actsummary").textContent = r.summary;
    $("livebtn").hidden = false;
    refresh();
    window.scrollTo({top: document.body.scrollHeight});
  } catch (e) {}
}
function showLive() {
  selectedRunId = null; selectedThread = ""; historyKey = null;
  $("livebtn").hidden = true;
  renderRuns();
  refresh();
}
$("newchat").onclick = async () => { await api("/api/new_thread", {}); showLive(); setView("chat"); $("prompt").focus(); };
$("livebtn").onclick = showLive;
async function refresh() {
  let s; try { s = await api("/api/state"); } catch (e) { $("meta").textContent = "cannot reach SmolPaw"; return; }
  $("meta").textContent = [s.mode, s.backend, s.model, s.status, s.progress].filter(Boolean).join(" · ");
  const p = s.pending;
  $("pending").hidden = !p;
  if (p && p.id !== pendingId) {
    pendingId = p.id; $("ptext").textContent = p.text;
    $("pkind").textContent = p.kind === "confirm" ? "Approval needed" : "The agent asks";
    $("yesno").hidden = p.kind !== "confirm"; $("askbox").hidden = p.kind !== "ask";
    if (navigator.vibrate) navigator.vibrate(200);
  }
  if (!p) pendingId = null;
  const viewing = selectedRunId !== null;
  $("runcard").hidden = !s.can_run;
  $("setform").hidden = !s.can_run;
  if (s.can_run) fillSettings(s);
  $("sapply").disabled = s.status === "running";
  $("run").disabled = s.status === "running"; $("stop").disabled = s.status !== "running";
  $("working").hidden = s.status !== "running";
  if (s.status === "running") { startedAt = s.started_at ? s.started_at * 1000 : (startedAt || Date.now()); tick(); }
  else { startedAt = null; }
  const done = s.answer || s.error;
  if (!viewing) {
    $("pastprompt").textContent = s.prompt || ""; $("userbubble").hidden = !s.prompt;
    const hk = (s.thread || "") + "|" + (s.turns || []).length;
    if (hk !== historyKey) { historyKey = hk; renderHistory(s.turns || []); }
  } else { $("userbubble").hidden = true; }
  $("result").hidden = viewing || (!done && !s.prompt);
  $("answer").textContent = s.error ? "[Error] " + s.error : (s.answer || (s.prompt ? "working on: " + s.prompt : ""));
  $("outcome").textContent = s.outcome || "";
  $("outcard").hidden = viewing || !(done && s.tool_output);
  if (s.tool_output) { $("outlabel").textContent = "Output of " + s.tool_output.label; $("outtext").textContent = s.tool_output.text; }
  if (lastRunId !== null && s.run_id !== lastRunId) selectedRunId = null;
  lastRunId = s.run_id;
  if (!selectedRunId) {
    $("livebtn").hidden = true;
    $("actsummary").textContent = s.summary || "";
    $("feed").textContent = s.prompt ? ((s.feed || []).join("\\n") || "(nothing yet)") : "(nothing yet)";
  }
  if ($("setcard").open && document.body.dataset.view === "settings") loadFiles();
  const sig = [s.run_id, s.answer, s.error, (s.feed || []).length, (s.turns || []).length, p && p.id].join("|");
  if (!viewing && sig !== lastSig) { lastSig = sig; window.scrollTo({top: document.body.scrollHeight, behavior: "smooth"}); }
  const key = [s.run_id, s.status, s.summary].join("|");
  if (key !== runsKey) { runsKey = key; loadRuns(); }
}
const wide = window.matchMedia("(min-width:900px)");
function openPanels() { $("setcard").open = wide.matches; }
function setView(v) {
  document.body.dataset.view = v;
  for (const b of document.querySelectorAll(".nav")) b.classList.toggle("on", b.dataset.view === v);
  try { localStorage.setItem("smolpawView", v); } catch (e) {}
}
for (const b of document.querySelectorAll(".nav")) b.onclick = () => setView(b.dataset.view);
try { const v = localStorage.getItem("smolpawView"); if (["chat", "settings"].includes(v)) setView(v); } catch (e) {}
wide.onchange = openPanels; openPanels();
refresh(); setInterval(refresh, 1500);
</script></body></html>
"""


if __name__ == "__main__":
    main()
