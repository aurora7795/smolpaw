"""
Pool eval logs into arms and compare them (#132): pass counts, stalls, steps, tokens and seconds per arm and model, and a
one-sided Fisher exact p for "the first arm passes more than the second" per model. Reads the JSON files tests/eval.py
writes to logs/ (those with a `runs` list); no model is needed.

  .venv/bin/python tests/compare_runs.py --arm compact='logs/eval-*-compact*.json' --arm default='logs/eval-*-default*.json'
  .venv/bin/python tests/compare_runs.py --arm new=... --arm old=... --family housekeeping --alpha 0.1

An arm is a name and a glob (quote it). --family keeps only logs whose label contains the text, so one task family is
pooled and others are not. The first --arm is "A", the second "B"; with more arms every later one is compared with the
first. The p threshold (--alpha, default 0.1, the rule used for #125) is a default, and the sample sizes are printed
beside it so a reader can see how little a small n can show.
"""

import argparse
import glob
import json
import sys
from collections import defaultdict
from math import comb
from pathlib import Path

ROOT = Path(__file__).parent.parent


def fisher_greater(a_pass: int, a_n: int, b_pass: int, b_n: int) -> float:
    """One-sided Fisher exact p that arm A's pass rate is higher than B's (hypergeometric tail)."""
    total, passed = a_n + b_n, a_pass + b_pass
    denom = comb(total, a_n)
    return sum(comb(passed, k) * comb(total - passed, a_n - k)
               for k in range(a_pass, min(a_n, passed) + 1)) / denom


def load(pattern: str, family: str | None) -> list[dict]:
    """The eval logs matching a glob (relative to the repo root unless absolute), minus other shapes and other families."""
    pattern = pattern if Path(pattern).is_absolute() else str(ROOT / pattern)
    logs = []
    for f in sorted(glob.glob(pattern)):
        try:
            d = json.loads(Path(f).read_text())
        except (OSError, ValueError):
            continue
        if isinstance(d, dict) and isinstance(d.get("runs"), list) and (not family or family in d.get("label", "")):
            logs.append({**d, "file": Path(f).name})
    return logs


def pool(logs: list[dict]) -> dict[str, dict]:
    """Per model: runs, passes, stalls and sums of steps, input tokens and seconds across the logs."""
    out: dict[str, dict] = defaultdict(lambda: {"n": 0, "passed": 0, "stalled": 0, "steps": 0, "tokens": 0, "secs": 0.0, "files": 0})
    for d in logs:
        m = out[d.get("model", "?")]
        m["files"] += 1
        for r in d["runs"]:
            m["n"] += 1
            m["passed"] += bool(r.get("passed"))
            m["stalled"] += bool(r.get("stalled"))
            m["steps"] += r.get("steps", 0)
            m["tokens"] += r.get("input_tokens", 0)
            m["secs"] += r.get("wall_s", 0.0)
    return dict(out)


def row(name: str, model: str, m: dict) -> str:
    n = m["n"]
    return (f"{name:<12} {model:<22} {m['passed']:>3}/{n:<3} passed  {m['stalled']:>2} stalled  "
            f"{m['steps'] / n:>5.1f} steps  {m['tokens'] / n:>7.0f} in-tokens  {m['secs'] / n:>5.0f}s  ({m['files']} logs)")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--arm", action="append", required=True, metavar="NAME=GLOB", help="an arm: a name and a quoted glob of log files")
    ap.add_argument("--family", help="keep only logs whose label contains this text")
    ap.add_argument("--alpha", type=float, default=0.1, help="p threshold shown as the verdict (default 0.1)")
    args = ap.parse_args(argv)
    arms = []
    for spec in args.arm:
        name, _, pattern = spec.partition("=")
        if not pattern:
            ap.error(f"--arm needs NAME=GLOB, got {spec!r}")
        arms.append((name, pool(load(pattern, args.family))))
    models = sorted({m for _, pooled in arms for m in pooled})
    for model in models:
        print(f"\n{model}")
        for name, pooled in arms:
            print("  " + (row(name, model, pooled[model]) if model in pooled else f"{name:<12} no runs"))
        a_name, a = arms[0][0], arms[0][1].get(model)
        for b_name, b_pooled in arms[1:]:
            b = b_pooled.get(model)
            if not a or not b:
                continue
            p = fisher_greater(a["passed"], a["n"], b["passed"], b["n"])
            print(f"  Fisher exact, one-sided, {a_name} better than {b_name}: p={p:.3f} "
                  f"({a['passed']}/{a['n']} vs {b['passed']}/{b['n']}); {'below' if p < args.alpha else 'not below'} {args.alpha}")
    print("\nSmall n shows little: with 3 runs per arm no difference can reach p below 0.05.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
