"""
The first-call prompt budget as a suite check (#110): fails when the system prompt or a tool schema grows past a
stated tolerance, with no model loaded.

Builds the generic agent as agent.py does (empty notes.md, only git-tracked skills, the default web search), writes the
first call's request the way tests/first_call_tokens.py does, and counts characters. Characters are an approximation of
tokens: the ratio in tests/prompt_budget.json was fitted to the measured figures for both models, and the check below
prints the error. To bump the budget on purpose after measuring (tests/first_call_tokens.py), run:

  .venv/bin/python tests/test_prompt_budget.py --update --measured qwen3.5:9b=4407 gemma4:e4b=4085
"""

import json
import os
import sys
import tempfile
from pathlib import Path

from smolagents.agents import SystemPromptStep, TaskStep
from smolagents.models import get_tool_json_schema

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ["SMOLPAW_SEARCH_PROVIDER"] = "ddgs"
import agent as agent_mod  # noqa: E402
import generic_tools as g  # noqa: E402
from tests.first_call_tokens import isolate  # noqa: E402

BUDGET = Path(__file__).parent / "prompt_budget.json"
failed = 0


def check(name: str, cond: bool) -> None:
    global failed
    print(f"{'PASS' if cond else 'FAIL'}  {name}")
    if not cond:
        failed += 1


def measure() -> dict:
    """Characters of the first call's request: the system prompt and each tool's schema, per piece."""
    isolate(Path(tempfile.mkdtemp()), "# notes\n")
    agent = agent_mod.build_agent("budget-check", backend="ollama")
    agent.memory.reset()
    agent.memory.system_prompt = SystemPromptStep(system_prompt=agent.initialize_system_prompt())
    agent.memory.steps.append(TaskStep(task="hello"))
    messages = agent.write_memory_to_messages()
    system_chars = sum(len(json.dumps(m, default=str)) for m in messages)
    tools = {t.name: len(json.dumps(get_tool_json_schema(t))) for t in agent.tools.values()}
    return {"system_chars": system_chars, "tool_chars": tools, "chars": system_chars + sum(tools.values())}


def main() -> None:
    now = measure()
    if "--update" in sys.argv:
        measured = dict(a.split("=") for a in sys.argv[sys.argv.index("--measured") + 1:]) if "--measured" in sys.argv else {}
        measured = {m: int(v) for m, v in measured.items()}
        old = json.loads(BUDGET.read_text()) if BUDGET.exists() else {}
        ratio = sum(measured.values()) / (len(measured) * now["chars"]) if measured else old.get("tokens_per_char", 0.25)
        BUDGET.write_text(json.dumps({
            "chars": now["chars"], "system_chars": now["system_chars"], "tool_chars": now["tool_chars"],
            "tokens_per_char": round(ratio, 5), "measured_tokens": measured or old.get("measured_tokens", {}),
            "tolerance": old.get("tolerance", 0.03), "budget_tokens": old.get("budget_tokens", 5000),
        }, indent=2) + "\n")
        print(f"wrote {BUDGET}: {now['chars']} chars, ratio {ratio:.5f}")
        return
    base = json.loads(BUDGET.read_text())
    tol, ratio = base["tolerance"], base["tokens_per_char"]
    est = now["chars"] * ratio
    check(f"first call is {now['chars']} characters (about {est:.0f} tokens), budget {base['budget_tokens']} tokens",
          est <= base["budget_tokens"])
    check(f"first call grew by at most {tol:.0%} over the recorded {base['chars']} characters",
          now["chars"] <= base["chars"] * (1 + tol))
    grown = {k: (base["tool_chars"].get(k, 0), v) for k, v in now["tool_chars"].items()
             if v > base["tool_chars"].get(k, 0) * (1 + tol) + 50}
    check("no tool schema grew by more than the tolerance (and 50 characters)", not grown)
    check("the system prompt did not grow by more than the tolerance",
          now["system_chars"] <= base["system_chars"] * (1 + tol) + 50)
    errs = {m: (base["chars"] * ratio - t) / t for m, t in base["measured_tokens"].items()}
    check("the characters-to-tokens ratio is within 10% of every measured figure: "
          + ", ".join(f"{m} {e:+.1%}" for m, e in errs.items()), all(abs(e) < 0.10 for e in errs.values()))
    if failed:
        print("\nBreakdown (characters; now vs recorded):")
        print(f"  system prompt and messages: {now['system_chars']} vs {base['system_chars']}")
        for k, v in sorted(now["tool_chars"].items(), key=lambda kv: -kv[1]):
            print(f"  {k}: {v} vs {base['tool_chars'].get(k, 'new')}")
        print("If the growth is deliberate, measure with tests/first_call_tokens.py and rerun with --update.")
    print(f"\n{failed} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
