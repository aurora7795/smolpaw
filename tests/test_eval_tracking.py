"""
Tests for the tracking mode of tests/eval.py (#87), run with a stub agent instead of a model.
Run with: .venv/bin/python tests/test_eval_tracking.py

Tests must not write to the real workspace/, notes.md, logs/ or .undo/.
"""

import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

from smolagents.memory import ActionStep, ToolCall
from smolagents.monitoring import Timing

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import generic_tools as g  # noqa: E402
from tests import eval as ev  # noqa: E402
from tests import tracking_fixture as tf  # noqa: E402

check_failed = 0


def check(name: str, cond: bool) -> None:
    global check_failed
    print(f"{'PASS' if cond else 'FAIL'}  {name}")
    if not cond:
        check_failed += 1


real_undo = ROOT / ".undo"
undo_snapshot = {(p.name, p.stat().st_size) for p in real_undo.iterdir()} if real_undo.exists() else set()
real_logs = ROOT / "logs"
logs_snapshot = {(p.name, p.stat().st_size) for p in real_logs.iterdir()} if real_logs.exists() else set()


class StubAgent:
    """Stands in for a smolagents agent: runs a scripted function that calls the real tools."""

    def __init__(self, script):
        self.script = script
        self.memory = SimpleNamespace(steps=[])
        self.monitor = SimpleNamespace(get_total_token_counts=lambda: SimpleNamespace(input_tokens=1, output_tokens=1))

    def run(self, prompt: str) -> str:
        return self.script()


def _stub_with_steps(script_for) -> StubAgent:
    """A stub whose memory holds the scripted ActionSteps, so run_once can read their tool calls."""
    script = script_for(None, None)
    agent = StubAgent(script)
    agent.memory.steps = script.steps
    return agent


saved = (g.WORKSPACE, g.UNDO_DIR, g.CONFIRM, ev.build_agent)
tmp = Path(tempfile.mkdtemp())


def run_case(case_name: str, script_for) -> dict:
    """Build the case in a fresh workspace and run a stub agent through the real run_once."""
    ws = tmp / f"ws-{len(list(tmp.iterdir()))}"
    case = next(c for c in tf.build(ws) if c.name == case_name)
    g.WORKSPACE, g.UNDO_DIR = ws, ws.parent / (ws.name + "-undo")
    g.CONFIRM = ev.workspace_write_confirm(ws)
    ev.build_agent = lambda *a, **k: StubAgent(script_for(ws, case))
    return ev.run_once("stub", case.prompt, case.expects, 12, check=lambda: case.check(ws))


try:
    # --- scripted approvals -------------------------------------------------------------------
    ws = tmp / "approval"
    ws.mkdir()
    ws = ws.resolve()  # write_file describes resolved paths
    confirm = ev.workspace_write_confirm(ws)
    check("a write inside the workspace is approved", confirm(f"Write 10 chars to {ws}/a.md:\nhello"))
    check("a write outside the workspace is declined", not confirm(f"Write 10 chars to {tmp}/other/a.md  (OUTSIDE workspace/):\nhi"))
    check("a path that only shares the folder name prefix is declined", not confirm(f"Write 10 chars to {ws}-evil/a.md:\nhi"))
    check("an edit inside the workspace is approved", confirm(f"Edit {ws}/a.md: replace 3 chars with 3\n- old\n+ new"))
    check("an edit outside the workspace or sharing only a name prefix is declined",
          not confirm(f"Edit {tmp}/other/a.md: replace 3 chars with 3\n- old\n+ new") and not confirm(f"Edit {ws}-evil/a.md: replace 3 chars with 3\n- a\n+ b"))
    check("a shell command is declined", not confirm("Run shell command:\n  rm -rf /"))
    (ws / "a.md").write_text("x")
    sh = lambda cmd: confirm(f"Run shell command in workspace/:\n  {cmd}")  # noqa: E731
    check("a literal sed -i replacement on a workspace file is approved", sh("sed -i 's/420 kilowatt hours/980 kilowatt hours/' a.md"))
    check("sed -i with a backup suffix or an empty one is approved",
          sh("sed -i.bak 's/a b/c d/g' a.md") and sh("sed -i '' 's/a/b/' a.md"))
    check("sed on a file that does not exist is declined", not sh("sed -i 's/a/b/' nope.md"))
    check("sed on a path is declined", not sh("sed -i 's/a/b/' ../a.md") and not sh("sed -i 's/a/b/' /etc/hosts"))
    check("sed with the e or w flag is declined", not sh("sed -i 's/a/b/e' a.md") and not sh("sed -i 's/a/b/w out' a.md"))
    check("sed chained with another command is declined",
          not sh("sed -i 's/a/b/' a.md; rm a.md") and not sh("sed -i 's/a/b/' a.md && cat a.md") and not sh("sed -i 's/a/b/' a.md | cat"))
    check("read-only pipelines are approved",
          sh("grep -oE '[0-9]+' a.md | head -20") and sh("cat a.md | tail -50") and sh("head -c 100 a.md | od -c | head -10")
          and sh("grep -n 'a|b' a.md 2>/dev/null") and sh("find . -name 'a.md' | head -5"))
    check("pipelines with writes, chaining, substitution or outside paths are declined",
          not sh("cat a.md > b.md") and not sh("cat a.md; rm a.md") and not sh("cat a.md && ls") and not sh("cat a.md || echo no")
          and not sh("cat $(ls)") and not sh("cat `ls`") and not sh("cat /etc/hosts | head") and not sh("cat ../a.md")
          and not sh("ls | xargs rm") and not sh("find . -delete") and not sh("find . -exec rm {} +")
          and not sh("sort -o a.md a.md") and not sh("tail -f a.md") and not sh("grep a a.md | tee b.md") and not sh("cat a.md | sh"))
    check("other editors and interpreters are declined",
          not sh("awk '{print}' a.md") and not sh("python3 -c 'print(1)'") and not sh("perl -pi -e 's/a/b/' a.md"))
    check("reading outside the workspace is declined", not confirm("Read file outside workspace/:\n  /etc/hosts"))

    # --- edit_one_section ---------------------------------------------------------------------
    def edit_ok(ws, case):
        def go():
            p = ws / tf.CASE_A_FILENAME
            g.write_file(tf.CASE_A_FILENAME, p.read_text().replace(tf.CASE_A_TARGET_OLD, tf.CASE_A_TARGET_NEW))
            return "Done."
        return go

    def edit_from_clipped_view(ws, case):
        def go():
            seen = (ws / tf.CASE_A_FILENAME).read_text()[:g.MAX_OUT]
            g.write_file(tf.CASE_A_FILENAME, seen)  # a model that wrote back only what it saw
            return "Done."
        return go

    def does_nothing(ws, case):
        return lambda: "Done."

    def writes_outside(ws, case):
        def go():
            g.write_file(f"../{ws.name}-outside/{tf.CASE_A_FILENAME}", "x")
            return "Done."
        return go

    r = run_case("edit_one_section", edit_ok)
    check("a correct edit passes", r["passed"] and r["check"].startswith("file equals"))
    check("the write was approved and logged", any(a.startswith("wrote ") for a in r["actions"]))
    def edit_with_tool(ws, case):
        def go():
            g.edit_file(tf.CASE_A_FILENAME, tf.CASE_A_TARGET_OLD, tf.CASE_A_TARGET_NEW)
            return "Done."
        return go

    r = run_case("edit_one_section", edit_with_tool)
    check("a correct edit_file call passes and is logged as an action", r["passed"] and any(a.startswith("edited ") for a in r["actions"]))
    r = run_case("edit_one_section", edit_from_clipped_view)
    check("writing back only the clipped view fails", not r["passed"] and "truncated" in r["check"])
    r = run_case("edit_one_section", does_nothing)
    check("doing nothing fails", not r["passed"] and "not modified" in r["check"])
    r = run_case("edit_one_section", writes_outside)
    check("a write outside the workspace is declined and the case still fails",
          not r["passed"] and any(a.startswith("declined") for a in r["actions"]))

    # --- read_three_report: the answer is checked, the files must stay unmodified ---------------
    def report(ws, case):
        return lambda: "hydrology 1485, geology 832, refuge 674"

    def report_partial(ws, case):
        return lambda: "hydrology 1485, geology 832"

    def report_and_overwrite(ws, case):
        def go():
            g.write_file(tf.CASE_C_FILES[0], "x")
            return "hydrology 1485, geology 832, refuge 674"
        return go

    r = run_case("read_three_report", report)
    check("a complete report passes", r["passed"])
    r = run_case("read_three_report", report_partial)
    check("a report missing a figure fails", not r["passed"])
    r = run_case("read_three_report", report_and_overwrite)
    check("a right answer that overwrote a source file fails", not r["passed"] and "modified" in r["check"])

    # --- tool arguments are logged, clipped (#89) -------------------------------------------
    def with_steps(ws, case):
        agent_steps = [
            ActionStep(step_number=1, timing=Timing(start_time=0.0),
                       tool_calls=[ToolCall(name="read_file", arguments={"path": "a.txt", "offset": 4000}, id="1")]),
            ActionStep(step_number=2, timing=Timing(start_time=0.0),
                       tool_calls=[ToolCall(name="run_shell", arguments={"command": "x" * 500}, id="2")]),
        ]

        def go():
            return "hydrology 1485, geology 832, refuge 674"
        go.steps = agent_steps
        return go

    saved_build = ev.build_agent
    ev.build_agent = lambda *a, **k: _stub_with_steps(with_steps)
    case_c = next(c for c in tf.build(tmp / "ws-args") if c.name == "read_three_report")
    r = ev.run_once("stub", case_c.prompt, case_c.expects, 12, check=lambda: case_c.check(tmp / "ws-args"))
    ev.build_agent = saved_build
    check("the run records each call's name and its arguments", r["tools"] == ["read_file", "run_shell"] and len(r["tool_args"]) == 2)
    check("a call's offset argument is kept so a page choice can be audited", "'offset': 4000" in r["tool_args"][0])
    check("a long argument is clipped to 200 characters", len(r["tool_args"][1]) == 200)

    # --- append_keep_all ----------------------------------------------------------------------
    def append_ok(ws, case):
        def go():
            p = ws / tf.CASE_B_FILENAME
            g.write_file(tf.CASE_B_FILENAME, p.read_text() + "\n" + tf.CASE_B_NEW_SECTION + "\n")
            return "Done."
        return go

    r = run_case("append_keep_all", append_ok)
    check("a correct append passes", r["passed"])

    # --- isolation ----------------------------------------------------------------------------
    check("the stub runs recorded clipped_results", "clipped_results" in r)
    check("no undo copies were written to the real .undo/",
          (not real_undo.exists() and not undo_snapshot)
          or {(p.name, p.stat().st_size) for p in real_undo.iterdir()} == undo_snapshot)
finally:
    g.WORKSPACE, g.UNDO_DIR, g.CONFIRM, ev.build_agent = saved

if real_logs.exists():
    check("the test suite wrote no run logs to the real logs/ directory",
          {(p.name, p.stat().st_size) for p in real_logs.iterdir()} == logs_snapshot)

print(f"\n{check_failed} failed")
sys.exit(1 if check_failed else 0)
