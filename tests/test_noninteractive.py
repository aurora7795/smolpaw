"""
Tests for non-interactive mode (agent.py -p "request" and --json).
Run with: .venv/bin/python tests/test_noninteractive.py

Uses a fake agent, temporary workspace and logs; never touches the real workspace, notes.md or logs/.
"""

import io
import itertools
import json
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import agent
import generic_tools as g
from smolagents.utils import AgentError, AgentMaxStepsError

check_failed = 0


def check(name: str, cond: bool) -> None:
    global check_failed
    print(f"{'PASS' if cond else 'FAIL'}  {name}")
    if not cond:
        check_failed += 1


real_logs = g.ROOT / "logs"
logs_snapshot = {(p.name, p.stat().st_size) for p in real_logs.iterdir()} if real_logs.exists() else set()

saved_log_dir = g.LOG_DIR
saved_workspace = g.WORKSPACE
saved_skills = g.SKILLS
saved_memory = g.MEMORY

tmp = Path(tempfile.mkdtemp())
g.LOG_DIR = tmp / "logs"
g.WORKSPACE = tmp / "workspace"
g.SKILLS = tmp / "skills"
g.MEMORY = tmp / "memory.md"
g.WORKSPACE.mkdir()
g.SKILLS.mkdir()

models = itertools.count()


class FakeAgent:
    """Runs `script(agent)` as the agent's work."""

    def __init__(self, script=None):
        self.memory = type("M", (), {"steps": []})()
        self.monitor = type("Mon", (), {"get_total_token_counts": lambda s: type("T", (), {
            "input_tokens": 120, "output_tokens": 30})()})()
        self.stall_reason = None
        self.script = script or (lambda a: "test answer")
        self.inputs = []

    def run(self, text):
        self.inputs.append(text)
        return self.script(self)

    def interrupt(self):
        pass


try:
    # 1. Plain mode: answer, [Harness says], "no changes made", exit 0
    fake = FakeAgent(lambda a: "simple answer")
    out, err = io.StringIO(), io.StringIO()
    code = agent.run_noninteractive(fake, f"m{next(models)}", "hello", out_stream=out, err_stream=err)
    check("plain mode exits with 0", code == 0)
    check("plain mode prints the answer", "simple answer" in out.getvalue())
    check("plain mode prints the [Harness says] report", "[Harness says]" in out.getvalue())
    check("plain mode prints 'no changes made' when nothing changed", "no changes made" in out.getvalue())

    # 2. --json mode: every line parses, last is final, nothing non-JSON on stdout, [log] on stderr
    fake = FakeAgent(lambda a: "json answer")
    out, err = io.StringIO(), io.StringIO()
    code = agent.run_noninteractive(fake, f"m{next(models)}", "hello json", json_mode=True, out_stream=out, err_stream=err)
    check("--json exits with 0", code == 0)
    lines = [line.strip() for line in out.getvalue().splitlines() if line.strip()]
    parsed = []
    valid_json = True
    for line in lines:
        try:
            parsed.append(json.loads(line))
        except Exception:
            valid_json = False
    check("--json stdout: every line parses as JSON", valid_json and len(parsed) >= 2)
    check("--json stdout: last entry is final", bool(parsed and parsed[-1].get("kind") == "final"))
    check("--json stdout: final entry contains answer and tokens",
          bool(parsed and parsed[-1].get("answer") == "json answer" and parsed[-1].get("input_tokens") == 120))
    check("--json stdout: nothing non-JSON on stdout", valid_json and bool(lines))
    check("--json [log] path line goes to stderr", "[log]" in err.getvalue())

    # 3. Exit code 2 on step limit
    fake_step = FakeAgent(lambda a: "unfinished")
    dummy_logger = type("L", (), {"log_error": lambda *args: None})()
    step_err = type("Step", (), {"error": AgentMaxStepsError("limit", dummy_logger)})()
    fake_step.memory.steps = [step_err]
    out, err = io.StringIO(), io.StringIO()
    code = agent.run_noninteractive(fake_step, f"m{next(models)}", "do long task", out_stream=out, err_stream=err)
    check("step limit exit code is 2", code == 2)
    check("step limit answer reports limit reached", "STEP LIMIT REACHED" in out.getvalue())

    # Step limit with --json
    fake_step_json = FakeAgent(lambda a: "unfinished")
    fake_step_json.memory.steps = [step_err]
    out, err = io.StringIO(), io.StringIO()
    code = agent.run_noninteractive(fake_step_json, f"m{next(models)}", "do long task json", json_mode=True, out_stream=out, err_stream=err)
    check("step limit with --json exit code is 2", code == 2)
    json_lines = [json.loads(line) for line in out.getvalue().splitlines() if line.strip()]
    check("step limit with --json ends with final entry", bool(json_lines and json_lines[-1]["kind"] == "final"))

    # 4. Exit code 3 on stall stop
    def stall_script(a):
        g.LAST_RESULT = "search: no results"
        a.stall_reason = "the same call failed 3 times in a row"
        raise AgentError("Agent interrupted.", type("L", (), {"log_error": lambda *args: None})())

    fake_stall = FakeAgent(stall_script)
    out, err = io.StringIO(), io.StringIO()
    code = agent.run_noninteractive(fake_stall, f"m{next(models)}", "stalling task", out_stream=out, err_stream=err)
    check("stall exit code is 3", code == 3)
    check("stall answer reports stopped early", "STOPPED EARLY: the same call failed 3 times in a row" in out.getvalue())

    # Stall with --json
    fake_stall_json = FakeAgent(stall_script)
    out, err = io.StringIO(), io.StringIO()
    code = agent.run_noninteractive(fake_stall_json, f"m{next(models)}", "stalling task json", json_mode=True, out_stream=out, err_stream=err)
    check("stall with --json exit code is 3", code == 3)
    json_lines = [json.loads(line) for line in out.getvalue().splitlines() if line.strip()]
    check("stall with --json ends with final entry", bool(json_lines and json_lines[-1]["kind"] == "final"))

    # 5. Exit code 1 on exception
    def boom_script(a):
        raise RuntimeError("model service crashed")

    fake_boom = FakeAgent(boom_script)
    out, err = io.StringIO(), io.StringIO()
    code = agent.run_noninteractive(fake_boom, f"m{next(models)}", "failing task", out_stream=out, err_stream=err)
    check("exception exit code is 1", code == 1)
    check("exception message is printed to stderr", "[Error] model service crashed" in err.getvalue())

    # Exception with --json
    fake_boom_json = FakeAgent(boom_script)
    out, err = io.StringIO(), io.StringIO()
    code = agent.run_noninteractive(fake_boom_json, f"m{next(models)}", "failing task json", json_mode=True, out_stream=out, err_stream=err)
    check("exception with --json exit code is 1", code == 1)
    check("exception with --json printed to stderr", "[Error] model service crashed" in err.getvalue())
    raw_lines = [line.strip() for line in out.getvalue().splitlines() if line.strip()]
    check("exception with --json stdout has only valid JSON lines", all(json.loads(line) for line in raw_lines))

    # 6. A write that would ask [y/N] is declined, file not created, decline reported
    target_file = g.WORKSPACE / "declined_write.txt"
    if target_file.exists():
        target_file.unlink()

    def write_script(a):
        res = g.write_file("declined_write.txt", "unwanted content")
        return f"tool result: {res}"

    fake_writer = FakeAgent(write_script)
    out, err = io.StringIO(), io.StringIO()
    code = agent.run_noninteractive(fake_writer, f"m{next(models)}", "write test", out_stream=out, err_stream=err)
    check("write task exit code is 0", code == 0)
    check("a write that would ask [y/N] is declined and file not created", not target_file.exists())
    check("the decline is reported in [Harness says]", "declined:" in out.getvalue() and "declined_write.txt" in out.getvalue())

    # 7. ask_user gets the no-answer reply
    def ask_script(a):
        ans = g.ask_user("May I delete workspace?")
        return f"answer: {ans}"

    fake_asker = FakeAgent(ask_script)
    out, err = io.StringIO(), io.StringIO()
    code = agent.run_noninteractive(fake_asker, f"m{next(models)}", "ask test", out_stream=out, err_stream=err)
    check("ask_user task exit code is 0", code == 0)
    check("ask_user gets the no-answer reply", agent.NO_ANSWER in out.getvalue())

    # 8. Hooks are restored after run (both normal and erroring)
    orig_confirm, orig_ask = g.CONFIRM, g.ASK
    fake_dummy = FakeAgent(lambda a: "done")
    agent.run_noninteractive(fake_dummy, f"m{next(models)}", "hook test", out_stream=io.StringIO(), err_stream=io.StringIO())
    check("CONFIRM hook restored after normal finish", g.CONFIRM == orig_confirm)
    check("ASK hook restored after normal finish", g.ASK == orig_ask)

    fake_err_hook = FakeAgent(lambda a: (_ for _ in ()).throw(ValueError("hook crash")))
    agent.run_noninteractive(fake_err_hook, f"m{next(models)}", "hook test err", out_stream=io.StringIO(), err_stream=io.StringIO())
    check("CONFIRM hook restored after exception", g.CONFIRM == orig_confirm)
    check("ASK hook restored after exception", g.ASK == orig_ask)

    # 9. -p with --tools radarr errors
    out, err = io.StringIO(), io.StringIO()
    code = agent.run_noninteractive(fake_dummy, f"m{next(models)}", "radarr test", toolset="radarr", out_stream=out, err_stream=err)
    check("-p with --tools radarr returns exit code 1", code == 1)
    check("-p with --tools radarr reports clear error", "Error: -p is only supported with generic tools (not radarr)." in err.getvalue())

    # 10. CLI argument parsing tests (subprocess)
    res = subprocess.run([sys.executable, "agent.py", "-p", "test", "--tools", "radarr"],
                         capture_output=True, text=True)
    check("CLI -p with --tools radarr exits with 1", res.returncode == 1)
    check("CLI -p with --tools radarr error message on stderr", "generic tools (not radarr)" in res.stderr)

    res = subprocess.run([sys.executable, "agent.py", "-p", "test", "--web"],
                         capture_output=True, text=True)
    check("CLI -p with --web exits with 1", res.returncode == 1)
    check("CLI -p with --web error message on stderr", "--web" in res.stderr)

    res = subprocess.run([sys.executable, "agent.py", "--json"],
                         capture_output=True, text=True)
    check("CLI --json without -p exits non-zero", res.returncode != 0)
    check("CLI --json without -p explains error", "--json requires -p" in res.stderr)

    # 11. Log isolation: real logs/ must not be touched
    if real_logs.exists():
        after = {(p.name, p.stat().st_size) for p in real_logs.iterdir()}
        check("the test suite wrote no run logs to the real logs/ directory", after == logs_snapshot)

finally:
    g.LOG_DIR = saved_log_dir
    g.WORKSPACE = saved_workspace
    g.SKILLS = saved_skills
    g.MEMORY = saved_memory

print(f"\n{check_failed} failed")
sys.exit(1 if check_failed else 0)
