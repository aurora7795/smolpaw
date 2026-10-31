"""Replay the second stall rule on recorded eval runs (#77), without a model.

Reads every logs/eval-*.json whose runs carry a `trace` (recorded by tests/eval.py since #77) and, for each limit pair,
reports how many runs the rule would have stopped, how many of those passed (cut short wrongly), and how many steps it
would have saved on runs that did not pass. The trace only covers steps the run made, so a run the first rule (#19)
already stopped is replayed up to that point.

Usage: .venv/bin/python tests/replay_stall.py [--label base77] [logs-dir]
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent import no_progress  # noqa: E402

LIMITS = [(2, 0), (3, 0), (4, 0), (0, 2), (0, 3), (0, 4), (3, 3), (4, 3)]


def load(logs: Path, label: str) -> list[tuple[str, dict]]:
    """(model, run) for every recorded run with a trace, optionally only logs whose label contains `label`."""
    out = []
    for f in sorted(logs.glob("eval-*.json")):
        try:
            d = json.loads(f.read_text())
        except (OSError, ValueError):
            continue
        if not isinstance(d, dict) or label not in str(d.get("label", "")):
            continue
        out += [(str(d.get("model")), r) for r in d.get("runs", []) if isinstance(r, dict) and r.get("trace")]
    return out


def replay(run: dict, fails: int, repeats: int) -> int | None:
    """The step number (1-based) at which the rule would have stopped this run, or None."""
    trace = [{"call": t["call"], "failed": t["failed"], "repeat": t["repeat"]} for t in run["trace"]]
    for n in range(1, len(trace) + 1):
        if no_progress(trace[:n], fails, repeats):
            return n
    return None


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", default="")
    ap.add_argument("logs", nargs="?", default=str(Path(__file__).resolve().parent.parent / "logs"))
    args = ap.parse_args()
    runs = load(Path(args.logs), args.label)
    for model in sorted({m for m, _ in runs}):
        mine = [r for m, r in runs if m == model]
        passed = [r for r in mine if r["passed"]]
        failed = [r for r in mine if not r["passed"]]
        capped = [r for r in mine if r["hit_cap"]]
        print(f"{model}: {len(mine)} runs, {len(passed)} passed, {len(failed)} not, {len(capped)} hit the cap")
        for fails, repeats in LIMITS:
            hits = [(r, replay(r, fails, repeats)) for r in mine]
            hits = [(r, n) for r, n in hits if n]
            wrong = [r for r, _ in hits if r["passed"]]
            saved = sum(r["steps"] - n for r, n in hits if not r["passed"])
            capped_hit = sum(1 for r, _ in hits if r["hit_cap"])
            print(f"  fails={fails} repeats={repeats}: stops {len(hits)} runs ({capped_hit} of {len(capped)} capped), "
                  f"{len(wrong)} of them passed, {saved} steps saved on the rest")
