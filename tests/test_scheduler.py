"""
Tests for the scheduler thread and the read-only mode of scheduled runs.
Run with: .venv/bin/python tests/test_scheduler.py

Uses a fake agent, an injected clock and temporary schedules.json, logs/ and workspace, never the real ones.
"""

import itertools
import json
import sys
import tempfile
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import generic_tools as g  # noqa: E402
import schedules  # noqa: E402
import web  # noqa: E402
from scheduler import Scheduler  # noqa: E402
from smolagents.utils import AgentError  # noqa: E402

tmp = Path(tempfile.mkdtemp())
schedules.PATH = tmp / "schedules.json"
g.LOG_DIR = tmp / "logs"
g.WORKSPACE = tmp / "workspace"
g.WORKSPACE.mkdir()
(g.WORKSPACE / "a.txt").write_text("hello\n")


def check(name: str, cond: bool) -> None:
    print(f"{'PASS' if cond else 'FAIL'}  {name}")
    if not cond:
        check.failed += 1


check.failed = 0

interactive_prompts: list[str] = []


def interactive_confirm(desc: str) -> bool:
    interactive_prompts.append(desc)
    return True


def interactive_ask(question: str) -> str:
    return "interactive answer"


g.CONFIRM, g.ASK = interactive_confirm, interactive_ask


class FakeAgent:
    """Runs `script(agent)` as the model's work; the script calls real tools. Blocks on `gate` if set."""

    def __init__(self):
        self.memory = type("M", (), {"steps": []})()
        self.monitor = type("Mon", (), {"get_total_token_counts": lambda s: type("T", (), {
            "input_tokens": 10, "output_tokens": 2})()})()
        self.stall_reason = None
        self.script = lambda agent: "done"
        self.gate: threading.Event | None = None
        self.stopped = threading.Event()
        self.tool_results: dict = {}
        self.inputs: list[str] = []

    def run(self, text):
        self.inputs.append(text)
        if self.gate is not None:
            self.gate.wait(5)
            if self.stopped.is_set():
                raise AgentError("Agent interrupted.", type("L", (), {"log_error": lambda *a: None})())
        return self.script(self)

    def interrupt(self):
        self.stopped.set()
        if self.gate is not None:
            self.gate.set()


models = itertools.count()
T0 = datetime(2026, 10, 26, 12, 0)


def make(agent: FakeAgent | None = None) -> tuple[web.Session, web.Approvals, FakeAgent]:
    agent = agent or FakeAgent()
    approvals = web.Approvals()
    return web.Session(agent, "m", approvals, "lmstudio", 5, run_summaries=False), approvals, agent


def next_model(sess: web.Session) -> None:
    sess.model = f"m{next(models)}"  # log files are named to the second: one model name per run keeps them apart


def wait_idle(sess: web.Session) -> None:
    for _ in range(200):
        if sess.status == "idle":
            return
        time.sleep(0.05)


def wait_running(sess: web.Session) -> None:
    for _ in range(200):
        if sess.status == "running":
            return
        time.sleep(0.01)


def reset_schedules() -> None:
    if schedules.PATH.exists():
        schedules.PATH.unlink()


def entries(path: Path) -> list[dict]:
    return [json.loads(x) for x in path.read_text().splitlines()]


def scheduler_for(sess, approvals, now: datetime) -> tuple[Scheduler, dict]:
    clock = {"now": now}
    sched = Scheduler(sess, approvals, poll=0.01, clock=lambda: clock["now"])
    return sched, clock


# --- when a schedule starts -------------------------------------------------------------------

reset_schedules()
sess, approvals, agent = make()
s1 = schedules.add("check the queue", "*/5 * * * *", now=T0)
sched, clock = scheduler_for(sess, approvals, T0)
check("a not-yet-due schedule does not start", sched.tick() is None and sess.status == "idle" and not agent.inputs)

clock["now"] = T0 + timedelta(minutes=5)
next_model(sess)
check("a due schedule starts once", sched.tick() == s1["id"])
wait_idle(sess)
check("the run got the schedule's prompt", agent.inputs == ["check the queue"])
after = schedules.load()[0]
check("next_run moved forward and last_run was set",
      datetime.fromisoformat(after["next_run"]) > clock["now"] and after["last_run"] == clock["now"].isoformat())
check("it does not start again until due", sched.tick() is None and len(agent.inputs) == 1)

# a long gap (laptop asleep) fires once, not once per missed slot
clock["now"] = T0 + timedelta(days=3)
next_model(sess)
check("missed slots after a long gap fire once", sched.tick() == s1["id"])
wait_idle(sess)
check("... and then the schedule is not due", sched.tick() is None and len(agent.inputs) == 2)

# --- nothing starts while busy ----------------------------------------------------------------

reset_schedules()
sess, approvals, agent = make()
s2 = schedules.add("later job", "*/5 * * * *", now=T0)
sched, clock = scheduler_for(sess, approvals, T0 + timedelta(minutes=10))
agent.gate = threading.Event()
next_model(sess)
sess.start("interactive work")
wait_running(sess)
check("nothing starts while an interactive run is in progress", sched.tick() is None)
agent.gate.set()
wait_idle(sess)
agent.gate = None
approvals.pending = {"id": 1, "kind": "confirm", "text": "x"}
check("nothing starts while an approval prompt is pending", sched.tick() is None)
approvals.pending = None
check("the schedule is still due afterwards", [d["id"] for d in schedules.due(clock["now"])] == [s2["id"]])
next_model(sess)
check("... and runs on the next free tick", sched.tick() == s2["id"])
wait_idle(sess)
agent.gate = threading.Event()
next_model(sess)
sess.start("interactive wins")
wait_running(sess)
check("a start refused because a run is in progress is not treated as started",
      sess.start("again", schedule="x") is False and sched.tick() is None)
agent.gate.set()
wait_idle(sess)
agent.gate = None

# --- ordering ---------------------------------------------------------------------------------

reset_schedules()
sess, approvals, agent = make()
late = schedules.add("second", "0 13 * * *", now=datetime(2026, 10, 26, 12, 30))  # due at 13:00
early = schedules.add("first", "*/10 * * * *", now=T0)  # due at 12:10
sched, clock = scheduler_for(sess, approvals, datetime(2026, 10, 26, 14, 0))
next_model(sess)
check("the oldest due schedule runs first", sched.tick() == early["id"])
wait_idle(sess)
next_model(sess)
check("the other one runs on the next tick (one run per tick)", sched.tick() == late["id"])
wait_idle(sess)
check("each ran once, in order", agent.inputs == ["first", "second"])

# --- read-only mode ---------------------------------------------------------------------------

reset_schedules()


def writes_and_reads(agent):
    agent.tool_results["write"] = g.write_file("new.txt", "data")
    agent.tool_results["read"] = g.read_file("a.txt")
    agent.tool_results["ask"] = g.ask_user("which one?")
    return "finished"


sess, approvals, agent = make()
agent.script = writes_and_reads
next_model(sess)
s3 = schedules.add("write something", "*/5 * * * *", now=T0)
sched, clock = scheduler_for(sess, approvals, T0 + timedelta(minutes=5))
started = time.time()
sched.tick()
wait_idle(sess)
check("a scheduled write that would ask [y/N] is declined without blocking", time.time() - started < 3)
check("the model sees DECLINED", agent.tool_results["write"] == g.DECLINED)
check("nothing was written", not (g.WORKSPACE / "new.txt").exists())
check("an auto-allowed read still runs in a scheduled run", "hello" in agent.tool_results["read"])
check("ask_user returns NO_ANSWER instead of blocking", agent.tool_results["ask"] == web.NO_ANSWER)
check("the interactive prompt hook was not used", interactive_prompts == [])
check("the deferred list is kept for the UI",
      sess.needs_approval is not None and sess.needs_approval["schedule_id"] == s3["id"]
      and sess.needs_approval["prompt"] == "write something" and len(sess.needs_approval["actions"]) == 1
      and "new.txt" in sess.needs_approval["actions"][0])
log = entries(g._log_file)
check("the log has a deferred entry", [e for e in log if e["kind"] == "deferred"]
      and "new.txt" in log[-1]["actions"][0])
check("the declined line reaches the harness's final summary",
      any(a.startswith("declined:") for a in log[[e["kind"] for e in log].index("final")]["actions"])
      and sess.outcome.count("declined:") == 1)
check("hooks are restored after a normal finish", g.CONFIRM is interactive_confirm and g.ASK is interactive_ask)

# the secret in a declined action is redacted
secret = "sk-test-0123456789abcdef0123456789abcdef"
g._secrets = lambda: [secret]
sess, approvals, agent = make()
agent.script = lambda a: g.write_file("note.txt", f"key {secret}")
next_model(sess)
schedules.add("leak?", "*/5 * * * *", now=T0)
Scheduler(sess, approvals, clock=lambda: T0 + timedelta(minutes=5)).tick()
wait_idle(sess)
check("secrets in the deferred list are redacted",
      sess.needs_approval is not None and secret not in json.dumps(sess.needs_approval["actions"])
      and secret not in g._log_file.read_text())

# an interactive run afterwards still prompts, with its own hooks
sess, approvals, agent = make()
agent.script = lambda a: g.write_file("after.txt", "x")
next_model(sess)
sess.start("interactive write")
wait_idle(sess)
check("an interactive run after a scheduled one still prompts", len(interactive_prompts) == 1
      and (g.WORKSPACE / "after.txt").exists())
check("... and does not join the scheduled run's thread", sess.history == [])
log = entries(g._log_file)
check("the schedule field is absent from an interactive run's start entry",
      log[0]["kind"] == "start" and "schedule" not in log[0])

# --- hooks restored after an exception and after Stop ----------------------------------------

sess, approvals, agent = make()


def boom(a):
    raise RuntimeError("model fell over")


agent.script = boom
next_model(sess)
reset_schedules()
s4 = schedules.add("will fail", "*/5 * * * *", now=T0)
sched, clock = scheduler_for(sess, approvals, T0 + timedelta(minutes=5))
check("an erroring run is started", sched.tick() == s4["id"])
wait_idle(sess)
check("hooks are restored after an exception", g.CONFIRM is interactive_confirm and g.ASK is interactive_ask)
check("the error is recorded on the session", "model fell over" in sess.error)
check("an erroring run still called mark_ran", datetime.fromisoformat(schedules.load()[0]["next_run"]) > clock["now"])
clock["now"] += timedelta(minutes=5)
agent.script = lambda a: "fine now"
next_model(sess)
check("the thread keeps going after an erroring run", sched.tick() == s4["id"])
wait_idle(sess)
check("... and the next run finishes", sess.answer == "fine now" and not sess.error)

sess, approvals, agent = make()
in_tool = threading.Event()
release = threading.Event()


def declined_then_hangs(a):
    g.write_file("stopped.txt", "x")  # declined: goes on the deferred list
    in_tool.set()
    release.wait(5)
    raise AgentError("Agent interrupted.", type("L", (), {"log_error": lambda *a: None})())


agent.script = declined_then_hangs
next_model(sess)
reset_schedules()
schedules.add("will be stopped", "*/5 * * * *", now=T0)
sched, clock = scheduler_for(sess, approvals, T0 + timedelta(minutes=5))
sched.tick()
in_tool.wait(5)
check("hooks are replaced while a scheduled run executes", g.CONFIRM is not interactive_confirm)
sess.stop()
release.set()
wait_idle(sess)
check("hooks are restored after Stop", g.CONFIRM is interactive_confirm and g.ASK is interactive_ask)
check("a stopped run leaves no needs_approval half-filled", sess.needs_approval is None
      or sess.needs_approval["prompt"] != "will be stopped")
check("the stopped run's declined write is still in its log",
      any(e["kind"] == "confirm" and not e["approved"] for e in entries(g._log_file)))

# --- the thread -------------------------------------------------------------------------------

reset_schedules()
sess, approvals, agent = make()
schedules.PATH.write_text("{not json")
sched = Scheduler(sess, approvals, poll=0.01)
errors: list[str] = []
real_print = print
import builtins  # noqa: E402

builtins.print = lambda *a, **k: errors.append(" ".join(str(x) for x in a))
try:
    thread = sched.start()
    time.sleep(0.3)
    alive_with_corrupt_file = thread.is_alive()
    schedules.PATH.unlink()
    due = schedules.add("recovers", "*/5 * * * *", now=datetime.now() - timedelta(minutes=10))
    next_model(sess)
    for _ in range(100):
        if agent.inputs:
            break
        time.sleep(0.05)
    sched.stop()
finally:
    builtins.print = real_print
check("a corrupt schedules.json does not kill the thread", alive_with_corrupt_file)
check("it prints one line per distinct error", len([e for e in errors if e.startswith("[scheduler]")]) == 1)
check("the thread picks the schedule up once the file is fixed", agent.inputs == ["recovers"])
wait_idle(sess)
check("the console never shows a schedule's prompt", not any("recovers" in e for e in errors))

# --- the schedule tag in the log ---------------------------------------------------------------

reset_schedules()
sess, approvals, agent = make()
next_model(sess)
s5 = schedules.add("tagged", "*/5 * * * *", now=T0)
Scheduler(sess, approvals, clock=lambda: T0 + timedelta(minutes=5)).tick()
wait_idle(sess)
start = entries(g._log_file)[0]
check("the schedule field appears in a scheduled run's start entry",
      start["kind"] == "start" and start["schedule"] == s5["id"] and "thread" in start)

print(f"\n{check.failed} failed")
sys.exit(1 if check.failed else 0)
