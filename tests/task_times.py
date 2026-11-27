"""
Per-task time comparison between models, from the eval logs already in logs/ (#148): the wait a user actually feels for a
whole task, as opposed to tests/speed.py's per-step speed. Needs no model.

For each task (the eval prompt, with the port number of a fixture server blanked) that every listed model has at least
--min-n runs of, it prints per model: runs, pass rate, median seconds per run, median steps, seconds per step, and
"s per pass" (all seconds spent on the task divided by its passes), which charges a model for the time it burns failing.
A model that is quick per step but needs many steps, or fails and retries, shows up here and not in tests/speed.py.

  .venv/bin/python tests/task_times.py                                    # Gemma 4 E4B against Qwen 3.5 9B on Ollama
  .venv/bin/python tests/task_times.py --models gemma4:e4b qwen3.5:9b bonsai2-9b-q2 --min-n 5
  .venv/bin/python tests/task_times.py --glob 'logs/eval-2026111*.json' --label housekeeping

Caveats are printed with the table: the logs come from different days, code states, prompts and fixtures, so a task's runs
for two models are not always matched, and timed-out runs count at the seconds they were stopped at.
"""

import argparse
import re
import statistics
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from compare_runs import load  # noqa: E402


def task_key(prompt: str) -> str:
    """The prompt with fixture-server ports blanked and whitespace collapsed, so runs on different ports are one task."""
    return re.sub(r"\s+", " ", re.sub(r"(://[\w.\-]+):\d{2,5}", r"\1:PORT", prompt or "")).strip()


def collect(logs: list[dict], models: list[str], backend: str | None) -> dict[str, dict[str, list[dict]]]:
    """Runs grouped by task, then model, for the listed models (on `backend` when given)."""
    out: dict[str, dict[str, list[dict]]] = defaultdict(lambda: defaultdict(list))
    for d in logs:
        if d.get("model") not in models or not d.get("prompt") or (backend and d.get("backend") not in (backend, None)):
            continue  # a log with no recorded prompt cannot be matched to a task
        for r in d["runs"]:
            if isinstance(r.get("wall_s"), (int, float)) and r.get("steps"):
                out[task_key(d.get("prompt", ""))][d["model"]].append(r)
    return out


def summarise(runs: list[dict]) -> dict:
    passed = sum(bool(r.get("passed")) for r in runs)
    secs = sum(r["wall_s"] for r in runs)
    steps = sum(r["steps"] for r in runs)
    return {"n": len(runs), "pass": passed, "median_s": round(statistics.median(r["wall_s"] for r in runs), 1),
            "median_steps": statistics.median(r["steps"] for r in runs), "s_per_step": round(secs / steps, 1),
            "s_per_pass": round(secs / passed, 1) if passed else None}


def table(tasks: dict, models: list[str], min_n: int) -> tuple[list[str], dict]:
    """Markdown rows for tasks every model has min_n runs of, and how often each model had the lowest s per pass."""
    rows, wins = [], defaultdict(int)
    for key in sorted(tasks):
        by_model = tasks[key]
        if not all(len(by_model.get(m, [])) >= min_n for m in models):
            continue
        s = {m: summarise(by_model[m]) for m in models}
        scored = {m: v["s_per_pass"] for m, v in s.items() if v["s_per_pass"] is not None}
        if scored:
            wins[min(scored, key=scored.get)] += 1
        cells = " | ".join(f"{v['pass']}/{v['n']} | {v['median_s']} | {v['median_steps']:g} | {v['s_per_step']} | "
                           f"{v['s_per_pass'] if v['s_per_pass'] is not None else 'none passed'}" for v in s.values())
        rows.append(f"| {key[:70].replace('|', '/')} | {cells} |")
    return rows, dict(wins)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", nargs="+", default=["gemma4:e4b", "qwen3.5:9b"])
    ap.add_argument("--backend", default="ollama", help="'' for every backend")
    ap.add_argument("--glob", default="logs/eval-*.json")
    ap.add_argument("--label", help="keep only logs whose label contains this text")
    ap.add_argument("--min-n", type=int, default=3, help="runs per model a task needs to be listed")
    args = ap.parse_args()

    tasks = collect(load(args.glob, args.label), args.models, args.backend or None)
    rows, wins = table(tasks, args.models, args.min_n)
    head = " | ".join(f"{m}: pass | median s | steps | s/step | s per pass" for m in args.models)
    print(f"| Task | {head} |")
    print("|---|" + "---|" * (5 * len(args.models)))
    print("\n".join(rows))
    print(f"\n{len(rows)} tasks with at least {args.min_n} runs per model. Lowest s per pass: "
          + ", ".join(f"{m} {wins.get(m, 0)}" for m in args.models) + ".")
    print("Caveat: logs span different days, code states and prompts, so a task's runs are not always matched.")


if __name__ == "__main__":
    main()
