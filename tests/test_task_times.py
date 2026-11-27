"""
Tests for tests/task_times.py (#148). Run with: .venv/bin/python tests/test_task_times.py

Writes synthetic eval logs to a temp folder; touches no real log, model, workspace or notes.
"""

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import task_times as tt  # noqa: E402
from compare_runs import load  # noqa: E402

assert tt.task_key("Using http://127.0.0.1:56477 find   x") == "Using http://127.0.0.1:PORT find x"
assert tt.task_key("see http://127.0.0.1:60000 find x") == tt.task_key("see http://127.0.0.1:1234 find x")
assert tt.task_key("plain text 12345") == "plain text 12345" and tt.task_key("") == ""


def run(passed, wall, steps):
    return {"passed": passed, "wall_s": wall, "steps": steps}


def log(model, prompt, runs, backend="ollama"):
    return {"model": model, "backend": backend, "label": "x", "prompt": prompt, "runs": runs}


tmp = Path(tempfile.mkdtemp())
logs = [
    log("g", "task A http://h:1111", [run(True, 10, 2), run(True, 20, 4), run(False, 30, 6)]),
    log("q", "task A http://h:2222", [run(True, 40, 4), run(True, 60, 6), run(True, 50, 5)]),
    log("g", "task B", [run(False, 10, 2)] * 3),
    log("q", "task B", [run(True, 30, 3)] * 3),
    log("g", "task C", [run(True, 5, 1)] * 2),                       # too few runs
    log("q", "task C", [run(True, 5, 1)] * 3),
    log("g", "task D", [run(True, 5, 1)] * 3, backend="lmstudio"),   # other backend, left out
    log("q", "task D", [run(True, 5, 1)] * 3),
    log("g", "task A http://h:1111", [{"passed": True, "wall_s": None, "steps": 2}, {"passed": True, "wall_s": 9}]),  # unusable runs skipped
]
for i, d in enumerate(logs):
    (tmp / f"eval-{i}.json").write_text(json.dumps(d))
(tmp / "eval-bad.json").write_text("not json")
(tmp / "eval-other.json").write_text(json.dumps({"qwen": []}))

logs.append(log("g", "", [run(True, 5, 1)] * 3))
logs.append(log("q", "", [run(True, 5, 1)] * 3))
for i, d in enumerate(logs[-2:], len(logs) - 2):
    (tmp / f"eval-{i}.json").write_text(json.dumps(d))
loaded = load(str(tmp / "eval-*.json"), None)
assert len(loaded) == len(logs) and "" not in tt.collect(loaded, ["g", "q"], "ollama")
tasks = tt.collect(loaded, ["g", "q"], "ollama")
assert len(tasks["task A http://h:PORT"]["g"]) == 3, "ports blanked, unusable runs skipped"
s = tt.summarise(tasks["task A http://h:PORT"]["g"])
assert s == {"n": 3, "pass": 2, "median_s": 20, "median_steps": 4, "s_per_step": 5.0, "s_per_pass": 30.0}, s
rows, wins = tt.table(tasks, ["g", "q"], 3)
assert len(rows) == 2, rows                                           # A and B; C has too few g runs, D has too few ollama g runs
assert wins == {"g": 1, "q": 1}, wins                                  # A: g 30 vs q 50 per pass; B: g never passed, so q
assert "none passed" in rows[1] and rows[0].startswith("| task A http://h:PORT |")
print("test_task_times: ok")
