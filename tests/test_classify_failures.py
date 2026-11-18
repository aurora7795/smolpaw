"""Tests for tests/classify_failures.py (#143). Run with: .venv/bin/python tests/test_classify_failures.py"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from classify_failures import arm_of, case_of, primary_reason  # noqa: E402

failed = 0


def check(name: str, cond: bool) -> None:
    global failed
    print(f"{'PASS' if cond else 'FAIL'}  {name}")
    failed += not cond


def run(**kw) -> dict:
    base = {"passed": False, "timed_out": False, "hit_cap": False, "stalled": None, "answer": "x", "error": "", "check": ""}
    return {**base, **kw}


EXPECT = [r"\b482\b"]
check("a passing run is 'pass'", primary_reason(run(passed=True), EXPECT) == "pass")
check("timeout comes before everything", primary_reason(run(timed_out=True, hit_cap=True, stalled="s"), EXPECT) == "timed out")
check("step cap comes before a stall", primary_reason(run(hit_cap=True, stalled="s"), EXPECT) == "step cap")
check("a stall names its rule", primary_reason(run(stalled="the same call failed 3 times in a row"), EXPECT)
      == "stalled: the same call failed 3 times in a row")
check("an empty answer is 'no answer'", primary_reason(run(answer="", error="boom"), EXPECT).startswith("no answer (boom"))
check("a failed check is reported with its reason and a normalised count",
      primary_reason(run(check="kept asking after being declined (4 declined actions)"), EXPECT)
      == "check: kept asking after being declined (n declined actions)")
check("an answer that misses a pattern names it", primary_reason(run(answer="no figure", check="files unchanged"), EXPECT)
      .startswith("answer missing"))
check("case_of reads the case from the label", case_of("readonly-append_log-sp136-qwen-default") == "append_log")
check("arm_of reads the arm from the file name", arm_of("logs/a-compact-final.json") == "compact-final" and arm_of("logs/a-default.json") == "default")
print(f"\n{failed} failed")
sys.exit(1 if failed else 0)
