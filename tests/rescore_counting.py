"""Re-score saved file-count eval logs with the current `COUNTING_EXPECT` (#49).

The count check once needed "files" after the number, which failed a correct bare "12". This reads each log, keeps the
other pass conditions (an answer, no step-cap hit, a passing disk check) and re-applies the current regex to the saved
answers, so earlier runs can be scored under the same definition without running a model again.

Usage: .venv/bin/python tests/rescore_counting.py [logs-dir]
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import eval as ev  # noqa: E402


def rescore(run: dict) -> bool:
    """Whether a saved run passes under the current count regex."""
    answer = run.get("answer") or ""
    return bool(answer) and not run.get("hit_cap") and (run.get("check", "") == "" or bool(run.get("passed"))) \
        and bool(re.search(ev.COUNTING_EXPECT, answer, re.I))


def main(logs: Path) -> None:
    for f in sorted(logs.glob("eval-*.json")):
        try:
            d = json.loads(f.read_text())
        except (OSError, ValueError):
            continue
        if not isinstance(d, dict) or not isinstance(d.get("runs"), list) \
                or d.get("prompt") not in (ev.COUNTING_PROMPT, ev.COUNTING_HOME_PROMPT):
            continue
        runs = d["runs"]
        old = sum(bool(r.get("passed")) for r in runs)
        new = sum(rescore(r) for r in runs)
        print(f"{f.name}: {old}/{len(runs)} as logged, {new}/{len(runs)} re-scored")


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent / "logs")
