"""
Tests for the scheduler thread and the read-only mode of scheduled runs.
Run with: .venv/bin/python tests/test_scheduler.py

Uses a fake agent, an injected clock and temporary schedules.json, logs/ and workspace, never the real ones.
"""

import itertools
import json
import os
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


def make(agent: FakeAgent | None = None,
         schedule_timeout: float | None = None) -> tuple[web.Session, web.Approvals, FakeAgent]:
    agent = agent or FakeAgent()
    approvals = web.Approvals()
    return web.Session(agent, "m", approvals, "lmstudio", 5, run_summaries=False,
                       schedule_timeout=schedule_timeout), approvals, agent


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
check("a run that changed nothing shows no [Harness says] block on the page", sess.outcome == "")
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
      bool(sess.needs_approval) and sess.needs_approval[0]["schedule_id"] == s3["id"]
      and sess.needs_approval[0]["prompt"] == "write something" and len(sess.needs_approval[0]["actions"]) == 1
      and "new.txt" in sess.needs_approval[0]["actions"][0])
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
      bool(sess.needs_approval) and secret not in json.dumps(sess.needs_approval[0]["actions"])
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
check("a stopped run leaves no needs_approval half-filled",
      not any(e.get("prompt") == "will be stopped" for e in sess.needs_approval))
check("the stopped run's declined write is still in its log",
      any(e["kind"] == "confirm" and not e["approved"] for e in entries(g._log_file)))
check("a stopped run does not write a deferred entry to the log",
      not any(e["kind"] == "deferred" for e in entries(g._log_file)))
check("a stopped run is not rebuilt after a restart",
      not any(e.get("prompt") == "will be stopped" for e in web.Session(agent, "m", approvals, run_summaries=False).needs_approval))

# --- the thread -------------------------------------------------------------------------------

reset_schedules()
sess, approvals, agent = make()
schedules.PATH.write_text("{not json")
sched = Scheduler(sess, approvals, poll=0.01)
errors: list[str] = []
orig_report = sched._report


def capture_report(message: str) -> None:
    if message != sched._last_error:
        errors.append(f"[scheduler] {message}")
    sched._last_error = message


sched._report = capture_report
try:
    thread = sched.start()
    time.sleep(0.3)
    alive_with_corrupt_file = thread.is_alive()
    with schedules._LOCK:
        schedules.PATH.unlink()
        due = schedules.add("recovers", "*/5 * * * *", now=datetime.now() - timedelta(minutes=10))
    next_model(sess)
    for _ in range(100):
        if agent.inputs:
            break
        time.sleep(0.05)
    sched.stop()
    thread.join(timeout=5)
finally:
    sched._report = orig_report
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

# --- scheduled run outcomes (#54) -------------------------------------------------------------

# 1. Scheduled run that finishes normally ends "ok"
reset_schedules()
sess, approvals, agent = make()
agent.script = lambda a: "done normal"
s_ok = schedules.add("normal finish prompt", "*/5 * * * *", now=T0)
sched, clock = scheduler_for(sess, approvals, T0 + timedelta(minutes=5))
next_model(sess)
sched.tick()
wait_idle(sess)
entry_ok = schedules.load()[0]
check("scheduled run that finishes normally ends 'ok'",
      entry_ok.get("last_status") == "ok" and entry_ok.get("last_error") == "")
check("prompt text never appears in status fields (ok)",
      s_ok["prompt"] not in (entry_ok.get("last_status") or "")
      and s_ok["prompt"] not in (entry_ok.get("last_error") or ""))

# 2. Fake agent raises ends "error" with last_error equal to exception class name and no secret
reset_schedules()
sess, approvals, agent = make()
secret_token_in_err = "SUPER_SECRET_LEAK_TEST_TOKEN_XYZ987"


def error_with_secret(a):
    raise ValueError(f"failure with secret: {secret_token_in_err}")


agent.script = error_with_secret
s_err = schedules.add("error prompt with secret", "*/5 * * * *", now=T0)
sched, clock = scheduler_for(sess, approvals, T0 + timedelta(minutes=5))
next_model(sess)
sched.tick()
wait_idle(sess)
entry_err = schedules.load()[0]
check("scheduled run whose fake agent raises ends 'error'",
      entry_err.get("last_status") == "error")
check("last_error is the exception class name",
      entry_err.get("last_error") == "ValueError")
raw_schedules_json = schedules.PATH.read_text(encoding="utf-8")
check("exception message with secret never appears in schedules.json",
      secret_token_in_err not in raw_schedules_json)
check("prompt text never appears in status fields (error)",
      s_err["prompt"] not in (entry_err.get("last_status") or "")
      and s_err["prompt"] not in (entry_err.get("last_error") or ""))

# 3. Scheduled run that is stopped ends "stopped"
reset_schedules()
sess, approvals, agent = make()
in_stop_tool = threading.Event()
release_stopped = threading.Event()


def stopped_agent(a):
    in_stop_tool.set()
    release_stopped.wait(5)
    raise AgentError("Agent interrupted.", type("L", (), {"log_error": lambda *a: None})())


agent.script = stopped_agent
s_stop = schedules.add("stopped prompt", "*/5 * * * *", now=T0)
sched, clock = scheduler_for(sess, approvals, T0 + timedelta(minutes=5))
next_model(sess)
sched.tick()
in_stop_tool.wait(5)
sess.stop()
release_stopped.set()
wait_idle(sess)
entry_stop = schedules.load()[0]
check("scheduled run that is stopped ends 'stopped'",
      entry_stop.get("last_status") == "stopped" and entry_stop.get("last_error") == "")
check("prompt text never appears in status fields (stopped)",
      s_stop["prompt"] not in (entry_stop.get("last_status") or "")
      and s_stop["prompt"] not in (entry_stop.get("last_error") or ""))

# 4. Scheduled run that defers an action ends "needs_approval"
reset_schedules()
sess, approvals, agent = make()


def deferring_agent(a):
    g.write_file("deferred_file.txt", "content")
    return "finished work"


agent.script = deferring_agent
s_defer = schedules.add("deferring prompt", "*/5 * * * *", now=T0)
sched, clock = scheduler_for(sess, approvals, T0 + timedelta(minutes=5))
next_model(sess)
sched.tick()
wait_idle(sess)
entry_defer = schedules.load()[0]
check("scheduled run that defers an action ends 'needs_approval'",
      entry_defer.get("last_status") == "needs_approval" and entry_defer.get("last_error") == "")
check("prompt text never appears in status fields (needs_approval)",
      s_defer["prompt"] not in (entry_defer.get("last_status") or "")
      and s_defer["prompt"] not in (entry_defer.get("last_error") or ""))

# 5. Failing mark_outcome still leaves Session status "idle"
reset_schedules()
sess, approvals, agent = make()
agent.script = lambda a: "ok"
s_fail = schedules.add("fail corrupt prompt", "*/5 * * * *", now=T0)
schedules.PATH.write_text("{corrupt json")
next_model(sess)
sess.start("fail corrupt prompt", schedule=s_fail["id"])
wait_idle(sess)
check("failing mark_outcome (corrupt file) still leaves Session status idle", sess.status == "idle")

reset_schedules()
ro_dir = tmp / "ro_schedules"
ro_dir.mkdir(exist_ok=True)
ro_file = ro_dir / "schedules.json"
saved_sched_path = schedules.PATH
schedules.PATH = ro_file
try:
    s_fail2 = schedules.add("fail unwritable prompt", "*/5 * * * *", now=T0)
    ro_dir.chmod(0o555)
    sess, approvals, agent = make()
    agent.script = lambda a: "ok"
    next_model(sess)
    sess.start("fail unwritable prompt", schedule=s_fail2["id"])
    wait_idle(sess)
    check("failing mark_outcome (unwritable directory) still leaves Session status idle", sess.status == "idle")
finally:
    ro_dir.chmod(0o755)
    schedules.PATH = saved_sched_path

# --- deferred approvals (#55) -----------------------------------------------------------------

deferred_tmp = tmp / "deferred_logs"
deferred_tmp.mkdir()
saved_log_dir = g.LOG_DIR
g.LOG_DIR = deferred_tmp

try:
    reset_schedules()
    sess, approvals, agent = make()
    agent.script = writes_and_reads

    # 1. The same schedule deferring twice: one entry, the newer one
    s_a = schedules.add("task a first", "*/5 * * * *", now=T0)
    next_model(sess)
    Scheduler(sess, approvals, clock=lambda: T0 + timedelta(minutes=5)).tick()
    wait_idle(sess)
    first_id = sess.needs_approval[0]["id"]

    # Same schedule s_a runs again at T0 + 10 with updated prompt and defers again
    scheds = schedules.load()
    scheds[0]["prompt"] = "task a second"
    schedules._atomic_save(scheds)
    next_model(sess)
    Scheduler(sess, approvals, clock=lambda: T0 + timedelta(minutes=10)).tick()
    wait_idle(sess)
    second_id = sess.needs_approval[0]["id"]

    check("the same schedule deferring twice: one entry, the newer one",
          len(sess.needs_approval) == 1
          and sess.needs_approval[0]["schedule_id"] == s_a["id"]
          and sess.needs_approval[0]["prompt"] == "task a second"
          and sess.needs_approval[0]["id"] == second_id
          and second_id != first_id)

    # 2. Two different schedules that both defer: two entries, oldest first
    s_b = schedules.add("task b", "*/5 * * * *", now=T0 + timedelta(minutes=10))
    next_model(sess)
    schedules.set_enabled(s_a["id"], False)
    Scheduler(sess, approvals, clock=lambda: T0 + timedelta(minutes=15)).tick()
    wait_idle(sess)
    schedules.set_enabled(s_a["id"], True)

    check("two different schedules that both defer: two entries, oldest first",
          len(sess.needs_approval) == 2
          and sess.needs_approval[0]["schedule_id"] == s_a["id"]
          and sess.needs_approval[1]["schedule_id"] == s_b["id"]
          and sess.needs_approval[0]["prompt"] == "task a second"
          and sess.needs_approval[1]["prompt"] == "task b"
          and "new.txt" in sess.needs_approval[0]["actions"][0]
          and "new.txt" in sess.needs_approval[1]["actions"][0])

    # 3. A run with no declined actions adds nothing and leaves other entries alone
    s_c = schedules.add("read-only task", "0 13 * * *", now=T0)
    agent.script = lambda a: g.read_file("a.txt")
    next_model(sess)
    schedules.set_enabled(s_a["id"], False)
    schedules.set_enabled(s_b["id"], False)
    Scheduler(sess, approvals, clock=lambda: datetime(2026, 10, 26, 13, 0)).tick()
    wait_idle(sess)
    schedules.set_enabled(s_a["id"], True)
    schedules.set_enabled(s_b["id"], True)

    check("a run with no declined actions adds nothing and leaves other entries alone",
          len(sess.needs_approval) == 2
          and [e["schedule_id"] for e in sess.needs_approval] == [s_a["id"], s_b["id"]])

    # 4. An interactive run never adds an entry
    agent.script = lambda a: "chat reply"
    next_model(sess)
    sess.start("interactive question")
    wait_idle(sess)

    check("an interactive run never adds an entry",
          len(sess.needs_approval) == 2
          and [e["schedule_id"] for e in sess.needs_approval] == [s_a["id"], s_b["id"]])

    # 5. Restart: a new Session over the same LOG_DIR has the same entries
    sess_restart, _, _ = make()
    check("restart: a new Session over the same LOG_DIR has the same entries",
          len(sess_restart.needs_approval) == len(sess.needs_approval)
          and [e["id"] for e in sess_restart.needs_approval] == [e["id"] for e in sess.needs_approval]
          and [e["schedule_id"] for e in sess_restart.needs_approval] == [e["schedule_id"] for e in sess.needs_approval]
          and [e["prompt"] for e in sess_restart.needs_approval] == [e["prompt"] for e in sess.needs_approval]
          and [e["actions"] for e in sess_restart.needs_approval] == [e["actions"] for e in sess.needs_approval]
          and [e["t"] for e in sess_restart.needs_approval] == [e["t"] for e in sess.needs_approval])

    # 6. dismiss_approval removes entry, returns False for unknown id, survives restart
    check("dismiss_approval returns False for an unknown id", sess.dismiss_approval("nonexistent-id") is False)

    to_dismiss = sess.needs_approval[0]
    dismiss_id = to_dismiss["id"]
    remaining_id = sess.needs_approval[1]["id"]
    dismiss_ok = sess.dismiss_approval(dismiss_id)
    sidecar_path = g.LOG_DIR / f"{dismiss_id}.handled.txt"
    check("dismiss_approval removes the entry",
          dismiss_ok is True
          and len(sess.needs_approval) == 1
          and sess.needs_approval[0]["id"] == remaining_id
          and sidecar_path.exists())

    sess_restart_after_dismiss, _, _ = make()
    check("the dismissal survives a restart",
          len(sess_restart_after_dismiss.needs_approval) == 1
          and sess_restart_after_dismiss.needs_approval[0]["id"] == remaining_id)

    # 7. A malformed or truncated log file, and a log without a start entry, are skipped without error
    (g.LOG_DIR / "99999999-000001-corrupt.jsonl").write_text("{broken json\n")
    (g.LOG_DIR / "99999999-000002-truncated.jsonl").write_text('{"t": "2026-10-26T12:00:00", "kind": "start"')
    (g.LOG_DIR / "99999999-000003-nostart.jsonl").write_text(
        json.dumps({"t": "2026-10-26T12:00:00", "kind": "deferred", "actions": ["do bad"]}) + "\n"
    )
    sess_bad_files, _, _ = make()
    check("a malformed or truncated log file, and a log without a start entry, are skipped without error",
          not any(bad in e["id"] for bad in ("corrupt", "truncated", "nostart")
                  for e in sess_bad_files.needs_approval))

    # 8. The 50-run cap on rebuild
    cap_dir = tmp / "cap_logs"
    cap_dir.mkdir()
    g.LOG_DIR = cap_dir
    for i in range(55):
        fname = f"20261026-{100000 + i:06d}-m.jsonl"
        t_iso = f"2026-10-26T10:{i // 60:02d}:{i % 60:02d}"
        (cap_dir / fname).write_text(
            json.dumps({"t": t_iso, "kind": "start", "schedule": f"sched_{i}", "prompt": f"prompt_{i}"}) + "\n"
            + json.dumps({"t": t_iso, "kind": "deferred", "actions": [f"action_{i}"]}) + "\n"
        )
    sess_cap, _, _ = make()
    check("the 50-run cap on rebuild",
          len(sess_cap.needs_approval) == 50
          and sess_cap.needs_approval[0]["schedule_id"] == "sched_5"
          and sess_cap.needs_approval[-1]["schedule_id"] == "sched_54")

    # 9. Secrets in loaded actions are redacted
    sec_dir = tmp / "sec_logs"
    sec_dir.mkdir()
    g.LOG_DIR = sec_dir
    secret_token = "sk-loaded-secret-key-12345"
    (sec_dir / "20261026-120000-m.jsonl").write_text(
        json.dumps({"t": "2026-10-26T12:00:00", "kind": "start", "schedule": "s_sec", "prompt": f"leak {secret_token}"}) + "\n"
        + json.dumps({"t": "2026-10-26T12:00:01", "kind": "deferred", "actions": [f"write {secret_token}"]}) + "\n"
    )
    g._secrets = lambda: [secret_token]
    sess_sec, _, _ = make()
    check("secrets in loaded actions are redacted",
          len(sess_sec.needs_approval) == 1
          and secret_token not in json.dumps(sess_sec.needs_approval)
          and "[REDACTED]" in sess_sec.needs_approval[0]["prompt"]
          and "[REDACTED]" in sess_sec.needs_approval[0]["actions"][0])
    g._secrets = lambda: []

    # 10. Only a deferring or dismissed newer run supersedes an older deferral, as in a live session
    sup_dir = tmp / "sup_logs"
    sup_dir.mkdir()
    g.LOG_DIR = sup_dir

    def sup_log(stem: str, schedule: str, *later: dict) -> None:
        start = {"t": "2026-10-26T09:00:00", "kind": "start", "schedule": schedule, "prompt": "p"}
        (sup_dir / f"{stem}.jsonl").write_text("\n".join(json.dumps(e) for e in (start, *later)) + "\n")

    sup_log("20261026-090000-m", "s_a", {"kind": "deferred", "actions": ["write a"]})
    sup_log("20261026-100000-m", "s_a", {"kind": "final", "answer": "nothing to do"})
    sup_log("20261026-110000-m", "s_a")  # a stopped run: start entry only
    check("a newer clean or stopped run does not hide an older deferral after a restart",
          [e["id"] for e in make()[0].needs_approval] == ["20261026-090000-m"])
    sup_log("20261026-120000-m", "s_a", {"kind": "deferred", "actions": ["write b"]})
    check("a newer deferring run supersedes the older one after a restart",
          [e["id"] for e in make()[0].needs_approval] == ["20261026-120000-m"])
    (sup_dir / "20261026-120000-m.handled.txt").write_text("handled\n")
    check("a dismissed newer run still hides the older deferral after a restart",
          make()[0].needs_approval == [])

finally:
    g.LOG_DIR = saved_log_dir
    g._secrets = lambda: []

# --- scheduled run time limits (#53) -----------------------------------------------------------

# 1. A scheduled run that hangs is stopped after the limit and the Session returns to idle;
#    recorded status and log entry show the timeout; hooks are restored afterwards.
reset_schedules()
sess, approvals, agent = make(schedule_timeout=0.2)
agent.gate = threading.Event()
s_hang = schedules.add("hanging scheduled run", "*/5 * * * *", now=T0)
sched, clock = scheduler_for(sess, approvals, T0 + timedelta(minutes=5))
next_model(sess)
sched.tick()
wait_running(sess)
check("hanging run starts running", sess.status == "running")
wait_idle(sess)
check("a scheduled run that hangs is stopped after the limit and the Session returns to idle", sess.status == "idle")

entry_timeout = schedules.load()[0]
check("the recorded status shows the timeout",
      entry_timeout.get("last_status") == "timeout" and entry_timeout.get("last_error") == "")
check("prompt text never appears in status fields (timeout)",
      s_hang["prompt"] not in (entry_timeout.get("last_status") or "")
      and s_hang["prompt"] not in (entry_timeout.get("last_error") or ""))
timeout_log_entries = [e for e in entries(g._log_file) if e.get("kind") == "timeout"]
check("the log entry shows the timeout with schedule and limit",
      len(timeout_log_entries) == 1
      and timeout_log_entries[0].get("schedule") == s_hang["id"]
      and timeout_log_entries[0].get("limit") == 0.2)
check("the timeout log entry never includes prompt text",
      s_hang["prompt"] not in json.dumps(timeout_log_entries[0]))
check("hooks are restored afterwards", g.CONFIRM is interactive_confirm and g.ASK is interactive_ask)

# 2. A run that finishes before the limit is unaffected, and its timer does not later stop the NEXT run
reset_schedules()
sess, approvals, agent = make()
sched = Scheduler(sess, approvals, schedule_timeout=0.2, clock=lambda: T0 + timedelta(minutes=5))
agent.gate = None
agent.script = lambda a: "fast answer"
s_fast = schedules.add("fast run", "*/5 * * * *", now=T0)
next_model(sess)
sched.tick()
wait_idle(sess)
check("a run that finishes before the limit is unaffected",
      sess.answer == "fast answer" and schedules.load()[0].get("last_status") == "ok")

# Start next run with slow gate, sleep longer than previous 0.2s timer, and verify it is not stopped
agent.gate = threading.Event()
next_model(sess)
sess.start("next interactive run")
wait_running(sess)
time.sleep(0.35)
check("its timer does not later stop the NEXT run", sess.status == "running" and not agent.stopped.is_set())
agent.gate.set()
wait_idle(sess)
check("next run finishes cleanly after gate unblocks", sess.status == "idle")

# 3. An interactive run with the same slow agent is NOT stopped
sess, approvals, agent = make(schedule_timeout=0.2)
agent.gate = threading.Event()
next_model(sess)
sess.start("interactive slow run")
wait_running(sess)
time.sleep(0.35)
check("an interactive run with the same slow agent is NOT stopped",
      sess.status == "running" and not agent.stopped.is_set())
agent.gate.set()
wait_idle(sess)
check("interactive slow run finished when unblocked", sess.status == "idle")

# 4. Limit 0 disables the timer
reset_schedules()
sess, approvals, agent = make(schedule_timeout=0.0)
agent.gate = threading.Event()
s_nolim = schedules.add("no limit run", "*/5 * * * *", now=T0)
sched, clock = scheduler_for(sess, approvals, T0 + timedelta(minutes=5))
next_model(sess)
sched.tick()
wait_running(sess)
time.sleep(0.35)
check("limit 0 disables the timer: scheduled run not stopped",
      sess.status == "running" and not agent.stopped.is_set())
agent.gate.set()
wait_idle(sess)
check("limit 0 scheduled run finishes cleanly once unblocked",
      sess.status == "idle" and schedules.load()[0].get("last_status") == "ok")

# 5. Bad SCHEDULE_TIMEOUT values fall back to the default instead of dropping the limit
saved_env = os.environ.get("SCHEDULE_TIMEOUT")
try:
    for raw, want in (("inf", 900.0), ("nan", 900.0), ("-5", 900.0), ("abc", 900.0), ("", 900.0), ("0", 0.0), ("60", 60.0)):
        os.environ["SCHEDULE_TIMEOUT"] = raw
        check(f"SCHEDULE_TIMEOUT={raw!r} gives {want}", make()[0].schedule_timeout == want)
finally:
    if saved_env is None:
        os.environ.pop("SCHEDULE_TIMEOUT", None)
    else:
        os.environ["SCHEDULE_TIMEOUT"] = saved_env

# --- scheduler robustness: summary in flight and failed mark_ran (#59) ---------

# 1. While a summary is held in flight (use the existing call_model hook with a gate),
#    a due schedule does not start; after the gate is released it starts on the next tick.
reset_schedules()
summary_gate = threading.Event()
summary_started = threading.Event()


def gated_summary_model(text: str) -> str:
    summary_started.set()
    summary_gate.wait(5)
    return "gated summary"


sess, approvals, agent = make()
sess.run_summaries = True
sess.call_model = gated_summary_model
s_held1 = schedules.add("first schedule", "*/5 * * * *", now=T0)
s_held2 = schedules.add("second schedule", "*/5 * * * *", now=T0)
sched, clock = scheduler_for(sess, approvals, T0 + timedelta(minutes=5))
next_model(sess)

sched.tick()
wait_idle(sess)
summary_started.wait(5)

check("while a summary is held in flight, a due schedule does not start", sched.tick() is None)

summary_gate.set()
for _ in range(100):
    if not getattr(sess, "summarizing", False):
        break
    time.sleep(0.01)

next_model(sess)
check("after the summary gate is released the schedule starts on the next tick",
      sched.tick() == s_held2["id"])
wait_idle(sess)

# 2. A summary hung longer than the bound does not block the schedule forever
#    (inject the bound or the clock so the test is fast).
reset_schedules()
hung_gate = threading.Event()
hung_started = threading.Event()


def hung_summary_model(text: str) -> str:
    hung_started.set()
    hung_gate.wait(5)
    return "hung summary"


sess, approvals, agent = make()
sess.run_summaries = True
sess.call_model = hung_summary_model
s_hung1 = schedules.add("first schedule hung", "*/5 * * * *", now=T0)
s_hung2 = schedules.add("second schedule hung", "*/5 * * * *", now=T0)
sched, clock = scheduler_for(sess, approvals, T0 + timedelta(minutes=5))
next_model(sess)

sched.tick()
wait_idle(sess)
hung_started.wait(5)

t0_tick = sched.tick()
clock["now"] += timedelta(seconds=121)
t1_tick = sched.tick()
check("a summary hung longer than the bound does not block the schedule forever",
      t0_tick is None and t1_tick == s_hung2["id"])

hung_gate.set()
wait_idle(sess)

# 3. The summarizing flag is cleared when the summary raises.
reset_schedules()
raise_gate = threading.Event()
raise_started = threading.Event()


def exploding_summary_model(text: str) -> str:
    raise_started.set()
    raise_gate.wait(5)
    raise RuntimeError("summary exploded")


sess, approvals, agent = make()
sess.run_summaries = True
sess.call_model = exploding_summary_model
next_model(sess)
sess.start("prompt for summary failure")
wait_idle(sess)
raise_started.wait(5)

was_summarizing = getattr(sess, "summarizing", False)
raise_gate.set()
for _ in range(100):
    if not getattr(sess, "summarizing", False):
        break
    time.sleep(0.01)

is_summarizing = getattr(sess, "summarizing", True)
check("the summarizing flag is cleared when the summary raises",
      was_summarizing is True and is_summarizing is False)

# 4. With schedules.mark_ran patched to raise: the first tick starts the run,
#    a second tick after the run ends does not start it again, and a new slot
#    (patch restored, next_run changed) does run.
reset_schedules()
sess, approvals, agent = make()
s_fail_mr = schedules.add("task with failing mark_ran", "*/5 * * * *", now=T0)
sched, clock = scheduler_for(sess, approvals, T0 + timedelta(minutes=5))
next_model(sess)

real_mark_ran = schedules.mark_ran


def broken_mark_ran(sid: str, now: datetime) -> None:
    raise OSError("schedules.json disk full")


schedules.mark_ran = broken_mark_ran
try:
    sched.tick()
    wait_idle(sess)
    first_tick_started = len(agent.inputs) == 1

    sched.tick()
    wait_idle(sess)
    second_tick_skipped = len(agent.inputs) == 1
finally:
    schedules.mark_ran = real_mark_ran

clock["now"] = T0 + timedelta(minutes=10)
scheds = schedules.load()
scheds[0]["next_run"] = clock["now"].isoformat()
schedules._atomic_save(scheds)

next_model(sess)
sched.tick()
wait_idle(sess)
new_slot_ran = len(agent.inputs) == 2

check("with mark_ran raising, the first tick starts the run", first_tick_started)
check("a second tick after the run ends does not start it again", second_tick_skipped)
check("and a new slot (patch restored, next_run changed) does run", new_slot_ran)

# 5. The in-memory dict does not grow without bound.
reset_schedules()
sess, approvals, agent = make()
s_bound = schedules.add("repeating task", "*/5 * * * *", now=T0)
sched, clock = scheduler_for(sess, approvals, T0 + timedelta(minutes=5))
next_model(sess)

for i in range(1, 6):
    clock["now"] = T0 + timedelta(minutes=5 * i)
    sched.tick()
    wait_idle(sess)

started_dict = getattr(sched, "_started", None)
dict_bounded_across_runs = started_dict is not None and len(started_dict) <= 1

capped_ok = False
if started_dict is not None:
    max_cap = getattr(sched, "_max_started", 1000)
    for i in range(max_cap + 100):
        sched._started[f"dummy_{i}"] = f"2026-10-28T00:{i:04d}"
        if len(sched._started) > max_cap:
            if hasattr(sched, "_prune_started"):
                sched._prune_started()
    capped_ok = len(sched._started) <= max_cap

check("the in-memory dict does not grow without bound",
      dict_bounded_across_runs and capped_ok)

# 6. Review additions (#59). The cap itself: ids that exist with a matching next_run are kept by the first
#    pass of _prune_started, so only the cap can trim them (the dummy ids in test 5 are dropped as unknown).
reset_schedules()
sess, approvals, agent = make()
sched, clock = scheduler_for(sess, approvals, T0 + timedelta(minutes=5))
sched._max_started = 3
for i in range(6):
    sc_i = schedules.add(f"cap schedule {i}", "*/5 * * * *", now=T0)
    sched._started[sc_i["id"]] = sc_i["next_run"]
sched._prune_started()
check("the cap trims entries that are otherwise still valid", len(sched._started) == 3)

# 7. A stale wait start does not cut a later summary's wait short: a summary is seen, an interactive
#    run follows (ticks return early), then a new summary begins with a schedule due.
reset_schedules()
sess, approvals, agent = make()
s_stale = schedules.add("stale wait schedule", "*/5 * * * *", now=T0)
sched, clock = scheduler_for(sess, approvals, T0 + timedelta(minutes=5))
sess._summarizing.set()
sched.tick()  # first summary seen
sess._summarizing.clear()
sess.status = "running"  # an interactive run, ten minutes long
clock["now"] = T0 + timedelta(minutes=15)
sched.tick()
sess.status = "idle"
sess._summarizing.set()  # its summary has just begun
started_during_fresh_summary = sched.tick()
sess._summarizing.clear()
check("a stale wait start does not let a schedule start during a fresh summary", started_during_fresh_summary is None)

print(f"\n{check.failed} failed")
sys.exit(1 if check.failed else 0)
