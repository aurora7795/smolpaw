"""Parse errors per model across the eval run logs in logs/ (#14).

Reads every logs/eval-*.json that used native history and prints, per model: runs, steps, parse errors, errors per
100 steps, the most common error texts, and the pass rate of runs with and without a parse error. Runs differ in case,
context and code, so the pass-rate split is a rough pooled figure, not a controlled comparison.

Usage: .venv/bin/python tests/parse_error_rate.py [logs-dir]
"""
import collections
import json
import sys
from pathlib import Path


def summarise(logs: Path) -> dict[str, dict]:
    """Per model: counts of runs, steps and parse errors, error texts, and passes with/without a parse error."""
    out: dict[str, dict] = {}
    for f in sorted(logs.glob("eval-*.json")):
        try:
            d = json.loads(f.read_text())
        except (OSError, ValueError):
            continue
        if not isinstance(d, dict) or d.get("history") != "native" or not isinstance(d.get("runs"), list):
            continue
        m = out.setdefault(str(d.get("model")), {"runs": 0, "steps": 0, "errors": 0, "texts": collections.Counter(),
                                                  "with": [0, 0], "without": [0, 0]})
        for r in d["runs"]:
            n = r.get("parse_errors") or 0
            m["runs"] += 1
            m["steps"] += r.get("steps") or 0
            m["errors"] += n
            m["texts"].update(str(t)[:90] for t in r.get("parse_error_detail") or [])
            if r.get("passed") is not None:
                bucket = m["with" if n else "without"]
                bucket[0] += 1
                bucket[1] += bool(r["passed"])
    return out


if __name__ == "__main__":
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent / "logs"
    for model, m in summarise(root).items():
        per100 = 100 * m["errors"] / max(m["steps"], 1)
        print(f"{model}: {m['runs']} runs, {m['steps']} steps, {m['errors']} parse errors ({per100:.1f} per 100 steps, "
              f"{m['errors'] / max(m['runs'], 1):.2f} per run)")
        print(f"  passed with a parse error: {m['with'][1]}/{m['with'][0]}; without: {m['without'][1]}/{m['without'][0]}")
        for text, n in m["texts"].most_common(3):
            print(f"  {n:3} {text}")
