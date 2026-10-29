"""
Tests for the tracking mode of tests/eval.py (#87), run with a stub agent instead of a model.
Run with: .venv/bin/python tests/test_eval_tracking.py

Tests must not write to the real workspace/, notes.md, logs/ or .undo/.
"""

import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

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
