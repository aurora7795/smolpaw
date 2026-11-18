"""
Sort the failed runs in eval logs by why they failed (#143).

For each log, every run that did not pass gets one primary reason, in this order: timed out, hit the step cap,
stalled (and which stall rule), no answer / error, the disk or declined-action check failed (and what it said),
or the answer did not match an expected pattern (and which). Runs that pass are counted. The answers behind the
"answer did not match" class are printed so a too-narrow pattern shows up as such.

Usage:
  .venv/bin/python tests/classify_failures.py 'logs/eval-*readonly-*sp136*.json' [--examples N]
"""

import argparse
import glob
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path


def primary_reason(run: dict, expects: list[str]) -> str:
    """One label for a run: 'pass' or the first failure reason that applies."""
    if run["passed"]:
        return "pass"
    if run.get("timed_out"):
        return "timed out"
    if run.get("hit_cap"):
        return "step cap"
    if run.get("stalled"):
        return f"stalled: {run['stalled']}"
    if not run.get("answer"):
        return f"no answer ({(run.get('error') or 'no error text')[:60]})"
    check = run.get("check") or ""
    if check and not check.startswith(("files unchanged", "ok")):
        return "check: " + re.sub(r"\(\d+ declined actions\)", "(n declined actions)", check)
    missed = [e for e in expects if not re.search(e, run["answer"], re.I)]
    if missed:
        return "answer missing: " + missed[0][:40]
    return "other"


def case_of(label: str) -> str:
    m = re.match(r"readonly-(\w+?)-sp\d+", label)
    return m.group(1) if m else label


def arm_of(path: str) -> str:
    return "compact-final" if path.endswith("compact-final.json") else "default"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pattern", help="glob of eval log files")
    ap.add_argument("--examples", type=int, default=2, help="answers to print per 'answer missing' class")
    args = ap.parse_args()
    files = sorted(glob.glob(args.pattern))
    if not files:
        sys.exit(f"no logs match {args.pattern}")
    tally: dict[tuple, Counter] = defaultdict(Counter)
    examples: dict[tuple, list[str]] = defaultdict(list)
    for f in files:
        d = json.loads(Path(f).read_text())
        for r in d["runs"]:
            reason = primary_reason(r, d["expect"])
            key = (d["model"], case_of(d["label"]), arm_of(f))
            tally[key][reason] += 1
            if reason.startswith("answer missing") and len(examples[(key, reason)]) < args.examples:
                examples[(key, reason)].append(r["answer"][:200].replace("\n", " "))
    for key in sorted(tally):
        model, case, arm = key
        total = sum(tally[key].values())
        print(f"\n{model} | {case} | {arm} ({total} runs)")
        for reason, n in tally[key].most_common():
            print(f"  {n:2d}  {reason}")
            for ex in examples.get((key, reason), []):
                print(f"        e.g. {ex!r}")
    print("\nTotals by model and arm")
    totals: dict[tuple, Counter] = defaultdict(Counter)
    for (model, _case, arm), c in tally.items():
        totals[(model, arm)].update(c)
    for key in sorted(totals):
        print(f"{key[0]} | {key[1]}: " + ", ".join(f"{n} {r}" for r, n in totals[key].most_common()))


if __name__ == "__main__":
    main()
